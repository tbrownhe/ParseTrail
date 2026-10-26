"""Fresh 2.0 SQLite profile for source evidence and authored account decisions.

This store has no reader or migration path for 1.x data. Source facts remain
immutable; imported observations start pending and unposted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from parsetrail.core.ledger import (
    AccountKind,
    Allocation,
    JournalEntry,
    LedgerAccount,
    LedgerError,
    Observation,
    Posting,
    validate_entry,
)
from parsetrail.core.source_evidence import (
    ActivityExportPayload,
    DateValue,
    MoneyValue,
    SourceEvidence,
    StatementAccount,
    StatementPayload,
)
from parsetrail.core.v2_builtin_categories import builtin_category, is_builtin_id_reserved
from parsetrail.core.v2_cash_source_policy import (
    HSA_CASH_PARSER,
    admitted_statement_scope,
    cash_accounting_description,
    cash_tracking_scope,
)
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_review_dates import permitted_posting_date, posting_date_candidate
from parsetrail.core.v2_settlements import (
    MAX_SETTLEMENT_PAYLOAD,
    ExpectedOwnedDestination,
    SettlementFee,
    SettlementPreview,
    TransferMovement,
    TransferSettlement,
    decode_settlement,
    fee_order,
    settlement_entries,
    settlement_payload,
    validate_movement,
    validate_settlement,
)
from parsetrail.core.v2_source_overlap import (
    OVERLAP_RULE,
    NearbySourceIndex,
    SourceOverlapCandidate,
    SourceOverlapInventory,
    SourceOverlapRow,
    nearby_source_pair,
    pairwise_source_group,
)
from parsetrail.core.v2_source_values import (
    SOURCE_VALUE_RULES,
    SourceValueProof,
    SourceValueReviewAnnotation,
    dated_value_conflicts,
    decode_source_value_proof,
    make_source_value_proof,
    proof_payload,
    source_value_candidate_id,
)

APPLICATION_ID = 0x50543230  # PT20
SCHEMA_VERSION = 20
TRACKING_SCOPES = {"account_total", "principal_component", "cash_component"}
CategoryPurpose = Literal["expense", "expense_refund", "income", "income_adjustment"]
CATEGORY_PURPOSE_KINDS = {
    "expense": "expense",
    "expense_refund": "expense",
    "income": "income",
    "income_adjustment": "income",
}


def _category_purposes(amount: int | None) -> tuple[CategoryPurpose, ...]:
    if type(amount) is not int or amount == 0:
        return ()
    return ("expense", "income_adjustment") if amount < 0 else ("expense_refund", "income")


def _category_purpose(amount: int, kind: str) -> CategoryPurpose:
    return next(purpose for purpose in _category_purposes(amount) if CATEGORY_PURPOSE_KINDS[purpose] == kind)


MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_DEFINITION_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
TABLE_COLUMNS = {
    "BindingCorrections": (
        ("correction_id", "INTEGER", 0, 1),
        ("source_sha256", "TEXT", 1, 0),
        ("target_payload", "TEXT", 1, 0),
        ("prior_payload", "TEXT", 1, 0),
        ("new_payload", "TEXT", 1, 0),
        ("invalidations_payload", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "Sources": (
        ("sha256", "TEXT", 0, 1),
        ("suffix", "TEXT", 1, 0),
        ("size", "INTEGER", 1, 0),
        ("content", "BLOB", 1, 0),
    ),
    "Definitions": (("sha256", "TEXT", 0, 1), ("size", "INTEGER", 1, 0), ("content", "BLOB", 1, 0)),
    "EvidenceSnapshots": (
        ("source_sha256", "TEXT", 0, 1),
        ("definition_sha256", "TEXT", 1, 0),
        ("size", "INTEGER", 1, 0),
        ("sha256", "TEXT", 1, 0),
        ("content", "BLOB", 1, 0),
    ),
    "SourceObservations": (
        ("row_id", "TEXT", 0, 1),
        ("source_sha256", "TEXT", 1, 0),
        ("source_account", "TEXT", 0, 0),
        ("source_account_form", "TEXT", 0, 0),
        ("row_role", "TEXT", 1, 0),
        ("date_role", "TEXT", 1, 0),
        ("observed_date", "TEXT", 1, 0),
        ("amount_minor", "INTEGER", 1, 0),
    ),
    "Accounts": (
        ("id", "TEXT", 0, 1),
        ("name", "TEXT", 1, 0),
        ("kind", "TEXT", 1, 0),
        ("currency", "TEXT", 1, 0),
        ("role", "TEXT", 1, 0),
        ("purpose", "TEXT", 1, 0),
        ("institution_key", "TEXT", 0, 0),
        ("full_account_number", "TEXT", 0, 0),
        ("tracking_scope", "TEXT", 1, 0),
    ),
    "CategoryBudgetRates": (
        ("category_id", "TEXT", 1, 1),
        ("effective_month", "TEXT", 1, 2),
        ("amount_minor", "INTEGER", 0, 0),
    ),
    "FileAccountAssertions": (
        ("source_sha256", "TEXT", 0, 1),
        ("ledger_account_id", "TEXT", 1, 0),
    ),
    "RowAccountAssignments": (
        ("row_id", "TEXT", 0, 1),
        ("ledger_account_id", "TEXT", 1, 0),
    ),
    "SourceAccountBindings": (
        ("source_sha256", "TEXT", 1, 1),
        ("source_identity", "TEXT", 1, 2),
        ("source_identity_form", "TEXT", 1, 3),
        ("ledger_account_id", "TEXT", 1, 0),
    ),
    "JournalEntries": (
        ("key", "TEXT", 0, 1),
        ("payload", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "JournalAllocations": (
        ("entry_key", "TEXT", 1, 1),
        ("row_id", "TEXT", 1, 2),
        ("amount_minor", "INTEGER", 1, 0),
    ),
    "JournalCorrections": (
        ("original_key", "TEXT", 0, 1),
        ("reversal_key", "TEXT", 1, 0),
        ("replacement_key", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "JournalRetirements": (
        ("original_key", "TEXT", 0, 1),
        ("reversal_key", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "StatementSourceReviews": (
        ("revision_id", "INTEGER", 0, 1),
        ("account_id", "TEXT", 1, 0),
        ("source_sha256", "TEXT", 1, 0),
        ("opening_origin", "TEXT", 1, 0),
        ("closing_origin", "TEXT", 1, 0),
        ("timing_confirmed", "INTEGER", 1, 0),
        ("posting_dates", "TEXT", 1, 0),
        ("source_reference", "TEXT", 1, 0),
        ("note", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
        ("source_identity", "TEXT", 1, 0),
        ("source_identity_form", "TEXT", 1, 0),
    ),
    "OpeningDecisions": (
        ("account_id", "TEXT", 0, 1),
        ("basis_sha256", "TEXT", 1, 0),
        ("amount_minor", "INTEGER", 0, 0),
        ("cutoff_date", "TEXT", 0, 0),
        ("entry_key", "TEXT", 0, 0),
        ("decision_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
        ("origin", "TEXT", 1, 0),
        ("state", "TEXT", 1, 0),
        ("tracking_scope", "TEXT", 1, 0),
        ("reference", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
    ),
    "OpeningDecisionRevisions": (
        ("revision_id", "INTEGER", 0, 1),
        ("account_id", "TEXT", 1, 0),
        ("prior_version", "TEXT", 1, 0),
        ("basis_sha256", "TEXT", 1, 0),
        ("amount_minor", "INTEGER", 0, 0),
        ("cutoff_date", "TEXT", 0, 0),
        ("entry_key", "TEXT", 0, 0),
        ("reason", "TEXT", 1, 0),
        ("decision_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
        ("origin", "TEXT", 1, 0),
        ("state", "TEXT", 1, 0),
        ("tracking_scope", "TEXT", 1, 0),
        ("reference", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
    ),
    "AccountDatedValues": (
        ("value_id", "INTEGER", 0, 1),
        ("account_id", "TEXT", 1, 0),
        ("value_date", "TEXT", 1, 0),
        ("amount_minor", "INTEGER", 1, 0),
        ("tracking_scope", "TEXT", 1, 0),
        ("reference", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("corrects_value_id", "INTEGER", 0, 0),
        ("request_basis", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
        ("origin", "TEXT", 1, 0),
        ("source_proof", "TEXT", 0, 0),
        ("allow_conflict", "INTEGER", 1, 0),
    ),
    "DatedValueWithdrawals": (
        ("withdrawal_id", "INTEGER", 0, 1),
        ("value_id", "INTEGER", 1, 0),
        ("prior_version", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "AccountLifecycleDecisions": (
        ("revision_id", "INTEGER", 0, 1),
        ("account_id", "TEXT", 1, 0),
        ("state", "TEXT", 1, 0),
        ("effective_date", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("prior_version", "TEXT", 0, 0),
        ("request_basis", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "SourceOverlapReviews": (
        ("revision_id", "INTEGER", 0, 1),
        ("left_row_id", "TEXT", 1, 0),
        ("right_row_id", "TEXT", 1, 0),
        ("decision", "TEXT", 1, 0),
        ("retained_row_id", "TEXT", 0, 0),
        ("basis_sha256", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "ReconciliationDecisions": (
        ("decision_id", "INTEGER", 0, 1),
        ("account_id", "TEXT", 1, 0),
        ("source_sha256", "TEXT", 1, 0),
        ("cutoff_date", "TEXT", 1, 0),
        ("rule", "TEXT", 1, 0),
        ("input_version", "TEXT", 1, 0),
        ("check_payload", "TEXT", 1, 0),
        ("journal_versions", "TEXT", 1, 0),
        ("snapshot_sha256", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "TransferEvents": (
        ("event_id", "TEXT", 0, 1),
        ("sequence", "INTEGER", 1, 0),
        ("outgoing_row_id", "TEXT", 1, 0),
        ("incoming_row_id", "TEXT", 0, 0),
        ("pair_payload", "TEXT", 1, 0),
        ("entry_versions", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "TransferEventActions": (
        ("event_id", "TEXT", 0, 1),
        ("action", "TEXT", 1, 0),
        ("replacement_event_id", "TEXT", 0, 0),
        ("request_basis", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "TransferPairReviews": (
        ("revision_id", "INTEGER", 0, 1),
        ("outgoing_row_id", "TEXT", 1, 0),
        ("incoming_row_id", "TEXT", 1, 0),
        ("pair_payload", "TEXT", 1, 0),
        ("context_sha256", "TEXT", 1, 0),
        ("decision", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "SourceInterpretationActions": (
        ("action_id", "INTEGER", 0, 1),
        ("row_id", "TEXT", 1, 0),
        ("entry_key", "TEXT", 1, 0),
        ("reversal_key", "TEXT", 1, 0),
        ("kind", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("original_sha256", "TEXT", 1, 0),
        ("inverse_sha256", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "PostedRepeatRepairs": (
        ("repair_id", "INTEGER", 0, 1),
        ("retained_row_id", "TEXT", 1, 0),
        ("redundant_row_id", "TEXT", 1, 0),
        ("retained_entry_key", "TEXT", 1, 0),
        ("redundant_entry_key", "TEXT", 1, 0),
        ("action_id", "INTEGER", 1, 0),
        ("review_revision_id", "INTEGER", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("retained_sha256", "TEXT", 1, 0),
        ("review_sha256", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
}
FOREIGN_KEYS = {
    "DatedValueWithdrawals": (("value_id", "AccountDatedValues", "value_id"),),
    "AccountDatedValues": (("corrects_value_id", "AccountDatedValues", "value_id"), ("account_id", "Accounts", "id")),
    "AccountLifecycleDecisions": (("account_id", "Accounts", "id"),),
    "BindingCorrections": (("source_sha256", "Sources", "sha256"),),
    "Sources": (),
    "Definitions": (),
    "EvidenceSnapshots": (("definition_sha256", "Definitions", "sha256"), ("source_sha256", "Sources", "sha256")),
    "SourceObservations": (("source_sha256", "Sources", "sha256"),),
    "Accounts": (),
    "CategoryBudgetRates": (("category_id", "Accounts", "id"),),
    "FileAccountAssertions": (("ledger_account_id", "Accounts", "id"), ("source_sha256", "Sources", "sha256")),
    "RowAccountAssignments": (
        ("ledger_account_id", "Accounts", "id"),
        ("row_id", "SourceObservations", "row_id"),
    ),
    "SourceAccountBindings": (
        ("ledger_account_id", "Accounts", "id"),
        ("source_sha256", "Sources", "sha256"),
    ),
    "JournalEntries": (),
    "JournalAllocations": (("row_id", "SourceObservations", "row_id"), ("entry_key", "JournalEntries", "key")),
    "JournalCorrections": (
        ("replacement_key", "JournalEntries", "key"),
        ("reversal_key", "JournalEntries", "key"),
        ("original_key", "JournalEntries", "key"),
    ),
    "JournalRetirements": (("reversal_key", "JournalEntries", "key"), ("original_key", "JournalEntries", "key")),
    "StatementSourceReviews": (("source_sha256", "Sources", "sha256"), ("account_id", "Accounts", "id")),
    "OpeningDecisions": (("entry_key", "JournalEntries", "key"), ("account_id", "Accounts", "id")),
    "OpeningDecisionRevisions": (("entry_key", "JournalEntries", "key"), ("account_id", "Accounts", "id")),
    "SourceOverlapReviews": (
        ("retained_row_id", "SourceObservations", "row_id"),
        ("right_row_id", "SourceObservations", "row_id"),
        ("left_row_id", "SourceObservations", "row_id"),
    ),
    "ReconciliationDecisions": (("source_sha256", "Sources", "sha256"), ("account_id", "Accounts", "id")),
    "TransferEvents": (
        ("incoming_row_id", "SourceObservations", "row_id"),
        ("outgoing_row_id", "SourceObservations", "row_id"),
    ),
    "TransferEventActions": (
        ("replacement_event_id", "TransferEvents", "event_id"),
        ("event_id", "TransferEvents", "event_id"),
    ),
    "TransferPairReviews": (
        ("incoming_row_id", "SourceObservations", "row_id"),
        ("outgoing_row_id", "SourceObservations", "row_id"),
    ),
    "SourceInterpretationActions": (
        ("reversal_key", "JournalEntries", "key"),
        ("entry_key", "JournalEntries", "key"),
        ("row_id", "SourceObservations", "row_id"),
    ),
    "PostedRepeatRepairs": (
        ("review_revision_id", "SourceOverlapReviews", "revision_id"),
        ("action_id", "SourceInterpretationActions", "action_id"),
        ("redundant_entry_key", "JournalEntries", "key"),
        ("retained_entry_key", "JournalEntries", "key"),
        ("redundant_row_id", "SourceObservations", "row_id"),
        ("retained_row_id", "SourceObservations", "row_id"),
    ),
}

IMMUTABLE_TABLES = (
    "DatedValueWithdrawals",
    "AccountDatedValues",
    "AccountLifecycleDecisions",
    "BindingCorrections",
    "Sources",
    "Definitions",
    "EvidenceSnapshots",
    "SourceObservations",
    "JournalEntries",
    "JournalAllocations",
    "JournalCorrections",
    "JournalRetirements",
    "StatementSourceReviews",
    "OpeningDecisions",
    "OpeningDecisionRevisions",
    "SourceOverlapReviews",
    "ReconciliationDecisions",
    "TransferEvents",
    "TransferEventActions",
    "TransferPairReviews",
    "SourceInterpretationActions",
    "PostedRepeatRepairs",
)

_INACTIVE_JOURNAL_SQL = (
    "SELECT original_key FROM JournalCorrections UNION SELECT reversal_key FROM JournalCorrections "
    "UNION SELECT original_key FROM JournalRetirements UNION SELECT reversal_key FROM JournalRetirements"
)
_UNSET_REVIEW_REVISION = object()


class ProfileFormatError(ValueError):
    """A profile or saved snapshot is unsupported or damaged."""


@dataclass(frozen=True)
class SavedImport:
    source: bytes
    definition: bytes
    evidence: SourceEvidence
    suffix: Literal[".csv", ".pdf"]


@dataclass(frozen=True)
class FinancialAccount:
    id: str
    name: str
    kind: Literal["asset", "liability"]
    institution_key: str
    full_account_number: str | None = None
    tracking_scope: Literal["account_total", "principal_component", "cash_component"] = "account_total"


@dataclass(frozen=True)
class CategoryAccount:
    id: str
    name: str
    kind: Literal["expense", "income"]


@dataclass(frozen=True)
class CategoryBudgetRate:
    category_id: str
    effective_month: date
    amount_minor: int | None


@dataclass(frozen=True)
class CategoryBudgetTarget:
    category_id: str
    name: str
    kind: Literal["expense", "income"]
    effective_month: date | None
    amount_minor: int | None


@dataclass(frozen=True)
class AccountBinding:
    row_id: str
    ledger_account_id: str | None
    basis: Literal["row", "file", "source", "automatic"] | None


@dataclass(frozen=True)
class SourceAccountBinding:
    source_identity: str
    source_identity_form: Literal["full", "last_four", "opaque"]
    ledger_account_id: str | None


@dataclass(frozen=True)
class BindingCorrectionTarget:
    source_sha256: str
    mode: Literal["source", "file", "rows"]
    source_identity: str | None = None
    source_identity_form: str | None = None
    row_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BindingCorrection:
    correction_id: int
    target: BindingCorrectionTarget
    prior_account_ids: tuple[str | None, ...]
    new_account_ids: tuple[str | None, ...]
    prior_bindings: tuple[AccountBinding, ...]
    new_bindings: tuple[AccountBinding, ...]
    invalidated_review_ids: tuple[int, ...]
    reason: str
    created_at: str
    version: str
    invalidated_transfer_review_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class BindingAffectedReviewRow:
    row_id: str
    source_sha256: str
    source_date: str | None
    description: str | None
    account_id: str | None
    account_name: str | None


@dataclass(frozen=True)
class BindingCorrectionSnapshot:
    target: BindingCorrectionTarget
    destination_account_id: str | None
    evidence: SourceEvidence
    accounts: tuple[FinancialAccount, ...]
    current_account_ids: tuple[str | None, ...]
    current_bindings: tuple[AccountBinding, ...]
    affected_row_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    ordinary_blockers: tuple[str, ...]
    opening_blocker_account_ids: tuple[str, ...]
    affected_review_pairs: tuple[tuple[str, str], ...]
    history: tuple[BindingCorrection, ...]
    basis_sha256: str
    affected_review_rows: tuple[BindingAffectedReviewRow, ...] = ()
    affected_transfer_review_ids: tuple[int, ...] = ()
    affected_transfer_reviews: tuple[TransferPairReview, ...] = ()
    source_value_anchors: tuple[ReviewedDatedValue, ...] = ()


@dataclass(frozen=True)
class EarliestSourceOpening:
    account_id: str
    account_name: str
    account_kind: Literal["asset", "liability"]
    bound_statement_sections: int
    earliest_period_start: date | None
    earliest_source_ids: tuple[str, ...]
    printed_opening_minor: int | None
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class StatementSourceReview:
    revision_id: int
    account_id: str
    source_sha256: str
    opening_origin: Literal["reported", "unestablished"]
    closing_origin: Literal["reported", "unestablished"]
    timing_confirmed: bool
    posting_dates: Literal["reported", "estimated", "unverified"]
    source_reference: str
    note: str
    source_identity: str = ""
    source_identity_form: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class OpeningDecision:
    account_id: str
    basis_sha256: str
    amount_minor: int | None
    cutoff_date: date | None
    entry_key: str | None
    stale: bool
    revision_id: int = 0
    version: str = ""
    origin: Literal["source", "manual"] = "source"
    state: Literal["active", "withdrawn"] = "active"
    tracking_scope: str = "account_total"
    reference: str = ""


@dataclass(frozen=True)
class OpeningDecisionHistoryRow:
    revision_id: int
    account_id: str
    basis_sha256: str
    amount_minor: int | None
    cutoff_date: date | None
    entry_key: str | None
    version: str
    prior_version: str | None
    reason: str
    created_at: str
    origin: Literal["source", "manual"] = "source"
    state: Literal["active", "withdrawn"] = "active"
    tracking_scope: str = "account_total"
    reference: str = ""
    request_basis_sha256: str = ""


@dataclass(frozen=True)
class ReviewedDatedValue:
    value_id: int
    account_id: str
    value_date: date
    amount_minor: int
    tracking_scope: str
    reference: str
    reason: str
    corrects_value_id: int | None
    created_at: str
    version: str
    origin: Literal["manual", "source"] = "manual"
    superseded_by_value_id: int | None = None
    source_proof: SourceValueProof | None = None
    withdrawal: DatedValueWithdrawal | None = None
    allow_conflict: bool = False
    source_review_changed: bool = False

    @property
    def state(self) -> Literal["active", "superseded", "withdrawn"]:
        return (
            "withdrawn"
            if self.withdrawal is not None
            else "superseded"
            if self.superseded_by_value_id is not None
            else "active"
        )


@dataclass(frozen=True)
class DatedValueWithdrawal:
    withdrawal_id: int
    value_id: int
    account_id: str
    prior_version: str
    reason: str
    created_at: str
    version: str


@dataclass(frozen=True)
class SourceClosingCandidate:
    candidate_id: str
    version: str
    account_id: str
    source_sha256: str
    source_identity: str
    source_identity_form: str
    value_date: date | None
    amount_minor: int | None
    tracking_scope: str
    proof: SourceValueProof | None
    blockers: tuple[str, ...]
    source_review: StatementSourceReview | None
    capture_verified: bool
    closing: MoneyValue | None = None
    endpoint: DateValue | None = None
    parser_id: str = ""
    definition_revision: str = ""
    sign_rule: str | None = None
    source_review_ambiguous: bool = False


@dataclass(frozen=True)
class AccountLifecycleDecision:
    revision_id: int
    account_id: str
    state: Literal["open", "closed"]
    effective_date: date
    reason: str
    prior_version: str | None
    created_at: str
    version: str


@dataclass(frozen=True)
class AccountOpeningBoundary:
    boundary_date: date
    kind: Literal["activity", "journal", "statement_start", "statement_end", "dated_value", "lifecycle"]
    allows_equal: bool
    source_sha256: str | None = None
    reference: str = ""


@dataclass(frozen=True)
class AccountAnchorSnapshot:
    account: FinancialAccount
    opening: OpeningDecision | None
    opening_history: tuple[OpeningDecisionHistoryRow, ...]
    dated_values: tuple[ReviewedDatedValue, ...]
    latest_dated_value: ReviewedDatedValue | None
    lifecycle: AccountLifecycleDecision | None
    lifecycle_history: tuple[AccountLifecycleDecision, ...]
    earliest_known_activity_date: date | None
    basis_sha256: str
    recorded_debit_minor: int
    position_debit_minor: int | None
    earliest_known_history_date: date | None = None
    opening_boundaries: tuple[AccountOpeningBoundary, ...] = ()
    source_value_candidates: tuple[SourceClosingCandidate, ...] = ()
    dated_value_withdrawals: tuple[DatedValueWithdrawal, ...] = ()
    value_status: Literal["missing", "known", "conflict"] = "missing"
    conflicting_dated_values: tuple[ReviewedDatedValue, ...] = ()
    current_dated_values: tuple[ReviewedDatedValue, ...] = ()


@dataclass(frozen=True)
class OpeningReviewSnapshot:
    candidate: EarliestSourceOpening
    reviews: tuple[StatementSourceReview, ...]
    decision: OpeningDecision | None
    basis_sha256: str
    history: tuple[OpeningDecisionHistoryRow, ...]
    sections: tuple[StatementCoverageRow, ...] = ()
    source_review_basis_sha256: str = ""


@dataclass(frozen=True)
class StatementCoverageRow:
    account_id: str
    account_name: str
    source_sha256: str
    parser_id: str
    period_start: date | None
    period_end: date
    period_start_provenance: Literal["observed", "derived", "unknown"]
    period_end_provenance: Literal["observed", "derived", "unknown"]
    relation_to_known_periods: Literal["first_known", "adjacent", "overlap", "gap", "unknown_start"]
    balance_scope: Literal["account_total", "cash_component", "principal_component"]
    opening: MoneyValue | None
    closing: MoneyValue | None
    independent_balance_verified: bool
    capture_verified: bool
    endpoint_comparison: Literal["not_adjacent", "unavailable", "ambiguous_prior", "same", "different"]
    compared_source_sha256: str | None
    source_identity: str = ""
    source_identity_form: str = ""


@dataclass(frozen=True)
class StatementSourceReviewSnapshot:
    account: FinancialAccount
    section: StatementCoverageRow
    saved: SavedImport
    payload: StatementPayload
    source_account: StatementAccount
    review: StatementSourceReview | None
    basis_sha256: str


@dataclass(frozen=True)
class StatementJournalComparison:
    account_id: str
    account_name: str
    account_kind: Literal["asset", "liability"]
    source_sha256: str
    period_start: date | None
    period_end: date
    printed_change_minor: int | None
    source_activity_change_minor: int | None
    journal_change_minor: int | None
    difference_minor: int | None
    activity_rows: int
    unallocated_rows: int
    unallocated_magnitude_minor: int
    allocations_outside_period: int
    outside_postings: int
    status: str


@dataclass(frozen=True)
class StatementReconciliationCheck:
    account_id: str
    account_name: str
    account_kind: Literal["asset", "liability"]
    source_sha256: str
    period_start: date | None
    period_end: date
    printed_opening_minor: int | None
    journal_opening_minor: int | None
    opening_difference_minor: int | None
    printed_closing_minor: int | None
    journal_closing_minor: int
    closing_difference_minor: int | None
    source_difference_minor: int | None
    exceptions: tuple[str, ...]
    coverage_warnings: tuple[str, ...]
    posted_interpretations_reviewed: bool
    reconciled: bool
    rule: str
    input_version: str
    balance_scope: str = "account_total"
    tracking_scope: str = "account_total"


@dataclass(frozen=True)
class ReconciliationDecision:
    decision_id: int
    account_id: str
    source_sha256: str
    cutoff_date: date
    rule: str
    input_version: str
    check: StatementReconciliationCheck
    journal_versions: tuple[tuple[str, str], ...]
    reason: str
    created_at: str
    stale: bool


@dataclass(frozen=True)
class ReconciliationSnapshot:
    checks: tuple[StatementReconciliationCheck, ...]
    history: tuple[ReconciliationDecision, ...]
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class CashActivityReviewRow:
    row_id: str
    date: str | None
    description: str
    amount_minor: int | None
    financial_account: str | None
    status: str
    entry_key: str | None = None
    category_id: str | None = None
    purpose: CategoryPurpose | None = None
    allowed_purposes: tuple[CategoryPurpose, ...] = ()
    tracking_scope: str | None = None
    accounting_description: str | None = None
    source_description_known: bool = True


@dataclass(frozen=True)
class CardPurchaseReviewRow:
    row_id: str
    source_date: str | None
    posting_candidate: str | None
    date_provenance: Literal["observed", "derived", "assumed", "unknown"] | None
    effective_date: str | None
    description: str | None
    amount_minor: int | None
    financial_account: str | None
    status: str
    entry_key: str | None = None
    category_id: str | None = None
    purpose: CategoryPurpose | None = None
    allowed_purposes: tuple[CategoryPurpose, ...] = ()


@dataclass(frozen=True)
class TransferCandidate:
    outgoing: TransferMovement
    incoming: TransferMovement
    kind: Literal["asset transfer", "card payment"]
    day_gap: int
    posting_allowed: bool


@dataclass(frozen=True)
class ReviewedTransferEvent:
    event_id: str
    pair: TransferCandidate | None
    entry_keys: tuple[str, ...]
    reason: str
    created_at: str
    version: str
    status: Literal["active", "cancelled", "replaced"]
    replacement_event_id: str | None
    action_reason: str | None
    settlement: TransferSettlement


@dataclass(frozen=True)
class TransferPairReview:
    revision_id: int
    pair: TransferCandidate
    decision: Literal["dismiss", "reopen"]
    reason: str
    created_at: str
    version: str
    context_current: bool


@dataclass(frozen=True)
class TransferReviewSnapshot:
    candidates: tuple[TransferCandidate, ...]
    events: tuple[ReviewedTransferEvent, ...]
    pair_reviews: tuple[TransferPairReview, ...]
    basis_sha256: str


@dataclass(frozen=True)
class SettlementReviewSnapshot:
    movements: tuple[TransferMovement, ...]
    events: tuple[ReviewedTransferEvent, ...]
    categories: tuple[CategoryAccount, ...]
    basis_sha256: str
    accounts: tuple[FinancialAccount, ...]


@dataclass(frozen=True)
class SourceInterpretationAction:
    action_id: int
    row_id: str
    entry_key: str
    reversal_key: str
    kind: Literal["withdraw", "repeat_repair"]
    reason: str
    created_at: str
    version: str


@dataclass(frozen=True)
class PostedRepeatRepair:
    repair_id: int
    retained_row_id: str
    redundant_row_id: str
    retained_entry_key: str
    redundant_entry_key: str
    reversal_key: str
    review_revision_id: int
    reason: str
    created_at: str
    version: str


@dataclass(frozen=True)
class SourceInterpretationSnapshot:
    source_sha256: str
    kind: Literal["cash", "card"]
    rows: tuple[CashActivityReviewRow | CardPurchaseReviewRow, ...]
    categories: tuple[CategoryAccount, ...]
    entries: tuple[JournalEntry, ...]
    history: tuple[SourceInterpretationAction, ...]
    basis_sha256: str
    preferences: V2Preferences | None
    statement: bool
    overlapping_source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReviewedCategoryTotal:
    category_id: str
    name: str
    amount_minor: int


@dataclass(frozen=True)
class ReviewedCategorySummary:
    start: date
    end: date
    kind: Literal["expense", "income"]
    categories: tuple[ReviewedCategoryTotal, ...]
    total_minor: int
    activity_rows_without_full_allocation: int
    sources_with_incomplete_activity: int
    excluded_unreviewed_entries: int


@dataclass(frozen=True)
class MonthlyBudgetRow:
    category_id: str
    name: str
    target_minor: int | None
    target_effective_month: date | None
    reviewed_spending_minor: int
    remaining_minor: int | None


@dataclass(frozen=True)
class MonthlyBudgetSummary:
    month: date
    categories: tuple[MonthlyBudgetRow, ...]
    total_target_minor: int | None
    total_reviewed_spending_minor: int
    activity_rows_without_full_allocation: int
    sources_with_incomplete_activity: int
    excluded_unreviewed_expense_entries: int


@dataclass(frozen=True)
class FinancialJournalMovement:
    account_id: str
    name: str
    kind: Literal["asset", "liability"]
    nonopening_change_minor: int
    opening_minor: int | None


@dataclass(frozen=True)
class FinancialJournalSummary:
    start: date
    end: date
    accounts: tuple[FinancialJournalMovement, ...]
    activity_rows_without_full_allocation: int
    sources_with_incomplete_activity: int
    excluded_unreviewed_financial_entries: int


@dataclass(frozen=True)
class AccountPositionHistoryRow:
    posting_date: date
    entry_key: str
    event_id: str
    description: str
    origin: str
    debit_change_minor: int
    recorded_debit_minor: int
    position_debit_minor: int | None
    correction_role: (
        Literal["original", "reversal", "replacement", "superseded_replacement", "retired", "retirement_reversal"]
        | None
    )


@dataclass(frozen=True)
class AccountPosition:
    account_id: str
    name: str
    kind: Literal["asset", "liability"]
    currency: str
    recorded_debit_minor: int
    position_debit_minor: int | None
    opening_status: Literal["missing", "withdrawn", "stale", "future", "conflict", "valid"]
    opening_cutoff: date | None
    opening_minor: int | None
    latest_source_cutoff: date | None
    latest_activity_date: date | None
    pending_activity_rows: int
    excluded_unreviewed_entries: int
    live_reconciled_cutoff: date | None
    coverage_warnings: tuple[str, ...]
    history: tuple[AccountPositionHistoryRow, ...]
    latest_saved_reconciled_cutoff: date | None = None
    current_saved_reconciled_cutoff: date | None = None
    tracking_scope: str = "account_total"
    opening_origin: str | None = None
    latest_dated_value: ReviewedDatedValue | None = None
    lifecycle: AccountLifecycleDecision | None = None
    closure_residual_debit_minor: int | None = None
    closure_residual_unknown: bool = False
    closure_residual_date: date | None = None
    value_status: Literal["missing", "known", "conflict"] = "missing"
    conflicting_dated_values: tuple[ReviewedDatedValue, ...] = ()
    current_dated_values: tuple[ReviewedDatedValue, ...] = ()


@dataclass(frozen=True)
class AccountPositionsSummary:
    as_of: date
    currency: str
    accounts: tuple[AccountPosition, ...]
    unbound_activity_rows: int
    activity_rows_without_full_allocation: int
    sources_with_incomplete_activity: int
    transfer_clearing_debit_minor: int


@dataclass(frozen=True)
class JournalExportAccount:
    id: str
    name: str
    kind: str


@dataclass(frozen=True)
class JournalExportCorrection:
    original_key: str
    reversal_key: str
    replacement_key: str
    reason: str
    created_at: str


@dataclass(frozen=True)
class JournalExportRetirement:
    original_key: str
    reversal_key: str
    reason: str
    created_at: str


@dataclass(frozen=True)
class JournalExportTransferAction:
    event_id: str
    action: str
    replacement_event_id: str | None
    reason: str
    created_at: str


@dataclass(frozen=True)
class ReviewedJournalExport:
    start: date
    end: date
    entries: tuple[JournalEntry, ...]
    accounts: tuple[JournalExportAccount, ...]
    source_rows: tuple[tuple[str, str], ...]
    corrections: tuple[JournalExportCorrection, ...]
    activity_rows_without_full_allocation: int
    sources_with_incomplete_activity: int
    excluded_unreviewed_entries: int
    excluded_opening_entries: int
    retirements: tuple[JournalExportRetirement, ...] = ()
    transfer_actions: tuple[JournalExportTransferAction, ...] = ()
    source_actions: tuple[SourceInterpretationAction, ...] = ()
    repeat_repairs: tuple[PostedRepeatRepair, ...] = ()
    settlements: tuple[ReviewedTransferEvent, ...] = ()
    dated_values: tuple[ReviewedDatedValue, ...] = ()
    dated_value_withdrawals: tuple[DatedValueWithdrawal, ...] = ()


BANK_CASH_STATEMENT_PARSERS = frozenset(
    {
        "happen_savings_line_pilot",
        "lendingclub_savings_line_pilot",
        "pdf_lendingclublus_202506",
        "pdf_occubank_201409",
        "pdf_wfbankper_202105",
        "wells_business_table_pilot",
    }
)
CARD_STATEMENT_PARSERS = frozenset(
    {
        "chase_card_line_pilot",
        "pdf_citicc_201505",
        "pdf_citicc_202506",
        "pdf_citicc_202511",
        "pdf_occucc_201904",
        "pdf_usbankreicc_201405",
        "synchrony_amazon_store_card",
    }
)


def _cash_review_scopes(evidence: SourceEvidence) -> dict[str, bool]:
    if isinstance(evidence.payload, ActivityExportPayload):
        return {row.row_id: True for row in evidence.payload.rows}
    if isinstance(evidence.payload, StatementPayload) and evidence.parser_id in BANK_CASH_STATEMENT_PARSERS | {
        HSA_CASH_PARSER
    }:
        return {
            row.row_id: account.balance_scope == cash_tracking_scope(evidence.parser_id)
            for account in evidence.payload.accounts
            for row in account.rows
        }
    return {}


def _card_review_scopes(evidence: SourceEvidence) -> dict[str, bool]:
    if isinstance(evidence.payload, StatementPayload) and evidence.parser_id in CARD_STATEMENT_PARSERS:
        return {
            row.row_id: account.balance_scope == "account_total"
            for account in evidence.payload.accounts
            for row in account.rows
        }
    return {}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rows(evidence: SourceEvidence):
    payload = evidence.payload
    if isinstance(payload, StatementPayload):
        return tuple(row for account in payload.accounts for row in account.rows)
    return payload.rows


def _journal_payload(entry: JournalEntry) -> str:
    return json.dumps(entry.payload(), sort_keys=True, separators=(",", ":"))


def _decode_journal(payload: str) -> JournalEntry:
    try:
        if type(payload) is not str:
            raise ValueError
        data = json.loads(payload)
        entry = JournalEntry(
            key=data["key"],
            event_id=data["event_id"],
            posting_date=date.fromisoformat(data["posting_date"]),
            description=data["description"],
            postings=tuple(
                Posting(
                    posting["account_id"],
                    posting["amount_minor"],
                    tuple(Allocation(**allocation) for allocation in posting["allocations"]),
                )
                for posting in data["postings"]
            ),
            origin=data["origin"],
            reviewed=data["reviewed"],
            reason=data["reason"],
        )
        if (
            any(
                type(value) is not str or not value
                for value in (entry.key, entry.event_id, entry.description, entry.origin)
            )
            or entry.origin not in {"imported", "manual", "opening", "reversal"}
            or type(entry.reviewed) is not bool
            or type(entry.reason) is not str
            or len(entry.postings) < 2
        ):
            raise ValueError
        for posting in entry.postings:
            if (
                type(posting.account_id) is not str
                or not posting.account_id
                or type(posting.amount_minor) is not int
                or not -(2**63) < posting.amount_minor < 2**63
                or posting.amount_minor == 0
                or any(
                    type(a.observation_id) is not str
                    or not a.observation_id
                    or type(a.amount_minor) is not int
                    or not -(2**63) < a.amount_minor < 2**63
                    or a.amount_minor == 0
                    for a in posting.allocations
                )
            ):
                raise ValueError
        if sum(posting.amount_minor for posting in entry.postings) != 0:
            raise ValueError
        return entry
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ProfileFormatError("journal_entry_invalid") from None


def _transfer_pair_payload(pair: TransferCandidate) -> str:
    return json.dumps(asdict(pair), sort_keys=True, separators=(",", ":"))


def _transfer_record_digest(*values) -> str:
    return _digest(json.dumps(values, sort_keys=True, separators=(",", ":")).encode())


def _transfer_pair_context(pair: TransferCandidate) -> str:
    return _transfer_record_digest(
        *(
            (m.row_id, m.source_sha256, m.account_id, m.account_kind, m.posting_date, m.date_provenance, m.amount_minor)
            for m in (pair.outgoing, pair.incoming)
        )
    )


def _decode_transfer_pair(payload: str) -> TransferCandidate:
    try:
        data = json.loads(payload)
        data["outgoing"] = TransferMovement(**data["outgoing"])
        data["incoming"] = TransferMovement(**data["incoming"])
        pair = TransferCandidate(**data)
        for movement in (pair.outgoing, pair.incoming):
            validate_movement(movement)
            if (
                any(
                    type(value) is not str or not value
                    for value in (
                        movement.row_id,
                        movement.source_sha256,
                        movement.account_id,
                        movement.account_name,
                        movement.posting_date,
                        movement.description,
                    )
                )
                or re.fullmatch(r"[0-9a-f]{64}", movement.source_sha256) is None
                or movement.account_kind not in {"asset", "liability"}
                or type(movement.amount_minor) is not int
                or movement.amount_minor == 0
                or movement.date_provenance not in {"observed", "derived", "assumed"}
                or type(movement.date_allowed) is not bool
                or (not movement.date_allowed and movement.date_provenance != "assumed")
            ):
                raise ValueError
            date.fromisoformat(movement.posting_date)
        gap = abs(
            (date.fromisoformat(pair.outgoing.posting_date) - date.fromisoformat(pair.incoming.posting_date)).days
        )
        if (
            pair.outgoing.account_kind != "asset"
            or pair.outgoing.amount_minor >= 0
            or pair.incoming.amount_minor != -pair.outgoing.amount_minor
            or pair.outgoing.account_id == pair.incoming.account_id
            or pair.outgoing.row_id == pair.incoming.row_id
            or pair.kind != ("card payment" if pair.incoming.account_kind == "liability" else "asset transfer")
            or type(pair.day_gap) is not int
            or pair.day_gap != gap
            or gap > 31
            or type(pair.posting_allowed) is not bool
            or pair.posting_allowed != (pair.outgoing.date_allowed and pair.incoming.date_allowed)
        ):
            raise ValueError
        return pair
    except (TypeError, ValueError, KeyError, RecursionError):
        raise ProfileFormatError("transfer_history_integrity") from None


def _reconciliation_payload(check: StatementReconciliationCheck) -> str:
    payload = asdict(check)
    payload["period_start"] = check.period_start.isoformat() if check.period_start is not None else None
    payload["period_end"] = check.period_end.isoformat()
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


RECONCILIATION_WARNINGS = frozenset(
    {
        "confirmed_repeated_supporting_evidence",
        "cross_source_occurrence_review_pending",
        "source_capture_incomplete",
        "overlapping_bound_source_periods",
        "calendar_gap_before_source",
        "adjacent_printed_endpoints_differ",
    }
)


def _reconciliation_snapshot_digest(check_payload: str, journal_versions: str) -> str:
    """Detect accidental snapshot changes; this is not database authentication."""
    canonical = json.dumps(
        {"check": json.loads(check_payload), "journal_versions": json.loads(journal_versions)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return _digest(canonical.encode())


def _decode_reconciliation_check(payload: str) -> StatementReconciliationCheck:
    try:
        data = json.loads(payload)
        for field in ("account_id", "account_name", "source_sha256", "rule", "input_version"):
            if type(data[field]) is not str or not data[field]:
                raise ValueError
        if data["account_kind"] not in {"asset", "liability"}:
            raise ValueError
        legacy_scope = data["rule"] in {"v2-statement-reconciliation-3", "v2-statement-reconciliation-4"}
        for field in ("balance_scope", "tracking_scope"):
            if field not in data and legacy_scope:
                data[field] = "account_total"
            if data.get(field) not in TRACKING_SCOPES:
                raise ValueError
        if data["rule"] == "v2-statement-reconciliation-5" and data["balance_scope"] != data["tracking_scope"]:
            raise ValueError
        for field in (
            "printed_opening_minor",
            "journal_opening_minor",
            "opening_difference_minor",
            "printed_closing_minor",
            "closing_difference_minor",
            "source_difference_minor",
        ):
            if data[field] is not None and type(data[field]) is not int:
                raise ValueError
        if type(data["journal_closing_minor"]) is not int:
            raise ValueError
        for field in ("posted_interpretations_reviewed", "reconciled"):
            if type(data[field]) is not bool:
                raise ValueError
        for field in ("exceptions", "coverage_warnings"):
            if type(data[field]) is not list or any(type(item) is not str for item in data[field]):
                raise ValueError
            data[field] = tuple(data[field])
        data["period_start"] = date.fromisoformat(data["period_start"]) if data["period_start"] is not None else None
        data["period_end"] = date.fromisoformat(data["period_end"])
        check = StatementReconciliationCheck(**data)
        if (
            not check.reconciled
            or not check.posted_interpretations_reviewed
            or check.exceptions
            or check.period_start is None
            or check.period_start >= check.period_end
            or check.printed_opening_minor is None
            or check.journal_opening_minor != check.printed_opening_minor
            or check.printed_closing_minor != check.journal_closing_minor
            or check.opening_difference_minor != 0
            or check.closing_difference_minor != 0
            or check.source_difference_minor != 0
            or not set(check.coverage_warnings) <= RECONCILIATION_WARNINGS
            or len(set(check.coverage_warnings)) != len(check.coverage_warnings)
            or re.fullmatch(r"[0-9a-f]{64}", check.source_sha256) is None
            or re.fullmatch(r"[0-9a-f]{64}", check.input_version) is None
        ):
            raise ValueError
        return check
    except (KeyError, TypeError, ValueError):
        raise ProfileFormatError("saved_reconciliation_integrity") from None


def _check_format(connection: sqlite3.Connection) -> None:
    try:
        marker = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if marker != APPLICATION_ID or version != SCHEMA_VERSION:
            raise ProfileFormatError("unsupported_profile_format")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != TABLE_COLUMNS.keys():
            raise ProfileFormatError("profile_schema_missing")
        for table, columns in TABLE_COLUMNS.items():
            actual_columns = tuple(
                (row[1], row[2], row[3], row[5]) for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if actual_columns != columns:
                raise ProfileFormatError("profile_schema_mismatch")
            actual_foreign_keys = tuple(
                (row[3], row[2], row[4]) for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            )
            if actual_foreign_keys != FOREIGN_KEYS[table]:
                raise ProfileFormatError("profile_schema_mismatch")
        expected_triggers = {
            f"immutable_{table}_{action}" for table in IMMUTABLE_TABLES for action in ("update", "delete")
        }
        triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if triggers != expected_triggers:
            raise ProfileFormatError("profile_schema_mismatch")
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ProfileFormatError("profile_integrity")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ProfileFormatError("profile_integrity")
    except sqlite3.DatabaseError:
        raise ProfileFormatError("profile_integrity") from None


class V2ProfileStore:
    """Open only a marked 2.0 profile; use as a context manager."""

    def __init__(self, connection: sqlite3.Connection, *, read_only: bool):
        self.connection = connection
        self.read_only = read_only
        self._transfer_mutating = False
        self._source_interpretation_mutating = False
        self._account_anchors_mutating = False

    @classmethod
    def create(cls, path: Path) -> V2ProfileStore:
        path = path.resolve()
        with path.open("xb"):
            pass
        connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(f"""
                BEGIN IMMEDIATE;
                PRAGMA application_id={APPLICATION_ID};
                PRAGMA user_version={SCHEMA_VERSION};
                CREATE TABLE Sources (
                    sha256 TEXT PRIMARY KEY, suffix TEXT NOT NULL CHECK(suffix IN ('.csv','.pdf')),
                    size INTEGER NOT NULL, content BLOB NOT NULL
                );
                CREATE TABLE Definitions (
                    sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL, content BLOB NOT NULL
                );
                CREATE TABLE EvidenceSnapshots (
                    source_sha256 TEXT PRIMARY KEY REFERENCES Sources(sha256),
                    definition_sha256 TEXT NOT NULL REFERENCES Definitions(sha256),
                    size INTEGER NOT NULL, sha256 TEXT NOT NULL, content BLOB NOT NULL
                );
                CREATE TABLE SourceObservations (
                    row_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL REFERENCES Sources(sha256),
                    source_account TEXT,
                    source_account_form TEXT CHECK(source_account_form IN ('full','last_four','opaque')),
                    row_role TEXT NOT NULL CHECK(row_role IN ('activity','period_summary','header_charge')),
                    date_role TEXT NOT NULL CHECK(date_role IN ('posting_date','activity_date','statement_period_end')),
                    observed_date TEXT NOT NULL, amount_minor INTEGER NOT NULL,
                    CHECK((source_account IS NULL) = (source_account_form IS NULL))
                );
                CREATE TABLE Accounts (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('asset','liability','equity','income','expense')),
                    currency TEXT NOT NULL CHECK(currency='USD'),
                    role TEXT NOT NULL CHECK(role IN ('financial','category','internal')),
                    purpose TEXT NOT NULL CHECK(purpose IN ('normal','clearing','opening_equity','suspense')),
                    institution_key TEXT, full_account_number TEXT,
                    tracking_scope TEXT NOT NULL DEFAULT 'account_total' CHECK(tracking_scope IN ('account_total','principal_component','cash_component')),
                    CHECK(
                        (role='financial' AND kind IN ('asset','liability') AND purpose='normal'
                            AND institution_key IS NOT NULL)
                        OR (role='category' AND kind IN ('income','expense') AND purpose='normal'
                            AND institution_key IS NULL AND full_account_number IS NULL)
                        OR (role='internal' AND institution_key IS NULL AND full_account_number IS NULL)
                    )
                );
                CREATE TABLE CategoryBudgetRates (
                    category_id TEXT NOT NULL REFERENCES Accounts(id),
                    effective_month TEXT NOT NULL,
                    amount_minor INTEGER CHECK(amount_minor>=0),
                    PRIMARY KEY(category_id,effective_month)
                );
                CREATE TABLE FileAccountAssertions (
                    source_sha256 TEXT PRIMARY KEY REFERENCES Sources(sha256),
                    ledger_account_id TEXT NOT NULL REFERENCES Accounts(id)
                );
                CREATE TABLE RowAccountAssignments (
                    row_id TEXT PRIMARY KEY REFERENCES SourceObservations(row_id),
                    ledger_account_id TEXT NOT NULL REFERENCES Accounts(id)
                );
                CREATE TABLE SourceAccountBindings (
                    source_sha256 TEXT NOT NULL REFERENCES Sources(sha256),
                    source_identity TEXT NOT NULL,
                    source_identity_form TEXT NOT NULL CHECK(source_identity_form IN ('full','last_four','opaque')),
                    ledger_account_id TEXT NOT NULL REFERENCES Accounts(id),
                    PRIMARY KEY(source_sha256,source_identity,source_identity_form)
                );
                CREATE TABLE JournalEntries (
                    key TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE JournalAllocations (
                    entry_key TEXT NOT NULL REFERENCES JournalEntries(key),
                    row_id TEXT NOT NULL REFERENCES SourceObservations(row_id),
                    amount_minor INTEGER NOT NULL CHECK(amount_minor<>0),
                    PRIMARY KEY(entry_key,row_id)
                );
                CREATE TABLE JournalCorrections (
                    original_key TEXT PRIMARY KEY REFERENCES JournalEntries(key),
                    reversal_key TEXT NOT NULL UNIQUE REFERENCES JournalEntries(key),
                    replacement_key TEXT NOT NULL UNIQUE REFERENCES JournalEntries(key),
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE JournalRetirements (
                    original_key TEXT PRIMARY KEY REFERENCES JournalEntries(key),
                    reversal_key TEXT NOT NULL UNIQUE REFERENCES JournalEntries(key),
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE StatementSourceReviews (
                    revision_id INTEGER PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES Accounts(id),
                    source_sha256 TEXT NOT NULL REFERENCES Sources(sha256),
                    opening_origin TEXT NOT NULL CHECK(opening_origin IN ('reported','unestablished')),
                    closing_origin TEXT NOT NULL CHECK(closing_origin IN ('reported','unestablished')),
                    timing_confirmed INTEGER NOT NULL CHECK(timing_confirmed IN (0,1)),
                    posting_dates TEXT NOT NULL CHECK(posting_dates IN ('reported','estimated','unverified')),
                    source_reference TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    source_identity TEXT NOT NULL,
                    source_identity_form TEXT NOT NULL CHECK(source_identity_form IN ('full','last_four','opaque'))
                );
                CREATE TABLE OpeningDecisions (
                    account_id TEXT PRIMARY KEY REFERENCES Accounts(id),
                    basis_sha256 TEXT NOT NULL,
                    amount_minor INTEGER,
                    cutoff_date TEXT,
                    entry_key TEXT REFERENCES JournalEntries(key),
                    decision_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    origin TEXT NOT NULL, state TEXT NOT NULL, tracking_scope TEXT NOT NULL,
                    reference TEXT NOT NULL, reason TEXT NOT NULL, request_basis TEXT NOT NULL
                );
                CREATE TABLE OpeningDecisionRevisions (
                    revision_id INTEGER PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES Accounts(id),
                    prior_version TEXT NOT NULL,
                    basis_sha256 TEXT NOT NULL, amount_minor INTEGER,
                    cutoff_date TEXT, entry_key TEXT REFERENCES JournalEntries(key),
                    reason TEXT NOT NULL,
                    decision_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    origin TEXT NOT NULL, state TEXT NOT NULL, tracking_scope TEXT NOT NULL,
                    reference TEXT NOT NULL, request_basis TEXT NOT NULL,
                    UNIQUE(account_id,prior_version)
                );
                CREATE TABLE AccountDatedValues (
                    value_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES Accounts(id),
                    value_date TEXT NOT NULL, amount_minor INTEGER NOT NULL, tracking_scope TEXT NOT NULL,
                    reference TEXT NOT NULL, reason TEXT NOT NULL,
                    corrects_value_id INTEGER UNIQUE REFERENCES AccountDatedValues(value_id),
                    request_basis TEXT NOT NULL, record_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    origin TEXT NOT NULL, source_proof TEXT,
                    allow_conflict INTEGER NOT NULL CHECK(allow_conflict IN (0,1))
                );
                CREATE TABLE DatedValueWithdrawals (
                    withdrawal_id INTEGER PRIMARY KEY, value_id INTEGER NOT NULL UNIQUE REFERENCES AccountDatedValues(value_id),
                    prior_version TEXT NOT NULL, request_basis TEXT NOT NULL, reason TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE AccountLifecycleDecisions (
                    revision_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES Accounts(id),
                    state TEXT NOT NULL, effective_date TEXT NOT NULL, reason TEXT NOT NULL, prior_version TEXT,
                    request_basis TEXT NOT NULL, record_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE SourceOverlapReviews (
                    revision_id INTEGER PRIMARY KEY,
                    left_row_id TEXT NOT NULL REFERENCES SourceObservations(row_id),
                    right_row_id TEXT NOT NULL REFERENCES SourceObservations(row_id),
                    decision TEXT NOT NULL CHECK(decision IN ('pending','distinct','repeat')),
                    retained_row_id TEXT REFERENCES SourceObservations(row_id),
                    basis_sha256 TEXT NOT NULL, reason TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    CHECK(left_row_id < right_row_id),
                    CHECK((decision='repeat' AND retained_row_id IS NOT NULL
                        AND retained_row_id IN (left_row_id,right_row_id))
                        OR (decision<>'repeat' AND retained_row_id IS NULL))
                );
                CREATE TABLE ReconciliationDecisions (
                    decision_id INTEGER PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES Accounts(id),
                    source_sha256 TEXT NOT NULL REFERENCES Sources(sha256),
                    cutoff_date TEXT NOT NULL, rule TEXT NOT NULL, input_version TEXT NOT NULL,
                    check_payload TEXT NOT NULL, journal_versions TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    UNIQUE(account_id,source_sha256,rule,input_version)
                );
                CREATE TABLE TransferEvents (
                    event_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE,
                    outgoing_row_id TEXT NOT NULL REFERENCES SourceObservations(row_id),
                    incoming_row_id TEXT REFERENCES SourceObservations(row_id),
                    pair_payload TEXT NOT NULL, entry_versions TEXT NOT NULL,
                    reason TEXT NOT NULL, request_basis TEXT NOT NULL, record_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE TransferEventActions (
                    event_id TEXT PRIMARY KEY REFERENCES TransferEvents(event_id),
                    action TEXT NOT NULL CHECK(action IN ('cancel','replace')),
                    replacement_event_id TEXT REFERENCES TransferEvents(event_id),
                    request_basis TEXT NOT NULL, reason TEXT NOT NULL, record_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    CHECK((action='cancel' AND replacement_event_id IS NULL)
                        OR (action='replace' AND replacement_event_id IS NOT NULL))
                );
                CREATE TABLE TransferPairReviews (
                    revision_id INTEGER PRIMARY KEY,
                    outgoing_row_id TEXT NOT NULL REFERENCES SourceObservations(row_id),
                    incoming_row_id TEXT NOT NULL REFERENCES SourceObservations(row_id),
                    pair_payload TEXT NOT NULL, context_sha256 TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('dismiss','reopen')),
                    request_basis TEXT NOT NULL, reason TEXT NOT NULL, record_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE SourceInterpretationActions (
                    action_id INTEGER PRIMARY KEY,
                    row_id TEXT NOT NULL REFERENCES SourceObservations(row_id),
                    entry_key TEXT NOT NULL UNIQUE REFERENCES JournalEntries(key),
                    reversal_key TEXT NOT NULL UNIQUE REFERENCES JournalEntries(key),
                    kind TEXT NOT NULL CHECK(kind IN ('withdraw','repeat_repair')),
                    request_basis TEXT NOT NULL, original_sha256 TEXT NOT NULL, inverse_sha256 TEXT NOT NULL,
                    reason TEXT NOT NULL, record_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE PostedRepeatRepairs (
                    repair_id INTEGER PRIMARY KEY,
                    retained_row_id TEXT NOT NULL REFERENCES SourceObservations(row_id),
                    redundant_row_id TEXT NOT NULL REFERENCES SourceObservations(row_id),
                    retained_entry_key TEXT NOT NULL REFERENCES JournalEntries(key),
                    redundant_entry_key TEXT NOT NULL REFERENCES JournalEntries(key),
                    action_id INTEGER NOT NULL UNIQUE REFERENCES SourceInterpretationActions(action_id),
                    review_revision_id INTEGER NOT NULL UNIQUE REFERENCES SourceOverlapReviews(revision_id),
                    request_basis TEXT NOT NULL, retained_sha256 TEXT NOT NULL, review_sha256 TEXT NOT NULL,
                    reason TEXT NOT NULL, record_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE BindingCorrections (
                    correction_id INTEGER PRIMARY KEY,
                    source_sha256 TEXT NOT NULL REFERENCES Sources(sha256),
                    target_payload TEXT NOT NULL, prior_payload TEXT NOT NULL, new_payload TEXT NOT NULL,
                    invalidations_payload TEXT NOT NULL, request_basis TEXT NOT NULL,
                    reason TEXT NOT NULL, record_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                COMMIT;
            """)
            for table in IMMUTABLE_TABLES:
                for action in ("UPDATE", "DELETE"):
                    connection.execute(
                        f"CREATE TRIGGER immutable_{table}_{action.lower()} "
                        f"BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable evidence'); END"
                    )
            _check_format(connection)
            return cls(connection, read_only=False)
        except BaseException:
            connection.close()
            path.unlink(missing_ok=True)
            raise

    @classmethod
    def open(cls, path: Path, *, read_only: bool = False) -> V2ProfileStore:
        path = path.resolve()
        if not path.is_file():
            raise ProfileFormatError("profile_missing")
        try:
            checked = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
            try:
                checked.execute("PRAGMA query_only=ON")
                _check_format(checked)
            finally:
                checked.close()
            mode = "ro" if read_only else "rw"
            connection = sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, isolation_level=None)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                if read_only:
                    connection.execute("PRAGMA query_only=ON")
                _check_format(connection)
                return cls(connection, read_only=read_only)
            except BaseException:
                connection.close()
                raise
        except sqlite3.DatabaseError:
            raise ProfileFormatError("profile_integrity") from None

    @classmethod
    def snapshot_to(cls, source_path: Path, destination_path: Path) -> Path:
        """Publish a verified SQLite snapshot at a new path without overwriting files."""
        requested = destination_path.expanduser()
        if requested.is_symlink():
            raise ProfileFormatError("profile_destination_exists")
        destination = requested.resolve()
        if destination.exists():
            raise ProfileFormatError("profile_destination_exists")
        if not destination.parent.is_dir():
            raise ProfileFormatError("profile_destination_parent_missing")
        with cls.open(source_path, read_only=True) as source:
            descriptor, partial_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
            )
            os.close(descriptor)
            partial = Path(partial_name)
            try:
                target = sqlite3.connect(partial)
                try:
                    source.connection.backup(target)
                finally:
                    target.close()
                with cls.open(partial, read_only=True) as verified:
                    if verified.connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                        raise ProfileFormatError("profile_snapshot_integrity")
                    for source_id in verified.source_ids():
                        verified.load_import(source_id)
                    verified._validate_journal_retirements()
                    for account in verified.financial_accounts():
                        verified.opening_decision_history(account.id)
                    verified._validate_transfer_history()
                    verified._validate_source_interpretation_history()
                    verified._read_binding_corrections()
                    verified._validate_common_journal_read()
                    verified._source_overlap_index()
                    verified._reconciliation_history(None)
                try:
                    os.link(partial, destination)
                except FileExistsError:
                    raise ProfileFormatError("profile_destination_exists") from None
                return destination
            finally:
                partial.unlink(missing_ok=True)

    def __enter__(self) -> V2ProfileStore:
        return self

    def __exit__(self, *_args) -> None:
        self.connection.close()

    def _require_writable(self) -> None:
        if self.read_only:
            raise ProfileFormatError("profile_read_only")

    def add_financial_account(self, account: FinancialAccount) -> None:
        """Create one user-authored financial account before any source binding."""
        self._require_writable()
        self._validate_builtin_categories()
        name, institution_key, full_number = self._financial_account_values(account)
        self.connection.execute(
            "INSERT INTO Accounts VALUES (?,?,?,'USD','financial','normal',?,?,?)",
            (account.id, name, account.kind, institution_key, full_number, account.tracking_scope),
        )

    @staticmethod
    def _financial_account_values(account: FinancialAccount) -> tuple[str, str, str | None]:
        if (
            not isinstance(account, FinancialAccount)
            or type(account.id) is not str
            or is_builtin_id_reserved(account.id)
            or account.id.startswith("internal:")
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,79}", account.id) is None
            or type(account.name) is not str
            or not 0 < len(account.name.strip()) <= 200
            or account.kind not in {"asset", "liability"}
            or type(account.tracking_scope) is not str
            or account.tracking_scope not in TRACKING_SCOPES
            or type(account.institution_key) is not str
            or re.fullmatch(r"[a-z][a-z0-9_-]{2,79}", account.institution_key) is None
            or (
                account.full_account_number is not None
                and (
                    type(account.full_account_number) is not str
                    or not 0 < len(account.full_account_number.strip()) <= 80
                )
            )
        ):
            raise ProfileFormatError("invalid_financial_account")
        return (
            account.name.strip(),
            account.institution_key,
            account.full_account_number.strip() if account.full_account_number is not None else None,
        )

    def update_financial_account(self, account: FinancialAccount) -> None:
        """Edit account identity labels while preserving its ledger class and ID."""
        self._require_writable()
        name, institution_key, full_number = self._financial_account_values(account)
        if self.connection.in_transaction:
            raise ProfileFormatError("account_anchor_requires_committed_snapshot")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            current = self.connection.execute(
                "SELECT kind,tracking_scope FROM Accounts WHERE id=? AND role='financial'", (account.id,)
            ).fetchone()
            if current is None:
                raise ProfileFormatError("financial_account_missing")
            if current[0] != account.kind:
                raise ProfileFormatError("financial_account_kind_immutable")
            if current[1] != account.tracking_scope and self.financial_account_scope_locked(account.id):
                raise ProfileFormatError("financial_account_scope_locked")
            self.connection.execute(
                "UPDATE Accounts SET name=?,institution_key=?,full_account_number=?,tracking_scope=? WHERE id=? AND role='financial'",
                (name, institution_key, full_number, account.tracking_scope, account.id),
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def financial_accounts(self) -> tuple[FinancialAccount, ...]:
        self._validate_builtin_categories()
        return tuple(
            FinancialAccount(*row)
            for row in self.connection.execute(
                "SELECT id,name,kind,institution_key,full_account_number,tracking_scope FROM Accounts "
                "WHERE role='financial' ORDER BY name,id"
            )
        )

    def financial_account_scope_locked(self, account_id: str) -> bool:
        """One policy for metadata editing and interpretation-history scope locks."""
        self._require_financial_account(account_id)
        if any(
            any(p.account_id == account_id for p in _decode_journal(payload).postings)
            for (payload,) in self.connection.execute("SELECT payload FROM JournalEntries")
        ):
            return True
        for table in ("OpeningDecisions", "StatementSourceReviews", "AccountDatedValues", "AccountLifecycleDecisions"):
            if self.connection.execute(f"SELECT 1 FROM {table} WHERE account_id=? LIMIT 1", (account_id,)).fetchone():
                return True
        if any(
            account_id in record.prior_account_ids or account_id in record.new_account_ids
            for record in self._read_binding_corrections()
        ):
            return True
        reviewed_rows = {
            r
            for left, right in self.connection.execute("SELECT left_row_id,right_row_id FROM SourceOverlapReviews")
            for r in (left, right)
        }
        for source_id in self.source_ids():
            if any(
                b.row_id in reviewed_rows and b.ledger_account_id == account_id
                for b in self.account_bindings(source_id)
            ):
                return True
        for (payload,) in self.connection.execute("SELECT pair_payload FROM TransferPairReviews"):
            pair = _decode_transfer_pair(payload)
            if account_id in (pair.outgoing.account_id, pair.incoming.account_id):
                return True
        for event in self._read_transfer_history()[0]:
            destination = event.settlement.expected_destination
            if destination is not None and destination.account_id == account_id:
                return True
        return False

    def _require_financial_account(self, account_id: str) -> None:
        if (
            self.connection.execute("SELECT 1 FROM Accounts WHERE id=? AND role='financial'", (account_id,)).fetchone()
            is None
        ):
            raise ProfileFormatError("financial_account_missing")

    def add_category_account(self, account_id: str, name: str, kind: Literal["expense", "income"]) -> None:
        """Create a fresh authored ledger category without source interpretation."""
        self._require_writable()
        self._validate_builtin_categories()
        if (
            type(account_id) is not str
            or is_builtin_id_reserved(account_id)
            or account_id.startswith("internal:")
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,79}", account_id) is None
            or type(name) is not str
            or not 0 < len(name.strip()) <= 200
            or kind not in {"expense", "income"}
        ):
            raise ProfileFormatError("invalid_category_account")
        self.connection.execute(
            "INSERT INTO Accounts VALUES (?,?,?,'USD','category','normal',NULL,NULL,'account_total')",
            (account_id, name, kind),
        )

    def category_accounts(self) -> tuple[CategoryAccount, ...]:
        self._validate_builtin_categories()
        return tuple(
            CategoryAccount(*row)
            for row in self.connection.execute(
                "SELECT id,name,kind FROM Accounts WHERE role='category' ORDER BY name,id"
            )
        )

    def ensure_builtin_category(self, account_id: str) -> CategoryAccount:
        """Explicitly materialize a known fixed category; discovery never writes."""
        self._require_writable()
        category = builtin_category(account_id) if type(account_id) is str else None
        if category is None:
            raise ProfileFormatError("builtin_category_unknown")
        self._validate_builtin_categories()
        self.connection.execute(
            "INSERT INTO Accounts VALUES (?,?,?,'USD','category','normal',NULL,NULL,'account_total') "
            "ON CONFLICT(id) DO NOTHING",
            (category.account_id, category.name, category.kind),
        )
        return CategoryAccount(category.account_id, category.name, category.kind)

    def _validate_builtin_categories(self) -> None:
        for row in self.connection.execute("SELECT * FROM Accounts"):
            if type(row[0]) is not str:
                raise ProfileFormatError("account_identity_integrity")
            if not is_builtin_id_reserved(row[0]):
                continue
            category = builtin_category(row[0])
            if category is None or row != (
                category.account_id,
                category.name,
                category.kind,
                "USD",
                "category",
                "normal",
                None,
                None,
                "account_total",
            ):
                raise ProfileFormatError("builtin_category_integrity")

    def rename_category_account(self, account_id: str, name: str) -> None:
        """Change only a category's display name; journal references use its ID."""
        self._require_writable()
        self._validate_builtin_categories()
        if type(account_id) is str and is_builtin_id_reserved(account_id):
            raise ProfileFormatError("builtin_category_immutable")
        if type(name) is not str or not 0 < len(name.strip()) <= 200:
            raise ProfileFormatError("invalid_category_name")
        cursor = self.connection.execute(
            "UPDATE Accounts SET name=? WHERE id=? AND role='category'", (name.strip(), account_id)
        )
        if cursor.rowcount != 1:
            raise ProfileFormatError("category_account_missing")

    @staticmethod
    def _budget_month(month: date) -> str:
        if type(month) is not date or month.day != 1:
            raise ProfileFormatError("budget_effective_month_invalid")
        return month.isoformat()[:7]

    def set_category_budget_rate(self, category_id: str, effective_month: date, amount_minor: int | None) -> None:
        """Set a monthly target from one month until the next authored change."""
        self._require_writable()
        self._validate_builtin_categories()
        month_key = self._budget_month(effective_month)
        if amount_minor is not None and (
            type(amount_minor) is not int or not 0 <= amount_minor < 9_000_000_000_000_000
        ):
            raise ProfileFormatError("budget_amount_invalid")
        if (
            self.connection.execute("SELECT 1 FROM Accounts WHERE id=? AND role='category'", (category_id,)).fetchone()
            is None
        ):
            raise ProfileFormatError("category_account_missing")
        self.connection.execute(
            "INSERT INTO CategoryBudgetRates(category_id,effective_month,amount_minor) VALUES (?,?,?) "
            "ON CONFLICT(category_id,effective_month) DO UPDATE SET amount_minor=excluded.amount_minor",
            (category_id, month_key, amount_minor),
        )

    def category_budget_history(self, category_id: str) -> tuple[CategoryBudgetRate, ...]:
        self._validate_builtin_categories()
        if (
            self.connection.execute("SELECT 1 FROM Accounts WHERE id=? AND role='category'", (category_id,)).fetchone()
            is None
        ):
            raise ProfileFormatError("category_account_missing")
        return tuple(
            CategoryBudgetRate(category_id, date.fromisoformat(month_key + "-01"), amount_minor)
            for month_key, amount_minor in self.connection.execute(
                "SELECT effective_month,amount_minor FROM CategoryBudgetRates "
                "WHERE category_id=? ORDER BY effective_month",
                (category_id,),
            )
        )

    def category_budget_targets(self, month: date) -> tuple[CategoryBudgetTarget, ...]:
        month_key = self._budget_month(month)
        active: dict[str, tuple[date, int | None]] = {}
        for category_id, effective_key, amount_minor in self.connection.execute(
            "SELECT category_id,effective_month,amount_minor FROM CategoryBudgetRates "
            "WHERE effective_month<=? ORDER BY category_id,effective_month",
            (month_key,),
        ):
            active[category_id] = (date.fromisoformat(effective_key + "-01"), amount_minor)
        return tuple(
            CategoryBudgetTarget(
                category.id,
                category.name,
                category.kind,
                active[category.id][0] if category.id in active else None,
                active[category.id][1] if category.id in active else None,
            )
            for category in self.category_accounts()
        )

    def _cash_category_source(self, row_id: str):
        source_row = self.connection.execute(
            "SELECT source_sha256,row_role,date_role,observed_date,amount_minor FROM SourceObservations WHERE row_id=?",
            (row_id,),
        ).fetchone()
        if source_row is None:
            raise ProfileFormatError("source_observation_missing")
        saved = self.load_import(source_row[0])
        if not _cash_review_scopes(saved.evidence).get(row_id, False):
            raise ProfileFormatError("cash_category_unsupported_source_scope")
        bindings = {binding.row_id: binding.ledger_account_id for binding in self.account_bindings(source_row[0])}
        row = next((item for item in _rows(saved.evidence) if item.row_id == row_id), None)
        financial_id = bindings.get(row_id)
        if (
            row is None
            or row.row_role != "activity"
            or row.date_role != "posting_date"
            or row.date.iso is None
            or row.amount.minor is None
            or row.amount.minor == 0
            or row.amount.provenance != "observed"
            or row.components
            or cash_accounting_description(
                saved.evidence.parser_id, cash_tracking_scope(saved.evidence.parser_id), row.description.text
            )
            is None
            or financial_id is None
        ):
            raise ProfileFormatError("cash_category_requires_bound_posted_movement")
        if source_row[1:] != (row.row_role, row.date_role, row.date.iso, row.amount.minor):
            raise ProfileFormatError("source_observation_index_mismatch")
        financial = self.connection.execute(
            "SELECT kind,role,tracking_scope FROM Accounts WHERE id=?", (financial_id,)
        ).fetchone()
        if financial != ("asset", "financial", cash_tracking_scope(saved.evidence.parser_id)):
            raise ProfileFormatError("cash_category_requires_asset_account")
        return (
            row,
            financial_id,
            self._ledger_accounts(),
            cash_accounting_description(
                saved.evidence.parser_id, cash_tracking_scope(saved.evidence.parser_id), row.description.text
            ),
        )

    def _ledger_accounts(self) -> dict[str, LedgerAccount]:
        self._validate_builtin_categories()
        self._validate_transfer_clearing()
        account_rows = self.connection.execute("SELECT id,name,kind,currency,role,purpose FROM Accounts").fetchall()
        return {
            account_id: LedgerAccount(
                account_id,
                name,
                AccountKind(kind),
                currency,
                account_id if role == "financial" else None,
                purpose,
            )
            for account_id, name, kind, currency, role, purpose in account_rows
        }

    def _card_purchase_source(self, row_id: str):
        source_row = self.connection.execute(
            "SELECT source_sha256,row_role,date_role,observed_date,amount_minor FROM SourceObservations WHERE row_id=?",
            (row_id,),
        ).fetchone()
        if source_row is None:
            raise ProfileFormatError("source_observation_missing")
        saved = self.load_import(source_row[0])
        if not _card_review_scopes(saved.evidence).get(row_id, False):
            raise ProfileFormatError("card_purchase_unsupported_source_scope")
        row = next((item for item in _rows(saved.evidence) if item.row_id == row_id), None)
        bindings = {binding.row_id: binding.ledger_account_id for binding in self.account_bindings(source_row[0])}
        financial_id = bindings.get(row_id)
        if (
            row is None
            or row.row_role != "activity"
            or row.amount.minor is None
            or row.amount.minor == 0
            or row.components
            or row.amount.provenance != "observed"
            or not row.description.text
            or financial_id is None
        ):
            raise ProfileFormatError("card_purchase_requires_bound_negative_movement")
        if source_row[1:] != (row.row_role, row.date_role, row.date.iso, row.amount.minor):
            raise ProfileFormatError("source_observation_index_mismatch")
        financial = self.connection.execute(
            "SELECT kind,role,tracking_scope FROM Accounts WHERE id=?", (financial_id,)
        ).fetchone()
        if financial != ("liability", "financial", "account_total"):
            raise ProfileFormatError("card_purchase_requires_liability_account")
        candidate = posting_date_candidate(row)
        if candidate is None:
            raise ProfileFormatError("card_purchase_posting_date_unavailable")
        return row, financial_id, self._ledger_accounts(), candidate

    def _active_consumed(self, *, excluding: str | None = None) -> dict[str, int]:
        self._validate_journal_retirements()
        self._validate_transfer_history()
        self._validate_source_interpretation_history()
        self._validate_common_journal_read()
        query = (
            f"SELECT row_id,SUM(amount_minor) FROM JournalAllocations WHERE entry_key NOT IN ({_INACTIVE_JOURNAL_SQL})"
        )
        parameters: tuple[str, ...] = ()
        if excluding is not None:
            query += " AND entry_key<>?"
            parameters = (excluding,)
        return dict(self.connection.execute(query + " GROUP BY row_id", parameters))

    def _inactive_journal_keys(self) -> frozenset[str]:
        self._validate_journal_retirements()
        self._validate_transfer_history()
        self._validate_source_interpretation_history()
        return frozenset(key for (key,) in self.connection.execute(_INACTIVE_JOURNAL_SQL))

    def _validate_journal_retirements(self) -> None:
        """A persisted retirement is exactly its original's reviewed inverse."""
        rows = self.connection.execute("SELECT original_key,reversal_key,reason FROM JournalRetirements").fetchall()
        if not rows:
            return
        corrections = self.connection.execute(
            "SELECT original_key,reversal_key,replacement_key FROM JournalCorrections"
        ).fetchall()
        correction_inactive = {key for row in corrections for key in row[:2]}
        correction_keys = {key for row in corrections for key in row}
        original_keys = {row[0] for row in rows}
        inverse_keys = {row[1] for row in rows}
        if original_keys & inverse_keys or original_keys & correction_inactive or inverse_keys & correction_keys:
            raise ProfileFormatError("journal_retirement_integrity")
        for original_key, inverse_key, reason in rows:
            saved = dict(
                self.connection.execute(
                    "SELECT key,payload FROM JournalEntries WHERE key IN (?,?)", (original_key, inverse_key)
                )
            )
            try:
                original = _decode_journal(saved[original_key])
                inverse = _decode_journal(saved[inverse_key])
                if (
                    original.key != original_key
                    or inverse.key != inverse_key
                    or original.reviewed is not True
                    or inverse.reviewed is not True
                    or inverse.origin != "reversal"
                    or inverse.event_id != original.event_id
                    or inverse.posting_date != original.posting_date
                    or original.origin not in {"imported", "opening", "manual"}
                    or type(reason) is not str
                    or not 0 < len(reason.strip()) <= 500
                    or inverse.reason != reason
                    or self.connection.execute(
                        "SELECT 1 FROM JournalAllocations WHERE entry_key=? LIMIT 1", (inverse_key,)
                    ).fetchone()
                    is not None
                    or len(original.postings) < 2
                    or len(original.postings) != len(inverse.postings)
                    or sum(posting.amount_minor for posting in original.postings) != 0
                    or any(
                        type(posting.amount_minor) is not int
                        or posting.amount_minor == 0
                        or type(reversal.amount_minor) is not int
                        or reversal.account_id != posting.account_id
                        or reversal.amount_minor != -posting.amount_minor
                        or reversal.allocations
                        for posting, reversal in zip(original.postings, inverse.postings, strict=True)
                    )
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise ProfileFormatError("journal_retirement_integrity") from None

    def _opening_journal_keys(self) -> frozenset[str]:
        """Opening inverses retain opening scope in movement and export views."""
        self._validate_journal_retirements()
        self._validate_opening_decision_histories()
        openings = {
            key
            for key, payload in self.connection.execute("SELECT key,payload FROM JournalEntries")
            if _decode_journal(payload).origin == "opening"
        }
        openings.update(
            reversal
            for original, reversal in self.connection.execute(
                "SELECT original_key,reversal_key FROM JournalRetirements"
            )
            if original in openings
        )
        return frozenset(openings)

    def _active_journal_entries(self) -> tuple[JournalEntry, ...]:
        inactive = self._inactive_journal_keys()
        return tuple(
            _decode_journal(payload)
            for key, payload in self.connection.execute("SELECT key,payload FROM JournalEntries")
            if key not in inactive
        )

    def _require_unposted_rows(self, row_ids: tuple[str, ...]) -> None:
        for offset in range(0, len(row_ids), 500):
            batch = row_ids[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            if self.connection.execute(
                f"SELECT 1 FROM JournalAllocations WHERE row_id IN ({placeholders}) LIMIT 1", batch
            ).fetchone():
                raise ProfileFormatError("account_binding_has_journal_history")
            if self.connection.execute(
                f"SELECT 1 FROM SourceOverlapReviews WHERE left_row_id IN ({placeholders}) "
                f"OR right_row_id IN ({placeholders}) LIMIT 1",
                (*batch, *batch),
            ).fetchone():
                raise ProfileFormatError("account_binding_has_overlap_review_history")
            if self.connection.execute(
                f"SELECT 1 FROM TransferPairReviews WHERE outgoing_row_id IN ({placeholders}) "
                f"OR incoming_row_id IN ({placeholders}) LIMIT 1",
                (*batch, *batch),
            ).fetchone():
                raise ProfileFormatError("account_binding_has_transfer_review_history")

    def _binding_opening_anchors(self, target: BindingCorrectionTarget, accounts) -> tuple[str, ...]:
        associated = set(accounts) - {None}
        associated.update(
            row[0]
            for row in self.connection.execute(
                "SELECT DISTINCT account_id FROM StatementSourceReviews WHERE source_sha256=?", (target.source_sha256,)
            )
        )
        return tuple(
            sorted(
                account
                for account in associated
                if (history := self.opening_decision_history(account))
                and history[0].origin == "source"
                and history[0].state == "active"
            )
        )

    def _require_ordinary_binding_change(self, target: BindingCorrectionTarget) -> None:
        _evidence, rows = self._binding_target_rows(target)
        self._require_unposted_rows(rows)
        for record in self._read_binding_corrections():
            if record.target.source_sha256 != target.source_sha256:
                continue
            _old_evidence, old_rows = self._binding_target_rows(record.target)
            if set(rows).intersection(old_rows) or record.target == target:
                raise ProfileFormatError("account_binding_has_correction_history")
        if self._binding_opening_anchors(target, self._binding_scope_accounts(target)):
            raise ProfileFormatError("account_binding_source_backed_opening_anchor")
        if self._binding_dated_value_anchors(target):
            raise ProfileFormatError("account_binding_source_backed_dated_value_anchor")

    def _binding_dated_value_anchors(self, target: BindingCorrectionTarget) -> tuple[ReviewedDatedValue, ...]:
        return tuple(
            value
            for value in self._read_dated_values()
            if value.state == "active"
            and value.source_proof is not None
            and value.source_proof.source_sha256 == target.source_sha256
            and target.mode == "source"
            and (value.source_proof.source_identity, value.source_proof.source_identity_form)
            == (target.source_identity, target.source_identity_form)
        )

    def source_overlap_history_row_ids(self, source_sha256: str) -> frozenset[str]:
        """Rows whose binding is fixed by durable occurrence-review history."""
        self.load_import(source_sha256)
        return frozenset(
            row_id
            for (row_id,) in self.connection.execute(
                "SELECT o.row_id FROM SourceObservations o WHERE o.source_sha256=? AND EXISTS ("
                "SELECT 1 FROM SourceOverlapReviews r WHERE r.left_row_id=o.row_id OR r.right_row_id=o.row_id)",
                (source_sha256,),
            )
        )

    def _source_overlap_index(self):
        """Build the full finite date-window index, retaining supporting rows."""
        accounts = {account.id: account for account in self.financial_accounts()}
        consumed = self._active_consumed()
        proven_support = set()
        if not self._source_interpretation_mutating:
            _actions, repairs = self._read_source_interpretation_history()
            proven_support = {repair.redundant_row_id for repair in repairs}
        history = {row[0] for row in self.connection.execute("SELECT DISTINCT row_id FROM JournalAllocations")}
        rows = {}
        for source_id in self.source_ids():
            evidence = self.load_import(source_id).evidence
            bindings = {binding.row_id: binding.ledger_account_id for binding in self.account_bindings(source_id)}
            for row in _rows(evidence):
                account = accounts.get(bindings.get(row.row_id))
                if account is None or row.row_role != "activity" or not row.amount.minor:
                    continue
                item = SourceOverlapRow(
                    row.row_id,
                    source_id,
                    account.id,
                    account.name,
                    row.date.iso,
                    row.date_role,
                    row.date.provenance,
                    row.amount.minor,
                    row.description.text or "Description not printed",
                    tuple(dict.fromkeys(fragment.location.model_dump_json() for fragment in row.fragments)),
                    consumed.get(row.row_id, 0),
                    row.row_id in history,
                    row.row_id in proven_support and not consumed.get(row.row_id, 0),
                )
                rows[item.row_id] = item
        reviews = {}
        for revision, left, right, decision, retained in self.connection.execute(
            "SELECT revision_id,left_row_id,right_row_id,decision,retained_row_id "
            "FROM SourceOverlapReviews ORDER BY revision_id"
        ):
            reviews[left, right] = (revision, decision, retained)
        aliases = {}
        for (left, right), (revision, decision, retained) in reviews.items():
            if decision == "repeat":
                excluded = right if retained == left else left
                if excluded in aliases or retained not in (left, right):
                    raise ProfileFormatError("source_overlap_history_integrity")
                aliases[excluded] = (retained, revision)
        groups = self._source_overlap_groups(rows, aliases)
        for root, members in groups.items():
            if any(member in aliases for member in (root,)) or any(member not in rows for member in members):
                raise ProfileFormatError("source_overlap_history_integrity")
            if not pairwise_source_group(rows[member] for member in members):
                raise ProfileFormatError("source_overlap_history_integrity")
            if any(review[1] == "distinct" and set(pair) <= set(members) for pair, review in reviews.items()):
                raise ProfileFormatError("source_overlap_history_integrity")
        for excluded in aliases:
            if rows[excluded].active_allocated_minor or (
                rows[excluded].has_journal_history
                and not rows[excluded].repeat_support_history_validated
                and not self._source_interpretation_mutating
            ):
                raise ProfileFormatError("source_overlap_history_integrity")
        try:
            index = NearbySourceIndex(rows.values())
        except ValueError:
            raise ProfileFormatError("source_overlap_history_integrity") from None
        return rows, index, reviews, aliases

    @staticmethod
    def _source_overlap_groups(rows, aliases):
        groups = {row: {row} for row in rows if row not in aliases}
        for excluded, (root, _revision) in aliases.items():
            groups.setdefault(root, {root}).add(excluded)
        return groups

    def _source_overlap_basis(self) -> str:
        self._validate_account_metadata()
        self._read_binding_corrections()
        self._validate_journal_retirements()
        self._validate_transfer_history()
        self._validate_source_interpretation_history()
        digest = hashlib.sha256(OVERLAP_RULE.encode())
        for table in (
            "EvidenceSnapshots",
            "SourceObservations",
            "Accounts",
            "SourceAccountBindings",
            "FileAccountAssertions",
            "RowAccountAssignments",
            "JournalEntries",
            "JournalAllocations",
            "JournalCorrections",
            "JournalRetirements",
            "OpeningDecisionRevisions",
            "OpeningDecisions",
            "AccountDatedValues",
            "DatedValueWithdrawals",
            "AccountLifecycleDecisions",
            "TransferEvents",
            "TransferEventActions",
            "TransferPairReviews",
            "SourceInterpretationActions",
            "PostedRepeatRepairs",
            "SourceOverlapReviews",
            "BindingCorrections",
        ):
            digest.update(table.encode())
            columns = "source_sha256,definition_sha256,size,sha256" if table == "EvidenceSnapshots" else "*"
            for row in sorted(
                self.connection.execute(f"SELECT {columns} FROM {table}").fetchall(),
                key=lambda item: json.dumps(item, separators=(",", ":")),
            ):
                digest.update(json.dumps(row, separators=(",", ":")).encode())
        return digest.hexdigest()

    @staticmethod
    def _source_overlap_candidate(left, right, reviews, aliases, basis):
        review = reviews.get((left.row_id, right.row_id))
        revision, decision, retained = review if review else (None, "pending", None)
        left_root = aliases.get(left.row_id, (left.row_id, None))[0]
        right_root = aliases.get(right.row_id, (right.row_id, None))[0]
        left_group = {left_root} | {row for row, (root, _revision) in aliases.items() if root == left_root}
        right_group = {right_root} | {row for row, (root, _revision) in aliases.items() if root == right_root}
        edges = tuple(
            sorted(
                tuple(sorted((row, root)))
                for row, (root, _revision) in aliases.items()
                if root in {left_root, right_root}
            )
        )
        if left_root == right_root:
            decision, retained = "repeat", left_root
            if review is None or review[1] != "repeat":
                revision = (aliases.get(left.row_id) or aliases[right.row_id])[1]
        elif decision != "distinct" and left.active_allocated_minor and right.active_allocated_minor:
            decision = "posted_conflict"
        return SourceOverlapCandidate(
            left,
            right,
            decision,
            retained,
            revision,
            basis,
            left_root,
            right_root,
            tuple(sorted(left_group)),
            tuple(sorted(right_group)),
            edges,
        )

    def source_overlap_pair(self, left_row_id: str, right_row_id: str) -> SourceOverlapCandidate:
        """Read an actual eligible pair, including saved root edges beyond list caps."""
        if type(left_row_id) is not str or type(right_row_id) is not str or left_row_id == right_row_id:
            raise ProfileFormatError("source_overlap_pair_unavailable")
        if self.connection.in_transaction:
            raise ProfileFormatError("source_overlap_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            rows, _index, reviews, aliases = self._source_overlap_index()
            left_id, right_id = sorted((left_row_id, right_row_id))
            left, right = rows.get(left_id), rows.get(right_id)
            if left is None or right is None or not nearby_source_pair(left, right):
                raise ProfileFormatError("source_overlap_pair_unavailable")
            return self._source_overlap_candidate(left, right, reviews, aliases, self._source_overlap_basis())
        finally:
            self.connection.execute("ROLLBACK")

    def source_overlap_inventory(
        self, *, source_sha256: str | None = None, max_pairs: int = 2000
    ) -> SourceOverlapInventory:
        """Read a capped candidate inventory from one coherent committed snapshot."""
        if type(max_pairs) is not int or not 1 <= max_pairs <= 10_000:
            raise ProfileFormatError("source_overlap_limit_invalid")
        owns_snapshot = not self.connection.in_transaction
        if owns_snapshot:
            self.connection.execute("BEGIN")
        try:
            if source_sha256 is not None:
                self.load_import(source_sha256)
            rows, index, reviews, aliases = self._source_overlap_index()
            basis = self._source_overlap_basis()
            candidates = []
            total = index.count_pairs(source_sha256=source_sha256)

            # Resolve the visible pending work, refresh, and the next pending pairs
            # become reachable even when the complete inventory exceeds the cap.
            for resolved in (False, True):
                for left_id, right_id in index.pairs(source_sha256=source_sha256):
                    same_group = aliases.get(left_id, (left_id, None))[0] == aliases.get(right_id, (right_id, None))[0]
                    is_resolved = (
                        same_group or reviews.get((left_id, right_id), (None, "pending", None))[1] == "distinct"
                    )
                    if is_resolved != resolved:
                        continue
                    candidate = self._source_overlap_candidate(rows[left_id], rows[right_id], reviews, aliases, basis)
                    candidates.append(candidate)
                    if len(candidates) == max_pairs:
                        break
                if len(candidates) == max_pairs:
                    break
            return SourceOverlapInventory(tuple(candidates), total > len(candidates), total)
        finally:
            if owns_snapshot:
                self.connection.execute("ROLLBACK")

    def source_overlap_posting_blocks(self, row_ids: tuple[str, ...]) -> dict[str, str]:
        """Guard every nearby edge from every member of a retained group."""
        owns_snapshot = not self.connection.in_transaction
        if owns_snapshot:
            self.connection.execute("BEGIN")
        try:
            return self._source_overlap_posting_blocks(row_ids)
        finally:
            if owns_snapshot:
                self.connection.execute("ROLLBACK")

    def _source_overlap_posting_blocks(self, row_ids: tuple[str, ...]) -> dict[str, str]:
        rows, index, reviews, aliases = self._source_overlap_index()
        groups = self._source_overlap_groups(rows, aliases)
        blocks = {}
        for row_id in row_ids:
            if row_id in aliases:
                blocks[row_id] = "Repeated supporting evidence; post the retained row"
                continue
            row = rows.get(row_id)
            if row is None:
                continue
            members = groups[row_id]
            if any(
                other_id not in members
                and reviews.get(tuple(sorted((member, other_id))), (None, "pending", None))[1] != "distinct"
                for member in members
                for other_id in index.neighbors(member)
            ):
                blocks[row_id] = "Cross-source occurrence needs review"
        return blocks

    def _require_source_overlap_postable(self, row_ids: tuple[str, ...]) -> None:
        if self.source_overlap_posting_blocks(row_ids):
            raise ProfileFormatError("source_overlap_review_required")

    def record_source_overlap_review(
        self,
        left_row_id: str,
        right_row_id: str,
        *,
        decision: Literal["distinct", "repeat", "pending"],
        retained_row_id: str | None = None,
        reason: str,
        expected_basis_sha256: str,
    ) -> SourceOverlapCandidate:
        return self._record_source_overlap_review(
            left_row_id,
            right_row_id,
            decision=decision,
            retained_row_id=retained_row_id,
            reason=reason,
            expected_basis_sha256=expected_basis_sha256,
        )

    def _record_source_overlap_review(
        self,
        left_row_id: str,
        right_row_id: str,
        *,
        decision: Literal["distinct", "repeat", "pending"],
        retained_row_id: str | None = None,
        reason: str,
        expected_basis_sha256: str,
        _owns_transaction: bool = True,
        _repair_proof: bool = False,
    ) -> SourceOverlapCandidate:
        """Append an explicit occurrence decision without changing evidence or money."""
        self._require_writable()
        if (
            type(left_row_id) is not str
            or type(right_row_id) is not str
            or left_row_id == right_row_id
            or decision not in {"distinct", "repeat", "pending"}
            or type(reason) is not str
            or not 0 < len(reason.strip()) <= 500
            or (decision == "repeat" and retained_row_id not in (left_row_id, right_row_id))
            or (decision != "repeat" and retained_row_id is not None)
            or type(expected_basis_sha256) is not str
        ):
            raise ProfileFormatError("source_overlap_review_invalid")
        left_id, right_id = sorted((left_row_id, right_row_id))
        if _owns_transaction:
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            if expected_basis_sha256 != self._source_overlap_basis():
                raise ProfileFormatError("source_overlap_changed_since_selection")
            rows, _buckets, reviews, aliases = self._source_overlap_index()
            left, right = rows.get(left_id), rows.get(right_id)
            if left is None or right is None or not nearby_source_pair(left, right):
                raise ProfileFormatError("source_overlap_pair_unavailable")
            old = reviews.get((left_id, right_id))
            left_root = aliases.get(left_id, (left_id, None))[0]
            right_root = aliases.get(right_id, (right_id, None))[0]
            direct_repeat = old is not None and old[1] == "repeat"
            if left_root == right_root:
                if not direct_repeat:
                    raise ProfileFormatError("source_overlap_clear_repeat_first")
            # Remove only this pair's old edge when checking a replacement decision.
            effective = dict(aliases)
            if old is not None and old[1] == "repeat":
                old_excluded = right_id if old[2] == left_id else left_id
                effective.pop(old_excluded, None)
            if (
                decision == "distinct"
                and effective.get(left_id, (left_id, None))[0] == effective.get(right_id, (right_id, None))[0]
            ):
                raise ProfileFormatError("source_overlap_clear_repeat_first")
            if decision == "repeat":
                excluded = right_id if retained_row_id == left_id else left_id
                proven = self._has_posted_repeat_proof(excluded) or (
                    _repair_proof
                    and self._source_interpretation_mutating
                    and self.connection.execute(
                        "SELECT 1 FROM SourceInterpretationActions WHERE row_id=? AND kind='repeat_repair'", (excluded,)
                    ).fetchone()
                    is not None
                    and not self._active_consumed().get(excluded, 0)
                )
                if rows[excluded].has_journal_history and not proven:
                    raise ProfileFormatError("source_overlap_excluded_has_journal_history")
                if (
                    retained_row_id in effective
                    or excluded in effective
                    or any(retained == excluded for retained, _revision in effective.values())
                ):
                    raise ProfileFormatError("source_overlap_chain_or_conflict")
                group = {retained_row_id, excluded} | {
                    alias for alias, (retained, _revision) in effective.items() if retained == retained_row_id
                }
                sources = [rows[row_id].source_sha256 for row_id in group]
                if len(set(sources)) != len(sources):
                    raise ProfileFormatError("source_overlap_occurrence_multiplicity")
                if not pairwise_source_group(rows[row_id] for row_id in group):
                    raise ProfileFormatError("source_overlap_group_not_pairwise_eligible")
                if any(
                    pair != (left_id, right_id) and review[1] == "distinct" and set(pair) <= group
                    for pair, review in reviews.items()
                ):
                    raise ProfileFormatError("source_overlap_conflicts_with_distinct")
            prior_reason = (
                self.connection.execute(
                    "SELECT reason FROM SourceOverlapReviews WHERE revision_id=?", (old[0],)
                ).fetchone()
                if old is not None
                else None
            )
            if not (old is not None and old[1:] == (decision, retained_row_id) and prior_reason == (reason.strip(),)):
                self.connection.execute(
                    "INSERT INTO SourceOverlapReviews "
                    "(left_row_id,right_row_id,decision,retained_row_id,basis_sha256,reason) VALUES (?,?,?,?,?,?)",
                    (left_id, right_id, decision, retained_row_id, expected_basis_sha256, reason.strip()),
                )
            _rows_index, _buckets, reviews, aliases = self._source_overlap_index()
            result = self._source_overlap_candidate(left, right, reviews, aliases, self._source_overlap_basis())
            if _owns_transaction:
                self.connection.execute("COMMIT")
        except BaseException:
            if _owns_transaction:
                self.connection.execute("ROLLBACK")
            raise
        return result

    def _row_assignments(self, row_ids: tuple[str, ...]) -> dict[str, str]:
        assigned = {}
        for offset in range(0, len(row_ids), 500):
            batch = row_ids[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            assigned.update(
                self.connection.execute(
                    f"SELECT row_id,ledger_account_id FROM RowAccountAssignments WHERE row_id IN ({placeholders})",
                    batch,
                )
            )
        return assigned

    def _ordinary_category_entry(
        self, entry_key: str, *, active: bool = True, _cache: dict | None = None
    ) -> tuple[JournalEntry, str]:
        cache = {} if _cache is None else _cache
        if type(entry_key) is not str or not entry_key.startswith(("review:cash:", "review:card:")):
            raise ProfileFormatError("source_interpretation_unsupported")
        saved = (
            (cache["journal_payloads"][entry_key],)
            if "journal_payloads" in cache and entry_key in cache["journal_payloads"]
            else self.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (entry_key,)).fetchone()
        )
        if saved is None:
            raise ProfileFormatError("source_interpretation_unsupported")
        entry = _decode_journal(saved[0])
        indexed = (
            cache["allocations"].get(entry_key, [])
            if "allocations" in cache
            else self.connection.execute(
                "SELECT row_id,amount_minor FROM JournalAllocations WHERE entry_key=?", (entry_key,)
            ).fetchall()
        )
        if (
            entry.key != entry_key
            or entry.origin != "imported"
            or entry.reviewed is not True
            or len(entry.postings) != 2
            or len(indexed) != 1
            or type(indexed[0][0]) is not str
            or type(indexed[0][1]) is not int
            or indexed[0][1] == 0
            or entry.postings[0].allocations != (Allocation(*indexed[0]),)
            or entry.postings[0].amount_minor != indexed[0][1]
            or entry.postings[1].amount_minor != -indexed[0][1]
            or entry.postings[1].allocations
        ):
            raise ProfileFormatError("source_interpretation_unsupported")
        row_id, amount = indexed[0]
        source = (
            (cache["observation_sources"][row_id],)
            if "observation_sources" in cache and row_id in cache["observation_sources"]
            else self.connection.execute(
                "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (row_id,)
            ).fetchone()
        )
        if source is None:
            raise ProfileFormatError("source_interpretation_unsupported")
        evidence_by_source = cache.setdefault("evidence", {})
        if source[0] not in evidence_by_source:
            evidence_by_source[source[0]] = self.load_import(source[0]).evidence
            cache.setdefault("source_rows", {})[source[0]] = {
                row.row_id: row for row in _rows(evidence_by_source[source[0]])
            }
        evidence = evidence_by_source[source[0]]
        row = cache["source_rows"][source[0]][row_id]
        if "tracking_scopes" not in cache:
            cache["tracking_scopes"] = dict(self.connection.execute("SELECT id,tracking_scope FROM Accounts"))
        scopes = cache.setdefault("review_scopes", {})
        if source[0] not in scopes:
            scopes[source[0]] = (_cash_review_scopes(evidence), _card_review_scopes(evidence))
        if "accounts" not in cache:
            cache["accounts"] = self._ledger_accounts()
            cache["roles"] = dict(self.connection.execute("SELECT id,role FROM Accounts"))
        accounts = cache["accounts"]
        financial = accounts.get(entry.postings[0].account_id)
        category = accounts.get(entry.postings[1].account_id)
        cash = entry_key.startswith("review:cash:")
        if (
            row.row_role != "activity"
            or row.components
            or row.amount.minor != amount
            or row.amount.provenance != "observed"
            or entry.description
            != (
                cash_accounting_description(
                    evidence.parser_id, cash_tracking_scope(evidence.parser_id), row.description.text
                )
                if cash
                else row.description.text
            )
            or entry.event_id != f"source:{row_id}"
            or financial is None
            or cache["tracking_scopes"].get(financial.id)
            != (cash_tracking_scope(evidence.parser_id) if cash else "account_total")
            or financial.source_account_id is None
            or category is None
            or category.source_account_id is not None
            or category.kind.value not in {"expense", "income"}
            or cache["roles"].get(category.id) != "category"
            or (
                cash
                and (
                    financial.kind != AccountKind.ASSET
                    or not scopes[source[0]][0].get(row_id, False)
                    or row.date_role != "posting_date"
                    or entry.posting_date.isoformat() != row.date.iso
                )
            )
            or (
                not cash
                and (
                    financial.kind != AccountKind.LIABILITY
                    or not scopes[source[0]][1].get(row_id, False)
                    or posting_date_candidate(row) is None
                )
            )
        ):
            raise ProfileFormatError("source_interpretation_unsupported")
        # Initial identities retain the explicitly reviewed financial purpose.
        # Corrections carry that purpose through their immutable original link.
        if not entry_key.startswith(("review:cash:correction:", "review:card:correction:")):
            purpose = _category_purpose(amount, category.kind.value)
            base = f"review:{'cash' if cash else 'card'}:{purpose}:{row_id}"
            if entry_key != base and re.fullmatch(re.escape(base) + r":repost:[1-9][0-9]*", entry_key) is None:
                raise ProfileFormatError("source_interpretation_unsupported")
        try:
            validate_entry(entry, accounts, {row_id: Observation(row_id, financial.id, amount, entry.posting_date)}, {})
        except LedgerError:
            raise ProfileFormatError("source_interpretation_unsupported") from None
        if active:
            if entry_key in self._inactive_journal_keys():
                raise ProfileFormatError("source_interpretation_not_active")
            bindings = {b.row_id: b.ledger_account_id for b in self.account_bindings(source[0])}
            usage = self._active_consumed()
            active_keys = self.connection.execute(
                f"SELECT entry_key FROM JournalAllocations WHERE row_id=? AND entry_key NOT IN ({_INACTIVE_JOURNAL_SQL})",
                (row_id,),
            ).fetchall()
            if bindings.get(row_id) != financial.id or usage.get(row_id) != amount or active_keys != [(entry_key,)]:
                raise ProfileFormatError("source_interpretation_not_active")
        return entry, row_id

    def _read_source_interpretation_history(
        self,
    ) -> tuple[tuple[SourceInterpretationAction, ...], tuple[PostedRepeatRepair, ...]]:
        self._validate_journal_retirements()
        actions, action_details = [], {}
        for row in self.connection.execute(
            "SELECT action_id,row_id,entry_key,reversal_key,kind,request_basis,original_sha256,inverse_sha256,reason,record_sha256,created_at FROM SourceInterpretationActions ORDER BY action_id DESC"
        ):
            action_id, row_id, key, inverse, kind, basis, original_sha, inverse_sha, reason, checksum, created = row
            if (
                type(action_id) is not int
                or action_id <= 0
                or any(type(value) is not str or not value for value in row[1:])
                or kind not in {"withdraw", "repeat_repair"}
                or not 0 < len(reason.strip()) <= 500
                or any(
                    re.fullmatch(r"[0-9a-f]{64}", value) is None
                    for value in (basis, original_sha, inverse_sha, checksum)
                )
                or checksum != _transfer_record_digest(*row[:9])
            ):
                raise ProfileFormatError("source_interpretation_history_integrity")
            try:
                entry, actual_row = self._ordinary_category_entry(key, active=False)
                saved_inverse = self.connection.execute(
                    "SELECT payload FROM JournalEntries WHERE key=?", (inverse,)
                ).fetchone()
                retired = self.connection.execute(
                    "SELECT reversal_key,reason FROM JournalRetirements WHERE original_key=?", (key,)
                ).fetchone()
                if (
                    actual_row != row_id
                    or retired != (inverse, reason)
                    or saved_inverse is None
                    or original_sha != _digest(_journal_payload(entry).encode())
                    or inverse_sha != _digest(saved_inverse[0].encode())
                ):
                    raise ValueError
            except (ProfileFormatError, TypeError, ValueError):
                raise ProfileFormatError("source_interpretation_history_integrity") from None
            actions.append(SourceInterpretationAction(action_id, row_id, key, inverse, kind, reason, created, checksum))
            action_details[action_id] = row
        repairs, repair_actions = [], set()
        for row in self.connection.execute(
            "SELECT repair_id,retained_row_id,redundant_row_id,retained_entry_key,redundant_entry_key,action_id,review_revision_id,request_basis,retained_sha256,review_sha256,reason,record_sha256,created_at FROM PostedRepeatRepairs ORDER BY repair_id DESC"
        ):
            (
                repair_id,
                retained,
                redundant,
                retained_key,
                redundant_key,
                action_id,
                review_id,
                basis,
                retained_sha,
                review_sha,
                reason,
                checksum,
                created,
            ) = row
            if (
                any(type(row[index]) is not int or row[index] <= 0 for index in (0, 5, 6))
                or any(type(row[index]) is not str or not row[index] for index in (1, 2, 3, 4, 7, 8, 9, 10, 11, 12))
                or any(
                    re.fullmatch(r"[0-9a-f]{64}", value) is None
                    for value in (basis, retained_sha, review_sha, checksum)
                )
                or checksum != _transfer_record_digest(*row[:11])
            ):
                raise ProfileFormatError("source_interpretation_history_integrity")
            action = action_details.get(action_id)
            if (
                action is None
                or action[1] != redundant
                or action[2] != redundant_key
                or action[4] != "repeat_repair"
                or action[5] != basis
                or action[8] != reason
                or action_id in repair_actions
            ):
                raise ProfileFormatError("source_interpretation_history_integrity")
            try:
                retained_entry, retained_actual = self._ordinary_category_entry(retained_key, active=False)
                redundant_entry, redundant_actual = self._ordinary_category_entry(redundant_key, active=False)
                review = self.connection.execute(
                    "SELECT * FROM SourceOverlapReviews WHERE revision_id=?", (review_id,)
                ).fetchone()
                if (
                    retained_actual != retained
                    or redundant_actual != redundant
                    or retained == redundant
                    or retained_entry.postings[0].account_id != redundant_entry.postings[0].account_id
                    or retained_entry.postings[0].amount_minor != redundant_entry.postings[0].amount_minor
                    or retained_sha != _digest(_journal_payload(retained_entry).encode())
                    or review is None
                    or review[1:5] != (*sorted((retained, redundant)), "repeat", retained)
                    or review[6] != reason
                    or review_sha != _transfer_record_digest(*review)
                ):
                    raise ValueError
                if not nearby_source_pair(
                    self._historical_overlap_row(retained, retained_entry.postings[0].account_id),
                    self._historical_overlap_row(redundant, redundant_entry.postings[0].account_id),
                ):
                    raise ValueError
            except (ProfileFormatError, TypeError, ValueError):
                raise ProfileFormatError("source_interpretation_history_integrity") from None
            repairs.append(
                PostedRepeatRepair(
                    repair_id,
                    retained,
                    redundant,
                    retained_key,
                    redundant_key,
                    action[3],
                    review_id,
                    reason,
                    created,
                    checksum,
                )
            )
            repair_actions.add(action_id)
        if {a.action_id for a in actions if a.kind == "repeat_repair"} != repair_actions:
            raise ProfileFormatError("source_interpretation_history_integrity")
        return tuple(actions), tuple(repairs)

    def _validate_source_interpretation_history(self) -> None:
        if not self._source_interpretation_mutating:
            self._read_source_interpretation_history()

    def _historical_overlap_row(self, row_id: str, account_id: str) -> SourceOverlapRow:
        """Use immutable source dates and the recorded journal account, never today's binding."""
        source = self.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (row_id,)
        ).fetchone()
        if source is None:
            raise ProfileFormatError("source_interpretation_history_integrity")
        evidence = self.load_import(source[0]).evidence
        row = next((row for row in _rows(evidence) if row.row_id == row_id), None)
        if row is None or row.row_role != "activity":
            raise ProfileFormatError("source_interpretation_history_integrity")
        return SourceOverlapRow(
            row_id,
            source[0],
            account_id,
            account_id,
            row.date.iso,
            row.date_role,
            row.date.provenance,
            row.amount.minor,
            row.description.text or "",
            (),
            0,
            True,
        )

    def _validate_common_journal_read(self) -> None:
        """Validate recorded money without invoking report or active-read helpers.

        Historical effective card dates remain reviewed facts. Source decoding and
        row indexes are cached for this pass, never shared across profile versions.
        Pending manual entries receive structural checks without being classified.
        """
        self._validate_account_metadata()
        self._read_binding_corrections()
        payloads = dict(self.connection.execute("SELECT key,payload FROM JournalEntries"))
        if not payloads:
            return
        entries = {key: _decode_journal(payload) for key, payload in payloads.items()}
        accounts = self._ledger_accounts()
        if any(
            type(key) is not str
            or entry.key != key
            or any(posting.account_id not in accounts for posting in entry.postings)
            for key, entry in entries.items()
        ):
            raise ProfileFormatError("journal_entry_invalid")
        allocations = {}
        for key, row_id, amount in self.connection.execute(
            "SELECT entry_key,row_id,amount_minor FROM JournalAllocations"
        ):
            allocations.setdefault(key, []).append((row_id, amount))
        cache = {
            "journal_payloads": payloads,
            "accounts": accounts,
            "roles": dict(self.connection.execute("SELECT id,role FROM Accounts")),
            "allocations": allocations,
            "observation_sources": dict(self.connection.execute("SELECT row_id,source_sha256 FROM SourceObservations")),
        }
        inactive = frozenset(key for (key,) in self.connection.execute(_INACTIVE_JOURNAL_SQL))
        active_by_row = {}
        for key, rows in allocations.items():
            if key not in inactive:
                for row_id, _amount in rows:
                    active_by_row.setdefault(row_id, []).append(key)
        ordinary = {}
        bindings_by_source = {}
        try:
            for key, entry in entries.items():
                if not key.startswith(("review:cash:", "review:card:")):
                    continue
                ordinary[key] = self._ordinary_category_entry(key, active=False, _cache=cache)
                if key not in inactive:
                    row_id = ordinary[key][1]
                    source_id = cache["observation_sources"][row_id]
                    if source_id not in bindings_by_source:
                        bindings_by_source[source_id] = {
                            b.row_id: b.ledger_account_id for b in self.account_bindings(source_id)
                        }
                    if (
                        active_by_row.get(row_id) != [key]
                        or bindings_by_source[source_id].get(row_id) != entry.postings[0].account_id
                    ):
                        raise ValueError
            corrections = self.connection.execute(
                "SELECT original_key,reversal_key,replacement_key,reason FROM JournalCorrections"
            ).fetchall()
            links = {}
            inverse_keys = {row[1] for row in corrections}
            other_keys = {key for row in corrections for key in (row[0], row[2])}
            if inverse_keys & other_keys:
                raise ValueError
            for original_key, inverse_key, replacement_key, reason in corrections:
                if (
                    any(
                        type(value) is not str or not value
                        for value in (original_key, inverse_key, replacement_key, reason)
                    )
                    or not 0 < len(reason.strip()) <= 500
                    or original_key == replacement_key
                ):
                    raise ValueError
                original, original_row = ordinary[original_key]
                replacement, replacement_row = ordinary[replacement_key]
                inverse = entries[inverse_key]
                expected = JournalEntry(
                    key=inverse_key,
                    event_id=original.event_id,
                    posting_date=original.posting_date,
                    description="Reversal: " + original.description,
                    postings=tuple(Posting(p.account_id, -p.amount_minor) for p in original.postings),
                    origin="reversal",
                    reviewed=True,
                    reason=reason,
                )
                if (
                    inverse != expected
                    or allocations.get(inverse_key)
                    or original_row != replacement_row
                    or original.event_id != replacement.event_id
                    or original.postings[0].account_id != replacement.postings[0].account_id
                    or original.postings[0].amount_minor != replacement.postings[0].amount_minor
                    or accounts[original.postings[1].account_id].kind
                    != accounts[replacement.postings[1].account_id].kind
                    or replacement.reason != reason
                    or original.key.split(":")[1] != replacement.key.split(":")[1]
                ):
                    raise ValueError
                links[original_key] = replacement_key
            replacement_keys = set(links.values())
            if any(
                key.startswith(("review:cash:correction:", "review:card:correction:")) and key not in replacement_keys
                for key in ordinary
            ):
                raise ValueError
            for key in links:
                seen = set()
                while key in links:
                    if key in seen:
                        raise ValueError
                    seen.add(key)
                    key = links[key]
        except (ProfileFormatError, KeyError, TypeError, ValueError):
            raise ProfileFormatError("ordinary_journal_integrity") from None

    def _has_posted_repeat_proof(self, row_id: str) -> bool:
        if self._active_consumed().get(row_id, 0):
            return False
        return (
            self.connection.execute(
                "SELECT 1 FROM PostedRepeatRepairs r JOIN SourceInterpretationActions a ON a.action_id=r.action_id WHERE r.redundant_row_id=? AND a.kind='repeat_repair' LIMIT 1",
                (row_id,),
            ).fetchone()
            is not None
        )

    def source_interpretation_snapshot(
        self, source_sha256: str, *, kind: Literal["cash", "card"], preferences: V2Preferences | None = None
    ) -> SourceInterpretationSnapshot:
        if kind not in {"cash", "card"} or (kind == "card" and type(preferences) is not V2Preferences):
            raise ProfileFormatError("source_interpretation_kind_invalid")
        if self.connection.in_transaction:
            raise ProfileFormatError("source_interpretation_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            actions, _repairs = self._read_source_interpretation_history()
            saved = self.load_import(source_sha256)
            rows = (
                self.cash_activity_review_rows(source_sha256)
                if kind == "cash"
                else self.card_purchase_review_rows(source_sha256, preferences=preferences)
            )
            keys = tuple(dict.fromkeys(row.entry_key for row in rows if row.entry_key is not None))
            entries = tuple(self._ordinary_category_entry(key)[0] for key in keys)
            row_ids = {row.row_id for row in _rows(saved.evidence)}
            statement = isinstance(saved.evidence.payload, StatementPayload)
            return SourceInterpretationSnapshot(
                source_sha256,
                kind,
                rows,
                self.category_accounts(),
                entries,
                tuple(action for action in actions if action.row_id in row_ids),
                self._source_overlap_basis(),
                preferences,
                statement,
                self.overlapping_statement_sources(source_sha256) if statement else (),
            )
        finally:
            self.connection.execute("ROLLBACK")

    def _append_source_interpretation_action(
        self, entry: JournalEntry, row_id: str, kind: str, basis: str, reason: str
    ) -> int:
        inverse = self._retire_journal_entry(entry, reason=reason)
        inverse_payload = self.connection.execute(
            "SELECT payload FROM JournalEntries WHERE key=?", (inverse,)
        ).fetchone()[0]
        action_id = self.connection.execute(
            "SELECT COALESCE(MAX(action_id),0)+1 FROM SourceInterpretationActions"
        ).fetchone()[0]
        fields = (
            action_id,
            row_id,
            entry.key,
            inverse,
            kind,
            basis,
            _digest(_journal_payload(entry).encode()),
            _digest(inverse_payload.encode()),
            reason,
        )
        self.connection.execute(
            "INSERT INTO SourceInterpretationActions(action_id,row_id,entry_key,reversal_key,kind,request_basis,original_sha256,inverse_sha256,reason,record_sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*fields, _transfer_record_digest(*fields)),
        )
        return action_id

    def withdraw_reviewed_interpretation(
        self, entry_key: str, *, expected_basis_sha256: str, reason: str
    ) -> SourceInterpretationAction:
        reason = self._transfer_write_start(reason)
        try:
            actions, _repairs = self._read_source_interpretation_history()
            prior = next((a for a in actions if a.entry_key == entry_key and a.kind == "withdraw"), None)
            if prior is not None:
                request = self.connection.execute(
                    "SELECT request_basis FROM SourceInterpretationActions WHERE action_id=?", (prior.action_id,)
                ).fetchone()[0]
                if request == expected_basis_sha256 and prior.reason == reason:
                    self.connection.execute("COMMIT")
                    return prior
                raise ProfileFormatError("source_interpretation_not_active")
            self._require_source_interpretation_basis(expected_basis_sha256, required=True)
            entry, row_id = self._ordinary_category_entry(entry_key)
            self._source_interpretation_mutating = True
            action_id = self._append_source_interpretation_action(
                entry, row_id, "withdraw", expected_basis_sha256, reason
            )
            self._source_interpretation_mutating = False
            result = next(a for a in self._read_source_interpretation_history()[0] if a.action_id == action_id)
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self._source_interpretation_mutating = False

    def _require_source_interpretation_basis(self, expected: str | None, *, required: bool = False) -> None:
        if required and (type(expected) is not str or re.fullmatch(r"[0-9a-f]{64}", expected) is None):
            raise ProfileFormatError("source_interpretation_version_required")
        if expected is not None and expected != self._source_overlap_basis():
            raise ProfileFormatError("source_interpretation_changed_since_selection")

    def repair_posted_repeat(
        self, retained_row_id: str, redundant_row_id: str, *, expected_basis_sha256: str, reason: str
    ) -> PostedRepeatRepair:
        reason = self._transfer_write_start(reason)
        try:
            _actions, repairs = self._read_source_interpretation_history()
            previous = next(
                (r for r in repairs if r.retained_row_id == retained_row_id and r.redundant_row_id == redundant_row_id),
                None,
            )
            if previous is not None:
                request = self.connection.execute(
                    "SELECT request_basis FROM PostedRepeatRepairs WHERE repair_id=?", (previous.repair_id,)
                ).fetchone()[0]
                latest = self.connection.execute(
                    "SELECT revision_id,decision,retained_row_id FROM SourceOverlapReviews WHERE left_row_id=? AND right_row_id=? ORDER BY revision_id DESC LIMIT 1",
                    tuple(sorted((retained_row_id, redundant_row_id))),
                ).fetchone()
                if (
                    request == expected_basis_sha256
                    and previous.reason == reason
                    and latest == (previous.review_revision_id, "repeat", retained_row_id)
                    and not self._active_consumed().get(redundant_row_id, 0)
                ):
                    self.connection.execute("COMMIT")
                    return previous
            self._require_source_interpretation_basis(expected_basis_sha256, required=True)
            rows, _buckets, _reviews, _aliases = self._source_overlap_index()
            retained, redundant = rows.get(retained_row_id), rows.get(redundant_row_id)
            if (
                retained is None
                or redundant is None
                or not nearby_source_pair(retained, redundant)
                or retained.active_allocated_minor != retained.amount_minor
                or redundant.active_allocated_minor != redundant.amount_minor
            ):
                raise ProfileFormatError("posted_repeat_requires_two_posted_occurrences")

            def active_entry(row_id):
                keys = self.connection.execute(
                    f"SELECT entry_key FROM JournalAllocations WHERE row_id=? AND entry_key NOT IN ({_INACTIVE_JOURNAL_SQL})",
                    (row_id,),
                ).fetchall()
                if len(keys) != 1:
                    raise ProfileFormatError("source_interpretation_unsupported")
                return self._ordinary_category_entry(keys[0][0])[0]

            retained_entry, redundant_entry = active_entry(retained_row_id), active_entry(redundant_row_id)
            self._source_interpretation_mutating = True
            action_id = self._append_source_interpretation_action(
                redundant_entry, redundant_row_id, "repeat_repair", expected_basis_sha256, reason
            )
            result = self._record_source_overlap_review(
                retained_row_id,
                redundant_row_id,
                decision="repeat",
                retained_row_id=retained_row_id,
                expected_basis_sha256=self._source_overlap_basis(),
                reason=reason,
                _owns_transaction=False,
                _repair_proof=True,
            )
            review = self.connection.execute(
                "SELECT * FROM SourceOverlapReviews WHERE revision_id=?", (result.revision_id,)
            ).fetchone()
            repair_id = self.connection.execute(
                "SELECT COALESCE(MAX(repair_id),0)+1 FROM PostedRepeatRepairs"
            ).fetchone()[0]
            fields = (
                repair_id,
                retained_row_id,
                redundant_row_id,
                retained_entry.key,
                redundant_entry.key,
                action_id,
                result.revision_id,
                expected_basis_sha256,
                _digest(_journal_payload(retained_entry).encode()),
                _transfer_record_digest(*review),
                reason,
            )
            self.connection.execute(
                "INSERT INTO PostedRepeatRepairs(repair_id,retained_row_id,redundant_row_id,retained_entry_key,redundant_entry_key,action_id,review_revision_id,request_basis,retained_sha256,review_sha256,reason,record_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (*fields, _transfer_record_digest(*fields)),
            )
            self._source_interpretation_mutating = False
            saved = self._read_source_interpretation_history()[1][0]
            self.connection.execute("COMMIT")
            return saved
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self._source_interpretation_mutating = False

    def cash_activity_review_rows(self, source_sha256: str) -> tuple[CashActivityReviewRow, ...]:
        """Describe source rows for explicit asset cash expense or income review."""
        saved = self.load_import(source_sha256)
        scopes = _cash_review_scopes(saved.evidence)
        bindings = {binding.row_id: binding.ledger_account_id for binding in self.account_bindings(source_sha256)}
        accounts = {
            account_id: (name, kind, role)
            for account_id, name, kind, role in self.connection.execute("SELECT id,name,kind,role FROM Accounts")
        }
        tracking_scopes = dict(self.connection.execute("SELECT id,tracking_scope FROM Accounts"))
        active = self._active_reviewed_entries(source_sha256)
        overlap_blocks = self.source_overlap_posting_blocks(tuple(row.row_id for row in _rows(saved.evidence)))
        result = []
        for row in _rows(saved.evidence):
            account_id = bindings.get(row.row_id)
            financial = accounts.get(account_id) if account_id is not None else None
            account_name = financial[0] if financial is not None else None
            entries = active.get(row.row_id, [])
            entry_key = None
            category_id = None
            purpose = None
            allowed_purposes = ()
            accounting_description = cash_accounting_description(
                saved.evidence.parser_id, cash_tracking_scope(saved.evidence.parser_id), row.description.text
            )
            if entries:
                status = "Already posted to the ledger"
                if len(entries) == 1:
                    entry = entries[0]
                    if (
                        entry.origin == "imported"
                        and entry.reviewed
                        and len(entry.postings) == 2
                        and entry.postings[0].account_id == account_id
                        and entry.postings[0].allocations == (Allocation(row.row_id, row.amount.minor),)
                        and accounts.get(entry.postings[1].account_id, (None, None, None))[1:]
                        in {("expense", "category"), ("income", "category")}
                    ):
                        entry_key = entry.key
                        category_id = entry.postings[1].account_id
                        purpose = _category_purpose(row.amount.minor, accounts[category_id][1])
                        allowed_purposes = (purpose,)
                        status = "Posted: " + accounts[category_id][0]
            elif row.row_id in overlap_blocks:
                status = overlap_blocks[row.row_id]
            elif not scopes.get(row.row_id, False):
                status = "Outside supported asset cash statement scope"
            elif row.row_role != "activity" or row.amount.minor is None or row.amount.minor == 0 or row.components:
                status = "Outside cash activity scope"
            elif row.amount.provenance != "observed":
                status = "Source amount not observed"
            elif row.date_role != "posting_date" or row.date.iso is None:
                status = "Posting date needs review"
            elif account_id is None:
                status = "Assign a financial account first"
            elif tracking_scopes.get(account_id) != cash_tracking_scope(saved.evidence.parser_id):
                status = "Tracking scope needs a supported source interpretation"
            elif financial is None or financial[1:] != ("asset", "financial"):
                status = "Requires a bound asset account"
            elif accounting_description is None:
                status = "Description needs review"
            else:
                status = "Ready for purpose review"
                allowed_purposes = _category_purposes(row.amount.minor)
            result.append(
                CashActivityReviewRow(
                    row.row_id,
                    row.date.iso,
                    row.description.text,
                    row.amount.minor,
                    account_name,
                    status,
                    entry_key,
                    category_id,
                    purpose,
                    allowed_purposes,
                    tracking_scopes.get(account_id),
                    accounting_description,
                    bool(row.description.text),
                )
            )
        return tuple(result)

    def _active_reviewed_entries(self, source_sha256: str) -> dict[str, list[JournalEntry]]:
        self._validate_journal_retirements()
        active: dict[str, list[JournalEntry]] = {}
        for row_id, payload in self.connection.execute(
            "SELECT a.row_id,e.payload FROM JournalAllocations a JOIN JournalEntries e ON e.key=a.entry_key "
            "JOIN SourceObservations o ON o.row_id=a.row_id "
            f"WHERE o.source_sha256=? AND a.entry_key NOT IN ({_INACTIVE_JOURNAL_SQL})",
            (source_sha256,),
        ):
            active.setdefault(row_id, []).append(_decode_journal(payload))
        return active

    def card_purchase_review_rows(
        self, source_sha256: str, *, preferences: V2Preferences
    ) -> tuple[CardPurchaseReviewRow, ...]:
        """List card source rows without interpreting positive movements as income."""
        if type(preferences) is not V2Preferences or type(preferences.allow_assumed_posting_dates) is not bool:
            raise ProfileFormatError("card_purchase_preferences_invalid")
        saved = self.load_import(source_sha256)
        scopes = _card_review_scopes(saved.evidence)
        bindings = {binding.row_id: binding.ledger_account_id for binding in self.account_bindings(source_sha256)}
        accounts = {
            account_id: (name, kind, role)
            for account_id, name, kind, role in self.connection.execute("SELECT id,name,kind,role FROM Accounts")
        }
        tracking_scopes = dict(self.connection.execute("SELECT id,tracking_scope FROM Accounts"))
        active = self._active_reviewed_entries(source_sha256)
        overlap_blocks = self.source_overlap_posting_blocks(tuple(row.row_id for row in _rows(saved.evidence)))
        result = []
        for row in _rows(saved.evidence):
            account_id = bindings.get(row.row_id)
            financial = accounts.get(account_id) if account_id is not None else None
            candidate = posting_date_candidate(row)
            entries = active.get(row.row_id, ())
            entry_key = None
            category_id = None
            effective_date = None
            purpose = None
            allowed_purposes = ()
            if entries:
                status = "Already posted to the ledger"
                if len(entries) == 1:
                    entry = entries[0]
                    if (
                        entry.origin == "imported"
                        and entry.reviewed
                        and len(entry.postings) == 2
                        and entry.postings[0].account_id == account_id
                        and entry.postings[0].allocations == (Allocation(row.row_id, row.amount.minor),)
                        and accounts.get(entry.postings[1].account_id, (None, None, None))[1:]
                        in {("expense", "category"), ("income", "category")}
                    ):
                        entry_key = entry.key
                        category_id = entry.postings[1].account_id
                        purpose = _category_purpose(row.amount.minor, accounts[category_id][1])
                        allowed_purposes = (purpose,)
                        effective_date = entry.posting_date.isoformat()
                        status = "Posted: " + accounts[category_id][0]
            elif row.row_id in overlap_blocks:
                status = overlap_blocks[row.row_id]
            elif not scopes.get(row.row_id, False):
                status = "Outside supported card statement scope"
            elif row.row_role != "activity" or row.components:
                status = "Header or summary charge needs separate review"
            elif row.amount.minor is None or row.amount.minor == 0:
                status = "Amount unavailable or zero"
            elif row.amount.provenance != "observed":
                status = "Source amount not observed"
            elif candidate is None:
                status = "Posting date unavailable"
            elif account_id is None:
                status = "Assign a financial account first"
            elif tracking_scopes.get(account_id) != "account_total":
                status = "Tracking scope needs a supported source interpretation"
            elif financial is None or financial[1:] != ("liability", "financial"):
                status = "Requires a bound card liability account"
            elif not row.description.text:
                status = "Description needs review"
            elif permitted_posting_date(row, preferences) is None:
                status = "Enable assumed dates or enter a corrected date"
                allowed_purposes = _category_purposes(row.amount.minor)
            else:
                status = "Ready for purpose review"
                allowed_purposes = _category_purposes(row.amount.minor)
            source_date = row.transaction_date or row.date
            result.append(
                CardPurchaseReviewRow(
                    row.row_id,
                    source_date.iso,
                    candidate.iso if candidate is not None else None,
                    candidate.provenance if candidate is not None else None,
                    effective_date,
                    row.description.text,
                    row.amount.minor,
                    financial[0] if financial is not None else None,
                    status,
                    entry_key,
                    category_id,
                    purpose,
                    allowed_purposes,
                )
            )
        return tuple(result)

    def _transfer_movements(
        self, preferences: V2Preferences, releasing_entry_keys: tuple[str, ...] = ()
    ) -> tuple[TransferMovement, ...]:
        if type(preferences) is not V2Preferences or type(preferences.allow_assumed_posting_dates) is not bool:
            raise ProfileFormatError("transfer_preferences_invalid")
        accounts = {account.id: account for account in self.financial_accounts()}
        consumed = self._active_consumed()
        for key in releasing_entry_keys:
            for row_id, amount in self.connection.execute(
                "SELECT row_id,amount_minor FROM JournalAllocations WHERE entry_key=?", (key,)
            ):
                consumed[row_id] = consumed.get(row_id, 0) - amount
        overlap_rows, _buckets, _reviews, _aliases = self._source_overlap_index()
        overlap_blocks = self.source_overlap_posting_blocks(tuple(overlap_rows))
        movements = []
        for source_sha256 in self.source_ids():
            evidence = self.load_import(source_sha256).evidence
            cash_scope = _cash_review_scopes(evidence)
            card_scope = _card_review_scopes(evidence)
            if not cash_scope and not card_scope:
                continue
            bindings = {binding.row_id: binding.ledger_account_id for binding in self.account_bindings(source_sha256)}
            for row in _rows(evidence):
                account_id = bindings.get(row.row_id)
                account = accounts.get(account_id)
                amount = row.amount.minor
                if (
                    account is None
                    or row.row_role != "activity"
                    or row.components
                    or type(amount) is not int
                    or amount == 0
                    or row.amount.provenance != "observed"
                    or consumed.get(row.row_id, 0)
                    or row.row_id in overlap_blocks
                ):
                    continue
                if (
                    account.kind == "asset"
                    and account.tracking_scope == cash_tracking_scope(evidence.parser_id)
                    and cash_scope.get(row.row_id, False)
                ):
                    if row.date_role != "posting_date" or row.date.iso is None:
                        continue
                    candidate = row.date
                elif (
                    account.kind == "liability"
                    and account.tracking_scope == "account_total"
                    and amount > 0
                    and card_scope.get(row.row_id, False)
                ):
                    candidate = posting_date_candidate(row)
                    if candidate is None:
                        continue
                else:
                    continue
                movements.append(
                    TransferMovement(
                        row.row_id,
                        source_sha256,
                        account.id,
                        account.name,
                        account.kind,
                        candidate.iso,
                        candidate.provenance,
                        candidate.provenance != "assumed" or preferences.allow_assumed_posting_dates,
                        amount,
                        row.description.text or "Description not printed",
                        account.tracking_scope,
                        bool(row.description.text),
                    )
                )
        return tuple(movements)

    def transfer_candidates(self, *, preferences: V2Preferences, max_day_gap: int = 7) -> tuple[TransferCandidate, ...]:
        self._validate_transfer_history()
        return self._transfer_candidates(preferences=preferences, max_day_gap=max_day_gap)

    def _transfer_candidates(
        self,
        *,
        preferences: V2Preferences,
        max_day_gap: int = 7,
        releasing_entry_keys: tuple[str, ...] = (),
        include_dismissed: bool = False,
    ) -> tuple[TransferCandidate, ...]:
        """Suggest equal, opposite owned-account movements; never infer a link."""
        if type(max_day_gap) is not int or not 0 <= max_day_gap <= 31:
            raise ProfileFormatError("transfer_window_invalid")
        movements = self._transfer_movements(preferences, releasing_entry_keys)
        invalidated = {
            revision
            for record in self._read_binding_corrections()
            for revision in record.invalidated_transfer_review_ids
        }
        decisions = {
            context: decision
            for revision, context, decision in self.connection.execute(
                "SELECT revision_id,context_sha256,decision FROM TransferPairReviews ORDER BY revision_id"
            )
            if revision not in invalidated
        }
        receiving: dict[int, list[TransferMovement]] = {}
        for movement in movements:
            if movement.amount_minor > 0:
                receiving.setdefault(movement.amount_minor, []).append(movement)
        candidates = []
        for outgoing in movements:
            if outgoing.account_kind != "asset" or outgoing.amount_minor >= 0:
                continue
            for incoming in receiving.get(-outgoing.amount_minor, ()):
                if outgoing.account_id == incoming.account_id:
                    continue
                gap = abs((date.fromisoformat(outgoing.posting_date) - date.fromisoformat(incoming.posting_date)).days)
                if gap <= max_day_gap:
                    pair = TransferCandidate(
                        outgoing,
                        incoming,
                        "card payment" if incoming.account_kind == "liability" else "asset transfer",
                        gap,
                        outgoing.date_allowed and incoming.date_allowed,
                    )
                    if include_dismissed or decisions.get(_transfer_pair_context(pair)) != "dismiss":
                        candidates.append(pair)
        return tuple(
            sorted(
                candidates, key=lambda pair: (pair.outgoing.posting_date, pair.outgoing.row_id, pair.incoming.row_id)
            )
        )

    def _post_transfer_untracked(
        self, outgoing_row_id: str, incoming_row_id: str, *, preferences: V2Preferences, reason: str, event_id: str
    ) -> str:
        """Confirm one whole-movement pair atomically, with source-dated clearing if needed."""
        self._require_writable()
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("transfer_reason_required")
        if type(preferences) is not V2Preferences or type(preferences.allow_assumed_posting_dates) is not bool:
            raise ProfileFormatError("transfer_preferences_invalid")
        try:
            existing = tuple(
                _decode_journal(payload)
                for (payload,) in self.connection.execute(
                    "SELECT payload FROM JournalEntries WHERE key IN (?,?,?) ORDER BY key",
                    (event_id + ":same", event_id + ":out", event_id + ":in"),
                )
            )
            if existing:
                allocated = {
                    allocation.observation_id
                    for entry in existing
                    for posting in entry.postings
                    for allocation in posting.allocations
                }
                expected_keys = {event_id + ":same"} if len(existing) == 1 else {event_id + ":out", event_id + ":in"}
                if (
                    {entry.key for entry in existing} != expected_keys
                    or allocated != {outgoing_row_id, incoming_row_id}
                    or any(entry.reason != reason.strip() or entry.event_id != event_id for entry in existing)
                ):
                    raise ProfileFormatError("transfer_conflicts_with_prior_decision")
                return event_id
            self._require_source_overlap_postable((outgoing_row_id, incoming_row_id))
            pair = next(
                (
                    candidate
                    for candidate in self._transfer_candidates(preferences=preferences, max_day_gap=31)
                    if candidate.outgoing.row_id == outgoing_row_id and candidate.incoming.row_id == incoming_row_id
                ),
                None,
            )
            if pair is None:
                raise ProfileFormatError("transfer_pair_unavailable_or_already_posted")
            if not pair.posting_allowed:
                raise ProfileFormatError("transfer_assumed_date_disabled")
            outgoing, incoming = pair.outgoing, pair.incoming
            amount = -outgoing.amount_minor
            out_date = date.fromisoformat(outgoing.posting_date)
            in_date = date.fromisoformat(incoming.posting_date)
            clearing_id = "internal:transfer-clearing:USD"
            if out_date != in_date:
                self._ensure_transfer_clearing()
            accounts = self._ledger_accounts()
            observations = {
                outgoing.row_id: Observation(outgoing.row_id, outgoing.account_id, -amount, out_date),
                incoming.row_id: Observation(incoming.row_id, incoming.account_id, amount, in_date),
            }
            if out_date == in_date:
                entries = (
                    JournalEntry(
                        event_id + ":same",
                        event_id,
                        out_date,
                        "Reviewed owned-account transfer",
                        (
                            Posting(outgoing.account_id, -amount, (Allocation(outgoing.row_id, -amount),)),
                            Posting(incoming.account_id, amount, (Allocation(incoming.row_id, amount),)),
                        ),
                        reviewed=True,
                        reason=reason.strip(),
                    ),
                )
            else:
                entries = (
                    JournalEntry(
                        event_id + ":out",
                        event_id,
                        out_date,
                        "Transfer sent",
                        (
                            Posting(outgoing.account_id, -amount, (Allocation(outgoing.row_id, -amount),)),
                            Posting(clearing_id, amount),
                        ),
                        reviewed=True,
                        reason=reason.strip(),
                    ),
                    JournalEntry(
                        event_id + ":in",
                        event_id,
                        in_date,
                        "Transfer received",
                        (
                            Posting(clearing_id, -amount),
                            Posting(incoming.account_id, amount, (Allocation(incoming.row_id, amount),)),
                        ),
                        reviewed=True,
                        reason=reason.strip(),
                    ),
                )
            consumed = self._active_consumed()
            for entry in entries:
                usage = validate_entry(entry, accounts, observations, consumed)
                for row_id, used in usage.items():
                    consumed[row_id] = consumed.get(row_id, 0) + used
            for entry in entries:
                self.connection.execute(
                    "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (entry.key, _journal_payload(entry))
                )
                for posting in entry.postings:
                    for allocation in posting.allocations:
                        self.connection.execute(
                            "INSERT INTO JournalAllocations VALUES (?,?,?)",
                            (entry.key, allocation.observation_id, allocation.amount_minor),
                        )
            return event_id
        except BaseException as exc:
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("transfer_posting_refused") from None
            raise

    @staticmethod
    def _expected_transfer_entries(pair: TransferCandidate, event_id: str, reason: str) -> tuple[JournalEntry, ...]:
        out, incoming = pair.outgoing, pair.incoming
        amount = -out.amount_minor
        out_date, in_date = date.fromisoformat(out.posting_date), date.fromisoformat(incoming.posting_date)
        clearing = "internal:transfer-clearing:USD"
        outgoing_posting = Posting(out.account_id, -amount, (Allocation(out.row_id, -amount),))
        incoming_posting = Posting(incoming.account_id, amount, (Allocation(incoming.row_id, amount),))
        if out_date == in_date:
            return (
                JournalEntry(
                    event_id + ":same",
                    event_id,
                    out_date,
                    "Reviewed owned-account transfer",
                    (outgoing_posting, incoming_posting),
                    reviewed=True,
                    reason=reason,
                ),
            )
        return (
            JournalEntry(
                event_id + ":out",
                event_id,
                out_date,
                "Transfer sent",
                (outgoing_posting, Posting(clearing, amount)),
                reviewed=True,
                reason=reason,
            ),
            JournalEntry(
                event_id + ":in",
                event_id,
                in_date,
                "Transfer received",
                (Posting(clearing, -amount), incoming_posting),
                reviewed=True,
                reason=reason,
            ),
        )

    def _validate_transfer_pair_source(self, pair: TransferCandidate) -> None:
        self._validate_transfer_movements_source((pair.outgoing, pair.incoming))

    def _validate_transfer_movements_source(self, movements: tuple[TransferMovement, ...]) -> None:
        for movement in movements:
            saved = self.load_import(movement.source_sha256)
            row = next((row for row in _rows(saved.evidence) if row.row_id == movement.row_id), None)
            account = self.connection.execute(
                "SELECT kind,role,tracking_scope FROM Accounts WHERE id=?", (movement.account_id,)
            ).fetchone()
            if row is None or account != (movement.account_kind, "financial", movement.tracking_scope):
                raise ProfileFormatError("transfer_history_integrity")
            candidate = (
                row.date
                if movement.account_kind == "asset" and row.date_role == "posting_date"
                else posting_date_candidate(row)
            )
            scope = (
                _cash_review_scopes(saved.evidence)
                if movement.account_kind == "asset"
                else _card_review_scopes(saved.evidence)
            )
            if (
                not scope.get(row.row_id, False)
                or movement.tracking_scope
                != (
                    cash_tracking_scope(saved.evidence.parser_id)
                    if movement.account_kind == "asset"
                    else "account_total"
                )
                or row.row_role != "activity"
                or row.components
                or row.amount.provenance != "observed"
                or row.amount.minor != movement.amount_minor
                or movement.description != (row.description.text or "Description not printed")
                or movement.source_description_known != bool(row.description.text)
                or candidate is None
                or candidate.iso != movement.posting_date
                or candidate.provenance != movement.date_provenance
                or self.connection.execute(
                    "SELECT source_sha256,row_role,date_role,observed_date,amount_minor FROM SourceObservations WHERE row_id=?",
                    (row.row_id,),
                ).fetchone()
                != (movement.source_sha256, row.row_role, row.date_role, row.date.iso, row.amount.minor)
                or (movement.account_kind == "liability" and movement.amount_minor <= 0)
            ):
                raise ProfileFormatError("transfer_history_integrity")

    def _validate_settlement_categories(self, settlement: TransferSettlement) -> None:
        for fee in settlement.fees:
            if self.connection.execute(
                "SELECT kind,role,currency FROM Accounts WHERE id=?", (fee.category_id,)
            ).fetchone() != ("expense", "category", "USD"):
                raise ProfileFormatError("settlement_fee_requires_expense_category")

    def _validate_transfer_clearing(self) -> None:
        saved = self.connection.execute("SELECT * FROM Accounts WHERE id='internal:transfer-clearing:USD'").fetchone()
        if saved is not None and saved != (
            "internal:transfer-clearing:USD",
            "Transfer clearing",
            "asset",
            "USD",
            "internal",
            "clearing",
            None,
            None,
            "account_total",
        ):
            raise ProfileFormatError("transfer_clearing_integrity")

    def _ensure_transfer_clearing(self) -> None:
        self._validate_transfer_clearing()
        self.connection.execute(
            "INSERT OR IGNORE INTO Accounts VALUES ('internal:transfer-clearing:USD','Transfer clearing','asset','USD','internal','clearing',NULL,NULL,'account_total')"
        )

    def _transfer_pair_context_current(self, pair: TransferCandidate) -> bool:
        for movement in (pair.outgoing, pair.incoming):
            bindings = {b.row_id: b.ledger_account_id for b in self.account_bindings(movement.source_sha256)}
            if bindings.get(movement.row_id) != movement.account_id:
                return False
        return True

    def _read_transfer_history(self) -> tuple[tuple[ReviewedTransferEvent, ...], tuple[TransferPairReview, ...]]:
        self._validate_journal_retirements()
        invalidated_pair_reviews = {
            revision
            for record in self._read_binding_corrections()
            for revision in record.invalidated_transfer_review_ids
        }
        event_rows = self.connection.execute(
            "SELECT event_id,sequence,outgoing_row_id,incoming_row_id,pair_payload,entry_versions,reason,request_basis,record_sha256,created_at FROM TransferEvents ORDER BY sequence"
        ).fetchall()
        for event_id, sequence, out_id, in_id, payload, versions, reason, basis, checksum, created in event_rows:
            if (
                type(sequence) is not int
                or sequence <= 0
                or any(
                    type(value) is not str or not value
                    for value in (event_id, out_id, payload, versions, reason, basis, checksum, created)
                )
                or (in_id is not None and (type(in_id) is not str or not in_id))
            ):
                raise ProfileFormatError("transfer_history_integrity")
        action_rows = self.connection.execute(
            "SELECT event_id,action,replacement_event_id,request_basis,reason,record_sha256,created_at FROM TransferEventActions"
        ).fetchall()
        for event_id, action, replacement, request, reason, checksum, created in action_rows:
            if any(
                type(value) is not str or not value for value in (event_id, action, request, reason, checksum, created)
            ) or (replacement is not None and (type(replacement) is not str or not replacement)):
                raise ProfileFormatError("transfer_history_integrity")
        actions = {row[0]: row for row in action_rows}
        events, event_sequences = [], {}
        event_metadata = {}
        journal_rows = self.connection.execute("SELECT key,payload FROM JournalEntries").fetchall()
        decoded_journals = {key: (_decode_journal(payload), payload) for key, payload in journal_rows}
        if any(type(entry.event_id) is not str for entry, _payload in decoded_journals.values()):
            raise ProfileFormatError("journal_entry_invalid")
        journal_event_ids = {
            entry.event_id
            for entry, _payload in decoded_journals.values()
            if entry.event_id.startswith("review:transfer:") and entry.origin != "reversal"
        }
        if journal_event_ids != {row[0] for row in event_rows}:
            raise ProfileFormatError("transfer_history_integrity")
        inactive = frozenset(key for (key,) in self.connection.execute(_INACTIVE_JOURNAL_SQL))
        retired = dict(self.connection.execute("SELECT original_key,reason FROM JournalRetirements"))
        accounts = self._ledger_accounts()
        for event_id, sequence, out_id, in_id, payload, versions, reason, basis, checksum, created in event_rows:
            if (
                len(payload) > MAX_SETTLEMENT_PAYLOAD
                or len(versions) > 64 * 1024
                or checksum
                != _transfer_record_digest(event_id, sequence, out_id, in_id, payload, versions, reason, basis)
            ):
                raise ProfileFormatError("transfer_history_integrity")
            try:
                generic = json.loads(payload).get("format") == "settlement-2"
                pair = None if generic else _decode_transfer_pair(payload)
                settlement = (
                    decode_settlement(payload) if generic else TransferSettlement(pair.outgoing, (pair.incoming,))
                )
                validate_settlement(settlement)
            except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
                raise ProfileFormatError("transfer_history_integrity") from None
            self._validate_transfer_movements_source(settlement.movements)
            self._validate_settlement_categories(settlement)
            self._validate_expected_destination(settlement.expected_destination)
            if (
                out_id != settlement.outgoing.row_id
                or in_id != (settlement.incoming[0].row_id if settlement.incoming else None)
                or not all(m.date_allowed for m in settlement.movements)
                or type(reason) is not str
                or not 0 < len(reason.strip()) <= 500
                or re.fullmatch(r"[0-9a-f]{64}", basis) is None
                or checksum
                != _transfer_record_digest(event_id, sequence, out_id, in_id, payload, versions, reason, basis)
            ):
                raise ProfileFormatError("transfer_history_integrity")
            expected = (
                settlement_entries(settlement, event_id, reason)
                if generic
                else self._expected_transfer_entries(pair, event_id, reason)
            )
            try:
                manifest = json.loads(versions)
                expected_manifest = [[entry.key, _digest(_journal_payload(entry).encode())] for entry in expected]
                if manifest != expected_manifest:
                    raise ValueError
                event_entries = {
                    key: payload
                    for key, (entry, payload) in decoded_journals.items()
                    if entry.event_id == event_id and entry.origin != "reversal"
                }
                if set(event_entries) != {entry.key for entry in expected}:
                    raise ValueError
                observations = {
                    m.row_id: Observation(m.row_id, m.account_id, m.amount_minor, date.fromisoformat(m.posting_date))
                    for m in settlement.movements
                }
                for entry in expected:
                    if event_entries[entry.key] != _journal_payload(entry):
                        raise ValueError
                    validate_entry(entry, accounts, observations, {})
                    indexed = dict(
                        self.connection.execute(
                            "SELECT row_id,amount_minor FROM JournalAllocations WHERE entry_key=?", (entry.key,)
                        )
                    )
                    allocated = {a.observation_id: a.amount_minor for p in entry.postings for a in p.allocations}
                    if indexed != allocated:
                        raise ValueError
            except (ValueError, TypeError, KeyError, sqlite3.DatabaseError, RecursionError):
                raise ProfileFormatError("transfer_history_integrity") from None
            action = actions.get(event_id)
            status, replacement, action_reason = "active", None, None
            if action is None:
                if any(entry.key in inactive for entry in expected):
                    raise ProfileFormatError("transfer_history_integrity")
                for movement in settlement.movements:
                    bindings = {b.row_id: b.ledger_account_id for b in self.account_bindings(movement.source_sha256)}
                    if bindings.get(movement.row_id) != movement.account_id:
                        raise ProfileFormatError("transfer_history_integrity")
                    expected_usage = [
                        (entry.key, allocation.amount_minor)
                        for entry in expected
                        for posting in entry.postings
                        for allocation in posting.allocations
                        if allocation.observation_id == movement.row_id
                    ]
                    actual_usage = self.connection.execute(
                        f"SELECT entry_key,amount_minor FROM JournalAllocations WHERE row_id=? AND entry_key NOT IN ({_INACTIVE_JOURNAL_SQL})",
                        (movement.row_id,),
                    ).fetchall()
                    if actual_usage != expected_usage:
                        raise ProfileFormatError("transfer_history_integrity")
            else:
                _, kind, replacement, request, action_reason, action_checksum, _created = action
                if (
                    kind not in {"cancel", "replace"}
                    or (kind == "cancel") != (replacement is None)
                    or type(action_reason) is not str
                    or not 0 < len(action_reason.strip()) <= 500
                    or re.fullmatch(r"[0-9a-f]{64}", request) is None
                    or action_checksum
                    != _transfer_record_digest(event_id, checksum, kind, replacement, request, action_reason)
                    or any(retired.get(entry.key) != action_reason for entry in expected)
                ):
                    raise ProfileFormatError("transfer_history_integrity")
                status = "cancelled" if kind == "cancel" else "replaced"
            events.append(
                ReviewedTransferEvent(
                    event_id,
                    pair,
                    tuple(e.key for e in expected),
                    reason,
                    created,
                    checksum,
                    status,
                    replacement,
                    action_reason,
                    settlement,
                )
            )
            event_sequences[event_id] = sequence
            event_metadata[event_id] = (basis, reason)
        if set(actions) - set(event_sequences):
            raise ProfileFormatError("transfer_history_integrity")
        for event in events:
            if event.replacement_event_id is not None and (
                event_sequences.get(event.replacement_event_id, -1) <= event_sequences[event.event_id]
                or event_metadata.get(event.replacement_event_id) != (actions[event.event_id][3], event.action_reason)
            ):
                raise ProfileFormatError("transfer_history_integrity")
        replacements = [event.replacement_event_id for event in events if event.replacement_event_id is not None]
        if len(replacements) != len(set(replacements)):
            raise ProfileFormatError("transfer_history_integrity")
        reviews = []
        for (
            revision,
            out_id,
            in_id,
            payload,
            context,
            decision,
            request,
            reason,
            checksum,
            created,
        ) in self.connection.execute(
            "SELECT revision_id,outgoing_row_id,incoming_row_id,pair_payload,context_sha256,decision,request_basis,reason,record_sha256,created_at FROM TransferPairReviews ORDER BY revision_id DESC"
        ):
            if (
                type(revision) is not int
                or revision <= 0
                or any(
                    type(value) is not str or not value
                    for value in (out_id, in_id, payload, context, decision, request, reason, checksum, created)
                )
            ):
                raise ProfileFormatError("transfer_history_integrity")
            pair = _decode_transfer_pair(payload)
            self._validate_transfer_pair_source(pair)
            if (
                out_id != pair.outgoing.row_id
                or in_id != pair.incoming.row_id
                or context != _transfer_pair_context(pair)
                or decision not in {"dismiss", "reopen"}
                or type(reason) is not str
                or not 0 < len(reason.strip()) <= 500
                or re.fullmatch(r"[0-9a-f]{64}", request) is None
                or checksum
                != _transfer_record_digest(revision, out_id, in_id, payload, context, decision, request, reason)
            ):
                raise ProfileFormatError("transfer_history_integrity")
            reviews.append(
                TransferPairReview(
                    revision,
                    pair,
                    decision,
                    reason,
                    created,
                    checksum,
                    revision not in invalidated_pair_reviews and self._transfer_pair_context_current(pair),
                )
            )
        return tuple(reversed(events)), tuple(reviews)

    def _validate_transfer_history(self) -> None:
        if not self._transfer_mutating:
            self._read_transfer_history()

    def _transfer_review_basis(self) -> str:
        return _transfer_record_digest("v2-transfer-review-1", self._source_overlap_basis())

    def transfer_review_snapshot(
        self, *, preferences: V2Preferences, max_day_gap: int = 7, replacing_event_id: str | None = None
    ) -> TransferReviewSnapshot:
        if self.connection.in_transaction:
            raise ProfileFormatError("transfer_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            events, reviews = self._read_transfer_history()
            releasing = ()
            if replacing_event_id is not None:
                selected = next((e for e in events if e.event_id == replacing_event_id and e.status == "active"), None)
                if selected is None:
                    raise ProfileFormatError("transfer_event_not_active")
                releasing = selected.entry_keys
            return TransferReviewSnapshot(
                self._transfer_candidates(
                    preferences=preferences, max_day_gap=max_day_gap, releasing_entry_keys=releasing
                ),
                events,
                reviews,
                self._transfer_review_basis(),
            )
        finally:
            self.connection.execute("ROLLBACK")

    def transfer_history(self) -> tuple[ReviewedTransferEvent, ...]:
        return self.transfer_review_snapshot(preferences=V2Preferences(), max_day_gap=31).events

    def settlement_review_snapshot(
        self, *, preferences: V2Preferences, replacing_event_id: str | None = None
    ) -> SettlementReviewSnapshot:
        if self.connection.in_transaction:
            raise ProfileFormatError("transfer_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            events, _reviews = self._read_transfer_history()
            releasing = self._settlement_releasing_keys(events, replacing_event_id)
            return SettlementReviewSnapshot(
                self._transfer_movements(preferences, releasing),
                events,
                tuple(c for c in self.category_accounts() if c.kind == "expense"),
                self._transfer_review_basis(),
                self.financial_accounts(),
            )
        finally:
            self.connection.execute("ROLLBACK")

    @staticmethod
    def _settlement_releasing_keys(events, event_id: str | None) -> tuple[str, ...]:
        if event_id is None:
            return ()
        selected = next((e for e in events if e.event_id == event_id and e.status == "active"), None)
        if selected is None:
            raise ProfileFormatError("transfer_event_not_active")
        return selected.entry_keys

    @staticmethod
    def _settlement_request(
        outgoing_row_id: str,
        incoming_row_ids: tuple[str, ...],
        fees: tuple[SettlementFee, ...],
        expected_destination: ExpectedOwnedDestination | None = None,
    ):
        if (
            type(outgoing_row_id) is not str
            or not outgoing_row_id
            or type(incoming_row_ids) is not tuple
            or not 0 <= len(incoming_row_ids) <= 32
            or any(type(row_id) is not str or not row_id for row_id in incoming_row_ids)
            or len(set(incoming_row_ids)) != len(incoming_row_ids)
            or outgoing_row_id in incoming_row_ids
            or type(fees) is not tuple
            or len(fees) > 64
            or any(not isinstance(fee, SettlementFee) for fee in fees)
        ):
            raise ProfileFormatError("settlement_manifest_invalid")
        if expected_destination is not None and (
            not isinstance(expected_destination, ExpectedOwnedDestination)
            or type(expected_destination.account_id) is not str
            or not 0 < len(expected_destination.account_id) <= 80
            or type(expected_destination.reference) is not str
            or not 0 < len(expected_destination.reference.strip()) <= 500
            or expected_destination.reference != expected_destination.reference.strip()
            or expected_destination.ownership_confirmed is not True
            or type(expected_destination.account_name) is not str
            or expected_destination.account_kind not in {None, "asset", "liability"}
            or expected_destination.tracking_scope
            not in {None, "account_total", "cash_component", "principal_component"}
        ):
            raise ProfileFormatError("settlement_expected_destination_required")
        if not incoming_row_ids and expected_destination is None:
            raise ProfileFormatError("settlement_expected_destination_required")
        if incoming_row_ids and expected_destination is not None:
            raise ProfileFormatError("settlement_expected_destination_requires_missing_receipts")
        try:
            normalized_fees = tuple(sorted(fees, key=fee_order))
        except (TypeError, ValueError):
            raise ProfileFormatError("settlement_fee_invalid") from None
        return outgoing_row_id, tuple(sorted(incoming_row_ids)), normalized_fees, expected_destination

    @staticmethod
    def _settlement_matches(settlement: TransferSettlement, request) -> bool:
        return (settlement.outgoing.row_id, tuple(m.row_id for m in settlement.incoming), settlement.fees) == request[
            :3
        ] and (settlement.expected_destination.request_key if settlement.expected_destination else None) == (
            request[3].request_key if request[3] else None
        )

    def _capture_expected_destination(
        self, destination: ExpectedOwnedDestination | None, outgoing_account_id: str
    ) -> ExpectedOwnedDestination | None:
        if destination is None:
            return None
        saved = self.connection.execute(
            "SELECT name,kind,tracking_scope FROM Accounts WHERE id=? AND role='financial' AND currency='USD'",
            (destination.account_id,),
        ).fetchone()
        if saved is None or destination.account_id == outgoing_account_id:
            raise ProfileFormatError("settlement_expected_destination_invalid")
        name, kind, scope = saved
        if (
            (destination.account_name and destination.account_name != name)
            or (destination.account_kind is not None and destination.account_kind != kind)
            or (destination.tracking_scope is not None and destination.tracking_scope != scope)
        ):
            raise ProfileFormatError("settlement_expected_destination_context_changed")
        return ExpectedOwnedDestination(destination.account_id, destination.reference, True, name, kind, scope)

    def _validate_expected_destination(self, destination: ExpectedOwnedDestination | None) -> None:
        if destination is not None and self.connection.execute(
            "SELECT kind,tracking_scope,role,currency FROM Accounts WHERE id=?", (destination.account_id,)
        ).fetchone() != (destination.account_kind, destination.tracking_scope, "financial", "USD"):
            raise ProfileFormatError("transfer_history_integrity")

    def _settlement_accounts(self, settlement: TransferSettlement, *, materialize: bool) -> dict[str, LedgerAccount]:
        for fee in settlement.fees:
            if materialize and builtin_category(fee.category_id) is not None:
                self.ensure_builtin_category(fee.category_id)
        accounts = self._ledger_accounts()
        for fee in settlement.fees:
            saved = self.connection.execute(
                "SELECT kind,role,currency FROM Accounts WHERE id=?", (fee.category_id,)
            ).fetchone()
            category = builtin_category(fee.category_id)
            if saved is None and category is not None and not materialize:
                accounts[category.account_id] = LedgerAccount(
                    category.account_id, category.name, AccountKind.EXPENSE, "USD"
                )
            elif saved != ("expense", "category", "USD"):
                raise ProfileFormatError("settlement_fee_requires_expense_category")
        return accounts

    def _build_settlement(self, request, preferences: V2Preferences, releasing: tuple[str, ...]) -> TransferSettlement:
        out_id, in_ids, fees, expected_destination = request
        movements = {m.row_id: m for m in self._transfer_movements(preferences, releasing)}
        try:
            destination = self._capture_expected_destination(expected_destination, movements[out_id].account_id)
            settlement = TransferSettlement(
                movements[out_id], tuple(movements[row_id] for row_id in in_ids), fees, destination
            )
            validate_settlement(settlement)
        except KeyError:
            raise ProfileFormatError("settlement_movement_unavailable_or_already_posted") from None
        except (TypeError, ValueError) as exc:
            raise ProfileFormatError(str(exc)) from None
        if not all(m.date_allowed for m in settlement.movements):
            raise ProfileFormatError("transfer_assumed_date_disabled")
        self._require_source_overlap_postable(settlement.row_ids)
        return settlement

    def preview_reviewed_settlement(
        self,
        outgoing_row_id: str,
        incoming_row_ids: tuple[str, ...],
        *,
        fees: tuple[SettlementFee, ...] = (),
        preferences: V2Preferences,
        expected_basis_sha256: str,
        replacing_event_id: str | None = None,
        reason: str = "Preview only",
        expected_destination: ExpectedOwnedDestination | None = None,
    ) -> SettlementPreview:
        request = self._settlement_request(outgoing_row_id, incoming_row_ids, fees, expected_destination)
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("transfer_reason_required")
        if self.connection.in_transaction:
            raise ProfileFormatError("transfer_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            events, _reviews = self._read_transfer_history()
            self._require_transfer_basis(expected_basis_sha256, required=True)
            releasing = self._settlement_releasing_keys(events, replacing_event_id)
            settlement = self._build_settlement(request, preferences, releasing)
            accounts = self._settlement_accounts(settlement, materialize=False)
            accounts.setdefault(
                "internal:transfer-clearing:USD",
                LedgerAccount(
                    "internal:transfer-clearing:USD", "Transfer clearing", AccountKind.ASSET, "USD", purpose="clearing"
                ),
            )
            entries = settlement_entries(settlement, "preview:settlement", reason.strip())
            self._validate_settlement_entries_for_posting(settlement, entries, accounts, releasing)
            return SettlementPreview(settlement, entries)
        finally:
            self.connection.execute("ROLLBACK")

    def _validate_settlement_entries_for_posting(self, settlement, entries, accounts, releasing=()) -> None:
        consumed = self._active_consumed()
        for key in releasing:
            for row_id, amount in self.connection.execute(
                "SELECT row_id,amount_minor FROM JournalAllocations WHERE entry_key=?", (key,)
            ):
                consumed[row_id] = consumed.get(row_id, 0) - amount
        observations = {
            m.row_id: Observation(m.row_id, m.account_id, m.amount_minor, date.fromisoformat(m.posting_date))
            for m in settlement.movements
        }
        try:
            for entry in entries:
                usage = validate_entry(entry, accounts, observations, consumed)
                for row_id, amount in usage.items():
                    consumed[row_id] = consumed.get(row_id, 0) + amount
        except LedgerError:
            raise ProfileFormatError("settlement_posting_refused") from None

    def _record_settlement_event(self, settlement: TransferSettlement, reason: str, basis: str) -> str:
        self._ensure_transfer_clearing()
        accounts = self._settlement_accounts(settlement, materialize=True)
        sequence = self.connection.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM TransferEvents").fetchone()[0]
        payload = settlement_payload(settlement)
        event_id = "review:transfer:" + _digest(payload.encode()) + f":v{sequence}"
        entries = settlement_entries(settlement, event_id, reason)
        self._validate_settlement_entries_for_posting(settlement, entries, accounts)
        for entry in entries:
            self.connection.execute(
                "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (entry.key, _journal_payload(entry))
            )
            for posting in entry.postings:
                for allocation in posting.allocations:
                    self.connection.execute(
                        "INSERT INTO JournalAllocations VALUES (?,?,?)",
                        (entry.key, allocation.observation_id, allocation.amount_minor),
                    )
        manifest = json.dumps([[e.key, _digest(_journal_payload(e).encode())] for e in entries], separators=(",", ":"))
        out_id, in_id = settlement.outgoing.row_id, settlement.incoming[0].row_id if settlement.incoming else None
        checksum = _transfer_record_digest(event_id, sequence, out_id, in_id, payload, manifest, reason, basis)
        self.connection.execute(
            "INSERT INTO TransferEvents(event_id,sequence,outgoing_row_id,incoming_row_id,pair_payload,entry_versions,reason,request_basis,record_sha256) VALUES (?,?,?,?,?,?,?,?,?)",
            (event_id, sequence, out_id, in_id, payload, manifest, reason, basis, checksum),
        )
        return event_id

    def post_reviewed_settlement(
        self,
        outgoing_row_id: str,
        incoming_row_ids: tuple[str, ...],
        *,
        fees: tuple[SettlementFee, ...] = (),
        preferences: V2Preferences,
        expected_basis_sha256: str,
        reason: str,
        expected_destination: ExpectedOwnedDestination | None = None,
    ) -> str:
        request = self._settlement_request(outgoing_row_id, incoming_row_ids, fees, expected_destination)
        reason = self._transfer_write_start(reason)
        try:
            events, _reviews = self._read_transfer_history()
            active = next(
                (e for e in events if e.status == "active" and self._settlement_matches(e.settlement, request)), None
            )
            if active is not None:
                original_basis = self.connection.execute(
                    "SELECT request_basis FROM TransferEvents WHERE event_id=?", (active.event_id,)
                ).fetchone()[0]
                if active.reason != reason:
                    raise ProfileFormatError("transfer_conflicts_with_prior_decision")
                if expected_basis_sha256 != original_basis:
                    self._require_transfer_basis(expected_basis_sha256, required=True)
                self.connection.execute("COMMIT")
                return active.event_id
            basis = self._require_transfer_basis(expected_basis_sha256, required=True)
            settlement = self._build_settlement(request, preferences, ())
            self._transfer_mutating = True
            event_id = self._record_settlement_event(settlement, reason, basis)
            self._transfer_mutating = False
            self._read_transfer_history()
            self.connection.execute("COMMIT")
            return event_id
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self._transfer_mutating = False

    def replace_reviewed_settlement(
        self,
        event_id: str,
        outgoing_row_id: str,
        incoming_row_ids: tuple[str, ...],
        *,
        fees: tuple[SettlementFee, ...] = (),
        preferences: V2Preferences,
        expected_basis_sha256: str,
        reason: str,
        expected_destination: ExpectedOwnedDestination | None = None,
    ) -> str:
        request = self._settlement_request(outgoing_row_id, incoming_row_ids, fees, expected_destination)
        reason = self._transfer_write_start(reason)
        try:
            events, _reviews = self._read_transfer_history()
            event = next((e for e in events if e.event_id == event_id), None)
            if event is None:
                raise ProfileFormatError("transfer_event_missing")
            if event.status == "replaced":
                replacement = next(e for e in events if e.event_id == event.replacement_event_id)
                action = self.connection.execute(
                    "SELECT request_basis,reason FROM TransferEventActions WHERE event_id=?", (event_id,)
                ).fetchone()
                if (
                    action == (expected_basis_sha256, reason)
                    and replacement.status == "active"
                    and self._settlement_matches(replacement.settlement, request)
                ):
                    self.connection.execute("COMMIT")
                    return replacement.event_id
            if event.status != "active":
                raise ProfileFormatError("transfer_event_not_active")
            basis = self._require_transfer_basis(expected_basis_sha256, required=True)
            if self._settlement_matches(event.settlement, request):
                raise ProfileFormatError("settlement_replacement_requires_changed_manifest")
            settlement = self._build_settlement(request, preferences, event.entry_keys)
            self._transfer_mutating = True
            for key in event.entry_keys:
                payload = self.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[
                    0
                ]
                self._retire_journal_entry(_decode_journal(payload), reason=reason)
            replacement_id = self._record_settlement_event(settlement, reason, basis)
            self._record_transfer_action(event, "replace", replacement_id, basis, reason)
            self._transfer_mutating = False
            self._read_transfer_history()
            self.connection.execute("COMMIT")
            return replacement_id
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self._transfer_mutating = False

    def _transfer_write_start(self, reason: str) -> str:
        self._require_writable()
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("transfer_reason_required")
        if self.connection.in_transaction:
            raise ProfileFormatError("transfer_requires_committed_snapshot")
        self.connection.execute("BEGIN IMMEDIATE")
        return reason.strip()

    def _require_transfer_basis(self, expected: str | None, *, required: bool = False) -> str:
        if required and (type(expected) is not str or re.fullmatch(r"[0-9a-f]{64}", expected) is None):
            raise ProfileFormatError("transfer_review_version_required")
        basis = self._transfer_review_basis()
        if expected is not None and expected != basis:
            raise ProfileFormatError("transfer_review_changed_since_selection")
        return basis

    def _record_transfer_event(
        self, out_id: str, in_id: str, preferences: V2Preferences, reason: str, basis: str
    ) -> str:
        self._require_source_overlap_postable((out_id, in_id))
        pair = next(
            (
                p
                for p in self._transfer_candidates(preferences=preferences, max_day_gap=31)
                if p.outgoing.row_id == out_id and p.incoming.row_id == in_id
            ),
            None,
        )
        if pair is None:
            raise ProfileFormatError("transfer_pair_unavailable_or_already_posted")
        if not pair.posting_allowed:
            raise ProfileFormatError("transfer_assumed_date_disabled")
        sequence = self.connection.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM TransferEvents").fetchone()[0]
        event_id = "review:transfer:" + _digest((out_id + ":" + in_id).encode()) + f":v{sequence}"
        self._post_transfer_untracked(out_id, in_id, preferences=preferences, reason=reason, event_id=event_id)
        payload = _transfer_pair_payload(pair)
        manifest = json.dumps(
            [
                [e.key, _digest(_journal_payload(e).encode())]
                for e in self._expected_transfer_entries(pair, event_id, reason)
            ],
            separators=(",", ":"),
        )
        checksum = _transfer_record_digest(event_id, sequence, out_id, in_id, payload, manifest, reason, basis)
        self.connection.execute(
            "INSERT INTO TransferEvents(event_id,sequence,outgoing_row_id,incoming_row_id,pair_payload,entry_versions,reason,request_basis,record_sha256) VALUES (?,?,?,?,?,?,?,?,?)",
            (event_id, sequence, out_id, in_id, payload, manifest, reason, basis, checksum),
        )
        return event_id

    def post_reviewed_transfer(
        self,
        outgoing_row_id: str,
        incoming_row_id: str,
        *,
        preferences: V2Preferences,
        reason: str,
        expected_basis_sha256: str | None = None,
    ) -> str:
        reason = self._transfer_write_start(reason)
        try:
            events, _reviews = self._read_transfer_history()
            active = next(
                (
                    e
                    for e in events
                    if e.status == "active"
                    and e.pair is not None
                    and e.pair.outgoing.row_id == outgoing_row_id
                    and e.pair.incoming.row_id == incoming_row_id
                ),
                None,
            )
            if active is not None:
                original_basis = self.connection.execute(
                    "SELECT request_basis FROM TransferEvents WHERE event_id=?", (active.event_id,)
                ).fetchone()[0]
                if active.reason != reason:
                    raise ProfileFormatError("transfer_conflicts_with_prior_decision")
                if expected_basis_sha256 is not None and expected_basis_sha256 != original_basis:
                    self._require_transfer_basis(expected_basis_sha256)
                self.connection.execute("COMMIT")
                return active.event_id
            basis = self._require_transfer_basis(expected_basis_sha256)
            self._transfer_mutating = True
            event_id = self._record_transfer_event(outgoing_row_id, incoming_row_id, preferences, reason, basis)
            self._transfer_mutating = False
            self._read_transfer_history()
            self.connection.execute("COMMIT")
            return event_id
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self._transfer_mutating = False

    def record_transfer_pair_review(
        self,
        outgoing_row_id: str,
        incoming_row_id: str,
        *,
        decision: Literal["dismiss", "reopen"],
        expected_basis_sha256: str,
        preferences: V2Preferences,
        reason: str,
    ) -> TransferPairReview:
        reason = self._transfer_write_start(reason)
        try:
            if decision not in {"dismiss", "reopen"}:
                raise ProfileFormatError("transfer_pair_decision_invalid")
            _events, reviews = self._read_transfer_history()
            pair = next(
                (
                    p
                    for p in self._transfer_candidates(preferences=preferences, max_day_gap=31, include_dismissed=True)
                    if p.outgoing.row_id == outgoing_row_id and p.incoming.row_id == incoming_row_id
                ),
                None,
            )
            if pair is None:
                raise ProfileFormatError("transfer_pair_unavailable_or_already_posted")
            context = _transfer_pair_context(pair)
            latest = next((r for r in reviews if r.context_current and _transfer_pair_context(r.pair) == context), None)
            if latest is not None and latest.decision == decision and latest.reason == reason:
                request = self.connection.execute(
                    "SELECT request_basis FROM TransferPairReviews WHERE revision_id=?", (latest.revision_id,)
                ).fetchone()[0]
                if request == expected_basis_sha256:
                    self.connection.execute("COMMIT")
                    return latest
            basis = self._require_transfer_basis(expected_basis_sha256, required=True)
            if decision == "reopen" and (latest is None or latest.decision != "dismiss"):
                raise ProfileFormatError("transfer_pair_not_dismissed")
            if latest is not None and latest.decision == decision:
                raise ProfileFormatError("transfer_pair_decision_unchanged")
            revision = self.connection.execute(
                "SELECT COALESCE(MAX(revision_id),0)+1 FROM TransferPairReviews"
            ).fetchone()[0]
            payload = _transfer_pair_payload(pair)
            checksum = _transfer_record_digest(
                revision, outgoing_row_id, incoming_row_id, payload, context, decision, basis, reason
            )
            self.connection.execute(
                "INSERT INTO TransferPairReviews(revision_id,outgoing_row_id,incoming_row_id,pair_payload,context_sha256,decision,request_basis,reason,record_sha256) VALUES (?,?,?,?,?,?,?,?,?)",
                (revision, outgoing_row_id, incoming_row_id, payload, context, decision, basis, reason, checksum),
            )
            saved = self._read_transfer_history()[1][0]
            self.connection.execute("COMMIT")
            return saved
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def _record_transfer_action(
        self, event: ReviewedTransferEvent, action: str, replacement: str | None, basis: str, reason: str
    ) -> None:
        checksum = _transfer_record_digest(event.event_id, event.version, action, replacement, basis, reason)
        self.connection.execute(
            "INSERT INTO TransferEventActions(event_id,action,replacement_event_id,request_basis,reason,record_sha256) VALUES (?,?,?,?,?,?)",
            (event.event_id, action, replacement, basis, reason, checksum),
        )

    def withdraw_reviewed_transfer(
        self, event_id: str, *, expected_basis_sha256: str, reason: str
    ) -> ReviewedTransferEvent:
        reason = self._transfer_write_start(reason)
        try:
            events, _reviews = self._read_transfer_history()
            event = next((e for e in events if e.event_id == event_id), None)
            if event is None:
                raise ProfileFormatError("transfer_event_missing")
            if event.status == "cancelled":
                action = self.connection.execute(
                    "SELECT request_basis,reason FROM TransferEventActions WHERE event_id=?", (event_id,)
                ).fetchone()
                if action == (expected_basis_sha256, reason):
                    self.connection.execute("COMMIT")
                    return event
            if event.status != "active":
                raise ProfileFormatError("transfer_event_not_active")
            basis = self._require_transfer_basis(expected_basis_sha256, required=True)
            self._transfer_mutating = True
            for key in event.entry_keys:
                payload = self.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[
                    0
                ]
                self._retire_journal_entry(_decode_journal(payload), reason=reason)
            self._record_transfer_action(event, "cancel", None, basis, reason)
            self._transfer_mutating = False
            saved = next(e for e in self._read_transfer_history()[0] if e.event_id == event_id)
            self.connection.execute("COMMIT")
            return saved
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self._transfer_mutating = False

    def replace_reviewed_transfer(
        self,
        event_id: str,
        outgoing_row_id: str,
        incoming_row_id: str,
        *,
        expected_basis_sha256: str,
        preferences: V2Preferences,
        reason: str,
    ) -> str:
        reason = self._transfer_write_start(reason)
        try:
            events, _reviews = self._read_transfer_history()
            event = next((e for e in events if e.event_id == event_id), None)
            if event is None:
                raise ProfileFormatError("transfer_event_missing")
            if event.status == "replaced":
                replacement = next(e for e in events if e.event_id == event.replacement_event_id)
                action = self.connection.execute(
                    "SELECT request_basis,reason FROM TransferEventActions WHERE event_id=?", (event_id,)
                ).fetchone()
                if (
                    action == (expected_basis_sha256, reason)
                    and replacement.status == "active"
                    and replacement.pair is not None
                    and replacement.pair.outgoing.row_id == outgoing_row_id
                    and replacement.pair.incoming.row_id == incoming_row_id
                ):
                    self.connection.execute("COMMIT")
                    return replacement.event_id
            if event.status != "active":
                raise ProfileFormatError("transfer_event_not_active")
            basis = self._require_transfer_basis(expected_basis_sha256, required=True)
            if event.pair is not None and (event.pair.outgoing.row_id, event.pair.incoming.row_id) == (
                outgoing_row_id,
                incoming_row_id,
            ):
                raise ProfileFormatError("transfer_replacement_requires_different_pair")
            self._transfer_mutating = True
            for key in event.entry_keys:
                payload = self.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[
                    0
                ]
                self._retire_journal_entry(_decode_journal(payload), reason=reason)
            replacement_id = self._record_transfer_event(outgoing_row_id, incoming_row_id, preferences, reason, basis)
            self._record_transfer_action(event, "replace", replacement_id, basis, reason)
            self._transfer_mutating = False
            self._read_transfer_history()
            self.connection.execute("COMMIT")
            return replacement_id
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self._transfer_mutating = False

    def _journal_entries_in_period(self, start: date, end: date):
        self._validate_journal_retirements()
        self._validate_opening_decision_histories()
        self._validate_transfer_history()
        self._validate_source_interpretation_history()
        self._validate_common_journal_read()
        if type(start) is not date or type(end) is not date or start >= end:
            raise ProfileFormatError("report_period_invalid")
        for (payload,) in self.connection.execute("SELECT payload FROM JournalEntries"):
            entry = _decode_journal(payload)
            if start <= entry.posting_date < end:
                yield entry

    def _unallocated_activity_counts(self) -> tuple[int, int]:
        self._validate_journal_retirements()
        self._validate_transfer_history()
        self._validate_source_interpretation_history()
        return self.connection.execute(
            "SELECT COUNT(*),COUNT(DISTINCT o.source_sha256) FROM SourceObservations o "
            "LEFT JOIN ("
            "SELECT a.row_id,SUM(a.amount_minor) AS used FROM JournalAllocations a "
            f"WHERE a.entry_key NOT IN ({_INACTIVE_JOURNAL_SQL}) GROUP BY a.row_id"
            ") active ON active.row_id=o.row_id "
            "WHERE o.row_role='activity' AND (active.used IS NULL OR active.used<>o.amount_minor)"
        ).fetchone()

    def reviewed_category_summary(
        self, *, kind: Literal["expense", "income"], start: date, end: date
    ) -> ReviewedCategorySummary:
        """Summarize reviewed category postings in the category's natural direction."""
        if kind not in {"expense", "income"}:
            raise ProfileFormatError("report_category_kind_invalid")
        categories = {category.id: category for category in self.category_accounts() if category.kind == kind}
        totals = dict.fromkeys(categories, 0)
        excluded_unreviewed = 0
        direction = 1 if kind == "expense" else -1
        for entry in self._journal_entries_in_period(start, end):
            if not entry.reviewed:
                excluded_unreviewed += any(posting.account_id in totals for posting in entry.postings)
                continue
            for posting in entry.postings:
                if posting.account_id in totals:
                    totals[posting.account_id] += direction * posting.amount_minor
        unresolved_rows, unresolved_sources = self._unallocated_activity_counts()
        return ReviewedCategorySummary(
            start,
            end,
            kind,
            tuple(
                ReviewedCategoryTotal(category_id, category.name, totals[category_id])
                for category_id, category in categories.items()
            ),
            sum(totals.values()),
            unresolved_rows,
            unresolved_sources,
            excluded_unreviewed,
        )

    def monthly_budget_summary(self, month: date) -> MonthlyBudgetSummary:
        """Compare effective expense targets with reviewed spending in a whole month."""
        self._budget_month(month)
        if month.year == 9999 and month.month == 12:
            raise ProfileFormatError("report_period_invalid")
        next_month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        spending = self.reviewed_category_summary(kind="expense", start=month, end=next_month)
        targets = {target.category_id: target for target in self.category_budget_targets(month)}
        rows = tuple(
            MonthlyBudgetRow(
                category.category_id,
                category.name,
                targets[category.category_id].amount_minor,
                targets[category.category_id].effective_month,
                category.amount_minor,
                (
                    targets[category.category_id].amount_minor - category.amount_minor
                    if targets[category.category_id].amount_minor is not None
                    else None
                ),
            )
            for category in spending.categories
        )
        return MonthlyBudgetSummary(
            month,
            rows,
            sum(row.target_minor for row in rows if row.target_minor is not None)
            if all(row.target_minor is not None for row in rows)
            else None,
            spending.total_minor,
            spending.activity_rows_without_full_allocation,
            spending.sources_with_incomplete_activity,
            spending.excluded_unreviewed_entries,
        )

    def financial_journal_summary(self, *, start: date, end: date) -> FinancialJournalSummary:
        """Show reviewed account postings, keeping openings apart from period activity."""
        accounts = {account.id: account for account in self.financial_accounts()}
        nonopening = dict.fromkeys(accounts, 0)
        opening = dict.fromkeys(accounts, 0)
        opening_seen: set[str] = set()
        excluded_unreviewed = 0
        opening_keys = self._opening_journal_keys()
        for entry in self._journal_entries_in_period(start, end):
            financial_postings = tuple(posting for posting in entry.postings if posting.account_id in accounts)
            if not entry.reviewed:
                excluded_unreviewed += bool(financial_postings)
                continue
            target = opening if entry.key in opening_keys else nonopening
            for posting in financial_postings:
                target[posting.account_id] += posting.amount_minor
                if entry.key in opening_keys:
                    opening_seen.add(posting.account_id)
        unresolved_rows, unresolved_sources = self._unallocated_activity_counts()
        return FinancialJournalSummary(
            start,
            end,
            tuple(
                FinancialJournalMovement(
                    account_id,
                    account.name,
                    account.kind,
                    nonopening[account_id],
                    opening[account_id] if account_id in opening_seen else None,
                )
                for account_id, account in accounts.items()
            ),
            unresolved_rows,
            unresolved_sources,
            excluded_unreviewed,
        )

    def account_positions(self, *, as_of: date) -> AccountPositionsSummary:
        """Read current reviewed books through an inclusive accounting-date cutoff.

        Positions are opening-based journal amounts, never certified bank balances.
        Pending evidence counts cover all saved dates and include supporting repeats.
        Each history uses deterministic date/key order; same-day running totals do
        not imply intraday source timing. Corrections restate accounting-date history,
        rather than reconstructing what the user knew at a past date.
        """
        if type(as_of) is not date:
            raise ProfileFormatError("report_as_of_invalid")
        if self.connection.in_transaction:
            raise ProfileFormatError("positions_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            return self._account_positions(as_of)
        finally:
            self.connection.execute("ROLLBACK")

    def _account_positions(self, as_of: date) -> AccountPositionsSummary:
        self._validate_journal_retirements()
        self._validate_opening_decision_histories()
        self._validate_common_journal_read()
        accounts = self.financial_accounts()
        entries = tuple(
            sorted(
                (
                    _decode_journal(payload)
                    for (payload,) in self.connection.execute("SELECT payload FROM JournalEntries")
                ),
                key=lambda entry: (entry.posting_date, entry.key),
            )
        )
        originals, reversals, replacements = set(), set(), set()
        for original, reversal, replacement in self.connection.execute(
            "SELECT original_key,reversal_key,replacement_key FROM JournalCorrections"
        ):
            originals.add(original)
            reversals.add(reversal)
            replacements.add(replacement)
        retired = dict(self.connection.execute("SELECT original_key,reversal_key FROM JournalRetirements"))
        retirement_reversals = set(retired.values())
        inactive = self._inactive_journal_keys()
        consumed = self._active_consumed()
        pending = dict.fromkeys((account.id for account in accounts), 0)
        latest_activity: dict[str, date] = {}
        unbound = 0
        for source_id in self.source_ids():
            bindings = {binding.row_id: binding.ledger_account_id for binding in self.account_bindings(source_id)}
            for row in _rows(self.load_import(source_id).evidence):
                if row.row_role != "activity":
                    continue
                account_id = bindings.get(row.row_id)
                if account_id not in pending:
                    unbound += 1
                    continue
                if row.date.iso is not None:
                    observed = date.fromisoformat(row.date.iso)
                    latest_activity[account_id] = max(latest_activity.get(account_id, observed), observed)
                if row.row_id not in consumed or consumed[row.row_id] != row.amount.minor:
                    pending[account_id] += 1
        coverage = self.statement_coverage()
        checks, reconciliation_unavailable = self._available_reconciliation_checks()
        saved_checks = self._reconciliation_history(checks)
        result = []
        for account in accounts:
            decision = self.opening_decision(account.id)
            if decision is None:
                status = "missing"
            elif decision.state == "withdrawn":
                status = "withdrawn"
            elif decision.stale:
                status = "stale"
            elif decision.cutoff_date > as_of:
                status = "future"
            elif any(
                entry.key != decision.entry_key
                and entry.key not in inactive
                and entry.posting_date <= decision.cutoff_date
                and any(posting.account_id == account.id for posting in entry.postings)
                for entry in entries
            ):
                status = "conflict"
            else:
                status = "valid"
            history = []
            recorded = 0
            excluded = 0
            for entry in entries:
                if entry.posting_date > as_of:
                    continue
                postings = tuple(posting for posting in entry.postings if posting.account_id == account.id)
                if not postings:
                    continue
                if not entry.reviewed:
                    excluded += 1
                    continue
                change = sum(posting.amount_minor for posting in postings)
                recorded += change
                role = None
                if entry.key in originals:
                    role = "superseded_replacement" if entry.key in replacements else "original"
                elif entry.key in reversals:
                    role = "reversal"
                elif entry.key in replacements:
                    role = "replacement"
                if entry.key in retired:
                    role = "retired"
                elif entry.key in retirement_reversals:
                    role = "retirement_reversal"
                history.append(
                    AccountPositionHistoryRow(
                        entry.posting_date,
                        entry.key,
                        entry.event_id,
                        entry.description,
                        entry.origin,
                        change,
                        recorded,
                        recorded if status == "valid" and entry.posting_date >= decision.cutoff_date else None,
                        role,
                    )
                )
            sections = tuple(section for section in coverage if section.account_id == account.id)
            source_cutoff = max((section.period_end for section in sections), default=None)
            warnings = []
            if reconciliation_unavailable is not None:
                warnings.append("live_reconciliation_unavailable")
            if not sections:
                warnings.append("no_statement_coverage")
            if any(
                section.period_start is not None
                and section.period_start <= as_of
                and section.relation_to_known_periods == "gap"
                for section in sections
            ):
                warnings.append("source_period_gap")
            if any(
                section.period_start is not None
                and section.period_start <= as_of
                and section.relation_to_known_periods == "overlap"
                for section in sections
            ):
                warnings.append("source_period_overlap")
            if any(not section.capture_verified for section in sections):
                warnings.append("source_capture_incomplete")
            if source_cutoff is not None and source_cutoff < as_of:
                warnings.append("source_cutoff_before_as_of")
            if source_cutoff is not None and source_cutoff > as_of:
                warnings.append("source_period_extends_after_as_of")
            live_cutoff = max(
                (
                    check.period_end
                    for check in checks
                    if status == "valid"
                    and check.account_id == account.id
                    and check.reconciled
                    and check.posted_interpretations_reviewed
                    and check.period_end <= as_of
                ),
                default=None,
            )
            lifecycle = self._account_lifecycle_at(account.id, as_of)
            closed = lifecycle is not None and lifecycle.state == "closed"
            value_status, latest_value, current_values = self._dated_value_point(account.id, as_of)
            result.append(
                AccountPosition(
                    account.id,
                    account.name,
                    account.kind,
                    "USD",
                    recorded,
                    recorded if status == "valid" else None,
                    status,
                    decision.cutoff_date if decision is not None else None,
                    decision.amount_minor if decision is not None else None,
                    source_cutoff,
                    latest_activity.get(account.id),
                    pending[account.id],
                    excluded,
                    live_cutoff,
                    tuple(warnings),
                    tuple(history),
                    max(
                        (
                            saved.cutoff_date
                            for saved in saved_checks
                            if saved.account_id == account.id and saved.cutoff_date <= as_of
                        ),
                        default=None,
                    ),
                    max(
                        (
                            saved.cutoff_date
                            for saved in saved_checks
                            if saved.account_id == account.id and saved.cutoff_date <= as_of and not saved.stale
                        ),
                        default=None,
                    ),
                    account.tracking_scope,
                    decision.origin if decision is not None else None,
                    latest_value,
                    lifecycle,
                    recorded if closed else None,
                    closed and status != "valid",
                    as_of if closed else None,
                    value_status,
                    current_values if value_status == "conflict" else (),
                    current_values,
                )
            )
        unresolved_rows, unresolved_sources = self._unallocated_activity_counts()
        clearing = sum(
            posting.amount_minor
            for entry in entries
            if entry.reviewed and entry.posting_date <= as_of
            for posting in entry.postings
            if posting.account_id == "internal:transfer-clearing:USD"
        )
        return AccountPositionsSummary(
            as_of, "USD", tuple(result), unbound, unresolved_rows, unresolved_sources, clearing
        )

    def reviewed_journal_export(self, *, start: date, end: date) -> ReviewedJournalExport:
        """Read active reviewed entries with posting and source provenance for export."""
        period_entries = tuple(self._journal_entries_in_period(start, end))
        action_history, repair_history = self._read_source_interpretation_history()
        period_keys = {entry.key for entry in period_entries}
        source_actions = tuple(action for action in action_history if action.entry_key in period_keys)
        repeat_repairs = tuple(repair for repair in repair_history if repair.redundant_entry_key in period_keys)
        settlements = tuple(
            event
            for event in self._read_transfer_history()[0]
            if event.pair is None and any(key in period_keys for key in event.entry_keys)
        )
        dated_values = tuple(v for v in self._read_dated_values() if start <= v.value_date < end)
        dated_withdrawals = tuple(v.withdrawal for v in dated_values if v.withdrawal is not None)
        period_events = {entry.event_id for entry in period_entries}
        transfer_actions = tuple(
            JournalExportTransferAction(*row)
            for row in self.connection.execute(
                "SELECT event_id,action,replacement_event_id,reason,created_at FROM TransferEventActions ORDER BY created_at,event_id"
            )
            if row[0] in period_events
        )
        corrections = tuple(
            JournalExportCorrection(original_key, reversal_key, replacement_key, reason, created_at)
            for original_key, reversal_key, replacement_key, reason, created_at, payload in self.connection.execute(
                "SELECT c.original_key,c.reversal_key,c.replacement_key,c.reason,c.created_at,e.payload "
                "FROM JournalCorrections c JOIN JournalEntries e ON e.key=c.original_key "
                "ORDER BY c.created_at,c.original_key"
            )
            if start <= _decode_journal(payload).posting_date < end
        )
        retirements = tuple(
            JournalExportRetirement(original, reversal, reason, created)
            for original, reversal, reason, created, payload in self.connection.execute(
                "SELECT r.original_key,r.reversal_key,r.reason,r.created_at,e.payload "
                "FROM JournalRetirements r JOIN JournalEntries e ON e.key=r.original_key "
                "ORDER BY r.created_at,r.original_key"
            )
            if start <= _decode_journal(payload).posting_date < end
        )
        inactive = self._inactive_journal_keys()
        opening_keys = self._opening_journal_keys()
        entries = tuple(
            sorted(
                (
                    entry
                    for entry in period_entries
                    if entry.reviewed and entry.key not in opening_keys and entry.key not in inactive
                ),
                key=lambda entry: (entry.posting_date, entry.key),
            )
        )
        accounts = tuple(
            JournalExportAccount(*row)
            for row in self.connection.execute("SELECT id,name,kind FROM Accounts ORDER BY id")
        )
        account_ids = {account.id for account in accounts}
        if any(posting.account_id not in account_ids for entry in entries for posting in entry.postings):
            raise ProfileFormatError("journal_export_account_missing")
        source_rows = tuple(
            self.connection.execute("SELECT row_id,source_sha256 FROM SourceObservations ORDER BY row_id")
        )
        source_ids = {row_id for row_id, _source_id in source_rows}
        if any(
            allocation.observation_id not in source_ids
            for entry in entries
            for posting in entry.postings
            for allocation in posting.allocations
        ):
            raise ProfileFormatError("journal_export_source_row_missing")
        unresolved_rows, unresolved_sources = self._unallocated_activity_counts()
        return ReviewedJournalExport(
            start,
            end,
            entries,
            accounts,
            source_rows,
            corrections,
            unresolved_rows,
            unresolved_sources,
            sum(not entry.reviewed for entry in period_entries),
            sum(entry.reviewed and entry.key in opening_keys for entry in period_entries),
            retirements,
            transfer_actions,
            source_actions,
            repeat_repairs,
            settlements,
            dated_values,
            dated_withdrawals,
        )

    def _insert_reviewed_category(
        self,
        entry: JournalEntry,
        row_id: str,
        financial_id: str,
        amount: int,
        accounts: dict[str, LedgerAccount],
        *,
        refusal_prefix: str,
        expected_basis_sha256: str | None = None,
    ) -> str:
        payload = _journal_payload(entry)
        prior = self.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (entry.key,)).fetchone()
        if prior is not None:
            if entry.key in self._inactive_journal_keys():
                active = self.connection.execute(
                    f"SELECT e.payload FROM JournalAllocations a JOIN JournalEntries e ON e.key=a.entry_key WHERE a.row_id=? AND a.entry_key NOT IN ({_INACTIVE_JOURNAL_SQL})",
                    (row_id,),
                ).fetchall()
                if active:
                    current = _decode_journal(active[0][0])
                    if (
                        len(active) == 1
                        and current.key.startswith(entry.key + ":repost:")
                        and _journal_payload(replace(entry, key=current.key)) == active[0][0]
                    ):
                        return current.key
                    raise ProfileFormatError(f"{refusal_prefix}_already_corrected")
                generation = self.connection.execute(
                    "SELECT MAX(action_id) FROM SourceInterpretationActions WHERE row_id=?", (row_id,)
                ).fetchone()[0]
                if generation is None:
                    raise ProfileFormatError(f"{refusal_prefix}_already_corrected")
                entry = replace(entry, key=entry.key + f":repost:{generation}")
                payload = _journal_payload(entry)
            else:
                if prior[0] != payload:
                    raise ProfileFormatError(f"{refusal_prefix}_conflicts_with_prior_entry")
                return entry.key
        self._require_source_interpretation_basis(expected_basis_sha256)
        self._require_source_overlap_postable((row_id,))
        validate_entry(
            entry,
            accounts,
            {row_id: Observation(row_id, financial_id, amount, entry.posting_date)},
            self._active_consumed(),
        )
        self.connection.execute("INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (entry.key, payload))
        self.connection.execute("INSERT INTO JournalAllocations VALUES (?,?,?)", (entry.key, row_id, amount))
        return entry.key

    def post_reviewed_cash_category(
        self,
        row_id: str,
        category_id: str,
        *,
        reason: str,
        expected_basis_sha256: str | None = None,
        purpose: CategoryPurpose | None = None,
    ) -> str:
        """Post one explicitly classified asset cash movement with source evidence."""
        self._require_writable()
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("cash_review_reason_required")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            expected_basis_sha256 = self._basis_before_builtin_materialization(category_id, expected_basis_sha256)
            category = self._category_for_posting(category_id)
            if category not in {("expense", "category"), ("income", "category")}:
                raise ProfileFormatError("cash_category_invalid")
            kind = category[0]
            row, financial_id, accounts, accounting_description = self._cash_category_source(row_id)
            amount = row.amount.minor
            if purpose is None:
                # Existing narrow callers explicitly review an ordinary category.
                # New adapters supply the complete purpose instead of inferring it.
                purpose = "expense" if kind == "expense" else "income"
            if purpose not in _category_purposes(amount) or CATEGORY_PURPOSE_KINDS.get(purpose) != kind:
                raise ProfileFormatError("cash_category_purpose_invalid")
            entry = JournalEntry(
                key=f"review:cash:{purpose}:{row_id}",
                event_id=f"source:{row_id}",
                posting_date=date.fromisoformat(row.date.iso),
                description=accounting_description,
                postings=(
                    Posting(financial_id, amount, (Allocation(row_id, amount),)),
                    Posting(category_id, -amount),
                ),
                reviewed=True,
                reason=reason.strip(),
            )
            key = self._insert_reviewed_category(
                entry,
                row_id,
                financial_id,
                amount,
                accounts,
                refusal_prefix="cash_review",
                expected_basis_sha256=expected_basis_sha256,
            )
            self.connection.execute("COMMIT")
            return key
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("cash_review_refused") from None
            raise

    def post_reviewed_card_purchase(
        self,
        row_id: str,
        category_id: str,
        *,
        reason: str,
        preferences: V2Preferences,
        accounting_date: date | None = None,
        expected_basis_sha256: str | None = None,
        purpose: CategoryPurpose = "expense",
    ) -> str:
        """Post one explicitly classified card movement; date overrides are explicit."""
        self._require_writable()
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("card_purchase_reason_required")
        if (
            type(preferences) is not V2Preferences
            or type(preferences.allow_assumed_posting_dates) is not bool
            or (accounting_date is not None and type(accounting_date) is not date)
        ):
            raise ProfileFormatError("card_purchase_date_decision_invalid")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            expected_basis_sha256 = self._basis_before_builtin_materialization(category_id, expected_basis_sha256)
            category = self._category_for_posting(category_id)
            if category not in {("expense", "category"), ("income", "category")}:
                raise ProfileFormatError("card_category_invalid")
            row, financial_id, accounts, candidate = self._card_purchase_source(row_id)
            if (
                purpose not in _category_purposes(row.amount.minor)
                or CATEGORY_PURPOSE_KINDS.get(purpose) != category[0]
            ):
                raise ProfileFormatError("card_category_purpose_invalid")
            permitted = permitted_posting_date(row, preferences)
            if accounting_date is None:
                if permitted is None:
                    raise ProfileFormatError("card_purchase_assumed_date_disabled")
                posting_date = date.fromisoformat(permitted.iso)
            else:
                if permitted is None and accounting_date.isoformat() == candidate.iso:
                    raise ProfileFormatError("card_purchase_assumed_date_disabled")
                posting_date = accounting_date
            amount = row.amount.minor
            entry = JournalEntry(
                key=f"review:card:{purpose}:{row_id}",
                event_id=f"source:{row_id}",
                posting_date=posting_date,
                description=row.description.text,
                postings=(
                    Posting(financial_id, amount, (Allocation(row_id, amount),)),
                    Posting(category_id, -amount),
                ),
                reviewed=True,
                reason=reason.strip(),
            )
            key = self._insert_reviewed_category(
                entry,
                row_id,
                financial_id,
                amount,
                accounts,
                refusal_prefix="card_purchase",
                expected_basis_sha256=expected_basis_sha256,
            )
            self.connection.execute("COMMIT")
            return key
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("card_purchase_refused") from None
            raise

    def _category_for_posting(self, category_id: str):
        if type(category_id) is str and is_builtin_id_reserved(category_id):
            self.ensure_builtin_category(category_id)
        return self.connection.execute("SELECT kind,role FROM Accounts WHERE id=?", (category_id,)).fetchone()

    def _basis_before_builtin_materialization(self, category_id: str, expected: str | None) -> str | None:
        # A selected built-in is authored in this same transaction. Its account
        # row changes the review version, so check the original selection first.
        if (
            type(category_id) is str
            and builtin_category(category_id) is not None
            and self.connection.execute("SELECT 1 FROM Accounts WHERE id=?", (category_id,)).fetchone() is None
        ):
            self._require_source_interpretation_basis(expected)
            return None
        return expected

    def _insert_reviewed_correction(
        self,
        original: JournalEntry,
        replacement: JournalEntry,
        row_id: str,
        financial_id: str,
        amount: int,
        accounts: dict[str, LedgerAccount],
        *,
        reason: str,
        refusal_prefix: str,
    ) -> str:
        if original.key in self._inactive_journal_keys():
            raise ProfileFormatError(f"{refusal_prefix}_original_inactive")
        reversal = JournalEntry(
            key="reversal:" + hashlib.sha256(original.key.encode()).hexdigest(),
            event_id=original.event_id,
            posting_date=original.posting_date,
            description="Reversal: " + original.description,
            postings=tuple(Posting(posting.account_id, -posting.amount_minor) for posting in original.postings),
            origin="reversal",
            reviewed=True,
            reason=reason,
        )
        if self.connection.execute(
            "SELECT 1 FROM JournalEntries WHERE key IN (?,?)", (reversal.key, replacement.key)
        ).fetchone():
            raise ProfileFormatError(f"{refusal_prefix}_key_conflict")
        validate_entry(
            replacement,
            accounts,
            {row_id: Observation(row_id, financial_id, amount, replacement.posting_date)},
            self._active_consumed(excluding=original.key),
        )
        self.connection.execute(
            "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (reversal.key, _journal_payload(reversal))
        )
        self.connection.execute(
            "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (replacement.key, _journal_payload(replacement))
        )
        self.connection.execute("INSERT INTO JournalAllocations VALUES (?,?,?)", (replacement.key, row_id, amount))
        self.connection.execute(
            "INSERT INTO JournalCorrections(original_key,reversal_key,replacement_key,reason) VALUES (?,?,?,?)",
            (original.key, reversal.key, replacement.key, reason),
        )
        return replacement.key

    def correct_reviewed_cash_category(
        self, original_key: str, category_id: str, *, reason: str, expected_basis_sha256: str | None = None
    ) -> str:
        """Atomically reverse and recategorize an active reviewed cash movement."""
        self._require_writable()
        if type(original_key) is not str or not original_key or type(category_id) is not str or not category_id:
            raise ProfileFormatError("cash_correction_identity_required")
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("cash_correction_reason_required")
        reason = reason.strip()
        replacement_key = (
            "review:cash:correction:" + hashlib.sha256(f"{original_key}\0{category_id}\0{reason}".encode()).hexdigest()
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            prior = self.connection.execute(
                "SELECT replacement_key,reason FROM JournalCorrections WHERE original_key=?", (original_key,)
            ).fetchone()
            if prior is not None:
                if prior == (replacement_key, reason) and replacement_key not in self._inactive_journal_keys():
                    self.connection.execute("COMMIT")
                    return replacement_key
                raise ProfileFormatError("cash_correction_conflicts_with_prior_decision")
            self._require_source_interpretation_basis(expected_basis_sha256)
            if original_key in self._inactive_journal_keys():
                raise ProfileFormatError("cash_correction_original_inactive")
            original_row = self.connection.execute(
                "SELECT payload FROM JournalEntries WHERE key=?", (original_key,)
            ).fetchone()
            if original_row is None:
                raise ProfileFormatError("cash_correction_original_missing")
            original = _decode_journal(original_row[0])
            allocations = self.connection.execute(
                "SELECT row_id,amount_minor FROM JournalAllocations WHERE entry_key=?", (original_key,)
            ).fetchall()
            if (
                original.key != original_key
                or original.origin != "imported"
                or not original.reviewed
                or len(original.postings) != 2
                or len(allocations) != 1
                or original.postings[0].amount_minor != allocations[0][1]
                or original.postings[0].amount_minor == 0
                or original.postings[0].allocations != (Allocation(*allocations[0]),)
                or original.postings[1].amount_minor != -allocations[0][1]
            ):
                raise ProfileFormatError("cash_correction_original_invalid")
            row_id, amount = allocations[0]
            old_category_id = original.postings[1].account_id
            old_category = self.connection.execute(
                "SELECT kind,role FROM Accounts WHERE id=?", (old_category_id,)
            ).fetchone()
            new_category = self._category_for_posting(category_id)
            kind = old_category[0] if old_category is not None else None
            row, financial_id, accounts, accounting_description = self._cash_category_source(row_id)
            if (
                original.postings[0].account_id != financial_id
                or original.event_id != f"source:{row_id}"
                or original.posting_date.isoformat() != row.date.iso
                or original.description != accounting_description
                or old_category != (kind, "category")
                or new_category != (kind, "category")
                or category_id == old_category_id
            ):
                raise ProfileFormatError("cash_correction_requires_new_same_kind_category")
            replacement = JournalEntry(
                key=replacement_key,
                event_id=original.event_id,
                posting_date=original.posting_date,
                description=original.description,
                postings=(
                    Posting(financial_id, amount, (Allocation(row_id, amount),)),
                    Posting(category_id, -amount),
                ),
                reviewed=True,
                reason=reason,
            )
            key = self._insert_reviewed_correction(
                original,
                replacement,
                row_id,
                financial_id,
                amount,
                accounts,
                reason=reason,
                refusal_prefix="cash_correction",
            )
            self.connection.execute("COMMIT")
            return key
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("cash_correction_refused") from None
            raise

    def correct_reviewed_card_purchase(
        self,
        original_key: str,
        category_id: str,
        *,
        reason: str,
        accounting_date: date | None = None,
        expected_basis_sha256: str | None = None,
    ) -> str:
        """Reverse and replace one card expense when its category or accounting date changes."""
        self._require_writable()
        if (
            type(original_key) is not str
            or not original_key.startswith("review:card:")
            or type(category_id) is not str
            or not category_id
            or (accounting_date is not None and type(accounting_date) is not date)
        ):
            raise ProfileFormatError("card_correction_identity_required")
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("card_correction_reason_required")
        reason = reason.strip()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            original_row = self.connection.execute(
                "SELECT payload FROM JournalEntries WHERE key=?", (original_key,)
            ).fetchone()
            if original_row is None:
                raise ProfileFormatError("card_correction_original_missing")
            original = _decode_journal(original_row[0])
            chosen_date = accounting_date or original.posting_date
            replacement_key = (
                "review:card:correction:"
                + hashlib.sha256(
                    f"{original_key}\0{category_id}\0{chosen_date.isoformat()}\0{reason}".encode()
                ).hexdigest()
            )
            prior = self.connection.execute(
                "SELECT replacement_key,reason FROM JournalCorrections WHERE original_key=?", (original_key,)
            ).fetchone()
            if prior is not None:
                if prior == (replacement_key, reason) and replacement_key not in self._inactive_journal_keys():
                    self.connection.execute("COMMIT")
                    return replacement_key
                raise ProfileFormatError("card_correction_conflicts_with_prior_decision")
            self._require_source_interpretation_basis(expected_basis_sha256)
            if original_key in self._inactive_journal_keys():
                raise ProfileFormatError("card_correction_original_inactive")
            allocations = self.connection.execute(
                "SELECT row_id,amount_minor FROM JournalAllocations WHERE entry_key=?", (original_key,)
            ).fetchall()
            if (
                original.key != original_key
                or original.origin != "imported"
                or not original.reviewed
                or len(original.postings) != 2
                or len(allocations) != 1
                or original.postings[0].amount_minor != allocations[0][1]
                or original.postings[0].amount_minor == 0
                or original.postings[0].allocations != (Allocation(*allocations[0]),)
                or original.postings[1].amount_minor != -allocations[0][1]
            ):
                raise ProfileFormatError("card_correction_original_invalid")
            row_id, amount = allocations[0]
            old_category_id = original.postings[1].account_id
            old_category = self.connection.execute(
                "SELECT kind,role FROM Accounts WHERE id=?", (old_category_id,)
            ).fetchone()
            new_category = self._category_for_posting(category_id)
            row, financial_id, accounts, _candidate = self._card_purchase_source(row_id)
            if (
                original.postings[0].account_id != financial_id
                or original.event_id != f"source:{row_id}"
                or original.description != row.description.text
                or old_category not in {("expense", "category"), ("income", "category")}
                or new_category != old_category
                or (category_id == old_category_id and chosen_date == original.posting_date)
            ):
                raise ProfileFormatError("card_correction_requires_changed_category_or_date")
            replacement = JournalEntry(
                key=replacement_key,
                event_id=original.event_id,
                posting_date=chosen_date,
                description=original.description,
                postings=(
                    Posting(financial_id, amount, (Allocation(row_id, amount),)),
                    Posting(category_id, -amount),
                ),
                reviewed=True,
                reason=reason,
            )
            key = self._insert_reviewed_correction(
                original,
                replacement,
                row_id,
                financial_id,
                amount,
                accounts,
                reason=reason,
                refusal_prefix="card_correction",
            )
            self.connection.execute("COMMIT")
            return key
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("card_correction_refused") from None
            raise

    def _binding_target_rows(self, target: BindingCorrectionTarget) -> tuple[SourceEvidence, tuple[str, ...]]:
        if (
            not isinstance(target, BindingCorrectionTarget)
            or type(target.source_sha256) is not str
            or type(target.mode) is not str
            or target.mode not in {"source", "file", "rows"}
            or type(target.row_ids) is not tuple
            or (target.source_identity is not None and type(target.source_identity) is not str)
            or (target.source_identity_form is not None and type(target.source_identity_form) is not str)
            or any(type(row) is not str for row in target.row_ids)
            or tuple(sorted(set(target.row_ids))) != target.row_ids
        ):
            raise ProfileFormatError("binding_correction_target_invalid")
        evidence = self.load_import(target.source_sha256).evidence
        rows = _rows(evidence)
        if target.mode == "source":
            if isinstance(evidence.payload, StatementPayload):
                identities = {(a.source_identity, a.source_identity_form) for a in evidence.payload.accounts}
            else:
                identities = {(r.source_account, r.source_account_form) for r in rows if r.source_account is not None}
            if target.row_ids or (target.source_identity, target.source_identity_form) not in identities:
                raise ProfileFormatError("binding_correction_target_invalid")
            selected = tuple(
                r.row_id
                for r in rows
                if (r.source_account, r.source_account_form) == (target.source_identity, target.source_identity_form)
            )
        else:
            if target.source_identity is not None or target.source_identity_form is not None:
                raise ProfileFormatError("binding_correction_target_invalid")
            if not isinstance(evidence.payload, ActivityExportPayload):
                raise ProfileFormatError("binding_correction_target_invalid")
            if target.mode == "file":
                if target.row_ids or not rows or any(r.source_account is not None for r in rows):
                    raise ProfileFormatError("binding_correction_target_invalid")
                selected = tuple(r.row_id for r in rows)
            else:
                if not target.row_ids or not set(target.row_ids) <= {
                    r.row_id for r in rows if r.source_account is None
                }:
                    raise ProfileFormatError("binding_correction_target_invalid")
                selected = target.row_ids
        return evidence, tuple(sorted(selected))

    def _binding_scope_accounts(self, target: BindingCorrectionTarget) -> tuple[str | None, ...]:
        if target.mode == "rows":
            assignments = self._row_assignments(target.row_ids)
            return tuple(assignments.get(row) for row in target.row_ids)
        if target.mode == "file":
            row = self.connection.execute(
                "SELECT ledger_account_id FROM FileAccountAssertions WHERE source_sha256=?", (target.source_sha256,)
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT ledger_account_id FROM SourceAccountBindings WHERE source_sha256=? AND source_identity=? AND source_identity_form=?",
                (target.source_sha256, target.source_identity, target.source_identity_form),
            ).fetchone()
        return (row[0] if row else None,)

    def _binding_affected_reviews(self, row_ids: tuple[str, ...], ceiling: int):
        latest = {}
        for row in self.connection.execute(
            "SELECT * FROM SourceOverlapReviews WHERE revision_id<=? ORDER BY revision_id", (ceiling,)
        ):
            latest[row[1], row[2]] = row
        affected = set(row_ids)
        while True:
            expanded = affected | {item for pair in latest if affected.intersection(pair) for item in pair}
            if expanded == affected:
                break
            affected = expanded
        return tuple(latest[pair] for pair in sorted(latest) if affected.intersection(pair))

    def _binding_affected_transfer_reviews(self, row_ids: tuple[str, ...], ceiling: int):
        selected = set(row_ids)
        return tuple(
            row
            for row in self.connection.execute(
                "SELECT * FROM TransferPairReviews WHERE revision_id<=? ORDER BY revision_id", (ceiling,)
            )
            if selected.intersection(row[1:3])
        )

    @staticmethod
    def _binding_context_json(accounts, bindings) -> str:
        return json.dumps(
            {"accounts": accounts, "bindings": [[b.row_id, b.ledger_account_id, b.basis] for b in bindings]},
            sort_keys=True,
            separators=(",", ":"),
        )

    def _read_binding_corrections(self) -> tuple[BindingCorrection, ...]:
        """Validate immutable recorded contexts without imposing today's mapping on history."""
        result = []
        for saved in self.connection.execute("SELECT * FROM BindingCorrections ORDER BY correction_id DESC"):
            number, source, raw_target, raw_prior, raw_new, raw_invalidations, basis, reason, checksum, created = saved
            try:
                if (
                    type(number) is not int
                    or number <= 0
                    or any(type(value) is not str or not value for value in saved[1:])
                    or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in (source, basis, checksum))
                    or not 0 < len(reason.strip()) <= 500
                    or checksum != _transfer_record_digest(*saved[:8], created)
                ):
                    raise ValueError
                decoded = json.loads(raw_target)
                if type(decoded) is not dict or set(decoded) != {
                    "source_sha256",
                    "mode",
                    "source_identity",
                    "source_identity_form",
                    "row_ids",
                }:
                    raise ValueError
                if type(decoded["row_ids"]) is not list:
                    raise ValueError
                decoded["row_ids"] = tuple(decoded["row_ids"])
                target = BindingCorrectionTarget(**decoded)
                _evidence, rows = self._binding_target_rows(target)
                if source != target.source_sha256:
                    raise ValueError
                contexts = []
                for raw in (raw_prior, raw_new):
                    context = json.loads(raw)
                    if type(context) is not dict or set(context) != {"accounts", "bindings"}:
                        raise ValueError
                    ids, bindings = context["accounts"], context["bindings"]
                    if (
                        type(ids) is not list
                        or len(ids) != (len(target.row_ids) if target.mode == "rows" else 1)
                        or any(value is not None and type(value) is not str for value in ids)
                        or type(bindings) is not list
                        or any(type(b) is not list or len(b) != 3 for b in bindings)
                    ):
                        raise ValueError
                    for account_id in ids:
                        if account_id is not None:
                            self._require_financial_account(account_id)
                    expected = [
                        [
                            row_id,
                            ids[index if target.mode == "rows" else 0],
                            {"source": "source", "file": "file", "rows": "row"}[target.mode]
                            if ids[index if target.mode == "rows" else 0] is not None
                            else None,
                        ]
                        for index, row_id in enumerate(rows)
                    ]
                    if bindings != expected:
                        raise ValueError
                    contexts.append((tuple(ids), tuple(AccountBinding(*b) for b in bindings)))
                if contexts[0] == contexts[1] or len(set(contexts[1][0])) != 1:
                    raise ValueError
                invalidations = json.loads(raw_invalidations)
                if type(invalidations) is not dict or set(invalidations) != {
                    "review_ceiling",
                    "edges",
                    "transfer_review_ceiling",
                    "transfer_reviews",
                }:
                    raise ValueError
                ceiling, edges = invalidations["review_ceiling"], invalidations["edges"]
                if type(ceiling) is not int or ceiling < 0 or type(edges) is not list:
                    raise ValueError
                transfer_ceiling = invalidations["transfer_review_ceiling"]
                if type(transfer_ceiling) is not int or transfer_ceiling < 0:
                    raise ValueError
                transfer_reviews = self._binding_affected_transfer_reviews(rows, transfer_ceiling)
                if invalidations["transfer_reviews"] != [list(row) for row in transfer_reviews]:
                    raise ValueError
                prior_reviews = self._binding_affected_reviews(rows, ceiling)
                if len(edges) != len(prior_reviews):
                    raise ValueError
                ids = []
                for offset, (edge, prior_review) in enumerate(zip(edges, prior_reviews, strict=True), 1):
                    if type(edge) is not list or len(edge) != 2 or edge[0] != list(prior_review):
                        raise ValueError
                    pending = edge[1]
                    if (
                        type(pending) is not list
                        or len(pending) != 8
                        or type(pending[0]) is not int
                        or pending[0] != ceiling + offset
                        or pending[1:7] != [prior_review[1], prior_review[2], "pending", None, basis, reason]
                        or self.connection.execute(
                            "SELECT * FROM SourceOverlapReviews WHERE revision_id=?", (pending[0],)
                        ).fetchone()
                        != tuple(pending)
                    ):
                        raise ValueError
                    ids.append(pending[0])
                result.append(
                    BindingCorrection(
                        number,
                        target,
                        contexts[0][0],
                        contexts[1][0],
                        contexts[0][1],
                        contexts[1][1],
                        tuple(ids),
                        reason,
                        created,
                        checksum,
                        tuple(row[0] for row in transfer_reviews),
                    )
                )
            except (ProfileFormatError, TypeError, ValueError, KeyError):
                raise ProfileFormatError("binding_correction_history_integrity") from None
        checked_scopes = set()
        for record in result:
            current = self._binding_scope_accounts(record.target)
            scope_keys = record.target.row_ids if record.target.mode == "rows" else (None,)
            for key, expected, actual in zip(scope_keys, record.new_account_ids, current, strict=True):
                scope = (
                    record.target.source_sha256,
                    record.target.mode,
                    record.target.source_identity,
                    record.target.source_identity_form,
                    key,
                )
                if scope not in checked_scopes:
                    if expected != actual:
                        raise ProfileFormatError("binding_correction_history_integrity")
                    checked_scopes.add(scope)
        return tuple(result)

    def binding_correction_history(self, source_sha256: str | None = None) -> tuple[BindingCorrection, ...]:
        if self.connection.in_transaction:
            raise ProfileFormatError("binding_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            if source_sha256 is not None:
                self.load_import(source_sha256)
            return tuple(
                r
                for r in self._read_binding_corrections()
                if source_sha256 is None or r.target.source_sha256 == source_sha256
            )
        finally:
            self.connection.execute("ROLLBACK")

    def _binding_correction_snapshot(
        self, target: BindingCorrectionTarget, destination_account_id: str | None
    ) -> BindingCorrectionSnapshot:
        history = self._read_binding_corrections()
        evidence, rows = self._binding_target_rows(target)
        if destination_account_id is not None and type(destination_account_id) is not str:
            raise ProfileFormatError("binding_correction_invalid")
        if destination_account_id is not None:
            self._require_financial_account(destination_account_id)
        accounts = self._binding_scope_accounts(target)
        bindings = tuple(b for b in self.account_bindings(target.source_sha256) if b.row_id in set(rows))
        bindings = tuple(sorted(bindings, key=lambda b: b.row_id))
        blockers = []
        if all(account == destination_account_id for account in accounts):
            blockers.append("binding_unchanged")
        if (
            target.mode == "file"
            and self.connection.execute(
                "SELECT 1 FROM RowAccountAssignments a JOIN SourceObservations o ON o.row_id=a.row_id WHERE o.source_sha256=? LIMIT 1",
                (target.source_sha256,),
            ).fetchone()
        ):
            blockers.append("row_mode_requires_clear")
        if (
            target.mode == "rows"
            and self.connection.execute(
                "SELECT 1 FROM FileAccountAssertions WHERE source_sha256=?", (target.source_sha256,)
            ).fetchone()
        ):
            blockers.append("file_mode_requires_clear")
        consumed = self._active_consumed()
        active_rows = {
            row
            for (row,) in self.connection.execute(
                f"SELECT DISTINCT row_id FROM JournalAllocations WHERE entry_key NOT IN ({_INACTIVE_JOURNAL_SQL})"
            )
        }
        if set(rows).intersection(active_rows) or any(consumed.get(row, 0) for row in rows):
            blockers.append("active_source_consumption")
        anchors = self._binding_opening_anchors(target, accounts)
        if anchors:
            blockers.append("source_backed_opening_anchor")
        value_anchors = self._binding_dated_value_anchors(target)
        if value_anchors:
            blockers.append("source_backed_dated_value_anchor")
        ordinary_blockers = ()
        try:
            self._require_ordinary_binding_change(target)
        except ProfileFormatError as exc:
            if str(exc) not in {
                "account_binding_has_journal_history",
                "account_binding_has_overlap_review_history",
                "account_binding_has_transfer_review_history",
                "account_binding_has_correction_history",
                "account_binding_source_backed_opening_anchor",
                "account_binding_source_backed_dated_value_anchor",
            }:
                raise
            ordinary_blockers = (str(exc),)
        ceiling = self.connection.execute("SELECT coalesce(max(revision_id),0) FROM SourceOverlapReviews").fetchone()[0]
        reviews = self._binding_affected_reviews(rows, ceiling)
        transfer_ceiling = self.connection.execute(
            "SELECT coalesce(max(revision_id),0) FROM TransferPairReviews"
        ).fetchone()[0]
        transfer_reviews = self._binding_affected_transfer_reviews(rows, transfer_ceiling)
        transfer_ids = tuple(row[0] for row in transfer_reviews)
        affected_ids = {row_id for review in reviews for row_id in review[1:3]}
        affected_ids.update(row_id for review in transfer_reviews for row_id in review[1:3])
        affected_rows = []
        account_names = {account.id: account.name for account in self.financial_accounts()}
        for (source_id,) in self.connection.execute("SELECT DISTINCT source_sha256 FROM SourceObservations"):
            source_rows = [row for row in _rows(self.load_import(source_id).evidence) if row.row_id in affected_ids]
            if not source_rows:
                continue
            source_bindings = {b.row_id: b.ledger_account_id for b in self.account_bindings(source_id)}
            affected_rows.extend(
                BindingAffectedReviewRow(
                    row.row_id,
                    source_id,
                    row.date.iso,
                    row.description.text,
                    source_bindings[row.row_id],
                    account_names.get(source_bindings[row.row_id]),
                )
                for row in source_rows
            )
        basis = _transfer_record_digest(
            "v2-binding-correction-1",
            self._source_overlap_basis(),
            self.connection.execute("SELECT * FROM OpeningDecisions ORDER BY account_id").fetchall(),
            self.connection.execute("SELECT * FROM StatementSourceReviews ORDER BY revision_id").fetchall(),
            asdict(target),
            destination_account_id,
        )
        return BindingCorrectionSnapshot(
            target,
            destination_account_id,
            evidence,
            self.financial_accounts(),
            accounts,
            bindings,
            rows,
            tuple(blockers),
            ordinary_blockers,
            anchors,
            tuple((row[1], row[2]) for row in reviews),
            tuple(r for r in history if r.target.source_sha256 == target.source_sha256),
            basis,
            tuple(sorted(affected_rows, key=lambda row: row.row_id)),
            transfer_ids,
            tuple(review for review in self._read_transfer_history()[1] if review.revision_id in set(transfer_ids)),
            value_anchors,
        )

    def binding_correction_snapshot(
        self, target: BindingCorrectionTarget, *, destination_account_id: str | None
    ) -> BindingCorrectionSnapshot:
        if self.connection.in_transaction:
            raise ProfileFormatError("binding_requires_committed_snapshot")
        if (
            isinstance(target, BindingCorrectionTarget)
            and type(target.row_ids) is tuple
            and all(type(row) is str for row in target.row_ids)
        ):
            target = replace(target, row_ids=tuple(sorted(target.row_ids)))
        self.connection.execute("BEGIN")
        try:
            return self._binding_correction_snapshot(target, destination_account_id)
        finally:
            self.connection.execute("ROLLBACK")

    def correct_reviewed_binding(
        self,
        target: BindingCorrectionTarget,
        *,
        destination_account_id: str | None,
        expected_basis_sha256: str,
        reason: str,
    ) -> BindingCorrection:
        """Change only reviewed assignment state; journal/source identities remain immutable."""
        self._require_writable()
        if self.connection.in_transaction:
            raise ProfileFormatError("binding_requires_committed_snapshot")
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500 or type(expected_basis_sha256) is not str:
            raise ProfileFormatError("binding_correction_invalid")
        reason = reason.strip()
        if (
            isinstance(target, BindingCorrectionTarget)
            and type(target.row_ids) is tuple
            and all(type(row) is str for row in target.row_ids)
        ):
            target = replace(target, row_ids=tuple(sorted(target.row_ids)))
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            history = self._read_binding_corrections()
            for record in history:
                saved_basis = self.connection.execute(
                    "SELECT request_basis FROM BindingCorrections WHERE correction_id=?", (record.correction_id,)
                ).fetchone()[0]
                if (
                    record.target == target
                    and record.new_account_ids == (destination_account_id,) * len(record.prior_account_ids)
                    and saved_basis == expected_basis_sha256
                    and record.reason == reason
                ):
                    self.connection.execute("COMMIT")
                    return record
            selected = self._binding_correction_snapshot(target, destination_account_id)
            if expected_basis_sha256 != selected.basis_sha256:
                raise ProfileFormatError("binding_changed_since_selection")
            if selected.blockers:
                raise ProfileFormatError("binding_correction_" + selected.blockers[0])
            ceiling = self.connection.execute(
                "SELECT coalesce(max(revision_id),0) FROM SourceOverlapReviews"
            ).fetchone()[0]
            reviews = self._binding_affected_reviews(selected.affected_row_ids, ceiling)
            transfer_ceiling = self.connection.execute(
                "SELECT coalesce(max(revision_id),0) FROM TransferPairReviews"
            ).fetchone()[0]
            transfer_reviews = self._binding_affected_transfer_reviews(selected.affected_row_ids, transfer_ceiling)
            if target.mode == "source":
                self.connection.execute(
                    "DELETE FROM SourceAccountBindings WHERE source_sha256=? AND source_identity=? AND source_identity_form=?",
                    (target.source_sha256, target.source_identity, target.source_identity_form),
                )
                if destination_account_id is not None:
                    self.connection.execute(
                        "INSERT INTO SourceAccountBindings VALUES (?,?,?,?)",
                        (
                            target.source_sha256,
                            target.source_identity,
                            target.source_identity_form,
                            destination_account_id,
                        ),
                    )
            elif target.mode == "file":
                self.connection.execute(
                    "DELETE FROM FileAccountAssertions WHERE source_sha256=?", (target.source_sha256,)
                )
                if destination_account_id is not None:
                    self.connection.execute(
                        "INSERT INTO FileAccountAssertions VALUES (?,?)", (target.source_sha256, destination_account_id)
                    )
            else:
                self.connection.executemany(
                    "DELETE FROM RowAccountAssignments WHERE row_id=?", ((row,) for row in target.row_ids)
                )
                if destination_account_id is not None:
                    self.connection.executemany(
                        "INSERT INTO RowAccountAssignments VALUES (?,?)",
                        ((row, destination_account_id) for row in target.row_ids),
                    )
            edges = []
            for review in reviews:
                cursor = self.connection.execute(
                    "INSERT INTO SourceOverlapReviews (left_row_id,right_row_id,decision,retained_row_id,basis_sha256,reason) VALUES (?,?,'pending',NULL,?,?)",
                    (review[1], review[2], expected_basis_sha256, reason),
                )
                pending = self.connection.execute(
                    "SELECT * FROM SourceOverlapReviews WHERE revision_id=?", (cursor.lastrowid,)
                ).fetchone()
                edges.append((review, pending))
            number = self.connection.execute(
                "SELECT coalesce(max(correction_id),0)+1 FROM BindingCorrections"
            ).fetchone()[0]
            created = self.connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
            new_accounts = (destination_account_id,) * len(selected.current_account_ids)
            new_bindings = tuple(
                AccountBinding(
                    row,
                    destination_account_id,
                    {"source": "source", "file": "file", "rows": "row"}[target.mode]
                    if destination_account_id is not None
                    else None,
                )
                for row in selected.affected_row_ids
            )
            fields = (
                number,
                target.source_sha256,
                json.dumps(asdict(target), sort_keys=True, separators=(",", ":")),
                self._binding_context_json(selected.current_account_ids, selected.current_bindings),
                self._binding_context_json(new_accounts, new_bindings),
                json.dumps(
                    {
                        "review_ceiling": ceiling,
                        "edges": edges,
                        "transfer_review_ceiling": transfer_ceiling,
                        "transfer_reviews": transfer_reviews,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                expected_basis_sha256,
                reason,
            )
            self.connection.execute(
                "INSERT INTO BindingCorrections VALUES (?,?,?,?,?,?,?,?,?,?)",
                (*fields, _transfer_record_digest(*fields, created), created),
            )
            result = next(row for row in self._read_binding_corrections() if row.correction_id == number)
            self._validate_common_journal_read()
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def source_account_bindings(self, source_sha256: str) -> tuple[SourceAccountBinding, ...]:
        """Show each identity printed by a source and its explicit ledger decision."""
        self._read_binding_corrections()
        evidence = self.load_import(source_sha256).evidence
        payload = evidence.payload
        if isinstance(payload, StatementPayload):
            identities = tuple((account.source_identity, account.source_identity_form) for account in payload.accounts)
        else:
            identities = tuple(
                dict.fromkeys(
                    (row.source_account, row.source_account_form)
                    for row in payload.rows
                    if row.source_account is not None
                )
            )
        saved = {
            (identity, form): account_id
            for identity, form, account_id in self.connection.execute(
                "SELECT source_identity,source_identity_form,ledger_account_id "
                "FROM SourceAccountBindings WHERE source_sha256=?",
                (source_sha256,),
            )
        }
        return tuple(SourceAccountBinding(identity, form, saved.get((identity, form))) for identity, form in identities)

    def bind_source_account(
        self, source_sha256: str, source_identity: str, source_identity_form: str, account_id: str
    ) -> None:
        """Bind one printed account identity after an explicit user decision."""
        self._require_writable()
        if (source_identity, source_identity_form) not in {
            (binding.source_identity, binding.source_identity_form)
            for binding in self.source_account_bindings(source_sha256)
        }:
            raise ProfileFormatError("source_account_missing")
        self._require_financial_account(account_id)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            prior = self.connection.execute(
                "SELECT ledger_account_id FROM SourceAccountBindings "
                "WHERE source_sha256=? AND source_identity=? AND source_identity_form=?",
                (source_sha256, source_identity, source_identity_form),
            ).fetchone()
            if prior != (account_id,):
                self._require_ordinary_binding_change(
                    BindingCorrectionTarget(source_sha256, "source", source_identity, source_identity_form)
                )
                self.connection.execute(
                    "INSERT INTO SourceAccountBindings VALUES (?,?,?,?) "
                    "ON CONFLICT(source_sha256,source_identity,source_identity_form) "
                    "DO UPDATE SET ledger_account_id=excluded.ledger_account_id",
                    (source_sha256, source_identity, source_identity_form, account_id),
                )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def clear_source_account_binding(self, source_sha256: str, source_identity: str, source_identity_form: str) -> None:
        self._require_writable()
        if (source_identity, source_identity_form) not in {
            (binding.source_identity, binding.source_identity_form)
            for binding in self.source_account_bindings(source_sha256)
        }:
            raise ProfileFormatError("source_account_missing")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.connection.execute(
                "SELECT 1 FROM SourceAccountBindings WHERE source_sha256=? AND source_identity=? AND source_identity_form=?",
                (source_sha256, source_identity, source_identity_form),
            ).fetchone():
                self._require_ordinary_binding_change(
                    BindingCorrectionTarget(source_sha256, "source", source_identity, source_identity_form)
                )
            self.connection.execute(
                "DELETE FROM SourceAccountBindings WHERE source_sha256=? AND source_identity=? AND source_identity_form=?",
                (source_sha256, source_identity, source_identity_form),
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def assert_file_account(self, source_sha256: str, account_id: str) -> None:
        """Assert that every accountless row belongs to one financial account."""
        self._require_writable()
        self._require_financial_account(account_id)
        evidence = self.load_import(source_sha256).evidence
        payload = evidence.payload
        if (
            not isinstance(payload, ActivityExportPayload)
            or not payload.rows
            or any(row.source_account is not None for row in payload.rows)
        ):
            raise ProfileFormatError("file_account_assertion_requires_accountless_export")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.connection.execute(
                "SELECT 1 FROM RowAccountAssignments a JOIN SourceObservations o ON o.row_id=a.row_id "
                "WHERE o.source_sha256=? LIMIT 1",
                (source_sha256,),
            ).fetchone():
                raise ProfileFormatError("file_account_assertion_conflicts_with_row_assignments")
            prior = self.connection.execute(
                "SELECT ledger_account_id FROM FileAccountAssertions WHERE source_sha256=?", (source_sha256,)
            ).fetchone()
            if prior != (account_id,):
                self._require_ordinary_binding_change(BindingCorrectionTarget(source_sha256, "file"))
            self.connection.execute(
                "INSERT INTO FileAccountAssertions VALUES (?,?) "
                "ON CONFLICT(source_sha256) DO UPDATE SET ledger_account_id=excluded.ledger_account_id",
                (source_sha256, account_id),
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def clear_file_account_assertion(self, source_sha256: str) -> None:
        self._require_writable()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.connection.execute(
                "SELECT 1 FROM FileAccountAssertions WHERE source_sha256=?", (source_sha256,)
            ).fetchone():
                self._require_ordinary_binding_change(BindingCorrectionTarget(source_sha256, "file"))
            self.connection.execute("DELETE FROM FileAccountAssertions WHERE source_sha256=?", (source_sha256,))
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def assign_row_account(self, row_id: str, account_id: str) -> None:
        """Assign one accountless row in an export reviewed row by row."""
        self._require_writable()
        row = self.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (row_id,)
        ).fetchone()
        if row is None:
            raise ProfileFormatError("observation_missing")
        self.assign_rows_account(row[0], (row_id,), account_id)

    def assign_rows_account(self, source_sha256: str, row_ids: tuple[str, ...], account_id: str) -> None:
        """Atomically assign selected rows in a mixed, accountless export."""
        self._require_writable()
        self._require_financial_account(account_id)
        evidence = self.load_import(source_sha256).evidence
        payload = evidence.payload
        if (
            not isinstance(payload, ActivityExportPayload)
            or not row_ids
            or len(set(row_ids)) != len(row_ids)
            or not set(row_ids) <= {row.row_id for row in payload.rows if row.source_account is None}
        ):
            raise ProfileFormatError("row_account_assignment_requires_accountless_export")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.connection.execute(
                "SELECT 1 FROM FileAccountAssertions WHERE source_sha256=?", (source_sha256,)
            ).fetchone():
                raise ProfileFormatError("row_account_assignment_conflicts_with_file_assertion")
            prior = self._row_assignments(row_ids)
            changed = tuple(sorted(row_id for row_id in row_ids if prior.get(row_id) != account_id))
            if changed:
                self._require_ordinary_binding_change(BindingCorrectionTarget(source_sha256, "rows", row_ids=changed))
            self.connection.executemany(
                "INSERT INTO RowAccountAssignments VALUES (?,?) "
                "ON CONFLICT(row_id) DO UPDATE SET ledger_account_id=excluded.ledger_account_id",
                ((row_id, account_id) for row_id in row_ids),
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def clear_row_account_assignment(self, row_id: str) -> None:
        row = self.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (row_id,)
        ).fetchone()
        if row is None:
            raise ProfileFormatError("observation_missing")
        self.clear_row_account_assignments(row[0], (row_id,))

    def clear_row_account_assignments(self, source_sha256: str, row_ids: tuple[str, ...]) -> None:
        self._require_writable()
        evidence = self.load_import(source_sha256).evidence
        if len(set(row_ids)) != len(row_ids) or not set(row_ids) <= {row.row_id for row in _rows(evidence)}:
            raise ProfileFormatError("invalid_row_assignment_selection")
        if not row_ids:
            return
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            assigned = tuple(self._row_assignments(row_ids))
            if assigned:
                self._require_ordinary_binding_change(
                    BindingCorrectionTarget(source_sha256, "rows", row_ids=tuple(sorted(assigned)))
                )
            self.connection.executemany(
                "DELETE FROM RowAccountAssignments WHERE row_id=?", ((row_id,) for row_id in row_ids)
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def account_bindings(self, source_sha256: str) -> tuple[AccountBinding, ...]:
        """Show effective user decisions; unassigned rows remain unresolved."""
        evidence = self.load_import(source_sha256).evidence
        file_row = self.connection.execute(
            "SELECT ledger_account_id FROM FileAccountAssertions WHERE source_sha256=?", (source_sha256,)
        ).fetchone()
        file_account_id = file_row[0] if file_row else None
        row_assignments = dict(
            self.connection.execute(
                "SELECT a.row_id,a.ledger_account_id FROM RowAccountAssignments a "
                "JOIN SourceObservations o ON o.row_id=a.row_id WHERE o.source_sha256=?",
                (source_sha256,),
            )
        )
        source_assignments = {
            (binding.source_identity, binding.source_identity_form): binding.ledger_account_id
            for binding in self.source_account_bindings(source_sha256)
        }
        result = []
        for row in _rows(evidence):
            if row.row_id in row_assignments:
                result.append(AccountBinding(row.row_id, row_assignments[row.row_id], "row"))
            elif row.source_account is not None and source_assignments.get(
                (row.source_account, row.source_account_form)
            ):
                result.append(
                    AccountBinding(
                        row.row_id, source_assignments[(row.source_account, row.source_account_form)], "source"
                    )
                )
            elif row.source_account is None and file_account_id is not None:
                result.append(AccountBinding(row.row_id, file_account_id, "file"))
            else:
                result.append(AccountBinding(row.row_id, None, None))
        return tuple(result)

    def journal_history_row_ids(self, source_sha256: str) -> frozenset[str]:
        """Rows whose account assignment is locked by any posted journal history."""
        self.load_import(source_sha256)
        return frozenset(
            row_id
            for (row_id,) in self.connection.execute(
                "SELECT DISTINCT a.row_id FROM JournalAllocations a "
                "JOIN SourceObservations o ON o.row_id=a.row_id WHERE o.source_sha256=?",
                (source_sha256,),
            )
        )

    def source_imported(self, source: bytes) -> bool:
        """Check an exact-source retry before invoking a parser."""
        if type(source) is not bytes or not 0 < len(source) <= MAX_SOURCE_BYTES:
            raise ProfileFormatError("source_size")
        return (
            self.connection.execute("SELECT 1 FROM Sources WHERE sha256=?", (_digest(source),)).fetchone() is not None
        )

    def source_ids(self) -> tuple[str, ...]:
        """List saved imports in their original insertion order, newest first."""
        return tuple(row[0] for row in self.connection.execute("SELECT sha256 FROM Sources ORDER BY rowid DESC"))

    def statement_coverage(self) -> tuple[StatementCoverageRow, ...]:
        """Compare printed periods on explicitly bound statements, without certifying coverage."""
        sections: dict[str, list[tuple[str, SourceEvidence, StatementPayload, StatementAccount]]] = {}
        saved: dict[str, SourceEvidence] = {}
        for source_id, identity, form, account_id in self.connection.execute(
            "SELECT source_sha256,source_identity,source_identity_form,ledger_account_id "
            "FROM SourceAccountBindings ORDER BY source_sha256,source_identity"
        ):
            evidence = saved.get(source_id)
            if evidence is None:
                evidence = self.load_import(source_id).evidence
                saved[source_id] = evidence
            payload = evidence.payload
            if not isinstance(payload, StatementPayload):
                continue
            account = next(
                (
                    item
                    for item in payload.accounts
                    if (item.source_identity, item.source_identity_form) == (identity, form)
                ),
                None,
            )
            if account is None:
                raise ProfileFormatError("coverage_bound_source_account_missing")
            sections.setdefault(account_id, []).append((source_id, evidence, payload, account))
        rows = []
        for financial in self.financial_accounts():
            bound = sorted(
                sections.get(financial.id, ()),
                key=lambda item: (item[2].start.iso or "9999-12-31", item[2].end.iso, item[0]),
            )
            latest_end: date | None = None
            latest_closers: list[tuple[str, StatementPayload, StatementAccount]] = []
            for source_id, evidence, payload, account in bound:
                start = date.fromisoformat(payload.start.iso) if payload.start.iso is not None else None
                end = date.fromisoformat(payload.end.iso)
                if start is None:
                    relation = "unknown_start"
                elif latest_end is None:
                    relation = "first_known"
                elif start <= latest_end:
                    relation = "overlap"
                elif (start - latest_end).days > 1:
                    relation = "gap"
                else:
                    relation = "adjacent"
                comparison = "not_adjacent"
                compared_source = None
                if relation == "adjacent":
                    if len(latest_closers) != 1:
                        comparison = "ambiguous_prior"
                    else:
                        previous_source, previous_payload, previous_account = latest_closers[0]
                        compared_source = previous_source
                        if (
                            payload.start.provenance != "observed"
                            or previous_payload.end.provenance != "observed"
                            or not admitted_statement_scope(
                                evidence.parser_id, account.balance_scope, financial.kind, financial.tracking_scope
                            )
                            or not admitted_statement_scope(
                                saved[previous_source].parser_id,
                                previous_account.balance_scope,
                                financial.kind,
                                financial.tracking_scope,
                            )
                            or account.opening is None
                            or previous_account.closing is None
                            or account.opening.provenance != "observed"
                            or previous_account.closing.provenance != "observed"
                            or account.opening.minor is None
                            or previous_account.closing.minor is None
                        ):
                            comparison = "unavailable"
                        else:
                            comparison = (
                                "same" if previous_account.closing.minor == account.opening.minor else "different"
                            )
                rows.append(
                    StatementCoverageRow(
                        financial.id,
                        financial.name,
                        source_id,
                        evidence.parser_id,
                        start,
                        end,
                        payload.start.provenance,
                        payload.end.provenance,
                        relation,
                        account.balance_scope,
                        account.opening,
                        account.closing,
                        payload.independent_balance_verified,
                        payload.capture_verified,
                        comparison,
                        compared_source,
                        account.source_identity,
                        account.source_identity_form,
                    )
                )
                if start is not None and (latest_end is None or end > latest_end):
                    latest_end = end
                    latest_closers = [(source_id, payload, account)]
                elif start is not None and end == latest_end:
                    latest_closers.append((source_id, payload, account))
        return tuple(rows)

    def statement_journal_comparisons(self) -> tuple[StatementJournalComparison, ...]:
        """Compare printed period movement with journal movement without certifying reconciliation."""
        coverage = self.statement_coverage()
        consumed = self._active_consumed()
        journal = tuple(
            _decode_journal(payload) for (payload,) in self.connection.execute("SELECT payload FROM JournalEntries")
        )
        inactive_keys = self._inactive_journal_keys()
        active_dates: dict[str, list[date]] = {}
        for entry in journal:
            if entry.key in inactive_keys:
                continue
            for posting in entry.postings:
                for allocation in posting.allocations:
                    active_dates.setdefault(allocation.observation_id, []).append(entry.posting_date)
        financial_accounts = {account.id: account for account in self.financial_accounts()}
        account_kinds = {account.id: account.kind for account in financial_accounts.values()}
        result = []
        for section in coverage:
            payload = self.load_import(section.source_sha256).evidence.payload
            if not isinstance(payload, StatementPayload):
                raise ProfileFormatError("statement_comparison_source_invalid")
            identities = {
                (identity, form)
                for identity, form in self.connection.execute(
                    "SELECT source_identity,source_identity_form FROM SourceAccountBindings "
                    "WHERE source_sha256=? AND ledger_account_id=?",
                    (section.source_sha256, section.account_id),
                )
            }
            matched = [
                account
                for account in payload.accounts
                if (account.source_identity, account.source_identity_form) in identities
            ]
            account = matched[0] if len(matched) == 1 else None
            activity = tuple(row for row in account.rows if row.row_role == "activity") if account else ()
            row_ids = {row.row_id for row in activity}
            remaining = tuple(
                row.amount.minor - consumed.get(row.row_id, 0) for row in activity if row.amount.minor is not None
            )
            unallocated_rows = sum(amount != 0 for amount in remaining)
            unallocated_magnitude = sum(abs(amount) for amount in remaining)
            allocations_outside_period = (
                sum(
                    any(
                        not section.period_start <= used_date <= section.period_end
                        for used_date in active_dates.get(row.row_id, ())
                    )
                    for row in activity
                )
                if section.period_start is not None
                else 0
            )
            source_change = (
                sum(row.amount.minor for row in activity)
                if account is not None
                and all(row.amount.minor is not None and row.amount.provenance == "observed" for row in activity)
                else None
            )
            printed_change = (
                account.closing.minor - account.opening.minor
                if account is not None
                and self._admitted_statement_scope(section.account_id, section.source_sha256, account)
                and account.opening is not None
                and account.closing is not None
                and account.opening.provenance == "observed"
                and account.closing.provenance == "observed"
                and account.opening.minor is not None
                and account.closing.minor is not None
                else None
            )
            journal_change = None
            outside_postings = 0
            if section.period_start is not None:
                journal_change = 0
                for entry in journal:
                    if section.period_start <= entry.posting_date <= section.period_end:
                        for posting in entry.postings:
                            if posting.account_id != section.account_id:
                                continue
                            journal_change += posting.amount_minor
                            if entry.key not in inactive_keys and (
                                not entry.reviewed
                                or not posting.allocations
                                or any(allocation.observation_id not in row_ids for allocation in posting.allocations)
                            ):
                                outside_postings += 1
            difference = (
                journal_change - printed_change if journal_change is not None and printed_change is not None else None
            )
            if account is None:
                status = "Bound source section is ambiguous"
            elif not self._admitted_statement_scope(section.account_id, section.source_sha256, account):
                status = "Outside account-total balance scope"
            elif section.period_start is None:
                status = "Source period start unavailable"
            elif printed_change is None:
                status = "Printed account endpoints unavailable"
            elif source_change is None:
                status = "Observed source activity incomplete"
            elif source_change != printed_change or not payload.independent_balance_verified:
                status = "Printed source balance equation unresolved"
            elif unallocated_rows:
                status = "Source movements awaiting allocation"
            elif allocations_outside_period:
                status = "Source allocations use dates outside this period"
            elif outside_postings:
                status = "Journal has postings outside this statement evidence"
            elif difference:
                status = "Journal differs from printed change"
            elif section.relation_to_known_periods == "overlap":
                status = "Movement agrees; source periods overlap"
            elif not payload.capture_verified:
                status = "Movement agrees; source capture incomplete"
            else:
                status = "Movement agrees; reconciliation still pending"
            result.append(
                StatementJournalComparison(
                    section.account_id,
                    section.account_name,
                    account_kinds[section.account_id],
                    section.source_sha256,
                    section.period_start,
                    section.period_end,
                    printed_change,
                    source_change,
                    journal_change,
                    difference,
                    len(activity),
                    unallocated_rows,
                    unallocated_magnitude,
                    allocations_outside_period,
                    outside_postings,
                    status,
                )
            )
        return tuple(result)

    def statement_reconciliation_checks(self) -> tuple[StatementReconciliationCheck, ...]:
        """Check bound statements in one read snapshot; never change accounting state."""
        if self.connection.in_transaction:
            raise ProfileFormatError("reconciliation_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            result = self._statement_reconciliation_checks()
        finally:
            self.connection.execute("ROLLBACK")
        return result

    def _reconciliation_rule_and_version(self) -> tuple[str, str]:
        """Hash inputs without requiring any source to be ready for reconciliation."""
        self._validate_journal_retirements()
        self._validate_transfer_history()
        self._validate_source_interpretation_history()
        self._validate_common_journal_read()
        rule = "v2-statement-reconciliation-5"
        version_tables = (
            ("Sources", "sha256"),
            ("EvidenceSnapshots", "source_sha256,definition_sha256,sha256"),
            ("SourceObservations", "*"),
            ("Accounts", "*"),
            ("SourceAccountBindings", "*"),
            ("FileAccountAssertions", "*"),
            ("RowAccountAssignments", "*"),
            ("BindingCorrections", "*"),
            ("JournalEntries", "*"),
            ("JournalAllocations", "*"),
            ("JournalCorrections", "*"),
            ("JournalRetirements", "*"),
            ("StatementSourceReviews", "*"),
            ("OpeningDecisions", "*"),
            ("OpeningDecisionRevisions", "*"),
            ("AccountDatedValues", "*"),
            ("DatedValueWithdrawals", "*"),
            ("AccountLifecycleDecisions", "*"),
            ("TransferEvents", "*"),
            ("TransferEventActions", "*"),
            ("TransferPairReviews", "*"),
            ("SourceInterpretationActions", "*"),
            ("PostedRepeatRepairs", "*"),
            ("SourceOverlapReviews", "*"),
        )
        digest = hashlib.sha256(rule.encode())
        for table, columns in version_tables:
            digest.update(table.encode())
            rows = sorted(
                self.connection.execute(f"SELECT {columns} FROM {table}").fetchall(),
                key=lambda row: json.dumps(row, separators=(",", ":")),
            )
            for row in rows:
                digest.update(json.dumps(row, separators=(",", ":")).encode())
        return rule, digest.hexdigest()

    def _statement_reconciliation_checks(self) -> tuple[StatementReconciliationCheck, ...]:
        rule, version = self._reconciliation_rule_and_version()
        coverage = self.statement_coverage()
        comparisons = {(row.account_id, row.source_sha256): row for row in self.statement_journal_comparisons()}
        entries = tuple(
            _decode_journal(payload) for (payload,) in self.connection.execute("SELECT payload FROM JournalEntries")
        )
        inactive = self._inactive_journal_keys()
        reviews = {
            account.id: {review.source_sha256: review for review in self.statement_source_reviews(account.id)}
            for account in self.financial_accounts()
        }
        decisions = {account_id: self.opening_decision(account_id) for account_id in reviews}
        kinds = {account.id: account.kind for account in self.financial_accounts()}
        overlap_rows, _buckets, _reviews, overlap_aliases = self._source_overlap_index()
        overlap_blocks = self.source_overlap_posting_blocks(tuple(overlap_rows))
        result = []
        for section in coverage:
            comparison = comparisons[(section.account_id, section.source_sha256)]
            _payload, source_section = self._bound_statement_section(section.account_id, section.source_sha256)
            source_row_ids = {row.row_id for row in source_section.rows if row.row_role == "activity"}
            review = reviews[section.account_id].get(section.source_sha256)
            opening_decision = decisions[section.account_id]
            printed_opening = (
                section.opening.minor
                if self._admitted_statement_scope(section.account_id, section.source_sha256, source_section)
                and section.opening is not None
                and section.opening.provenance == "observed"
                else None
            )
            printed_closing = (
                section.closing.minor
                if self._admitted_statement_scope(section.account_id, section.source_sha256, source_section)
                and section.closing is not None
                and section.closing.provenance == "observed"
                else None
            )
            journal_opening = None
            if section.period_start is not None:
                journal_opening = sum(
                    posting.amount_minor
                    for entry in entries
                    if entry.posting_date < section.period_start
                    for posting in entry.postings
                    if posting.account_id == section.account_id
                )
            journal_closing = sum(
                posting.amount_minor
                for entry in entries
                if entry.posting_date <= section.period_end
                for posting in entry.postings
                if posting.account_id == section.account_id
            )
            opening_difference = (
                journal_opening - printed_opening
                if journal_opening is not None and printed_opening is not None
                else None
            )
            closing_difference = journal_closing - printed_closing if printed_closing is not None else None
            source_difference = (
                comparison.source_activity_change_minor - comparison.printed_change_minor
                if comparison.source_activity_change_minor is not None and comparison.printed_change_minor is not None
                else None
            )
            exceptions = []
            if not self._admitted_statement_scope(section.account_id, section.source_sha256, source_section):
                exceptions.append("account_total_scope_unavailable")
            if section.period_start is None:
                exceptions.append("source_period_start_unavailable")
            if printed_opening is None or printed_closing is None:
                exceptions.append("reported_balance_endpoints_unavailable")
            if not section.independent_balance_verified or source_difference != 0:
                exceptions.append("source_balance_equation_unverified")
            if comparison.unallocated_rows:
                exceptions.append("unallocated_source_movements")
            if comparison.allocations_outside_period:
                exceptions.append("source_allocations_outside_period")
            unsupported_postings = any(
                entry.key not in inactive
                and section.period_start is not None
                and section.period_start <= entry.posting_date <= section.period_end
                and (
                    not posting.allocations
                    or any(allocation.observation_id not in source_row_ids for allocation in posting.allocations)
                )
                for entry in entries
                for posting in entry.postings
                if posting.account_id == section.account_id
            )
            if unsupported_postings:
                exceptions.append("postings_outside_statement_evidence")
            if opening_difference is not None and opening_difference != 0:
                exceptions.append("opening_balance_difference")
            if closing_difference is not None and closing_difference != 0:
                exceptions.append("closing_balance_difference")
            if review is None or review.opening_origin != "reported" or review.closing_origin != "reported":
                exceptions.append("source_endpoints_not_reviewed")
            if review is None or not review.timing_confirmed:
                exceptions.append("source_period_timing_unreviewed")
            if review is None or review.posting_dates != "reported":
                exceptions.append("posting_dates_not_reported")
            if opening_decision is None or opening_decision.state != "active" or opening_decision.stale:
                exceptions.append("opening_position_unverified_or_stale")
            overlapping = any(
                other.account_id == section.account_id
                and other.source_sha256 != section.source_sha256
                and section.period_start is not None
                and other.period_start is not None
                and section.period_start <= other.period_end
                and other.period_start <= section.period_end
                for other in coverage
            )
            warnings = []
            if any(row_id in overlap_aliases for row_id in source_row_ids):
                warnings.append("confirmed_repeated_supporting_evidence")
            if any(row_id in overlap_blocks and row_id not in overlap_aliases for row_id in source_row_ids):
                warnings.append("cross_source_occurrence_review_pending")
            if not section.capture_verified:
                warnings.append("source_capture_incomplete")
            if overlapping:
                warnings.append("overlapping_bound_source_periods")
            if section.relation_to_known_periods == "gap":
                warnings.append("calendar_gap_before_source")
            if section.endpoint_comparison == "different":
                warnings.append("adjacent_printed_endpoints_differ")
            unreviewed = any(
                entry.key not in inactive
                and entry.posting_date <= section.period_end
                and not entry.reviewed
                and any(posting.account_id == section.account_id for posting in entry.postings)
                for entry in entries
            )
            result.append(
                StatementReconciliationCheck(
                    section.account_id,
                    section.account_name,
                    kinds[section.account_id],
                    section.source_sha256,
                    section.period_start,
                    section.period_end,
                    printed_opening,
                    journal_opening,
                    opening_difference,
                    printed_closing,
                    journal_closing,
                    closing_difference,
                    source_difference,
                    tuple(exceptions),
                    tuple(warnings),
                    not unreviewed,
                    not exceptions,
                    rule,
                    version,
                    section.balance_scope,
                    next(a.tracking_scope for a in self.financial_accounts() if a.id == section.account_id),
                )
            )
        return tuple(result)

    def save_reconciliation_decision(
        self,
        account_id: str,
        source_sha256: str,
        *,
        expected_input_version: str,
        reason: str,
    ) -> ReconciliationDecision:
        """Explicitly retain a successful current check, without posting any money."""
        self._require_writable()
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("reconciliation_reason_required")
        if type(expected_input_version) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_input_version) is None:
            raise ProfileFormatError("reconciliation_input_version_required")
        if self.connection.in_transaction:
            raise ProfileFormatError("reconciliation_requires_committed_snapshot")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._require_financial_account(account_id)
            checks = self._statement_reconciliation_checks()
            check = next(
                (item for item in checks if item.account_id == account_id and item.source_sha256 == source_sha256),
                None,
            )
            if check is None:
                raise ProfileFormatError("reconciliation_check_missing")
            if check.input_version != expected_input_version:
                raise ProfileFormatError("reconciliation_changed_since_selection")
            if not check.reconciled or check.exceptions or not check.posted_interpretations_reviewed:
                raise ProfileFormatError("reconciliation_check_not_successful")
            prior = self.connection.execute(
                "SELECT decision_id FROM ReconciliationDecisions "
                "WHERE account_id=? AND source_sha256=? AND rule=? AND input_version=?",
                (account_id, source_sha256, check.rule, check.input_version),
            ).fetchone()
            if prior is None:
                journal_versions = tuple(
                    (key, _digest(payload.encode()))
                    for key, payload in self.connection.execute("SELECT key,payload FROM JournalEntries ORDER BY key")
                )
                check_payload = _reconciliation_payload(check)
                _decode_reconciliation_check(check_payload)
                versions_payload = json.dumps(journal_versions, separators=(",", ":"))
                cursor = self.connection.execute(
                    "INSERT INTO ReconciliationDecisions "
                    "(account_id,source_sha256,cutoff_date,rule,input_version,check_payload,journal_versions,snapshot_sha256,reason) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        account_id,
                        source_sha256,
                        check.period_end.isoformat(),
                        check.rule,
                        check.input_version,
                        check_payload,
                        versions_payload,
                        _reconciliation_snapshot_digest(check_payload, versions_payload),
                        reason.strip(),
                    ),
                )
                decision_id = cursor.lastrowid
            else:
                decision_id = prior[0]
            saved = next(
                item for item in self._reconciliation_history(checks, account_id) if item.decision_id == decision_id
            )
            self.connection.execute("COMMIT")
            return saved
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def reconciliation_history(self, account_id: str | None = None) -> tuple[ReconciliationDecision, ...]:
        """Read immutable saved checks and their conservative current/stale status."""
        if self.connection.in_transaction:
            raise ProfileFormatError("reconciliation_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            if account_id is not None:
                self._require_financial_account(account_id)
            query = "SELECT 1 FROM ReconciliationDecisions"
            parameters = ()
            if account_id is not None:
                query += " WHERE account_id=?"
                parameters = (account_id,)
            if self.connection.execute(query + " LIMIT 1", parameters).fetchone() is None:
                return ()
            checks, _unavailable = self._available_reconciliation_checks()
            return self._reconciliation_history(checks, account_id)
        finally:
            self.connection.execute("ROLLBACK")

    def _available_reconciliation_checks(self) -> tuple[tuple[StatementReconciliationCheck, ...], str | None]:
        try:
            return self._statement_reconciliation_checks(), None
        except ProfileFormatError as exc:
            if str(exc) != "statement_review_requires_one_bound_section":
                raise
            return (), str(exc)

    def reconciliation_snapshot(self) -> ReconciliationSnapshot:
        """Read live checks and saved status from the same committed profile view."""
        if self.connection.in_transaction:
            raise ProfileFormatError("reconciliation_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            checks, unavailable = self._available_reconciliation_checks()
            return ReconciliationSnapshot(checks, self._reconciliation_history(checks), unavailable)
        finally:
            self.connection.execute("ROLLBACK")

    def _reconciliation_history(
        self, checks: tuple[StatementReconciliationCheck, ...] | None, account_id: str | None = None
    ) -> tuple[ReconciliationDecision, ...]:
        live = {(check.account_id, check.source_sha256): check for check in checks or ()}
        current_rule, current_version = self._reconciliation_rule_and_version()
        journal_versions = {
            key: _digest(payload.encode())
            for key, payload in self.connection.execute("SELECT key,payload FROM JournalEntries")
        }
        query = (
            "SELECT decision_id,account_id,source_sha256,cutoff_date,rule,input_version,"
            "check_payload,journal_versions,snapshot_sha256,reason,created_at FROM ReconciliationDecisions"
        )
        parameters = ()
        if account_id is not None:
            query += " WHERE account_id=?"
            parameters = (account_id,)
        result = []
        for (
            decision_id,
            account,
            source,
            cutoff,
            rule,
            version,
            payload,
            versions,
            snapshot_sha256,
            reason,
            created,
        ) in self.connection.execute(query + " ORDER BY decision_id DESC", parameters):
            check = _decode_reconciliation_check(payload)
            try:
                if _reconciliation_snapshot_digest(payload, versions) != snapshot_sha256:
                    raise ValueError
                cutoff_date = date.fromisoformat(cutoff)
                decoded_versions = json.loads(versions)
                if type(decoded_versions) is not list:
                    raise ValueError
                entry_versions = []
                seen = set()
                for item in decoded_versions:
                    if (
                        type(item) is not list
                        or len(item) != 2
                        or type(item[0]) is not str
                        or type(item[1]) is not str
                        or re.fullmatch(r"[0-9a-f]{64}", item[1]) is None
                        or item[0] in seen
                        or journal_versions.get(item[0]) != item[1]
                    ):
                        raise ValueError
                    seen.add(item[0])
                    entry_versions.append(tuple(item))
                if (
                    check.account_id != account
                    or check.source_sha256 != source
                    or check.period_end != cutoff_date
                    or check.rule != rule
                    or check.input_version != version
                    or not check.reconciled
                    or check.exceptions
                    or not check.posted_interpretations_reviewed
                    or not reason.strip()
                    or not admitted_statement_scope(
                        self.load_import(source).evidence.parser_id,
                        check.balance_scope,
                        check.account_kind,
                        check.tracking_scope,
                    )
                ):
                    raise ValueError
            except (TypeError, ValueError):
                raise ProfileFormatError("saved_reconciliation_integrity") from None
            current = live.get((account, source))
            stale = (
                current is None
                or current.rule != rule
                or current.input_version != version
                or not current.reconciled
                or not current.posted_interpretations_reviewed
            )
            if (not stale and check != current) or (
                rule == current_rule and version == current_version and dict(entry_versions) != journal_versions
            ):
                raise ProfileFormatError("saved_reconciliation_integrity")
            result.append(
                ReconciliationDecision(
                    decision_id,
                    account,
                    source,
                    cutoff_date,
                    rule,
                    version,
                    check,
                    tuple(entry_versions),
                    reason,
                    created,
                    stale,
                )
            )
        return tuple(result)

    def statement_source_reviews(self, account_id: str) -> tuple[StatementSourceReview, ...]:
        """Latest assertions whose exact section is currently unambiguously bound."""
        self._require_financial_account(account_id)
        latest = {}
        for review in self.statement_source_review_history(account_id):
            if review.source_sha256 in latest:
                continue
            bindings = self.connection.execute(
                "SELECT source_identity,source_identity_form FROM SourceAccountBindings WHERE source_sha256=? AND ledger_account_id=?",
                (review.source_sha256, account_id),
            ).fetchall()
            if bindings == [(review.source_identity, review.source_identity_form)]:
                latest[review.source_sha256] = review
        return tuple(latest[source] for source in sorted(latest))

    def statement_source_review_history(self, account_id: str) -> tuple[StatementSourceReview, ...]:
        self._require_financial_account(account_id)
        result = []
        for row in self.connection.execute(
            "SELECT revision_id,account_id,source_sha256,opening_origin,closing_origin,timing_confirmed,posting_dates,source_reference,note,source_identity,source_identity_form,created_at FROM StatementSourceReviews WHERE account_id=? ORDER BY revision_id DESC",
            (account_id,),
        ):
            revision, account, source, opening, closing, timing, dates, reference, note, identity, form, created = row
            try:
                if (
                    type(timing) is not int
                    or timing not in {0, 1}
                    or type(source) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", source) is None
                    or type(created) is not str
                    or not created
                ):
                    raise ValueError
                SourceValueReviewAnnotation(
                    revision_id=revision,
                    opening_origin=opening,
                    closing_origin=closing,
                    timing_confirmed=bool(timing),
                    posting_dates=dates,
                    source_reference=reference,
                    note=note,
                    source_identity=identity,
                    source_identity_form=form,
                )
                if not reference.strip() or reference != reference.strip() or note != note.strip():
                    raise ValueError
                payload = self.load_import(source).evidence.payload
                if not isinstance(payload, StatementPayload):
                    raise ValueError
                sections = [
                    s for s in payload.accounts if (s.source_identity, s.source_identity_form) == (identity, form)
                ]
                if len(sections) != 1:
                    raise ValueError
                section = sections[0]
                if any(
                    origin == "reported"
                    and (
                        not self._admitted_statement_scope(account_id, source, section)
                        or money is None
                        or money.provenance != "observed"
                        or money.minor is None
                    )
                    for origin, money in ((opening, section.opening), (closing, section.closing))
                ):
                    raise ValueError
                if timing and (payload.start.iso is None or payload.end.iso is None):
                    raise ValueError
                if dates == "reported" and any(
                    (candidate := posting_date_candidate(r)) is None
                    or candidate.provenance not in {"observed", "derived"}
                    for r in section.rows
                    if r.row_role == "activity"
                ):
                    raise ValueError
                result.append(
                    StatementSourceReview(
                        revision,
                        account,
                        source,
                        opening,
                        closing,
                        bool(timing),
                        dates,
                        reference,
                        note,
                        identity,
                        form,
                        created,
                    )
                )
            except (ValueError, TypeError, RecursionError):
                raise ProfileFormatError("statement_source_review_history_integrity") from None
        return tuple(result)

    def _bound_statement_section(
        self, account_id: str, source_sha256: str
    ) -> tuple[StatementPayload, StatementAccount]:
        self._require_financial_account(account_id)
        payload = self.load_import(source_sha256).evidence.payload
        if not isinstance(payload, StatementPayload):
            raise ProfileFormatError("statement_review_requires_bound_statement")
        identities = {
            (identity, form)
            for identity, form in self.connection.execute(
                "SELECT source_identity,source_identity_form FROM SourceAccountBindings "
                "WHERE source_sha256=? AND ledger_account_id=?",
                (source_sha256, account_id),
            )
        }
        sections = [
            section
            for section in payload.accounts
            if (section.source_identity, section.source_identity_form) in identities
        ]
        if len(sections) != 1:
            raise ProfileFormatError("statement_review_requires_one_bound_section")
        return payload, sections[0]

    def _admitted_statement_scope(self, account_id: str, source_id: str, section: StatementAccount) -> bool:
        financial = self.connection.execute(
            "SELECT kind,tracking_scope FROM Accounts WHERE id=? AND role='financial'", (account_id,)
        ).fetchone()
        return financial is not None and admitted_statement_scope(
            self.load_import(source_id).evidence.parser_id, section.balance_scope, financial[0], financial[1]
        )

    def _admitted_source_opening_history(self, account: FinancialAccount, amount: int, cutoff: date) -> bool:
        if account.tracking_scope == "account_total":
            return True
        if account.kind != "asset" or account.tracking_scope != "cash_component":
            return False
        for review in self.statement_source_review_history(account.id):
            if review.opening_origin != "reported" or not review.timing_confirmed:
                continue
            evidence = self.load_import(review.source_sha256).evidence
            if (
                evidence.parser_id != HSA_CASH_PARSER
                or not isinstance(evidence.payload, StatementPayload)
                or evidence.payload.start.iso is None
            ):
                continue
            for section in evidence.payload.accounts:
                if (section.source_identity, section.source_identity_form) != (
                    review.source_identity,
                    review.source_identity_form,
                ):
                    continue
                start = date.fromisoformat(evidence.payload.start.iso)
                if (
                    admitted_statement_scope(
                        evidence.parser_id, section.balance_scope, account.kind, account.tracking_scope
                    )
                    and section.opening is not None
                    and section.opening.provenance == "observed"
                    and section.opening.minor == amount
                    and start.toordinal() > 1
                    and cutoff == date.fromordinal(start.toordinal() - 1)
                ):
                    return True
        return False

    def statement_source_review_snapshot(self, account_id: str, source_sha256: str) -> StatementSourceReviewSnapshot:
        if self.connection.in_transaction:
            raise ProfileFormatError("statement_source_review_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            payload, source_account = self._bound_statement_section(account_id, source_sha256)
            account = next(a for a in self.financial_accounts() if a.id == account_id)
            saved = self.load_import(source_sha256)
            section = next(
                s
                for s in self.statement_coverage()
                if s.account_id == account_id
                and s.source_sha256 == source_sha256
                and (s.source_identity, s.source_identity_form)
                == (source_account.source_identity, source_account.source_identity_form)
            )
            review = next(
                (r for r in self.statement_source_reviews(account_id) if r.source_sha256 == source_sha256), None
            )
            return StatementSourceReviewSnapshot(
                account, section, saved, payload, source_account, review, self._account_anchor_basis()
            )
        finally:
            self.connection.execute("ROLLBACK")

    def record_statement_source_review(
        self,
        account_id: str,
        source_sha256: str,
        *,
        expected_revision_id: int | None,
        opening_origin: Literal["reported", "unestablished"],
        closing_origin: Literal["reported", "unestablished"],
        timing_confirmed: bool,
        posting_dates: Literal["reported", "estimated", "unverified"],
        source_reference: str,
        note: str = "",
        expected_section: tuple[str, str] | None = None,
        expected_basis_sha256: str | None = None,
    ) -> int:
        """Append a reviewed source assertion; printed evidence stays immutable."""
        self._require_writable()
        if (
            opening_origin not in {"reported", "unestablished"}
            or closing_origin not in {"reported", "unestablished"}
            or type(timing_confirmed) is not bool
            or posting_dates not in {"reported", "estimated", "unverified"}
            or type(source_reference) is not str
            or not 0 < len(source_reference.strip()) <= 500
            or type(note) is not str
            or len(note.strip()) > 500
            or (
                expected_basis_sha256 is not None
                and (
                    type(expected_basis_sha256) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", expected_basis_sha256) is None
                )
            )
            or (
                expected_section is not None
                and (
                    type(expected_section) is not tuple
                    or len(expected_section) != 2
                    or any(type(v) is not str or not v for v in expected_section)
                )
            )
        ):
            raise ProfileFormatError("statement_source_review_invalid")
        payload, section = self._bound_statement_section(account_id, source_sha256)
        if opening_origin == "reported" and (
            not self._admitted_statement_scope(account_id, source_sha256, section)
            or section.opening is None
            or section.opening.provenance != "observed"
            or section.opening.minor is None
        ):
            raise ProfileFormatError("opening_reported_balance_unavailable")
        if closing_origin == "reported" and (
            not self._admitted_statement_scope(account_id, source_sha256, section)
            or section.closing is None
            or section.closing.provenance != "observed"
            or section.closing.minor is None
        ):
            raise ProfileFormatError("closing_reported_balance_unavailable")
        if posting_dates == "reported" and any(
            (candidate := posting_date_candidate(row)) is None or candidate.provenance not in {"observed", "derived"}
            for row in section.rows
            if row.row_role == "activity"
        ):
            raise ProfileFormatError("reported_posting_dates_unavailable")
        if timing_confirmed and (payload.start.iso is None or payload.end.iso is None):
            raise ProfileFormatError("statement_period_timing_unavailable")
        values = (
            opening_origin,
            closing_origin,
            timing_confirmed,
            posting_dates,
            source_reference.strip(),
            note.strip(),
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            _locked_payload, locked_section = self._bound_statement_section(account_id, source_sha256)
            if expected_basis_sha256 is not None and expected_basis_sha256 != self._account_anchor_basis():
                raise ProfileFormatError("statement_source_review_changed_since_selection")
            context = (section.source_identity, section.source_identity_form)
            if (locked_section.source_identity, locked_section.source_identity_form) != context or (
                expected_section is not None and expected_section != context
            ):
                raise ProfileFormatError("statement_source_review_context_changed_since_selection")
            latest = next(
                (
                    review
                    for review in self.statement_source_reviews(account_id)
                    if review.source_sha256 == source_sha256
                ),
                None,
            )
            if (latest.revision_id if latest else None) != expected_revision_id:
                raise ProfileFormatError("statement_source_review_changed_since_selection")
            if (
                latest is not None
                and (
                    latest.opening_origin,
                    latest.closing_origin,
                    latest.timing_confirmed,
                    latest.posting_dates,
                    latest.source_reference,
                    latest.note,
                )
                == values
            ):
                self.connection.execute("COMMIT")
                return latest.revision_id
            cursor = self.connection.execute(
                "INSERT INTO StatementSourceReviews "
                "(account_id,source_sha256,opening_origin,closing_origin,timing_confirmed,posting_dates,source_reference,note,source_identity,source_identity_form) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    account_id,
                    source_sha256,
                    opening_origin,
                    closing_origin,
                    int(timing_confirmed),
                    posting_dates,
                    source_reference.strip(),
                    note.strip(),
                    section.source_identity,
                    section.source_identity_form,
                ),
            )
            self.connection.execute("COMMIT")
            return cursor.lastrowid
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def record_opening_source_review(
        self,
        account_id: str,
        source_sha256: str,
        *,
        opening_origin: Literal["reported", "unestablished"],
        timing_confirmed: bool,
        source_reference: str,
        note: str = "",
        expected_revision_id: int | None | object = _UNSET_REVIEW_REVISION,
        expected_section: tuple[str, str] | None = None,
        expected_basis_sha256: str | None = None,
    ) -> int:
        """Record a source inspection without altering its printed evidence."""
        candidate = next((item for item in self.earliest_source_openings() if item.account_id == account_id), None)
        if candidate is None or source_sha256 not in candidate.earliest_source_ids:
            raise ProfileFormatError("opening_source_not_earliest_bound")
        latest = next(
            (review for review in self.statement_source_reviews(account_id) if review.source_sha256 == source_sha256),
            None,
        )
        return self.record_statement_source_review(
            account_id,
            source_sha256,
            expected_revision_id=(latest.revision_id if latest else None)
            if expected_revision_id is _UNSET_REVIEW_REVISION
            else expected_revision_id,
            opening_origin=opening_origin,
            closing_origin=latest.closing_origin if latest else "unestablished",
            timing_confirmed=timing_confirmed,
            posting_dates=latest.posting_dates if latest else "unverified",
            source_reference=source_reference,
            note=note,
            expected_section=expected_section,
            expected_basis_sha256=expected_basis_sha256,
        )

    @staticmethod
    def _opening_basis(candidate: EarliestSourceOpening, reviews: tuple[StatementSourceReview, ...]) -> str:
        data = {
            "account_id": candidate.account_id,
            "period_start": candidate.earliest_period_start.isoformat() if candidate.earliest_period_start else None,
            "sources": candidate.earliest_source_ids,
            "amount_minor": candidate.printed_opening_minor,
            "reviews": [
                (review.source_sha256, review.revision_id)
                for review in reviews
                if review.source_sha256 in candidate.earliest_source_ids
            ],
        }
        return _digest(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())

    def opening_decision(self, account_id: str) -> OpeningDecision | None:
        self._require_financial_account(account_id)
        history = self.opening_decision_history(account_id)
        if not history:
            return None
        saved = history[0]
        stale = False
        if saved.state == "active":
            if saved.origin == "source":
                candidate = next(item for item in self.earliest_source_openings() if item.account_id == account_id)
                stale = bool(candidate.blockers) or saved.basis_sha256 != self._opening_basis(
                    candidate, self.statement_source_reviews(account_id)
                )
            else:
                stale = self._manual_opening_history_conflict(account_id, saved.cutoff_date)
        return OpeningDecision(
            account_id,
            saved.basis_sha256,
            saved.amount_minor,
            saved.cutoff_date,
            saved.entry_key,
            stale,
            saved.revision_id,
            saved.version,
            saved.origin,
            saved.state,
            saved.tracking_scope,
            saved.reference,
        )

    @staticmethod
    def _opening_decision_version(
        account_id,
        revision_id,
        basis,
        amount,
        cutoff,
        entry_key,
        prior_version=None,
        reason="Initial reviewed opening",
        origin="source",
        state="active",
        tracking_scope="account_total",
        reference="",
        request_basis=None,
        created_at=None,
    ) -> str:
        return _transfer_record_digest(
            account_id,
            revision_id,
            prior_version,
            basis,
            amount,
            cutoff,
            entry_key,
            reason,
            origin,
            state,
            tracking_scope,
            reference,
            basis if request_basis is None else request_basis,
            created_at,
        )

    @staticmethod
    def _manual_opening_basis(account_id, amount, cutoff, scope, reference):
        return _transfer_record_digest("manual-opening-1", account_id, amount, cutoff, scope, reference)

    def opening_decision_history(self, account_id: str) -> tuple[OpeningDecisionHistoryRow, ...]:
        """One immutable source/manual/withdrawal chain; zero and unknown remain distinct."""
        self._validate_journal_retirements()
        self._require_financial_account(account_id)
        account = next(a for a in self.financial_accounts() if a.id == account_id)
        saved = self.connection.execute(
            "SELECT basis_sha256,amount_minor,cutoff_date,entry_key,reason,decision_sha256,created_at,origin,state,tracking_scope,reference,request_basis FROM OpeningDecisions WHERE account_id=?",
            (account_id,),
        ).fetchone()
        revisions = self.connection.execute(
            "SELECT revision_id,prior_version,basis_sha256,amount_minor,cutoff_date,entry_key,reason,decision_sha256,created_at,origin,state,tracking_scope,reference,request_basis FROM OpeningDecisionRevisions WHERE account_id=? ORDER BY revision_id",
            (account_id,),
        ).fetchall()
        if saved is None:
            if revisions:
                raise ProfileFormatError("opening_decision_history_invalid")
            return ()
        rows = [(0, None, *saved), *revisions]
        prior = None
        result = []
        entry_reasons = {}
        for (
            revision,
            previous,
            basis,
            amount,
            cutoff,
            key,
            reason,
            stored,
            created,
            origin,
            state,
            scope,
            reference,
            request,
        ) in rows:
            try:
                if (
                    type(revision) is not int
                    or revision < 0
                    or previous != prior
                    or any(
                        type(v) is not str
                        for v in (basis, reason, stored, created, origin, state, scope, reference, request)
                    )
                    or any(re.fullmatch(r"[0-9a-f]{64}", v) is None for v in (basis, stored, request))
                    or not 0 < len(reason.strip()) <= 500
                    or len(reference) > 500
                    or not created
                    or origin not in {"source", "manual"}
                    or state not in {"active", "withdrawn"}
                    or scope not in TRACKING_SCOPES
                    or scope != account.tracking_scope
                ):
                    raise ValueError
                cutoff_date = None
                if state == "withdrawn":
                    if (
                        revision == 0
                        or amount is not None
                        or cutoff is not None
                        or key is not None
                        or basis != _transfer_record_digest("withdraw-opening-1", previous)
                    ):
                        raise ValueError
                else:
                    if (
                        type(amount) is not int
                        or not -(2**63) < amount < 2**63
                        or type(cutoff) is not str
                        or (amount == 0) != (key is None)
                    ):
                        raise ValueError
                    cutoff_date = date.fromisoformat(cutoff)
                    if cutoff_date.isoformat() != cutoff or (
                        origin == "source" and not self._admitted_source_opening_history(account, amount, cutoff_date)
                    ):
                        raise ValueError
                    if origin == "manual" and (
                        not reference.strip()
                        or basis != self._manual_opening_basis(account_id, amount, cutoff, scope, reference)
                    ):
                        raise ValueError
                if key is not None:
                    payload = self.connection.execute(
                        "SELECT payload FROM JournalEntries WHERE key=?", (key,)
                    ).fetchone()
                    entry = _decode_journal(payload[0]) if payload else None
                    entry_reasons.setdefault(key, reason)
                    if (
                        type(key) is not str
                        or entry is None
                        or entry.key != key
                        or entry.origin != "opening"
                        or entry.event_id != key
                        or entry.description != "Reviewed opening position"
                        or entry.reason != entry_reasons[key]
                        or not entry.reviewed
                        or entry.posting_date != cutoff_date
                        or len(entry.postings) != 2
                        or entry.postings[0] != Posting(account_id, amount)
                        or entry.postings[1] != Posting("internal:opening-equity:USD", -amount)
                        or self.connection.execute(
                            "SELECT 1 FROM JournalAllocations WHERE entry_key=? LIMIT 1", (key,)
                        ).fetchone()
                    ):
                        raise ValueError
                    if self.connection.execute(
                        "SELECT kind,role,purpose,currency FROM Accounts WHERE id='internal:opening-equity:USD'"
                    ).fetchone() != ("equity", "internal", "opening_equity", "USD"):
                        raise ValueError
                    validate_entry(entry, self._ledger_accounts(), {}, {})
                version = self._opening_decision_version(
                    account_id,
                    revision,
                    basis,
                    amount,
                    cutoff,
                    key,
                    previous,
                    reason,
                    origin,
                    state,
                    scope,
                    reference,
                    request,
                    created,
                )
                if stored != version:
                    raise ValueError
                result.append(
                    OpeningDecisionHistoryRow(
                        revision,
                        account_id,
                        basis,
                        amount,
                        cutoff_date,
                        key,
                        version,
                        previous,
                        reason,
                        created,
                        origin,
                        state,
                        scope,
                        reference,
                        request,
                    )
                )
                prior = version
            except (ProfileFormatError, LedgerError, TypeError, ValueError):
                raise ProfileFormatError("opening_decision_history_invalid") from None
        retirements = dict(self.connection.execute("SELECT original_key,reason FROM JournalRetirements"))
        for older, newer in zip(result, result[1:], strict=False):
            if (
                older.entry_key != newer.entry_key
                and older.entry_key is not None
                and retirements.get(older.entry_key) != newer.reason
            ):
                raise ProfileFormatError("opening_decision_history_invalid")
        if result[-1].entry_key is not None and result[-1].entry_key in self._inactive_journal_keys():
            raise ProfileFormatError("opening_decision_history_invalid")
        return tuple(reversed(result))

    def _validate_opening_decision_histories(self) -> None:
        """Validate stored decisions without demanding current source review."""
        for (account_id,) in self.connection.execute(
            "SELECT account_id FROM OpeningDecisions UNION SELECT account_id FROM OpeningDecisionRevisions"
        ).fetchall():
            self.opening_decision_history(account_id)

    def _anchor_write_start(self, reason: str) -> None:
        self._require_writable()
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("account_anchor_reason_required")
        if self.connection.in_transaction:
            raise ProfileFormatError("account_anchor_requires_committed_snapshot")
        self.connection.execute("BEGIN IMMEDIATE")

    def _anchor_account(self, account_id: str, scope: str) -> FinancialAccount:
        self._require_financial_account(account_id)
        account = next(a for a in self.financial_accounts() if a.id == account_id)
        if type(scope) is not str or scope not in TRACKING_SCOPES or scope != account.tracking_scope:
            raise ProfileFormatError("account_anchor_scope_mismatch")
        return account

    @staticmethod
    def _validate_anchor_value(amount, value_date, reference):
        if (
            type(amount) is not int
            or not -(2**63) < amount < 2**63
            or type(value_date) is not date
            or type(reference) is not str
            or not 0 < len(reference.strip()) <= 500
        ):
            raise ProfileFormatError("account_anchor_value_invalid")

    def _source_value_annotation(
        self,
        account_id: str,
        source_sha256: str,
        revision_id: int | None = None,
        *,
        source_identity: str | None = None,
        source_identity_form: str | None = None,
    ) -> SourceValueReviewAnnotation | None:
        if revision_id is None:
            if source_identity is None:
                bindings = self.connection.execute(
                    "SELECT source_identity,source_identity_form FROM SourceAccountBindings WHERE source_sha256=? AND ledger_account_id=?",
                    (source_sha256, account_id),
                ).fetchall()
                if len(bindings) != 1:
                    return None
                source_identity, source_identity_form = bindings[0]
            row = self.connection.execute(
                "SELECT revision_id,opening_origin,closing_origin,timing_confirmed,posting_dates,source_reference,note,source_identity,source_identity_form FROM StatementSourceReviews WHERE account_id=? AND source_sha256=? AND source_identity=? AND source_identity_form=? ORDER BY revision_id DESC LIMIT 1",
                (account_id, source_sha256, source_identity, source_identity_form),
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT revision_id,opening_origin,closing_origin,timing_confirmed,posting_dates,source_reference,note,source_identity,source_identity_form FROM StatementSourceReviews WHERE account_id=? AND source_sha256=? AND revision_id=?",
                (account_id, source_sha256, revision_id),
            ).fetchone()
            if row is None:
                raise ProfileFormatError("account_dated_value_source_proof_invalid")
        if row is None:
            return None
        if type(row[3]) is not int or row[3] not in {0, 1}:
            raise ProfileFormatError("account_dated_value_source_proof_invalid")
        return SourceValueReviewAnnotation(
            revision_id=row[0],
            opening_origin=row[1],
            closing_origin=row[2],
            timing_confirmed=bool(row[3]),
            posting_dates=row[4],
            source_reference=row[5],
            note=row[6],
            source_identity=row[7],
            source_identity_form=row[8],
        )

    def _validate_dated_source_proof(self, account: FinancialAccount, proof: SourceValueProof) -> None:
        saved = self.load_import(proof.source_sha256)
        payload = saved.evidence.payload
        if not isinstance(payload, StatementPayload):
            raise ProfileFormatError("account_dated_value_source_proof_invalid")
        sections = [
            s
            for s in payload.accounts
            if (s.source_identity, s.source_identity_form) == (proof.source_identity, proof.source_identity_form)
        ]
        if len(sections) != 1:
            raise ProfileFormatError("account_dated_value_source_proof_invalid")
        annotation = None
        if proof.review_annotation is not None:
            annotation = self._source_value_annotation(
                account.id, proof.source_sha256, proof.review_annotation.revision_id
            )
        digest = self.connection.execute(
            "SELECT sha256 FROM EvidenceSnapshots WHERE source_sha256=?", (proof.source_sha256,)
        ).fetchone()[0]
        expected = make_source_value_proof(
            saved.evidence,
            sections[0],
            financial_kind=account.kind,
            tracking_scope=account.tracking_scope,
            evidence_sha256=digest,
            review_annotation=annotation,
        )
        if proof != expected:
            raise ProfileFormatError("account_dated_value_source_proof_invalid")

    def _read_dated_value_withdrawals(self, values: dict[int, ReviewedDatedValue]) -> tuple[DatedValueWithdrawal, ...]:
        result = []
        for row in self.connection.execute("SELECT * FROM DatedValueWithdrawals ORDER BY withdrawal_id DESC"):
            number, value_id, prior, request, reason, checksum, created = row
            if (
                type(number) is not int
                or number <= 0
                or type(value_id) is not int
                or value_id not in values
                or any(type(v) is not str or not v for v in row[2:])
                or not 0 < len(reason.strip()) <= 500
                or any(re.fullmatch(r"[0-9a-f]{64}", v) is None for v in (prior, request, checksum))
                or prior != values[value_id].version
                or checksum != _transfer_record_digest(*row[:5], created)
            ):
                raise ProfileFormatError("account_dated_value_history_integrity")
            result.append(
                DatedValueWithdrawal(number, value_id, values[value_id].account_id, prior, reason, created, checksum)
            )
        return tuple(result)

    def _read_dated_values(self, account_id: str | None = None) -> tuple[ReviewedDatedValue, ...]:
        values = []
        by_id = {}
        corrected = {}
        for row in self.connection.execute("SELECT * FROM AccountDatedValues ORDER BY value_id"):
            (
                number,
                account,
                day,
                amount,
                scope,
                reference,
                reason,
                previous,
                request,
                checksum,
                created,
                origin,
                raw_proof,
                allow_conflict,
            ) = row
            try:
                if (
                    type(number) is not int
                    or number <= 0
                    or any(type(row[i]) is not str for i in (1, 2, 4, 5, 6, 8, 9, 10))
                    or any(re.fullmatch(r"[0-9a-f]{64}", v) is None for v in (request, checksum))
                    or not 0 < len(reason.strip()) <= 500
                    or not created
                    or origin not in {"manual", "source"}
                    or type(allow_conflict) is not int
                    or allow_conflict not in {0, 1}
                    or (origin == "manual") != (raw_proof is None)
                    or checksum != _transfer_record_digest(*row[:9], created, origin, raw_proof, allow_conflict)
                ):
                    raise ValueError
                financial = self._anchor_account(account, scope)
                value_date = date.fromisoformat(day)
                self._validate_anchor_value(amount, value_date, reference)
                if value_date.isoformat() != day:
                    raise ValueError
                proof = decode_source_value_proof(raw_proof) if origin == "source" else None
                if proof is not None:
                    self._validate_dated_source_proof(financial, proof)
                    if (
                        amount != proof.amount_minor
                        or value_date.isoformat() != proof.value_date.iso
                        or scope != proof.tracking_scope
                    ):
                        raise ValueError
                if previous is not None and (
                    type(previous) is not int
                    or previous not in by_id
                    or previous in corrected
                    or by_id[previous].account_id != account
                ):
                    raise ValueError
                item = ReviewedDatedValue(
                    number,
                    account,
                    value_date,
                    amount,
                    scope,
                    reference,
                    reason,
                    previous,
                    created,
                    checksum,
                    origin=origin,
                    source_proof=proof,
                    allow_conflict=bool(allow_conflict),
                    source_review_changed=proof is not None
                    and proof.review_annotation
                    != self._source_value_annotation(
                        account,
                        proof.source_sha256,
                        source_identity=proof.source_identity,
                        source_identity_form=proof.source_identity_form,
                    ),
                )
                values.append(item)
                by_id[number] = item
                if previous is not None:
                    corrected[previous] = number
            except (ProfileFormatError, TypeError, ValueError, RecursionError):
                raise ProfileFormatError("account_dated_value_history_integrity") from None
        withdrawals = {w.value_id: w for w in self._read_dated_value_withdrawals(by_id)}
        if set(withdrawals).intersection(corrected):
            raise ProfileFormatError("account_dated_value_history_integrity")
        for item in values:
            if item.value_id not in corrected and item.value_id not in withdrawals and item.source_proof is not None:
                proof = item.source_proof
                if self.connection.execute(
                    "SELECT ledger_account_id FROM SourceAccountBindings WHERE source_sha256=? AND source_identity=? AND source_identity_form=?",
                    (proof.source_sha256, proof.source_identity, proof.source_identity_form),
                ).fetchone() != (item.account_id,):
                    raise ProfileFormatError("account_dated_value_history_integrity")
        return tuple(
            replace(
                item, superseded_by_value_id=corrected.get(item.value_id), withdrawal=withdrawals.get(item.value_id)
            )
            for item in reversed(values)
            if account_id is None or item.account_id == account_id
        )

    def _read_account_lifecycle(self, account_id: str | None = None) -> tuple[AccountLifecycleDecision, ...]:
        values = []
        latest = {}
        phases = {}
        for row in self.connection.execute("SELECT * FROM AccountLifecycleDecisions ORDER BY revision_id"):
            number, account, state, day, reason, previous, request, checksum, created = row
            try:
                if (
                    type(number) is not int
                    or number <= 0
                    or any(type(row[i]) is not str for i in (1, 2, 3, 4, 6, 7, 8))
                    or state not in {"open", "closed"}
                    or not 0 < len(reason.strip()) <= 500
                    or not created
                    or any(re.fullmatch(r"[0-9a-f]{64}", v) is None for v in (request, checksum))
                    or checksum != _transfer_record_digest(*row[:7], created)
                ):
                    raise ValueError
                self._require_financial_account(account)
                effective = date.fromisoformat(day)
                if effective.isoformat() != day or previous != (latest[account].version if account in latest else None):
                    raise ValueError
                events = phases.setdefault(account, [])
                if events and events[-1].state == state:
                    events.pop()
                if events and effective < events[-1].effective_date:
                    raise ValueError
                item = AccountLifecycleDecision(number, account, state, effective, reason, previous, created, checksum)
                events.append(item)
                latest[account] = item
                values.append(item)
            except (ProfileFormatError, TypeError, ValueError):
                raise ProfileFormatError("account_lifecycle_history_integrity") from None
        return tuple(item for item in reversed(values) if account_id is None or item.account_id == account_id)

    def _account_lifecycle_at(self, account_id: str, as_of: date) -> AccountLifecycleDecision | None:
        return next(
            (item for item in reversed(self._account_lifecycle_phases(account_id)) if item.effective_date <= as_of),
            None,
        )

    def _account_lifecycle_phases(self, account_id: str) -> tuple[AccountLifecycleDecision, ...]:
        phases = []
        for item in reversed(self._read_account_lifecycle(account_id)):
            if phases and phases[-1].state == item.state:
                phases.pop()
            phases.append(item)
        return tuple(phases)

    def _latest_dated_value(self, account_id: str, as_of: date) -> ReviewedDatedValue | None:
        return self._dated_value_point(account_id, as_of)[1]

    def _dated_value_point(self, account_id: str, as_of: date):
        values = tuple(
            item for item in self._read_dated_values(account_id) if item.state == "active" and item.value_date <= as_of
        )
        if not values:
            return "missing", None, ()
        latest_date = max(item.value_date for item in values)
        current = tuple(item for item in values if item.value_date == latest_date)
        if len({item.amount_minor for item in current}) > 1:
            return "conflict", None, current
        return "known", max(current, key=lambda item: item.value_id), current

    def _validate_account_metadata(self) -> None:
        self._validate_builtin_categories()
        self._validate_transfer_clearing()
        for (account_id,) in self.connection.execute("SELECT DISTINCT account_id FROM StatementSourceReviews"):
            self.statement_source_review_history(account_id)
        if not self._account_anchors_mutating:
            if any(
                type(scope) is not str or scope not in TRACKING_SCOPES
                for (scope,) in self.connection.execute("SELECT tracking_scope FROM Accounts")
            ):
                raise ProfileFormatError("account_tracking_scope_integrity")
            self._read_dated_values()
            self._read_account_lifecycle()
            self._validate_opening_decision_histories()

    def _source_value_candidates(self, account_id: str) -> tuple[SourceClosingCandidate, ...]:
        self._require_financial_account(account_id)
        review_history = {r.revision_id: r for r in self.statement_source_review_history(account_id)}
        account = next(a for a in self.financial_accounts() if a.id == account_id)
        candidates = []
        bindings = self.connection.execute(
            "SELECT source_sha256,source_identity,source_identity_form FROM SourceAccountBindings WHERE ledger_account_id=? ORDER BY source_sha256,source_identity,source_identity_form",
            (account_id,),
        ).fetchall()
        for source_id, identity, form in bindings:
            evidence = self.load_import(source_id).evidence
            if not isinstance(evidence.payload, StatementPayload):
                continue
            sections = [
                s for s in evidence.payload.accounts if (s.source_identity, s.source_identity_form) == (identity, form)
            ]
            if len(sections) != 1:
                raise ProfileFormatError("source_value_bound_section_unavailable")
            section = sections[0]
            annotation = self._source_value_annotation(
                account_id, source_id, source_identity=identity, source_identity_form=form
            )
            review = review_history.get(annotation.revision_id) if annotation is not None else None
            digest = self.connection.execute(
                "SELECT sha256 FROM EvidenceSnapshots WHERE source_sha256=?", (source_id,)
            ).fetchone()[0]
            proof, blockers = None, ()
            try:
                proof = make_source_value_proof(
                    evidence,
                    section,
                    financial_kind=account.kind,
                    tracking_scope=account.tracking_scope,
                    evidence_sha256=digest,
                    review_annotation=annotation,
                )
            except ValueError as exc:
                blockers = (str(exc),)
            candidate_id = source_value_candidate_id(source_id, section)
            version = _transfer_record_digest(
                candidate_id,
                account_id,
                account.kind,
                account.tracking_scope,
                digest,
                proof_payload(proof) if proof else None,
                blockers,
                annotation.model_dump(mode="json") if annotation else None,
            )
            rule = SOURCE_VALUE_RULES.get(evidence.parser_id)
            candidates.append(
                SourceClosingCandidate(
                    candidate_id,
                    version,
                    account_id,
                    source_id,
                    identity,
                    form,
                    date.fromisoformat(proof.value_date.iso) if proof else None,
                    proof.amount_minor if proof else None,
                    section.balance_scope,
                    proof,
                    blockers,
                    review,
                    evidence.payload.capture_verified,
                    section.closing,
                    evidence.payload.end,
                    evidence.parser_id,
                    evidence.definition_revision,
                    rule.sign_rule if rule else None,
                    False,
                )
            )
        return tuple(candidates)

    def source_dated_value_snapshot(self, account_id: str, *, as_of: date | None = None) -> AccountAnchorSnapshot:
        return self.account_anchor_snapshot(account_id, as_of=as_of)

    def _account_anchor_basis(self) -> str:
        rule, version = self._reconciliation_rule_and_version()
        return _transfer_record_digest("account-anchor-1", rule, version)

    def account_anchor_snapshot(self, account_id: str, *, as_of: date | None = None) -> AccountAnchorSnapshot:
        if self.connection.in_transaction:
            raise ProfileFormatError("account_anchor_requires_committed_snapshot")
        if as_of is None:
            as_of = date.today()
        if type(as_of) is not date:
            raise ProfileFormatError("account_anchor_date_invalid")
        self.connection.execute("BEGIN")
        try:
            self._require_financial_account(account_id)
            account = next(a for a in self.financial_accounts() if a.id == account_id)
            history = self.opening_decision_history(account_id)
            opening = self.opening_decision(account_id)
            lifecycle = self._read_account_lifecycle(account_id)
            recorded = sum(
                p.amount_minor
                for (payload,) in self.connection.execute("SELECT payload FROM JournalEntries")
                for entry in (_decode_journal(payload),)
                if entry.reviewed and entry.posting_date <= as_of
                for p in entry.postings
                if p.account_id == account_id
            )
            earliest = self._earliest_known_account_activity(account_id)
            boundaries = self._account_opening_boundaries(account_id)
            value_status, latest_value, current_values = self._dated_value_point(account_id, as_of)
            value_history = self._read_dated_values(account_id)
            valid = (
                opening is not None and opening.state == "active" and not opening.stale and opening.cutoff_date <= as_of
            )
            if valid and any(
                entry.key != opening.entry_key
                and entry.posting_date <= opening.cutoff_date
                and any(p.account_id == account_id for p in entry.postings)
                for entry in self._active_journal_entries()
            ):
                valid = False
            return AccountAnchorSnapshot(
                account,
                opening,
                history,
                value_history,
                latest_value,
                lifecycle[0] if lifecycle else None,
                lifecycle,
                earliest,
                self._account_anchor_basis(),
                recorded,
                recorded if valid else None,
                min((item.boundary_date for item in boundaries), default=None),
                boundaries,
                self._source_value_candidates(account_id),
                tuple(v.withdrawal for v in value_history if v.withdrawal is not None),
                value_status,
                current_values if value_status == "conflict" else (),
                current_values,
            )
        finally:
            self.connection.execute("ROLLBACK")

    def record_reviewed_dated_value(
        self,
        account_id: str,
        *,
        amount_minor: int,
        value_date: date,
        tracking_scope: str,
        reference: str,
        reason: str,
        expected_basis_sha256: str,
        corrects_value_id: int | None = None,
        allow_conflict: bool = False,
    ) -> ReviewedDatedValue:
        self._anchor_write_start(reason)
        try:
            result = self._append_dated_value(
                account_id,
                amount_minor=amount_minor,
                value_date=value_date,
                tracking_scope=tracking_scope,
                reference=reference,
                reason=reason,
                expected_basis_sha256=expected_basis_sha256,
                corrects_value_id=corrects_value_id,
                allow_conflict=allow_conflict,
            )
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def _append_dated_value(
        self,
        account_id,
        *,
        amount_minor,
        value_date,
        tracking_scope,
        reference,
        reason,
        expected_basis_sha256,
        corrects_value_id=None,
        allow_conflict=False,
        source_proof=None,
    ) -> ReviewedDatedValue:
        if (
            type(expected_basis_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_basis_sha256) is None
            or (corrects_value_id is not None and type(corrects_value_id) is not int)
            or type(allow_conflict) is not bool
        ):
            raise ProfileFormatError("account_anchor_version_required")
        self._anchor_account(account_id, tracking_scope)
        self._validate_anchor_value(amount_minor, value_date, reference)
        origin = "source" if source_proof is not None else "manual"
        raw_proof = proof_payload(source_proof) if source_proof is not None else None
        history = self._read_dated_values(account_id)
        prior = self.connection.execute(
            "SELECT value_id FROM AccountDatedValues WHERE account_id=? AND value_date=? AND amount_minor=? AND tracking_scope=? AND reference=? AND reason=? AND corrects_value_id IS ? AND request_basis=? AND origin=? AND source_proof IS ? AND allow_conflict=?",
            (
                account_id,
                value_date.isoformat(),
                amount_minor,
                tracking_scope,
                reference.strip(),
                reason.strip(),
                corrects_value_id,
                expected_basis_sha256,
                origin,
                raw_proof,
                int(allow_conflict),
            ),
        ).fetchone()
        if prior:
            return next(v for v in history if v.value_id == prior[0])
        if self._account_anchor_basis() != expected_basis_sha256:
            raise ProfileFormatError("account_anchor_changed_since_selection")
        if corrects_value_id is not None and not any(
            v.value_id == corrects_value_id and v.state == "active" for v in history
        ):
            raise ProfileFormatError("account_dated_value_correction_unavailable")
        if (
            dated_value_conflicts(
                history, value_date=value_date, amount_minor=amount_minor, corrects_value_id=corrects_value_id
            )
            and not allow_conflict
        ):
            raise ProfileFormatError("account_dated_value_conflict_requires_review")
        number = self.connection.execute("SELECT coalesce(max(value_id),0)+1 FROM AccountDatedValues").fetchone()[0]
        created = self.connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
        fields = (
            number,
            account_id,
            value_date.isoformat(),
            amount_minor,
            tracking_scope,
            reference.strip(),
            reason.strip(),
            corrects_value_id,
            expected_basis_sha256,
        )
        checksum = _transfer_record_digest(*fields, created, origin, raw_proof, int(allow_conflict))
        self.connection.execute(
            "INSERT INTO AccountDatedValues VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*fields, checksum, created, origin, raw_proof, int(allow_conflict)),
        )
        return next(v for v in self._read_dated_values(account_id) if v.value_id == number)

    def record_reviewed_source_value(
        self,
        account_id: str,
        candidate_id: str,
        *,
        expected_candidate_sha256: str,
        expected_basis_sha256: str,
        reference: str,
        reason: str,
        corrects_value_id: int | None = None,
        allow_conflict: bool = False,
    ) -> ReviewedDatedValue:
        self._anchor_write_start(reason)
        try:
            if (
                type(candidate_id) is not str
                or type(expected_candidate_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", expected_candidate_sha256) is None
                or type(expected_basis_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", expected_basis_sha256) is None
                or type(allow_conflict) is not bool
                or (corrects_value_id is not None and type(corrects_value_id) is not int)
            ):
                raise ProfileFormatError("account_anchor_version_required")
            if type(reference) is not str or not 0 < len(reference.strip()) <= 500:
                raise ProfileFormatError("account_anchor_value_invalid")
            # Exact historical retry may return its old receipt after retirement,
            # never act on a newly established value of the same source point.
            for value in self._read_dated_values(account_id):
                proof = value.source_proof
                if (
                    proof is None
                    or value.corrects_value_id != corrects_value_id
                    or value.reference != reference.strip()
                    or value.reason != reason.strip()
                    or value.allow_conflict != allow_conflict
                ):
                    continue
                # Candidate IDs use the same finite source/section tuple.
                source_id = _digest(
                    json.dumps(
                        (proof.source_sha256, proof.source_identity, proof.source_identity_form), separators=(",", ":")
                    ).encode()
                )
                old_version = _transfer_record_digest(
                    source_id,
                    account_id,
                    proof.financial_kind,
                    proof.tracking_scope,
                    proof.evidence_sha256,
                    proof_payload(proof),
                    (),
                    proof.review_annotation.model_dump(mode="json") if proof.review_annotation else None,
                )
                prior_basis = self.connection.execute(
                    "SELECT request_basis FROM AccountDatedValues WHERE value_id=?", (value.value_id,)
                ).fetchone()[0]
                if (
                    source_id == candidate_id
                    and old_version == expected_candidate_sha256
                    and prior_basis == expected_basis_sha256
                ):
                    self.connection.execute("COMMIT")
                    return value
            candidate = next(
                (c for c in self._source_value_candidates(account_id) if c.candidate_id == candidate_id), None
            )
            if candidate is None or candidate.proof is None or candidate.blockers:
                raise ProfileFormatError("source_value_candidate_unavailable")
            if candidate.version != expected_candidate_sha256:
                raise ProfileFormatError("source_value_candidate_changed_since_selection")
            result = self._append_dated_value(
                account_id,
                amount_minor=candidate.amount_minor,
                value_date=candidate.value_date,
                tracking_scope=candidate.tracking_scope,
                reference=reference,
                reason=reason,
                expected_basis_sha256=expected_basis_sha256,
                corrects_value_id=corrects_value_id,
                allow_conflict=allow_conflict,
                source_proof=candidate.proof,
            )
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def withdraw_reviewed_dated_value(
        self,
        account_id: str,
        value_id: int,
        *,
        expected_value_version: str,
        expected_basis_sha256: str,
        reason: str,
    ) -> DatedValueWithdrawal:
        self._anchor_write_start(reason)
        try:
            if type(value_id) is not int or any(
                type(v) is not str or re.fullmatch(r"[0-9a-f]{64}", v) is None
                for v in (expected_value_version, expected_basis_sha256)
            ):
                raise ProfileFormatError("account_anchor_version_required")
            history = self._read_dated_values(account_id)
            selected = next((v for v in history if v.value_id == value_id), None)
            if selected is None or selected.version != expected_value_version:
                raise ProfileFormatError("account_dated_value_changed_since_selection")
            if selected.withdrawal is not None:
                basis = self.connection.execute(
                    "SELECT request_basis FROM DatedValueWithdrawals WHERE withdrawal_id=?",
                    (selected.withdrawal.withdrawal_id,),
                ).fetchone()[0]
                if selected.withdrawal.reason == reason.strip() and basis == expected_basis_sha256:
                    self.connection.execute("COMMIT")
                    return selected.withdrawal
                raise ProfileFormatError("account_dated_value_withdrawal_unavailable")
            if selected.state != "active":
                raise ProfileFormatError("account_dated_value_withdrawal_unavailable")
            if self._account_anchor_basis() != expected_basis_sha256:
                raise ProfileFormatError("account_anchor_changed_since_selection")
            number = self.connection.execute(
                "SELECT coalesce(max(withdrawal_id),0)+1 FROM DatedValueWithdrawals"
            ).fetchone()[0]
            created = self.connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
            fields = (number, value_id, selected.version, expected_basis_sha256, reason.strip())
            self.connection.execute(
                "INSERT INTO DatedValueWithdrawals VALUES (?,?,?,?,?,?,?)",
                (*fields, _transfer_record_digest(*fields, created), created),
            )
            result = next(v.withdrawal for v in self._read_dated_values(account_id) if v.value_id == value_id)
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def record_account_lifecycle(
        self,
        account_id: str,
        *,
        state: str,
        effective_date: date,
        reason: str,
        expected_version: str | None,
        expected_basis_sha256: str,
    ) -> AccountLifecycleDecision:
        self._anchor_write_start(reason)
        try:
            if (
                type(expected_basis_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", expected_basis_sha256) is None
                or (
                    expected_version is not None
                    and (type(expected_version) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_version) is None)
                )
            ):
                raise ProfileFormatError("account_anchor_version_required")
            self._require_financial_account(account_id)
            if type(state) is not str or state not in {"open", "closed"} or type(effective_date) is not date:
                raise ProfileFormatError("account_lifecycle_invalid")
            history = self._read_account_lifecycle(account_id)
            current = history[0] if history else None
            for receipt in history:
                if (
                    receipt.prior_version == expected_version
                    and receipt.state == state
                    and receipt.effective_date == effective_date
                    and receipt.reason == reason.strip()
                ):
                    request = self.connection.execute(
                        "SELECT request_basis FROM AccountLifecycleDecisions WHERE revision_id=?",
                        (receipt.revision_id,),
                    ).fetchone()[0]
                    if request == expected_basis_sha256:
                        self.connection.execute("COMMIT")
                        return receipt
            if expected_version != (current.version if current else None):
                raise ProfileFormatError("account_lifecycle_changed_since_selection")
            if self._account_anchor_basis() != expected_basis_sha256:
                raise ProfileFormatError("account_anchor_changed_since_selection")
            phases = list(self._account_lifecycle_phases(account_id))
            if phases and phases[-1].state == state:
                phases.pop()
            if phases and effective_date < phases[-1].effective_date:
                raise ProfileFormatError("account_lifecycle_date_order")
            number = self.connection.execute(
                "SELECT coalesce(max(revision_id),0)+1 FROM AccountLifecycleDecisions"
            ).fetchone()[0]
            created = self.connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
            fields = (
                number,
                account_id,
                state,
                effective_date.isoformat(),
                reason.strip(),
                expected_version,
                expected_basis_sha256,
            )
            self.connection.execute(
                "INSERT INTO AccountLifecycleDecisions VALUES (?,?,?,?,?,?,?,?,?)",
                (*fields, _transfer_record_digest(*fields, created), created),
            )
            result = self._read_account_lifecycle(account_id)[0]
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def opening_review_snapshot(self, account_id: str) -> OpeningReviewSnapshot:
        if self.connection.in_transaction:
            raise ProfileFormatError("opening_requires_committed_snapshot")
        self.connection.execute("BEGIN")
        try:
            self._require_financial_account(account_id)
            candidate = next(item for item in self.earliest_source_openings() if item.account_id == account_id)
            reviews = self.statement_source_reviews(account_id)
            return OpeningReviewSnapshot(
                candidate,
                reviews,
                self.opening_decision(account_id),
                self._opening_basis(candidate, reviews),
                self.opening_decision_history(account_id),
                tuple(
                    section
                    for section in self.statement_coverage()
                    if section.account_id == account_id and section.source_sha256 in candidate.earliest_source_ids
                ),
                self._account_anchor_basis(),
            )
        finally:
            self.connection.execute("ROLLBACK")

    def opening_review_basis(self, account_id: str) -> str:
        candidate = next((item for item in self.earliest_source_openings() if item.account_id == account_id), None)
        if candidate is None:
            raise ProfileFormatError("financial_account_missing")
        return self._opening_basis(candidate, self.statement_source_reviews(account_id))

    def earliest_source_openings(self) -> tuple[EarliestSourceOpening, ...]:
        """Inventory earliest explicitly bound statement openings without posting them."""
        sections: dict[str, list[tuple[str, date | None, StatementAccount]]] = {}
        saved: dict[str, SourceEvidence] = {}
        for source_id, identity, form, account_id in self.connection.execute(
            "SELECT source_sha256,source_identity,source_identity_form,ledger_account_id "
            "FROM SourceAccountBindings ORDER BY source_sha256,source_identity"
        ):
            evidence = saved.get(source_id)
            if evidence is None:
                evidence = self.load_import(source_id).evidence
                saved[source_id] = evidence
            payload = evidence.payload
            if not isinstance(payload, StatementPayload):
                continue
            source_account = next(
                (
                    account
                    for account in payload.accounts
                    if (account.source_identity, account.source_identity_form) == (identity, form)
                ),
                None,
            )
            if source_account is None:
                raise ProfileFormatError("opening_bound_source_account_missing")
            sections.setdefault(account_id, []).append(
                (
                    source_id,
                    date.fromisoformat(payload.start.iso) if payload.start.iso is not None else None,
                    source_account,
                )
            )
        result = []
        for financial in self.financial_accounts():
            bound = sections.get(financial.id, [])
            if not bound:
                result.append(
                    EarliestSourceOpening(
                        financial.id, financial.name, financial.kind, 0, None, (), None, ("no_bound_statement",)
                    )
                )
                continue
            if any(start is None for _source_id, start, _account in bound):
                result.append(
                    EarliestSourceOpening(
                        financial.id,
                        financial.name,
                        financial.kind,
                        len(bound),
                        None,
                        tuple(sorted({source_id for source_id, _start, _account in bound})),
                        None,
                        ("unknown_source_period", "source_timing_unreviewed"),
                    )
                )
                continue
            earliest = min(start for _source_id, start, _account in bound if start is not None)
            tied = [(source_id, account) for source_id, start, account in bound if start == earliest]
            blockers = []
            if any(
                not admitted_statement_scope(
                    saved[source_id].parser_id, account.balance_scope, financial.kind, financial.tracking_scope
                )
                for source_id, account in tied
            ):
                blockers.append("non_account_total_scope")
            if any(
                account.opening is None or account.opening.provenance != "observed" or account.opening.minor is None
                for _source_id, account in tied
            ):
                blockers.append("printed_opening_unavailable")
            amounts = {
                account.opening.minor
                for _source_id, account in tied
                if account.opening is not None and account.opening.provenance == "observed"
            }
            if len(amounts) > 1:
                blockers.append("conflicting_earliest_openings")
            if len(tied) != len({source_id for source_id, _account in tied}):
                blockers.append("duplicate_earliest_source_sections")
            printed_opening = next(iter(amounts)) if not blockers and len(amounts) == 1 else None
            reviews = {review.source_sha256: review for review in self.statement_source_reviews(financial.id)}
            if any(
                (review := reviews.get(source_id)) is None
                or review.opening_origin != "reported"
                or not review.timing_confirmed
                for source_id, _account in tied
            ):
                blockers.append("source_timing_unreviewed")
            result.append(
                EarliestSourceOpening(
                    financial.id,
                    financial.name,
                    financial.kind,
                    len(bound),
                    earliest,
                    tuple(sorted({source_id for source_id, _account in tied})),
                    printed_opening,
                    tuple(blockers),
                )
            )
        return tuple(result)

    def _account_activity_boundaries(self, account_id: str) -> tuple[AccountOpeningBoundary, ...]:
        bounds = []
        for source_id in self.source_ids():
            bound = {b.row_id for b in self.account_bindings(source_id) if b.ledger_account_id == account_id}
            for row in _rows(self.load_import(source_id).evidence):
                if row.row_id not in bound or row.row_role != "activity":
                    continue
                for actual in (row.transaction_date, row.date):
                    if actual is not None and actual.iso is not None and actual.provenance in {"observed", "derived"}:
                        bounds.append(
                            AccountOpeningBoundary(
                                date.fromisoformat(actual.iso), "activity", False, source_id, row.row_id
                            )
                        )
        entries = {
            key: _decode_journal(payload)
            for key, payload in self.connection.execute("SELECT key,payload FROM JournalEntries")
        }
        openings = {key for key, entry in entries.items() if entry.origin == "opening"}
        openings.update(
            inverse
            for original, inverse in self.connection.execute("SELECT original_key,reversal_key FROM JournalRetirements")
            if original in openings
        )
        inactive = frozenset(key for (key,) in self.connection.execute(_INACTIVE_JOURNAL_SQL))
        bounds.extend(
            AccountOpeningBoundary(entry.posting_date, "journal", False, reference=key)
            for key, entry in entries.items()
            if key not in inactive and key not in openings and any(p.account_id == account_id for p in entry.postings)
        )
        return tuple(set(bounds))

    def _earliest_known_account_activity(self, account_id: str) -> date | None:
        return min((bound.boundary_date for bound in self._account_activity_boundaries(account_id)), default=None)

    def _account_opening_boundaries(self, account_id: str) -> tuple[AccountOpeningBoundary, ...]:
        bounds = list(self._account_activity_boundaries(account_id))
        associated = {
            source
            for (source,) in self.connection.execute(
                "SELECT DISTINCT source_sha256 FROM SourceAccountBindings WHERE ledger_account_id=?", (account_id,)
            )
        }
        for source_id in associated:
            payload = self.load_import(source_id).evidence.payload
            if not isinstance(payload, StatementPayload):
                continue
            if payload.start.iso is not None and payload.start.provenance in {"observed", "derived"}:
                bounds.append(
                    AccountOpeningBoundary(
                        date.fromisoformat(payload.start.iso),
                        "statement_start",
                        False,
                        source_id,
                        "Known statement interval",
                    )
                )
            elif payload.end.iso is not None and payload.end.provenance in {"observed", "derived"}:
                bounds.append(
                    AccountOpeningBoundary(
                        date.fromisoformat(payload.end.iso),
                        "statement_end",
                        True,
                        source_id,
                        "First known statement endpoint",
                    )
                )
        bounds.extend(
            AccountOpeningBoundary(item.value_date, "dated_value", True, reference=str(item.value_id))
            for item in self._read_dated_values(account_id)
            if item.state == "active"
        )
        bounds.extend(
            AccountOpeningBoundary(item.effective_date, "lifecycle", True, reference=str(item.revision_id))
            for item in self._account_lifecycle_phases(account_id)
        )
        return tuple(
            sorted(
                set(bounds),
                key=lambda item: (
                    item.boundary_date,
                    item.allows_equal,
                    item.kind,
                    item.source_sha256 or "",
                    item.reference,
                ),
            )
        )

    def _manual_opening_history_conflict(self, account_id: str, cutoff: date) -> bool:
        return any(
            cutoff > bound.boundary_date or (cutoff == bound.boundary_date and not bound.allows_equal)
            for bound in self._account_opening_boundaries(account_id)
        )

    def _append_opening_decision(
        self, account_id, *, current, origin, state, amount, cutoff, basis, reference, reason, request_basis
    ):
        account = next(a for a in self.financial_accounts() if a.id == account_id)
        if state == "active":
            if origin == "manual":
                if self._manual_opening_history_conflict(account_id, cutoff):
                    raise ProfileFormatError("opening_earlier_activity_conflict")
            for entry in self._active_journal_entries():
                if (
                    entry.key != (current.entry_key if current else None)
                    and entry.posting_date <= cutoff
                    and any(p.account_id == account_id for p in entry.postings)
                ):
                    raise ProfileFormatError("opening_earlier_posting_conflict")
        self._account_anchors_mutating = True
        try:
            key = current.entry_key if current else None
            keep = (
                current is not None
                and current.state == "active"
                and state == "active"
                and current.origin == origin
                and current.amount_minor == amount
                and current.cutoff_date == cutoff
            )
            if not keep:
                if key is not None:
                    payload = self.connection.execute(
                        "SELECT payload FROM JournalEntries WHERE key=?", (key,)
                    ).fetchone()[0]
                    self._retire_journal_entry(_decode_journal(payload), reason=reason)
                key = None
                if state == "active" and amount != 0:
                    equity = "internal:opening-equity:USD"
                    self.connection.execute(
                        "INSERT OR IGNORE INTO Accounts VALUES (?,?,?,'USD','internal','opening_equity',NULL,NULL,'account_total')",
                        (equity, "Opening equity", "equity"),
                    )
                    if current is None:
                        key = ("review:opening:" if origin == "source" else "review:opening:manual:") + account_id
                    else:
                        key = "review:opening:correction:" + _transfer_record_digest(
                            account_id, current.version, basis, reason, origin
                        )
                    entry = JournalEntry(
                        key=key,
                        event_id=key,
                        posting_date=cutoff,
                        description="Reviewed opening position",
                        postings=(Posting(account_id, amount), Posting(equity, -amount)),
                        origin="opening",
                        reviewed=True,
                        reason=reason,
                    )
                    validate_entry(entry, self._ledger_accounts(), {}, {})
                    self.connection.execute(
                        "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (key, _journal_payload(entry))
                    )
            revision = (
                0
                if current is None
                else self.connection.execute(
                    "SELECT coalesce(max(revision_id),0)+1 FROM OpeningDecisionRevisions"
                ).fetchone()[0]
            )
            previous = current.version if current else None
            cutoff_text = cutoff.isoformat() if cutoff is not None else None
            created = self.connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
            version = self._opening_decision_version(
                account_id,
                revision,
                basis,
                amount,
                cutoff_text,
                key,
                previous,
                reason,
                origin,
                state,
                account.tracking_scope,
                reference,
                request_basis,
                created,
            )
            if current is None:
                self.connection.execute(
                    "INSERT INTO OpeningDecisions (account_id,basis_sha256,amount_minor,cutoff_date,entry_key,decision_sha256,origin,state,tracking_scope,reference,reason,request_basis,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        account_id,
                        basis,
                        amount,
                        cutoff_text,
                        key,
                        version,
                        origin,
                        state,
                        account.tracking_scope,
                        reference,
                        reason,
                        request_basis,
                        created,
                    ),
                )
            else:
                self.connection.execute(
                    "INSERT INTO OpeningDecisionRevisions (revision_id,account_id,prior_version,basis_sha256,amount_minor,cutoff_date,entry_key,reason,decision_sha256,origin,state,tracking_scope,reference,request_basis,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        revision,
                        account_id,
                        previous,
                        basis,
                        amount,
                        cutoff_text,
                        key,
                        reason,
                        version,
                        origin,
                        state,
                        account.tracking_scope,
                        reference,
                        request_basis,
                        created,
                    ),
                )
        finally:
            self._account_anchors_mutating = False
        return self.opening_decision(account_id)

    def post_reviewed_opening(self, account_id: str, *, expected_basis_sha256: str | None = None) -> OpeningDecision:
        self._require_writable()
        if self.connection.in_transaction:
            raise ProfileFormatError("opening_requires_committed_snapshot")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            candidate = next((c for c in self.earliest_source_openings() if c.account_id == account_id), None)
            if (
                candidate is None
                or candidate.blockers
                or candidate.earliest_period_start is None
                or candidate.printed_opening_minor is None
            ):
                raise ProfileFormatError("opening_review_blocked")
            if candidate.earliest_period_start == date.min:
                raise ProfileFormatError("opening_cutoff_unavailable")
            basis = self._opening_basis(candidate, self.statement_source_reviews(account_id))
            if expected_basis_sha256 is not None and expected_basis_sha256 != basis:
                raise ProfileFormatError("opening_review_changed_since_selection")
            current = self.opening_decision(account_id)
            cutoff = date.fromordinal(candidate.earliest_period_start.toordinal() - 1)
            if current is not None:
                if (
                    current.origin == "source"
                    and current.state == "active"
                    and not current.stale
                    and (current.basis_sha256, current.amount_minor, current.cutoff_date)
                    == (basis, candidate.printed_opening_minor, cutoff)
                ):
                    self.connection.execute("COMMIT")
                    return current
                raise ProfileFormatError("opening_already_decided")
            result = self._append_opening_decision(
                account_id,
                current=None,
                origin="source",
                state="active",
                amount=candidate.printed_opening_minor,
                cutoff=cutoff,
                basis=basis,
                reference="",
                reason="Initial reviewed opening",
                request_basis=basis,
            )
            self.connection.execute("COMMIT")
            return result
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("opening_posting_refused") from None
            raise

    def _retire_journal_entry(self, original: JournalEntry, *, reason: str) -> str:
        """Transaction-owned inverse plus link; callers admit the specific workflow."""
        if not self.connection.in_transaction:
            raise ProfileFormatError("journal_retirement_requires_transaction")
        if original.key in self._inactive_journal_keys():
            raise ProfileFormatError("journal_retirement_original_inactive")
        saved = self.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (original.key,)).fetchone()
        if saved is None or saved[0] != _journal_payload(original):
            raise ProfileFormatError("journal_retirement_original_changed")
        inverse = JournalEntry(
            key="retirement:" + _digest(original.key.encode()),
            event_id=original.event_id,
            posting_date=original.posting_date,
            description="Retirement: " + original.description,
            postings=tuple(Posting(posting.account_id, -posting.amount_minor) for posting in original.postings),
            origin="opening" if original.origin == "opening" else "manual",
            reviewed=True,
            reason=reason,
        )
        validate_entry(inverse, self._ledger_accounts(), {}, self._active_consumed())
        inverse = replace(inverse, origin="reversal")
        self.connection.execute(
            "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (inverse.key, _journal_payload(inverse))
        )
        self.connection.execute(
            "INSERT INTO JournalRetirements(original_key,reversal_key,reason) VALUES (?,?,?)",
            (original.key, inverse.key, reason),
        )
        return inverse.key

    def correct_reviewed_opening(
        self, account_id: str, *, expected_decision_version: str, expected_basis_sha256: str, reason: str
    ) -> OpeningDecision:
        if self.connection.in_transaction:
            raise ProfileFormatError("opening_requires_committed_snapshot")
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("opening_correction_reason_required")
        if any(
            type(v) is not str or re.fullmatch(r"[0-9a-f]{64}", v) is None
            for v in (expected_decision_version, expected_basis_sha256)
        ):
            raise ProfileFormatError("opening_correction_version_required")
        self._anchor_write_start(reason)
        try:
            current = self.opening_decision(account_id)
            if current is None:
                raise ProfileFormatError("opening_correction_decision_missing")
            candidate = next(c for c in self.earliest_source_openings() if c.account_id == account_id)
            basis = self._opening_basis(candidate, self.statement_source_reviews(account_id))
            if basis != expected_basis_sha256:
                raise ProfileFormatError("opening_review_changed_since_selection")
            if candidate.blockers or candidate.earliest_period_start is None or candidate.printed_opening_minor is None:
                raise ProfileFormatError("opening_review_blocked")
            if candidate.earliest_period_start == date.min:
                raise ProfileFormatError("opening_cutoff_unavailable")
            cutoff = date.fromordinal(candidate.earliest_period_start.toordinal() - 1)
            latest = self.opening_decision_history(account_id)[0]
            if current.version != expected_decision_version:
                if (
                    latest.prior_version == expected_decision_version
                    and latest.request_basis_sha256 == basis
                    and latest.origin == "source"
                    and latest.state == "active"
                    and latest.reason == reason.strip()
                    and not current.stale
                ):
                    self.connection.execute("COMMIT")
                    return current
                raise ProfileFormatError("opening_decision_changed_since_selection")
            if (
                current.origin == "source"
                and current.state == "active"
                and (current.basis_sha256, current.amount_minor, current.cutoff_date)
                == (basis, candidate.printed_opening_minor, cutoff)
            ):
                raise ProfileFormatError("opening_correction_requires_changed_basis")
            result = self._append_opening_decision(
                account_id,
                current=current,
                origin="source",
                state="active",
                amount=candidate.printed_opening_minor,
                cutoff=cutoff,
                basis=basis,
                reference="",
                reason=reason.strip(),
                request_basis=basis,
            )
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def withdraw_reviewed_opening(
        self, account_id: str, *, expected_decision_version: str, reason: str
    ) -> OpeningDecision:
        if (
            type(expected_decision_version) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_decision_version) is None
        ):
            raise ProfileFormatError("opening_correction_version_required")
        self._anchor_write_start(reason)
        try:
            current = self.opening_decision(account_id)
            if current is None:
                raise ProfileFormatError("opening_correction_decision_missing")
            history = self.opening_decision_history(account_id)
            for old in history:
                if (
                    old.state == "withdrawn"
                    and old.prior_version == expected_decision_version
                    and old.reason == reason.strip()
                ):
                    receipt = OpeningDecision(
                        old.account_id,
                        old.basis_sha256,
                        None,
                        None,
                        None,
                        False,
                        old.revision_id,
                        old.version,
                        old.origin,
                        old.state,
                        old.tracking_scope,
                        old.reference,
                    )
                    self.connection.execute("COMMIT")
                    return receipt
            latest = history[0]
            if (
                current.state == "withdrawn"
                and latest.prior_version == expected_decision_version
                and latest.reason == reason.strip()
            ):
                self.connection.execute("COMMIT")
                return current
            if current.version != expected_decision_version:
                raise ProfileFormatError("opening_decision_changed_since_selection")
            if current.state == "withdrawn":
                raise ProfileFormatError("opening_already_withdrawn")
            result = self._append_opening_decision(
                account_id,
                current=current,
                origin=current.origin,
                state="withdrawn",
                amount=None,
                cutoff=None,
                basis=_transfer_record_digest("withdraw-opening-1", current.version),
                reference=current.reference,
                reason=reason.strip(),
                request_basis=current.version,
            )
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def post_reviewed_manual_opening(
        self,
        account_id: str,
        *,
        amount_minor: int,
        cutoff_date: date,
        tracking_scope: str,
        reference: str,
        reason: str,
        expected_decision_version: str | None,
        expected_basis_sha256: str,
    ) -> OpeningDecision:
        self._anchor_write_start(reason)
        try:
            if (
                type(expected_basis_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", expected_basis_sha256) is None
                or (
                    expected_decision_version is not None
                    and (
                        type(expected_decision_version) is not str
                        or re.fullmatch(r"[0-9a-f]{64}", expected_decision_version) is None
                    )
                )
            ):
                raise ProfileFormatError("account_anchor_version_required")
            account = self._anchor_account(account_id, tracking_scope)
            self._validate_anchor_value(amount_minor, cutoff_date, reference)
            current = self.opening_decision(account_id)
            basis = self._manual_opening_basis(
                account_id, amount_minor, cutoff_date.isoformat(), account.tracking_scope, reference.strip()
            )
            if current is not None and current.version != expected_decision_version:
                latest = self.opening_decision_history(account_id)[0]
                if (
                    latest.prior_version == expected_decision_version
                    and latest.request_basis_sha256 == expected_basis_sha256
                    and latest.origin == "manual"
                    and latest.state == "active"
                    and latest.basis_sha256 == basis
                    and latest.reason == reason.strip()
                ):
                    self.connection.execute("COMMIT")
                    return current
                raise ProfileFormatError("opening_decision_changed_since_selection")
            if current is None and expected_decision_version is not None:
                raise ProfileFormatError("opening_decision_changed_since_selection")
            if self._account_anchor_basis() != expected_basis_sha256:
                raise ProfileFormatError("account_anchor_changed_since_selection")
            if (
                current is not None
                and current.state == "active"
                and current.origin == "manual"
                and current.basis_sha256 == basis
            ):
                raise ProfileFormatError("opening_correction_requires_changed_basis")
            result = self._append_opening_decision(
                account_id,
                current=current,
                origin="manual",
                state="active",
                amount=amount_minor,
                cutoff=cutoff_date,
                basis=basis,
                reference=reference.strip(),
                reason=reason.strip(),
                request_basis=expected_basis_sha256,
            )
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def overlapping_statement_sources(self, source_sha256: str) -> tuple[str, ...]:
        """Find period overlaps only for explicitly linked ledger accounts."""
        payload = self.load_import(source_sha256).evidence.payload
        if not isinstance(payload, StatementPayload) or payload.start.iso is None:
            return ()
        account_ids = tuple(
            sorted(
                {
                    binding.ledger_account_id
                    for binding in self.source_account_bindings(source_sha256)
                    if binding.ledger_account_id is not None
                }
            )
        )
        if not account_ids:
            return ()
        placeholders = ",".join("?" for _ in account_ids)
        candidates = self.connection.execute(
            "SELECT DISTINCT source_sha256 FROM SourceAccountBindings "
            f"WHERE ledger_account_id IN ({placeholders}) AND source_sha256<>? ORDER BY source_sha256",
            (*account_ids, source_sha256),
        )
        overlaps = []
        for (candidate_id,) in candidates:
            other = self.load_import(candidate_id).evidence.payload
            if (
                isinstance(other, StatementPayload)
                and other.start.iso is not None
                and payload.start.iso <= other.end.iso
                and other.start.iso <= payload.end.iso
            ):
                overlaps.append(candidate_id)
        return tuple(overlaps)

    def import_source(
        self, source: bytes, definition: bytes, evidence: SourceEvidence, *, suffix: Literal[".csv", ".pdf"]
    ) -> bool:
        """Atomically save one admitted snapshot. False means exact-source retry."""
        self._require_writable()
        if (
            type(source) is not bytes
            or not 0 < len(source) <= MAX_SOURCE_BYTES
            or type(definition) is not bytes
            or not 0 < len(definition) <= MAX_DEFINITION_BYTES
            or suffix not in {".csv", ".pdf"}
        ):
            raise ProfileFormatError("source_or_definition_size")
        try:
            saved = evidence.model_dump_json().encode("utf-8")
            if not 0 < len(saved) <= MAX_EVIDENCE_BYTES:
                raise ProfileFormatError("evidence_size")
            evidence = SourceEvidence.model_validate_json(saved)
        except (AttributeError, ValidationError, ValueError):
            raise ProfileFormatError("invalid_evidence") from None
        source_hash, definition_hash = _digest(source), _digest(definition)
        if evidence.source_sha256 != source_hash or evidence.definition_sha256 != definition_hash:
            raise ProfileFormatError("evidence_hash_mismatch")
        c = self.connection
        c.execute("BEGIN IMMEDIATE")
        try:
            if c.execute("SELECT 1 FROM Sources WHERE sha256=?", (source_hash,)).fetchone():
                c.execute("COMMIT")
                return False
            c.execute(
                "INSERT OR IGNORE INTO Definitions VALUES (?,?,?)", (definition_hash, len(definition), definition)
            )
            c.execute("INSERT INTO Sources VALUES (?,?,?,?)", (source_hash, suffix, len(source), source))
            c.execute(
                "INSERT INTO EvidenceSnapshots VALUES (?,?,?,?,?)",
                (source_hash, definition_hash, len(saved), _digest(saved), saved),
            )
            c.executemany(
                "INSERT INTO SourceObservations VALUES (?,?,?,?,?,?,?,?)",
                (
                    (
                        row.row_id,
                        source_hash,
                        row.source_account,
                        row.source_account_form,
                        row.row_role,
                        row.date_role,
                        row.date.iso,
                        row.amount.minor,
                    )
                    for row in _rows(evidence)
                ),
            )
            c.execute("COMMIT")
            return True
        except BaseException:
            c.execute("ROLLBACK")
            raise

    def load_import(self, source_sha256: str) -> SavedImport:
        row = self.connection.execute(
            "SELECT s.content,s.size,s.suffix,d.content,d.size,e.content,e.size,e.sha256 "
            "FROM Sources s JOIN EvidenceSnapshots e ON e.source_sha256=s.sha256 "
            "JOIN Definitions d ON d.sha256=e.definition_sha256 WHERE s.sha256=?",
            (source_sha256,),
        ).fetchone()
        if row is None:
            raise ProfileFormatError("source_missing")
        source, source_size, suffix, definition, definition_size, content, evidence_size, evidence_hash = row
        if (
            len(source) != source_size
            or len(definition) != definition_size
            or len(content) != evidence_size
            or len(source) > MAX_SOURCE_BYTES
            or len(definition) > MAX_DEFINITION_BYTES
            or len(content) > MAX_EVIDENCE_BYTES
            or _digest(source) != source_sha256
            or _digest(content) != evidence_hash
        ):
            raise ProfileFormatError("saved_snapshot_integrity")
        try:
            evidence = SourceEvidence.model_validate_json(content)
        except ValidationError:
            raise ProfileFormatError("invalid_saved_evidence") from None
        if evidence.source_sha256 != source_sha256 or evidence.definition_sha256 != _digest(definition):
            raise ProfileFormatError("saved_evidence_mismatch")
        expected = {
            (
                item.row_id,
                item.source_account,
                item.source_account_form,
                item.row_role,
                item.date_role,
                item.date.iso,
                item.amount.minor,
            )
            for item in _rows(evidence)
        }
        actual = set(
            self.connection.execute(
                "SELECT row_id,source_account,source_account_form,row_role,date_role,observed_date,amount_minor "
                "FROM SourceObservations WHERE source_sha256=?",
                (source_sha256,),
            )
        )
        if expected != actual:
            raise ProfileFormatError("observation_inventory_mismatch")
        return SavedImport(source, definition, evidence, suffix)

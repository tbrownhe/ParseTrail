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
from dataclasses import dataclass
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
    MoneyValue,
    SourceEvidence,
    StatementAccount,
    StatementPayload,
)
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_review_dates import permitted_posting_date, posting_date_candidate

APPLICATION_ID = 0x50543230  # PT20
SCHEMA_VERSION = 10
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_DEFINITION_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
TABLE_COLUMNS = {
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
    ),
    "OpeningDecisions": (
        ("account_id", "TEXT", 0, 1),
        ("basis_sha256", "TEXT", 1, 0),
        ("amount_minor", "INTEGER", 1, 0),
        ("cutoff_date", "TEXT", 1, 0),
        ("entry_key", "TEXT", 0, 0),
        ("created_at", "TEXT", 1, 0),
    ),
}
FOREIGN_KEYS = {
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
    "StatementSourceReviews": (("source_sha256", "Sources", "sha256"), ("account_id", "Accounts", "id")),
    "OpeningDecisions": (("entry_key", "JournalEntries", "key"), ("account_id", "Accounts", "id")),
}

IMMUTABLE_TABLES = (
    "Sources",
    "Definitions",
    "EvidenceSnapshots",
    "SourceObservations",
    "JournalEntries",
    "JournalAllocations",
    "JournalCorrections",
    "StatementSourceReviews",
    "OpeningDecisions",
)


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


@dataclass(frozen=True)
class OpeningDecision:
    account_id: str
    basis_sha256: str
    amount_minor: int
    cutoff_date: date
    entry_key: str | None
    stale: bool


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


@dataclass(frozen=True)
class TransferMovement:
    row_id: str
    source_sha256: str
    account_id: str
    account_name: str
    account_kind: Literal["asset", "liability"]
    posting_date: str
    date_provenance: str
    date_allowed: bool
    amount_minor: int
    description: str


@dataclass(frozen=True)
class TransferCandidate:
    outgoing: TransferMovement
    incoming: TransferMovement
    kind: Literal["asset transfer", "card payment"]
    day_gap: int
    posting_allowed: bool


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
    if isinstance(evidence.payload, StatementPayload) and evidence.parser_id in BANK_CASH_STATEMENT_PARSERS:
        return {
            row.row_id: account.balance_scope == "account_total"
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
        data = json.loads(payload)
        return JournalEntry(
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
    except (KeyError, TypeError, ValueError):
        raise ProfileFormatError("journal_entry_invalid") from None


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
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE OpeningDecisions (
                    account_id TEXT PRIMARY KEY REFERENCES Accounts(id),
                    basis_sha256 TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    cutoff_date TEXT NOT NULL,
                    entry_key TEXT REFERENCES JournalEntries(key),
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
                    for (payload,) in verified.connection.execute("SELECT payload FROM JournalEntries"):
                        _decode_journal(payload)
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
        name, institution_key, full_number = self._financial_account_values(account)
        self.connection.execute(
            "INSERT INTO Accounts VALUES (?,?,?,'USD','financial','normal',?,?)",
            (account.id, name, account.kind, institution_key, full_number),
        )

    @staticmethod
    def _financial_account_values(account: FinancialAccount) -> tuple[str, str, str | None]:
        if (
            not isinstance(account, FinancialAccount)
            or type(account.id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,79}", account.id) is None
            or type(account.name) is not str
            or not 0 < len(account.name.strip()) <= 200
            or account.kind not in {"asset", "liability"}
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
        current = self.connection.execute(
            "SELECT kind FROM Accounts WHERE id=? AND role='financial'", (account.id,)
        ).fetchone()
        if current is None:
            raise ProfileFormatError("financial_account_missing")
        if current[0] != account.kind:
            raise ProfileFormatError("financial_account_kind_immutable")
        self.connection.execute(
            "UPDATE Accounts SET name=?,institution_key=?,full_account_number=? WHERE id=? AND role='financial'",
            (name, institution_key, full_number, account.id),
        )

    def financial_accounts(self) -> tuple[FinancialAccount, ...]:
        return tuple(
            FinancialAccount(*row)
            for row in self.connection.execute(
                "SELECT id,name,kind,institution_key,full_account_number FROM Accounts "
                "WHERE role='financial' ORDER BY name,id"
            )
        )

    def _require_financial_account(self, account_id: str) -> None:
        if (
            self.connection.execute("SELECT 1 FROM Accounts WHERE id=? AND role='financial'", (account_id,)).fetchone()
            is None
        ):
            raise ProfileFormatError("financial_account_missing")

    def add_category_account(self, account_id: str, name: str, kind: Literal["expense", "income"]) -> None:
        """Create a fresh authored ledger category without source interpretation."""
        self._require_writable()
        if (
            type(account_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,79}", account_id) is None
            or type(name) is not str
            or not 0 < len(name.strip()) <= 200
            or kind not in {"expense", "income"}
        ):
            raise ProfileFormatError("invalid_category_account")
        self.connection.execute(
            "INSERT INTO Accounts VALUES (?,?,?,'USD','category','normal',NULL,NULL)",
            (account_id, name, kind),
        )

    def category_accounts(self) -> tuple[CategoryAccount, ...]:
        return tuple(
            CategoryAccount(*row)
            for row in self.connection.execute(
                "SELECT id,name,kind FROM Accounts WHERE role='category' ORDER BY name,id"
            )
        )

    def rename_category_account(self, account_id: str, name: str) -> None:
        """Change only a category's display name; journal references use its ID."""
        self._require_writable()
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

    def _cash_category_source(self, row_id: str, kind: Literal["expense", "income"]):
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
            or (row.amount.minor < 0) != (kind == "expense")
            or not row.description.text
            or financial_id is None
        ):
            raise ProfileFormatError("cash_category_requires_bound_posted_movement")
        if source_row[1:] != (row.row_role, row.date_role, row.date.iso, row.amount.minor):
            raise ProfileFormatError("source_observation_index_mismatch")
        financial = self.connection.execute("SELECT kind,role FROM Accounts WHERE id=?", (financial_id,)).fetchone()
        if financial != ("asset", "financial"):
            raise ProfileFormatError("cash_category_requires_asset_account")
        return row, financial_id, self._ledger_accounts()

    def _ledger_accounts(self) -> dict[str, LedgerAccount]:
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
            or row.amount.minor >= 0
            or row.amount.provenance != "observed"
            or not row.description.text
            or financial_id is None
        ):
            raise ProfileFormatError("card_purchase_requires_bound_negative_movement")
        if source_row[1:] != (row.row_role, row.date_role, row.date.iso, row.amount.minor):
            raise ProfileFormatError("source_observation_index_mismatch")
        financial = self.connection.execute("SELECT kind,role FROM Accounts WHERE id=?", (financial_id,)).fetchone()
        if financial != ("liability", "financial"):
            raise ProfileFormatError("card_purchase_requires_liability_account")
        candidate = posting_date_candidate(row)
        if candidate is None:
            raise ProfileFormatError("card_purchase_posting_date_unavailable")
        return row, financial_id, self._ledger_accounts(), candidate

    def _active_consumed(self, *, excluding: str | None = None) -> dict[str, int]:
        query = (
            "SELECT row_id,SUM(amount_minor) FROM JournalAllocations "
            "WHERE entry_key NOT IN (SELECT original_key FROM JournalCorrections)"
        )
        parameters: tuple[str, ...] = ()
        if excluding is not None:
            query += " AND entry_key<>?"
            parameters = (excluding,)
        return dict(self.connection.execute(query + " GROUP BY row_id", parameters))

    def _require_unposted_rows(self, row_ids: tuple[str, ...]) -> None:
        for offset in range(0, len(row_ids), 500):
            batch = row_ids[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            if self.connection.execute(
                f"SELECT 1 FROM JournalAllocations WHERE row_id IN ({placeholders}) LIMIT 1", batch
            ).fetchone():
                raise ProfileFormatError("account_binding_has_journal_history")

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

    def cash_activity_review_rows(self, source_sha256: str) -> tuple[CashActivityReviewRow, ...]:
        """Describe source rows for explicit asset cash expense or income review."""
        saved = self.load_import(source_sha256)
        scopes = _cash_review_scopes(saved.evidence)
        bindings = {binding.row_id: binding.ledger_account_id for binding in self.account_bindings(source_sha256)}
        accounts = {
            account_id: (name, kind, role)
            for account_id, name, kind, role in self.connection.execute("SELECT id,name,kind,role FROM Accounts")
        }
        active = self._active_reviewed_entries(source_sha256)
        result = []
        for row in _rows(saved.evidence):
            account_id = bindings.get(row.row_id)
            financial = accounts.get(account_id) if account_id is not None else None
            account_name = financial[0] if financial is not None else None
            entries = active.get(row.row_id, [])
            entry_key = None
            category_id = None
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
                        == ("expense" if row.amount.minor < 0 else "income", "category")
                    ):
                        entry_key = entry.key
                        category_id = entry.postings[1].account_id
                        status = "Posted: " + accounts[category_id][0]
            elif not scopes.get(row.row_id, False):
                status = "Outside supported asset cash statement scope"
            elif row.row_role != "activity" or row.amount.minor is None or row.amount.minor == 0:
                status = "Outside cash activity scope"
            elif row.date_role != "posting_date" or row.date.iso is None:
                status = "Posting date needs review"
            elif account_id is None:
                status = "Assign a financial account first"
            elif financial is None or financial[1:] != ("asset", "financial"):
                status = "Requires a bound asset account"
            elif not row.description.text:
                status = "Description needs review"
            else:
                status = "Ready for expense review" if row.amount.minor < 0 else "Ready for income review"
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
                )
            )
        return tuple(result)

    def _active_reviewed_entries(self, source_sha256: str) -> dict[str, list[JournalEntry]]:
        active: dict[str, list[JournalEntry]] = {}
        for row_id, payload in self.connection.execute(
            "SELECT a.row_id,e.payload FROM JournalAllocations a JOIN JournalEntries e ON e.key=a.entry_key "
            "JOIN SourceObservations o ON o.row_id=a.row_id "
            "WHERE o.source_sha256=? AND a.entry_key NOT IN (SELECT original_key FROM JournalCorrections)",
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
        active = self._active_reviewed_entries(source_sha256)
        result = []
        for row in _rows(saved.evidence):
            account_id = bindings.get(row.row_id)
            financial = accounts.get(account_id) if account_id is not None else None
            candidate = posting_date_candidate(row)
            entries = active.get(row.row_id, ())
            entry_key = None
            category_id = None
            effective_date = None
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
                        == ("expense", "category")
                    ):
                        entry_key = entry.key
                        category_id = entry.postings[1].account_id
                        effective_date = entry.posting_date.isoformat()
                        status = "Posted: " + accounts[category_id][0]
            elif not scopes.get(row.row_id, False):
                status = "Outside supported card statement scope"
            elif row.row_role != "activity":
                status = "Header or summary charge needs separate review"
            elif row.amount.minor is None or row.amount.minor == 0:
                status = "Amount unavailable or zero"
            elif row.amount.minor > 0:
                status = "Payment, refund or other positive movement pending"
            elif row.amount.provenance != "observed":
                status = "Source amount not observed"
            elif candidate is None:
                status = "Posting date unavailable"
            elif account_id is None:
                status = "Assign a financial account first"
            elif financial is None or financial[1:] != ("liability", "financial"):
                status = "Requires a bound card liability account"
            elif not row.description.text:
                status = "Description needs review"
            elif permitted_posting_date(row, preferences) is None:
                status = "Enable assumed dates or enter a corrected date"
            else:
                status = "Ready for expense review"
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
                )
            )
        return tuple(result)

    def _transfer_movements(self, preferences: V2Preferences) -> tuple[TransferMovement, ...]:
        if type(preferences) is not V2Preferences or type(preferences.allow_assumed_posting_dates) is not bool:
            raise ProfileFormatError("transfer_preferences_invalid")
        accounts = {account.id: account for account in self.financial_accounts()}
        consumed = self._active_consumed()
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
                    or type(amount) is not int
                    or amount == 0
                    or row.amount.provenance != "observed"
                    or consumed.get(row.row_id, 0)
                ):
                    continue
                if account.kind == "asset" and cash_scope.get(row.row_id, False):
                    if row.date_role != "posting_date" or row.date.iso is None:
                        continue
                    candidate = row.date
                elif account.kind == "liability" and amount > 0 and card_scope.get(row.row_id, False):
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
                    )
                )
        return tuple(movements)

    def transfer_candidates(self, *, preferences: V2Preferences, max_day_gap: int = 7) -> tuple[TransferCandidate, ...]:
        """Suggest equal, opposite owned-account movements; never infer a link."""
        if type(max_day_gap) is not int or not 0 <= max_day_gap <= 31:
            raise ProfileFormatError("transfer_window_invalid")
        movements = self._transfer_movements(preferences)
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
                    candidates.append(
                        TransferCandidate(
                            outgoing,
                            incoming,
                            "card payment" if incoming.account_kind == "liability" else "asset transfer",
                            gap,
                            outgoing.date_allowed and incoming.date_allowed,
                        )
                    )
        return tuple(
            sorted(
                candidates, key=lambda pair: (pair.outgoing.posting_date, pair.outgoing.row_id, pair.incoming.row_id)
            )
        )

    def post_reviewed_transfer(
        self, outgoing_row_id: str, incoming_row_id: str, *, preferences: V2Preferences, reason: str
    ) -> str:
        """Confirm one whole-movement pair atomically, with source-dated clearing if needed."""
        self._require_writable()
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("transfer_reason_required")
        if type(preferences) is not V2Preferences or type(preferences.allow_assumed_posting_dates) is not bool:
            raise ProfileFormatError("transfer_preferences_invalid")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            event_id = "review:transfer:" + _digest((outgoing_row_id + ":" + incoming_row_id).encode())
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
                self.connection.execute("COMMIT")
                return event_id
            pair = next(
                (
                    candidate
                    for candidate in self.transfer_candidates(preferences=preferences, max_day_gap=31)
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
                self.connection.execute(
                    "INSERT OR IGNORE INTO Accounts VALUES (?,?,?,'USD','internal','clearing',NULL,NULL)",
                    (clearing_id, "Transfer clearing", "asset"),
                )
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
            self.connection.execute("COMMIT")
            return event_id
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("transfer_posting_refused") from None
            raise

    def _journal_entries_in_period(self, start: date, end: date):
        if type(start) is not date or type(end) is not date or start >= end:
            raise ProfileFormatError("report_period_invalid")
        for (payload,) in self.connection.execute("SELECT payload FROM JournalEntries"):
            entry = _decode_journal(payload)
            if start <= entry.posting_date < end:
                yield entry

    def _unallocated_activity_counts(self) -> tuple[int, int]:
        return self.connection.execute(
            "SELECT COUNT(*),COUNT(DISTINCT o.source_sha256) FROM SourceObservations o "
            "LEFT JOIN ("
            "SELECT a.row_id,SUM(a.amount_minor) AS used FROM JournalAllocations a "
            "WHERE a.entry_key NOT IN (SELECT original_key FROM JournalCorrections) GROUP BY a.row_id"
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
        for entry in self._journal_entries_in_period(start, end):
            financial_postings = tuple(posting for posting in entry.postings if posting.account_id in accounts)
            if not entry.reviewed:
                excluded_unreviewed += bool(financial_postings)
                continue
            target = opening if entry.origin == "opening" else nonopening
            for posting in financial_postings:
                target[posting.account_id] += posting.amount_minor
                if entry.origin == "opening":
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

    def reviewed_journal_export(self, *, start: date, end: date) -> ReviewedJournalExport:
        """Read active reviewed entries with posting and source provenance for export."""
        period_entries = tuple(self._journal_entries_in_period(start, end))
        corrections = tuple(
            JournalExportCorrection(original_key, reversal_key, replacement_key, reason, created_at)
            for original_key, reversal_key, replacement_key, reason, created_at, payload in self.connection.execute(
                "SELECT c.original_key,c.reversal_key,c.replacement_key,c.reason,c.created_at,e.payload "
                "FROM JournalCorrections c JOIN JournalEntries e ON e.key=c.original_key "
                "ORDER BY c.created_at,c.original_key"
            )
            if start <= _decode_journal(payload).posting_date < end
        )
        inactive = {row[0] for row in self.connection.execute("SELECT original_key FROM JournalCorrections")}
        inactive.update(row[0] for row in self.connection.execute("SELECT reversal_key FROM JournalCorrections"))
        entries = tuple(
            sorted(
                (
                    entry
                    for entry in period_entries
                    if entry.reviewed and entry.origin != "opening" and entry.key not in inactive
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
            sum(entry.reviewed and entry.origin == "opening" for entry in period_entries),
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
    ) -> str:
        payload = _journal_payload(entry)
        prior = self.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (entry.key,)).fetchone()
        if prior is not None:
            if self.connection.execute(
                "SELECT 1 FROM JournalCorrections WHERE original_key=?", (entry.key,)
            ).fetchone():
                raise ProfileFormatError(f"{refusal_prefix}_already_corrected")
            if prior[0] != payload:
                raise ProfileFormatError(f"{refusal_prefix}_conflicts_with_prior_entry")
            return entry.key
        validate_entry(
            entry,
            accounts,
            {row_id: Observation(row_id, financial_id, amount, entry.posting_date)},
            self._active_consumed(),
        )
        self.connection.execute("INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (entry.key, payload))
        self.connection.execute("INSERT INTO JournalAllocations VALUES (?,?,?)", (entry.key, row_id, amount))
        return entry.key

    def post_reviewed_cash_category(self, row_id: str, category_id: str, *, reason: str) -> str:
        """Post one explicitly classified asset cash movement with source evidence."""
        self._require_writable()
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("cash_review_reason_required")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            category = self.connection.execute("SELECT kind,role FROM Accounts WHERE id=?", (category_id,)).fetchone()
            if category not in {("expense", "category"), ("income", "category")}:
                raise ProfileFormatError("cash_category_invalid")
            kind = category[0]
            row, financial_id, accounts = self._cash_category_source(row_id, kind)
            amount = row.amount.minor
            entry = JournalEntry(
                key=f"review:cash:{kind}:{row_id}",
                event_id=f"source:{row_id}",
                posting_date=date.fromisoformat(row.date.iso),
                description=row.description.text,
                postings=(
                    Posting(financial_id, amount, (Allocation(row_id, amount),)),
                    Posting(category_id, -amount),
                ),
                reviewed=True,
                reason=reason.strip(),
            )
            key = self._insert_reviewed_category(
                entry, row_id, financial_id, amount, accounts, refusal_prefix="cash_review"
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
    ) -> str:
        """Post one classified negative card movement; a date override is explicit."""
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
            category = self.connection.execute("SELECT kind,role FROM Accounts WHERE id=?", (category_id,)).fetchone()
            if category != ("expense", "category"):
                raise ProfileFormatError("card_purchase_requires_expense_category")
            row, financial_id, accounts, candidate = self._card_purchase_source(row_id)
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
                key=f"review:card:expense:{row_id}",
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
                entry, row_id, financial_id, amount, accounts, refusal_prefix="card_purchase"
            )
            self.connection.execute("COMMIT")
            return key
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("card_purchase_refused") from None
            raise

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

    def correct_reviewed_cash_category(self, original_key: str, category_id: str, *, reason: str) -> str:
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
                if prior == (replacement_key, reason):
                    self.connection.execute("COMMIT")
                    return replacement_key
                raise ProfileFormatError("cash_correction_conflicts_with_prior_decision")
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
            new_category = self.connection.execute(
                "SELECT kind,role FROM Accounts WHERE id=?", (category_id,)
            ).fetchone()
            kind = "expense" if amount < 0 else "income"
            row, financial_id, accounts = self._cash_category_source(row_id, kind)
            if (
                original.postings[0].account_id != financial_id
                or original.event_id != f"source:{row_id}"
                or original.posting_date.isoformat() != row.date.iso
                or original.description != row.description.text
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
        self, original_key: str, category_id: str, *, reason: str, accounting_date: date | None = None
    ) -> str:
        """Reverse and replace one card expense when its category or accounting date changes."""
        self._require_writable()
        if (
            type(original_key) is not str
            or not original_key.startswith(("review:card:expense:", "review:card:correction:"))
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
                if prior == (replacement_key, reason):
                    self.connection.execute("COMMIT")
                    return replacement_key
                raise ProfileFormatError("card_correction_conflicts_with_prior_decision")
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
                or original.postings[0].amount_minor >= 0
                or original.postings[0].allocations != (Allocation(*allocations[0]),)
                or original.postings[1].amount_minor != -allocations[0][1]
            ):
                raise ProfileFormatError("card_correction_original_invalid")
            row_id, amount = allocations[0]
            row, financial_id, accounts, _candidate = self._card_purchase_source(row_id)
            old_category_id = original.postings[1].account_id
            old_category = self.connection.execute(
                "SELECT kind,role FROM Accounts WHERE id=?", (old_category_id,)
            ).fetchone()
            new_category = self.connection.execute(
                "SELECT kind,role FROM Accounts WHERE id=?", (category_id,)
            ).fetchone()
            if (
                original.postings[0].account_id != financial_id
                or original.event_id != f"source:{row_id}"
                or original.description != row.description.text
                or old_category != ("expense", "category")
                or new_category != ("expense", "category")
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

    def source_account_bindings(self, source_sha256: str) -> tuple[SourceAccountBinding, ...]:
        """Show each identity printed by a source and its explicit ledger decision."""
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
                row_ids = tuple(
                    row[0]
                    for row in self.connection.execute(
                        "SELECT row_id FROM SourceObservations WHERE source_sha256=? "
                        "AND source_account=? AND source_account_form=?",
                        (source_sha256, source_identity, source_identity_form),
                    )
                )
                self._require_unposted_rows(row_ids)
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
            row_ids = tuple(
                row[0]
                for row in self.connection.execute(
                    "SELECT row_id FROM SourceObservations WHERE source_sha256=? "
                    "AND source_account=? AND source_account_form=?",
                    (source_sha256, source_identity, source_identity_form),
                )
            )
            self._require_unposted_rows(row_ids)
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
                self._require_unposted_rows(tuple(row.row_id for row in payload.rows))
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
                self._require_unposted_rows(
                    tuple(
                        row[0]
                        for row in self.connection.execute(
                            "SELECT row_id FROM SourceObservations WHERE source_sha256=?", (source_sha256,)
                        )
                    )
                )
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
            self._require_unposted_rows(tuple(row_id for row_id in row_ids if prior.get(row_id) != account_id))
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
            self._require_unposted_rows(assigned)
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
                            or account.balance_scope != "account_total"
                            or previous_account.balance_scope != "account_total"
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
        reversal_keys = {key for (key,) in self.connection.execute("SELECT reversal_key FROM JournalCorrections")}
        inactive_keys = {key for (key,) in self.connection.execute("SELECT original_key FROM JournalCorrections")}
        active_dates: dict[str, list[date]] = {}
        for entry in journal:
            if entry.key in inactive_keys or entry.key in reversal_keys:
                continue
            for posting in entry.postings:
                for allocation in posting.allocations:
                    active_dates.setdefault(allocation.observation_id, []).append(entry.posting_date)
        account_kinds = {account.id: account.kind for account in self.financial_accounts()}
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
                and account.balance_scope == "account_total"
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
                            if entry.key not in reversal_keys and (
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
            elif account.balance_scope != "account_total":
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

    def _statement_reconciliation_checks(self) -> tuple[StatementReconciliationCheck, ...]:
        rule = "v2-statement-reconciliation-2"
        version_tables = (
            ("Sources", "sha256"),
            ("EvidenceSnapshots", "source_sha256,definition_sha256,sha256"),
            ("SourceObservations", "*"),
            ("Accounts", "*"),
            ("SourceAccountBindings", "*"),
            ("JournalEntries", "*"),
            ("JournalAllocations", "*"),
            ("JournalCorrections", "*"),
            ("StatementSourceReviews", "*"),
            ("OpeningDecisions", "*"),
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
        version = digest.hexdigest()
        coverage = self.statement_coverage()
        comparisons = {(row.account_id, row.source_sha256): row for row in self.statement_journal_comparisons()}
        entries = tuple(
            _decode_journal(payload) for (payload,) in self.connection.execute("SELECT payload FROM JournalEntries")
        )
        inactive = {key for (key,) in self.connection.execute("SELECT original_key FROM JournalCorrections")}
        inactive.update(key for (key,) in self.connection.execute("SELECT reversal_key FROM JournalCorrections"))
        reviews = {
            account.id: {review.source_sha256: review for review in self.statement_source_reviews(account.id)}
            for account in self.financial_accounts()
        }
        decisions = {account_id: self.opening_decision(account_id) for account_id in reviews}
        kinds = {account.id: account.kind for account in self.financial_accounts()}
        result = []
        for section in coverage:
            comparison = comparisons[(section.account_id, section.source_sha256)]
            _payload, source_section = self._bound_statement_section(section.account_id, section.source_sha256)
            source_row_ids = {row.row_id for row in source_section.rows if row.row_role == "activity"}
            review = reviews[section.account_id].get(section.source_sha256)
            opening_decision = decisions[section.account_id]
            printed_opening = (
                section.opening.minor
                if section.balance_scope == "account_total"
                and section.opening is not None
                and section.opening.provenance == "observed"
                else None
            )
            printed_closing = (
                section.closing.minor
                if section.balance_scope == "account_total"
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
            if section.balance_scope != "account_total":
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
            if opening_decision is None or opening_decision.stale:
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
                )
            )
        return tuple(result)

    def statement_source_reviews(self, account_id: str) -> tuple[StatementSourceReview, ...]:
        """Return the latest append-only assertion for each source on an account."""
        self._require_financial_account(account_id)
        return tuple(
            StatementSourceReview(revision, account, source, opening, closing, bool(timing), dates, reference, note)
            for revision, account, source, opening, closing, timing, dates, reference, note in self.connection.execute(
                "SELECT r.revision_id,r.account_id,r.source_sha256,r.opening_origin,r.closing_origin,"
                "r.timing_confirmed,r.posting_dates,r.source_reference,r.note FROM StatementSourceReviews r "
                "WHERE r.account_id=? AND r.revision_id=(SELECT MAX(later.revision_id) "
                "FROM StatementSourceReviews later WHERE later.account_id=r.account_id "
                "AND later.source_sha256=r.source_sha256) ORDER BY r.source_sha256",
                (account_id,),
            )
        )

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
        ):
            raise ProfileFormatError("statement_source_review_invalid")
        payload, section = self._bound_statement_section(account_id, source_sha256)
        if opening_origin == "reported" and (
            section.balance_scope != "account_total"
            or section.opening is None
            or section.opening.provenance != "observed"
            or section.opening.minor is None
        ):
            raise ProfileFormatError("opening_reported_balance_unavailable")
        if closing_origin == "reported" and (
            section.balance_scope != "account_total"
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
                "(account_id,source_sha256,opening_origin,closing_origin,timing_confirmed,posting_dates,source_reference,note) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    account_id,
                    source_sha256,
                    opening_origin,
                    closing_origin,
                    int(timing_confirmed),
                    posting_dates,
                    source_reference.strip(),
                    note.strip(),
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
            expected_revision_id=latest.revision_id if latest else None,
            opening_origin=opening_origin,
            closing_origin=latest.closing_origin if latest else "unestablished",
            timing_confirmed=timing_confirmed,
            posting_dates=latest.posting_dates if latest else "unverified",
            source_reference=source_reference,
            note=note,
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
        saved = self.connection.execute(
            "SELECT basis_sha256,amount_minor,cutoff_date,entry_key FROM OpeningDecisions WHERE account_id=?",
            (account_id,),
        ).fetchone()
        if saved is None:
            return None
        candidate = next(item for item in self.earliest_source_openings() if item.account_id == account_id)
        reviews = self.statement_source_reviews(account_id)
        stale = bool(candidate.blockers) or saved[0] != self._opening_basis(candidate, reviews)
        return OpeningDecision(account_id, saved[0], saved[1], date.fromisoformat(saved[2]), saved[3], stale)

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
            if any(account.balance_scope != "account_total" for _source_id, account in tied):
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

    def post_reviewed_opening(self, account_id: str, *, expected_basis_sha256: str | None = None) -> OpeningDecision:
        """Post a printed opening through equity after every earliest source is reviewed."""
        self._require_writable()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            candidate = next((item for item in self.earliest_source_openings() if item.account_id == account_id), None)
            if candidate is None or candidate.blockers or candidate.earliest_period_start is None:
                raise ProfileFormatError("opening_review_blocked")
            if candidate.earliest_period_start == date.min:
                raise ProfileFormatError("opening_cutoff_unavailable")
            amount = candidate.printed_opening_minor
            if amount is None:
                raise ProfileFormatError("opening_review_blocked")
            reviews = self.statement_source_reviews(account_id)
            basis = self._opening_basis(candidate, reviews)
            if expected_basis_sha256 is not None and basis != expected_basis_sha256:
                raise ProfileFormatError("opening_review_changed_since_selection")
            prior = self.connection.execute(
                "SELECT basis_sha256,amount_minor,cutoff_date,entry_key FROM OpeningDecisions WHERE account_id=?",
                (account_id,),
            ).fetchone()
            cutoff = date.fromordinal(candidate.earliest_period_start.toordinal() - 1)
            if prior is not None:
                if prior[:3] == (basis, amount, cutoff.isoformat()):
                    self.connection.execute("COMMIT")
                    return OpeningDecision(account_id, basis, amount, cutoff, prior[3], False)
                raise ProfileFormatError("opening_already_decided")
            for (payload,) in self.connection.execute("SELECT payload FROM JournalEntries"):
                entry = _decode_journal(payload)
                if entry.posting_date <= cutoff and any(posting.account_id == account_id for posting in entry.postings):
                    raise ProfileFormatError("opening_earlier_posting_conflict")
            key = None
            if amount != 0:
                equity_id = "internal:opening-equity:USD"
                self.connection.execute(
                    "INSERT OR IGNORE INTO Accounts VALUES (?,?,?,'USD','internal','opening_equity',NULL,NULL)",
                    (equity_id, "Opening equity", "equity"),
                )
                key = f"review:opening:{account_id}"
                entry = JournalEntry(
                    key=key,
                    event_id=key,
                    posting_date=cutoff,
                    description="Reviewed printed opening position",
                    postings=(Posting(account_id, amount), Posting(equity_id, -amount)),
                    origin="opening",
                    reviewed=True,
                    reason="Confirmed printed balance and inclusive source timing",
                )
                validate_entry(entry, self._ledger_accounts(), {}, self._active_consumed())
                self.connection.execute(
                    "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (key, _journal_payload(entry))
                )
            self.connection.execute(
                "INSERT INTO OpeningDecisions(account_id,basis_sha256,amount_minor,cutoff_date,entry_key) "
                "VALUES (?,?,?,?,?)",
                (account_id, basis, amount, cutoff.isoformat(), key),
            )
            self.connection.execute("COMMIT")
            return OpeningDecision(account_id, basis, amount, cutoff, key, False)
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("opening_posting_refused") from None
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

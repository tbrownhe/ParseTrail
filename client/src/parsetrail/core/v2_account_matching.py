"""Truthful source-account suggestions before a 2.0 ledger binding is saved."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from parsetrail.core.source_evidence import SourceEvidence, StatementPayload
from parsetrail.core.v2_data_catalog import VerifiedCatalog

AccountForm = Literal["full", "last_four", "opaque"]
FinancialKind = Literal["asset", "liability"]


class MatchPreferences(Protocol):
    allow_abbreviated_account_matching: bool


@dataclass(frozen=True)
class LedgerAccountCandidate:
    ledger_account_id: str
    institution_key: str
    kind: FinancialKind
    full_account_number: str | None


@dataclass(frozen=True)
class AccountMatch:
    status: Literal["automatic", "review", "ambiguous", "no_candidate"]
    ledger_account_id: str | None
    suggestions: tuple[str, ...]
    offer_enable_abbreviated_matching: bool


def match_source_account(
    source_identity: str,
    source_form: AccountForm,
    *,
    institution_key: str,
    kind: FinancialKind,
    candidates: tuple[LedgerAccountCandidate, ...],
    preferences: MatchPreferences,
) -> AccountMatch:
    """Auto-select only one eligible account; otherwise leave a review decision."""
    if (
        not source_identity
        or not institution_key
        or source_form not in {"full", "last_four", "opaque"}
        or kind not in {"asset", "liability"}
    ):
        raise ValueError("invalid_source_account_identity")
    if source_form == "opaque":
        return AccountMatch("review", None, (), False)
    if source_form == "last_four" and (len(source_identity) != 4 or not source_identity.isdigit()):
        raise ValueError("invalid_abbreviated_account_identity")
    eligible = tuple(
        candidate
        for candidate in candidates
        if candidate.institution_key == institution_key
        and candidate.kind == kind
        and candidate.full_account_number is not None
        and (
            candidate.full_account_number == source_identity
            if source_form == "full"
            else candidate.full_account_number.isdigit()
            and len(candidate.full_account_number) > 4
            and candidate.full_account_number.endswith(source_identity)
        )
    )
    ids = tuple(dict.fromkeys(candidate.ledger_account_id for candidate in eligible))
    if not ids:
        return AccountMatch("no_candidate", None, (), False)
    if len(ids) > 1:
        return AccountMatch("ambiguous", None, ids, False)
    if source_form == "last_four" and not preferences.allow_abbreviated_account_matching:
        return AccountMatch("review", None, ids, True)
    return AccountMatch("automatic", ids[0], ids, False)


def match_verified_source_account(
    evidence: SourceEvidence,
    source_identity: str,
    source_form: AccountForm,
    *,
    catalog: VerifiedCatalog | None,
    candidates: tuple[LedgerAccountCandidate, ...],
    preferences: MatchPreferences,
) -> AccountMatch:
    """Use context only from the exact signed declaration that made the evidence."""
    payload = evidence.payload
    printed = (
        {(account.source_identity, account.source_identity_form) for account in payload.accounts}
        if isinstance(payload, StatementPayload)
        else {(row.source_account, row.source_account_form) for row in payload.rows if row.source_account is not None}
    )
    if (source_identity, source_form) not in printed:
        return AccountMatch("review", None, (), False)
    entries = (
        tuple(
            item
            for item in catalog.definitions
            if item.identity.parser_id == evidence.parser_id
            and item.identity.revision == evidence.definition_revision
            and item.sha256 == evidence.definition_sha256
        )
        if catalog is not None
        else ()
    )
    if len(entries) != 1 or entries[0].account_context is None:
        return AccountMatch("review", None, (), False)
    context = entries[0].account_context
    return match_source_account(
        source_identity,
        source_form,
        institution_key=context.institution_key,
        kind=context.kind,
        candidates=candidates,
        preferences=preferences,
    )

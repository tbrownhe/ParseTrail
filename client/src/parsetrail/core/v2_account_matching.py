"""Truthful source-account suggestions before a 2.0 ledger binding is saved."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

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

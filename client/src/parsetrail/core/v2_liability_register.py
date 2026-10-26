"""Finite account-total liability registers, independent of principal components."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from parsetrail.core.source_evidence import DateValue, ObservationEvidence, SourceEvidence, StatementPayload

REGISTER_PARSER = "pdf_yamahafin_202306"
RegisterPurpose = Literal["expense", "expense_refund", "income", "income_adjustment"]


@dataclass(frozen=True)
class RegisterActivityReviewRow:
    row_id: str
    source_date: str | None
    posting_date: str | None
    posting_date_provenance: str | None
    effective_date: str | None
    description: str | None
    amount_minor: int | None
    financial_account: str | None
    status: str
    entry_key: str | None = None
    category_id: str | None = None
    purpose: RegisterPurpose | None = None
    allowed_purposes: tuple[RegisterPurpose, ...] = ()
    transaction_date: date | None = None
    transaction_date_provenance: str | None = None
    financial_account_id: str | None = None
    financial_account_kind: str | None = None
    tracking_scope: str | None = None


def register_review_scopes(evidence: SourceEvidence) -> dict[str, bool]:
    if evidence.parser_id != REGISTER_PARSER or not isinstance(evidence.payload, StatementPayload):
        return {}
    return {
        row.row_id: account.balance_scope == "account_total"
        for account in evidence.payload.accounts
        for row in account.rows
    }


def register_posting_date(row: ObservationEvidence) -> DateValue | None:
    """A printed posting column can resolve its year without estimating a date."""
    if (
        row.row_role != "activity"
        or row.date_role != "posting_date"
        or row.date.iso is None
        or row.date.provenance not in {"observed", "derived"}
        or row.components
    ):
        return None
    return row.date

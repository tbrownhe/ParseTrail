"""Finite statement-value review; period totals never become cash transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from parsetrail.core.source_evidence import DateValue, MoneyValue, ObservationEvidence, SourceEvidence, StatementPayload

if TYPE_CHECKING:
    from parsetrail.core.v2_profile_store import ReviewedDatedValue, SourceClosingCandidate
    from parsetrail.core.v2_source_values import SourceValueProof


SUMMARY_VALUE_PARSERS = frozenset({"pdf_fidelity401k_201810", "pdf_vanguard_202210", "pdf_fidelityhsa_202001"})
SummaryReviewStatus = Literal["pending", "reviewed", "conflict", "blocked"]


@dataclass(frozen=True, slots=True)
class StatementSummarySection:
    source_identity: str
    source_identity_form: str
    account_id: str | None
    account_name: str | None
    opening: MoneyValue | None
    closing: MoneyValue | None
    rows: tuple[ObservationEvidence, ...]
    candidate: SourceClosingCandidate | None
    basis_sha256: str | None
    active_value: ReviewedDatedValue | None
    history: tuple[ReviewedDatedValue, ...]
    conflicting_values: tuple[ReviewedDatedValue, ...]
    blockers: tuple[str, ...]
    status: SummaryReviewStatus


@dataclass(frozen=True, slots=True)
class StatementSummarySnapshot:
    source_sha256: str
    parser_id: str
    start: DateValue
    end: DateValue
    capture_verified: bool
    independent_balance_verified: bool
    sections: tuple[StatementSummarySection, ...]
    blockers: tuple[str, ...]
    profile_identity: str

    @property
    def complete(self) -> bool:
        return (
            bool(self.sections) and not self.blockers and all(section.status == "reviewed" for section in self.sections)
        )


def summary_shape_blockers(evidence: SourceEvidence) -> tuple[str, ...]:
    if evidence.parser_id not in SUMMARY_VALUE_PARSERS:
        return ("statement_summary_family_unsupported",)
    payload = evidence.payload
    if not isinstance(payload, StatementPayload) or not payload.accounts:
        return ("statement_summary_shape_unsupported",)
    if any(
        row.row_role != "period_summary"
        or row.date_role != "statement_period_end"
        or row.date.iso != payload.end.iso
        or row.components
        for section in payload.accounts
        for row in section.rows
    ):
        return ("statement_summary_shape_unsupported",)
    return ()


def summary_value_state(
    proof: SourceValueProof | None,
    *,
    account_id: str | None,
    history: tuple[ReviewedDatedValue, ...],
    current_values: tuple[ReviewedDatedValue, ...],
    blockers: tuple[str, ...],
) -> tuple[SummaryReviewStatus, ReviewedDatedValue | None, tuple[ReviewedDatedValue, ...], tuple[str, ...]]:
    """Completion is the exact active source interpretation, never equal money alone."""
    if blockers or proof is None or account_id is None:
        return "blocked", None, (), blockers
    conflicts = tuple(value for value in current_values if value.amount_minor != proof.amount_minor)
    active = next(
        (
            value
            for value in history
            if value.state == "active"
            and value.account_id == account_id
            and not value.source_review_changed
            and value.source_proof == proof
        ),
        None,
    )
    if conflicts:
        return "conflict", active, current_values, ("statement_summary_value_conflict",)
    return ("reviewed" if active else "pending"), active, (), ()

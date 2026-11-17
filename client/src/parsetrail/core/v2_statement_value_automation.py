"""Standing authorization for exact closing values on newly imported summaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from parsetrail.core.v2_import_warnings import evidence_import_warnings
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_statement_summary_review import SUMMARY_VALUE_PARSERS, summary_shape_blockers

AUTOMATIC_REASON = "Automatically recorded under the statement-value preference"


@dataclass(frozen=True, slots=True)
class StatementValueAutomationResult:
    status: Literal["recorded", "needs_review", "cancelled"]
    value_id: int | None = None
    amount_minor: int | None = None
    value_date: date | None = None
    reason_code: str | None = None


def record_imported_statement_value(
    store,
    source_sha256: str,
    *,
    preferences: V2Preferences,
    expected_profile: str,
    authorize: Callable[[], None],
) -> StatementValueAutomationResult | None:
    """Record one exact new source value under transactional standing consent.

    The workspace establishes that this source was newly imported while consent
    was enabled. The source-value service owns all money/proof/history writes;
    its transaction hooks recheck policy and current consent before any retry or
    insertion and immediately before commit. Import persistence is independent.
    """
    from parsetrail.core.v2_import_accounts import _profile_identity
    from parsetrail.core.v2_profile_store import ProfileFormatError

    if type(preferences) is not V2Preferences or preferences.auto_record_statement_values is not True:
        raise ProfileFormatError("statement_value_auto_consent_required")

    def check_authorization():
        authorize()
        if _profile_identity(store) != expected_profile:
            raise ProfileFormatError("statement_value_auto_changed")

    def check_policy():
        evidence = store.load_import(source_sha256).evidence
        if evidence.parser_id not in SUMMARY_VALUE_PARSERS or summary_shape_blockers(evidence):
            raise ProfileFormatError("statement_value_auto_unsupported")
        if len(evidence.payload.accounts) != 1:
            raise ProfileFormatError("statement_value_auto_multiple_sections")
        if any(warning.classification == "requires_review" for warning in evidence_import_warnings(evidence)):
            raise ProfileFormatError("statement_value_auto_source_warning")
        if any(
            value.source_proof is not None and value.source_proof.source_sha256 == source_sha256
            for value in store._read_dated_values()
        ):
            raise ProfileFormatError("statement_value_auto_prior_review")

    evidence = store.load_import(source_sha256).evidence
    if evidence.parser_id not in SUMMARY_VALUE_PARSERS:
        return None
    check_authorization()
    check_policy()
    snapshot = store.statement_summary_snapshot(source_sha256)
    if snapshot.profile_identity != expected_profile:
        raise ProfileFormatError("statement_value_auto_changed")
    if snapshot.blockers or len(snapshot.sections) != 1:
        raise ProfileFormatError("statement_value_auto_unsupported")
    section = snapshot.sections[0]
    if section.status == "conflict":
        raise ProfileFormatError("statement_value_auto_conflict")
    if section.account_id is None:
        raise ProfileFormatError("statement_value_auto_account_required")
    if section.status != "pending" or section.blockers or section.candidate is None:
        raise ProfileFormatError("statement_value_auto_unavailable")
    candidate = section.candidate
    reference = f"{section.account_name} · statement ending {candidate.value_date} · source {source_sha256}"[:500]

    def before_write():
        check_authorization()
        check_policy()
        check_authorization()

    def before_commit():
        check_authorization()
        active = tuple(
            value
            for value in store._read_dated_values(section.account_id)
            if value.state == "active" and value.source_proof == candidate.proof
        )
        if len(active) != 1 or active[0].reason != AUTOMATIC_REASON or active[0].reference != reference:
            raise ProfileFormatError("statement_value_auto_changed")
        check_authorization()

    check_authorization()
    value = store.record_reviewed_source_value(
        section.account_id,
        candidate.candidate_id,
        expected_candidate_sha256=candidate.version,
        expected_basis_sha256=section.basis_sha256,
        expected_profile_identity=expected_profile,
        reference=reference,
        reason=AUTOMATIC_REASON,
        before_write=before_write,
        before_commit=before_commit,
    )
    return StatementValueAutomationResult("recorded", value.value_id, value.amount_minor, value.value_date)

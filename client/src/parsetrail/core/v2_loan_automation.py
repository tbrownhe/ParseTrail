"""Standing opt-in authorization for finite, newly imported lender payments."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from parsetrail.core.source_evidence import StatementPayload
from parsetrail.core.v2_import_warnings import evidence_import_warnings
from parsetrail.core.v2_preferences import V2Preferences

AUTOMATIC_REASON = "Automatically posted under the supported-loan-payment preference"


@dataclass(frozen=True, slots=True)
class LoanAutomationResult:
    status: Literal["posted", "needs_review", "cancelled"]
    event_id: str | None = None
    principal_minor: int | None = None
    interest_minor: int | None = None
    reason_code: str | None = None


def post_imported_loan_payment(
    store,
    source_sha256: str,
    *,
    preferences: V2Preferences,
    established_accounts: frozenset[str],
    expected_profile: str,
    authorize: Callable[[], None],
) -> LoanAutomationResult | None:
    """Rebuild and post one eligible new lender side inside its write transaction.

    The caller owns proof that this source was freshly imported under the captured
    opt-in. The authorization callback rechecks current consent and cancellation.
    Any refusal rolls back postings while retaining the earlier source import.
    """
    from parsetrail.core.v2_import_accounts import _profile_identity
    from parsetrail.core.v2_loan_payments import LOAN_PARSERS
    from parsetrail.core.v2_profile_store import ProfileFormatError

    if type(preferences) is not V2Preferences or preferences.auto_post_loan_payments is not True:
        raise ProfileFormatError("loan_auto_consent_required")

    def check_authorization():
        authorize()
        if _profile_identity(store) != expected_profile:
            raise ProfileFormatError("loan_auto_changed")

    def refuse(code):
        raise ProfileFormatError(code)

    evidence = store.load_import(source_sha256).evidence
    if evidence.parser_id not in LOAN_PARSERS:
        return None
    if evidence.parser_id != "pdf_capitaloneauto_202402" or evidence.engine_version != "loan-history-lines-pilot-2":
        return LoanAutomationResult("needs_review", reason_code="loan_auto_unsupported")
    check_authorization()
    store._loan_write_start(AUTOMATIC_REASON)
    try:
        check_authorization()
        evidence = store.load_import(source_sha256).evidence
        if evidence.parser_id != "pdf_capitaloneauto_202402" or evidence.engine_version != "loan-history-lines-pilot-2":
            refuse("loan_auto_unsupported")
        payload = evidence.payload
        if not isinstance(payload, StatementPayload) or len(payload.accounts) != 1:
            refuse("loan_auto_multiple_payments")
        rows = payload.accounts[0].rows
        if len(rows) != 1:
            refuse("loan_auto_multiple_payments")
        if (rows[0].description.text or "").strip().casefold() == "amount financed":
            refuse("loan_auto_origination")
        if any(warning.classification == "requires_review" for warning in evidence_import_warnings(evidence)):
            refuse("loan_auto_source_warning")
        if any(
            proof.source_sha256 == source_sha256
            for event in store._read_loan_history()[0]
            for proof in event.manifest.components
        ):
            refuse("loan_auto_prior_review")
        if not preferences.allow_assumed_posting_dates:
            refuse("loan_auto_date_permission_required")
        components = tuple(row for row in store._loan_component_rows(preferences) if row.source_sha256 == source_sha256)
        if len(components) != 1 or components[0].account_id is None:
            refuse("loan_auto_account_required")
        component = components[0]
        if component.account_id not in established_accounts:
            refuse("loan_auto_account_new")
        if not component.eligible:
            refuse(component.blockers[0] if component.blockers else "loan_auto_changed")
        manifest = store._loan_build((None, (component.row_id,)), preferences)
        basis = store._source_overlap_basis()
        reference = f"{component.account_name} · {component.activity_date} · source {source_sha256}"[:500]
        check_authorization()
        store._loan_mutating = True
        event_id = store._loan_record(manifest, reference=reference, reason=AUTOMATIC_REASON, basis=basis)
        store._loan_mutating = False
        # Validation and history reconstruction may be substantial. Consent and
        # cancellation are checked again before committing any financial effect.
        saved = next(event for event in store._read_loan_history()[0] if event.event_id == event_id)
        check_authorization()
        store.connection.execute("COMMIT")
        return LoanAutomationResult("posted", saved.event_id, manifest.principal_minor, manifest.interest_minor)
    except BaseException:
        store.connection.execute("ROLLBACK")
        raise
    finally:
        store._loan_mutating = False

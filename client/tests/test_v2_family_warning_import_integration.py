"""Benign source qualifications never authorize an origination posting."""

import pytest
from parsetrail.core.v2_import_warnings import evidence_import_warnings
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_loan_document_review import V2LoanDocumentReview

from devtools.parser_engine_pilot import test_loan_history_lines as capital
from devtools.parser_engine_pilot.synthetic_family_sources import pdf_document, text_page
from devtools.parser_engine_pilot.test_summary_followup_shapes import HSA, empty_cash_lines

from .qt_journey_helpers import JourneyArtifacts
from .test_v2_loan_automation import choose_loan, loan_workspace
from .test_v2_loan_automation_desktop import dispose
from .v2_job_wait import wait_for_jobs


def prepare_origination(tmp_path):
    workspace, payment = loan_workspace(tmp_path)
    workspace.import_file(payment, review_import=choose_loan)
    workspace.set_allow_abbreviated_account_matching(True)
    workspace.set_import_preview_mode("when_needed")
    workspace.set_allow_assumed_posting_dates(True)
    workspace.set_auto_post_loan_payments(True)
    printed = capital.lines(interest=False, changes={1: "Current Payment Due: $300.00 Principal Balance: $10,000.00"})
    source = pdf_document((text_page("Capital One Auto Finance", *(line.raw for line in printed.lines)),))
    path = tmp_path / "public-origination.pdf"
    path.write_bytes(source)
    return workspace, path, source


def import_without_preview(workspace, path):
    def unexpected(*_args):
        pytest.fail("The established account and proved origination source should not need import preview")

    result = workspace.import_file(path, review_import=unexpected)
    assert result.status == "imported"
    assert result.loan_automation is not None and result.loan_automation.status != "posted"
    warnings = evidence_import_warnings(result.evidence)
    assert not any(warning.classification == "requires_review" for warning in warnings)
    limit = next(warning for warning in warnings if warning.code == "source_balance_check_unavailable")
    assert limit.classification == "informational"
    assert result.evidence.payload.accounts[0].opening is None
    assert not result.evidence.payload.independent_balance_verified and not result.evidence.payload.capture_verified
    return result


def test_real_origination_auto_import_keeps_financial_review_and_saved_evidence(tmp_path, monkeypatch):
    workspace, path, source = prepare_origination(tmp_path)
    result = import_without_preview(workspace, path)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        saved = store.load_import(result.source_sha256)
        assert saved.source == source and saved.evidence == result.evidence
        assert not store.loan_history() and not store.origination_snapshot().events
        assert len(store.origination_snapshot().rows) == 1
        assert not store._active_consumed() and not store._active_journal_entries()
        assert store.opening_decision("loan") is None

    from parsetrail.core import v2_source_pipeline as pipeline

    def forbidden(*_args, **_kwargs):
        pytest.fail("Saved source retry must not decode, reparse or create a financial event")

    monkeypatch.setattr(pipeline, "build_source_evidence", forbidden)
    assert workspace.import_file(path, review_import=forbidden).status == "already_imported"


@pytest.mark.parametrize("closure", ["11/30/26)", "02/30/26)"])
def test_source_closure_date_never_closes_the_authored_account(tmp_path, closure):
    printed = ["HealthEquity HealthSavingsAccount", "HealthSavingsAccount(Closed", closure, *empty_cash_lines()]
    source = pdf_document((text_page(*printed),))
    evidence = build_source_evidence(source, HSA, suffix=".pdf")
    requires_review = any(warning.classification == "requires_review" for warning in evidence_import_warnings(evidence))
    assert requires_review == (closure == "02/30/26)")
    account = evidence.payload.accounts[0]
    assert not account.rows and account.opening.minor == account.closing.minor == 1000
    path = tmp_path / "empty-hsa.db"
    with V2ProfileStore.create(path) as store:
        store.add_financial_account(
            FinancialAccount(
                "hsa", "Cash component", "asset", "healthequity", tracking_scope="cash_component", product_type="hsa"
            )
        )
        store.import_source(source, HSA, evidence, suffix=".pdf")
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "hsa")
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert store.connection.execute("SELECT count(*) FROM AccountLifecycleDecisions").fetchone() == (0,)
        assert not store._active_journal_entries() and store.opening_decision("hsa") is None


@pytest.mark.parametrize("size", [(1050, 700), (1100, 650)])
def test_qualified_import_still_has_a_manual_origination_action(qtbot, qapp, tmp_path, journey_artifacts, size):
    workspace, path, _source = prepare_origination(tmp_path)
    imported = import_without_preview(workspace, path)
    view = V2LoanDocumentReview(workspace, imported.source_sha256)
    try:
        view.resize(*size)
        view.show()
        wait_for_jobs(view)
        assert view.table.rowCount() == 1
        assert view.action_button.isEnabled() and "origination" in view.action_button.text().lower()
        assert view.action_button.property("formState") == "ready"
        assert "unknown opening" in " ".join(label.text().lower() for label in view.findChildren(type(view.status)))
        JourneyArtifacts(journey_artifacts, qapp, size).capture("01-imported-origin-still-needs-financial-review", view)
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert not store.origination_snapshot().events and not store._active_journal_entries()
    finally:
        dispose(qtbot, view)

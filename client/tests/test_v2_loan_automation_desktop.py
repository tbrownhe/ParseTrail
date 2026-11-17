"""Standing consent, low-friction review and truthful completed-loan presentation."""

import pytest
from parsetrail.core.v2_import_accounts import _profile_identity
from parsetrail.core.v2_loan_automation import AUTOMATIC_REASON, LoanAutomationResult, post_imported_loan_payment
from parsetrail.core.v2_loan_history_lines import parse_loan_history
from parsetrail.core.v2_preferences import save_preferences
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import BatchFileResult, BatchImportResult, V2Workspace
from parsetrail.gui.v2_batch_import import V2BatchImportReport
from parsetrail.gui.v2_loan_document_review import V2LoanDocumentReview
from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QThread
from shiboken6 import isValid

from devtools.parser_engine_pilot import test_loan_history_lines as capital
from devtools.parser_engine_pilot import test_wells_loan_lines as wells

from .qt_journey_helpers import JourneyArtifacts, click_menu
from .test_v2_document_browser import wait_for_inventory
from .test_v2_loan_payments import PREFERENCES, _post, _profile
from .v2_job_wait import wait_for_jobs


def prepared(tmp_path, *, multiple=False):
    path = tmp_path / "loans.db"
    args = (
        {"evidence": wells.parse(), "definition": wells.DEFINITION, "raw": b"%PDF-synthetic-loan"} if multiple else {}
    )
    _bank, rows = _profile(path, **args)
    prefs = tmp_path / "preferences.json"
    save_preferences(prefs, PREFERENCES)
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=prefs)
    with V2ProfileStore.open(path, read_only=True) as store:
        source = next(
            row.source_sha256 for row in store.loan_review_snapshot(PREFERENCES).components if row.row_id == rows[0]
        )
    return workspace, source, rows


def click_checkbox(qtbot, widget):
    qtbot.mouseClick(widget, Qt.LeftButton, pos=QPoint(8, widget.height() // 2))


def dispose(qtbot, widget):
    destroyed = []
    thread = QThread.currentThread()
    widget.destroyed.connect(lambda: destroyed.append(QThread.currentThread() == thread))
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qtbot.waitUntil(lambda: not isValid(widget))
    assert destroyed == [True]


def test_menu_opt_in_is_persistent_future_only_and_independent_of_date_permission(
    qtbot, qapp, tmp_path, journey_artifacts
):
    workspace, _source, _rows = prepared(tmp_path)
    workspace.set_allow_assumed_posting_dates(False)
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.show()
    wait_for_inventory(window)
    assert not window.auto_post_loan_action.isChecked()
    click_menu(qtbot, window, "Settings", "Automatically post supported loan payments")
    assert workspace.preferences().auto_post_loan_payments
    assert not workspace.preferences().allow_assumed_posting_dates
    assert "future supported imports" in window.status.text()
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert not store.loan_history() and not store._active_journal_entries()
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("01-standing-opt-in", window)
    window._sync_preference_controls()
    assert window.auto_post_loan_action.isChecked()
    window.auto_post_loan_action.trigger()
    assert not workspace.preferences().auto_post_loan_payments
    dispose(qtbot, window)


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800), (1100, 650)])
def test_one_payment_is_selected_and_toggle_preserves_manual_draft_without_posting(
    qtbot, qapp, tmp_path, journey_artifacts, size
):
    workspace, source, rows = prepared(tmp_path)
    view = V2LoanPaymentReview(workspace, source_sha256=source, focus_row_id=rows[0])
    qtbot.addWidget(view)
    view.resize(*size)
    view.show()
    wait_for_jobs(view)
    assert view._component_ids() == rows
    assert view.bank.currentData() is None and view.confirm.isEnabled()
    assert view.confirm.property("formState") == "ready"
    assert view.reason.text() == "Initial Review" and view.reference.text()
    assert view.preview.manifest.bank is None
    reference = view.reference.text()
    qtbot.mouseClick(view.rules.button, Qt.LeftButton)
    click_checkbox(qtbot, view.auto_post)
    assert workspace.preferences().auto_post_loan_payments
    assert view._component_ids() == rows and view.reference.text() == reference
    assert view.confirm.isEnabled() and view.selected_event is None
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert not store.loan_history() and not store._active_journal_entries()
    assert "Future imports only" in view.auto_post_help.text()
    qtbot.wait(150)  # Let the native checkbox's checkmark animation settle for inspection.
    assert view.components.viewport().height() >= view.components.rowHeight(0)
    JourneyArtifacts(journey_artifacts, qapp, size).capture("02-selected-payment-future-consent", view)
    click_checkbox(qtbot, view.auto_post)
    assert not workspace.preferences().auto_post_loan_payments
    qtbot.mouseClick(view.rules.button, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.rules.height() < 50)
    qapp.processEvents()
    view.resize(*size)
    qtbot.waitUntil(lambda: (view.width(), view.height()) == size)
    assert (view.width(), view.height()) == size
    JourneyArtifacts(journey_artifacts, qapp, size).capture("02b-selected-current-payment", view)
    dispose(qtbot, view)


def test_multiple_components_are_not_selected_automatically(qtbot, tmp_path):
    workspace, source, _rows = prepared(tmp_path, multiple=True)
    view = V2LoanPaymentReview(workspace, source_sha256=source)
    qtbot.addWidget(view)
    wait_for_jobs(view)
    assert len(view.rows) == 2 and not view._component_ids() and not view.confirm.isEnabled()
    dispose(qtbot, view)


def test_automatic_payment_is_complete_neutral_and_has_truthful_history(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, source, rows = prepared(tmp_path)
    workspace.set_auto_post_loan_payments(True)
    with V2ProfileStore.open(workspace.profile_path) as store:
        result = post_imported_loan_payment(
            store,
            source,
            preferences=workspace.preferences(),
            established_accounts=frozenset({"loan"}),
            expected_profile=_profile_identity(store),
            authorize=lambda: None,
        )
        assert result.status == "posted"
        event = store.loan_history()[0]
        assert event.reason == AUTOMATIC_REASON and event.manifest.bank is None
    landing = V2LoanDocumentReview(workspace, source)
    qtbot.addWidget(landing)
    landing.resize(1050, 700)
    landing.show()
    wait_for_jobs(landing)
    assert landing.action_button.text() == "View payment"
    assert landing.action_button.isEnabled() and landing.action_button.property("formState") == "neutral"
    assert "Review complete" in landing.explanation.text()
    assert "Automatically posted" in landing.status.text()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    artifacts.capture("03-complete-neutral-automatic-payment", landing)
    dispose(qtbot, landing)
    saved = V2LoanPaymentReview(workspace, event_id=event.event_id, source_sha256=source, focus_row_id=rows[0])
    qtbot.addWidget(saved)
    saved.show()
    wait_for_jobs(saved)
    assert "Automatically posted" in saved.summary.text()
    assert AUTOMATIC_REASON in saved.history_details.toPlainText()
    assert not saved.confirm.isEnabled()
    artifacts.capture("04-automatic-payment-history", saved)
    dispose(qtbot, saved)


def test_batch_report_separates_import_success_posting_and_manual_fallback(qtbot, qapp, tmp_path, journey_artifacts):
    posted = LoanAutomationResult("posted", "event", 20000, 2000)
    review = LoanAutomationResult("needs_review", reason_code="loan_auto_date_permission_required")
    result = BatchImportResult(
        (
            BatchFileResult(tmp_path / "complete.pdf", "imported", "a" * 64, loan_automation=posted),
            BatchFileResult(tmp_path / "needs-date.pdf", "imported", "b" * 64, loan_automation=review),
        ),
        False,
    )
    report = V2BatchImportReport(result)
    qtbot.addWidget(report)
    report.show()
    assert "Automatically posted" in report.recovery_guidance.text()
    assert "$200.00 principal" in report.recovery_guidance.text()
    assert "unresolved in Transfers" in report.recovery_guidance.text()
    report.files.setCurrentRow(1)
    assert (
        "Imported" in report.recovery_guidance.text() and "assumed accounting date" in report.recovery_guidance.text()
    )
    JourneyArtifacts(journey_artifacts, qapp, (780, 480)).capture("05-imported-manual-fallback", report)
    dispose(qtbot, report)


def test_saved_origination_is_neutral_and_complete(qtbot, qapp, tmp_path, journey_artifacts):
    from .test_v2_flexible_funding import funding
    from .test_v2_origination_desktop import prepared as origination

    workspace, _bank, row = origination(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        event = store.post_loan_origination(funding(store, row))
        source = store.origination_snapshot().rows[0].source_sha256
    landing = V2LoanDocumentReview(workspace, source)
    qtbot.addWidget(landing)
    landing.resize(1050, 700)
    landing.show()
    wait_for_jobs(landing)
    assert event.status == "active" and landing.action_button.text() == "View loan origination"
    assert landing.action_button.property("formState") == "neutral"
    assert "Review complete" in landing.explanation.text()
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("06-complete-neutral-origination", landing)
    dispose(qtbot, landing)


def test_one_saved_row_does_not_mark_a_whole_statement_complete(qtbot, qapp, tmp_path, journey_artifacts):
    path = tmp_path / "two-payments.db"
    evidence = parse_loan_history(
        capital.DEFINITION,
        capital.lines(changes={5: "01/20/2026 Payment Received -$100.00 -$10.00 = -$110.00"}),
    )
    _bank, rows = _profile(path, evidence=evidence)
    prefs = tmp_path / "preferences.json"
    save_preferences(prefs, PREFERENCES)
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=prefs)
    with V2ProfileStore.open(path) as store:
        _post(store, None, (rows[0],))
    landing = V2LoanDocumentReview(workspace, evidence.source_sha256)
    qtbot.addWidget(landing)
    landing.resize(1050, 700)
    landing.show()
    wait_for_jobs(landing)
    assert len(landing.rows) == 2 and "Review complete" not in landing.explanation.text()
    assert landing.action_button.text() == "View payment"
    assert landing.action_button.property("formState") == "neutral"
    landing.table.selectRow(1)
    assert landing.action_button.text() == "Review loan payment…"
    assert landing.action_button.property("formState") == "ready"
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("07-incomplete-statement-next-action", landing)
    dispose(qtbot, landing)

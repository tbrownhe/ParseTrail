"""Standing statement-value consent stays distinct from the current manual draft."""

from datetime import date

import pytest
from parsetrail.core.v2_import_accounts import _profile_identity
from parsetrail.core.v2_loan_automation import LoanAutomationResult
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_statement_value_automation import (
    AUTOMATIC_REASON,
    StatementValueAutomationResult,
    record_imported_statement_value,
)
from parsetrail.core.v2_workspace import BatchFileResult, BatchImportResult
from parsetrail.gui.v2_account_anchors import V2AccountAnchors
from parsetrail.gui.v2_batch_import import V2BatchImportReport, import_automation_summary
from parsetrail.gui.v2_statement_summary_review import V2StatementSummaryReview
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from .qt_journey_helpers import JourneyArtifacts, click_menu
from .test_v2_document_browser import wait_for_inventory
from .test_v2_statement_summary_desktop import dispose, prepared
from .v2_job_wait import wait_for_jobs


def test_settings_and_embedded_choice_sync_without_recording_current_source(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, sources = prepared(tmp_path)
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.show()
    wait_for_inventory(window)
    window._select_review_source(sources[0])
    window.navigation.setCurrentRow(window.REVIEW)
    view = window._review_widget
    wait_for_jobs(view)
    assert isinstance(view, V2StatementSummaryReview)
    assert not window.auto_record_statement_values_action.isChecked() and not view.auto_record.isChecked()
    view.reference.setText("My initial statement reference")
    view.reason.setText("My initial statement assessment")
    fields = view.reference.text(), view.reason.text()
    click_menu(qtbot, window, "Settings", "Automatically record supported statement values")
    assert workspace.preferences().auto_record_statement_values
    assert view.auto_record.isChecked()
    assert not workspace.preferences().auto_post_loan_payments
    assert not workspace.preferences().allow_assumed_posting_dates
    assert (view.reference.text(), view.reason.text()) == fields and view.has_unsaved_draft
    assert not view.snapshot.complete and view.action_button.isEnabled()
    qtbot.mouseClick(view.details.button, Qt.LeftButton)
    view.auto_record.setFocus()
    qtbot.keyClick(view.auto_record, Qt.Key_Space)
    assert not workspace.preferences().auto_record_statement_values
    assert not window.auto_record_statement_values_action.isChecked()
    qtbot.keyClick(view.auto_record, Qt.Key_Space)
    assert workspace.preferences().auto_record_statement_values
    assert window.auto_record_statement_values_action.isChecked()
    assert "future imports" in view.status.text() and "Record action" in view.status.text()
    assert (view.reference.text(), view.reason.text()) == fields and view.has_unsaved_draft
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("01-synchronized-future-import-choice", window)
    view.reference.setText(view._default_fields[0])
    view.reason.setText(view._default_fields[1])
    dispose(qtbot, window)
    reopened = V2WorkspaceWindow(workspace)
    qtbot.addWidget(reopened)
    wait_for_inventory(reopened)
    assert reopened.auto_record_statement_values_action.isChecked()
    dispose(qtbot, reopened)


@pytest.mark.parametrize("size", [(1050, 700), (1100, 650), (1280, 800)])
def test_future_import_details_are_readable_and_leave_current_manual_action(
    qtbot, qapp, tmp_path, journey_artifacts, size
):
    workspace, sources = prepared(tmp_path)
    view = V2StatementSummaryReview(workspace, sources[0])
    qtbot.addWidget(view)
    view.resize(*size)
    view.show()
    wait_for_jobs(view)
    assert view.details.height() < 50 and not view.auto_record.isVisible()
    fields = view.reference.text(), view.reason.text()
    qtbot.mouseClick(view.details.button, Qt.LeftButton)
    view.auto_record.setFocus()
    qtbot.keyClick(view.auto_record, Qt.Key_Space)
    assert workspace.preferences().auto_record_statement_values
    assert (view.reference.text(), view.reason.text()) == fields
    assert not view.has_unsaved_draft and not view.snapshot.complete
    assert view.action_button.isEnabled() and view.action_button.property("formState") == "ready"
    assert "Future imports only" in view.auto_record_help.text()
    assert "Fidelity" in view.auto_record_help.text() and "no transactions or budget" in view.auto_record_help.text()
    assert view.table.viewport().height() >= sum(view.table.rowHeight(i) for i in range(view.table.rowCount()))
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    artifacts.capture("02-expanded-future-import-setting", view)
    view.reference.clear()
    qtbot.keyClick(view.auto_record, Qt.Key_Space)
    assert view.reference.text() == "" and not view.action_button.isEnabled()
    assert "review reference and reason" in view.status.text() and "Show details" in view.status.text()
    assert view.reference.property("formState") == "required"
    artifacts.capture("02b-required-field-after-preference-change", view)
    view.reference.setText(fields[0])
    assert view.action_button.isEnabled() and view.action_button.property("formState") == "ready"
    qtbot.mouseClick(view.details.button, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.details.height() < 50)
    view.resize(*size)
    qapp.processEvents()
    assert (view.width(), view.height()) == size
    artifacts.capture("03-collapsed-current-manual-review", view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert not store.statement_summary_snapshot(sources[0]).complete
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (0,)
    dispose(qtbot, view)


def test_preference_failure_restores_both_controls_and_preserves_draft(qtbot, tmp_path, monkeypatch):
    workspace, sources = prepared(tmp_path)
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.show()
    wait_for_inventory(window)
    window._select_review_source(sources[0])
    window.navigation.setCurrentRow(window.REVIEW)
    view = window._review_widget
    wait_for_jobs(view)
    fields = view.reference.text(), view.reason.text()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(True))

    def unavailable(_enabled):
        raise OSError("Synthetic preference write failure")

    monkeypatch.setattr(workspace, "set_auto_record_statement_values", unavailable)
    window.auto_record_statement_values_action.trigger()
    assert warnings == [True]
    assert not window.auto_record_statement_values_action.isChecked() and not view.auto_record.isChecked()
    qtbot.mouseClick(view.details.button, Qt.LeftButton)
    view.auto_record.setFocus()
    qtbot.keyClick(view.auto_record, Qt.Key_Space)
    assert not view.auto_record.isChecked() and not workspace.preferences().auto_record_statement_values
    assert "not saved" in view.status.text()
    assert (view.reference.text(), view.reason.text()) == fields
    assert view.action_button.isEnabled() and not view.snapshot.complete
    monkeypatch.setattr(
        workspace, "preferences", lambda: (_ for _ in ()).throw(ValueError("Synthetic invalid settings"))
    )
    qtbot.mouseClick(view.reload_button, Qt.LeftButton)
    wait_for_jobs(view)
    assert "preferences are unavailable" in view.status.text()
    assert view.action_button.isEnabled() and not view.snapshot.complete
    dispose(qtbot, window)


def test_automatic_value_has_truthful_complete_status_and_history(
    qtbot, qapp, tmp_path, journey_artifacts, monkeypatch
):
    workspace, sources = prepared(tmp_path)
    workspace.set_auto_record_statement_values(True)
    with V2ProfileStore.open(workspace.profile_path) as store:
        result = record_imported_statement_value(
            store,
            sources[0],
            preferences=workspace.preferences(),
            expected_profile=_profile_identity(store),
            authorize=lambda: None,
        )
        assert result.status == "recorded"
        assert store.statement_summary_snapshot(sources[0]).sections[0].active_value.reason == AUTOMATIC_REASON
    view = V2StatementSummaryReview(workspace, sources[0])
    qtbot.addWidget(view)
    view.resize(1050, 700)
    view.show()
    wait_for_jobs(view)
    assert view.snapshot.complete and "Value recorded automatically" in view.status.text()
    assert "Review complete" in view.status.text()
    assert view.action_button.property("formState") == "neutral"
    assert view.action_button.text() == "View recorded value/history…"
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("04-automatic-value-complete", view)
    inspected = []

    def inspect(dialog):
        assert dialog.snapshot.latest_dated_value.reason == AUTOMATIC_REASON
        assert dialog.snapshot.latest_dated_value.amount_minor == 14000
        assert "2026-01-31" in dialog.books.text()
        inspected.append(True)
        return 0

    monkeypatch.setattr(V2AccountAnchors, "exec", inspect)
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    wait_for_jobs(view)
    assert inspected == [True] and view.snapshot.complete
    dispose(qtbot, view)


def test_batch_results_distinguish_value_loan_and_manual_fallback(qtbot, qapp, tmp_path, journey_artifacts):
    loan = BatchFileResult(
        tmp_path / "loan.pdf", "imported", loan_automation=LoanAutomationResult("posted", "loan", 20000, 2000)
    )
    value = BatchFileResult(
        tmp_path / "retirement.pdf",
        "imported",
        statement_value_automation=StatementValueAutomationResult("recorded", 1, 14000, date(2026, 1, 31)),
    )
    conflict = BatchFileResult(
        tmp_path / "conflict.pdf",
        "imported",
        statement_value_automation=StatementValueAutomationResult(
            "needs_review", reason_code="statement_value_auto_conflict"
        ),
    )
    cancelled = BatchFileResult(
        tmp_path / "cancelled.pdf",
        "imported",
        statement_value_automation=StatementValueAutomationResult(
            "cancelled", reason_code="statement_value_auto_cancelled"
        ),
    )
    view = V2BatchImportReport(BatchImportResult((loan, value, conflict, cancelled), True))
    qtbot.addWidget(view)
    view.show()
    view.files.setCurrentRow(1)
    assert "statement value recorded automatically" in view.files.item(1).text()
    assert "140.00" in view.recovery_guidance.text() and "2026-01-31" in view.recovery_guidance.text()
    assert "payment" not in view.recovery_guidance.text()
    view.files.setCurrentRow(2)
    assert "Imported" in view.recovery_guidance.text() and "Different values" in view.recovery_guidance.text()
    assert "needs review" in view.files.item(2).text() and "failed" not in view.files.item(2).text()
    JourneyArtifacts(journey_artifacts, qapp, (780, 480)).capture("05-import-saved-manual-value-fallback", view)
    view.files.setCurrentRow(3)
    assert "cancelled" in view.recovery_guidance.text()
    assert "Imported" in view.recovery_guidance.text()
    assert "Automatically posted payment" in import_automation_summary(loan)
    dispose(qtbot, view)

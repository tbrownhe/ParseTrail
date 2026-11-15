"""The document month, budget editing and correction return share one context."""

from datetime import date

from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_categories import V2CategoryDialog
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import QDate, Qt

from .qt_journey_helpers import JourneyArtifacts, ModalSteps, close_dialog, enter_text
from .test_v2_document_browser import _populated_workspace, wait_for_inventory
from .test_v2_reports_responsiveness import wait_for_reports
from .test_v2_workspace_window import DEFINITION, SOURCE
from .v2_job_wait import wait_for_jobs


def prepare(qtbot, tmp_path):
    workspace = _populated_workspace(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        source = store.load_import(store.source_ids()[0])
        row_id = source.evidence.payload.rows[0].row_id
        store.add_category_account("expense:food", "Food", "expense")
        store.set_category_budget_rate("expense:food", date(2026, 10, 1), 1000)
        store.post_reviewed_cash_category(row_id, "expense:food", purpose="expense", reason="Verified food")
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.show()
    wait_for_inventory(window)
    return window, workspace, row_id


def test_document_budget_keeps_month_and_exact_origin_after_source_review(qtbot, tmp_path, qapp, journey_artifacts):
    window, workspace, row_id = prepare(qtbot, tmp_path)
    window.navigation.setCurrentRow(window.REVIEW)
    wait_for_jobs(window._review_widget)
    window.document_spending_button.click()
    view = window._reports_view
    view.end.setDate(QDate(2026, 10, 15))
    window.navigation.setCurrentRow(window.BUDGET)
    wait_for_reports(view)
    assert window._reports_view is view
    assert view.budget_month.date() == QDate(2026, 10, 1)
    assert view.budget_model.rows[0].target_minor == 1000
    assert view.budget_model.rows[0].reviewed_spending_minor == 400
    assert view.budget_model.rows[0].remaining_minor == 600
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    artifacts.capture("01-document-october-budget", window)
    view.source_review_requested.emit(window._selected_source(), row_id)
    wait_for_jobs(window._review_widget)
    assert window.navigation.currentRow() == window.REVIEW
    assert window.back_to_report_button.text() == "Back to budget"
    window.back_to_report_button.click()
    wait_for_reports(view)
    assert window.navigation.currentRow() == window.BUDGET
    assert view.tabs.currentIndex() == 2
    assert view.end.date() == QDate(2026, 10, 15)
    view.budget_month.setDate(QDate(2026, 9, 1))
    window.navigation.setCurrentRow(window.REPORTS)
    assert view.tabs.currentIndex() == 0
    view.tabs.setCurrentIndex(3)
    window.navigation.setCurrentRow(window.BUDGET)
    assert view.budget_month.date() == QDate(2026, 9, 1)
    window.navigation.setCurrentRow(window.REPORTS)
    assert view.tabs.currentIndex() == 3
    wait_for_reports(view)
    window.close()


def test_budget_return_does_not_reseed_from_a_different_source_month(qtbot, tmp_path):
    window, workspace, _row_id = prepare(qtbot, tmp_path)
    window.navigation.setCurrentRow(window.BUDGET)
    view = window._reports_view
    wait_for_reports(view)
    view.end.setDate(QDate(2026, 10, 15))
    other = SOURCE.replace(b"10/01/2026", b"09/01/2026").replace(b"Coffee", b"September coffee")
    evidence = build_source_evidence(other, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(other, DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
    window.refresh()
    wait_for_inventory(window)
    window._review_report_source(evidence.source_sha256, evidence.payload.rows[0].row_id)
    wait_for_jobs(window._review_widget)
    window.back_to_report_button.click()
    wait_for_reports(view)
    assert window.navigation.currentRow() == window.BUDGET
    assert view.budget_month.date() == QDate(2026, 10, 1)
    assert view.end.date() == QDate(2026, 10, 15)
    window.close()


def test_budget_edit_opens_selected_month_category_and_refreshes_without_posting(
    qtbot, tmp_path, qapp, journey_artifacts
):
    window, workspace, _row_id = prepare(qtbot, tmp_path)
    window.navigation.setCurrentRow(window.BUDGET)
    view = window._reports_view
    wait_for_reports(view)
    assert view.budget_month.date() == QDate(2026, 10, 1)
    view.budget_table.selectRow(0)
    modals = ModalSteps(qtbot)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))

    def edit(dialog):
        assert dialog.budget_month.date() == QDate(2026, 10, 1)
        assert dialog.categories.currentItem().data(Qt.UserRole) == "expense:food"
        assert not dialog.add_panel.isVisible()
        enter_text(qtbot, dialog.budget_amount, "20.00")
        qtbot.mouseClick(dialog.budget_save, Qt.LeftButton)
        assert not dialog.add_choice_status.isVisible()
        artifacts.capture("02-budget-edit-saved-no-unrelated-error", dialog)
        close_dialog(qtbot, dialog)

    modals.arm((V2CategoryDialog, edit))
    qtbot.mouseClick(view.edit_budget_button, Qt.LeftButton)
    modals.finish()
    wait_for_inventory(window)
    wait_for_reports(view)
    assert view.budget_month.date() == QDate(2026, 10, 1)
    assert view.budget_model.rows[0].target_minor == 2000
    assert view.budget_model.rows[0].remaining_minor == 1600
    assert view.budget_table.currentIndex().row() == 0
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)
        assert len(store.source_ids()) == 1
    artifacts.capture("03-budget-result-refreshed", window)
    window.close()

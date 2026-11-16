"""Context stays attached across document review, spending and correction."""

from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import QCoreApplication, QDate, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from .test_v2_document_browser import _populated_workspace, wait_for_inventory
from .test_v2_reports_responsiveness import wait_for_reports
from .test_v2_workspace_window import DEFINITION, SOURCE
from .v2_job_wait import wait_for_jobs

pytestmark = pytest.mark.usefixtures("qapp")


def cleanup(window):
    if window._review_widget is not None and hasattr(window._review_widget, "batch"):
        window._review_widget.reason.clear()
        window._review_widget.batch.clear()
    window.close()
    QApplication.processEvents()
    # These functional checks own their windows without qtbot.addWidget.
    # Dispose on the GUI thread instead of leaving parent/slot cycles for GC
    # during a later test's asynchronous profile read.
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_document_dates_handoff_and_back_keep_report_period(tmp_path):
    QApplication.instance() or QApplication([])
    window = V2WorkspaceWindow(_populated_workspace(tmp_path))
    try:
        wait_for_inventory(window)
        window.navigation.setCurrentRow(window.REVIEW)
        wait_for_jobs(window._review_widget)
        window.document_spending_button.click()
        reports = window._reports_view
        wait_for_reports(reports)
        assert reports.start.date() == QDate(2026, 10, 1)
        assert reports.end.date() == QDate(2026, 10, 2)
        assert "All profile accounts" in window.report_context.text()
        assert "Dates from" in window.report_context.text()
        assert reports.budget_month.date() == QDate(2026, 10, 1)
        reports.start.setDate(QDate(2026, 9, 1))
        reports.tabs.setCurrentIndex(3)
        window.navigation.setCurrentRow(window.REVIEW)
        window._back_to_report()
        wait_for_reports(reports)
        assert reports.start.date() == QDate(2026, 9, 1)
        assert reports.tabs.currentIndex() == 3
        summary = window._document_summaries[window._selected_source()]
        window._document_summaries[summary.source_sha256] = replace(summary, end=None)
        window._update_controls()
        assert not window.document_spending_button.isEnabled()
    finally:
        cleanup(window)


def test_next_attention_skips_allocated_and_selector_keeps_draft(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    workspace = _populated_workspace(tmp_path)
    other = SOURCE.replace(b"Coffee", b"Tea")
    other_evidence = build_source_evidence(other, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(other, DEFINITION, other_evidence, suffix=".csv")
        store.bind_source_account(other_evidence.source_sha256, "Checking A", "opaque", "cash")
    window = V2WorkspaceWindow(workspace)
    try:
        wait_for_inventory(window)
        first = window._selected_source()
        summary = window._document_summaries[first]
        window._document_summaries[first] = replace(summary, pending_activity_rows=0)
        window._next_document()
        wait_for_jobs(window._review_widget)
        assert window._selected_source() != first
        selected = window._selected_source()
        window._review_widget.batch.reason.setText("Keep this unrelated review draft")
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        window.review_document_selector.setCurrentIndex(window.review_document_selector.findData(first))
        assert window._selected_source() == selected
        assert window.review_document_selector.currentData() == selected
        assert window._review_widget.batch.reason.text() == "Keep this unrelated review draft"
    finally:
        cleanup(window)


def test_report_route_decline_preserves_unrelated_document_and_saved_entries(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    workspace = _populated_workspace(tmp_path)
    other = SOURCE.replace(b"Coffee", b"Tea")
    other_evidence = build_source_evidence(other, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(other, DEFINITION, other_evidence, suffix=".csv")
        store.bind_source_account(other_evidence.source_sha256, "Checking A", "opaque", "cash")
    window = V2WorkspaceWindow(workspace)
    try:
        wait_for_inventory(window)
        window.navigation.setCurrentRow(window.REVIEW)
        review = window._review_widget
        wait_for_jobs(review)
        current = window._selected_source()
        destination = next(source for source in window._document_summaries if source != current)
        review.batch.reason.setText("Keep this review in progress")
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        window._review_report_source(destination, "report-row")
        assert window._selected_source() == current
        assert window._review_widget is review
        assert review.batch.reason.text() == "Keep this review in progress"
        assert not window._report_review_target
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert len(store.source_ids()) == 2
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        cleanup(window)


def test_report_source_route_reveals_exact_reviewed_row_and_preserves_correction(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    workspace = _populated_workspace(tmp_path)
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    row_id = evidence.payload.rows[0].row_id
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
        store.post_reviewed_cash_category(row_id, "expense:food", purpose="expense", reason="Synthetic review")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    window = V2WorkspaceWindow(workspace)
    try:
        wait_for_inventory(window)
        window._show_document_spending()
        wait_for_reports(window._reports_view)
        assert window._reports_view.spending_report.total_minor == 400
        window._reports_view.source_review_requested.emit(evidence.source_sha256, row_id)
        review = window._review_widget
        wait_for_jobs(review)
        assert window.navigation.currentRow() == window.REVIEW
        assert review._current().row_id == row_id and review._current().entry_key is not None
        assert len(review.navigation.selected()) == 1 and review.category.isEnabled()
        assert review.navigation.status_filter.currentData() == "all"
        assert review.saved_review_note.isReadOnly()
        assert review.saved_review_note.toPlainText() == "Synthetic review"
        assert not review.reason.text() and not review.has_unsaved_draft
        assert not review.action_button.isEnabled() and not review.withdraw_button.isEnabled()
        assert "unsaved" not in review.status.text().lower()
        review.category.setCurrentIndex(review.category.findData("expense:travel"))
        assert not review.action_button.isEnabled()  # Saved context cannot authorize a new correction.
        review.reason.setText("Correct synthetic category")
        assert review.action_button.isEnabled(), review.status.text()
        review.action_button.click()
        wait_for_jobs(review)
        wait_for_inventory(window)
        assert review.saved_review_note.toPlainText() == "Correct synthetic category"
        assert not review.reason.text() and not review.has_unsaved_draft
        assert not review.action_button.isEnabled() and not review.withdraw_button.isEnabled()
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.connection.execute("SELECT COUNT(*) FROM JournalCorrections").fetchone() == (1,)
        window._back_to_report()
        wait_for_reports(window._reports_view)
        assert window._reports_view.start.date().toPython() == date(2026, 10, 1)
        assert window._reports_view.end.date().toPython() == date(2026, 10, 2)
        assert window._reports_view.spending_report.total_minor == 400
        totals = {row.category_id: row.amount_minor for row in window._reports_view.model.rows}
        assert totals == {"builtin:loan-interest": 0, "expense:food": 0, "expense:travel": 400}
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.connection.execute("SELECT COUNT(*) FROM JournalCorrections").fetchone() == (1,)
            assert len(store.source_ids()) == 1
    finally:
        cleanup(window)


def test_report_lender_route_opens_the_exact_owning_loan_event(tmp_path, monkeypatch):
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview

    from .test_v2_loan_payments import _post
    from .test_v2_loan_payments import _profile as loan_profile

    QApplication.instance() or QApplication([])
    profile = tmp_path / "lender.db"
    bank, rows = loan_profile(profile)
    with V2ProfileStore.open(profile) as store:
        event = _post(store, bank, rows)
        lender_source = store.loan_source_links()[0].source_sha256
    workspace = V2Workspace.open(
        profile, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json"
    )
    window = V2WorkspaceWindow(workspace)
    seen = []

    def inspect_owner(dialog):
        wait_for_jobs(dialog)
        seen.append(dialog.selected_event.event_id)
        assert dialog.tabs.tabText(dialog.tabs.currentIndex()) == "Saved event / history"
        assert "Posted payment" in dialog.status.text()
        assert dialog.selected_event.status == "active"
        assert not dialog.assumed_dates.isChecked()
        assert not dialog.confirm.isEnabled()
        assert dialog.preview is None
        dialog.reason.setText("Inspect withdrawal availability without confirming")
        assert dialog.withdraw.isEnabled()
        dialog.close()
        return 0

    monkeypatch.setattr(V2LoanPaymentReview, "exec", inspect_owner)
    try:
        wait_for_inventory(window)
        before = profile.read_bytes()
        window._review_report_source(lender_source, rows[0])
        review = window._review_widget
        wait_for_jobs(review)
        assert review._current().row_id == rows[0]
        assert "View" in review.action_button.text() and "loan" in review.action_button.text()
        assert review.action_button.isEnabled()
        review.action_button.click()
        wait_for_jobs(review)
        assert seen == [event.event_id]
        assert profile.read_bytes() == before
    finally:
        cleanup(window)

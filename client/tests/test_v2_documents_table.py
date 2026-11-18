"""Documents discovery uses typed sorting, source identity and guarded filtering."""

from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.v2_profile_store import DocumentSummary, FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_documents_table import DocumentFilters, DocumentsFilterBar, DocumentsTable
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QMessageBox

from .qt_journey_helpers import JourneyArtifacts, choose_combo, enter_text
from .test_v2_document_browser import _populated_workspace, wait_for_inventory
from .test_v2_reports_responsiveness import wait_for_reports
from .test_v2_workspace_window import DEFINITION, SOURCE
from .v2_institution_helpers import add_test_financial_account
from .v2_job_wait import wait_for_jobs


def summary(source, **changes):
    base = DocumentSummary(
        source,
        "pdf_citiaadvantage_201506",
        "statement",
        "citi",
        ("1234",),
        ("Everyday card",),
        date(2026, 10, 1),
        date(2026, 10, 31),
        "printed",
        "printed",
        10,
        10,
        0,
        False,
        True,
        associated_account_ids=("card",),
        association_complete=True,
    )
    return replace(base, **changes)


def test_sorting_uses_dates_counts_and_preserves_source_identity(qtbot):
    table = DocumentsTable()
    qtbot.addWidget(table)
    rows = (
        summary("unknown", start=None, end=None),
        summary("october", pending_activity_rows=2),
        summary("february", start=date(2026, 2, 1), end=date(2026, 2, 28)),
    )
    table.replace(rows, "october")
    assert table.visible_sources() == ("october", "february", "unknown")
    table.sortByColumn(2, Qt.AscendingOrder)
    assert table.visible_sources() == ("february", "october", "unknown")
    assert table.selected_source() == "october"
    table.sortByColumn(4, Qt.AscendingOrder)
    assert table.visible_sources()[0] == "october"  # 2 rows before 10, never lexical order.
    table.replace(tuple(reversed(rows)), "october")
    assert table.selected_source() == "october"
    assert table.horizontalHeader().sortIndicatorSection() == 4


def test_facets_match_all_account_associations_and_inclusive_period_overlap(qtbot):
    table, filters = DocumentsTable(), DocumentsFilterBar()
    qtbot.addWidget(table)
    qtbot.addWidget(filters)
    rows = (
        summary(
            "occu",
            institution_key="occu",
            associated_account_ids=("checking", "savings"),
            bound_account_names=("Household checking", "Emergency savings"),
        ),
        summary(
            "value",
            parser_id="pdf_vanguard401k_202006",
            institution_key="vanguard",
            pending_activity_rows=0,
            pending_summary_values=1,
        ),
        summary("unknown", start=None, end=None),
    )
    table.replace(rows)
    filters.set_options(rows)
    filters.changed.connect(table.documents_proxy.set_filters)
    filters.set_state(DocumentFilters(account="savings"), emit=True)
    assert table.visible_sources() == ("occu",)
    assert "Emergency savings" in table.model().index(0, 0).data()
    filters.set_state(DocumentFilters(start=date(2026, 10, 31), end=date(2026, 11, 1)), emit=True)
    assert set(table.visible_sources()) == {"occu", "value"}
    filters.set_state(DocumentFilters(review="value", institution="vanguard"), emit=True)
    assert table.visible_sources() == ("value",)
    filters.set_options(())
    assert filters.state().institution == "vanguard"  # Reload must not silently broaden a filter.
    assert filters.state().review == "value"
    filters.clear.click()
    assert not filters.state().active_count
    assert table.model().rowCount() == 3


def _multiple_workspace(tmp_path):
    workspace = _populated_workspace(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        add_test_financial_account(
            store,
            FinancialAccount(
                "savings", "Emergency savings for household and planned equipment replacement", "asset", "synthetic"
            ),
        )
        for month, text in (("09", b"Tea"), ("08", b"Lunch")):
            content = SOURCE.replace(b"10/01/2026", f"{month}/01/2026".encode()).replace(b"Coffee", text)
            evidence = build_source_evidence(content, DEFINITION, suffix=".csv")
            store.import_source(content, DEFINITION, evidence, suffix=".csv")
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "savings")
    return workspace


def test_filter_cancel_restores_draft_selection_and_controls_sort_reload_keeps_draft(tmp_path, qtbot, monkeypatch):
    window = V2WorkspaceWindow(_multiple_workspace(tmp_path))
    qtbot.addWidget(window)
    wait_for_inventory(window)
    source = window._selected_source()
    window.navigation.setCurrentRow(window.REVIEW)
    view = window._review_widget
    wait_for_jobs(view)
    view.batch.reason.setText("Unapplied review choice")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    window.document_search.setText("Emergency savings")
    assert window.document_search.text() == ""
    assert window._selected_source() == source and window._review_widget is view
    assert view.has_unsaved_draft
    window.sources.sortByColumn(0, Qt.DescendingOrder)
    window.refresh(select_source=source)
    wait_for_inventory(window)
    assert window._selected_source() == source and window._review_widget is view
    assert view.has_unsaved_draft
    assert window.sources.horizontalHeader().sortIndicatorSection() == 0
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    window.document_search.setText("no matching statement")
    assert window._selected_source() is None
    assert not window.review_document_button.isEnabled() and not window.preview_button.isEnabled()
    window.document_filters.clear.click()
    assert window._selected_source() == source
    assert window.review_document_button.property("formState") == "ready"
    window.close()


def test_explicit_report_handoff_reveals_filtered_source_and_keeps_report_dates(tmp_path, qtbot):
    window = V2WorkspaceWindow(_multiple_workspace(tmp_path))
    qtbot.addWidget(window)
    wait_for_inventory(window)
    source = window._selected_source()
    with V2ProfileStore.open(window.workspace.profile_path, read_only=True) as store:
        row = store.load_import(source).evidence.payload.rows[0].row_id
    window.document_search.setText("Emergency savings")
    assert source not in window.sources.visible_sources()
    window.navigation.setCurrentRow(window.REPORTS)
    reports = window._reports_view
    reports.start.setDate(QDate(2026, 8, 1))
    reports.end.setDate(QDate(2026, 11, 1))
    wait_for_reports(reports)
    window._review_report_source(source, row)
    wait_for_jobs(window._review_widget)
    qtbot.waitUntil(lambda: "Filters cleared" in window.status.text())
    assert window._selected_source() == source and not window.document_filters.state().active_count
    window._back_to_report()
    wait_for_reports(reports)
    assert window._reports_view is reports
    assert reports.start.date() == QDate(2026, 8, 1) and reports.end.date() == QDate(2026, 11, 1)
    window.close()


def test_initial_post_reveals_next_pending_outside_filter_and_completed_view_is_neutral(tmp_path, qtbot):
    from .test_v2_core_journey import cleanup
    from .test_v2_review_advance import prepared, save_staged, stage

    workspace, first, second = prepared(tmp_path)
    window = V2WorkspaceWindow(workspace)
    window.show()
    try:
        wait_for_inventory(window)
        window._select_review_source(first)
        window.document_search.setText("2026-10-01")
        assert window.sources.visible_sources() == (first,)
        window.navigation.setCurrentRow(window.REVIEW)
        review = window._review_widget
        wait_for_jobs(review)
        stage(review)
        save_staged(qtbot, review)
        qtbot.waitUntil(lambda: window._selected_source() == second, timeout=10000)
        wait_for_inventory(window)
        wait_for_jobs(window._review_widget)
        assert not window.document_filters.state().active_count
        assert "Filters cleared" in window.status.text()
        window._back_to_completed_statement()
        wait_for_jobs(window._review_widget)
        assert window._selected_source() == first
        assert window.review_document_button.text() == "View document"
        assert window.review_document_button.property("formState") == "neutral"
    finally:
        cleanup(window)


@pytest.mark.parametrize("size", [(1050, 700), (1100, 650), (1280, 800)])
def test_native_documents_table_discovery_keyboard_filters_and_review(tmp_path, qtbot, qapp, journey_artifacts, size):
    window = V2WorkspaceWindow(_multiple_workspace(tmp_path))
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    wait_for_inventory(window)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    artifacts.capture("01-documents-table", window)
    assert window.sources.model().rowCount() == 3
    assert window.sources.horizontalScrollBar().maximum() == 0
    header = window.sources.horizontalHeader()
    header.setFocus()
    qtbot.keyClick(header, Qt.Key_Home)
    qtbot.keyClick(header, Qt.Key_Space)
    assert header.sortIndicatorSection() == 0 and header.sortIndicatorOrder() == Qt.AscendingOrder
    qtbot.keyClick(header, Qt.Key_Space)
    assert header.sortIndicatorOrder() == Qt.DescendingOrder
    qtbot.mouseClick(window.document_filters.toggle, Qt.LeftButton)
    assert window.document_filters.panel.isVisible()
    choose_combo(qtbot, window.document_filters.account, "savings")
    assert window.sources.model().rowCount() == 2
    artifacts.capture("02-column-filters", window)
    enter_text(qtbot, window.document_search, "no such statement")
    assert not window.review_document_button.isEnabled()
    artifacts.capture("03-no-matching-documents", window)
    qtbot.mouseClick(window.document_filters.clear, Qt.LeftButton)
    assert window.sources.model().rowCount() == 3
    long_account_source = next(
        summary.source_sha256
        for summary in window._document_summaries.values()
        if "savings" in summary.associated_account_ids
    )
    assert window.sources.select_source(long_account_source)
    window.sources.setFocus()
    qtbot.keyClick(window.sources, Qt.Key_Return)
    wait_for_jobs(window._review_widget)
    assert window.navigation.currentRow() == window.REVIEW
    selected = window._document_summaries[window._selected_source()]
    assert window.review_period.isVisible()
    assert selected.start.isoformat() in window.review_period.text()
    assert selected.end.isoformat() in window.review_period.text()
    assert "derived" in window.review_period.text()
    artifacts.capture("04-keyboard-open-review", window)
    window.close()

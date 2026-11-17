"""Retirement summaries have a value-review journey, not blocked cash categorization."""

from datetime import date
from pathlib import Path
from threading import Event

import pytest
from parsetrail.core.v2_preferences import V2Preferences, save_preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_account_anchors import V2AccountAnchors
from parsetrail.gui.v2_statement_summary_review import V2StatementSummaryReview
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThread
from shiboken6 import isValid

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

from .qt_journey_helpers import JourneyArtifacts
from .test_v2_document_browser import wait_for_inventory
from .test_v2_reports_responsiveness import wait_for_reports
from .v2_institution_helpers import add_test_financial_account
from .v2_job_wait import wait_for_jobs


def prepared(tmp_path, *, bound=True, second=False):
    family = "fidelity-401k-summary-pilot-definition.json"
    case = next(item for item in family_sources() if item.definition_name == family)
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / family).read_bytes()
    path = tmp_path / "retirement.db"
    sources = []
    with V2ProfileStore.create(path) as store:
        add_test_financial_account(
            store,
            FinancialAccount(
                "retirement",
                "Workplace retirement savings · long account nickname",
                "asset",
                "fidelity",
                product_type="investment",
            ),
        )
        for index in range(2 if second else 1):
            raw = case.source + (b"\n% second synthetic source\n" if index else b"")
            evidence = build_source_evidence(raw, definition, suffix=".pdf")
            store.import_source(raw, definition, evidence, suffix=".pdf")
            if bound:
                section = evidence.payload.accounts[0]
                store.bind_source_account(
                    evidence.source_sha256, section.source_identity, section.source_identity_form, "retirement"
                )
            sources.append(evidence.source_sha256)
    preferences = tmp_path / "preferences.json"
    save_preferences(preferences, V2Preferences())
    return V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=preferences), sources


def dispose(qtbot, view):
    destroyed = []
    gui_thread = QThread.currentThread()
    view.destroyed.connect(lambda: destroyed.append(QThread.currentThread() == gui_thread))
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qtbot.waitUntil(lambda: not isValid(view))
    assert destroyed == [True]


@pytest.mark.parametrize("size", [(1050, 700), (1100, 650), (1280, 800)])
def test_pending_recorded_and_reopened_value_without_journals(qtbot, qapp, tmp_path, journey_artifacts, size):
    workspace, sources = prepared(tmp_path)
    source = sources[0]
    view = V2StatementSummaryReview(workspace, source)
    qtbot.addWidget(view)
    view.resize(*size)
    view.show()
    wait_for_jobs(view)
    assert view.action_button.text() == "Record statement value"
    assert view.action_button.isEnabled() and view.action_button.property("formState") == "ready"
    assert not view.has_unsaved_draft and view.details.height() < 50
    assert view.table.rowCount() == 4
    assert view.table.item(1, 0).text() == "Your Contributions"
    assert view.table.item(2, 0).text() == "Change in Market Value"
    assert "50.00" in view.table.item(1, 1).text() and "-" in view.table.item(2, 1).text()
    assert "140.00" in view.value.text() and "2026-01-31" in view.value.text()
    assert "individual transactions" in view.explanation.text()
    assert view.snapshot.independent_balance_verified and not view.snapshot.capture_verified
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.document_summaries()[0].pending_summary_values == 1
        original = store.load_import(source).evidence
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    artifacts.capture("01-pending-statement-value", view)
    completed = []
    view.initial_review_completed.connect(completed.append)
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    wait_for_jobs(view)
    assert completed == [source]
    assert view.snapshot.complete and "Review complete" in view.status.text()
    assert view.action_button.property("formState") == "neutral"
    assert view.action_button.text() == "View recorded value/history…"
    artifacts.capture("02-recorded-statement-value", view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        summary = store.document_summaries()[0]
        assert summary.pending_summary_values == 0 and summary.reviewed_summary_values == 1
        assert summary.pending_activity_rows == 0
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM UnresolvedTransferLegs").fetchone() == (0,)
        assert store.load_import(source).evidence == original
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
    dispose(qtbot, view)
    reopened = V2StatementSummaryReview(workspace, source)
    qtbot.addWidget(reopened)
    wait_for_jobs(reopened)
    assert reopened.snapshot.complete and not reopened.has_unsaved_draft
    dispose(qtbot, reopened)


def test_missing_account_and_value_conflict_have_meaningful_actions(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts
):
    workspace, sources = prepared(tmp_path, bound=False)
    source = sources[0]
    view = V2StatementSummaryReview(workspace, source)
    qtbot.addWidget(view)
    view.resize(1050, 700)
    view.show()
    wait_for_jobs(view)
    assert view.action_button.isEnabled() and view.action_button.text() == "Choose account…"
    chosen = []
    view.account_assignment_requested.connect(lambda: chosen.append(True))
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    assert chosen == [True]
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    artifacts.capture("03-account-required", view)
    with V2ProfileStore.open(workspace.profile_path) as store:
        section = store.load_import(source).evidence.payload.accounts[0]
        store.bind_source_account(source, section.source_identity, section.source_identity_form, "retirement")
        snapshot = store.account_anchor_snapshot("retirement")
        store.record_reviewed_dated_value(
            "retirement",
            amount_minor=15000,
            value_date=date(2026, 1, 31),
            tracking_scope="account_total",
            reference="Independent contradictory point",
            reason="Review conflict example",
            expected_basis_sha256=snapshot.basis_sha256,
        )
        snapshot = store.account_anchor_snapshot("retirement")
        store.record_reviewed_dated_value(
            "retirement",
            amount_minor=20000,
            value_date=date(2026, 2, 28),
            tracking_scope="account_total",
            reference="Later known value",
            reason="Later statement context must not hide January",
            expected_basis_sha256=snapshot.basis_sha256,
        )
    view.refresh()
    wait_for_jobs(view)
    assert view.action_button.text() == "Review conflicting values…" and not view.snapshot.complete
    anchors = []

    def inspect(dialog):
        anchors.append(dialog.account.currentData())
        assert dialog.tabs.currentIndex() == 1
        assert "150.00" in dialog.value_state.text() and "2026-01-31" in dialog.value_state.text()
        assert "2026-01-31" in dialog.books.text()
        selected = dialog._selected(dialog.value_history, dialog.snapshot.dated_values)
        assert selected.amount_minor == 15000 and selected.value_date == date(2026, 1, 31)
        assert dialog.value_amount.text() == ""
        return 0

    monkeypatch.setattr(V2AccountAnchors, "exec", inspect)
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    wait_for_jobs(view)
    assert anchors == ["retirement"]
    artifacts.capture("04-value-conflict", view)
    dispose(qtbot, view)


def test_withdrawal_and_failed_reload_do_not_leave_false_completion(qtbot, tmp_path, monkeypatch):
    workspace, sources = prepared(tmp_path)
    view = V2StatementSummaryReview(workspace, sources[0])
    qtbot.addWidget(view)
    wait_for_jobs(view)
    view.action_button.click()
    wait_for_jobs(view)
    with V2ProfileStore.open(workspace.profile_path) as store:
        snapshot = store.account_anchor_snapshot("retirement")
        value = snapshot.dated_values[0]
        store.withdraw_reviewed_dated_value(
            "retirement",
            value.value_id,
            expected_value_version=value.version,
            expected_basis_sha256=snapshot.basis_sha256,
            reason="Withdraw value before fresh review",
        )
    view.refresh()
    wait_for_jobs(view)
    assert not view.snapshot.complete and view.action_button.text() == "Record statement value"
    with monkeypatch.context() as patch:
        patch.setattr(
            V2ProfileStore, "statement_summary_snapshot", lambda *_: (_ for _ in ()).throw(ValueError("unavailable"))
        )
        view.refresh()
        wait_for_jobs(view)
        assert view.snapshot is None and not view.action_button.isEnabled()
    view.refresh()
    wait_for_jobs(view)
    assert view.action_button.isEnabled()
    dispose(qtbot, view)


def test_workspace_routes_pending_values_and_advances_after_explicit_record(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, sources = prepared(tmp_path, second=True)
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.resize(1050, 700)
    window.show()
    wait_for_inventory(window)
    assert all(summary.pending_summary_values for summary in window._document_summaries.values())
    window._select_review_source(sources[0])
    window.navigation.setCurrentRow(window.REVIEW)
    view = window._review_widget
    assert isinstance(view, V2StatementSummaryReview)
    wait_for_jobs(view)
    assert not window.cash_review_button.isVisible()
    assert "statement value" in window.review_context.text().casefold()
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("05-integrated-summary-review", window)
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._selected_source() == sources[1], timeout=20000)
    wait_for_inventory(window)
    wait_for_jobs(window._review_widget)
    assert isinstance(window._review_widget, V2StatementSummaryReview)
    assert window._review_widget.action_button.text() == "Record statement value"
    assert "Now reviewing" in window.review_completion.text()
    assert "posted" not in window.review_completion.text().casefold()
    dispose(qtbot, window)


def test_stale_value_needs_fresh_click_and_confirmed_write_finishes_before_close(qtbot, tmp_path, monkeypatch):
    workspace, sources = prepared(tmp_path)
    view = V2StatementSummaryReview(workspace, sources[0])
    qtbot.addWidget(view)
    wait_for_jobs(view)
    with V2ProfileStore.open(workspace.profile_path) as store:
        add_test_financial_account(
            store, FinancialAccount("other", "A newly added account", "asset", "fidelity", product_type="savings")
        )
    view.action_button.click()
    wait_for_jobs(view)
    assert not view.snapshot.complete and view.action_button.isEnabled()
    assert "fresh confirmation" in view.status.text()
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (0,)
    entered, release = Event(), Event()
    original = V2ProfileStore.record_reviewed_source_value

    def wait_for_release(store, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(store, *args, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "record_reviewed_source_value", wait_for_release)
    view.action_button.click()
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
        assert view.jobs.writing and not view.request_cancel()
        assert not view.action_button.isEnabled()
    finally:
        release.set()
    wait_for_jobs(view)
    assert view.snapshot.complete and view.action_button.property("formState") == "neutral"
    dispose(qtbot, view)


def test_required_details_explain_disabled_action_and_restore_primary(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, sources = prepared(tmp_path)
    view = V2StatementSummaryReview(workspace, sources[0])
    qtbot.addWidget(view)
    view.resize(1050, 700)
    view.show()
    wait_for_jobs(view)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    original_reference = view.reference.text()
    for index, field in enumerate((view.reference, view.reason)):
        qtbot.mouseClick(view.details.button, Qt.LeftButton)
        field.setFocus()
        qtbot.keyClick(field, Qt.Key_A, Qt.ControlModifier)
        qtbot.keyClick(field, Qt.Key_Backspace)
        qtbot.mouseClick(view.details.button, Qt.LeftButton)
        qapp.processEvents()
        assert field.property("formState") == "required"
        assert not view.action_button.isEnabled() and "Show details" in view.status.text()
        artifacts.capture(f"08-required-review-field-{index}", view)
        field.setText(original_reference if field is view.reference else "Initial Review")
        assert field.property("formState") == "ready"
        assert view.action_button.isEnabled() and view.action_button.property("formState") == "ready"
    dispose(qtbot, view)


def test_value_report_uses_statement_account_and_date_without_changing_budget(
    qtbot, qapp, tmp_path, journey_artifacts, monkeypatch
):
    workspace, sources = prepared(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        add_test_financial_account(
            store, FinancialAccount("aaa", "AAA other account", "asset", "fidelity", product_type="savings")
        )
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.resize(1050, 700)
    window.show()
    wait_for_inventory(window)
    reports = window._ensure_report_view(window.REPORTS)
    reports.show_account_value("aaa", date(2026, 3, 31))
    wait_for_reports(reports)
    reports.set_budget_month(date(2026, 7, 1))
    reports.set_period(date(2025, 3, 1), date(2025, 4, 1))
    wait_for_reports(reports)
    budget_month = reports.budget_month.date()
    start, end = reports.start.date(), reports.end.date()
    window._select_review_source(sources[0])
    window.navigation.setCurrentRow(window.REVIEW)
    view = window._review_widget
    wait_for_jobs(view)
    assert window.document_spending_button.text() == "View account value"
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    artifacts.capture("06-integrated-value-action", window)
    view.action_button.click()
    wait_for_jobs(view)
    wait_for_inventory(window)
    qtbot.mouseClick(window.document_spending_button, Qt.LeftButton)
    wait_for_reports(reports)
    assert window.navigation.currentRow() == window.REPORTS and reports.tabs.currentIndex() == 4
    assert reports.as_of.date().toPython() == date(2026, 1, 31)
    selected = reports.positions_model.rows[reports.positions_table.currentIndex().row()]
    assert selected.account_id == "retirement" and selected.latest_dated_value.amount_minor == 14000
    assert selected.position_debit_minor is None
    assert not reports.positions_table.isColumnHidden(12)
    value_index = reports.positions_model.index(reports.positions_table.currentIndex().row(), 12)
    assert "140.00" in reports.positions_model.data(value_index)
    assert "2026-01-31" in reports.positions_model.data(value_index)
    assert "source" in reports.positions_model.data(value_index)
    assert reports.positions_table.visualRect(value_index).right() <= reports.positions_table.viewport().width()
    assert reports.budget_month.date() == budget_month
    assert (reports.start.date(), reports.end.date()) == (start, end)
    artifacts.capture("07-statement-account-value-report", window)
    opened = []

    def inspect(dialog):
        opened.append(dialog)
        assert dialog._as_of == date(2026, 1, 31)
        assert "2026-01-31" in dialog.books.text()
        return 0

    monkeypatch.setattr(V2AccountAnchors, "exec", inspect)
    reports._open_selected_account_review("values")
    wait_for_reports(reports)
    assert len(opened) == 1
    dispose(qtbot, window)

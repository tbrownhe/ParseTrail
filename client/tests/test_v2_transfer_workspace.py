"""Relationship resolution uses posted sides without creating another payment."""

from datetime import date

import pytest
from parsetrail.core.v2_preferences import save_preferences
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview
from parsetrail.gui.v2_report_drilldown import V2ReviewedEntryDrilldown
from parsetrail.gui.v2_transfer_workspace import V2TransferWorkspace
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from .qt_journey_helpers import JourneyArtifacts, ModalSteps
from .test_v2_document_browser import wait_for_inventory
from .test_v2_loan_payments import PREFERENCES, _post, _profile
from .v2_job_wait import wait_for_jobs


def prepared(tmp_path, *, posted_bank):
    path = tmp_path / "resolution.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        loan = _post(store, None, rows)
        if posted_bank:
            snapshot = store.resolution_snapshot(preferences=PREFERENCES)
            store.post_unresolved_transfer(
                bank,
                preferences=PREFERENCES,
                expected_basis_sha256=snapshot.basis_sha256,
                reason="Bank transfer reviewed",
            )
    prefs = tmp_path / "prefs.json"
    save_preferences(prefs, PREFERENCES)
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=prefs)
    return workspace, loan, bank


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050", "1280"])
def test_two_posted_sides_match_link_only_and_withdraw_without_new_money(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts, size
):
    workspace, loan, _bank = prepared(tmp_path, posted_bank=True)
    view = V2TransferWorkspace(workspace)
    qtbot.addWidget(view)
    view.resize(*size)
    view.show()
    wait_for_jobs(view)
    assert view.table.rowCount() == 2
    view.table.selectRow(next(i for i, item in enumerate(view._visible) if item.id == loan.event_id))
    assert view.counterpart.count() == 2 and not view.match_button.isEnabled()
    view.counterpart.setCurrentIndex(1)
    assert view.match_button.isEnabled()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    artifacts.capture("01-two-posted-sides", view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        count = store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone()[0]
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    qtbot.mouseClick(view.match_button, Qt.LeftButton)
    assert view.table.rowCount() == 2
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    qtbot.mouseClick(view.match_button, Qt.LeftButton)
    wait_for_jobs(view)
    assert view.table.rowCount() == 0
    view.filter.setCurrentIndex(1)
    assert view.table.rowCount() == 2
    assert "Matched:" in view.saved_context.text() and "Initial Review" in view.saved_context.text()
    assert "assumed" in view.saved_context.text() and view.counterpart_source.isEnabled()
    view.focus_row(view._current().row_ids[0])
    assert view.filter.currentData() == "matched"
    artifacts.capture("02-saved-matched-relationship", view)
    assert not view.withdraw_button.isEnabled()
    qtbot.mouseClick(view.corrections, Qt.LeftButton)
    view.correction_reason.setText("The two sources are different payments")
    assert view.withdraw_button.isEnabled()
    qtbot.mouseClick(view.withdraw_button, Qt.LeftButton)
    wait_for_jobs(view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone()[0] == count
        assert all(
            item.status == "unmatched"
            for item in store.resolution_snapshot(preferences=PREFERENCES).items
            if not item.id.startswith("row:")
        )
    assert view.shutdown()


def test_unreviewed_source_requires_separate_manual_choice(qtbot, tmp_path, monkeypatch):
    workspace, _loan, _bank = prepared(tmp_path, posted_bank=False)
    view = V2TransferWorkspace(workspace)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    assert view.table.rowCount() == 1 and view.counterpart.count() == 1
    qtbot.mouseClick(view.manual_candidates_button, Qt.LeftButton)
    assert view.counterpart.count() == 2 and "manual" in view.counterpart.itemText(1)
    view.counterpart.setCurrentIndex(1)
    confirmations = []

    def confirm(_parent, _title, text):
        confirmations.append(text)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    qtbot.mouseClick(view.match_button, Qt.LeftButton)
    wait_for_jobs(view)
    assert "Manual selection" in confirmations[0]
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store._active_journal_entries()) == 2
        assert (
            len([link for link in store.resolution_snapshot(preferences=PREFERENCES).links if link.status == "active"])
            == 1
        )
    assert view.shutdown()


def test_lender_only_interest_drilldown_retains_loan_source_without_bank(qtbot, tmp_path):
    workspace, _loan, _bank = prepared(tmp_path, posted_bank=False)
    before = workspace.profile_path.read_bytes()
    dialog = V2ReviewedEntryDrilldown(
        workspace.profile_path, "builtin:loan-interest", start=date(2026, 1, 1), end=date(2026, 2, 1)
    )
    qtbot.addWidget(dialog)
    assert dialog.model.rowCount() == 1
    assert "lender-side" in dialog.details.toPlainText()
    assert "Transfers" in dialog.details.toPlainText()
    assert dialog.source.count() == 1
    assert workspace.profile_path.read_bytes() == before
    dialog.close()


def test_workspace_menu_reflects_date_preference_changed_by_child_review(qtbot, tmp_path):
    workspace, _loan, _bank = prepared(tmp_path, posted_bank=False)
    workspace.set_allow_assumed_posting_dates(False)
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    wait_for_inventory(window)
    assert not window.assumed_posting_action.isChecked()
    workspace.set_allow_assumed_posting_dates(True)
    window.refresh()
    wait_for_inventory(window)
    assert window.assumed_posting_action.isChecked()
    assert workspace.preferences().allow_assumed_posting_dates
    window.close()


@pytest.mark.parametrize("posted_bank", [True, False], ids=["link-only", "missing-bank-leg"])
def test_confirmation_explains_exact_posting_effects(qtbot, qapp, tmp_path, journey_artifacts, posted_bank):
    workspace, _loan, _bank = prepared(tmp_path, posted_bank=posted_bank)
    view = V2TransferWorkspace(workspace)
    qtbot.addWidget(view)
    view.resize(1050, 700)
    view.show()
    wait_for_jobs(view)
    if not posted_bank:
        qtbot.mouseClick(view.manual_candidates_button, Qt.LeftButton)
    view.counterpart.setCurrentIndex(1)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    modals = ModalSteps(qtbot)

    def inspect(message):
        assert "2026-01-14" in message.text() and "2026-01-15" in message.text()
        assert "Already posted" in message.text()
        assert ("No new financial entries" if posted_bank else "Post $220.00 outgoing") in message.text()
        if not posted_bank:
            assert "Manual selection" in message.text()
        artifacts.capture("exact-match-confirmation", message)
        qtbot.mouseClick(message.button(QMessageBox.No), Qt.LeftButton)

    modals.arm((QMessageBox, inspect))
    qtbot.mouseClick(view.match_button, Qt.LeftButton)
    modals.finish()
    assert view.shutdown()


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050", "1280"])
def test_loan_dialog_handoff_closes_modal_and_opens_focused_transfer_workspace(
    qtbot, qapp, tmp_path, journey_artifacts, size
):
    workspace, loan, _bank = prepared(tmp_path, posted_bank=False)
    source, row = loan.manifest.components[0].source_sha256, loan.manifest.components[0].row_id
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    wait_for_inventory(window)
    assert [window.navigation.item(i).text() for i in range(window.navigation.count())] == [
        "Documents",
        "Accounts",
        "Review",
        "Transfers",
        "Budget",
        "Reports",
    ]
    window._review_report_source(source, row)
    wait_for_jobs(window._review_widget)
    modals = ModalSteps(qtbot)

    def resolve(dialog):
        wait_for_jobs(dialog)
        assert dialog.resolve_button.isVisible() and dialog.resolve_button.isEnabled()
        qtbot.mouseClick(dialog.resolve_button, Qt.LeftButton)

    modals.arm((V2LoanPaymentReview, resolve))
    qtbot.mouseClick(window._review_widget.action_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: window.navigation.currentRow() == window.TRANSFERS)
    wait_for_jobs(window._transfers_view)
    assert row in window._transfers_view._current().row_ids
    assert qapp.activeModalWidget() is None
    transfer_filter = window._transfers_view.filter.currentData()
    qtbot.mouseClick(window._transfers_view.source_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.navigation.currentRow() == window.REVIEW)
    wait_for_jobs(window._review_widget)
    assert "transfer's source row" in window.status.text()
    assert window.back_to_report_button.text() == "Back to transfers"
    qtbot.mouseClick(window.back_to_report_button, Qt.LeftButton)
    wait_for_jobs(window._transfers_view)
    assert row in window._transfers_view._current().row_ids
    assert window._transfers_view.filter.currentData() == transfer_filter
    JourneyArtifacts(journey_artifacts, qapp, size).capture("integrated-transfer-handoff", window)
    window.close()

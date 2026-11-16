"""Funding and signed card transfers join the separate relationship workflow."""

from parsetrail.core.v2_preferences import save_preferences
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from .qt_journey_helpers import JourneyArtifacts
from .test_v2_core_journey import cleanup
from .test_v2_document_browser import wait_for_inventory
from .test_v2_flexible_funding import deposit, funding, signed_card_profile
from .test_v2_loan_payments import PREFERENCES
from .test_v2_origination import origination_profile
from .test_v2_review_advance import save_staged
from .v2_job_wait import wait_for_jobs


def workspace_for(path, tmp_path):
    prefs = tmp_path / "prefs.json"
    save_preferences(prefs, PREFERENCES)
    return V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=prefs)


def test_negative_card_transfer_is_selectable_and_posts_without_expense(qtbot, qapp, tmp_path, journey_artifacts):
    path = tmp_path / "cards.db"
    _incoming, evidence = signed_card_profile(path)
    workspace = workspace_for(path, tmp_path)
    view = V2CardPurchaseReview(workspace, evidence.source_sha256)
    qtbot.addWidget(view)
    view.resize(1050, 700)
    view.show()
    wait_for_jobs(view)
    negative = next(i for i, row in enumerate(view.model.rows) if row.amount_minor < 0)
    view.table.selectRow(negative)
    assert view.purpose.findData("transfer") >= 0
    view.purpose.setCurrentIndex(view.purpose.findData("transfer"))
    view.batch.stage_button.click()
    assert len(view.batch.staged) == 1
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("negative-card-transfer-staged", view)
    save_staged(qtbot, view)
    with V2ProfileStore.open(path, read_only=True) as store:
        entries = store._active_journal_entries()
        assert len(entries) == 1
        assert {posting.account_id for posting in entries[0].postings} == {"new", "internal:transfer-clearing:USD"}
    assert view.request_cancel()
    view.close()


def test_funding_expectation_matches_actual_receipt_and_returns_to_source(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts
):
    path = tmp_path / "funding.db"
    _bank, row = origination_profile(path)
    with V2ProfileStore.open(path) as store:
        event = store.post_loan_origination(funding(store, row, destination_account_id="bank"))
        deposit(store)
    workspace = workspace_for(path, tmp_path)
    window = V2WorkspaceWindow(workspace)
    window.resize(1280, 800)
    window.show()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    try:
        wait_for_inventory(window)
        window._open_transfers(row)
        view = window._transfers_view
        wait_for_jobs(view)
        assert view._current().id == event.event_id
        assert "Expected destination:" in view.saved_context.text()
        assert "Full acquisition cost is unknown" in view.saved_context.text()
        view.corrections.setChecked(True)
        view.correction_reason.setText("Inspect source first")
        assert not view.withdraw_posting_button.isVisible()
        view.manual_candidates_button.click()
        view.counterpart.setCurrentIndex(1)
        confirmations = []

        def confirm(_parent, _title, text):
            confirmations.append(text)
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", confirm)
        qtbot.mouseClick(view.match_button, Qt.LeftButton)
        wait_for_jobs(view)
        assert "assumed" in confirmations[0] and "Already posted" in confirmations[0]
        view.filter.setCurrentIndex(view.filter.findData("matched"))
        view.focus_row(row)
        assert view._current().kind == "origination" and view.counterpart_source.isEnabled()
        JourneyArtifacts(journey_artifacts, qapp, (1280, 800)).capture("financing-matched", window)
        view.source_button.click()
        wait_for_jobs(window._review_widget)
        assert window.navigation.currentRow() == window.REVIEW
        assert window._review_source_id == event.source_sha256
        assert window.back_to_report_button.text() == "Back to transfers"
        window.back_to_report_button.click()
        wait_for_jobs(view)
        assert window.navigation.currentRow() == window.TRANSFERS
        assert view._current().id == event.event_id and view.filter.currentData() == "matched"
    finally:
        cleanup(window)

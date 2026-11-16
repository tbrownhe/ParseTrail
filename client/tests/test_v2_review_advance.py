"""Advance only a completed initial review, preserving explicit return contexts."""

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox

from .qt_journey_helpers import JourneyArtifacts, ModalSteps
from .test_v2_core_journey import cleanup
from .test_v2_document_browser import _populated_workspace, wait_for_inventory
from .test_v2_workspace_window import DEFINITION, SOURCE
from .v2_job_wait import wait_for_jobs


def prepared(tmp_path):
    workspace = _populated_workspace(tmp_path)
    second = SOURCE.replace(b"10/01/2026", b"10/02/2026").replace(b"Coffee", b"Tea").replace(b"-$4.00", b"-$6.00")
    evidence = build_source_evidence(second, DEFINITION, suffix=".csv")
    first = build_source_evidence(SOURCE, DEFINITION, suffix=".csv").source_sha256
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_category_account("expense:food", "Food", "expense")
        store.import_source(second, DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
    return workspace, first, evidence.source_sha256


def save_staged(qtbot, view, *, accept=True):
    steps = ModalSteps(qtbot)

    def confirm(dialog):
        buttons = dialog.findChild(QDialogButtonBox)
        if accept:
            next(
                button for button in buttons.buttons() if buttons.buttonRole(button) == QDialogButtonBox.AcceptRole
            ).click()
        else:
            buttons.button(QDialogButtonBox.Cancel).click()

    steps.arm((QDialog, confirm))
    view.batch.preview_button.click()
    steps.finish()
    wait_for_jobs(view)


def stage(view, *, transfer=False):
    view.table.selectRow(0)
    view.purpose.setCurrentIndex(view.purpose.findData("transfer" if transfer else "expense"))
    if not transfer:
        view.category.setCurrentIndex(view.category.findData("expense:food"))
    view.batch.stage_button.click()
    assert len(view.batch.staged) == 1


@pytest.mark.parametrize("transfer", [False, True], ids=["expense", "transfer"])
def test_initial_post_advances_and_back_keeps_completed_source(qtbot, qapp, tmp_path, journey_artifacts, transfer):
    workspace, first, second = prepared(tmp_path)
    window = V2WorkspaceWindow(workspace)
    window.resize(1280, 800)
    window.show()
    try:
        wait_for_inventory(window)
        window._select_review_source(first)
        window.navigation.setCurrentRow(window.REVIEW)
        review = window._review_widget
        wait_for_jobs(review)
        stage(review, transfer=transfer)
        save_staged(qtbot, review)
        qtbot.waitUntil(lambda: window._selected_source() == second, timeout=10000)
        wait_for_inventory(window)
        wait_for_jobs(window._review_widget)
        assert "Initial review complete" in window.review_completion.text()
        assert "Now reviewing" in window.review_completion.text()
        assert "2026-10-01" in window.review_completion.text() and "2026-10-02" in window.review_completion.text()
        assert window.previous_document_button.isVisible()
        if transfer:
            with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
                assert any(
                    item.status == "unmatched"
                    for item in store.resolution_snapshot(preferences=workspace.preferences()).items
                )
        JourneyArtifacts(journey_artifacts, qapp, (1280, 800)).capture("review-advanced", window)
        qtbot.mouseClick(window.previous_document_button, Qt.LeftButton)
        wait_for_jobs(window._review_widget)
        assert window._selected_source() == first
        assert not window._needs_attention(window._document_summaries[first])
    finally:
        cleanup(window)


@pytest.mark.parametrize("context", ["cancel", "refresh", "report", "transfers"])
def test_cancel_refresh_and_source_return_do_not_advance(qtbot, tmp_path, monkeypatch, context):
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    workspace, first, _second = prepared(tmp_path)
    window = V2WorkspaceWindow(workspace)
    window.show()
    try:
        wait_for_inventory(window)
        window._select_review_source(first)
        window.navigation.setCurrentRow(window.REVIEW)
        review = window._review_widget
        wait_for_jobs(review)
        if context in {"report", "transfers"}:
            window._report_review_target = (first, review.model.rows[0].row_id)
            if context == "transfers":
                window._transfer_return_row = review.model.rows[0].row_id
        if context == "refresh":
            review.changed.emit()
        else:
            stage(review)
            save_staged(qtbot, review, accept=context != "cancel")
        wait_for_inventory(window)
        wait_for_jobs(review)
        assert window._selected_source() == first
        assert window._initial_post_pending is None
        assert window.review_completion.isHidden()
    finally:
        cleanup(window)

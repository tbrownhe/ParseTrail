"""One staging route shows exact captured choices and preserves local recovery."""

import gc
from datetime import date

import pytest
import shiboken6
from parsetrail.core.v2_profile_store import V2ProfileStore
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit

from .qt_journey_helpers import JourneyArtifacts, ModalSteps, choose_combo, enter_text
from .test_v2_multirow_review import choices, select, workspace_rows
from .test_v2_review_cues import open_review


def marker(view, text):
    number = next(i for i, row in enumerate(view.model.rows) if row.description == text)
    return view.model.data(view.model.index(number, view.model.columnCount() - 1))


def journals(workspace):
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        return store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone()[0]


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)])
def test_single_staging_route_visible_state_edit_remove_filter_cancel_and_exact_post(
    qtbot, qapp, tmp_path, journey_artifacts, size
):
    workspace, evidence, _ = workspace_rows(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_category_account("expense:travel", "Travel", "expense")
    window, view = open_review(qtbot, workspace, size=size)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    modals = ModalSteps(qtbot)
    transient_previews = []
    select(qtbot, view, "Coffee")
    choices(qtbot, view)
    assert view.batch.reason is view.reason
    assert view.batch.stage_button.isEnabled()
    assert not view.action_button.isVisible() and not view.action_button.isEnabled()
    assert view.table.horizontalHeader().visualIndex(view.model.columnCount() - 1) == 0
    assert marker(view, "Coffee") == marker(view, "Tea") == "Not staged"
    view.action_button.setEnabled(True)  # Simulate a stale shortcut/control state.
    view._act()
    view._update_review_actions()
    assert journals(workspace) == 0  # A stale direct handler cannot bypass staging.
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert marker(view, "Coffee") == "Staged · not saved"
    assert marker(view, "Tea") == "Not staged"
    coffee = next(row for row in view.model.rows if row.description == "Coffee")
    index = view.model.index(view.model.rows.index(coffee), view.model.columnCount() - 1)
    assert view.model.data(index, Qt.BackgroundRole) is not None
    assert view.model.data(index, Qt.FontRole).bold()
    assert "Food" in view.model.data(index, Qt.ToolTipRole)
    artifacts.capture("01-one-staged-visible-next-to-unstaged", window)

    select(qtbot, view, "Tea")
    choices(qtbot, view)
    enter_text(qtbot, view.reason, "Checked both purchases against original")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    original_tea = next(value for value in view.batch.staged.values() if value.row_id != coffee.row_id)
    choose_combo(qtbot, view.category, "expense:travel")
    enter_text(qtbot, view.reason, "An edited note which is not staged")
    assert marker(view, "Tea") == "Staged · changes not staged"
    assert "Changes not staged" in view.status.text()
    assert view.batch.staged[original_tea.row_id].category_id == "expense:food"
    assert view.batch.note() == "Checked both purchases against original"
    artifacts.capture("02-current-edits-distinct-from-staged-proposals", window)

    def reject(dialog):
        transient_previews.append(dialog)
        details = dialog.findChild(QPlainTextEdit).toPlainText()
        assert "Tea" in details and "Coffee" in details
        assert "Food" in details and "Travel" not in details
        assert "Checked both purchases" in details and "An edited note" not in details
        artifacts.capture("03-cancel-exact-staged-preview", dialog)
        qtbot.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel), Qt.LeftButton)

    modals.arm((QDialog, reject))
    qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending)
    dismissed = transient_previews.pop()
    qtbot.waitUntil(lambda preview=dismissed: not shiboken6.isValid(preview))
    del dismissed
    gc.collect()  # Normal collection must be safe after dismissed modal teardown.
    assert len(view.batch.staged) == 2 and journals(workspace) == 0
    assert view.reason.text() == "An edited note which is not staged"
    qtbot.mouseClick(view.batch.remove_button, Qt.LeftButton)
    assert set(view.batch.staged) == {coffee.row_id}
    assert marker(view, "Tea") == "Not staged"
    assert view.category.currentData() == "expense:travel"
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert marker(view, "Tea") == "Staged · not saved"
    assert len(view.batch.staged) == 2
    enter_text(qtbot, view.navigation.search, "Coffee")
    assert "1 hidden" in view.batch.summary.text()
    assert not view.navigation.next_button.isEnabled()  # Every visible row is already staged.
    assert "all" in view.batch.summary.toolTip().lower()
    artifacts.capture("04-hidden-stage-still-in-confirmation-scope", window)
    qtbot.keyClick(view.navigation.search, Qt.Key_A, Qt.ControlModifier)
    qtbot.keyClick(view.navigation.search, Qt.Key_Backspace)

    # An old Food draft must not label a newly captured Travel choice as changed.
    select(qtbot, view, "Coffee")
    choose_combo(qtbot, view.category, "expense:travel")
    enter_text(qtbot, view.reason, "Restaged chosen category")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert marker(view, "Coffee") == "Staged · not saved"
    select(qtbot, view, "Snack")
    choices(qtbot, view)
    note = view.reason.text()
    qtbot.mouseClick(view.batch.clear_button, Qt.LeftButton)
    assert not view.batch.staged and marker(view, "Coffee") == "Not staged"
    assert view.reason.text() == note and view.category.currentData() == "expense:food"
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert len(view.batch.staged) == 1
    qtbot.mouseClick(view.navigation.next_button, Qt.LeftButton)
    assert view._current().description != "Snack"

    def accept(dialog):
        transient_previews.append(dialog)
        details = dialog.findChild(QPlainTextEdit).toPlainText()
        assert "Snack" in details and "Coffee" not in details and "Tea" not in details
        button = next(
            button
            for button in dialog.findChild(QDialogButtonBox).buttons()
            if button.text().startswith("Confirm and post")
        )
        qtbot.mouseClick(button, Qt.LeftButton)

    modals.arm((QDialog, accept))
    qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending and not window.inventory_pending, timeout=15000)
    dismissed = transient_previews.pop()
    qtbot.waitUntil(lambda preview=dismissed: not shiboken6.isValid(preview))
    del dismissed
    gc.collect()
    assert not view.batch.staged and journals(workspace) == 1
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 100
        )
        assert store.load_import(evidence.source_sha256).evidence == evidence
    select(qtbot, view, "Coffee")
    assert marker(view, "Coffee") == "Not staged"
    view.navigation.status_filter.setCurrentIndex(view.navigation.status_filter.findData("all"))
    select(qtbot, view, "Snack")
    assert view.action_button.isVisible() and not view.batch.stage_button.isVisible()
    assert marker(view, "Snack").startswith("Reviewed")
    artifacts.capture("05-saved-review-separate-from-unstaged", window)


def test_common_staged_choices_restore_after_filter_preview_cancel_without_false_changes(
    qtbot, qapp, tmp_path, journey_artifacts
):
    workspace, _evidence, _raw = workspace_rows(tmp_path)
    window, view = open_review(qtbot, workspace)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    select(qtbot, view, "Coffee")
    select(qtbot, view, "Tea", Qt.ControlModifier)
    choices(qtbot, view)
    note = view.reason.text()
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert marker(view, "Coffee") == marker(view, "Tea") == "Staged · not saved"
    enter_text(qtbot, view.navigation.search, "Deposit")
    assert "2 hidden" in view.batch.summary.text()
    modals = ModalSteps(qtbot)
    modals.arm(
        (
            QDialog,
            lambda dialog: qtbot.mouseClick(
                dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel), Qt.LeftButton
            ),
        )
    )
    qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending)
    enter_text(qtbot, view.navigation.search, "Tea")
    select(qtbot, view, "Tea")
    assert view.purpose.currentData() == "expense" and view.category.currentData() == "expense:food"
    assert view.reason.text() == note
    assert marker(view, "Coffee") == marker(view, "Tea") == "Staged · not saved"
    qtbot.mouseClick(view.batch.remove_button, Qt.LeftButton)
    assert marker(view, "Tea") == "Not staged" and marker(view, "Coffee") == "Staged · not saved"
    assert "2 staged" not in view.operation_status.text()
    assert journals(workspace) == 0
    artifacts.capture("06-common-stage-filter-cancel-restores-captured-proposal", window)
    enter_text(qtbot, view.navigation.search, "Coffee")
    select(qtbot, view, "Coffee")
    assert "Staged" in view.status.text()
    qtbot.mouseClick(view.batch.clear_button, Qt.LeftButton)
    assert not view.batch.staged and marker(view, "Coffee") == "Not staged"
    assert view.status.text().startswith("Ready to stage")
    assert "2 staged" not in view.operation_status.text()
    assert view.category.currentData() == "expense:food" and view.reason.text() == note

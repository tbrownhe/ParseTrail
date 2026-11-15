"""A possible-repeat block provides a contextual route without bypassing review."""

from dataclasses import replace

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from .ordinary_staging_helpers import review_reason
from .qt_journey_helpers import JourneyArtifacts, ModalSteps, choose_combo, close_dialog, enter_text
from .test_v2_multirow_review import choices, select, workspace_rows
from .test_v2_review_cues import open_review
from .test_v2_source_overlap import setup, source
from .test_v2_wider_source_matching import decide, row


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)])
@pytest.mark.parametrize("decision", ["distinct", "supporting"])
def test_contextual_repeat_review_cancel_then_distinct_retains_staged_work(
    qtbot, qapp, tmp_path, journey_artifacts, size, decision
):
    workspace, original, raw = workspace_rows(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        other = source(store, "Second export of coffee")
    window, view = open_review(qtbot, workspace, size=size)
    choose_combo(qtbot, window.review_document_selector, original.source_sha256)
    qtbot.waitUntil(lambda: not window.inventory_pending and not window._review_widget.review_pending, timeout=15000)
    view = window._review_widget
    select(qtbot, view, "Tea")
    assert view._current().description == "Tea", view._current()
    assert view._current().status == "Ready for purpose review", view._current()
    choices(qtbot, view)
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    staged, note = dict(view.batch.staged), view.batch.note()
    select(qtbot, view, "Coffee")
    focused = view._current().row_id
    assert "Possible repeat in another document" in view.status.text()
    assert "choose a purpose" not in view.status.text()
    assert not view.purpose.isEnabled() and not view.action_button.isVisible()
    assert view.repeat_review_button.isVisible() and view.repeat_review_button.isEnabled()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    artifacts.capture("01-blocked-direct-recovery-action", window)
    modals = ModalSteps(qtbot)

    def cancel(dialog):
        pair = dialog._current()
        assert focused in {pair.left.row_id, pair.right.row_id}
        assert pair.state == "pending" and dialog.preview_left.isEnabled() and dialog.preview_right.isEnabled()
        dialog.resize(*size)
        artifacts.capture("02-focused-comparison-cancel", dialog)
        close_dialog(qtbot, dialog)

    modals.arm((V2SourceOverlapReview, cancel))
    qtbot.mouseClick(view.repeat_review_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending and not window.inventory_pending, timeout=15000)
    assert view._current().row_id == focused and not view.action_button.isEnabled()
    assert view.batch.staged == staged and view.batch.note() == note

    def review(dialog):
        choice = "distinct"
        if decision == "supporting":
            choice = "retain_right" if dialog._current().left.row_id == focused else "retain_left"
        choose_combo(qtbot, dialog.decision, choice)
        enter_text(qtbot, review_reason(dialog), "Compared both originals and explicitly reviewed this relationship")
        qtbot.mouseClick(dialog.save_button, Qt.LeftButton)

    def confirm(dialog):
        assert "Source dates, evidence and existing journal entries remain unchanged" in dialog.text()
        artifacts.capture("03-explicit-relationship-confirmation", dialog)
        qtbot.mouseClick(dialog.button(QMessageBox.Yes), Qt.LeftButton)

    modals.arm(
        (V2SourceOverlapReview, review),
        (QMessageBox, confirm),
        (V2SourceOverlapReview, lambda d: close_dialog(qtbot, d)),
    )
    qtbot.mouseClick(view.repeat_review_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending and not window.inventory_pending, timeout=15000)
    assert view._current().row_id == focused
    assert view.batch.staged == staged and view.batch.note() == note
    if decision == "distinct":
        assert view.purpose.isEnabled() and not view.repeat_review_button.isVisible()
        choices(qtbot, view)
        assert view.batch.stage_button.isEnabled()
        artifacts.capture("04-same-row-eligible-prior-stage-retained", window)
    else:
        assert not view.purpose.isEnabled() and not view.action_button.isVisible()
        assert "cannot post separately" in view.status.text()
        assert view.repeat_review_button.isVisible()
        assert view.table.columnWidth(1) >= 140
        artifacts.capture("04-supporting-occurrence-stays-blocked-prior-stage-retained", window)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.load_import(original.source_sha256).source == raw
        assert store.load_import(original.source_sha256).evidence == original
        pair = store.source_overlap_pair(focused, row(other))
        if decision == "distinct":
            assert pair.state == "distinct"
        else:
            assert pair.state == "repeat" and pair.retained_row_id == row(other)
            assert store.cash_activity_review_rows(other.source_sha256)[0].status == "Ready for purpose review"


def test_focus_follows_indirect_group_blocker_and_support_cannot_post(qtbot, tmp_path):
    profile = tmp_path / "groups.db"
    with V2ProfileStore.create(profile) as store:
        setup(store)
        first = source(store, "Root", source_date="10/01/2026")
        support = source(store, "Support", source_date="10/04/2026")
        outsider = source(store, "Outside", source_date="10/07/2026")
        a, b, c = map(row, (first, support, outsider))
        decide(store, a, b, retained=a)
    dialog = V2SourceOverlapReview(profile, focus_row_id=a)
    qtbot.addWidget(dialog)
    dialog.show()
    assert {dialog._current().left.row_id, dialog._current().right.row_id} == {b, c}
    assert dialog._current().state == "pending"
    with V2ProfileStore.open(profile) as store:
        decide(store, b, c, "distinct")
        assert store.source_overlap_posting_blocks((a, b, c)) == {
            b: "Repeated supporting evidence; post the retained row"
        }
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_capped_missing_focus_does_not_select_unrelated_pair(qtbot, tmp_path, monkeypatch):
    profile = tmp_path / "cap.db"
    with V2ProfileStore.create(profile) as store:
        setup(store)
        first = source(store, "One", count=2)
        source(store, "Two", count=2)
        full = store.source_overlap_inventory()
    focus = next(
        item.row_id
        for item in first.payload.rows
        if item.row_id not in {full.candidates[0].left.row_id, full.candidates[0].right.row_id}
    )
    read_inventory = V2ProfileStore.source_overlap_inventory

    def capped(store, **_kwargs):
        inventory = read_inventory(store)
        return replace(inventory, candidates=(inventory.candidates[0],), truncated=True)

    monkeypatch.setattr(V2ProfileStore, "source_overlap_inventory", capped)
    dialog = V2SourceOverlapReview(profile, focus_row_id=focus)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._current() is None and not dialog.save_button.isEnabled()
    assert "does not clear its posting block" in dialog.summary.text()
    assert "Display limit reached" in dialog.summary.text()

"""Partly assigned documents retain useful review space and truthful guidance."""

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from PySide6.QtCore import Qt

from .ordinary_staging_helpers import review_reason
from .qt_journey_helpers import JourneyArtifacts
from .test_v2_multirow_review import choices, select, workspace_rows
from .test_v2_review_cues import open_review


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050x700", "1280x800"])
def test_partial_assignment_notice_preserves_four_rows_and_eligible_review(
    qtbot,
    qapp,
    tmp_path,
    journey_artifacts,
    size,
):
    workspace, evidence, _raw = workspace_rows(tmp_path)
    window, view = open_review(qtbot, workspace, size=size)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    assert window.account_group.isVisible() and window.account_group.isFlat()
    assert window.account_group.title() == ""
    assert "Review confirmed rows" in window.account_assignment_status.text()
    assert "1 document account" in window.account_assignment_status.text()
    assert "before reviewing" not in window.review_progress.text()
    assert window.source_review_button.isEnabled()
    select(qtbot, view, "Coffee")
    select(qtbot, view, "Tea", Qt.ControlModifier)
    choices(qtbot, view)
    selected_ids = {row.row_id for row in view.navigation.selected()}
    shared_proposal = (view.purpose.currentData(), view.category.currentData(), review_reason(view).text())
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    staged = dict(view.batch.staged)
    staged_note = view.batch.note()
    assert view.batch.stage_button.isEnabled()
    assert not view.action_button.isVisible()
    qtbot.wait(20)
    row_height = view.table.verticalHeader().defaultSectionSize()
    assert view.table.viewport().height() >= 4 * row_height, (view.table.viewport().height(), row_height)
    artifacts.capture("01-compact-remaining-assignment-two-selected", window)
    # Assigning the last source account removes the remaining-assignment notice;
    # it does not create a posting or change any source evidence.
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.bind_source_account(evidence.source_sha256, "Other", "opaque", "cash")
    window.refresh(select_source=evidence.source_sha256)
    qtbot.waitUntil(lambda: not window.inventory_pending and not view.review_pending, timeout=15000)
    assert not window.account_group.isVisible()
    assert {row.row_id for row in view.navigation.selected()} == selected_ids
    assert (view.purpose.currentData(), view.category.currentData(), review_reason(view).text()) == shared_proposal
    assert view.batch.staged == staged and view.batch.note() == staged_note
    previously_unassigned = next(row for row in view.model.rows if row.description == "Unassigned")
    assert previously_unassigned.status == "Ready for purpose review"
    assert previously_unassigned.financial_account.startswith("Everyday checking")
    assert view.basis is not None
    artifacts.capture("02-remaining-assignment-resolved", window)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.load_import(evidence.source_sha256).evidence == evidence

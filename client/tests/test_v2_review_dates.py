"""Assumed card dates stay distinguishable and require the global posting choice."""

from __future__ import annotations

import json
from pathlib import Path

from parsetrail.core.v2_card_lines import parse_card_lines
from parsetrail.core.v2_card_source_output import from_card
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_preferences import V2Preferences, load_preferences
from parsetrail.core.v2_review_dates import permitted_posting_date, posting_date_candidate
from parsetrail.core.v2_synchrony_source_output import from_synchrony_table
from parsetrail.core.v2_table_card_source_output import from_anchored_card
from parsetrail.core.v2_workspace import V2Workspace

from devtools.parser_engine_pilot.test_card_lines import pages
from devtools.parser_engine_pilot.test_card_source_output import DEFINITION as CHASE_DEFINITION
from devtools.parser_engine_pilot.test_synchrony_source_output import DEFINITION as SYNCHRONY_DEFINITION
from devtools.parser_engine_pilot.test_synchrony_source_output import channels
from devtools.parser_engine_pilot.test_table_card_source_output import DEFINITION as TABLE_DEFINITION
from devtools.parser_engine_pilot.test_table_card_source_output import evidence as table_evidence


def test_printed_posting_and_assumed_card_dates_have_distinct_gates() -> None:
    chase_lines = page_lines(b"%PDF-synthetic", pages(), extraction_library="synthetic-pdf-1")
    chase = from_card(parse_card_lines(CHASE_DEFINITION, chase_lines), chase_lines).payload.accounts[0].rows[0]
    printed = from_anchored_card(TABLE_DEFINITION, *table_evidence()).payload.accounts[0].rows[0]
    synchrony = from_synchrony_table(SYNCHRONY_DEFINITION, *channels()).payload.accounts[0].rows[0]
    off = V2Preferences()
    on = V2Preferences(allow_assumed_posting_dates=True)

    assert posting_date_candidate(chase).provenance == "assumed"
    assert permitted_posting_date(chase, off) is None
    assert permitted_posting_date(chase, on).iso == chase.date.iso
    from parsetrail.gui.v2_evidence_preview import _RowsModel

    preview = _RowsModel((chase,))
    assert preview.data(preview.index(0, 0)) == "2026-03-15 (derived from source)"
    assert preview.data(preview.index(0, 2)) == "2026-03-16 (assumed)"
    assert printed.date.provenance == "derived"
    assert permitted_posting_date(printed, off).iso == printed.date.iso
    assert synchrony.date_role == "activity_date" and synchrony.date.iso == "2025-12-31"
    assert posting_date_candidate(synchrony).iso == "2026-01-01"
    assert permitted_posting_date(synchrony, off) is None
    assert permitted_posting_date(synchrony, on).provenance == "assumed"


def test_assumed_date_choice_is_global_and_preserves_other_preference(tmp_path: Path) -> None:
    workspace = V2Workspace.create(
        tmp_path / "profile.db",
        tmp_path / "catalog",
        trusted_keys={},
        preferences_path=tmp_path / "preferences.json",
    )
    assert workspace.preferences() == V2Preferences()
    workspace.set_allow_abbreviated_account_matching(True)
    workspace.set_allow_assumed_posting_dates(True)
    assert workspace.preferences() == V2Preferences(True, True)
    workspace.set_allow_abbreviated_account_matching(False)
    assert workspace.preferences().allow_assumed_posting_dates is True

    workspace.preferences_path.write_text(json.dumps({"allow_abbreviated_account_matching": True}))
    assert load_preferences(workspace.preferences_path) == V2Preferences(True, False)


def test_assumed_date_menu_toggle_persists_across_windows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    workspace = V2Workspace.create(
        tmp_path / "profile.db",
        tmp_path / "catalog",
        trusted_keys={},
        preferences_path=tmp_path / "preferences.json",
    )
    first = V2WorkspaceWindow(workspace)
    try:
        assert not first.assumed_posting_action.isChecked()
        first.assumed_posting_action.trigger()
        assert workspace.preferences().allow_assumed_posting_dates
    finally:
        first.close()
        app.processEvents()
    second = V2WorkspaceWindow(workspace)
    try:
        assert second.assumed_posting_action.isChecked()
        second.assumed_posting_action.trigger()
        assert not workspace.preferences().allow_assumed_posting_dates
    finally:
        second.close()
        app.processEvents()

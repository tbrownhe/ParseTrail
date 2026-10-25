"""Saved occurrence decisions keep binding controls truthful before any posting."""

from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace
from PySide6.QtWidgets import QApplication

from devtools.parser_engine_pilot.review_source_overlap import DEFINITION, SOURCES, prepare_demo


@pytest.mark.parametrize("accountless", [False, True])
def test_overlap_history_disables_account_reassignment_controls(tmp_path: Path, accountless: bool) -> None:
    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "bindings.db"
    if not accountless:
        prepare_demo(profile)
    else:
        with V2ProfileStore.create(profile) as store:
            store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
            for source in SOURCES:
                evidence = build_source_evidence(source, DEFINITION, suffix=".csv")
                rows = tuple(
                    row.model_copy(update={"source_account": None, "source_account_form": None})
                    for row in evidence.payload.rows
                )
                evidence = evidence.model_copy(update={"payload": evidence.payload.model_copy(update={"rows": rows})})
                store.import_source(source, DEFINITION, evidence, suffix=".csv")
                store.assert_file_account(evidence.source_sha256, "cash")
    with V2ProfileStore.open(profile) as store:
        pair = store.source_overlap_inventory().candidates[0]
        store.record_source_overlap_review(
            pair.left.row_id,
            pair.right.row_id,
            decision="distinct",
            reason="Separate purchases at source locations",
            expected_basis_sha256=pair.basis_sha256,
        )
        source_id = pair.left.source_sha256
        assert not store.journal_history_row_ids(source_id)
    if accountless:
        from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview

        dialog = V2AccountBindingReview(profile, source_id)
        dialog.table.selectRow(0)
        assert not dialog.file_button.isEnabled()
        assert not dialog.clear_file_button.isEnabled()
        assert not dialog.assign_rows_button.isEnabled()
    else:
        from parsetrail.gui.v2_source_account_review import V2SourceAccountReview

        workspace = V2Workspace.open(profile, tmp_path / "catalog", preferences_path=tmp_path / "preferences.json")
        dialog = V2SourceAccountReview(workspace, source_id)
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData("cash"))
        assert not dialog.assign_button.isEnabled()
        assert not dialog.clear_button.isEnabled()
    try:
        assert "repeated-row review history" in dialog.lock_notice.text()
    finally:
        dialog.close()
        app.processEvents()

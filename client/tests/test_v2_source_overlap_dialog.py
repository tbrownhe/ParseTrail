"""Source occurrence review uses explicit decisions over disposable V2 profiles."""

from __future__ import annotations

import os
from pathlib import Path

from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _profile(
    profile: Path, *, amounts: tuple[int, ...] = (-400,), variants: tuple[str, ...] = ("original", "exported")
):
    with V2ProfileStore.create(profile) as store:
        store.add_financial_account(FinancialAccount("checking", "Synthetic checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        sources = []
        for suffix in variants:
            data = "Date,Account,Description,Amount,ReportedBalance\n"
            for index, minor in enumerate(amounts, start=1):
                sign = "-" if minor < 0 else ""
                data += (
                    f"10/{index:02}/2026,Checking A,Coffee {suffix} {index},"
                    f"{sign}${abs(minor) // 100}.{abs(minor) % 100:02},$996.00\n"
                )
            content = data.encode()
            evidence = build_source_evidence(content, DEFINITION, suffix=".csv")
            store.import_source(content, DEFINITION, evidence, suffix=".csv")
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "checking")
            sources.append(evidence)
    return sources


def test_empty_inventory_and_workspace_entry(tmp_path: Path, monkeypatch):
    app = _app()
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    workspace = V2Workspace.create(
        tmp_path / "empty.db", tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    dialog = V2SourceOverlapReview(workspace.profile_path)
    try:
        assert dialog.table.rowCount() == 0
        assert not dialog.save_button.isEnabled()
        assert not dialog.preview_left.isEnabled()
        assert "does not establish" in dialog.note.text()
        assert str(workspace.profile_path) == dialog.profile_path.text()
        assert dialog.profile_path.isReadOnly()
    finally:
        dialog.close()
    opened = []
    monkeypatch.setattr(V2SourceOverlapReview, "exec", lambda review: opened.append(review.profile))
    window = V2WorkspaceWindow(workspace)
    try:
        window.overlap_review_button.click()
        assert opened == [workspace.profile_path]
    finally:
        window.close()
        app.processEvents()


def test_repeat_requires_reason_confirmation_and_persists_without_posting(tmp_path: Path, monkeypatch):
    app = _app()
    from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "review.db"
    _profile(profile)
    dialog = V2SourceOverlapReview(profile)
    try:
        dialog.table.selectRow(0)
        pair = dialog._current()
        assert pair is not None
        assert pair.left.source_sha256 in dialog.left_details.toPlainText()
        assert pair.right.source_sha256 in dialog.right_details.toPlainText()
        assert "posting date, observed" in dialog.left_details.toPlainText()
        assert "Source locations:" in dialog.left_details.toPlainText()
        assert "row 2" in dialog.left_details.toPlainText()
        assert "Active source allocation: $0.00" in dialog.left_details.toPlainText()
        assert "fixes these account assignments" in dialog.review_note.text()
        previews = []
        monkeypatch.setattr(V2EvidencePreview, "exec", lambda preview: previews.append(preview))
        dialog.preview_left.click()
        dialog.preview_right.click()
        assert len(previews) == 2
        dialog.decision.setCurrentIndex(dialog.decision.findData("retain_left"))
        assert not dialog.save_button.isEnabled()
        dialog.reason.setText("Same coffee occurrence in a second export")
        assert dialog.save_button.isEnabled()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.No)
        dialog.save_button.click()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store.source_overlap_inventory().candidates[0].state == "pending"
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
        dialog.save_button.click()
        assert "saved" in dialog.status.text()
        assert dialog._current().state == "repeat"
        assert not dialog.reason.text()
    finally:
        dialog.close()
        app.processEvents()
    with V2ProfileStore.open(profile, read_only=True) as store:
        candidate = store.source_overlap_inventory().candidates[0]
        assert candidate.state == "repeat"
        assert candidate.retained_row_id == pair.left.row_id
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert "Repeated supporting" in store.source_overlap_posting_blocks((pair.right.row_id,))[pair.right.row_id]


def test_supporting_pair_does_not_claim_same_movement_or_edit_indirect_review(tmp_path: Path):
    app = _app()
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtCore import Qt

    profile = tmp_path / "supporting.db"
    sources = _profile(profile, variants=("original", "exported", "third"))
    retained, independent, supporting = (source.payload.rows[0].row_id for source in sources)
    with V2ProfileStore.open(profile) as store:
        pair = next(
            pair
            for pair in store.source_overlap_inventory().candidates
            if {pair.left.row_id, pair.right.row_id} == {retained, supporting}
        )
        store.record_source_overlap_review(
            pair.left.row_id,
            pair.right.row_id,
            decision="repeat",
            retained_row_id=retained,
            reason="Third source repeats original",
            expected_basis_sha256=pair.basis_sha256,
        )
    dialog = V2SourceOverlapReview(profile)
    try:
        index = next(
            index
            for index in range(dialog.table.rowCount())
            if {
                dialog.candidates[dialog.table.item(index, 0).data(Qt.ItemDataRole.UserRole)].left.row_id,
                dialog.candidates[dialog.table.item(index, 0).data(Qt.ItemDataRole.UserRole)].right.row_id,
            }
            == {independent, supporting}
        )
        dialog.table.selectRow(index)
        assert dialog._current().state == "supporting"
        assert "Supporting evidence involved" in dialog.details_state.text()
        assert "no same-movement assertion" in dialog.details_state.text()
        assert retained in dialog.details_state.text()
        assert not dialog.decision.isEnabled()
        assert not dialog.save_button.isEnabled()
        assert dialog.preview_left.isEnabled()
        assert "Select the pair containing the retained row" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()


def test_stale_form_refreshes_and_distinct_can_return_to_pending(tmp_path: Path, monkeypatch):
    app = _app()
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "stale.db"
    _profile(profile)
    first = V2SourceOverlapReview(profile)
    stale = V2SourceOverlapReview(profile)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    try:
        for dialog in (first, stale):
            dialog.table.selectRow(0)
            dialog.decision.setCurrentIndex(dialog.decision.findData("distinct"))
            dialog.reason.setText("Verified two separate purchases")
        first.save_button.click()
        assert first._current().state == "distinct"
        stale.save_button.click()
        assert "not saved" in stale.status.text()
        assert stale._current().state == "distinct"
        assert stale.decision.currentData() is None
        first.decision.setCurrentIndex(first.decision.findData("pending"))
        first.reason.setText("Need another source check")
        first.save_button.click()
        assert first._current().state == "pending"
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM SourceOverlapReviews").fetchone() == (2,)
    finally:
        first.close()
        stale.close()
        app.processEvents()


def test_numeric_sort_cap_warning_and_posted_row_cannot_be_excluded(tmp_path: Path, monkeypatch):
    app = _app()
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtCore import Qt

    profile = tmp_path / "sort.db"
    _profile(profile, amounts=(-400, -10000))
    original = V2ProfileStore.source_overlap_inventory
    monkeypatch.setattr(
        V2ProfileStore, "source_overlap_inventory", lambda store, **kwargs: original(store, max_pairs=1, **kwargs)
    )
    limited = V2SourceOverlapReview(profile)
    try:
        assert limited.table.rowCount() == 1
        assert "Display limit reached" in limited.summary.text()
        assert "still checked before posting" in limited.summary.text()
    finally:
        limited.close()
    monkeypatch.setattr(V2ProfileStore, "source_overlap_inventory", original)
    with V2ProfileStore.open(profile) as store:
        pair = store.source_overlap_inventory().candidates[0]
        store.record_source_overlap_review(
            pair.left.row_id,
            pair.right.row_id,
            decision="distinct",
            reason="Separate purchases",
            expected_basis_sha256=pair.basis_sha256,
        )
        store.post_reviewed_cash_category(pair.left.row_id, "expense:food", reason="Reviewed first purchase")
    dialog = V2SourceOverlapReview(profile)
    try:
        dialog.table.sortItems(2, Qt.SortOrder.AscendingOrder)
        assert [dialog.table.item(index, 2).text() for index in range(2)] == ["-$100.00", "-$4.00"]
        row = next(
            index
            for index in range(dialog.table.rowCount())
            if dialog.candidates[dialog.table.item(index, 0).data(Qt.ItemDataRole.UserRole)].left.row_id
            == pair.left.row_id
        )
        dialog.table.selectRow(row)
        dialog.reason.setText("Must not exclude the posted side")
        dialog.decision.setCurrentIndex(dialog.decision.findData("retain_right"))
        assert not dialog.save_button.isEnabled()
        assert "has journal history" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()

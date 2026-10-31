"""Plan checkboxes are drafts; exact captured selections need explicit confirmation."""

from __future__ import annotations

import hashlib
import threading
import time

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_transfer_planning import RULE, pair_key, plan_transfers
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui import v2_transfer_review
from parsetrail.gui.v2_transfer_plan import V2TransferPlanPage, V2TransferSelectionManifest
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from .test_v2_transfer_planning import _movement, _profile, _snapshot
from .test_v2_transfer_review_async import wait_for_transfers


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    return QApplication.instance() or QApplication([])


def _dialog(tmp_path):
    path = tmp_path / "plan.db"
    _profile(path)
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    dialog = v2_transfer_review.V2TransferReview(workspace)
    wait_for_transfers(dialog)
    return dialog


def _tick_until(app, predicate, timeout=5):
    end = time.monotonic() + timeout
    while not predicate():
        app.processEvents()
        time.sleep(0.003)
        assert time.monotonic() < end
    app.processEvents()


def _check(page, status, checked=True):
    index = next(index for index, row in enumerate(page.rows) if row.status == status)
    page.table.item(index, 0).setCheckState(Qt.Checked if checked else Qt.Unchecked)
    return index


def test_default_plan_only_prechecks_ready_and_highlight_never_includes(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    try:
        page = dialog.plan_page
        assert dialog.tabs.currentWidget() is page
        assert len(dialog.window_plan.ready_pairs) == 1 and len(dialog.window_plan.proposals) == 2
        assert "Ready 1 pair" in page.counts.text() and "Suggested 2 pairs" in page.counts.text()
        assert "Needs review 0 groups" in page.counts.text()
        assert sum(row.status == "Alternative" for row in page.rows) == 1
        assert page.selected_keys() == (pair_key(dialog.window_plan.ready_pairs[0]),)
        assert "maximum date gap 7" in page.scope.text()

        def forbidden(*_args, **_kwargs):
            raise AssertionError("Checkboxes and row inspection must not read or rank")

        monkeypatch.setattr(V2ProfileStore, "open", forbidden)
        monkeypatch.setattr(v2_transfer_review, "plan_transfers", forbidden)
        original = page.selected_keys()
        for index, row in enumerate(page.rows):
            page.table.selectRow(index)
            page.note.setText(f"Draft {index}")
            assert page.selected_keys() == original
            if row.status == "Suggested":
                assert page.table.item(index, 0).checkState() == Qt.Unchecked
        selected = _check(page, "Suggested")
        assert len(page.selected_keys()) == 2
        page.table.selectRow(selected)
        page.alternatives.click()
        assert dialog.tabs.currentWidget() is dialog.matches_page
        assert pair_key(dialog._current()) == pair_key(page.rows[selected].pair)
    finally:
        dialog.close()
        app.processEvents()


def test_exact_ready_and_suggested_selection_posts_only_after_manifest(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    try:
        page = dialog.plan_page
        _check(page, "Suggested")
        captured = set(page.selected_keys())
        assert len(captured) == 2
        page.note.setText("Both sources inspected")
        manifests = []

        def accept(manifest):
            manifests.append(manifest)
            assert manifest.table.rowCount() == 2
            assert {manifest.table.item(index, 0).text() for index in range(2)} == {"Ready", "Suggested"}
            assert manifest.post.text() == "Confirm and post 2 pairs"
            assert not manifest.post.autoDefault()
            assert manifest.buttons.button(QDialogButtonBox.Cancel).isDefault()
            return QDialog.Accepted

        monkeypatch.setattr(V2TransferSelectionManifest, "exec", accept)
        page.review.click()
        wait_for_transfers(dialog)
        assert len(manifests) == 1 and len(dialog.events) == 2
        assert {pair_key(event.pair) for event in dialog.events} == captured
        assert all(RULE in event.reason and "Both sources inspected" in event.reason for event in dialog.events)
        with V2ProfileStore.open(dialog.workspace.profile_path, read_only=True) as store:
            assert len(store._active_consumed()) == 4
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (3,)
        assert "2 selected transfer pairs posted" in page.status.text()
    finally:
        dialog.close()
        app.processEvents()


def test_cancel_retains_checkbox_draft_and_writes_nothing(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    try:
        page = dialog.plan_page
        _check(page, "Suggested")
        page.note.setText("Retain my draft")
        keys = page.selected_keys()
        before = hashlib.sha256(dialog.workspace.profile_path.read_bytes()).hexdigest()
        monkeypatch.setattr(V2TransferSelectionManifest, "exec", lambda _self: QDialog.Rejected)
        page.review.click()
        wait_for_transfers(dialog)
        assert page.selected_keys() == keys and page.note.text() == "Retain my draft"
        assert hashlib.sha256(dialog.workspace.profile_path.read_bytes()).hexdigest() == before
    finally:
        dialog.close()
        app.processEvents()


def test_nested_date_policy_change_refuses_frozen_manifest_and_resets_draft(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    try:
        page = dialog.plan_page
        before = hashlib.sha256(dialog.workspace.profile_path.read_bytes()).hexdigest()
        page.note.setText("Original note")

        def changed(_manifest):
            page.note.setText("Changed behind modal")
            _check(page, "Suggested")
            dialog.workspace.set_allow_assumed_posting_dates(True)
            return QDialog.Accepted

        monkeypatch.setattr(V2TransferSelectionManifest, "exec", changed)
        page.review.click()
        wait_for_transfers(dialog)
        assert not dialog.events
        assert hashlib.sha256(dialog.workspace.profile_path.read_bytes()).hexdigest() == before
        assert dialog.window_plan.preferences.allow_assumed_posting_dates
        assert page.selected_keys() == tuple(sorted(pair_key(p) for p in dialog.window_plan.ready_pairs))
        assert page.note.text() == "" and "no pairs were posted" in page.status.text()
    finally:
        dialog.close()
        app.processEvents()


def test_nested_draft_changes_do_not_expand_captured_selection_or_reason(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    try:
        page = dialog.plan_page
        captured = set(page.selected_keys())
        page.note.setText("Original captured note")

        def changed_draft(_manifest):
            page.note.setText("Unconfirmed replacement note")
            _check(page, "Suggested")
            return QDialog.Accepted

        monkeypatch.setattr(V2TransferSelectionManifest, "exec", changed_draft)
        page.review.click()
        wait_for_transfers(dialog)
        assert len(dialog.events) == 1 and {pair_key(event.pair) for event in dialog.events} == captured
        assert "Original captured note" in dialog.events[0].reason
        assert "Unconfirmed replacement note" not in dialog.events[0].reason
    finally:
        dialog.close()
        app.processEvents()


def test_ranking_and_selection_preparation_run_off_gui_and_prepare_has_no_db(tmp_path, app, monkeypatch):
    ranked, selected = [], []
    rank = v2_transfer_review.plan_transfers
    select = v2_transfer_review.select_transfer_plan

    def rank_worker(*args, **kwargs):
        assert QThread.currentThread() != app.thread()
        ranked.append(True)
        return rank(*args, **kwargs)

    def select_worker(*args, **kwargs):
        assert QThread.currentThread() != app.thread()
        selected.append(True)
        return select(*args, **kwargs)

    monkeypatch.setattr(v2_transfer_review, "plan_transfers", rank_worker)
    monkeypatch.setattr(v2_transfer_review, "select_transfer_plan", select_worker)
    dialog = _dialog(tmp_path)
    try:
        assert ranked and selected

        def forbidden(*_args, **_kwargs):
            raise AssertionError("Preparing a cached selection must not open the database")

        monkeypatch.setattr(V2ProfileStore, "open", forbidden)
        monkeypatch.setattr(V2TransferSelectionManifest, "exec", lambda _self: QDialog.Rejected)
        dialog.plan_page.review.click()
        wait_for_transfers(dialog)
        assert len(selected) == 2
    finally:
        dialog.close()
        app.processEvents()


def test_estimated_dates_stay_unchecked_even_with_explicit_policy(app):
    assert app is QApplication.instance()
    outgoing = (_movement("out", 0, "a", -10000),)
    incoming = (_movement("estimated", 1, "b", 10000, assumed=True),)
    plan = plan_transfers(_snapshot(outgoing, incoming, preferences=V2Preferences(False, True)))
    page = V2TransferPlanPage(date_label=v2_transfer_review._source_date, pair_details=v2_transfer_review._pair_details)
    try:
        page.set_plan(plan, note_limit=200)
        assert page.selected_keys() == ()
        assert page.rows[0].status == "Suggested" and page.rows[0].selectable
        assert page.table.item(0, 0).checkState() == Qt.Unchecked
        assert "(assumed)" in page.table.item(0, 4).text()
        assert not page.review.isEnabled()
    finally:
        page.close()


@pytest.mark.parametrize("incoming_count", [2, 64])
def test_tied_and_oversized_groups_never_get_include_checkboxes(app, incoming_count):
    assert app is QApplication.instance()
    outgoing = (_movement("out", 0, "a", -10000),)
    incoming = tuple(_movement(f"in-{i}", 0, "b", 10000) for i in range(incoming_count))
    plan = plan_transfers(_snapshot(outgoing, incoming))
    page = V2TransferPlanPage(date_label=v2_transfer_review._source_date, pair_details=v2_transfer_review._pair_details)
    try:
        page.set_plan(plan, note_limit=200)
        assert "Needs review 1 group" in page.counts.text()
        assert not page.selected_keys() and not page.review.isEnabled()
        assert page.table.currentRow() == 0 and page.manual.isEnabled()
        for index in range(page.table.rowCount()):
            assert page.rows[index].status == "Needs review"
            assert not page.table.item(index, 0).flags() & Qt.ItemIsUserCheckable
    finally:
        page.close()


def test_close_during_prepare_does_not_open_a_late_manifest(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    started, release = threading.Event(), threading.Event()
    original = v2_transfer_review.select_transfer_plan
    manifests = []

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(v2_transfer_review, "select_transfer_plan", delayed)
    monkeypatch.setattr(V2TransferSelectionManifest, "exec", lambda _self: manifests.append(True) or QDialog.Accepted)
    try:
        dialog.plan_page.review.click()
        _tick_until(app, started.is_set)
        assert dialog.close()
        release.set()
        _tick_until(app, lambda: not v2_transfer_review._TRANSFER_WORKERS)
        assert manifests == []
        with V2ProfileStore.open(dialog.workspace.profile_path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        release.set()
        dialog.close()
        app.processEvents()


def test_note_budget_preserves_exact_500_character_history_reason(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    try:
        page = dialog.plan_page
        page.note.setText("n" * page.note.maxLength())
        note = page.note.text()
        monkeypatch.setattr(V2TransferSelectionManifest, "exec", lambda _self: QDialog.Accepted)
        page.review.click()
        wait_for_transfers(dialog)
        assert len(dialog.events) == 1 and len(dialog.events[0].reason) == 500
        assert note in dialog.events[0].reason and RULE in dialog.events[0].reason
    finally:
        dialog.close()
        app.processEvents()


def test_unused_alternative_does_not_inflate_separate_unresolved_group_count(tmp_path, app):
    from parsetrail.core.v2_source_pipeline import build_source_evidence

    from .test_v2_transfers import BANK_DEFINITION

    path = tmp_path / "plan.db"
    _profile(path)
    source = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"01/03/2026,Account A,Tied out one,-$50.00,$0.00\n"
        b"01/03/2026,Account A,Tied out two,-$50.00,$0.00\n"
        b"01/03/2026,Account C,Tied in one,$50.00,$0.00\n"
        b"01/03/2026,Account C,Tied in two,$50.00,$0.00\n"
    )
    evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Account A", "opaque", "a")
        store.bind_source_account(evidence.source_sha256, "Account C", "opaque", "c")
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    dialog = v2_transfer_review.V2TransferReview(workspace)
    try:
        wait_for_transfers(dialog)
        page = dialog.plan_page
        assert "Ready 1 pair" in page.counts.text()
        assert "Suggested 2 pairs" in page.counts.text()
        assert "Needs review 1 group" in page.counts.text()
        assert sum(row.status == "Alternative" for row in page.rows) == 1
        assert sum(row.status == "Needs review" for row in page.rows) == 4
    finally:
        dialog.close()
        app.processEvents()


def test_focused_unmatched_movement_shows_manual_recovery_instead_of_unrelated_plan(tmp_path, app):
    from parsetrail.core.v2_source_pipeline import build_source_evidence

    from .test_v2_transfers import BANK_DEFINITION

    path = tmp_path / "plan.db"
    _profile(path)
    source = (
        b"Date,Account,Description,Amount,ReportedBalance\n01/03/2026,Account A,No eligible counterpart,-$77.00,$0.00\n"
    )
    evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Account A", "opaque", "a")
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    dialog = v2_transfer_review.V2TransferReview(workspace, focus_row_id=evidence.payload.rows[0].row_id)
    try:
        wait_for_transfers(dialog)
        assert dialog.tabs.currentWidget() is dialog.matches_page
        assert "No eligible counterpart" in dialog.status.text()
        assert not dialog.confirm.isEnabled()
        assert len(dialog.window_plan.ready_pairs) == 1
        assert not dialog.plan_page.review.isDefault()
    finally:
        dialog.close()
        app.processEvents()

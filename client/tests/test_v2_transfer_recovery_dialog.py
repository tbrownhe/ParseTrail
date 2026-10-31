"""Individual transfer recovery stays explicit and bound to the displayed profile."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_transfer_planning import (
    pair_key,
    plan_transfers,
    post_reviewed_transfer_selection,
    select_transfer_plan,
)
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui import v2_transfer_review
from parsetrail.gui.v2_transfer_plan import V2TransferManualReview
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .test_v2_transfer_planning import _profile
from .test_v2_transfer_review_async import wait_for_transfers


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    return QApplication.instance() or QApplication([])


def _dialog(tmp_path, state="pending"):
    path = tmp_path / "a.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        frame = store.transfer_review_snapshot(preferences=V2Preferences())
        pair = next(p for p in frame.candidates if p.day_gap == 1)
        if state in {"active", "mixed"}:
            store.post_reviewed_transfer(
                *pair_key(pair),
                preferences=V2Preferences(),
                reason="Earlier manual review",
                expected_basis_sha256=frame.basis_sha256,
            )
        elif state == "dismissed":
            store.record_transfer_pair_review(
                *pair_key(pair),
                decision="dismiss",
                preferences=V2Preferences(),
                reason="Earlier dismissed suggestion",
                expected_basis_sha256=frame.basis_sha256,
            )
        if state == "mixed":
            plan = plan_transfers(store.transfer_review_snapshot(preferences=V2Preferences()))
            post_reviewed_transfer_selection(
                store,
                select_transfer_plan(plan, [pair_key(plan.ready_pairs[0])]),
                preferences=V2Preferences(),
                reason="Earlier planned review",
            )
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    dialog = v2_transfer_review.V2TransferReview(workspace)
    wait_for_transfers(dialog)
    return dialog


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_question_action(dialog, action):
    if action in {"post", "dismiss"}:
        dialog.table.selectRow(0)
        dialog.note.setText("Reviewed pair context")
        return dialog.confirm if action == "post" else dialog.dismiss
    if action == "reopen":
        dialog.review_table.selectRow(0)
        dialog.reopen_reason.setText("Reviewed reopening context")
        return dialog.reopen
    dialog.event_table.selectRow(0)
    dialog.correction_reason.setText("Reviewed correction context")
    if action == "replace":
        dialog.load_replacements.click()
        wait_for_transfers(dialog)
        index = next(
            i for i, p in enumerate(dialog.replacements) if pair_key(p) != pair_key(dialog.selected_event.pair)
        )
        dialog.replacement.setCurrentIndex(dialog.replacement.findData(index))
        assert dialog.replace.isEnabled()
        return dialog.replace
    return dialog.withdraw


@pytest.mark.parametrize("action", ["post", "dismiss", "reopen", "withdraw", "replace"])
@pytest.mark.parametrize("switch_before_click", [False, True])
def test_all_question_actions_refuse_identical_other_profile(tmp_path, app, monkeypatch, action, switch_before_click):
    state = "active" if action in {"withdraw", "replace"} else "dismissed" if action == "reopen" else "pending"
    dialog = _dialog(tmp_path, state)
    path = dialog.workspace.profile_path
    other = tmp_path / "identical-b.db"
    shutil.copyfile(path, other)
    before = _hash(path), _hash(other)
    questions = []
    try:
        button = _prepare_question_action(dialog, action)

        def switch(_parent, _title, _message):
            questions.append(True)
            dialog.workspace.profile_path = other
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", switch)
        if switch_before_click:
            dialog.workspace.profile_path = other
        button.click()
        wait_for_transfers(dialog)
        assert len(questions) == (0 if switch_before_click else 1)
        assert (_hash(path), _hash(other)) == before
        assert dialog._snapshot_profile == other
        assert dialog.profile_path.text() == str(other)
    finally:
        dialog.close()
        app.processEvents()


def test_global_policy_change_before_click_refuses_stale_display(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    try:
        dialog.table.selectRow(0)
        before = _hash(dialog.workspace.profile_path)
        questions = []
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: questions.append(True) or QMessageBox.Yes)
        dialog.workspace.set_allow_assumed_posting_dates(True)
        dialog.confirm.click()
        wait_for_transfers(dialog)
        assert not questions and not dialog.events
        assert _hash(dialog.workspace.profile_path) == before
        assert dialog._snapshot.preferences.allow_assumed_posting_dates
    finally:
        dialog.close()
        app.processEvents()


def test_refused_profile_switch_requires_new_review_in_visible_reloaded_profile(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    original = dialog.workspace.profile_path
    other = tmp_path / "identical-b.db"
    shutil.copyfile(original, other)
    initial = _hash(original), _hash(other)
    try:
        dialog.tabs.setCurrentWidget(dialog.matches_page)
        dialog.table.selectRow(0)

        def change_profile(_parent, _title, _message):
            dialog.workspace.profile_path = other
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", change_profile)
        dialog.confirm.click()
        wait_for_transfers(dialog)
        assert (_hash(original), _hash(other)) == initial
        assert dialog._snapshot_profile == other and dialog.profile_path.text() == str(other)
        dialog.table.selectRow(0)
        dialog.note.setText("Explicitly reviewed the visible reloaded profile")
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        dialog.confirm.click()
        wait_for_transfers(dialog)
        assert _hash(original) == initial[0] and _hash(other) != initial[1]
        assert len(dialog.events) == 1 and dialog.profile_path.text() == str(other)
    finally:
        dialog.close()
        app.processEvents()


def test_direct_review_chooses_from_frozen_group_and_captures_its_own_note(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    captured = []
    try:
        page = dialog.plan_page
        index = next(i for i, row in enumerate(page.rows) if row.status == "Alternative")
        page.table.selectRow(index)
        page.note.setText("Prefilled visible plan note")

        def choose(manual):
            assert manual.note.text() == "Prefilled visible plan note"
            assert manual.table.columnCount() == 7
            original = pair_key(manual.current_pair())
            target = next(i for i, p in enumerate(manual.pairs) if pair_key(p) != original)
            manual.table.selectRow(target)
            manual.note.setText("Final note from this review")
            manual.accept()
            captured.append(pair_key(manual.confirmed_pair))
            # A changed main-window highlight must not substitute another pair.
            page.table.selectRow(0)
            page.note.setText("Unconfirmed main-window note")
            return QDialog.Accepted

        monkeypatch.setattr(V2TransferManualReview, "exec", choose)
        page.manual.click()
        wait_for_transfers(dialog)
        assert len(dialog.events) == 1 and pair_key(dialog.events[0].pair) == captured[0]
        assert "Final note from this review" in dialog.events[0].reason
        assert "Unconfirmed main-window note" not in dialog.events[0].reason
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("change", ["profile_before", "profile_during", "prefs_before", "prefs_during"])
def test_direct_review_scope_change_refuses_without_writes(tmp_path, app, monkeypatch, change):
    dialog = _dialog(tmp_path)
    path = dialog.workspace.profile_path
    other = tmp_path / "identical-b.db"
    shutil.copyfile(path, other)
    before = _hash(path), _hash(other)
    modals = []

    def changed():
        if change.startswith("profile"):
            dialog.workspace.profile_path = other
        else:
            dialog.workspace.set_allow_assumed_posting_dates(True)

    try:
        page = dialog.plan_page
        page.table.selectRow(next(i for i, row in enumerate(page.rows) if row.status == "Alternative"))

        def accept(manual):
            modals.append(True)
            manual.accept()
            changed()
            return QDialog.Accepted

        monkeypatch.setattr(V2TransferManualReview, "exec", accept)
        if change.endswith("before"):
            changed()
        page.manual.click()
        wait_for_transfers(dialog)
        assert len(modals) == (0 if change.endswith("before") else 1)
        assert (_hash(path), _hash(other)) == before
        assert not dialog.events
    finally:
        dialog.close()
        app.processEvents()


def test_manual_cancel_and_row_selection_do_not_read_or_write_profile(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path)
    try:
        page = dialog.plan_page
        page.table.selectRow(next(i for i, row in enumerate(page.rows) if row.status == "Alternative"))
        before = _hash(dialog.workspace.profile_path)

        def forbidden(*_args, **_kwargs):
            raise AssertionError("Cached manual review must not open the database")

        monkeypatch.setattr(V2ProfileStore, "open", forbidden)

        def cancel(manual):
            for index in range(len(manual.pairs)):
                manual.table.selectRow(index)
                manual.note.setText(f"Uncommitted note {index}")
            return QDialog.Rejected

        monkeypatch.setattr(V2TransferManualReview, "exec", cancel)
        page.manual.click()
        assert _hash(dialog.workspace.profile_path) == before
    finally:
        dialog.close()
        app.processEvents()


def test_mixed_manual_and_planned_history_explains_and_preserves_recovery(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path, "mixed")
    try:
        assert len(dialog.events) == 2
        manual = next(event for event in dialog.events if event.reason == "Earlier manual review")
        planned = next(event for event in dialog.events if event.event_id != manual.event_id)
        for event in (manual, planned):
            dialog.correction_reason.clear()
            dialog.event_table.selectRow(
                next(i for i, row in enumerate(dialog.events) if row.event_id == event.event_id)
            )
            assert "Correct or undo" in dialog.correction_group.title()
            assert not dialog.withdraw.isEnabled() and "Enter a reason above" in dialog.event_status.text()
            dialog.correction_reason.setText("Reviewed correction reason")
            assert dialog.withdraw.isEnabled()
            dialog.load_replacements.click()
            wait_for_transfers(dialog)
            if event.event_id == planned.event_id:
                assert "No different replacement pair" in dialog.event_status.text()
                assert not dialog.replace.isEnabled()
        dialog.event_table.selectRow(next(i for i, row in enumerate(dialog.events) if row.event_id == manual.event_id))
        target = next(i for i, p in enumerate(dialog.replacements) if pair_key(p) != pair_key(manual.pair))
        dialog.replacement.setCurrentIndex(dialog.replacement.findData(target))
        assert dialog.replace.isEnabled() and "Replacement is ready" in dialog.event_status.text()
        before = _hash(dialog.workspace.profile_path)
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        dialog.replace.click()
        assert _hash(dialog.workspace.profile_path) == before
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        dialog.withdraw.click()
        wait_for_transfers(dialog)
        by_id = {e.event_id: e for e in dialog.events}
        assert by_id[manual.event_id].status == "cancelled" and by_id[planned.event_id].status == "active"
        assert "Select an Active row" in dialog.event_status.text()
        dialog.event_table.selectRow(next(i for i, row in enumerate(dialog.events) if row.event_id == planned.event_id))
        dialog.event_table.selectRow(next(i for i, row in enumerate(dialog.events) if row.event_id == manual.event_id))
        assert "historical match was already withdrawn" in dialog.event_status.text()
        with V2ProfileStore.open(dialog.workspace.profile_path, read_only=True) as store:
            assert set(store._active_consumed()) == set(pair_key(planned.pair))
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (5,)
    finally:
        dialog.close()
        app.processEvents()


def test_cached_settlement_launch_refuses_other_profile(tmp_path, app, monkeypatch):
    dialog = _dialog(tmp_path, "active")
    try:
        dialog.event_table.selectRow(0)
        path = dialog.workspace.profile_path
        other = tmp_path / "identical-b.db"
        shutil.copyfile(path, other)
        before = _hash(path), _hash(other)

        def forbidden(*_args, **_kwargs):
            raise AssertionError("A cached event must not open a different profile's settlement")

        monkeypatch.setattr(v2_transfer_review, "V2SettlementReview", forbidden)
        dialog.workspace.profile_path = other
        dialog.review_settlement.click()
        wait_for_transfers(dialog)
        assert (_hash(path), _hash(other)) == before
    finally:
        dialog.close()
        app.processEvents()


def test_manual_unknown_source_description_is_qualified(tmp_path, app):
    dialog = _dialog(tmp_path)
    try:
        original = dialog.candidates[0]
        pair = replace(
            original,
            outgoing=replace(original.outgoing, source_description_known=False, description="Accounting label only"),
        )
        manual = V2TransferManualReview(
            (pair,),
            pair_key(pair),
            scope="Public synthetic",
            explanation="Manual review",
            date_label=v2_transfer_review._source_date,
            pair_details=v2_transfer_review._pair_details,
        )
        assert "source description unavailable" in manual.table.item(0, 2).text()
        assert "Source description unavailable; accounting label only" in manual.details.toPlainText()
        manual.close()
    finally:
        dialog.close()
        app.processEvents()

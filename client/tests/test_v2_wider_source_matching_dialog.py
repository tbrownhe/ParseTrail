"""Nearby source dates and retained-group navigation use disposable real profiles."""

from __future__ import annotations

import hashlib
import json

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_source_overlap_dialog import DEFINITION


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _profile(profile, days, *, roles=None):
    sources = []
    with V2ProfileStore.create(profile) as store:
        store.add_financial_account(FinancialAccount("cash", "Synthetic checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        for index, day in enumerate(days):
            definition = json.loads(DEFINITION)
            definition["date_role"] = roles[index] if roles else "posting_date"
            definition = json.dumps(definition).encode()
            content = (
                "Date,Account,Description,Amount,ReportedBalance\n"
                f"{day},Checking A,Revised merchant description {index},-$4.00,$996.00\n"
            ).encode()
            evidence = build_source_evidence(content, definition, suffix=".csv")
            store.import_source(content, definition, evidence, suffix=".csv")
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
            sources.append(evidence)
    return tuple(source.payload.rows[0].row_id for source in sources)


def _review(profile, left, right, decision, retained=None):
    with V2ProfileStore.open(profile) as store:
        pair = store.source_overlap_pair(left, right)
        return store.record_source_overlap_review(
            left,
            right,
            decision=decision,
            retained_row_id=retained,
            reason="Explicit synthetic source comparison",
            expected_basis_sha256=pair.basis_sha256,
        )


def _select(dialog, left, right):
    from PySide6.QtCore import Qt

    for index in range(dialog.table.rowCount()):
        pair = dialog.candidates[dialog.table.item(index, 0).data(Qt.UserRole)]
        if {pair.left.row_id, pair.right.row_id} == {left, right}:
            dialog.table.selectRow(index)
            return dialog._current()
    pytest.fail("Expected actual row pair is not reachable")


def _choose(dialog, choice):
    dialog.decision.setCurrentIndex(dialog.decision.findData(choice))
    dialog.reason.setText("Compared immutable dates, descriptions and locations")


def test_shifted_roles_dates_cancel_review_and_reopen(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "dates.db"
    rows = _profile(
        profile, ("12/30/2025", "01/02/2026", "01/06/2026"), roles=("posting_date", "activity_date", "posting_date")
    )
    dialog = V2SourceOverlapReview(profile)
    try:
        assert dialog.table.rowCount() == 1
        pair = _select(dialog, *rows[:2])
        assert "3 day(s) apart; source date roles differ" in dialog.details_state.text()
        details = dialog.left_details.toPlainText() + dialog.right_details.toPlainText()
        assert "posting date, observed" in details and "activity date, observed" in details
        assert "2025-12-30" in details and "2026-01-02" in details
        assert "Signed source amount: -$4.00" in details and "row 2" in details
        assert dialog.table.item(dialog.table.currentRow(), 1).text() == pair.left.source_date
        assert dialog.table.item(dialog.table.currentRow(), 4).text() == pair.right.source_date
        _choose(dialog, "distinct")
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        dialog.save_button.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        questions = []

        def accept(_parent, _title, text):
            questions.append(text)
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", accept)
        dialog.save_button.click()
        assert "2025-12-30" in questions[0] and "2026-01-02" in questions[0]
        assert "exact signed source amount: -$4.00" in questions[0]
        assert dialog._current().state == "distinct"
    finally:
        dialog.close()
        app.processEvents()
    reopened = V2SourceOverlapReview(profile)
    try:
        _select(reopened, *rows[:2])
        assert reopened._current().state == "distinct"
        _choose(reopened, "pending")
        reopened.save_button.click()
        assert reopened._current().state == "pending"
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert not store._active_consumed()
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        reopened.close()


def test_alias_only_outsider_review_and_uncapped_saved_edge_navigation(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "alias.db"
    root, alias, outsider = _profile(profile, ("01/03/2026", "01/01/2026", "12/30/2025"))
    _review(profile, root, alias, "repeat", root)
    original = V2ProfileStore.source_overlap_inventory
    monkeypatch.setattr(V2ProfileStore, "source_overlap_inventory", lambda store: original(store, max_pairs=1))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = V2SourceOverlapReview(profile)
    try:
        assert dialog.table.rowCount() == 1 and "Display limit" in dialog.summary.text()
        _select(dialog, alias, outsider)
        assert dialog._current().state == "pending"
        _choose(dialog, "retain_left")
        assert not dialog.save_button.isEnabled()
        _choose(dialog, "distinct")
        assert dialog.save_button.isEnabled()
        dialog.save_button.click()
        assert dialog._current().state == "distinct"
        _choose(dialog, "pending")
        dialog.save_button.click()
        assert dialog._current().state == "pending"
        assert dialog.saved_pair.count() == 1
        calls = []
        lookup = V2ProfileStore.source_overlap_pair

        def direct(store, left, right):
            calls.append({left, right})
            return lookup(store, left, right)

        monkeypatch.setattr(V2ProfileStore, "source_overlap_pair", direct)
        dialog.open_saved_pair.click()
        assert calls == [{root, alias}]
        assert {dialog._current().left.row_id, dialog._current().right.row_id} == {root, alias}
        assert "independently of the display limit" in dialog.summary.text()
        _choose(dialog, "pending")
        assert dialog.save_button.isEnabled()
        dialog.save_button.click()
        assert dialog._current().state == "pending"
        assert not dialog.saved_pair.isEnabled()
        pair = _select(dialog, alias, outsider)
        _choose(dialog, "retain_left" if pair.left.row_id == outsider else "retain_right")
        assert dialog.save_button.isEnabled()
        dialog.save_button.click()
        assert dialog._current().state == "repeat" and dialog._current().retained_row_id == outsider
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert not store._active_consumed()
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("decision", ["pending", "distinct"])
def test_implicit_group_pair_cannot_clear_group_and_direct_edge_clears_only_one(tmp_path, app, monkeypatch, decision):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "group.db"
    root, first, second = _profile(profile, ("01/02/2026", "01/01/2026", "01/03/2026"))
    _review(profile, root, first, "repeat", root)
    _review(profile, root, second, "repeat", root)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = V2SourceOverlapReview(profile)
    try:
        _select(dialog, first, second)
        assert dialog._current().state == "repeat"
        assert dialog.saved_pair.count() == 2
        _choose(dialog, "pending")
        assert not dialog.save_button.isEnabled()
        assert "implicit group relationship" in dialog.status.text()
        edge_index = next(
            index
            for index in range(dialog.saved_pair.count())
            if set(dialog.saved_pair.itemData(index)) == {root, first}
        )
        dialog.saved_pair.setCurrentIndex(edge_index)
        dialog.open_saved_pair.click()
        _choose(dialog, "distinct")
        assert dialog.save_button.isEnabled()
        _choose(dialog, decision)
        assert dialog.save_button.isEnabled()
        dialog.save_button.click()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store.source_overlap_pair(root, second).state == "repeat"
            assert store.source_overlap_pair(root, first).state == decision
    finally:
        dialog.close()
        app.processEvents()


def test_shifted_posted_repeat_repair_preserves_original_dates_and_cancellation(tmp_path, app, monkeypatch):
    from datetime import date

    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "posted.db"
    retained, redundant = _profile(profile, ("12/30/2025", "01/02/2026"))
    _review(profile, retained, redundant, "distinct")
    with V2ProfileStore.open(profile) as store:
        kept_key = store.post_reviewed_cash_category(retained, "expense:food", reason="Reviewed first occurrence")
        old_key = store.post_reviewed_cash_category(redundant, "expense:food", reason="Reviewed second occurrence")
    dialog = V2SourceOverlapReview(profile)
    try:
        pair = _select(dialog, retained, redundant)
        _choose(dialog, "retain_left" if pair.left.row_id == retained else "retain_right")
        assert dialog.repair_button.isEnabled() and not dialog.save_button.isEnabled()
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        dialog.repair_button.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        questions = []

        def accept(_parent, _title, message):
            questions.append(message)
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", accept)
        dialog.repair_button.click()
        assert "2025-12-30" in questions[0] and "2026-01-02" in questions[0]
        assert "commit together" in questions[0]
        assert "current state" in dialog.status.text()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store._active_consumed() == {retained: -400}
            position = store.account_positions(as_of=date(2026, 1, 31)).accounts[0]
            assert position.recorded_debit_minor == -400
            history = {item.entry_key: item for item in position.history}
            assert history[kept_key].posting_date == date(2025, 12, 30)
            assert history[old_key].posting_date == date(2026, 1, 2)
            inverse = [item for item in position.history if item.entry_key not in {kept_key, old_key}]
            assert len(inverse) == 1 and inverse[0].posting_date == date(2026, 1, 2)
            assert inverse[0].debit_change_minor == 400
            assert store.source_overlap_pair(retained, redundant).state == "repeat"
    finally:
        dialog.close()
        app.processEvents()


def test_nontransitive_group_refusal_refreshes_without_review_or_money(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "chain.db"
    root, alias, outsider = _profile(profile, ("01/03/2026", "01/01/2026", "01/05/2026"))
    _review(profile, root, alias, "repeat", root)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = V2SourceOverlapReview(profile)
    try:
        pair = _select(dialog, root, outsider)
        _choose(dialog, "retain_left" if pair.left.row_id == root else "retain_right")
        dialog.save_button.click()
        assert "not saved" in dialog.status.text()
        assert dialog.decision.currentData() is None
        assert not dialog.save_button.isEnabled()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store.source_overlap_pair(root, alias).state == "repeat"
            assert store.source_overlap_pair(root, outsider).state == "pending"
            assert not store._active_consumed()
    finally:
        dialog.close()
        app.processEvents()


def test_posted_retained_root_with_support_can_repair_an_eligible_outsider(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "root-repair.db"
    root, alias, outsider = _profile(profile, ("01/02/2026", "01/01/2026", "01/03/2026"))
    _review(profile, root, alias, "repeat", root)
    _review(profile, root, outsider, "distinct")
    _review(profile, alias, outsider, "distinct")
    with V2ProfileStore.open(profile) as store:
        store.post_reviewed_cash_category(root, "expense:food", reason="Retained interpretation")
        store.post_reviewed_cash_category(outsider, "expense:food", reason="Initially independent interpretation")
    _review(profile, alias, outsider, "pending")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = V2SourceOverlapReview(profile)
    try:
        pair = _select(dialog, root, outsider)
        _choose(dialog, "retain_left" if pair.left.row_id == root else "retain_right")
        assert dialog.repair_button.isEnabled()
        assert not dialog.save_button.isEnabled()
        dialog.repair_button.click()
        assert "repair is recorded" in dialog.status.text()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store._active_consumed() == {root: -400}
            pair = store.source_overlap_pair(alias, outsider)
            assert pair.state == "repeat" and len(pair.left_group_row_ids) == 3
    finally:
        dialog.close()
        app.processEvents()


def test_direct_lookup_and_inventory_failures_clear_stale_controls(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview

    profile = tmp_path / "refused.db"
    root, alias, outsider = _profile(profile, ("01/03/2026", "01/01/2026", "12/30/2025"))
    _review(profile, root, alias, "repeat", root)
    dialog = V2SourceOverlapReview(profile)

    def refuse(*_args, **_kwargs):
        raise ProfileFormatError("synthetic_read_refusal")

    try:
        _select(dialog, alias, outsider)
        _choose(dialog, "distinct")
        assert dialog.save_button.isEnabled()
        monkeypatch.setattr(V2ProfileStore, "source_overlap_pair", refuse)
        dialog.open_saved_pair.click()
        assert "could not be opened" in dialog.status.text()
        assert not dialog.save_button.isEnabled()
        assert dialog.decision.currentData() is None
        monkeypatch.setattr(V2ProfileStore, "source_overlap_inventory", refuse)
        dialog.refresh()
        assert dialog.table.rowCount() == 0
        assert dialog.saved_pair.count() == 0
        assert not dialog.open_saved_pair.isEnabled()
        assert not dialog.save_button.isEnabled()
        assert not dialog.repair_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()

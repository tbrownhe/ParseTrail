"""Reviewed report inspection shares scope, money and immutable provenance."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_report_drilldown import read_reviewed_entry_drilldown
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_category_reports import DEFINITION, SOURCE

START, END = date(2026, 10, 1), date(2026, 11, 1)


def _profile(path: Path):
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    coffee, tea, deposit = evidence.payload.rows
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
        store.add_category_account("income:pay", "Pay", "income")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        original = store.post_reviewed_cash_category(coffee.row_id, "expense:food", reason="Reviewed coffee")
        corrected = store.correct_reviewed_cash_category(original, "expense:travel", reason="Correct coffee category")
        tea_key = store.post_reviewed_cash_category(tea.row_id, "expense:food", reason="Reviewed tea")
        store.post_reviewed_cash_category(deposit.row_id, "income:pay", reason="Reviewed income")
    return evidence, corrected, tea_key


def test_drilldown_matches_common_category_income_and_movement_scope_without_writes(tmp_path):
    profile = tmp_path / "fresh.db"
    _evidence, coffee_key, tea_key = _profile(profile)
    before = profile.read_bytes()
    food = read_reviewed_entry_drilldown(profile, "expense:food", start=START, end=END)
    travel = read_reviewed_entry_drilldown(profile, "expense:travel", start=START, end=END)
    income = read_reviewed_entry_drilldown(profile, "income:pay", start=START, end=END)
    movement = read_reviewed_entry_drilldown(profile, "cash", start=START, end=END)
    assert (food.total_minor, travel.total_minor, income.total_minor, movement.total_minor) == (300, 400, 1000, 300)
    assert [entry.key for entry in food.entries] == [tea_key]
    assert travel.entries[0].key == coffee_key and len(travel.corrections) == 1
    assert food.corrections == ()
    coffee = next(entry for entry in movement.entries if entry.key == coffee_key)
    tea = next(entry for entry in movement.entries if entry.key == tea_key)
    assert len(movement.entry_history(coffee)[0]) == 1
    assert movement.entry_history(tea) == ((), ())
    with V2ProfileStore.open(profile, read_only=True) as store:
        spending = store.reviewed_category_summary(kind="expense", start=START, end=END)
        assert food.total_minor + travel.total_minor == spending.total_minor
        assert income.total_minor == store.reviewed_category_summary(kind="income", start=START, end=END).total_minor
        assert (
            movement.total_minor
            == store.financial_journal_summary(start=START, end=END).accounts[0].nonopening_change_minor
        )
    assert profile.read_bytes() == before


def test_card_date_restating_keeps_out_of_period_correction_links_and_liability_sign(tmp_path):
    profile = tmp_path / "card.db"
    evidence = _chase_profile(profile)
    source_account = evidence.payload.accounts[0]
    with V2ProfileStore.open(profile) as store:
        store.bind_source_account(
            evidence.source_sha256, source_account.source_identity, source_account.source_identity_form, "card"
        )
        original = store.post_reviewed_card_purchase(
            source_account.rows[0].row_id,
            "expense:food",
            reason="Reviewed charge",
            preferences=V2Preferences(False, True),
        )
    march = read_reviewed_entry_drilldown(profile, "card", start=date(2026, 3, 1), end=date(2026, 4, 1))
    assert march.total_minor == 1000
    with V2ProfileStore.open(profile) as store:
        replacement = store.correct_reviewed_card_purchase(
            original, "expense:food", reason="Corrected actual posting date", accounting_date=date(2026, 4, 1)
        )
    old_period = read_reviewed_entry_drilldown(profile, "card", start=date(2026, 3, 1), end=date(2026, 4, 1))
    current = read_reviewed_entry_drilldown(profile, "expense:food", start=date(2026, 4, 1), end=date(2026, 5, 1))
    assert old_period.total_minor == 0 and old_period.entries == ()
    assert current.total_minor == 1000 and current.entries[0].key == replacement
    assert current.corrections[0].original_key == original
    assert current.corrections[0].replacement_key == replacement
    assert current.report.corrections == ()  # Export-period audit links are narrower.
    related = current.related_entries(current.entries[0])
    assert {entry.key for entry in related} == {original, current.corrections[0].reversal_key}
    assert {entry.posting_date for entry in related} == {date(2026, 3, 16)}


def test_withdrawn_history_is_related_to_fresh_entry_without_reviving_old_money(tmp_path):
    profile = tmp_path / "withdrawn.db"
    evidence, _coffee, old_tea = _profile(profile)
    with V2ProfileStore.open(profile) as store:
        snapshot = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        store.withdraw_reviewed_interpretation(
            old_tea, expected_basis_sha256=snapshot.basis_sha256, reason="Withdraw unsupported interpretation"
        )
        new = store.post_reviewed_cash_category(
            evidence.payload.rows[1].row_id, "expense:food", reason="Fresh reviewed tea"
        )
    report = read_reviewed_entry_drilldown(profile, "expense:food", start=START, end=END)
    assert report.total_minor == 300 and [entry.key for entry in report.entries] == [new]
    assert new != old_tea and report.retirements[0].original_key == old_tea
    assert {entry.key for entry in report.related_entries(report.entries[0])} == {
        old_tea,
        report.retirements[0].reversal_key,
    }


def test_retained_repeat_entry_keeps_related_cross_source_retirement_links(tmp_path):
    from .test_v2_source_interpretation_repair import _posted_pair, _repair

    profile = tmp_path / "repaired.db"
    with V2ProfileStore.create(profile) as store:
        first, second, retained, redundant = _posted_pair(store)
        _repair(store, first.payload.rows[0].row_id, second.payload.rows[0].row_id)
    before = profile.read_bytes()
    report = read_reviewed_entry_drilldown(profile, "expense:food", start=START, end=END)
    assert report.total_minor == 400 and [entry.key for entry in report.entries] == [retained]
    assert report.retirements[0].original_key == redundant
    assert report.entry_history(report.entries[0])[1] == report.retirements
    assert profile.read_bytes() == before


def test_drilldown_one_snapshot_preserves_rows_and_audit_links_during_concurrent_correction(tmp_path, monkeypatch):
    profile = tmp_path / "concurrent.db"
    _evidence, _coffee, tea = _profile(profile)
    with V2ProfileStore.open(profile) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
    original = V2ProfileStore.reviewed_journal_export

    def change_after_entries_read(store, *, start, end):
        report = original(store, start=start, end=end)
        with V2ProfileStore.open(profile) as other:
            other.correct_reviewed_cash_category(tea, "expense:travel", reason="Concurrent reviewed correction")
        return report

    monkeypatch.setattr(V2ProfileStore, "reviewed_journal_export", change_after_entries_read)
    report = read_reviewed_entry_drilldown(profile, "expense:food", start=START, end=END)
    assert report.total_minor == 300 and report.entries[0].key == tea and report.corrections == ()
    monkeypatch.setattr(V2ProfileStore, "reviewed_journal_export", original)
    current = read_reviewed_entry_drilldown(profile, "expense:food", start=START, end=END)
    assert current.total_minor == 0 and current.entries == ()


def test_invalid_scope_and_empty_month_are_unknown_activity_not_missing_money(tmp_path):
    profile = tmp_path / "scope.db"
    _profile(profile)
    with pytest.raises(ProfileFormatError, match="drilldown_account_missing"):
        read_reviewed_entry_drilldown(profile, "missing", start=START, end=END)
    with pytest.raises(ProfileFormatError, match="report_period_invalid"):
        read_reviewed_entry_drilldown(profile, "cash", start=END, end=START)
    empty = read_reviewed_entry_drilldown(profile, "cash", start=END, end=date(2026, 12, 1))
    assert empty.entries == () and empty.total_minor == 0


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_dialog_preview_reads_saved_source_and_failed_refresh_clears_stale_values(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_report_drilldown import V2ReviewedEntryDrilldown

    profile = tmp_path / "dialog.db"
    evidence, _coffee, _tea = _profile(profile)
    before = profile.read_bytes()
    seen = []

    class Preview:
        def __init__(self, saved, _parent):
            seen.append(saved)

        def exec(self):
            return 0

    monkeypatch.setattr("parsetrail.gui.v2_report_drilldown.V2EvidencePreview", Preview)
    dialog = V2ReviewedEntryDrilldown(profile, "expense:food", start=START, end=END, expected_total_minor=700)
    try:
        assert dialog.model.rowCount() == 1 and "$3.00" in dialog.total.text()
        assert "changed since" in dialog.stale_note.text()
        assert dialog.preview.isEnabled()
        dialog.preview.click()
        assert seen[0].source == SOURCE and seen[0].evidence == evidence

        def unavailable(*_args, **_kwargs):
            raise ProfileFormatError("synthetic_read_failure")

        monkeypatch.setattr("parsetrail.gui.v2_report_drilldown.read_reviewed_entry_drilldown", unavailable)
        dialog.refresh()
        assert dialog.model.rowCount() == 0 and dialog.total.text() == ""
        assert not dialog.preview.isEnabled() and dialog.source.count() == 0
    finally:
        dialog.close()
        app.processEvents()
    assert profile.read_bytes() == before


def test_parent_inspection_uses_selected_category_account_and_budget_month(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_report_drilldown import V2ReviewedEntryDrilldown
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate

    profile = tmp_path / "parent.db"
    _profile(profile)
    before = profile.read_bytes()
    seen = []
    monkeypatch.setattr(V2ReviewedEntryDrilldown, "exec", lambda dialog: seen.append(dialog.drilldown) or 0)
    dialog = V2ReviewedReportsDialog(profile)
    try:
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 11, 1))
        for tab, table in ((0, dialog.table), (1, dialog.account_table), (3, dialog.income_table)):
            dialog.tabs.setCurrentIndex(tab)
            table.selectRow(0)
            assert dialog.inspect_button.isEnabled()
            dialog.inspect_button.click()
        assert [report.account.id for report in seen] == ["expense:food", "cash", "income:pay"]
        assert [report.total_minor for report in seen] == [300, 300, 1000]
        dialog.end.setDate(QDate(2026, 10, 1))  # Invalid global range cannot change budget scope.
        dialog.tabs.setCurrentIndex(2)
        dialog.budget_month.setDate(QDate(2026, 10, 1))
        dialog.budget_table.selectRow(0)
        dialog.inspect_button.click()
        assert seen[-1].report.start == START and seen[-1].report.end == END
        assert seen[-1].total_minor == 300
        dialog.tabs.setCurrentIndex(4)
        assert not dialog.inspect_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()
    assert profile.read_bytes() == before


@pytest.mark.parametrize("refresh_path", ["period", "budget", "positions"])
def test_malformed_journal_clears_parent_reports_and_can_refresh_after_valid_restore(tmp_path, app, refresh_path):
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate

    profile = tmp_path / "corrupt.db"
    _evidence, _coffee, tea = _profile(profile)

    def replace_payload(payload):
        with sqlite3.connect(profile) as connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='immutable_JournalEntries_update'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER immutable_JournalEntries_update")
            connection.execute("UPDATE JournalEntries SET payload=? WHERE key=?", (payload, tea))
            connection.execute(trigger)

    with V2ProfileStore.open(profile, read_only=True) as store:
        original = store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (tea,)).fetchone()[0]
    dialog = V2ReviewedReportsDialog(profile)
    dialog.start.setDate(QDate(2026, 10, 1))
    dialog.end.setDate(QDate(2026, 11, 1))
    assert dialog.model.rowCount() == 2 and dialog.export_button.isEnabled()
    invalid = json.loads(original)
    invalid["postings"][1]["amount_minor"] += 1
    replace_payload(json.dumps(invalid))
    before = profile.read_bytes()
    try:
        {"period": dialog.refresh, "budget": dialog._refresh_budget, "positions": dialog._refresh_positions}[
            refresh_path
        ]()
        assert "unavailable" in dialog.total.text()
        assert not dialog.export_button.isEnabled() and not dialog.inspect_button.isEnabled()
        assert dialog.model.rowCount() == dialog.income_model.rowCount() == dialog.account_model.rowCount() == 0
        assert dialog.budget_model.rowCount() == dialog.positions_model.rowCount() == 0
        assert profile.read_bytes() == before
        replace_payload(original)
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 11, 1))
        dialog.budget_month.setDate(QDate(2026, 10, 1))
        dialog.refresh_reports_button.click()
        assert dialog.export_button.isEnabled()
        assert dialog.model.rowCount() == dialog.budget_model.rowCount() == 2
        assert dialog.positions_model.rowCount() == 1
        assert "$7.00" in dialog.total.text()
    finally:
        dialog.close()
        app.processEvents()

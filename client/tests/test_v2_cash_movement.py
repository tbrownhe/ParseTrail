"""Selected-asset movement reuses the reviewed books and exact transfer dates."""

from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest
from parsetrail.core.v2_cash_movement import read_cash_movement
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_report_drilldown import END, START, _profile
from .test_v2_transfer_corrections import _alternative
from .test_v2_transfers import BANK_DEFINITION
from .test_v2_transfers import _profile as payment_profile

JAN, FEB = date(2026, 1, 1), date(2026, 2, 1)


def _read(profile, accounts=("checking",), *, start=JAN, end=FEB):
    return read_cash_movement(profile, accounts, start=start, end=end)


def _post_payment(profile, day):
    outgoing, incoming = payment_profile(profile, bank_date=day)
    with V2ProfileStore.open(profile) as store:
        event = store.post_reviewed_transfer(outgoing, incoming, preferences=V2Preferences(), reason="Reviewed payment")
    return outgoing, incoming, event


def _asset_transfer(profile, *, incoming_day="01/05/2026"):
    outgoing_source = (
        b"Date,Account,Description,Amount,ReportedBalance\n01/03/2026,Checking A,Transfer,-$20.00,$980.00\n"
    )
    incoming_source = (
        f"Date,Account,Description,Amount,ReportedBalance\n{incoming_day},Savings B,Transfer,$20.00,$1020.00\n".encode()
    )
    with V2ProfileStore.create(profile) as store:
        for source, identity, account_id in (
            (outgoing_source, "Checking A", "checking"),
            (incoming_source, "Savings B", "savings"),
        ):
            evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
            store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
            store.add_financial_account(FinancialAccount(account_id, account_id.title(), "asset", "synthetic"))
            store.bind_source_account(evidence.source_sha256, identity, "opaque", account_id)
        pair = store.transfer_candidates(preferences=V2Preferences())[0]
        store.post_reviewed_transfer(
            pair.outgoing.row_id, pair.incoming.row_id, preferences=V2Preferences(), reason="Reviewed owned transfer"
        )


def test_income_expense_and_corrections_equal_common_selected_movement_without_writes(tmp_path):
    profile = tmp_path / "cash.db"
    _profile(profile)
    before = profile.read_bytes()
    report = _read(profile, ("cash",), start=START, end=END)
    assert report.total_minor == 300
    assert [(bucket.classification, bucket.amount_minor) for bucket in report.buckets] == [
        ("income", 1000),
        ("expense", -700),
    ]
    assert len(report.rows) == 3 and report.outside_scope_entries == 0
    with V2ProfileStore.open(profile, read_only=True) as store:
        movement = store.financial_journal_summary(start=START, end=END)
        assert report.total_minor == movement.accounts[0].nonopening_change_minor
        assert sum(row.amount_minor for row in report.buckets) == report.total_minor
        assert (
            -next(bucket.amount_minor for bucket in report.buckets if bucket.classification == "expense")
            == store.reviewed_category_summary(kind="expense", start=START, end=END).total_minor
        )
    assert profile.read_bytes() == before


def test_card_purchase_is_spending_without_selected_asset_movement(tmp_path):
    profile = tmp_path / "card.db"
    evidence = _chase_profile(profile)
    with V2ProfileStore.open(profile) as store:
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        store.post_reviewed_card_purchase(
            account.rows[0].row_id, "expense:food", reason="Reviewed charge", preferences=V2Preferences(False, True)
        )
    report = _read(profile, start=date(2026, 3, 1), end=date(2026, 4, 1))
    assert report.total_minor == 0 and report.rows == () and report.outside_scope_entries == 1
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert (
            store.reviewed_category_summary(
                kind="expense", start=report.journal.start, end=report.journal.end
            ).total_minor
            == 1000
        )
    with pytest.raises(ProfileFormatError, match="scope_invalid"):
        _read(profile, ("card",), start=date(2026, 3, 1), end=date(2026, 4, 1))


@pytest.mark.parametrize("bank_day,records", [("01/03/2026", 2), ("01/05/2026", 1)])
def test_card_payment_is_one_cash_outflow_and_keeps_counterpart_dates(tmp_path, bank_day, records):
    profile = tmp_path / "payment.db"
    _post_payment(profile, bank_day)
    before = profile.read_bytes()
    report = _read(profile)
    assert len(report.rows) == 1 and report.total_minor == -2000
    assert report.rows[0].classification == "card_payment"
    assert report.outside_scope_entries == records - 1
    assert "2026-01-05" in report.rows[0].event_note
    if records == 2:
        assert report.rows[0].entry.posting_date == date(2026, 1, 3)
        only_counterpart = _read(profile, start=date(2026, 1, 4), end=date(2026, 1, 6))
        assert only_counterpart.rows == () and only_counterpart.total_minor == 0
        assert only_counterpart.outside_scope_entries == 1
    assert profile.read_bytes() == before


@pytest.mark.parametrize("incoming_day,records", [("01/03/2026", 1), ("01/05/2026", 2)])
def test_owned_transfers_inside_outside_scope_and_partial_period_do_not_become_expenses(
    tmp_path, incoming_day, records
):
    profile = tmp_path / "owned.db"
    _asset_transfer(profile, incoming_day=incoming_day)
    outgoing = _read(profile)
    incoming = _read(profile, ("savings",))
    both = _read(profile, ("checking", "savings"))
    assert outgoing.total_minor == -2000 and incoming.total_minor == 2000 and both.total_minor == 0
    assert outgoing.rows[0].classification == incoming.rows[0].classification == "owned_transfer"
    assert len(both.rows) == records and {row.classification for row in both.rows} == {"within_scope_transfer"}
    assert not any(bucket.classification == "expense" for bucket in both.buckets)
    if records == 2:
        in_transit = _read(profile, ("checking", "savings"), end=date(2026, 1, 4))
        assert in_transit.total_minor == -2000 and in_transit.rows[0].classification == "within_scope_transfer"
    else:
        assert len(both.rows[0].account_effects) == 2


def test_replacement_and_withdrawal_change_classification_without_reviving_old_money(tmp_path):
    profile = tmp_path / "replace.db"
    outgoing, _incoming, event = _post_payment(profile, "01/03/2026")
    with V2ProfileStore.open(profile) as store:
        savings = _alternative(store)
        frame = store.transfer_review_snapshot(preferences=V2Preferences(), replacing_event_id=event)
        replacement = store.replace_reviewed_transfer(
            event,
            outgoing,
            savings,
            preferences=V2Preferences(),
            expected_basis_sha256=frame.basis_sha256,
            reason="Correct destination",
        )
    corrected = _read(profile)
    assert corrected.total_minor == -2000 and corrected.rows[0].classification == "owned_transfer"
    with V2ProfileStore.open(profile) as store:
        frame = store.transfer_review_snapshot(preferences=V2Preferences())
        store.withdraw_reviewed_transfer(
            replacement, expected_basis_sha256=frame.basis_sha256, reason="Withdraw unsupported event"
        )
    assert _read(profile).rows == () and _read(profile).total_minor == 0


def test_scope_is_explicit_and_unknown_reviewed_shape_is_not_inferred_from_categories(tmp_path):
    profile = tmp_path / "scope.db"
    _profile(profile)
    for accounts, code in (
        ((), "scope_required"),
        (("cash", "cash"), "scope_required"),
        (("missing",), "scope_invalid"),
        (("expense:food",), "scope_invalid"),
    ):
        with pytest.raises(ProfileFormatError, match=code):
            _read(profile, accounts, start=START, end=END)
    with pytest.raises(ProfileFormatError, match="report_period_invalid"):
        _read(profile, ("cash",), start=END, end=START)
    payload = {
        "key": "synthetic:unsupported",
        "event_id": "synthetic:unsupported",
        "posting_date": "2026-10-04",
        "description": "Unsupported reviewed shape",
        "origin": "manual",
        "reviewed": True,
        "reason": "Synthetic unknown classification boundary",
        "postings": [
            {"account_id": "cash", "amount_minor": 123, "allocations": []},
            {"account_id": "income:pay", "amount_minor": -123, "allocations": []},
        ],
    }
    with V2ProfileStore.open(profile) as store:
        store.connection.execute(
            "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (payload["key"], json.dumps(payload))
        )
    report = _read(profile, ("cash",), start=START, end=END)
    assert report.total_minor == 423
    assert [(row.classification, row.amount_minor) for row in report.rows if row.entry.key == payload["key"]] == [
        ("unclassified", 123)
    ]


def test_concurrent_withdrawal_after_rows_read_cannot_mix_old_money_and_new_event_metadata(tmp_path, monkeypatch):
    profile = tmp_path / "snapshot.db"
    _outgoing, _incoming, event = _post_payment(profile, "01/03/2026")
    with V2ProfileStore.open(profile) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
    original = V2ProfileStore.reviewed_journal_export

    def change_after_read(store, *, start, end):
        report = original(store, start=start, end=end)
        with V2ProfileStore.open(profile) as other:
            frame = other.transfer_review_snapshot(preferences=V2Preferences())
            other.withdraw_reviewed_transfer(
                event, expected_basis_sha256=frame.basis_sha256, reason="Concurrent withdrawal"
            )
        return report

    monkeypatch.setattr(V2ProfileStore, "reviewed_journal_export", change_after_read)
    report = _read(profile)
    assert report.total_minor == -2000 and report.rows[0].classification == "card_payment"
    monkeypatch.setattr(V2ProfileStore, "reviewed_journal_export", original)
    assert _read(profile).rows == ()


def test_openings_and_unreviewed_entries_stay_excluded_and_empty_period_is_only_recorded_scope(tmp_path):
    from .test_v2_statement_journal_comparison import _profile as statement_profile
    from .test_v2_statement_reconciliation import _review_and_post

    profile = tmp_path / "opening.db"
    evidence = statement_profile(profile)
    with V2ProfileStore.open(profile) as store:
        _review_and_post(store, evidence)
        pending = {
            "key": "synthetic:unreviewed",
            "event_id": "synthetic:unreviewed",
            "posting_date": "2026-01-10",
            "description": "Unreviewed structural fixture",
            "origin": "manual",
            "reviewed": False,
            "reason": "",
            "postings": [
                {"account_id": "cash", "amount_minor": 123, "allocations": []},
                {"account_id": "income:interest", "amount_minor": -123, "allocations": []},
            ],
        }
        store.connection.execute(
            "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (pending["key"], json.dumps(pending))
        )
    before = profile.read_bytes()
    report = _read(profile, ("cash",), start=date(2025, 12, 1))
    assert report.total_minor == -1000 and len(report.rows) == 2
    assert report.journal.excluded_opening_entries == report.journal.excluded_unreviewed_entries == 1
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert (
            report.total_minor
            == store.financial_journal_summary(start=report.journal.start, end=FEB).accounts[0].nonopening_change_minor
        )
        assert store.account_positions(as_of=date(2026, 1, 31)).accounts[0].position_debit_minor == 9000
    empty = _read(profile, ("cash",), start=FEB, end=date(2026, 3, 1))
    assert empty.total_minor == 0 and empty.rows == ()
    assert profile.read_bytes() == before


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_dialog_requires_scope_previews_saved_sources_inspects_common_entries_and_clears_failures(
    tmp_path, app, monkeypatch
):
    from parsetrail.gui.v2_cash_movement import V2CashMovementDialog
    from parsetrail.gui.v2_report_drilldown import V2ReviewedEntryDrilldown
    from PySide6.QtCore import QDate, Qt

    profile = tmp_path / "dialog.db"
    evidence, _coffee, _tea = _profile(profile)
    seen, inspected = [], []

    class Preview:
        def __init__(self, saved, _parent):
            seen.append(saved)

        def exec(self):
            return 0

    monkeypatch.setattr("parsetrail.gui.v2_cash_movement.V2EvidencePreview", Preview)
    monkeypatch.setattr(V2ReviewedEntryDrilldown, "exec", lambda dialog: inspected.append(dialog.drilldown) or 0)
    before = profile.read_bytes()
    dialog = V2CashMovementDialog(profile)
    try:
        assert dialog.report is None and not dialog.inspect.isEnabled() and not dialog.preview.isEnabled()
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 11, 1))
        dialog.accounts.item(0).setCheckState(Qt.Checked)
        assert dialog.entries.rowCount() == 3 and "$3.00" in dialog.total.text()
        dialog.preview.click()
        assert seen[0].evidence == evidence
        dialog.inspect.click()
        assert inspected[0].total_minor == 300 and inspected[0].account.id == "cash"
        assert profile.read_bytes() == before
        key = dialog.report.rows[0].entry.key
        with sqlite3.connect(profile) as connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='immutable_JournalEntries_update'"
            ).fetchone()[0]
            payload = json.loads(
                connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[0]
            )
            payload["postings"][1]["amount_minor"] += 1
            connection.execute("DROP TRIGGER immutable_JournalEntries_update")
            connection.execute("UPDATE JournalEntries SET payload=? WHERE key=?", (json.dumps(payload), key))
            connection.execute(trigger)
        corrupt = profile.read_bytes()
        dialog.refresh()
        assert dialog.report is None and "unavailable" in dialog.total.text()
        assert dialog.entries.rowCount() == dialog.summary.rowCount() == dialog.sources.count() == 0
        assert dialog.details.toPlainText() == "" and not dialog.preview.isEnabled() and not dialog.inspect.isEnabled()
        assert profile.read_bytes() == corrupt
    finally:
        dialog.close()
        app.processEvents()


def test_workspace_reports_menu_opens_explicit_scope_dialog(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_cash_movement import V2CashMovementDialog
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    from .test_v2_workspace_window import _workspace

    workspace = _workspace(tmp_path)
    seen = []
    monkeypatch.setattr(V2CashMovementDialog, "exec", lambda dialog: seen.append((dialog.profile, dialog.report)) or 0)
    window = V2WorkspaceWindow(workspace)
    try:
        window.cash_movement_action.trigger()
        assert seen == [(workspace.profile_path, None)]
    finally:
        window.close()
        app.processEvents()


def test_duplicate_account_names_remain_distinguishable_in_scope_and_inspection(tmp_path, app):
    from parsetrail.core.v2_cash_movement import cash_account_labels
    from parsetrail.gui.v2_cash_movement import V2CashMovementDialog
    from PySide6.QtCore import QDate, Qt

    profile = tmp_path / "duplicate-names.db"
    _profile(profile)
    with V2ProfileStore.open(profile) as store:
        store.update_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic", "11110001"))
        store.add_financial_account(FinancialAccount("cash2", "Checking", "asset", "synthetic", "22220002"))
        source = b"Date,Account,Description,Amount,ReportedBalance\n10/06/2026,Checking B,Deposit,$5.00,$1005.00\n"
        evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
        store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Checking B", "opaque", "cash2")
        store.post_reviewed_cash_category(
            evidence.payload.rows[0].row_id, "income:pay", reason="Reviewed second account income"
        )
    dialog = V2CashMovementDialog(profile)
    try:
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 11, 1))
        choices = {
            dialog.accounts.item(index).data(Qt.UserRole): dialog.accounts.item(index)
            for index in range(dialog.accounts.count())
        }
        assert "ending 0001" in choices["cash"].text() and "ending 0002" in choices["cash2"].text()
        assert choices["cash"].text() != choices["cash2"].text()
        assert "11110001" not in choices["cash"].text()
        assert "Account ID: cash2" in choices["cash2"].toolTip()
        choices["cash2"].setCheckState(Qt.Checked)
        assert dialog.report.total_minor == 500 and "ending 0002" in dialog.inspect_account.currentText()
        choices["cash"].setCheckState(Qt.Checked)
        assert dialog.report.total_minor == 800
        assert len({dialog.inspect_account.itemText(index) for index in range(dialog.inspect_account.count())}) == 2
    finally:
        dialog.close()
        app.processEvents()
    fallback = cash_account_labels(
        (
            FinancialAccount("first", "Same", "asset", "synthetic"),
            FinancialAccount("second", "Same", "asset", "synthetic"),
        )
    )
    assert fallback["first"] != fallback["second"] and fallback["first"].startswith("ID first")

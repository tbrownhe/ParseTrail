"""Common financial reads refuse malformed money before reports can display it."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_category_reports import DEFINITION, SOURCE

START, END = date(2026, 10, 1), date(2026, 11, 1)


def _profile(path):
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    coffee, tea, deposit = evidence.payload.rows
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        for name in ("food", "travel"):
            store.add_category_account(f"expense:{name}", name.title(), "expense")
        store.add_category_account("income:pay", "Pay", "income")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        original = store.post_reviewed_cash_category(coffee.row_id, "expense:food", reason="Reviewed coffee")
        corrected = store.correct_reviewed_cash_category(original, "expense:travel", reason="Correct coffee category")
        tea_key = store.post_reviewed_cash_category(tea.row_id, "expense:food", reason="Reviewed tea")
        store.post_reviewed_cash_category(deposit.row_id, "income:pay", reason="Reviewed income")
    return evidence, corrected, tea_key


def _change_entry(path, key, edit, *, allocation=None):
    with sqlite3.connect(path) as connection:
        payload = json.loads(connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[0])
        edit(payload)
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_JournalEntries_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_JournalEntries_update")
        connection.execute("UPDATE JournalEntries SET payload=? WHERE key=?", (json.dumps(payload), key))
        connection.execute(trigger)
        if allocation is not None:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='immutable_JournalAllocations_update'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER immutable_JournalAllocations_update")
            connection.execute("UPDATE JournalAllocations SET amount_minor=? WHERE entry_key=?", (allocation, key))
            connection.execute(trigger)


@pytest.mark.parametrize(
    "corruption",
    [
        "unbalanced",
        "fractional",
        "balanced_fractional",
        "balanced_source_mismatch",
        "index_mismatch",
        "fractional_index",
        "single_posting",
        "zero_posting",
        "payload_blob",
    ],
)
def test_initial_ordinary_corruption_refuses_all_common_reads_and_backup(tmp_path: Path, corruption: str):
    profile = tmp_path / "initial.db"
    _evidence, _coffee, tea = _profile(profile)

    def edit(payload):
        if corruption == "unbalanced":
            payload["postings"][1]["amount_minor"] = 301
        elif corruption == "fractional":
            payload["postings"][1]["amount_minor"] = 300.5
        elif corruption == "balanced_fractional":
            payload["postings"][0]["amount_minor"] = -300.5
            payload["postings"][1]["amount_minor"] = 300.5
        elif corruption == "balanced_source_mismatch":
            payload["postings"][0]["amount_minor"] = -301
            payload["postings"][0]["allocations"][0]["amount_minor"] = -301
            payload["postings"][1]["amount_minor"] = 301
        elif corruption == "single_posting":
            payload["postings"] = payload["postings"][:1]
        elif corruption == "zero_posting":
            payload["postings"].append({"account_id": "expense:travel", "amount_minor": 0, "allocations": []})

    index_amount = {"index_mismatch": -299, "fractional_index": -300.5, "balanced_source_mismatch": -301}.get(
        corruption
    )
    _change_entry(profile, tea, edit, allocation=index_amount)
    if corruption == "payload_blob":
        with sqlite3.connect(profile) as connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='immutable_JournalEntries_update'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER immutable_JournalEntries_update")
            connection.execute("UPDATE JournalEntries SET payload=CAST(payload AS BLOB) WHERE key=?", (tea,))
            connection.execute(trigger)
    corrupted_bytes = profile.read_bytes()
    with V2ProfileStore.open(profile, read_only=True) as store:
        for read in (
            lambda: store.reviewed_journal_export(start=START, end=END),
            lambda: store.reviewed_category_summary(kind="expense", start=START, end=END),
            lambda: store.reviewed_category_summary(kind="income", start=START, end=END),
            lambda: store.financial_journal_summary(start=START, end=END),
            lambda: store.monthly_budget_summary(START),
            lambda: store.account_positions(as_of=date(2026, 10, 31)),
            store.statement_reconciliation_checks,
            store.reconciliation_snapshot,
            store._active_consumed,
        ):
            with pytest.raises(ProfileFormatError):
                read()
            assert not store.connection.in_transaction
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.snapshot_to(profile, tmp_path / "refused.db")
    assert profile.read_bytes() == corrupted_bytes
    assert not (tmp_path / "refused.db").exists() and not tuple(tmp_path.glob("*.partial"))


def test_balanced_corrupt_correction_inverse_cannot_change_common_totals(tmp_path: Path):
    profile = tmp_path / "inverse.db"
    _profile(profile)
    with V2ProfileStore.open(profile, read_only=True) as store:
        inverse = store.connection.execute("SELECT reversal_key FROM JournalCorrections").fetchone()[0]

    def edit(payload):
        payload["postings"][0]["amount_minor"] = 401
        payload["postings"][1]["amount_minor"] = -401

    _change_entry(profile, inverse, edit)
    with V2ProfileStore.open(profile, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="ordinary_journal_integrity"):
            store.reviewed_category_summary(kind="expense", start=START, end=END)
        with pytest.raises(ProfileFormatError, match="ordinary_journal_integrity"):
            store.account_positions(as_of=date(2026, 10, 31))
    with pytest.raises(ProfileFormatError, match="ordinary_journal_integrity"):
        V2ProfileStore.snapshot_to(profile, tmp_path / "refused.db")


def test_balanced_corrupt_historical_original_cannot_drift_original_inverse_math(tmp_path: Path):
    profile = tmp_path / "historical.db"
    _profile(profile)
    with V2ProfileStore.open(profile, read_only=True) as store:
        original = store.connection.execute("SELECT original_key FROM JournalCorrections").fetchone()[0]

    def edit(payload):
        payload["postings"][0]["amount_minor"] = -401
        payload["postings"][0]["allocations"][0]["amount_minor"] = -401
        payload["postings"][1]["amount_minor"] = 401

    _change_entry(profile, original, edit, allocation=-401)
    with V2ProfileStore.open(profile, read_only=True) as store:
        with pytest.raises(ProfileFormatError):
            store.reviewed_journal_export(start=START, end=END)
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.snapshot_to(profile, tmp_path / "refused.db")


def test_recorded_card_override_history_remains_valid_without_current_assumption_opt_in(tmp_path: Path):
    profile = tmp_path / "card.db"
    evidence = _chase_profile(profile)
    with V2ProfileStore.open(profile) as store:
        source = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, source.source_identity, source.source_identity_form, "card")
        key = store.post_reviewed_card_purchase(
            source.rows[0].row_id, "expense:food", reason="Reviewed with opt in", preferences=V2Preferences(False, True)
        )
        replacement = store.correct_reviewed_card_purchase(
            key, "expense:travel", reason="Reviewed actual date", accounting_date=date(2026, 4, 1)
        )
        march = store.reviewed_journal_export(start=date(2026, 3, 1), end=date(2026, 4, 1))
        april = store.reviewed_journal_export(start=date(2026, 4, 1), end=date(2026, 5, 1))
        assert march.entries == () and april.entries[0].key == replacement
        store._validate_common_journal_read()
    V2ProfileStore.snapshot_to(profile, tmp_path / "backup.db")


def test_valid_unreviewed_manual_entries_keep_pending_scope_and_are_excluded(tmp_path: Path):
    profile = tmp_path / "pending.db"
    _profile(profile)
    with V2ProfileStore.open(profile) as store:
        payload = {
            "key": "pending:manual",
            "event_id": "pending:manual",
            "posting_date": START.isoformat(),
            "description": "Unreviewed manual scope",
            "origin": "manual",
            "reviewed": False,
            "reason": "",
            "postings": [
                {"account_id": "cash", "amount_minor": 123, "allocations": []},
                {"account_id": "income:pay", "amount_minor": -123, "allocations": []},
            ],
        }
        store.connection.execute(
            "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (payload["key"], json.dumps(payload))
        )
        report = store.reviewed_journal_export(start=START, end=END)
        assert report.excluded_unreviewed_entries == 1 and len(report.entries) == 3
        assert store.reviewed_category_summary(kind="income", start=START, end=END).total_minor == 1_000
        positions = store.account_positions(as_of=date(2026, 10, 31)).accounts[0]
        assert positions.recorded_debit_minor == 300 and positions.excluded_unreviewed_entries == 1
    V2ProfileStore.snapshot_to(profile, tmp_path / "backup.db")

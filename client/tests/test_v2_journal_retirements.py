"""The retirement foundation has one inactive definition across ledger consumers."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore, _decode_journal
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_category_reports import DEFINITION, SOURCE
from .test_v2_opening_corrections import _correct, _new_source, _review
from .test_v2_reviewed_openings import _profile


def test_retired_replacement_releases_allocation_without_resurrecting_original_correction(tmp_path: Path) -> None:
    path = tmp_path / "retirement.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        original = store.post_reviewed_cash_category(evidence.payload.rows[0].row_id, "expense:food", reason="Reviewed")
        replacement = store.correct_reviewed_cash_category(original, "expense:travel", reason="Correct category")
        entry = _decode_journal(
            store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (replacement,)).fetchone()[0]
        )
        version_before = store._source_overlap_basis()
        store.connection.execute("BEGIN IMMEDIATE")
        inverse = store._retire_journal_entry(entry, reason="Synthetic internal foundation check")
        store.connection.execute("COMMIT")
        assert {original, replacement, inverse} <= store._inactive_journal_keys()
        assert store._active_journal_entries() == ()
        assert store._active_consumed() == {}
        assert store._active_reviewed_entries(evidence.source_sha256) == {}
        assert store._unallocated_activity_counts() == (3, 1)
        assert store._source_overlap_basis() != version_before
        assert not store.cash_activity_review_rows(evidence.source_sha256)[0].entry_key
        summary = store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1))
        assert summary.total_minor == 0
        movement = store.financial_journal_summary(start=summary.start, end=summary.end)
        assert movement.accounts[0].nonopening_change_minor == 0
        exported = store.reviewed_journal_export(start=summary.start, end=summary.end)
        assert exported.entries == () and len(exported.corrections) == len(exported.retirements) == 1
        assert exported.retirements[0].original_key == replacement
        with pytest.raises(ProfileFormatError, match="cash_correction_conflicts_with_prior_decision"):
            store.correct_reviewed_cash_category(original, "expense:travel", reason="Correct category")
        with pytest.raises(ProfileFormatError, match="cash_correction_original_inactive"):
            store.correct_reviewed_cash_category(replacement, "expense:food", reason="Retired cannot be corrected")
        with pytest.raises(ProfileFormatError, match="cash_review_already_corrected"):
            store.post_reviewed_cash_category(evidence.payload.rows[0].row_id, "expense:food", reason="Reviewed")
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="journal_retirement_original_inactive"):
            store._retire_journal_entry(entry, reason="Repeat inverse refused")
        store.connection.execute("ROLLBACK")


def test_retirement_and_opening_revisions_are_append_only_and_backup_independent(tmp_path: Path) -> None:
    path, backup = tmp_path / "opening.db", tmp_path / "backup.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        store.post_reviewed_opening("cash")
        _new_source(store, evidence, amount=0)
        decision = _correct(store)
        for table in ("JournalRetirements", "OpeningDecisionRevisions"):
            for action in (f"UPDATE {table} SET reason='rewrite'", f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
                    store.connection.execute(action)
        history = store.opening_decision_history("cash")
    before = path.read_bytes()
    V2ProfileStore.snapshot_to(path, backup)
    assert path.read_bytes() == before
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.opening_decision("cash") == decision
        assert store.opening_decision_history("cash") == history
        assert len(store._inactive_journal_keys()) == 2
        assert store.account_positions(as_of=date(2026, 1, 31)).accounts[0].position_debit_minor == 0


def test_revision_twelve_profile_is_refused_before_writable_initialization(tmp_path: Path) -> None:
    path = tmp_path / "earlier.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA user_version=12")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("field", ["amount", "date", "event", "account", "allocations", "reason", "origin", "reviewed"])
def test_corrupt_retirement_inverse_refuses_common_reads_and_backup(tmp_path: Path, field: str) -> None:
    path = tmp_path / "damaged.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        store.post_reviewed_opening("cash")
        _new_source(store, evidence, amount=0)
        _correct(store)
        inverse = store.connection.execute("SELECT reversal_key FROM JournalRetirements").fetchone()[0]
    with sqlite3.connect(path) as connection:
        payload = json.loads(
            connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (inverse,)).fetchone()[0]
        )
        if field == "amount":
            payload["postings"][0]["amount_minor"] = -9_999
            payload["postings"][1]["amount_minor"] = 9_999
        elif field == "date":
            payload["posting_date"] = "2025-12-30"
        elif field == "event":
            payload["event_id"] = "different-event"
        elif field == "account":
            payload["postings"].reverse()
        elif field == "allocations":
            payload["postings"][0]["allocations"] = [{"observation_id": "invented", "amount_minor": -10_000}]
        elif field == "reason":
            payload["reason"] = "Altered inverse reason"
        elif field == "origin":
            payload["origin"] = "opening"
        else:
            payload["reviewed"] = False
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_JournalEntries_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_JournalEntries_update")
        connection.execute("UPDATE JournalEntries SET payload=? WHERE key=?", (json.dumps(payload), inverse))
        connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        for read in (
            store._active_consumed,
            lambda: store.opening_decision_history("cash"),
            lambda: store.account_positions(as_of=date(2026, 1, 31)),
            lambda: store.financial_journal_summary(start=date(2025, 12, 1), end=date(2026, 2, 1)),
            lambda: store.reviewed_category_summary(kind="expense", start=date(2025, 12, 1), end=date(2026, 2, 1)),
        ):
            with pytest.raises(ProfileFormatError, match="journal_retirement_integrity"):
                read()
    with pytest.raises(ProfileFormatError, match="journal_retirement_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()


def test_retirement_inverse_cannot_also_participate_in_correction_graph(tmp_path: Path) -> None:
    path = tmp_path / "graph.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        initial = store.post_reviewed_opening("cash")
        _new_source(store, evidence, amount=0)
        _correct(store)
        inverse = store.connection.execute("SELECT reversal_key FROM JournalRetirements").fetchone()[0]
        store.connection.execute(
            "INSERT INTO JournalCorrections(original_key,reversal_key,replacement_key,reason) VALUES (?,?,?,?)",
            (initial.entry_key, inverse, initial.entry_key, "Corrupt overlapping history"),
        )
        with pytest.raises(ProfileFormatError, match="journal_retirement_integrity"):
            store._inactive_journal_keys()
    with pytest.raises(ProfileFormatError, match="journal_retirement_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")


def test_retirement_inverse_cannot_have_indexed_source_allocations(tmp_path: Path) -> None:
    path = tmp_path / "indexed.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        store.post_reviewed_opening("cash")
        _new_source(store, evidence, amount=0)
        _correct(store)
        inverse = store.connection.execute("SELECT reversal_key FROM JournalRetirements").fetchone()[0]
        row = evidence.payload.accounts[0].rows[0]
        store.connection.execute("INSERT INTO JournalAllocations VALUES (?,?,?)", (inverse, row.row_id, 10_000))
        with pytest.raises(ProfileFormatError, match="journal_retirement_integrity"):
            store._active_consumed()
    with pytest.raises(ProfileFormatError, match="journal_retirement_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")

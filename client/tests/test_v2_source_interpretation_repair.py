"""Ordinary withdrawal and posted-repeat repair retain exact financial history."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_report_export import write_reviewed_journal_workbook

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_source_overlap import review, setup, source
from .test_v2_statement_journal_comparison import _profile as bank_profile
from .test_v2_statement_reconciliation import _review_and_post
from .test_v2_transfers import _profile as transfer_profile


def _snapshot(store, evidence, *, kind="cash", preferences=None):
    return store.source_interpretation_snapshot(evidence.source_sha256, kind=kind, preferences=preferences)


def _posted_pair(store):
    setup(store)
    first, second = source(store, "First"), source(store, "Second")
    left, right = first.payload.rows[0].row_id, second.payload.rows[0].row_id
    review(store, left, right, decision="distinct", reason="Initially reviewed as separate")
    first_key = store.post_reviewed_cash_category(left, "expense:food", reason="First reviewed expense")
    second_key = store.post_reviewed_cash_category(right, "expense:other", reason="Second reviewed expense")
    return first, second, first_key, second_key


def _repair(store, retained, redundant, *, reason="Same occurrence in two sources"):
    pair = next(
        pair
        for pair in store.source_overlap_inventory().candidates
        if {pair.left.row_id, pair.right.row_id} == {retained, redundant}
    )
    return store.repair_posted_repeat(retained, redundant, expected_basis_sha256=pair.basis_sha256, reason=reason)


def test_withdraw_corrected_cash_chain_and_repost_never_revives_old_entries(tmp_path: Path) -> None:
    path = tmp_path / "cash.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        evidence = source(store, "Expense")
        row_id = evidence.payload.rows[0].row_id
        initial = store.post_reviewed_cash_category(row_id, "expense:food", reason="Reviewed expense")
        corrected = store.correct_reviewed_cash_category(initial, "expense:other", reason="Correct category")
        latest = store.correct_reviewed_cash_category(corrected, "expense:food", reason="Correct again")
        selected = _snapshot(store, evidence)
        assert selected.rows[0].entry_key == latest and selected.entries[0].key == latest
        action = store.withdraw_reviewed_interpretation(
            latest, expected_basis_sha256=selected.basis_sha256, reason="Interpretation is unsupported"
        )
        assert action.row_id == row_id and action.entry_key == latest and action.kind == "withdraw"
        assert store._active_consumed() == {}
        assert _snapshot(store, evidence).rows[0].status == "Ready for purpose review"
        assert (
            store.withdraw_reviewed_interpretation(
                latest, expected_basis_sha256=selected.basis_sha256, reason="Interpretation is unsupported"
            )
            == action
        )
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 0
        )
        fresh = _snapshot(store, evidence)
        posted = store.post_reviewed_cash_category(
            row_id, "expense:other", reason="New reviewed interpretation", expected_basis_sha256=fresh.basis_sha256
        )
        assert posted not in {initial, corrected, latest}
        assert (
            store.post_reviewed_cash_category(
                row_id, "expense:other", reason="New reviewed interpretation", expected_basis_sha256=fresh.basis_sha256
            )
            == posted
        )
        assert store._active_consumed() == {row_id: -400}
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 400
        )
        assert {initial, corrected, latest, action.reversal_key} <= store._inactive_journal_keys()
        assert _snapshot(store, evidence).history == (action,)


def test_card_date_correction_withdrawal_keeps_date_and_new_post_requires_fresh_review(tmp_path: Path) -> None:
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        purchase = account.rows[0].row_id
        initial = store.post_reviewed_card_purchase(
            purchase, "expense:food", reason="Assumed source date enabled", preferences=V2Preferences(False, True)
        )
        corrected = store.correct_reviewed_card_purchase(
            initial, "expense:travel", reason="Reviewed actual date", accounting_date=date(2026, 4, 1)
        )
        selected = _snapshot(store, evidence, kind="card", preferences=V2Preferences())
        action = store.withdraw_reviewed_interpretation(
            corrected, expected_basis_sha256=selected.basis_sha256, reason="Withdraw dated interpretation"
        )
        inverse = json.loads(
            store.connection.execute(
                "SELECT payload FROM JournalEntries WHERE key=?", (action.reversal_key,)
            ).fetchone()[0]
        )
        assert inverse["posting_date"] == "2026-04-01" and inverse["postings"][0]["amount_minor"] == 1000
        assert store._active_consumed() == {}
        selected = _snapshot(store, evidence, kind="card", preferences=V2Preferences())
        assert not selected.entries and selected.preferences == V2Preferences()
        with pytest.raises(ProfileFormatError, match="card_purchase_assumed_date_disabled"):
            store.post_reviewed_card_purchase(
                purchase,
                "expense:food",
                reason="No new assumption allowed",
                preferences=V2Preferences(),
                expected_basis_sha256=selected.basis_sha256,
            )
        posted = store.post_reviewed_card_purchase(
            purchase,
            "expense:food",
            reason="Explicit new reviewed date",
            preferences=V2Preferences(),
            accounting_date=date(2026, 4, 2),
            expected_basis_sha256=selected.basis_sha256,
        )
        assert posted not in {initial, corrected}
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 3, 1), end=date(2026, 4, 1)).total_minor
            == 0
        )
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 4, 1), end=date(2026, 5, 1)).total_minor
            == 1000
        )


def test_repair_posted_repeat_retires_only_redundant_entry_and_preserves_supporting_scope(tmp_path: Path) -> None:
    path = tmp_path / "repeat.db"
    with V2ProfileStore.create(path) as store:
        first, second, first_key, second_key = _posted_pair(store)
        retained, redundant = first.payload.rows[0].row_id, second.payload.rows[0].row_id
        selected = store.source_overlap_inventory().candidates[0]
        with pytest.raises(ProfileFormatError, match="source_overlap_excluded_has_journal_history"):
            review(store, retained, redundant, retained=retained)
        repaired = _repair(store, retained, redundant)
        assert repaired.retained_entry_key == first_key and repaired.redundant_entry_key == second_key
        assert store._active_consumed() == {retained: -400}
        assert store._unallocated_activity_counts() == (1, 1)  # Supporting evidence is not an allocation.
        assert store.source_overlap_inventory().candidates[0].state == "repeat"
        proof_pair = store.source_overlap_inventory().candidates[0]
        excluded = proof_pair.left if proof_pair.left.row_id == redundant else proof_pair.right
        assert excluded.repeat_support_history_validated and excluded.active_allocated_minor == 0
        assert (
            store.repair_posted_repeat(
                retained,
                redundant,
                expected_basis_sha256=selected.basis_sha256,
                reason="Same occurrence in two sources",
            )
            == repaired
        )
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 400
        )
        report = store.reviewed_journal_export(start=date(2026, 10, 1), end=date(2026, 11, 1))
        assert [entry.key for entry in report.entries] == [first_key]
        assert report.repeat_repairs == (repaired,) and len(report.source_actions) == 1
        workbook = load_workbook(write_reviewed_journal_workbook(report, tmp_path / "repaired.xlsx"), read_only=True)
        try:
            assert list(workbook["Repeat Repairs"].values)[1][1:5] == (retained, redundant, first_key, second_key)
        finally:
            workbook.close()
        corrected_root = store.correct_reviewed_cash_category(
            first_key, "expense:other", reason="Correct retained category"
        )
        assert store._active_consumed() == {retained: -400}
        assert store.source_overlap_inventory().candidates[0].state == "repeat"
        assert _snapshot(store, first).entries[0].key == corrected_root
        review(store, retained, redundant, decision="pending", reason="Reopen occurrence review")
        assert store._active_consumed() == {retained: -400}  # No automatic resurrection.
        pending = store.source_overlap_inventory().candidates[0]
        excluded = pending.left if pending.left.row_id == redundant else pending.right
        assert excluded.repeat_support_history_validated
        review(
            store, retained, redundant, retained=retained, reason="Reconfirm previously repaired supporting evidence"
        )
        assert store._active_consumed() == {retained: -400}
        review(store, retained, redundant, decision="pending", reason="Review distinct possibility")
        review(store, retained, redundant, decision="distinct", reason="Actually separate purchases")
        assert store._active_consumed() == {retained: -400}
        selected = _snapshot(store, second)
        reposted = store.post_reviewed_cash_category(
            redundant,
            "expense:food",
            reason="Reviewed separate occurrence",
            expected_basis_sha256=selected.basis_sha256,
        )
        assert reposted != second_key and store._active_consumed() == {retained: -400, redundant: -400}
        active_pair = store.source_overlap_inventory().candidates[0]
        excluded = active_pair.left if active_pair.left.row_id == redundant else active_pair.right
        assert not excluded.repeat_support_history_validated
        with pytest.raises(ProfileFormatError, match="source_overlap_excluded_has_journal_history"):
            review(store, retained, redundant, retained=retained)
        second_repair = _repair(store, retained, redundant, reason="Corrected repeat review again")
        assert second_repair.redundant_entry_key == reposted and second_repair.repair_id != repaired.repair_id


@pytest.mark.parametrize("failure", ["retirement", "action", "review", "repair"])
def test_repeat_repair_failures_roll_back_money_and_review_together(tmp_path: Path, failure: str) -> None:
    with V2ProfileStore.create(tmp_path / "atomic.db") as store:
        first, second, _first_key, _second_key = _posted_pair(store)
        retained, redundant = first.payload.rows[0].row_id, second.payload.rows[0].row_id
        table = {
            "retirement": "JournalRetirements",
            "action": "SourceInterpretationActions",
            "review": "SourceOverlapReviews",
            "repair": "PostedRepeatRepairs",
        }[failure]
        store.connection.execute(
            f"CREATE TRIGGER fail_repair BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
        with pytest.raises(sqlite3.DatabaseError):
            _repair(store, retained, redundant)
        store.connection.execute("DROP TRIGGER fail_repair")
        assert not store.connection.in_transaction
        assert store._active_consumed() == {retained: -400, redundant: -400}
        assert store.source_overlap_inventory().candidates[0].state == "distinct"
        assert store.connection.execute("SELECT COUNT(*) FROM JournalRetirements").fetchone() == (0,)
        assert store.connection.execute("SELECT COUNT(*) FROM SourceInterpretationActions").fetchone() == (0,)
        assert store.connection.execute("SELECT COUNT(*) FROM PostedRepeatRepairs").fetchone() == (0,)


def test_stale_source_frames_cannot_post_correct_withdraw_or_repair(tmp_path: Path) -> None:
    with V2ProfileStore.create(tmp_path / "stale.db") as store:
        setup(store)
        evidence = source(store, "Expense")
        row_id = evidence.payload.rows[0].row_id
        frame = _snapshot(store, evidence)
        store.rename_category_account("expense:food", "Food renamed")
        with pytest.raises(ProfileFormatError, match="source_interpretation_changed_since_selection"):
            store.post_reviewed_cash_category(
                row_id, "expense:food", reason="Stale post", expected_basis_sha256=frame.basis_sha256
            )
        key = store.post_reviewed_cash_category(row_id, "expense:food", reason="Current post")
        frame = _snapshot(store, evidence)
        store.rename_category_account("expense:other", "Other renamed")
        for operation in (
            lambda: store.correct_reviewed_cash_category(
                key, "expense:other", reason="Stale correction", expected_basis_sha256=frame.basis_sha256
            ),
            lambda: store.withdraw_reviewed_interpretation(
                key, expected_basis_sha256=frame.basis_sha256, reason="Stale withdrawal"
            ),
        ):
            with pytest.raises(ProfileFormatError, match="source_interpretation_changed_since_selection"):
                operation()
        assert store._active_consumed() == {row_id: -400}


def test_withdrawal_invalidates_saved_reconciliation_and_backup_retains_history(tmp_path: Path) -> None:
    path, backup = tmp_path / "profile.db", tmp_path / "backup.db"
    evidence = bank_profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        check = store.statement_reconciliation_checks()[0]
        saved = store.save_reconciliation_decision(
            "cash",
            evidence.source_sha256,
            expected_input_version=check.input_version,
            reason="Reviewed exact statement",
        )
        selected = _snapshot(store, evidence)
        key = next(row.entry_key for row in selected.rows if row.amount_minor < 0)
        action = store.withdraw_reviewed_interpretation(
            key, expected_basis_sha256=selected.basis_sha256, reason="Unresolved withdrawal interpretation"
        )
        assert store.reconciliation_history()[0].stale and store.reconciliation_history()[0].check == saved.check
        assert not store.statement_reconciliation_checks()[0].reconciled
        assert store.account_positions(as_of=date(2026, 1, 31)).accounts[0].current_saved_reconciled_cutoff is None
        assert store.monthly_budget_summary(date(2026, 1, 1)).total_reviewed_spending_minor == 0
    before = path.read_bytes()
    V2ProfileStore.snapshot_to(path, backup)
    assert path.read_bytes() == before
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert _snapshot(store, evidence).history == (action,)


def test_transfer_legs_are_refused_and_nested_transaction_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "transfer.db"
    outgoing, incoming = transfer_profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        event = store.post_reviewed_transfer(
            outgoing, incoming, preferences=V2Preferences(), reason="Reviewed transfer"
        )
        key = store.transfer_history()[0].entry_keys[0]
        basis = store._source_overlap_basis()
        with pytest.raises(ProfileFormatError, match="source_interpretation_unsupported"):
            store.withdraw_reviewed_interpretation(key, expected_basis_sha256=basis, reason="Cannot withdraw a leg")
        assert store.transfer_history()[0].event_id == event and store.transfer_history()[0].status == "active"
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError):
            store.withdraw_reviewed_interpretation(key, expected_basis_sha256=basis, reason="Nested refused")
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("SourceInterpretationActions", "request_basis", sqlite3.Binary(b"invalid")),
        ("SourceInterpretationActions", "original_sha256", "0" * 64),
        ("SourceInterpretationActions", "reason", "Altered action reason"),
        ("PostedRepeatRepairs", "request_basis", sqlite3.Binary(b"invalid")),
        ("PostedRepeatRepairs", "retained_sha256", "0" * 64),
        ("PostedRepeatRepairs", "review_sha256", "0" * 64),
        ("PostedRepeatRepairs", "reason", "Altered repair reason"),
    ],
)
def test_malformed_action_or_repair_refuses_reports_version_hashes_and_backup(
    tmp_path: Path, table: str, column: str, value
) -> None:
    path = tmp_path / "damaged.db"
    with V2ProfileStore.create(path) as store:
        first, second, _first_key, _second_key = _posted_pair(store)
        _repair(store, first.payload.rows[0].row_id, second.payload.rows[0].row_id)
    with sqlite3.connect(path) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (f"immutable_{table}_update",)
        ).fetchone()[0]
        connection.execute(f"DROP TRIGGER immutable_{table}_update")
        connection.execute(f"UPDATE {table} SET {column}=?", (value,))
        connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        for read in (
            lambda: _snapshot(store, first),
            store._active_consumed,
            store._source_overlap_basis,
            store._reconciliation_rule_and_version,
            lambda: store.reviewed_journal_export(start=date(2026, 10, 1), end=date(2026, 11, 1)),
        ):
            with pytest.raises(ProfileFormatError, match="source_interpretation_history_integrity"):
                read()
        assert not store.connection.in_transaction
    with pytest.raises(ProfileFormatError, match="source_interpretation_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()


def test_repair_history_and_actions_are_append_only_and_restore_independent(tmp_path: Path) -> None:
    path, backup = tmp_path / "profile.db", tmp_path / "backup.db"
    with V2ProfileStore.create(path) as store:
        first, second, _first_key, _second_key = _posted_pair(store)
        repaired = _repair(store, first.payload.rows[0].row_id, second.payload.rows[0].row_id)
        for table in ("SourceInterpretationActions", "PostedRepeatRepairs"):
            for sql in (f"UPDATE {table} SET reason='rewrite'", f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
                    store.connection.execute(sql)
        second_frame = _snapshot(store, second)
    before = path.read_bytes()
    V2ProfileStore.snapshot_to(path, backup)
    assert path.read_bytes() == before
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert _snapshot(store, second) == second_frame
        report = store.reviewed_journal_export(start=date(2026, 10, 1), end=date(2026, 11, 1))
        assert report.repeat_repairs == (repaired,)
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            store.repair_posted_repeat(
                repaired.retained_row_id,
                repaired.redundant_row_id,
                expected_basis_sha256=second_frame.basis_sha256,
                reason="Readonly repair refused",
            )


def test_composite_source_frame_is_coherent_during_concurrent_category_change(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "coherent.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        setup(store)
        evidence = source(store, "Expense")
        original = store.category_accounts

        def rename_after_categories_read():
            categories = original()
            with V2ProfileStore.open(path) as other:
                other.rename_category_account("expense:food", "Concurrent new label")
            return categories

        monkeypatch.setattr(store, "category_accounts", rename_after_categories_read)
        old = _snapshot(store, evidence)
        assert old.categories[0].name == "Food"
        monkeypatch.setattr(store, "category_accounts", original)
        current = _snapshot(store, evidence)
        assert current.categories[0].name == "Concurrent new label" and current.basis_sha256 != old.basis_sha256
        with pytest.raises(ProfileFormatError, match="source_interpretation_changed_since_selection"):
            store.post_reviewed_cash_category(
                evidence.payload.rows[0].row_id,
                "expense:food",
                reason="Old displayed form",
                expected_basis_sha256=old.basis_sha256,
            )


def test_repair_requires_both_fully_posted_and_preserves_same_source_multiplicity(tmp_path: Path) -> None:
    with V2ProfileStore.create(tmp_path / "refused.db") as store:
        setup(store)
        evidence = source(store, "Two genuine equal occurrences", count=2)
        first, second = evidence.payload.rows
        store.post_reviewed_cash_category(first.row_id, "expense:food", reason="First occurrence")
        store.post_reviewed_cash_category(second.row_id, "expense:food", reason="Second occurrence")
        with pytest.raises(ProfileFormatError, match="posted_repeat_requires_two_posted_occurrences"):
            store.repair_posted_repeat(
                first.row_id,
                second.row_id,
                expected_basis_sha256=store._source_overlap_basis(),
                reason="Same-source occurrences cannot collapse",
            )
        assert store._active_consumed() == {first.row_id: -400, second.row_id: -400}
        third = source(store, "Unposted repeat")
        with pytest.raises(ProfileFormatError, match="posted_repeat_requires_two_posted_occurrences"):
            store.repair_posted_repeat(
                first.row_id,
                third.payload.rows[0].row_id,
                expected_basis_sha256=store._source_overlap_basis(),
                reason="One is unposted",
            )
        assert store.connection.execute("SELECT COUNT(*) FROM PostedRepeatRepairs").fetchone() == (0,)


def test_revision_fourteen_profile_is_refused_before_writes(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA user_version=14")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before

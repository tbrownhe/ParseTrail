"""Reviewed binding changes preserve books and durably reopen occurrence review."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import (
    BindingCorrectionTarget,
    ProfileFormatError,
    V2ProfileStore,
)
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_account_bindings import DEFINITION, SOURCE
from .test_v2_reviewed_openings import _profile as opening_profile
from .test_v2_source_interpretation_repair import _posted_pair, _repair
from .test_v2_source_overlap import DEFINITION as CASH_DEFINITION
from .test_v2_source_overlap import account, review, setup, source
from .test_v2_statement_journal_comparison import _profile as bank_profile
from .test_v2_statement_reconciliation import _review_and_post
from .test_v2_transfers import _profile as transfer_profile


def target(evidence):
    row = evidence.payload.rows[0] if hasattr(evidence.payload, "rows") else evidence.payload.accounts[0]
    return BindingCorrectionTarget(
        evidence.source_sha256,
        "source",
        row.source_account if hasattr(row, "source_account") else row.source_identity,
        row.source_account_form if hasattr(row, "source_account_form") else row.source_identity_form,
    )


def change(store, selected, destination, reason="Reviewed correct account"):
    frame = store.binding_correction_snapshot(selected, destination_account_id=destination)
    return store.correct_reviewed_binding(
        frame.target, destination_account_id=destination, expected_basis_sha256=frame.basis_sha256, reason=reason
    )


def withdraw(store, key):
    return store.withdraw_reviewed_interpretation(
        key, expected_basis_sha256=store._source_overlap_basis(), reason="Withdraw before account repair"
    )


def test_source_correction_requires_withdrawal_preserves_historical_accounts_and_reposts_fresh(tmp_path):
    path = tmp_path / "source.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        account(store, "other")
        evidence = source(store, "Coffee")
        selected = target(evidence)
        row_id = evidence.payload.rows[0].row_id
        initial = store.post_reviewed_cash_category(row_id, "expense:food", reason="Reviewed coffee")
        key = store.correct_reviewed_cash_category(initial, "expense:other", reason="Correct category")
        frame = store.binding_correction_snapshot(selected, destination_account_id="other")
        assert frame.current_account_ids == ("cash",)
        assert frame.blockers == ("active_source_consumption",)
        with pytest.raises(ProfileFormatError, match="active_source_consumption"):
            change(store, selected, "other")
        withdraw(store, key)
        with pytest.raises(ProfileFormatError, match="account_binding_has_journal_history"):
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "other")
        before = store.connection.execute("SELECT * FROM JournalEntries ORDER BY key").fetchall()
        correction = change(store, selected, "other")
        assert correction.prior_account_ids == ("cash",) and correction.new_account_ids == ("other",)
        assert store.connection.execute("SELECT * FROM JournalEntries ORDER BY key").fetchall() == before
        assert store.account_bindings(evidence.source_sha256)[0].ledger_account_id == "other"
        fresh = store.post_reviewed_cash_category(row_id, "expense:food", reason="New account review")
        assert fresh not in {initial, key}
        assert store._ordinary_category_entry(fresh)[0].postings[0].account_id == "other"
        exported = store.reviewed_journal_export(start=date(2026, 10, 1), end=date(2026, 11, 1))
        assert exported.entries[0].postings[0].account_id == "other"
        assert store.binding_correction_history() == (correction,)
    backup = tmp_path / "backup.db"
    V2ProfileStore.snapshot_to(path, backup)
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.binding_correction_history() == (correction,)
        assert store._ordinary_category_entry(initial, active=False)[0].postings[0].account_id == "cash"


def test_file_and_selected_rows_require_clear_first_and_reconciliation_versions_include_all_modes(tmp_path):
    path = tmp_path / "accountless.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        account(store, "cash")
        account(store, "other")
        file_target = BindingCorrectionTarget(evidence.source_sha256, "file")
        rows = tuple(row.row_id for row in evidence.payload.rows)
        row_target = BindingCorrectionTarget(evidence.source_sha256, "rows", row_ids=rows)
        version = store._reconciliation_rule_and_version()[1]
        store.assert_file_account(evidence.source_sha256, "cash")
        assert store._reconciliation_rule_and_version()[1] != version
        assert (
            "file_mode_requires_clear"
            in store.binding_correction_snapshot(row_target, destination_account_id="other").blockers
        )
        change(store, file_target, "other")
        change(store, file_target, None)
        first = replace(row_target, row_ids=(rows[0],))
        with pytest.raises(ProfileFormatError, match="correction_history"):
            store.assign_rows_account(evidence.source_sha256, (rows[0],), "cash")
        change(store, first, "cash")
        version = store._reconciliation_rule_and_version()[1]
        change(store, replace(row_target, row_ids=(rows[1],)), "other")
        assert store._reconciliation_rule_and_version()[1] != version
        assert (
            "row_mode_requires_clear"
            in store.binding_correction_snapshot(file_target, destination_account_id="other").blockers
        )
        correction = change(store, row_target, "other")
        assert set(correction.prior_account_ids) == {"cash", "other"}
        change(store, first, None)
        assert store.account_bindings(evidence.source_sha256)[0].ledger_account_id is None
        change(store, replace(row_target, row_ids=(rows[1],)), None)
        change(store, file_target, "cash")
        assert all(b.basis == "file" for b in store.account_bindings(evidence.source_sha256))


def test_entire_connected_repeat_review_graph_invalidated_and_a_b_a_stays_pending(tmp_path):
    path = tmp_path / "repeat.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        account(store, "other")
        first, second, third = (source(store, label) for label in ("First", "Second", "Third"))
        left, middle, right = (e.payload.rows[0].row_id for e in (first, second, third))
        review(store, left, middle, retained=left)
        review(store, left, right, retained=left)
        selected = target(second)
        frame = store.binding_correction_snapshot(selected, destination_account_id="other")
        assert set(frame.affected_review_pairs) == {tuple(sorted((left, middle))), tuple(sorted((left, right)))}
        correction = change(store, selected, "other")
        assert len(correction.invalidated_review_ids) == 2
        assert not store._source_overlap_index()[3]
        change(store, selected, "cash")
        assert not store._source_overlap_index()[3]
        assert {pair.state for pair in store.source_overlap_inventory().candidates} == {"pending"}
        assert store.source_overlap_posting_blocks((left, middle, right))
        with pytest.raises(ProfileFormatError, match="overlap_review_history"):
            store.clear_source_account_binding(second.source_sha256, "Checking A", "opaque")
    V2ProfileStore.snapshot_to(path, tmp_path / "repeat-backup.db")


def test_posted_repeat_proof_remains_recoverable_after_rebinding(tmp_path):
    path = tmp_path / "proof.db"
    with V2ProfileStore.create(path) as store:
        first, second, first_key, _second_key = _posted_pair(store)
        account(store, "other")
        left, right = first.payload.rows[0].row_id, second.payload.rows[0].row_id
        repair = _repair(store, left, right)
        withdraw(store, first_key)
        change(store, target(second), "other")
        assert store._read_source_interpretation_history()[1] == (repair,)
        change(store, target(second), "cash")
        assert not store._source_overlap_index()[3]
        review(store, left, right, retained=left)
        assert store._source_overlap_index()[3][right][0] == left
        assert store._active_consumed() == {}
    V2ProfileStore.snapshot_to(path, tmp_path / "proof-backup.db")


def test_stale_preview_and_historical_idempotent_retry_do_not_restore_old_binding(tmp_path):
    path = tmp_path / "stale.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        account(store, "other")
        evidence = source(store, "Expense")
        selected = target(evidence)
        frame = store.binding_correction_snapshot(selected, destination_account_id="other")
        record = store.correct_reviewed_binding(
            frame.target,
            destination_account_id="other",
            expected_basis_sha256=frame.basis_sha256,
            reason="Correct account",
        )
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.correct_reviewed_binding(
                frame.target,
                destination_account_id=None,
                expected_basis_sha256=frame.basis_sha256,
                reason="Stale clear",
            )
        change(store, selected, "cash")
        assert (
            store.correct_reviewed_binding(
                frame.target,
                destination_account_id="other",
                expected_basis_sha256=frame.basis_sha256,
                reason="Correct account",
            )
            == record
        )
        assert store.account_bindings(evidence.source_sha256)[0].ledger_account_id == "cash"
        current = store.binding_correction_snapshot(selected, destination_account_id="other")
        source(store, "Later source")
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.correct_reviewed_binding(
                current.target,
                destination_account_id="other",
                expected_basis_sha256=current.basis_sha256,
                reason="Stale source list",
            )


@pytest.mark.parametrize("fail_table", ["SourceAccountBindings", "SourceOverlapReviews", "BindingCorrections"])
def test_assignment_invalidation_history_failure_rolls_back_atomically(tmp_path, fail_table):
    path = tmp_path / "atomic.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        account(store, "other")
        first, second = source(store, "First"), source(store, "Second")
        review(
            store, first.payload.rows[0].row_id, second.payload.rows[0].row_id, retained=first.payload.rows[0].row_id
        )
        selected = target(second)
        prior = {
            table: store.connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("SourceAccountBindings", "SourceOverlapReviews", "BindingCorrections")
        }
        store.connection.execute(
            f"CREATE TRIGGER fail_binding BEFORE INSERT ON {fail_table} BEGIN SELECT RAISE(ABORT,'synthetic fail'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="synthetic fail"):
            change(store, selected, "other")
        assert not store.connection.in_transaction
        for table, rows in prior.items():
            assert store.connection.execute(f"SELECT * FROM {table}").fetchall() == rows


@pytest.mark.parametrize(
    "column,value",
    [
        ("request_basis", sqlite3.Binary(b"blob")),
        ("target_payload", "{}"),
        ("prior_payload", "{}"),
        ("new_payload", "[]"),
        ("invalidations_payload", "{}"),
        ("reason", "changed"),
        ("created_at", "changed"),
    ],
)
def test_corrupt_binding_history_refuses_common_reads_and_backup(tmp_path, column, value):
    path = tmp_path / "corrupt.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        account(store, "other")
        evidence = source(store, "Expense")
        change(store, target(evidence), "other")
        trigger = store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_BindingCorrections_update'"
        ).fetchone()[0]
        store.connection.execute("DROP TRIGGER immutable_BindingCorrections_update")
        store.connection.execute(f"UPDATE BindingCorrections SET {column}=?", (value,))
        store.connection.execute(trigger)
        for read in (
            store.binding_correction_history,
            store._active_consumed,
            store._source_overlap_basis,
            store._reconciliation_rule_and_version,
            lambda: store.reviewed_journal_export(start=date(2026, 10, 1), end=date(2026, 11, 1)),
            lambda: store.account_positions(as_of=date(2026, 10, 31)),
        ):
            with pytest.raises(ProfileFormatError, match="binding_correction_history_integrity"):
                read()
    with pytest.raises(ProfileFormatError, match="binding_correction_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()


@pytest.mark.parametrize("amount", [0, 10_000])
def test_source_backed_opening_including_zero_blocks_binding_correction(tmp_path, amount):
    path = tmp_path / "opening.db"
    evidence = opening_profile(path, amount_minor=amount)
    with V2ProfileStore.open(path) as store:
        account(store, "other")
        store.record_opening_source_review(
            "cash",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Reviewed synthetic opening",
        )
        store.post_reviewed_opening("cash")
        frame = store.binding_correction_snapshot(target(evidence), destination_account_id="other")
        assert frame.opening_blocker_account_ids == ("cash",)
        assert frame.blockers == ("source_backed_opening_anchor",)
        with pytest.raises(ProfileFormatError, match="source_backed_opening_anchor"):
            change(store, target(evidence), "other")
        original = evidence.payload.accounts[0]
        store.bind_source_account(
            evidence.source_sha256, original.source_identity, original.source_identity_form, "cash"
        )
        with pytest.raises(ProfileFormatError, match="source_backed_opening_anchor"):
            store.clear_source_account_binding(
                evidence.source_sha256, original.source_identity, original.source_identity_form
            )


def test_empty_statement_section_retains_scope_mapping_history_and_ordinary_locks(tmp_path):
    path = tmp_path / "empty.db"
    evidence = opening_profile(path)
    with V2ProfileStore.open(path) as store:
        from .test_v2_opening_corrections import _new_source

        empty = _new_source(store, evidence, replace_binding=False)
        account(store, "other")
        selected = target(empty)
        frame = store.binding_correction_snapshot(selected, destination_account_id="other")
        assert frame.current_account_ids == ("cash",) and frame.current_bindings == frame.affected_row_ids == ()
        record = change(store, selected, "other")
        assert record.prior_account_ids == ("cash",) and record.new_account_ids == ("other",)
        assert record.prior_bindings == record.new_bindings == ()
        with pytest.raises(ProfileFormatError, match="correction_history"):
            store.bind_source_account(
                empty.source_sha256, selected.source_identity, selected.source_identity_form, "cash"
            )
        store.bind_source_account(empty.source_sha256, selected.source_identity, selected.source_identity_form, "other")
    V2ProfileStore.snapshot_to(path, tmp_path / "empty-backup.db")


def test_saved_reconciliation_invalidates_on_unconsumed_binding_correction(tmp_path):
    path = tmp_path / "reconciliation.db"
    evidence = bank_profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        account(store, "other")
        account(store, "third")
        unposted = source(store, "Unposted", account_id="other")
        check = store.statement_reconciliation_checks()[0]
        saved = store.save_reconciliation_decision(
            "cash",
            evidence.source_sha256,
            expected_input_version=check.input_version,
            reason="Reviewed original result",
        )
        change(store, target(unposted), "third")
        history = store.reconciliation_history("cash")
        assert history[0].stale and history[0].check == saved.check
        positions = store.account_positions(as_of=date(2026, 1, 31))
        cash = next(p for p in positions.accounts if p.account_id == "cash")
        assert cash.current_saved_reconciled_cutoff is None
    V2ProfileStore.snapshot_to(path, tmp_path / "reconciliation-backup.db")


@pytest.mark.parametrize("bank_date", ["01/05/2026", "01/03/2026"])
def test_transfer_all_legs_block_then_whole_withdrawal_allows_binding_repair(tmp_path, bank_date):
    path = tmp_path / "transfer.db"
    out_id, in_id = transfer_profile(path, bank_date=bank_date)
    with V2ProfileStore.open(path) as store:
        account(store, "other")
        source_id = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (out_id,)
        ).fetchone()[0]
        evidence = store.load_import(source_id).evidence
        selected = target(evidence)
        event = store.post_reviewed_transfer(
            out_id, in_id, preferences=V2Preferences(), reason="Reviewed whole transfer"
        )
        assert (
            "active_source_consumption"
            in store.binding_correction_snapshot(selected, destination_account_id="other").blockers
        )
        frame = store.transfer_review_snapshot(preferences=V2Preferences())
        store.withdraw_reviewed_transfer(
            event, expected_basis_sha256=frame.basis_sha256, reason="Withdraw whole event for binding repair"
        )
        original = store.transfer_history()[0]
        change(store, selected, "other")
        assert store.transfer_history()[0] == original
        assert store._active_consumed() == {}
    V2ProfileStore.snapshot_to(path, tmp_path / "transfer-backup.db")


def test_read_only_nested_transactions_and_prior_schema_refusal(tmp_path):
    path = tmp_path / "boundaries.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        account(store, "other")
        evidence = source(store, "Expense")
        selected = target(evidence)
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="committed_snapshot"):
            store.binding_correction_snapshot(selected, destination_account_id="other")
        with pytest.raises(ProfileFormatError, match="committed_snapshot"):
            store.correct_reviewed_binding(
                selected, destination_account_id="other", expected_basis_sha256="0" * 64, reason="Nested refusal"
            )
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")
        correction = change(store, selected, "other")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store.connection.execute("DELETE FROM BindingCorrections")
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.binding_correction_history() == (correction,)
        frame = store.binding_correction_snapshot(selected, destination_account_id="cash")
        with pytest.raises(ProfileFormatError, match="read_only"):
            store.correct_reviewed_binding(
                frame.target,
                destination_account_id="cash",
                expected_basis_sha256=frame.basis_sha256,
                reason="Readonly refusal",
            )
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=15")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before


def test_wal_preview_keeps_mapping_accounts_and_basis_from_one_committed_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "coherent.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        setup(store)
        account(store, "other")
        evidence = source(store, "Expense")
        selected = target(evidence)
        expected = store.binding_correction_snapshot(selected, destination_account_id="other")
        original = store._binding_scope_accounts
        fired = False

        def interleave(request):
            nonlocal fired
            current = original(request)
            if not fired:
                fired = True
                with V2ProfileStore.open(path) as writer:
                    writer.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "other")
                    account(writer, "third")
            return current

        monkeypatch.setattr(store, "_binding_scope_accounts", interleave)
        frame = store.binding_correction_snapshot(selected, destination_account_id="other")
        assert fired and frame == expected
        assert frame.current_account_ids == ("cash",) and {a.id for a in frame.accounts} == {"cash", "other"}
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.correct_reviewed_binding(
                frame.target,
                destination_account_id="other",
                expected_basis_sha256=frame.basis_sha256,
                reason="Old displayed account",
            )
        fresh = store.binding_correction_snapshot(selected, destination_account_id="other")
        assert fresh.current_account_ids == ("other",) and fresh.basis_sha256 != frame.basis_sha256


def test_partial_group_invalidation_failure_and_mutated_live_mapping_refuse(tmp_path):
    path = tmp_path / "partial.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        account(store, "other")
        first, second, third = (source(store, label) for label in ("First", "Second", "Third"))
        left, middle, right = (e.payload.rows[0].row_id for e in (first, second, third))
        review(store, left, middle, retained=left)
        review(store, left, right, retained=left)
        ceiling = store.connection.execute("SELECT max(revision_id) FROM SourceOverlapReviews").fetchone()[0]
        before = store._source_overlap_basis()
        store.connection.execute(
            f"CREATE TRIGGER fail_second_pending BEFORE INSERT ON SourceOverlapReviews WHEN (SELECT max(revision_id) FROM SourceOverlapReviews)>{ceiling} BEGIN SELECT RAISE(ABORT,'second pending fails'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="second pending fails"):
            change(store, target(second), "other")
        assert store._source_overlap_basis() == before
        store.connection.execute("DROP TRIGGER fail_second_pending")
        change(store, target(second), "other")
        store.connection.execute(
            "UPDATE SourceAccountBindings SET ledger_account_id='cash' WHERE source_sha256=?", (second.source_sha256,)
        )
        with pytest.raises(ProfileFormatError, match="binding_correction_history_integrity"):
            store.binding_correction_history()
    with pytest.raises(ProfileFormatError, match="binding_correction_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")


def test_transfer_dismissal_stays_stale_after_binding_a_b_a_and_fresh_dismissal_is_explicit(tmp_path):
    path = tmp_path / "dismissal.db"
    outgoing, incoming = transfer_profile(path, bank_date="01/05/2026")
    with V2ProfileStore.open(path) as store:
        account(store, "other")
        frame = store.transfer_review_snapshot(preferences=V2Preferences())
        saved = store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=frame.basis_sha256,
            preferences=V2Preferences(),
            reason="Original pair not a transfer",
        )
        assert saved.context_current and not store.transfer_candidates(preferences=V2Preferences())
        source_id = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (outgoing,)
        ).fetchone()[0]
        evidence = store.load_import(source_id).evidence
        preview = store.binding_correction_snapshot(target(evidence), destination_account_id="other")
        assert preview.affected_transfer_review_ids == (saved.revision_id,)
        assert preview.affected_transfer_reviews == (saved,)
        assert {row.row_id for row in preview.affected_review_rows} == {outgoing, incoming}
        record = change(store, target(evidence), "other")
        assert record.invalidated_transfer_review_ids == (saved.revision_id,)
        assert not store.transfer_review_snapshot(preferences=V2Preferences()).pair_reviews[0].context_current
        change(store, target(evidence), "checking")
        current = store.transfer_review_snapshot(preferences=V2Preferences())
        assert len(current.candidates) == 1 and not current.pair_reviews[0].context_current
        assert current.pair_reviews[0].pair == saved.pair and current.pair_reviews[0].reason == saved.reason
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.record_transfer_pair_review(
                outgoing,
                incoming,
                decision="dismiss",
                expected_basis_sha256=frame.basis_sha256,
                preferences=V2Preferences(),
                reason=saved.reason,
            )
        fresh = store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=current.basis_sha256,
            preferences=V2Preferences(),
            reason="New reviewed account context",
        )
        assert fresh.revision_id != saved.revision_id and fresh.context_current
        assert not store.transfer_candidates(preferences=V2Preferences())
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    V2ProfileStore.snapshot_to(path, tmp_path / "dismissal-backup.db")


@pytest.mark.parametrize("mode", ["source", "file", "rows"])
@pytest.mark.parametrize("review_decision", ["dismiss", "reopen"])
def test_transfer_pair_review_history_locks_all_ordinary_assignment_modes(tmp_path, mode, review_decision):
    path = tmp_path / "ordinary-dismissal.db"
    outgoing, incoming = transfer_profile(path, bank_date="01/05/2026")
    with V2ProfileStore.open(path) as store:
        account(store, "other")
        original_source_id = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (outgoing,)
        ).fetchone()[0]
        original = store.load_import(original_source_id).evidence
        selected = target(original)
        if mode != "source":
            store.clear_source_account_binding(original_source_id, "Checking A", "opaque")
            definition = json.loads(CASH_DEFINITION)
            del definition["columns"]["account"]
            definition["account_key"] = "unknown"
            raw_definition = json.dumps(definition).encode()
            content = (
                b"Date,Account,Description,Amount,ReportedBalance\n01/05/2026,,Accountless payment,-$20.00,$980.00\n"
            )
            evidence = build_source_evidence(content, raw_definition, suffix=".csv")
            store.import_source(content, raw_definition, evidence, suffix=".csv")
            outgoing = evidence.payload.rows[0].row_id
            selected = BindingCorrectionTarget(
                evidence.source_sha256, mode, row_ids=(outgoing,) if mode == "rows" else ()
            )
            if mode == "file":
                store.assert_file_account(evidence.source_sha256, "checking")
            else:
                store.assign_row_account(outgoing, "checking")

        def plain_assign(destination):
            if mode == "source":
                store.bind_source_account(
                    selected.source_sha256, selected.source_identity, selected.source_identity_form, destination
                )
            elif mode == "file":
                store.assert_file_account(selected.source_sha256, destination)
            else:
                store.assign_row_account(outgoing, destination)

        def plain_clear():
            if mode == "source":
                store.clear_source_account_binding(
                    selected.source_sha256, selected.source_identity, selected.source_identity_form
                )
            elif mode == "file":
                store.clear_file_account_assertion(selected.source_sha256)
            else:
                store.clear_row_account_assignment(outgoing)

        frame = store.transfer_review_snapshot(preferences=V2Preferences())
        store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=frame.basis_sha256,
            preferences=V2Preferences(),
            reason="Explicit dismissal before binding repair",
        )
        if review_decision == "reopen":
            frame = store.transfer_review_snapshot(preferences=V2Preferences())
            store.record_transfer_pair_review(
                outgoing,
                incoming,
                decision="reopen",
                expected_basis_sha256=frame.basis_sha256,
                preferences=V2Preferences(),
                reason="Explicit reopen before binding repair",
            )
        preview = store.binding_correction_snapshot(selected, destination_account_id="other")
        assert preview.ordinary_blockers == ("account_binding_has_transfer_review_history",)
        plain_assign("checking")  # Same-account retries remain harmless.
        for ordinary_write in (lambda: plain_assign("other"), plain_clear):
            with pytest.raises(ProfileFormatError, match="account_binding_has_transfer_review_history"):
                ordinary_write()
        assert store.binding_correction_history() == ()
        change(store, selected, "other")
        change(store, selected, "checking")
        assert len(store.transfer_candidates(preferences=V2Preferences())) == 1

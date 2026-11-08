"""Explicit ordinary batches preserve exact source effects and all-or-none writes."""

import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_ordinary_batch import OrdinaryBatchCancelled, OrdinaryCategorySelection, preview_digest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_review_read_performance import _tamper

DEFINITION = (Path(__file__).parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json").read_bytes()
SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee,-$4.01,Unavailable\n"
    b"10/03/2026,Checking A,Refund,$4.01,Unavailable\n"
    b"10/05/2026,Checking A,Income,$9.99,Unavailable\n"
)


def _profile(path):
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Synthetic checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("income:pay", "Pay", "income")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
    return evidence


def _preview(store, evidence, *, selections=None, **kwargs):
    snapshot = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
    if selections is None:
        selections = tuple(
            OrdinaryCategorySelection(row.row_id, category, purpose)
            for row, category, purpose in zip(
                evidence.payload.rows,
                ("expense:food", "expense:food", "income:pay"),
                ("expense", "expense_refund", "income"),
                strict=True,
            )
        )
    return store.preview_reviewed_ordinary_batch(
        evidence.source_sha256,
        kind="cash",
        selections=selections,
        reason="Explicit shared review reason",
        expected_basis_sha256=snapshot.basis_sha256,
        **kwargs,
    )


def _counts(store):
    return tuple(
        store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("JournalEntries", "JournalAllocations", "JournalCorrections", "SourceInterpretationActions")
    )


def test_exact_preview_does_not_write_and_successful_retry_is_deterministic(tmp_path):
    path = tmp_path / "batch.db"
    evidence = _profile(path)
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        preview = _preview(store, evidence)
        assert _counts(store) == (0, 0, 0, 0)
        assert [entry.posting_date for entry in preview.entries] == [date(2026, 10, day) for day in (1, 3, 5)]
        assert [tuple(p.amount_minor for p in entry.postings) for entry in preview.entries] == [
            (-401, 401),
            (401, -401),
            (999, -999),
        ]
        assert all(
            e.reason == "Explicit shared review reason" and sum(p.amount_minor for p in e.postings) == 0
            for e in preview.entries
        )
    assert path.read_bytes() == before
    with V2ProfileStore.open(path) as store:
        result = store.post_reviewed_ordinary_batch(preview)
        assert not result.already_posted and result.entry_keys == tuple(e.key for e in preview.entries)
        assert _counts(store) == (3, 3, 0, 0)
        retry = store.post_reviewed_ordinary_batch(preview)
        assert retry.already_posted and retry.entry_keys == result.entry_keys
        assert _counts(store) == (3, 3, 0, 0)
        assert store._active_consumed() == {r.row_id: r.amount.minor for r in evidence.payload.rows}
        summary = store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1))
        assert summary.total_minor == 0 and summary.reviewed_entry_count == 2
        empty = store.reviewed_category_summary(kind="expense", start=date(2026, 11, 1), end=date(2026, 12, 1))
        assert empty.total_minor == 0 and empty.reviewed_entry_count == 0


@pytest.mark.parametrize("change", ["account", "category", "allocation"])
def test_stale_preview_refuses_without_partial_posting(tmp_path, change):
    path = tmp_path / "stale.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        preview = _preview(store, evidence)
        if change == "account":
            store.update_financial_account(FinancialAccount("cash", "Renamed", "asset", "synthetic"))
        elif change == "category":
            store.add_category_account("expense:other", "Other", "expense")
        else:
            store.post_reviewed_cash_category(evidence.payload.rows[0].row_id, "expense:food", reason="Other review")
        before = _counts(store)
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.post_reviewed_ordinary_batch(preview)
        assert _counts(store) == before and not store.connection.in_transaction


def test_invalid_final_selection_cannot_commit_first_valid_row(tmp_path):
    path = tmp_path / "invalid.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        items = (
            OrdinaryCategorySelection(evidence.payload.rows[0].row_id, "expense:food", "expense"),
            OrdinaryCategorySelection(evidence.payload.rows[1].row_id, "income:pay", "expense_refund"),
        )
        with pytest.raises(ProfileFormatError, match="purpose_invalid"):
            _preview(store, evidence, selections=items)
        assert _counts(store) == (0, 0, 0, 0)


def test_duplicate_rows_and_blank_shared_reason_are_refused(tmp_path):
    path = tmp_path / "duplicate.db"
    evidence = _profile(path)
    item = OrdinaryCategorySelection(evidence.payload.rows[0].row_id, "expense:food", "expense")
    with V2ProfileStore.open(path) as store:
        with pytest.raises(ProfileFormatError, match="selection_invalid"):
            _preview(store, evidence, selections=(item, item))
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        with pytest.raises(ProfileFormatError, match="reason_required"):
            store.preview_reviewed_ordinary_batch(
                evidence.source_sha256,
                kind="cash",
                selections=(item,),
                reason=" ",
                expected_basis_sha256=frame.basis_sha256,
            )
        assert _counts(store) == (0, 0, 0, 0)


def test_mid_insert_failure_rolls_back_journal_and_allocations(tmp_path):
    path = tmp_path / "failure.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        preview = _preview(store, evidence)
        store.connection.execute(
            "CREATE TEMP TRIGGER fail_second BEFORE INSERT ON JournalAllocations "
            "WHEN (SELECT count(*) FROM JournalAllocations)=1 BEGIN SELECT RAISE(ABORT,'injected failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
            store.post_reviewed_ordinary_batch(preview)
        assert _counts(store) == (0, 0, 0, 0) and not store.connection.in_transaction
        store.connection.execute("DROP TRIGGER fail_second")
        assert len(store.post_reviewed_ordinary_batch(preview).entry_keys) == 3


def test_cancel_after_first_insert_rolls_back_every_row(tmp_path):
    path = tmp_path / "cancelled.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        preview = _preview(store, evidence)

        def cancelled():
            return _counts(store)[0] > 0

        with pytest.raises(OrdinaryBatchCancelled):
            store.post_reviewed_ordinary_batch(preview, cancelled=cancelled)
        assert _counts(store) == (0, 0, 0, 0)
        assert store._source_read_evidence is None and not store.connection.in_transaction


def test_tampered_effect_and_recomputed_digest_are_refused(tmp_path):
    path = tmp_path / "tampered.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        preview = _preview(store, evidence)
        changed = replace(
            preview, entries=(replace(preview.entries[0], posting_date=date(2026, 10, 9)), *preview.entries[1:])
        )
        with pytest.raises(ProfileFormatError, match="preview_invalid"):
            store.post_reviewed_ordinary_batch(changed)
        changed = replace(changed, preview_sha256=preview_digest(changed))
        with pytest.raises(ProfileFormatError, match="preview_changed"):
            store.post_reviewed_ordinary_batch(changed)
        assert _counts(store) == (0, 0, 0, 0)


def test_new_cross_source_candidate_blocks_preview(tmp_path):
    path = tmp_path / "overlap.db"
    evidence = _profile(path)
    other = SOURCE.replace(b"Coffee", b"Another export coffee")
    parsed = build_source_evidence(other, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.import_source(other, DEFINITION, parsed, suffix=".csv")
        store.bind_source_account(parsed.source_sha256, "Checking A", "opaque", "cash")
        with pytest.raises(ProfileFormatError, match="source_overlap_review_required"):
            _preview(store, evidence)
        assert _counts(store) == (0, 0, 0, 0)


def test_corrupt_unbound_archive_source_still_blocks_post(tmp_path):
    path = tmp_path / "corrupt.db"
    evidence = _profile(path)
    other = SOURCE.replace(b"Coffee", b"Unbound evidence")
    parsed = build_source_evidence(other, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.import_source(other, DEFINITION, parsed, suffix=".csv")
        preview = _preview(store, evidence)
    _tamper(
        path,
        parsed.source_sha256,
        "Sources",
        "UPDATE Sources SET content=? WHERE sha256=?",
        lambda source: (b"bad", source),
    )
    with V2ProfileStore.open(path) as store:
        with pytest.raises(ProfileFormatError, match="saved_snapshot_integrity"):
            store.post_reviewed_ordinary_batch(preview)
        assert _counts(store) == (0, 0, 0, 0)


def test_card_batch_keeps_source_and_explicit_accounting_dates_separate(tmp_path):
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    section = evidence.payload.accounts[0]
    with V2ProfileStore.open(path) as store:
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="card", preferences=V2Preferences())
        item = OrdinaryCategorySelection(section.rows[0].row_id, "expense:food", "expense", date(2026, 3, 17))
        preview = store.preview_reviewed_ordinary_batch(
            evidence.source_sha256,
            kind="card",
            selections=(item,),
            reason="Explicit card date",
            expected_basis_sha256=frame.basis_sha256,
            preferences=V2Preferences(),
        )
        assert preview.entries[0].posting_date == date(2026, 3, 17)
        store.post_reviewed_ordinary_batch(preview)
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert (
            store.source_interpretation_snapshot(evidence.source_sha256, kind="card", preferences=V2Preferences())
            .rows[0]
            .source_date
            == "2026-03-15"
        )


def test_withdrawn_batch_is_not_retried_and_fresh_review_preserves_history(tmp_path):
    path = tmp_path / "history.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        original = _preview(store, evidence)
        store.post_reviewed_ordinary_batch(original)
        basis = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash").basis_sha256
        store.withdraw_reviewed_interpretation(
            original.entries[0].key, expected_basis_sha256=basis, reason="Withdraw choice"
        )
        with pytest.raises(ProfileFormatError, match="retry_changed|preview_changed"):
            store.post_reviewed_ordinary_batch(original)
        fresh = _preview(store, evidence, selections=(original.selections[0],))
        result = store.post_reviewed_ordinary_batch(fresh)
        assert result.entry_keys[0].startswith(original.entries[0].key + ":repost:")
        assert _counts(store) == (5, 4, 0, 1)
        assert len(store.source_interpretation_snapshot(evidence.source_sha256, kind="cash").history) == 1


def test_batch_preview_cannot_be_applied_to_restored_profile_identity(tmp_path):
    path = tmp_path / "original.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        preview = _preview(store, evidence)
    restored = V2ProfileStore.snapshot_to(path, tmp_path / "restored.db")
    with V2ProfileStore.open(restored) as store:
        with pytest.raises(ProfileFormatError, match="profile_changed"):
            store.post_reviewed_ordinary_batch(preview)
        assert _counts(store) == (0, 0, 0, 0)
        reviewed_here = _preview(store, evidence)
        assert len(store.post_reviewed_ordinary_batch(reviewed_here).entry_keys) == 3


def test_builtin_category_is_virtual_in_preview_and_atomic_in_post(tmp_path):
    path = tmp_path / "builtin.db"
    evidence = _profile(path)
    item = OrdinaryCategorySelection(evidence.payload.rows[0].row_id, "builtin:loan-interest", "expense")
    with V2ProfileStore.open(path) as store:
        preview = _preview(store, evidence, selections=(item,))
        assert store.connection.execute("SELECT 1 FROM Accounts WHERE id=?", (item.category_id,)).fetchone() is None
        result = store.post_reviewed_ordinary_batch(preview)
        assert len(result.entry_keys) == 1
        assert store.connection.execute("SELECT name FROM Accounts WHERE id=?", (item.category_id,)).fetchone() == (
            "Loan interest",
        )
        assert store.post_reviewed_ordinary_batch(preview).already_posted


def test_register_batch_retains_printed_transaction_and_posting_dates(tmp_path):
    from parsetrail.core.v2_two_date_card_lines import parse_two_date_card

    from devtools.parser_engine_pilot import test_two_date_card_lines as yamaha

    from .test_v2_liability_register import _profile as _register_profile

    path = tmp_path / "register.db"
    evidence = parse_two_date_card(yamaha.DEFINITION, yamaha.lines())
    _register_profile(path, (b"%PDF-synthetic", yamaha.DEFINITION, evidence))
    row = evidence.payload.accounts[0].rows[0]
    with V2ProfileStore.open(path) as store:
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="register")
        item = OrdinaryCategorySelection(row.row_id, "expense:first", "expense")
        preview = store.preview_reviewed_ordinary_batch(
            evidence.source_sha256,
            kind="register",
            selections=(item,),
            reason="Explicit register purchase",
            expected_basis_sha256=frame.basis_sha256,
        )
        assert preview.entries[0].posting_date == date(2026, 2, 7)
        assert preview.entries[0].postings[0].amount_minor == -1000
        store.post_reviewed_ordinary_batch(preview)
        assert (
            store.load_import(evidence.source_sha256).evidence.payload.accounts[0].rows[0].transaction_date.iso
            == "2026-02-05"
        )


def test_card_assumed_candidate_requires_enabled_preference_or_different_explicit_date(tmp_path):
    path = tmp_path / "card-date.db"
    evidence = _chase_profile(path)
    section = evidence.payload.accounts[0]
    with V2ProfileStore.open(path) as store:
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="card", preferences=V2Preferences())
        for accounting_date in (None, date(2026, 3, 16)):
            item = OrdinaryCategorySelection(section.rows[0].row_id, "expense:food", "expense", accounting_date)
            with pytest.raises(ProfileFormatError, match="assumed_date_disabled"):
                store.preview_reviewed_ordinary_batch(
                    evidence.source_sha256,
                    kind="card",
                    selections=(item,),
                    reason="Date must be reviewed",
                    expected_basis_sha256=frame.basis_sha256,
                    preferences=V2Preferences(),
                )
        assert _counts(store) == (0, 0, 0, 0)


def test_correction_keeps_original_reversal_and_replacement_and_disables_old_batch_retry(tmp_path):
    path = tmp_path / "corrected.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.add_category_account("expense:other", "Other", "expense")
        preview = _preview(store, evidence)
        store.post_reviewed_ordinary_batch(preview)
        basis = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash").basis_sha256
        replacement = store.correct_reviewed_cash_category(
            preview.entries[0].key, "expense:other", reason="Correct ordinary category", expected_basis_sha256=basis
        )
        with pytest.raises(ProfileFormatError):
            store.post_reviewed_ordinary_batch(preview)
        assert _counts(store) == (5, 4, 1, 0)
        current = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        assert current.rows[0].entry_key == replacement


def test_cash_movement_cancellation_leaves_profile_unchanged(tmp_path):
    from parsetrail.core.v2_cash_movement import read_cash_movement

    path = tmp_path / "report-cancelled.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.post_reviewed_ordinary_batch(_preview(store, evidence))
    before = path.read_bytes()
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 4

    with pytest.raises(ProfileFormatError, match="cash_movement_cancelled"):
        read_cash_movement(path, ("cash",), start=date(2026, 10, 1), end=date(2026, 11, 1), cancelled=cancelled)
    assert path.read_bytes() == before
    report = read_cash_movement(path, ("cash",), start=date(2026, 10, 1), end=date(2026, 11, 1))
    assert report.total_minor == 999

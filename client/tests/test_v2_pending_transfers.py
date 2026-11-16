"""Transfer designations persist without money and authorize only reviewed matches."""

import json
import sqlite3
from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.v2_ordinary_batch import (
    OrdinaryBatchCancelled,
    OrdinaryCategorySelection,
    OrdinaryTransferSelection,
    preview_digest,
)
from parsetrail.core.v2_pending_transfers import _digest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_transfer_batch import plan_unique_transfers
from parsetrail.core.v2_transfer_planning import pair_key, plan_transfers, select_transfer_plan

from .test_v2_ordinary_batch import _preview as ordinary_preview
from .test_v2_ordinary_batch import _profile as ordinary_profile
from .test_v2_transfer_batch import _profile as transfer_profile
from .test_v2_transfers import _profile as card_profile
from .v2_institution_helpers import add_test_financial_account


def designate(store, row_id, reason="Initial Review"):
    frame = store.pending_transfer_snapshot()
    prior = next((s for s in frame.rows if s.row_id == row_id), None)
    return store.set_pending_transfer(
        row_id,
        expected_basis_sha256=frame.basis_sha256,
        expected_revision_id=prior.revision_id if prior else None,
        reason=reason,
    )


def counts(store):
    return tuple(
        store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("JournalEntries", "JournalAllocations", "PendingTransferReviews")
    )


def test_no_money_retry_restart_and_accounting_reports_remain_pending(tmp_path):
    path = tmp_path / "pending.db"
    cash, card = card_profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        frame = store.pending_transfer_snapshot()
        saved = store.set_pending_transfer(cash, reason="Initial Review", expected_basis_sha256=frame.basis_sha256)
        assert (
            store.set_pending_transfer(cash, reason="Initial Review", expected_basis_sha256=frame.basis_sha256) == saved
        )
        assert counts(store) == (0, 0, 1) and store._active_consumed() == {}
        assert store.pending_transfer_snapshot().rows[0].status == "waiting"
        assert store.pending_transfer_match_snapshot(preferences=V2Preferences()).candidates == ()
        assert len(store.transfer_review_snapshot(preferences=V2Preferences()).candidates) == 1
        assert store.account_positions(as_of=date(2040, 1, 1)).transfer_clearing_debit_minor == 0
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2027, 1, 1)).total_minor
            == 0
        )
        basis = store.pending_transfer_snapshot().basis_sha256
    with V2ProfileStore.open(path, read_only=True) as store:
        frame = store.pending_transfer_snapshot()
        assert frame.basis_sha256 == basis and frame.rows[0].reason == "Initial Review"
        assert frame.history == (saved,) and frame.rows[0].active


def test_both_intents_required_then_confirm_exact_dated_card_payment(tmp_path):
    path = tmp_path / "both.db"
    cash, card = card_profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        designate(store, cash)
        with pytest.raises(ProfileFormatError, match="both_designations_required"):
            store.post_reviewed_transfer(
                cash, card, preferences=V2Preferences(), reason="Inspect match", require_pending_intents=True
            )
        designate(store, card)
        frame = store.pending_transfer_match_snapshot(preferences=V2Preferences())
        assert frame.require_pending_intents and len(frame.candidates) == 1
        assert all(
            s.status == "match_available" and len(s.counterpart_row_ids) == 1
            for s in store.pending_transfer_snapshot().rows
        )
        plan = plan_unique_transfers(frame)
        assert plan.require_pending_intents
        result = store.post_reviewed_transfer_batch(plan, preferences=V2Preferences(), reason="Confirmed both sources")
        assert result.posted_pairs == 1 and counts(store) == (2, 2, 2)
        assert (
            store.post_reviewed_transfer_batch(
                plan, preferences=V2Preferences(), reason="Confirmed both sources"
            ).already_posted_pairs
            == 1
        )
        assert all(s.status == "consumed" for s in store.pending_transfer_snapshot().rows)
        assert store.account_positions(as_of=date(2026, 1, 4)).transfer_clearing_debit_minor == 2000
        assert store.account_positions(as_of=date(2026, 1, 6)).transfer_clearing_debit_minor == 0
        frame = store.transfer_review_snapshot(preferences=V2Preferences())
        store.withdraw_reviewed_transfer(
            result.event_ids[0], expected_basis_sha256=frame.basis_sha256, reason="Payment match was mistaken"
        )
        assert all(s.status == "stale" for s in store.pending_transfer_snapshot().rows)
        assert not store.pending_transfer_match_snapshot(preferences=V2Preferences()).candidates
        designate(store, cash, reason="Rechecked released cash evidence")
        designate(store, card, reason="Rechecked released card evidence")
        assert len(store.pending_transfer_match_snapshot(preferences=V2Preferences()).candidates) == 1


def test_ambiguous_marked_counterparts_remain_ambiguous_and_unmarked_excluded(tmp_path):
    path = tmp_path / "ambiguous.db"
    evidence = transfer_profile(path, competing=True)
    with V2ProfileStore.open(path) as store:
        for row in evidence.payload.rows:
            designate(store, row.row_id)
        frame = store.pending_transfer_match_snapshot(preferences=V2Preferences())
        plan = plan_unique_transfers(frame)
        assert plan.candidate_count == 3 and plan.ambiguous_pair_count == 2 and len(plan.pairs) == 1
        state = next(s for s in store.pending_transfer_snapshot().rows if s.row_id == evidence.payload.rows[0].row_id)
        assert len(state.counterpart_row_ids) == 2
        last = next(s for s in store.pending_transfer_snapshot().rows if s.row_id == evidence.payload.rows[-1].row_id)
        store.withdraw_pending_transfer(
            last.row_id,
            expected_revision_id=last.revision_id,
            expected_basis_sha256=store.pending_transfer_snapshot().basis_sha256,
            reason="Receipt is ordinary income",
        )
        assert len(plan_unique_transfers(store.pending_transfer_match_snapshot(preferences=V2Preferences())).pairs) == 2


def test_full_window_marked_plan_posts_and_retries(tmp_path):
    path = tmp_path / "window.db"
    evidence = transfer_profile(path)
    with V2ProfileStore.open(path) as store:
        for row in evidence.payload.rows:
            designate(store, row.row_id)
        plan = plan_transfers(store.pending_transfer_match_snapshot(preferences=V2Preferences()))
        assert plan.require_pending_intents and len(plan.ready_pairs) == 2
        selection = select_transfer_plan(plan, tuple(pair_key(p) for p in plan.ready_pairs))
        result = store.post_reviewed_transfer_selection(
            selection, preferences=V2Preferences(), reason="Checked marked plan"
        )
        assert result.posted_pairs == 2
        assert (
            store.post_reviewed_transfer_selection(
                selection, preferences=V2Preferences(), reason="Checked marked plan"
            ).already_posted_pairs
            == 2
        )


def test_stale_basis_revision_and_consumed_rows_refuse(tmp_path):
    path = tmp_path / "stale.db"
    evidence = ordinary_profile(path)
    row = evidence.payload.rows[0].row_id
    with V2ProfileStore.open(path) as store:
        original = store.pending_transfer_snapshot()
        saved = designate(store, row)
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.set_pending_transfer(row, reason="Other choice", expected_basis_sha256=original.basis_sha256)
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.set_pending_transfer(
                row,
                reason="Other choice",
                expected_basis_sha256=store.pending_transfer_snapshot().basis_sha256,
                expected_revision_id=saved.revision_id + 100,
            )
        with pytest.raises(ProfileFormatError, match="reason_required"):
            designate(store, row, " ")
        with pytest.raises(ProfileFormatError, match="withdrawal_required"):
            store.post_reviewed_cash_category(row, "expense:food", reason="Mistakenly bypass correction")
        with pytest.raises(ProfileFormatError, match="unavailable_or_overlap"):
            designate(store, "missing")
        assert counts(store) == (0, 0, 1)


def test_binding_requires_withdrawal_and_preserves_history(tmp_path):
    path = tmp_path / "binding.db"
    evidence = ordinary_profile(path)
    row = evidence.payload.rows[0].row_id
    with V2ProfileStore.open(path) as store:
        saved = designate(store, row)
        add_test_financial_account(store, FinancialAccount("other", "Other", "asset", "synthetic"))
        with pytest.raises(ProfileFormatError, match="pending_transfer"):
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "other")
        store.withdraw_pending_transfer(
            row,
            reason="Assigned to wrong account",
            expected_revision_id=saved.revision_id,
            expected_basis_sha256=store.pending_transfer_snapshot().basis_sha256,
        )
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "other")
        assert store.pending_transfer_snapshot().rows[0].status == "withdrawn"
        current = designate(store, row, "Reviewed new account assignment")
        assert current.account_id == "other" and len(store.pending_transfer_snapshot().history) == 3


def test_mixed_batch_exact_no_money_preview_and_atomic_reclassification(tmp_path):
    path = tmp_path / "mixed.db"
    evidence = ordinary_profile(path)
    first, second = evidence.payload.rows[:2]
    items = (
        OrdinaryTransferSelection(first.row_id),
        OrdinaryCategorySelection(second.row_id, "expense:food", "expense_refund"),
    )
    with V2ProfileStore.open(path) as store:
        preview = ordinary_preview(store, evidence, selections=items)
        assert len(preview.entries) == len(preview.pending_transfers) == 1 and counts(store) == (0, 0, 0)
        assert preview.pending_transfers[0].movement.amount_minor == -401
        result = store.post_reviewed_ordinary_batch(preview)
        assert counts(store) == (1, 1, 1) and len(result.pending_transfer_revision_ids) == 1
        assert store.post_reviewed_ordinary_batch(preview).already_posted
        saved = store.pending_transfer_snapshot().rows[0]
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        assert frame.pending_transfers == (saved,) and first.row_id in frame.transfer_eligible_row_ids
        correction = store.preview_reviewed_ordinary_batch(
            evidence.source_sha256,
            kind="cash",
            reason="Actually a purchase",
            expected_basis_sha256=frame.basis_sha256,
            selections=(
                OrdinaryCategorySelection(
                    first.row_id, "expense:food", "expense", pending_transfer_revision_id=saved.revision_id
                ),
            ),
        )
        assert len(correction.pending_transfer_withdrawals) == 1
        store.post_reviewed_ordinary_batch(correction)
        assert store.post_reviewed_ordinary_batch(correction).already_posted
        assert store.pending_transfer_snapshot().rows[0].status == "withdrawn" and counts(store) == (2, 2, 2)
        with pytest.raises(ProfileFormatError, match="unavailable_or_overlap"):
            designate(store, first.row_id, "Cannot silently turn posted expense into transfer")


@pytest.mark.parametrize("failure", ["cancel", "database"])
def test_mixed_batch_rolls_back_intents_and_journal_on_cancel_or_failure(tmp_path, failure):
    path = tmp_path / "rollback.db"
    evidence = ordinary_profile(path)
    first, second = evidence.payload.rows[:2]
    with V2ProfileStore.open(path) as store:
        preview = ordinary_preview(
            store,
            evidence,
            selections=(
                OrdinaryCategorySelection(first.row_id, "expense:food", "expense"),
                OrdinaryTransferSelection(second.row_id),
            ),
        )
        if failure == "database":
            store.connection.execute(
                "CREATE TEMP TRIGGER fail_intent BEFORE INSERT ON PendingTransferReviews BEGIN SELECT RAISE(ABORT,'injected intent failure'); END"
            )
            with pytest.raises(sqlite3.IntegrityError, match="injected intent failure"):
                store.post_reviewed_ordinary_batch(preview)
        else:
            with pytest.raises(OrdinaryBatchCancelled):
                store.post_reviewed_ordinary_batch(preview, cancelled=lambda: counts(store)[2] > 0)
        assert counts(store) == (0, 0, 0) and not store.connection.in_transaction


def test_older_schema_is_refused_without_mutating_profile(tmp_path):
    path = tmp_path / "old.db"
    ordinary_profile(path)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=24")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "mutation",
    [
        {"posting_date": "2026-10-02"},
        {"date_provenance": "derived"},
        {"amount_minor": -402},
        {"description": "Invented source description"},
        {"tracking_scope": "cash_component"},
        {"account_kind": "liability"},
        {"source_description_known": False},
        {"date_provenance": "assumed", "date_allowed": False},
    ],
)
def test_recomputed_intent_checksum_cannot_change_source_facts_or_admission(tmp_path, mutation):
    path = tmp_path / "tampered.db"
    evidence = ordinary_profile(path)
    with V2ProfileStore.open(path) as store:
        designate(store, evidence.payload.rows[0].row_id)
    with sqlite3.connect(path) as connection:
        saved = list(connection.execute("SELECT * FROM PendingTransferReviews").fetchone())
        payload = json.loads(saved[4])
        payload.update(mutation)
        saved[4] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        saved[10] = _digest(["pending-transfer-1", *saved[:10], saved[11]])
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_PendingTransferReviews_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_PendingTransferReviews_update")
        connection.execute(
            "UPDATE PendingTransferReviews SET movement_payload=?,record_sha256=?", (saved[4], saved[10])
        )
        connection.execute(trigger)
    before = path.read_bytes()
    with V2ProfileStore.open(path) as store:
        with pytest.raises(ProfileFormatError, match="pending_transfer_history_integrity"):
            store.pending_transfer_snapshot()
        with pytest.raises(ProfileFormatError, match="pending_transfer_history_integrity"):
            store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
    destination = tmp_path / "invalid-copy.db"
    with pytest.raises(ProfileFormatError, match="pending_transfer_history_integrity"):
        V2ProfileStore.snapshot_to(path, destination)
    assert not destination.exists() and path.read_bytes() == before


def test_history_keeps_legitimate_old_account_label_and_verified_recovery(tmp_path):
    path = tmp_path / "renamed.db"
    evidence = ordinary_profile(path)
    row = evidence.payload.rows[0].row_id
    with V2ProfileStore.open(path) as store:
        original = designate(store, row)
        store.update_financial_account(FinancialAccount("cash", "Updated label", "asset", "synthetic"))
        frame = store.pending_transfer_snapshot()
        assert frame.history == (original,) and frame.rows[0].status == "stale"
        assert frame.history[0].movement.account_name == "Synthetic checking"
        assert store.financial_account_scope_locked("cash")
        with pytest.raises(ProfileFormatError, match="financial_account_scope_locked"):
            store.update_financial_account(
                FinancialAccount("cash", "Updated label", "asset", "synthetic", tracking_scope="cash_component")
            )
    recovered = V2ProfileStore.snapshot_to(path, tmp_path / "recovered.db")
    with V2ProfileStore.open(recovered, read_only=True) as store:
        assert store.pending_transfer_snapshot().history == (original,)


@pytest.mark.parametrize("mutation", ["added_selection", "missing_draft", "changed_revision", "extra_draft"])
def test_posted_batch_retry_requires_exact_transfer_selection_effect_correspondence(tmp_path, mutation):
    path = tmp_path / "retry.db"
    evidence = ordinary_profile(path)
    first, second, third = evidence.payload.rows
    with V2ProfileStore.open(path) as store:
        selections = (OrdinaryCategorySelection(first.row_id, "expense:food", "expense"),)
        if mutation != "added_selection":
            selections += (OrdinaryTransferSelection(second.row_id),)
        preview = ordinary_preview(store, evidence, selections=selections)
        store.post_reviewed_ordinary_batch(preview)
        if mutation == "added_selection":
            forged = replace(preview, selections=(*preview.selections, OrdinaryTransferSelection(second.row_id)))
        elif mutation == "missing_draft":
            forged = replace(preview, pending_transfers=())
        elif mutation == "changed_revision":
            forged = replace(preview, selections=(preview.selections[0], OrdinaryTransferSelection(second.row_id, 123)))
        else:
            forged = replace(
                preview,
                pending_transfers=(
                    *preview.pending_transfers,
                    replace(preview.pending_transfers[0], row_id=third.row_id),
                ),
            )
        forged = replace(forged, preview_sha256=preview_digest(forged))
        before = counts(store)
        with pytest.raises(ProfileFormatError, match="effect_selection_mismatch"):
            store.post_reviewed_ordinary_batch(forged)
        assert counts(store) == before and not store.connection.in_transaction
        assert store.post_reviewed_ordinary_batch(preview).already_posted


def test_posted_reclassification_retry_cannot_omit_its_selected_intent_withdrawal(tmp_path):
    path = tmp_path / "withdrawal-retry.db"
    evidence = ordinary_profile(path)
    row = evidence.payload.rows[0].row_id
    with V2ProfileStore.open(path) as store:
        saved = designate(store, row)
        selection = OrdinaryCategorySelection(
            row, "expense:food", "expense", pending_transfer_revision_id=saved.revision_id
        )
        preview = ordinary_preview(store, evidence, selections=(selection,))
        store.post_reviewed_ordinary_batch(preview)
        forged = replace(preview, pending_transfer_withdrawals=())
        forged = replace(forged, preview_sha256=preview_digest(forged))
        before = counts(store)
        with pytest.raises(ProfileFormatError, match="effect_selection_mismatch"):
            store.post_reviewed_ordinary_batch(forged)
        assert counts(store) == before and store.post_reviewed_ordinary_batch(preview).already_posted

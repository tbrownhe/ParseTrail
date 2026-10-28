"""Only graph-isolated reviewed transfers post together, with exact atomic history."""

from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_transfer_batch import (
    TransferBatchCancelled,
    plan_unique_transfers,
    post_reviewed_transfer_batch,
)

from .test_v2_review_read_performance import _tamper
from .test_v2_transfers import BANK_DEFINITION

REASON = "Confirmed unique owned-account transfers"


def _profile(path, *, competing=False):
    source = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"01/03/2026,Checking A,First sent,-$10.00,$990.00\n"
        b"01/05/2026,Savings B,First received,$10.00,$1010.00\n"
        b"01/07/2026,Checking A,Second sent,-$20.00,$970.00\n"
        b"01/07/2026,Savings B,Second received,$20.00,$1030.00\n"
    )
    if competing:
        source += b"01/04/2026,Other C,Competing receipt,$10.00,$1010.00\n"
    evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
        for identity, account_id in (("Checking A", "a"), ("Savings B", "b"), ("Other C", "c")):
            store.add_financial_account(FinancialAccount(account_id, identity, "asset", "synthetic"))
            if identity != "Other C" or competing:
                store.bind_source_account(evidence.source_sha256, identity, "opaque", account_id)
    return evidence


def _plan(store, *, gap=7):
    return plan_unique_transfers(store.transfer_review_snapshot(preferences=V2Preferences(), max_day_gap=gap))


def _post(store, plan, **kwargs):
    return post_reviewed_transfer_batch(store, plan, preferences=V2Preferences(), reason=REASON, **kwargs)


def test_batch_keeps_exact_dates_clearing_and_no_expense_then_retries_idempotently(tmp_path):
    path = tmp_path / "batch.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        assert len(plan.pairs) == plan.candidate_count == 2
        assert plan.total_minor == 3000 and plan.excluded_pair_count == 0
        result = _post(store, plan)
        assert result.posted_pairs == len(result.event_ids) == 2
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (3,)
        assert store.connection.execute("SELECT count(*) FROM JournalAllocations").fetchone() == (4,)
        before_receipt = store.account_positions(as_of=date(2026, 1, 4))
        assert before_receipt.transfer_clearing_debit_minor == 1000
        assert all(account.position_debit_minor is None for account in before_receipt.accounts)
        assert store.account_positions(as_of=date(2026, 1, 31)).transfer_clearing_debit_minor == 0
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
        before = path.read_bytes()
        retry = _post(store, plan)
        assert retry.posted_pairs == 0 and retry.already_posted_pairs == 2 and retry.event_ids == result.event_ids
        assert path.read_bytes() == before
        assert store._transfer_verified_sources is None and not store.connection.in_transaction
        assert _plan(store).pairs == ()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert len(store.transfer_history()) == 2


def test_only_pairs_without_competitors_on_both_legs_are_selected(tmp_path):
    path = tmp_path / "ambiguous.db"
    _profile(path, competing=True)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        assert plan.candidate_count == 3 and plan.ambiguous_pair_count == plan.excluded_pair_count == 2
        assert len(plan.pairs) == 1 and plan.total_minor == 2000
        assert _post(store, plan).posted_pairs == 1
        assert len(store.transfer_candidates(preferences=V2Preferences())) == 2


def test_batch_scope_uses_current_gap_and_new_competing_receipt_stales_the_plan(tmp_path):
    path = tmp_path / "scope.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        narrow = _plan(store, gap=1)
        assert len(narrow.pairs) == 1 and narrow.total_minor == 2000
        assert narrow.max_day_gap == 1
        plan = _plan(store)
        source = b"Date,Account,Description,Amount,ReportedBalance\n01/04/2026,Other C,Another possible receipt,$10.00,$1010.00\n"
        evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
        store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Other C", "opaque", "c")
        with pytest.raises(ProfileFormatError, match="transfer_review_changed_since_selection"):
            _post(store, plan)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        fresh = _plan(store)
        assert fresh.ambiguous_pair_count == 2 and len(fresh.pairs) == 1


def test_batch_events_support_existing_whole_event_withdrawal_and_fresh_repost(tmp_path):
    path = tmp_path / "history.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        original = _post(store, _plan(store))
        snapshot = store.transfer_review_snapshot(preferences=V2Preferences())
        cancelled = store.withdraw_reviewed_transfer(
            original.event_ids[0],
            expected_basis_sha256=snapshot.basis_sha256,
            reason="Correct the first confirmed transfer",
        )
        assert cancelled.status == "cancelled" and len(cancelled.entry_keys) == 2
        fresh = _plan(store)
        assert len(fresh.pairs) == 1
        reposted = _post(store, fresh)
        assert reposted.event_ids[0] not in original.event_ids
        history = store.transfer_history()
        assert len(history) == 3 and sum(event.status == "active" for event in history) == 2
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (7,)
        assert store.connection.execute("SELECT count(*) FROM JournalRetirements").fetchone() == (2,)
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )


def test_disabled_date_competitor_still_prevents_bulk_confirmation(tmp_path):
    path = tmp_path / "disabled.db"
    _profile(path)
    with V2ProfileStore.open(path, read_only=True) as store:
        snapshot = store.transfer_review_snapshot(preferences=V2Preferences())
    pair = snapshot.candidates[0]
    disabled = replace(
        pair,
        incoming=replace(pair.incoming, row_id="f" * 64, date_allowed=False, date_provenance="assumed"),
        posting_allowed=False,
    )
    plan = plan_unique_transfers(replace(snapshot, candidates=(*snapshot.candidates, disabled)))
    assert len(plan.pairs) == 1 and plan.ambiguous_pair_count == 2
    assert all(candidate.outgoing.row_id != pair.outgoing.row_id for candidate in plan.pairs)


@pytest.mark.parametrize("failure", ["cancel", "insert"])
def test_batch_failure_rolls_back_every_entry_event_allocation_and_clearing_account(tmp_path, failure):
    path = tmp_path / "rollback.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        before = path.read_bytes()
        if failure == "cancel":
            with pytest.raises(TransferBatchCancelled):
                _post(
                    store,
                    plan,
                    cancelled=lambda: (
                        store.connection.execute("SELECT count(*) FROM TransferEvents").fetchone()[0] == 1
                    ),
                )
        else:
            store.connection.execute(
                "CREATE TEMP TRIGGER refuse_second BEFORE INSERT ON TransferEvents WHEN (SELECT count(*) FROM TransferEvents)=1 BEGIN SELECT RAISE(ABORT,'synthetic refusal'); END"
            )
            with pytest.raises(Exception, match="synthetic refusal"):
                _post(store, plan)
        assert path.read_bytes() == before
        for table in ("JournalEntries", "JournalAllocations", "TransferEvents"):
            assert store.connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM Accounts WHERE role='internal'").fetchone() == (0,)
        assert store._transfer_verified_sources is None and not store.connection.in_transaction


def test_stale_state_scope_preferences_and_copied_profile_refuse_without_posting(tmp_path):
    path = tmp_path / "stale.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        with pytest.raises(ProfileFormatError, match="transfer_batch_preferences_changed"):
            post_reviewed_transfer_batch(
                store, plan, preferences=V2Preferences(allow_assumed_posting_dates=True), reason=REASON
            )
        store.add_financial_account(FinancialAccount("new", "New unrelated account", "asset", "synthetic"))
        before = path.read_bytes()
        with pytest.raises(ProfileFormatError, match="transfer_review_changed_since_selection"):
            _post(store, plan)
        assert path.read_bytes() == before
        plan = _plan(store)
    copied = V2ProfileStore.snapshot_to(path, tmp_path / "copy.db")
    with V2ProfileStore.open(copied) as store:
        with pytest.raises(ProfileFormatError, match="transfer_batch_profile_changed"):
            _post(store, plan)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_one_verified_source_pass_for_read_single_post_and_batch(tmp_path, monkeypatch):
    path = tmp_path / "onepass.db"
    evidence = _profile(path)
    verified = []
    original = V2ProfileStore._verified_saved_import

    def record(source, row, observations):
        verified.append(source)
        return original(source, row, observations)

    monkeypatch.setattr(V2ProfileStore, "_verified_saved_import", staticmethod(record))
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        assert verified == [evidence.source_sha256]
        verified.clear()
        pair = plan.pairs[0]
        store.post_reviewed_transfer(
            pair.outgoing.row_id,
            pair.incoming.row_id,
            preferences=V2Preferences(),
            reason=REASON,
            expected_basis_sha256=plan.basis_sha256,
        )
        assert verified == [evidence.source_sha256]
        verified.clear()
        fresh = _plan(store)
        assert verified == [evidence.source_sha256]
        verified.clear()
        _post(store, fresh)
        assert verified == [evidence.source_sha256]


def test_cache_never_survives_to_a_later_corrupt_read_or_failed_write(tmp_path):
    path = tmp_path / "corrupt.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path, read_only=True) as store:
        plan = _plan(store)
        assert store._transfer_verified_sources is None
    _tamper(
        path,
        evidence.source_sha256,
        "SourceObservations",
        "UPDATE SourceObservations SET amount_minor=amount_minor+1 WHERE source_sha256=?",
        lambda source: (source,),
    )
    before = path.read_bytes()
    with V2ProfileStore.open(path) as store:
        with pytest.raises(ProfileFormatError, match="observation_inventory_mismatch"):
            _plan(store)
        assert store._transfer_verified_sources is None and not store.connection.in_transaction
        with pytest.raises(ProfileFormatError, match="observation_inventory_mismatch"):
            _post(store, plan)
        assert store._transfer_verified_sources is None and not store.connection.in_transaction
    assert path.read_bytes() == before

"""Full-horizon transfer proposals are tentative, global and explicitly selected."""

from dataclasses import asdict, replace
from datetime import date, timedelta
from hashlib import sha256
from itertools import permutations

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import (
    FinancialAccount,
    ProfileFormatError,
    TransferCandidate,
    TransferReviewSnapshot,
    V2ProfileStore,
)
from parsetrail.core.v2_settlements import TransferMovement
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_transfer_batch import TransferBatchCancelled
from parsetrail.core.v2_transfer_planning import (
    MAX_COMPONENT_EDGES,
    RULE,
    _digest,
    max_user_reason_length,
    pair_key,
    plan_transfers,
    post_reviewed_transfer_selection,
    select_transfer_plan,
    selection_reason,
)

from .test_v2_transfers import BANK_DEFINITION

PREFERENCES = V2Preferences()


def _movement(label, day, account, amount, *, assumed=False, enabled=True):
    return TransferMovement(
        sha256(label.encode()).hexdigest(),
        "a" * 64,
        account,
        account,
        "asset",
        (date(2026, 1, 1) + timedelta(days=day)).isoformat(),
        "assumed" if assumed else "observed",
        enabled,
        amount,
        "Source text 1234; this is not a verified reference",
    )


def _snapshot(outgoing, incoming, *, horizon=7, preferences=PREFERENCES):
    pairs = tuple(
        TransferCandidate(out, inc, "asset transfer", gap, out.date_allowed and inc.date_allowed)
        for out in outgoing
        for inc in incoming
        if out.account_id != inc.account_id
        and out.amount_minor == -inc.amount_minor
        and (gap := abs((date.fromisoformat(out.posting_date) - date.fromisoformat(inc.posting_date)).days)) <= horizon
    )
    return TransferReviewSnapshot(pairs, (), (), "1" * 64, preferences, horizon, "2" * 64)


def test_whole_horizon_beats_closest_first_greedy_and_is_permutation_invariant():
    # The closest edge O1/I1 would leave O2 unmatched. The global solution uses
    # O1/I2 and O2/I1: 5+6 > 7. The same-account edge O2/I2 is unsupported.
    outgoing = (_movement("o1", 0, "a", -10000), _movement("o2", 3, "b", -10000))
    incoming = (_movement("i1", 1, "c", 10000), _movement("i2", 3, "b", 10000))
    snapshot = _snapshot(outgoing, incoming)
    expected = {(outgoing[0].row_id, incoming[1].row_id), (outgoing[1].row_id, incoming[0].row_id)}
    plan = plan_transfers(snapshot)
    assert not plan.ready_pairs
    assert {pair_key(p.pair) for p in plan.proposals} == expected
    assert plan.components[0].optimum_score == 11
    for order in permutations(snapshot.candidates):
        assert plan_transfers(replace(snapshot, candidates=order)) == plan
    assert all("Tentative date-only" in p.explanation for p in plan.proposals)


def test_meaningful_unmatched_option_can_prefer_one_pair_over_two():
    outgoing = (_movement("o1", 0, "a", -10000), _movement("o2", 7, "b", -10000))
    incoming = (_movement("i1", 0, "c", 10000), _movement("i2", 7, "b", 10000))
    plan = plan_transfers(_snapshot(outgoing, incoming))
    assert tuple(pair_key(p.pair) for p in plan.proposals) == ((outgoing[0].row_id, incoming[0].row_id),)
    assert set(plan.components[0].unmatched_row_ids) == {outgoing[1].row_id, incoming[1].row_id}
    assert plan.components[0].optimum_score == 8


def test_equal_score_different_cardinality_remains_unresolved():
    outgoing = (_movement("o1", 0, "a", -10000), _movement("o2", 5, "b", -10000))
    incoming = (_movement("i1", 1, "c", 10000), _movement("i2", 4, "b", 10000))
    plan = plan_transfers(_snapshot(outgoing, incoming, horizon=6))
    assert plan.proposals == plan.selectable_pairs == ()
    assert plan.components[0].status == "ties" and plan.components[0].optimum_score == 6
    assert not plan.components[0].unmatched_row_ids


def test_equal_date_ties_do_not_use_source_order_or_descriptions_as_evidence():
    outgoing = tuple(_movement(f"o{i}", 0, "a", -10000) for i in range(2))
    incoming = tuple(_movement(f"i{i}", 0, "b", 10000) for i in range(2))
    snapshot = _snapshot(outgoing, incoming)
    plan = plan_transfers(snapshot)
    assert not plan.proposals and plan.components[0].status == "ties"
    assert plan_transfers(replace(snapshot, candidates=tuple(reversed(snapshot.candidates)))) == plan


def test_disabled_estimated_competitor_prevents_ready_and_date_ranking():
    outgoing = (_movement("o", 0, "a", -10000),)
    incoming = (_movement("i", 0, "b", 10000), _movement("estimate", 1, "c", 10000, assumed=True, enabled=False))
    plan = plan_transfers(_snapshot(outgoing, incoming))
    assert plan.candidate_count == 2 and not plan.selectable_pairs
    assert plan.components[0].status == "estimated_dates"
    with pytest.raises(ProfileFormatError, match="selection_invalid"):
        select_transfer_plan(plan, [pair_key(plan.candidates[0])])
    unique = _snapshot(outgoing, (replace(incoming[1], date_allowed=True),), preferences=V2Preferences(False, True))
    estimated = plan_transfers(unique)
    assert not estimated.ready_pairs and len(estimated.estimated_date_pairs) == 1
    assert select_transfer_plan(estimated, [pair_key(estimated.estimated_date_pairs[0])]).pairs


@pytest.mark.parametrize("out_count,in_count", [(23, 23), (1, 64)])
def test_oversized_component_keeps_all_edges_for_explicit_individual_review(out_count, in_count):
    outgoing = tuple(_movement(f"o{i}", 0, "a", -10000) for i in range(out_count))
    incoming = tuple(_movement(f"i{i}", 0, "b", 10000) for i in range(in_count))
    plan = plan_transfers(_snapshot(outgoing, incoming))
    assert out_count + in_count > 64 or out_count * in_count > MAX_COMPONENT_EDGES
    assert len(plan.candidates) == len(plan.components[0].pairs) == out_count * in_count
    assert plan.components[0].status == "oversized" and not plan.selectable_pairs


def test_duplicate_edges_inconsistent_movements_and_selection_duplicates_refuse():
    snapshot = _snapshot((_movement("o", 0, "a", -10000),), (_movement("i", 0, "b", 10000),))
    with pytest.raises(ProfileFormatError, match="graph_invalid"):
        plan_transfers(replace(snapshot, candidates=snapshot.candidates * 2))
    plan = plan_transfers(snapshot)
    key = pair_key(plan.ready_pairs[0])
    with pytest.raises(ProfileFormatError, match="selection_invalid"):
        select_transfer_plan(plan, [key, key])
    with pytest.raises(ProfileFormatError, match="selection_invalid"):
        select_transfer_plan(plan, [])
    with pytest.raises(ProfileFormatError, match="plan_invalid"):
        select_transfer_plan(replace(plan, confirmation_sha256="f" * 64), [key])


def _profile(path):
    # Three connected equal-amount edges, two globally proposed pairs, plus
    # a graph-isolated $20 ready pair. Dates remain separate clearing dates.
    source = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"01/01/2026,Account A,Sent first,-$100.00,$0.00\n"
        b"01/04/2026,Account B,Sent second,-$100.00,$0.00\n"
        b"01/02/2026,Account C,Received first,$100.00,$0.00\n"
        b"01/04/2026,Account B,Received second,$100.00,$0.00\n"
        b"01/07/2026,Account A,Other sent,-$20.00,$0.00\n"
        b"01/07/2026,Account B,Other received,$20.00,$0.00\n"
    )
    evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
        for identity, account_id in (("Account A", "a"), ("Account B", "b"), ("Account C", "c")):
            store.add_financial_account(FinancialAccount(account_id, identity, "asset", "synthetic"))
            store.bind_source_account(evidence.source_sha256, identity, "opaque", account_id)
    return evidence


def _plan(store):
    return plan_transfers(store.transfer_review_snapshot(preferences=PREFERENCES))


def _post(store, selection, **kwargs):
    return post_reviewed_transfer_selection(
        store, selection, preferences=PREFERENCES, reason="Reviewed selected pairs", **kwargs
    )


def test_ready_and_explicit_proposals_post_atomically_keep_dates_rule_and_retry(tmp_path, monkeypatch):
    path = tmp_path / "selected.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        assert len(plan.ready_pairs) == 1 and len(plan.proposals) == 2
        selected = select_transfer_plan(plan, [pair_key(p) for p in plan.selectable_pairs])
        verified = []
        original = store._verified_saved_import

        def counted(*args, **kwargs):
            verified.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(store, "_verified_saved_import", counted)
        result = _post(store, selected)
        assert result.posted_pairs == 3 and len(verified) == 1
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (5,)
        assert store.connection.execute("SELECT count(*) FROM JournalAllocations").fetchone() == (6,)
        history = store.transfer_history()
        assert all(RULE in e.reason and selected.confirmation_sha256 in e.reason for e in history)
        assert {
            p.posting_date for p in (m for event in history for m in (event.pair.outgoing, event.pair.incoming))
        } == {"2026-01-01", "2026-01-02", "2026-01-04", "2026-01-07"}
        before = path.read_bytes()
        assert _post(store, selected).already_posted_pairs == 3
        assert path.read_bytes() == before
        assert store._transfer_history_cache is None and not store.connection.in_transaction


def test_partial_selection_posts_only_chosen_pairs_and_rejects_changed_full_graph(tmp_path):
    path = tmp_path / "partial.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        selected = select_transfer_plan(plan, [pair_key(plan.ready_pairs[0])])
        assert _post(store, selected).posted_pairs == 1
        assert len(_plan(store).proposals) == 2
        assert _post(store, selected).already_posted_pairs == 1
        source = b"Date,Account,Description,Amount,ReportedBalance\n01/02/2026,Account C,New competing receipt,$100.00,$0.00\n"
        evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
        store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Account C", "opaque", "c")
        with pytest.raises(ProfileFormatError, match="planning_graph_changed"):
            _post(store, selected)


@pytest.mark.parametrize("failure", ["cancel", "sql"])
def test_selected_batch_failure_rolls_back_every_pair_and_clearing(tmp_path, failure):
    path = tmp_path / "rollback.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        selected = select_transfer_plan(plan, [pair_key(p) for p in plan.selectable_pairs])
        before = path.read_bytes()
        if failure == "sql":
            store.connection.execute(
                "CREATE TEMP TRIGGER refuse_second BEFORE INSERT ON TransferEvents WHEN (SELECT count(*) FROM TransferEvents)=1 BEGIN SELECT RAISE(ABORT,'test rollback'); END"
            )
            with pytest.raises(Exception, match="test rollback"):
                _post(store, selected)
        else:
            with pytest.raises(TransferBatchCancelled):
                _post(
                    store,
                    selected,
                    cancelled=lambda: store.connection.execute("SELECT count(*) FROM TransferEvents").fetchone()[0] > 0,
                )
        assert path.read_bytes() == before and store._transfer_history_cache is None
        for table in ("JournalEntries", "JournalAllocations", "TransferEvents"):
            assert store.connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        assert not store.connection.execute("SELECT 1 FROM Accounts WHERE purpose='clearing'").fetchone()


def test_recomputed_client_hash_cannot_authorize_an_unproposed_or_stale_pair(tmp_path):
    path = tmp_path / "tamper.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        alternate = next(p for p in plan.candidates if p not in plan.selectable_pairs)
        # Forge both a consistent client plan and selection token. Only the
        # write-locked canonical graph/solver result is posting authority.
        forged = replace(plan, ready_pairs=plan.ready_pairs + (alternate,), confirmation_sha256="")
        forged = replace(forged, confirmation_sha256=_digest([RULE, asdict(forged)]))
        selection = select_transfer_plan(forged, [pair_key(alternate)])
        with pytest.raises(ProfileFormatError, match="planning_graph_changed"):
            _post(store, selection)
        assert not store.transfer_history()
        selected = select_transfer_plan(plan, [pair_key(plan.ready_pairs[0])])
        store.connection.execute("UPDATE Accounts SET name='Changed account' WHERE id='a'")
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            _post(store, selected)


def test_reason_bound_and_cooperative_solver_cancellation(tmp_path):
    path = tmp_path / "reason.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        selected = select_transfer_plan(plan, [pair_key(plan.ready_pairs[0])])
        limit = max_user_reason_length(selected)
        assert len(selection_reason(selected, "x" * limit)) == 500
        with pytest.raises(ProfileFormatError, match="reason_too_long"):
            store.post_reviewed_transfer_selection(selected, preferences=PREFERENCES, reason="x" * (limit + 1))
        assert not store.connection.in_transaction
        with pytest.raises(TransferBatchCancelled):
            plan_transfers(store.transfer_review_snapshot(preferences=PREFERENCES), cancelled=lambda: True)


def test_profile_preferences_consumption_and_lifecycle_changes_cannot_bypass_review(tmp_path):
    import shutil

    path, copied = tmp_path / "scope.db", tmp_path / "copy.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        selected = select_transfer_plan(plan, [pair_key(plan.ready_pairs[0])])
        shutil.copyfile(path, copied)
        with V2ProfileStore.open(copied) as other:
            with pytest.raises(ProfileFormatError, match="profile_changed"):
                _post(other, selected)
        with pytest.raises(ProfileFormatError, match="preferences_changed"):
            store.post_reviewed_transfer_selection(selected, preferences=V2Preferences(True, False), reason="Reviewed")
        anchor = store.account_anchor_snapshot("a")
        store.record_account_lifecycle(
            "a",
            state="closed",
            effective_date=date(2026, 2, 1),
            reason="Recorded later closure",
            expected_version=None,
            expected_basis_sha256=anchor.basis_sha256,
        )
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            _post(store, selected)
        # Historical evidence can still be reviewed; closure is not an invented
        # prohibition on historical postings. A subsequent consumption does stale it.
        plan = _plan(store)
        selected = select_transfer_plan(plan, [pair_key(plan.ready_pairs[0])])
        store.add_category_account("expense:test", "Synthetic expense", "expense")
        store.post_reviewed_cash_category(
            selected.pairs[0].outgoing.row_id, "expense:test", reason="Explicit classification"
        )
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            _post(store, selected)
        assert not _plan(store).ready_pairs


def test_partial_prior_apply_or_withdrawn_event_never_recreates_an_old_selection(tmp_path):
    path = tmp_path / "prior.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        whole = select_transfer_plan(plan, [pair_key(p) for p in plan.selectable_pairs])
        first = select_transfer_plan(plan, [pair_key(plan.ready_pairs[0])])
        original = _post(store, first)
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            _post(store, whole)
        snapshot = store.transfer_review_snapshot(preferences=PREFERENCES)
        store.withdraw_reviewed_transfer(
            original.event_ids[0], expected_basis_sha256=snapshot.basis_sha256, reason="Withdraw reviewed pair"
        )
        before = path.read_bytes()
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            _post(store, first)
        assert path.read_bytes() == before
        assert store.transfer_history()[0].status == "cancelled"


def test_source_overlap_still_blocks_duplicate_evidence_before_proposals(tmp_path):
    path = tmp_path / "overlap.db"
    _profile(path)
    source = b"Date,Account,Description,Amount,ReportedBalance\n01/07/2026,Account A,Other sent,-$20.00,$0.00\n"
    evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        plan = _plan(store)
        selected = select_transfer_plan(plan, [pair_key(plan.ready_pairs[0])])
        store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Account A", "opaque", "a")
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            _post(store, selected)
        assert not _plan(store).ready_pairs

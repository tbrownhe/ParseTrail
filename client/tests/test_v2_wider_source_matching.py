"""Nearby evidence needs explicit actual-pair review, never transitive matching."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import (
    BindingCorrectionTarget,
    ProfileFormatError,
    V2ProfileStore,
)

from .test_v2_card_purchase_review import CHASE_DEFINITION, _chase_profile
from .test_v2_source_overlap import account, setup, source
from .test_v2_statement_journal_comparison import _profile as bank_profile
from .test_v2_statement_reconciliation import _review_and_post


def row(evidence):
    return evidence.payload.rows[0].row_id


def decide(store, left, right, decision="repeat", retained=None, reason="Compared actual source occurrences"):
    pair = store.source_overlap_pair(left, right)
    return store.record_source_overlap_review(
        left,
        right,
        decision=decision,
        retained_row_id=retained if decision == "repeat" else None,
        expected_basis_sha256=pair.basis_sha256,
        reason=reason,
    )


@pytest.mark.parametrize(
    "other_date,role,eligible",
    [
        ("12/31/2026", "posting_date", True),
        ("01/03/2027", "activity_date", True),
        ("01/04/2027", "posting_date", False),
    ],
)
def test_exact_window_crosses_year_and_preserves_description_date_role_and_originals(
    tmp_path, other_date, role, eligible
):
    path = tmp_path / "window.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        first = source(store, "Original description", source_date="12/31/2026")
        second = source(store, "REVISED description", source_date=other_date, date_role=role)
        inventory = store.source_overlap_inventory()
        assert inventory.total_pairs == int(eligible)
        assert store.source_overlap_inventory(source_sha256=first.source_sha256).total_pairs == int(eligible)
        if eligible:
            pair = store.source_overlap_pair(row(first), row(second))
            assert pair.state == "pending" and pair.left.description != pair.right.description
            decide(store, row(first), row(second), retained=row(first))
            assert set(store.source_overlap_posting_blocks((row(first), row(second)))) == {row(second)}
        else:
            with pytest.raises(ProfileFormatError, match="pair_unavailable"):
                store.source_overlap_pair(row(first), row(second))
        assert store.load_import(first.source_sha256).evidence == first
        assert store.load_import(second.source_sha256).evidence == second
    V2ProfileStore.snapshot_to(path, tmp_path / "window-backup.db")


def test_alias_only_neighbor_blocks_root_and_every_actual_outsider_edge_needs_distinct_review(tmp_path):
    with V2ProfileStore.create(tmp_path / "alias.db") as store:
        setup(store)
        first = source(store, "Root", source_date="10/01/2026")
        support = source(store, "Support", source_date="10/04/2026")
        outsider = source(store, "Outside", source_date="10/07/2026")
        a, b, c = map(row, (first, support, outsider))
        decide(store, a, b, retained=a)
        pair = store.source_overlap_pair(b, c)
        assert pair.state == "pending" and {pair.left_root_row_id, pair.right_root_row_id} == {a, c}
        assert pair.repeat_edges == (tuple(sorted((a, b))),)
        assert set(store.source_overlap_posting_blocks((a, b, c))) == {a, b, c}
        with pytest.raises(ProfileFormatError, match="source_overlap_review_required"):
            store.post_reviewed_cash_category(a, "expense:food", reason="Hidden alias neighbor still pending")
        with pytest.raises(ProfileFormatError, match="pair_unavailable"):
            store.source_overlap_pair(a, c)
        decide(store, b, c, "distinct")
        assert set(store.source_overlap_posting_blocks((a, b, c))) == {b}
        store.post_reviewed_cash_category(a, "expense:food", reason="Reviewed retained source")
        store.post_reviewed_cash_category(c, "expense:other", reason="Explicit different occurrence")
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 800
        )
        decide(store, b, c, "pending")
        assert a in store.source_overlap_posting_blocks((a,))


def test_distinct_root_pair_never_resolves_support_member_outsider_edge(tmp_path):
    with V2ProfileStore.create(tmp_path / "edges.db") as store:
        setup(store)
        a, b, c = (
            row(source(store, label, source_date=day))
            for label, day in (("A", "10/01/2026"), ("B", "10/02/2026"), ("C", "10/03/2026"))
        )
        decide(store, a, b, retained=a)
        decide(store, a, c, "distinct")
        assert set(store.source_overlap_posting_blocks((a, c))) == {a, c}
        decide(store, b, c, "distinct")
        assert not store.source_overlap_posting_blocks((a, c))
        assert store.source_overlap_pair(b, c).state == "distinct"
        decide(store, b, c, "pending")
        assert set(store.source_overlap_posting_blocks((a, c))) == {a, c}


def test_nontransitive_three_day_chain_cannot_become_repeat_group_and_is_atomic(tmp_path):
    with V2ProfileStore.create(tmp_path / "chain.db") as store:
        setup(store)
        a, b, c = (
            row(source(store, label, source_date=day))
            for label, day in (("A", "10/01/2026"), ("B", "10/04/2026"), ("C", "10/07/2026"))
        )
        decide(store, a, b, retained=b)
        before = store.connection.execute("SELECT * FROM SourceOverlapReviews").fetchall()
        with pytest.raises(ProfileFormatError, match="group_not_pairwise_eligible"):
            decide(store, b, c, retained=b)
        assert store.connection.execute("SELECT * FROM SourceOverlapReviews").fetchall() == before
        assert not store.connection.in_transaction
        assert b in store.source_overlap_posting_blocks((b,))
        decide(store, a, b, "distinct")  # Explicitly removes that actual saved edge.
        decide(store, b, c, retained=b)
        assert store.source_overlap_pair(a, b).state == "distinct"


def test_implicit_same_group_pair_cannot_clear_group_and_actual_saved_edge_is_directly_reachable(tmp_path):
    with V2ProfileStore.create(tmp_path / "navigate.db") as store:
        setup(store)
        a, b, c = (row(source(store, label)) for label in ("A", "B", "C"))
        decide(store, a, b, retained=a)
        decide(store, a, c, retained=a)
        implicit = store.source_overlap_pair(b, c)
        assert implicit.state == "repeat" and implicit.left_group_row_ids == implicit.right_group_row_ids == tuple(
            sorted((a, b, c))
        )
        assert set(implicit.repeat_edges) == {tuple(sorted((a, b))), tuple(sorted((a, c)))}
        before = store.connection.execute("SELECT count(*) FROM SourceOverlapReviews").fetchone()
        for decision in ("pending", "distinct"):
            with pytest.raises(ProfileFormatError, match="clear_repeat_first"):
                decide(store, b, c, decision)
        assert store.connection.execute("SELECT count(*) FROM SourceOverlapReviews").fetchone() == before
        decide(store, a, b, "pending")
        assert store._source_overlap_index()[3] == {c: (a, store.source_overlap_pair(a, c).revision_id)}
        capped = store.source_overlap_inventory(max_pairs=1)
        assert capped.candidates[0].state == "pending"
        actual = store.source_overlap_pair(a, c)
        assert actual.state == "repeat"
        decide(store, a, c, "distinct")
        assert not store._source_overlap_index()[3]


def test_shifted_hidden_candidates_and_direct_read_ignore_display_cap_and_refuse_stale_forms(tmp_path):
    with V2ProfileStore.create(tmp_path / "cap.db") as store:
        setup(store)
        first = source(store, "First", count=46, source_date="10/01/2026")
        second = source(store, "Later export", count=46, source_date="10/04/2026")
        inventory = store.source_overlap_inventory()
        assert inventory.total_pairs == 2116 and inventory.truncated and len(inventory.candidates) == 2000
        visible = {(p.left.row_id, p.right.row_id) for p in inventory.candidates}
        hidden = next(
            tuple(sorted((a.row_id, b.row_id)))
            for a in first.payload.rows
            for b in second.payload.rows
            if tuple(sorted((a.row_id, b.row_id))) not in visible
        )
        pair = store.source_overlap_pair(*hidden)
        assert pair.state == "pending" and set(store.source_overlap_posting_blocks(hidden)) == set(hidden)
        decide(store, *hidden, "distinct")
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.record_source_overlap_review(
                *hidden, decision="pending", reason="Stale review", expected_basis_sha256=pair.basis_sha256
            )
        assert set(store.source_overlap_posting_blocks(hidden)) == set(hidden)  # Other exact pairs remain unresolved.
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="committed_snapshot"):
            store.source_overlap_pair(*hidden)
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")


def test_shifted_posted_repair_keeps_each_journal_date_and_historical_proof_after_rebinding(tmp_path):
    path = tmp_path / "repair.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        account(store, "other")
        retained = source(store, "Later retained", source_date="10/04/2026")
        redundant = source(store, "Earlier redundant", source_date="10/01/2026")
        a, b = map(row, (retained, redundant))
        decide(store, a, b, "distinct")
        key_a = store.post_reviewed_cash_category(a, "expense:food", reason="Reviewed first occurrence")
        key_b = store.post_reviewed_cash_category(b, "expense:other", reason="Initially considered separate")
        before = store.connection.execute("SELECT * FROM JournalEntries").fetchall()
        store.connection.execute(
            "CREATE TRIGGER fail_shifted_repair BEFORE INSERT ON SourceOverlapReviews BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
            store.repair_posted_repeat(
                a,
                b,
                expected_basis_sha256=store.source_overlap_pair(a, b).basis_sha256,
                reason="Same occurrence across dates",
            )
        assert store.connection.execute("SELECT * FROM JournalEntries").fetchall() == before
        store.connection.execute("DROP TRIGGER fail_shifted_repair")
        repair = store.repair_posted_repeat(
            a,
            b,
            expected_basis_sha256=store.source_overlap_pair(a, b).basis_sha256,
            reason="Same occurrence across dates",
        )
        inverse = json.loads(
            store.connection.execute(
                "SELECT payload FROM JournalEntries WHERE key=?", (repair.reversal_key,)
            ).fetchone()[0]
        )
        assert inverse["posting_date"] == "2026-10-01"
        assert store.account_positions(as_of=date(2026, 10, 2)).accounts[0].recorded_debit_minor == 0
        assert store.account_positions(as_of=date(2026, 10, 4)).accounts[0].recorded_debit_minor == -400
        assert store.reviewed_journal_export(start=date(2026, 10, 1), end=date(2026, 11, 1)).entries[0].key == key_a
        store.withdraw_reviewed_interpretation(
            key_a,
            expected_basis_sha256=store.source_overlap_pair(a, b).basis_sha256,
            reason="Withdraw retained before binding review",
        )
        selected = BindingCorrectionTarget(redundant.source_sha256, "source", "Checking A", "opaque")
        for destination in ("other", "cash"):
            frame = store.binding_correction_snapshot(selected, destination_account_id=destination)
            store.correct_reviewed_binding(
                selected,
                destination_account_id=destination,
                expected_basis_sha256=frame.basis_sha256,
                reason="Reviewed corrected binding",
            )
        assert store._read_source_interpretation_history()[1] == (repair,)
        assert store._ordinary_category_entry(key_b, active=False)[0].postings[0].account_id == "cash"
        decide(store, a, b, retained=a)
    V2ProfileStore.snapshot_to(path, tmp_path / "repair-backup.db")


def test_card_different_source_dates_roles_and_effective_dates_repair_without_rewriting_evidence(tmp_path):
    path = tmp_path / "card.db"
    first = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        section = first.payload.accounts[0]
        store.bind_source_account(first.source_sha256, section.source_identity, section.source_identity_form, "card")
        raw = b"%PDF-shifted-synthetic-card"
        purchase = section.rows[0]
        shifted = purchase.model_copy(
            update={
                "row_id": hashlib.sha256(raw + purchase.row_id.encode()).hexdigest(),
                "date_role": "posting_date",
                "date": purchase.date.model_copy(
                    update={"iso": "2026-03-18", "raw": "03/18", "provenance": "observed"}
                ),
                "posting_date_guess": None,
            }
        )
        second = first.model_copy(
            update={
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "payload": first.payload.model_copy(
                    update={
                        "accounts": (section.model_copy(update={"rows": (shifted,)}),),
                        "independent_balance_verified": False,
                    }
                ),
            }
        )
        store.import_source(raw, CHASE_DEFINITION, second, suffix=".pdf")
        store.bind_source_account(second.source_sha256, section.source_identity, section.source_identity_form, "card")
        a, b = purchase.row_id, shifted.row_id
        with pytest.raises(ProfileFormatError, match="source_overlap_review_required"):
            store.post_reviewed_card_purchase(
                a,
                "expense:food",
                reason="Still pending source comparison",
                accounting_date=date(2026, 3, 17),
                preferences=V2Preferences(),
            )
        decide(store, a, b, "distinct")
        store.post_reviewed_card_purchase(
            a,
            "expense:food",
            reason="Reviewed actual date",
            accounting_date=date(2026, 3, 17),
            preferences=V2Preferences(),
        )
        redundant = store.post_reviewed_card_purchase(
            b, "expense:travel", reason="Reviewed shifted printed date", preferences=V2Preferences()
        )
        repair = store.repair_posted_repeat(
            a,
            b,
            expected_basis_sha256=store.source_overlap_pair(a, b).basis_sha256,
            reason="Same charge in revised export",
        )
        assert repair.redundant_entry_key == redundant
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 3, 1), end=date(2026, 4, 1)).total_minor
            == 1000
        )
        assert (
            store.load_import(first.source_sha256).evidence == first
            and store.load_import(second.source_sha256).evidence == second
        )
        assert store._read_source_interpretation_history()[1] == (repair,)
    V2ProfileStore.snapshot_to(path, tmp_path / "card-backup.db")


def test_transfer_candidate_and_posting_cannot_bypass_alias_only_pending_edge(tmp_path):
    with V2ProfileStore.create(tmp_path / "transfer.db") as store:
        setup(store)
        account(store, "savings")
        a, b, c = (
            row(source(store, label, source_date=day))
            for label, day in (("Root", "10/01/2026"), ("Support", "10/04/2026"), ("Outsider", "10/07/2026"))
        )
        receiving = source(store, "Owned receipt", amount="$4.00", source_date="10/01/2026", account_id="savings")
        decide(store, a, b, retained=a)
        assert not store.transfer_candidates(preferences=V2Preferences())
        with pytest.raises(ProfileFormatError, match="source_overlap_review_required"):
            store.post_reviewed_transfer(
                a, row(receiving), preferences=V2Preferences(), reason="Unresolved supporting source neighbor"
            )
        decide(store, b, c, "distinct")
        event = store.post_reviewed_transfer(
            a, row(receiving), preferences=V2Preferences(), reason="Explicit owned transfer"
        )
        assert store.transfer_history()[0].event_id == event
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 0
        )


def test_changed_money_sign_account_and_unbound_rows_stay_outside_wider_candidates(tmp_path):
    with V2ProfileStore.create(tmp_path / "exclusions.db") as store:
        setup(store)
        account(store, "other")
        original = source(store, "Original")
        source(store, "Revised amount", amount="-$4.01", source_date="10/02/2026")
        source(store, "Opposite sign", amount="$4.00", source_date="10/03/2026")
        source(store, "Different account", account_id="other", source_date="10/04/2026")
        unbound = source(store, "Unbound", source_date="10/02/2026")
        store.clear_source_account_binding(unbound.source_sha256, "Checking A", "opaque")
        assert store.source_overlap_inventory().total_pairs == 0
        assert not store.source_overlap_posting_blocks((row(original),))


def test_direct_pair_is_one_wal_snapshot_and_old_selection_refuses_after_concurrent_review(tmp_path, monkeypatch):
    path = tmp_path / "direct-snapshot.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        setup(store)
        a, b = (row(source(store, label, source_date=day)) for label, day in (("A", "10/01/2026"), ("B", "10/04/2026")))
        expected = store.source_overlap_pair(a, b)
        original = store._source_overlap_basis
        fired = False

        def concurrent_review():
            nonlocal fired
            if not fired:
                fired = True
                with V2ProfileStore.open(path) as writer:
                    decide(writer, a, b, "distinct")
            return original()

        monkeypatch.setattr(store, "_source_overlap_basis", concurrent_review)
        coherent = store.source_overlap_pair(a, b)
        assert coherent == expected and fired
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.record_source_overlap_review(
                a, b, decision="pending", expected_basis_sha256=coherent.basis_sha256, reason="Stale displayed pair"
            )
        assert store.source_overlap_pair(a, b).state == "distinct"


def test_prior_reconciliation_rule_history_remains_exact_stale_and_recoverable(tmp_path, monkeypatch):
    path = tmp_path / "prior-rule.db"
    evidence = bank_profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        original = store._reconciliation_rule_and_version

        def prior_rule():
            _rule, version = original()
            return "v2-statement-reconciliation-3", version

        with monkeypatch.context() as patch:
            # Emulate a successful saved decision produced by the prior rule.
            patch.setattr(store, "_reconciliation_rule_and_version", prior_rule)
            check = store.statement_reconciliation_checks()[0]
            saved = store.save_reconciliation_decision(
                "cash",
                evidence.source_sha256,
                expected_input_version=check.input_version,
                reason="Explicitly confirmed prior rule",
            )
        current = store.statement_reconciliation_checks()[0]
        assert current.rule == "v2-statement-reconciliation-4"
        history = store.reconciliation_history("cash")[0]
        assert history.stale and history.check == saved.check and history.journal_versions == saved.journal_versions
    V2ProfileStore.snapshot_to(path, tmp_path / "prior-rule-backup.db")


def test_dense_confirmed_group_prioritizes_outsider_edges_without_building_skipped_metadata(tmp_path, monkeypatch):
    with V2ProfileStore.create(tmp_path / "dense.db") as store:
        setup(store)
        members = [row(source(store, f"Dense group {index}")) for index in range(12)]
        root = members[0]
        for supporting in members[1:]:
            decide(store, root, supporting, retained=root)
        outsider = row(source(store, "Outside group"))
        constructed = []
        original = store._source_overlap_candidate

        def counted(*args):
            constructed.append((args[0].row_id, args[1].row_id))
            return original(*args)

        monkeypatch.setattr(store, "_source_overlap_candidate", counted)
        inventory = store.source_overlap_inventory(max_pairs=1)
        assert inventory.total_pairs == 78 and inventory.truncated
        assert inventory.candidates[0].state == "pending" and outsider in constructed[0]
        assert len(constructed) == 1
        actual = store.source_overlap_pair(root, members[-1])
        assert actual.state == "repeat" and len(actual.repeat_edges) == 11
        decide(store, root, outsider, "distinct")
        assert root in store.source_overlap_posting_blocks((root,))
        assert store.source_overlap_inventory(max_pairs=1).candidates[0].state == "pending"
        for supporting in members[1:]:
            decide(store, supporting, outsider, "distinct")
        assert not store.source_overlap_posting_blocks((root, outsider))
        constructed.clear()
        resolved = store.source_overlap_inventory(max_pairs=1)
        assert resolved.total_pairs == 78 and resolved.candidates[0].state in {"repeat", "distinct"}
        assert len(constructed) == 1
        assert store.source_overlap_pair(root, members[-1]).state == "repeat"

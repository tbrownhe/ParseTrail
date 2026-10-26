"""Cross-source equality requires explicit occurrence review before allocation."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_card_lines import parse_card_lines
from parsetrail.core.v2_card_source_output import from_card
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

from devtools.parser_engine_pilot.test_card_lines import pages
from devtools.parser_engine_pilot.test_card_source_output import DEFINITION as CARD_DEFINITION

from .test_v2_statement_journal_comparison import _profile as bank_profile

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()


def account(store, account_id="cash"):
    store.add_financial_account(FinancialAccount(account_id, account_id.title(), "asset", "synthetic"))


def source(
    store,
    label,
    *,
    count=1,
    account_id="cash",
    amount="-$4.00",
    source_date="10/01/2026",
    date_role="posting_date",
    date_provenance="observed",
):
    content = b"Date,Account,Description,Amount,ReportedBalance\n" + b"".join(
        f"{source_date},Checking A,{label} {index},{amount},$996.00\n".encode() for index in range(count)
    )
    evidence = build_source_evidence(content, DEFINITION, suffix=".csv")
    if date_role != "posting_date" or date_provenance != "observed":
        evidence = evidence.model_copy(
            update={
                "payload": evidence.payload.model_copy(
                    update={
                        "rows": tuple(
                            row.model_copy(
                                update={
                                    "date_role": date_role,
                                    "date": row.date.model_copy(
                                        update={
                                            "provenance": date_provenance,
                                            "raw": row.date.raw if date_provenance == "observed" else None,
                                        }
                                    ),
                                }
                            )
                            for row in evidence.payload.rows
                        ),
                    }
                )
            }
        )
    store.import_source(content, DEFINITION, evidence, suffix=".csv")
    store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", account_id)
    return evidence


def review(store, first, second, decision="repeat", retained=None, reason="Compared original source occurrences"):
    pair = next(
        pair
        for pair in store.source_overlap_inventory(max_pairs=10_000).candidates
        if {pair.left.row_id, pair.right.row_id} == {first, second}
    )
    return store.record_source_overlap_review(
        first,
        second,
        decision=decision,
        retained_row_id=retained if decision == "repeat" else None,
        reason=reason,
        expected_basis_sha256=pair.basis_sha256,
    )


def setup(store):
    account(store)
    store.add_category_account("expense:food", "Food", "expense")
    store.add_category_account("expense:other", "Other", "expense")


def test_repeat_is_support_only_with_exact_posting_and_reopen_snapshot(tmp_path):
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile) as store:
        setup(store)
        first, second = source(store, "Coffee"), source(store, "COFFEE export")
        original_first = store.load_import(first.source_sha256).source
        original_second = store.load_import(second.source_sha256).source
        retained, excluded = first.payload.rows[0].row_id, second.payload.rows[0].row_id
        inventory = store.source_overlap_inventory()
        assert inventory.total_pairs == 1 and not inventory.truncated
        pair = inventory.candidates[0]
        assert pair.state == "pending"
        assert pair.left.amount_minor == pair.right.amount_minor == -400
        assert pair.left.locations and pair.left.source_date == "2026-10-01"
        assert len(store.source_overlap_posting_blocks((retained, excluded))) == 2
        with pytest.raises(ProfileFormatError, match="source_overlap_review_required"):
            store.post_reviewed_cash_category(retained, "expense:food", reason="Not yet resolved")
        assert not store.connection.in_transaction
        decided = review(store, retained, excluded, retained=retained)
        assert decided.state == "repeat" and decided.retained_row_id == retained
        assert store.source_overlap_posting_blocks((retained, excluded)) == {
            excluded: "Repeated supporting evidence; post the retained row"
        }
        key = store.post_reviewed_cash_category(retained, "expense:food", reason="Reviewed coffee")
        assert store.post_reviewed_cash_category(retained, "expense:food", reason="Reviewed coffee") == key
        with pytest.raises(ProfileFormatError, match="source_overlap_review_required"):
            store.post_reviewed_cash_category(excluded, "expense:food", reason="Would double expense")
        assert store._active_consumed() == {retained: -400}
        assert store._unallocated_activity_counts() == (1, 1)
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 400
        )
        store.correct_reviewed_cash_category(key, "expense:other", reason="Correct reviewed category")
        assert excluded in store.source_overlap_posting_blocks((excluded,))
        assert store._active_consumed() == {retained: -400}
        assert store.load_import(first.source_sha256).evidence == first
        assert store.load_import(second.source_sha256).evidence == second
        assert store.load_import(first.source_sha256).source == original_first
        assert store.load_import(second.source_sha256).source == original_second
    backup = V2ProfileStore.snapshot_to(profile, tmp_path / "backup.db")
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.source_overlap_inventory().candidates[0].state == "repeat"
        assert store._active_consumed() == {retained: -400}
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            review(store, retained, excluded, "pending")


def test_distinct_legitimate_purchases_post_twice_then_pending_undo_blocks_new_money(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        first, second = source(store, "First coffee"), source(store, "Second coffee")
        a, b = first.payload.rows[0].row_id, second.payload.rows[0].row_id
        decision = review(store, a, b, "distinct")
        assert not store.source_overlap_posting_blocks((a, b))
        again = review(store, a, b, "distinct")
        assert again.revision_id == decision.revision_id
        review(store, a, b, "pending")
        assert len(store.source_overlap_posting_blocks((a, b))) == 2
        review(store, a, b, "distinct")
        store.post_reviewed_cash_category(a, "expense:food", reason="First actual purchase")
        store.post_reviewed_cash_category(b, "expense:food", reason="Second actual purchase")
        assert store._active_consumed() == {a: -400, b: -400}


def test_review_stale_after_binding_posting_correction_or_other_review(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        account(store, "other")
        first, second = source(store, "First"), source(store, "Second")
        a, b = first.payload.rows[0].row_id, second.payload.rows[0].row_id
        pair = store.source_overlap_inventory().candidates[0]
        store.bind_source_account(second.source_sha256, "Checking A", "opaque", "other")
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.record_source_overlap_review(
                a, b, decision="distinct", reason="Stale binding", expected_basis_sha256=pair.basis_sha256
            )
        store.bind_source_account(second.source_sha256, "Checking A", "opaque", "cash")
        stale = store.source_overlap_inventory().candidates[0]
        review(store, a, b, "distinct")
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.record_source_overlap_review(
                a, b, decision="pending", reason="Stale review", expected_basis_sha256=stale.basis_sha256
            )
        stale = store.source_overlap_inventory().candidates[0]
        key = store.post_reviewed_cash_category(a, "expense:food", reason="Reviewed")
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.record_source_overlap_review(
                a,
                b,
                decision="repeat",
                retained_row_id=a,
                reason="Stale posting",
                expected_basis_sha256=stale.basis_sha256,
            )
        stale = store.source_overlap_inventory().candidates[0]
        store.correct_reviewed_cash_category(key, "expense:other", reason="Correction")
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.record_source_overlap_review(
                a,
                b,
                decision="repeat",
                retained_row_id=a,
                reason="Stale correction",
                expected_basis_sha256=stale.basis_sha256,
            )


def test_repeat_binds_rows_forever_and_retained_correction_does_not_reactivate_alias(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        account(store, "other")
        first, second = source(store, "First"), source(store, "Second")
        a, b = first.payload.rows[0].row_id, second.payload.rows[0].row_id
        review(store, a, b, retained=a)
        assert store.source_overlap_history_row_ids(second.source_sha256) == {b}
        assert not store.journal_history_row_ids(second.source_sha256)
        with pytest.raises(ProfileFormatError, match="account_binding_has_overlap_review_history"):
            store.bind_source_account(second.source_sha256, "Checking A", "opaque", "other")
        with pytest.raises(ProfileFormatError, match="account_binding_has_overlap_review_history"):
            store.clear_source_account_binding(second.source_sha256, "Checking A", "opaque")
        review(store, a, b, "pending")
        assert len(store.source_overlap_posting_blocks((a, b))) == 2
        assert store.connection.execute("SELECT COUNT(*) FROM SourceOverlapReviews").fetchone() == (2,)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store.connection.execute("DELETE FROM SourceOverlapReviews")


def test_multiplicity_one_occurrence_per_source_and_independent_two_by_two(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        first, second = source(store, "First", count=2), source(store, "Second", count=2)
        a1, a2 = [row.row_id for row in first.payload.rows]
        b1, b2 = [row.row_id for row in second.payload.rows]
        assert store.source_overlap_inventory().total_pairs == 4
        review(store, a1, b1, retained=b1)
        with pytest.raises(ProfileFormatError, match="occurrence_multiplicity"):
            review(store, a2, b1, retained=b1)
        review(store, a2, b2, retained=b2)
        assert set(store.source_overlap_posting_blocks((a1, a2, b1, b2))) == {a1, a2, b1, b2}
        review(store, a1, b2, "distinct")
        review(store, a2, b1, "distinct")
        assert store.source_overlap_posting_blocks((a1, a2, b1, b2)).keys() == {a1, a2}
        store.post_reviewed_cash_category(b1, "expense:food", reason="Occurrence one")
        store.post_reviewed_cash_category(b2, "expense:food", reason="Occurrence two")
        assert store._active_consumed() == {b1: -400, b2: -400}


def test_no_chains_cycles_or_distinct_contradictions(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        ids = [source(store, name).payload.rows[0].row_id for name in ("A", "B", "C")]
        a, b, c = ids
        review(store, a, c, "distinct")
        review(store, a, b, retained=b)
        with pytest.raises(ProfileFormatError, match="chain_or_conflict"):
            review(store, b, c, retained=c)
        with pytest.raises(ProfileFormatError, match="chain_or_conflict"):
            review(store, a, c, retained=a)
        with pytest.raises(ProfileFormatError, match="conflicts_with_distinct"):
            review(store, b, c, retained=b)
        review(store, a, b, "pending")
        review(store, b, c, retained=c)
        assert b in store.source_overlap_posting_blocks((b,))


def test_both_posted_are_visible_conflict_and_never_silently_excluded(tmp_path, monkeypatch):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        first = source(store, "First")
        a = first.payload.rows[0].row_id
        original = store.post_reviewed_cash_category(a, "expense:food", reason="Before second source")
        second = source(store, "Second")
        b = second.payload.rows[0].row_id
        # Reproduce journal history written before this safeguard existed.
        with monkeypatch.context() as patch:
            patch.setattr(store, "_require_source_overlap_postable", lambda _row_ids: None)
            store.post_reviewed_cash_category(b, "expense:food", reason="Earlier duplicate mistake")
        assert store.source_overlap_inventory().candidates[0].state == "posted_conflict"
        with pytest.raises(ProfileFormatError, match="excluded_has_journal_history"):
            review(store, a, b, retained=a)
        assert store.connection.execute("SELECT COUNT(*) FROM SourceOverlapReviews").fetchone() == (0,)
        store.correct_reviewed_cash_category(original, "expense:other", reason="Still permit category correction")
        assert store._active_consumed() == {a: -400, b: -400}


def test_inventory_cap_advances_pending_and_guard_covers_hidden_pairs(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        first, second = source(store, "First", count=3), source(store, "Second", count=3)
        a = [row.row_id for row in first.payload.rows]
        b = [row.row_id for row in second.payload.rows]
        for number in range(9):
            inventory = store.source_overlap_inventory(max_pairs=1)
            assert inventory.total_pairs == 9 and inventory.truncated
            pair = inventory.candidates[0]
            assert pair.state == "pending"
            store.record_source_overlap_review(
                pair.left.row_id,
                pair.right.row_id,
                decision="distinct",
                reason="Separate actual occurrences",
                expected_basis_sha256=pair.basis_sha256,
            )
            if number == 0:
                hidden = next(row_id for row_id in a + b if row_id not in (pair.left.row_id, pair.right.row_id))
                assert hidden in store.source_overlap_posting_blocks((hidden,))
        assert not store.source_overlap_posting_blocks(tuple(a + b))
        assert store.source_overlap_inventory(max_pairs=1).candidates[0].state == "distinct"


def test_unbound_other_account_far_date_and_zero_are_not_matched(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        account(store, "other")
        first = source(store, "First")
        source(store, "Other account", account_id="other")
        source(store, "Other date", source_date="10/05/2026")
        source(store, "Zero", amount="$0.00")
        source(store, "Other sign", amount="$4.00")
        second = source(store, "Unbound")
        store.clear_source_account_binding(second.source_sha256, "Checking A", "opaque")
        assert store.source_overlap_inventory().total_pairs == 0
        assert not store.source_overlap_posting_blocks((first.payload.rows[0].row_id,))


@pytest.mark.parametrize("provenance", ["observed", "derived", "assumed"])
def test_candidate_retains_original_date_provenance_without_certifying_it(tmp_path, provenance):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        first = source(store, "First", date_role="activity_date")
        second = source(store, "Second", date_role="activity_date", date_provenance=provenance)
        row_id = second.payload.rows[0].row_id
        pair = store.source_overlap_inventory().candidates[0]
        row = pair.left if pair.left.row_id == row_id else pair.right
        assert row.source_date == "2026-10-01" and row.date_role == "activity_date"
        assert row.date_provenance == provenance
        review(store, first.payload.rows[0].row_id, row_id, retained=first.payload.rows[0].row_id)
        assert store.load_import(second.source_sha256).evidence == second
        assert store.load_import(second.source_sha256).evidence.payload.rows[0].date.provenance == provenance
        assert store.load_import(second.source_sha256).evidence.payload.rows[0].row_id == row_id


def test_schema_ten_refused_without_write(tmp_path):
    path = tmp_path / "old.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA user_version=10")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("incoming_date,entry_count", [("10/01/2026", 1), ("10/02/2026", 2)])
def test_transfer_guard_covers_repeated_leg_and_preserves_source_dated_clearing(tmp_path, incoming_date, entry_count):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        account(store, "savings")
        outgoing, repeated = source(store, "Payment"), source(store, "Payment export")
        incoming = source(store, "Receipt", account_id="savings", amount="$4.00", source_date=incoming_date)
        out_id, repeated_id = outgoing.payload.rows[0].row_id, repeated.payload.rows[0].row_id
        in_id = incoming.payload.rows[0].row_id
        assert not store.transfer_candidates(preferences=V2Preferences())
        with pytest.raises(ProfileFormatError, match="source_overlap_review_required"):
            store.post_reviewed_transfer(out_id, in_id, preferences=V2Preferences(), reason="Pending candidate")
        review(store, out_id, repeated_id, retained=out_id)
        event = store.post_reviewed_transfer(out_id, in_id, preferences=V2Preferences(), reason="Owned savings")
        assert store._active_consumed() == {out_id: -400, in_id: 400}
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (entry_count,)
        with pytest.raises(ProfileFormatError, match="source_overlap_review_required"):
            store.post_reviewed_transfer(repeated_id, in_id, preferences=V2Preferences(), reason="Repeat blocked")
        assert store.post_reviewed_transfer(out_id, in_id, preferences=V2Preferences(), reason="Owned savings") == event
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 0
        )


def test_card_guard_and_retained_date_correction_do_not_allocate_support(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "chase"))
        store.add_category_account("expense:food", "Food", "expense")
        evidences = []
        for content in (b"%PDF-overlap-card-one", b"%PDF-overlap-card-two"):
            lines = page_lines(content, pages(), extraction_library="synthetic-pdf-1")
            evidence = from_card(parse_card_lines(CARD_DEFINITION, lines), lines)
            store.import_source(content, CARD_DEFINITION, evidence, suffix=".pdf")
            section = evidence.payload.accounts[0]
            store.bind_source_account(
                evidence.source_sha256, section.source_identity, section.source_identity_form, "card"
            )
            evidences.append(evidence)
        a, b = [evidence.payload.accounts[0].rows[0].row_id for evidence in evidences]
        prefs = V2Preferences(False, True)
        with pytest.raises(ProfileFormatError, match="source_overlap_review_required"):
            store.post_reviewed_card_purchase(a, "expense:food", reason="Needs occurrence review", preferences=prefs)
        review(store, a, b, retained=a)
        key = store.post_reviewed_card_purchase(a, "expense:food", reason="Reviewed charge", preferences=prefs)
        store.correct_reviewed_card_purchase(
            key, "expense:food", accounting_date=date(2026, 3, 17), reason="Explicit date correction"
        )
        assert store._active_consumed() == {a: -1000}
        with pytest.raises(ProfileFormatError, match="source_overlap_review_required"):
            store.post_reviewed_card_purchase(b, "expense:food", reason="Support cannot post", preferences=prefs)


def test_failed_review_and_posting_rollback_leave_no_partial_decision_or_money(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        first, second = source(store, "First"), source(store, "Second")
        a, b = first.payload.rows[0].row_id, second.payload.rows[0].row_id
        store.connection.execute(
            "CREATE TRIGGER test_refuse_review BEFORE INSERT ON SourceOverlapReviews "
            "BEGIN SELECT RAISE(ABORT,'injected review failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected review failure"):
            review(store, a, b, retained=a)
        store.connection.execute("DROP TRIGGER test_refuse_review")
        assert store.connection.execute("SELECT COUNT(*) FROM SourceOverlapReviews").fetchone() == (0,)
        review(store, a, b, retained=a)
        store.connection.execute(
            "CREATE TRIGGER test_refuse_allocation BEFORE INSERT ON JournalAllocations "
            "BEGIN SELECT RAISE(ABORT,'injected allocation failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected allocation failure"):
            store.post_reviewed_cash_category(a, "expense:food", reason="Atomic failure")
        store.connection.execute("DROP TRIGGER test_refuse_allocation")
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalAllocations").fetchone() == (0,)
        assert b in store.source_overlap_posting_blocks((b,))


def test_different_retained_roots_remain_pending_actual_pairs_not_a_false_repeat_claim(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        first, second = source(store, "First", count=2), source(store, "Second", count=2)
        a1, a2 = [row.row_id for row in first.payload.rows]
        b1, b2 = [row.row_id for row in second.payload.rows]
        review(store, a1, b1, retained=b1)
        review(store, a2, b2, retained=b2)
        inventory = store.source_overlap_inventory()
        for pair in inventory.candidates:
            expected = "repeat" if {pair.left.row_id, pair.right.row_id} in ({a1, b1}, {a2, b2}) else "pending"
            assert pair.state == expected


def test_default_inventory_cap_does_not_weaken_unseen_posting_guard(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        first, second = source(store, "First", count=46), source(store, "Second", count=46)
        inventory = store.source_overlap_inventory()
        assert inventory.truncated and inventory.total_pairs == 2116 and len(inventory.candidates) == 2000
        visible = {(pair.left.row_id, pair.right.row_id) for pair in inventory.candidates}
        unseen = next(
            (left.row_id, right.row_id)
            for left in first.payload.rows
            for right in second.payload.rows
            if tuple(sorted((left.row_id, right.row_id))) not in visible
        )
        assert set(store.source_overlap_posting_blocks(unseen)) == set(unseen)


def test_repeat_constraint_refuses_null_retained_row(tmp_path):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        setup(store)
        first, second = source(store, "First"), source(store, "Second")
        left, right = sorted((first.payload.rows[0].row_id, second.payload.rows[0].row_id))
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            store.connection.execute(
                "INSERT INTO SourceOverlapReviews "
                "(left_row_id,right_row_id,decision,retained_row_id,basis_sha256,reason) VALUES (?,?,'repeat',NULL,?,?)",
                (left, right, "synthetic invalid basis", "Missing retained identity"),
            )
        assert store.connection.execute("SELECT COUNT(*) FROM SourceOverlapReviews").fetchone() == (0,)


def test_reconciliation_versions_review_and_keeps_support_distinct_from_allocation(tmp_path):
    path = tmp_path / "fresh.db"
    original = bank_profile(path)
    content = b"synthetic repeated bank statement bytes"
    with V2ProfileStore.open(path) as store:
        saved = store.load_import(original.source_sha256)
        section = original.payload.accounts[0]
        repeated_rows = tuple(
            row.model_copy(update={"row_id": hashlib.sha256(content + row.row_id.encode()).hexdigest()})
            for row in section.rows
        )
        repeated = original.model_copy(
            update={
                "source_sha256": hashlib.sha256(content).hexdigest(),
                "payload": original.payload.model_copy(
                    update={
                        "accounts": (section.model_copy(update={"rows": repeated_rows}),),
                    }
                ),
            }
        )
        store.import_source(content, saved.definition, repeated, suffix=".pdf")
        store.bind_source_account(repeated.source_sha256, section.source_identity, section.source_identity_form, "cash")
        before = {item.source_sha256: item for item in store.statement_reconciliation_checks()}
        assert all("cross_source_occurrence_review_pending" in item.coverage_warnings for item in before.values())
        for retained, supporting in zip(section.rows, repeated_rows, strict=True):
            review(store, retained.row_id, supporting.row_id, retained=retained.row_id)
        after = {item.source_sha256: item for item in store.statement_reconciliation_checks()}
        checked = after[repeated.source_sha256]
        assert "confirmed_repeated_supporting_evidence" in checked.coverage_warnings
        assert "cross_source_occurrence_review_pending" not in checked.coverage_warnings
        assert "unallocated_source_movements" in checked.exceptions
        assert not checked.reconciled
        assert checked.input_version != before[repeated.source_sha256].input_version
        assert checked.rule == "v2-statement-reconciliation-5"
        assert not store._active_consumed()

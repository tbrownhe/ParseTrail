import json
from dataclasses import replace

import pytest
from parsetrail.core.ledger import AccountKind, LedgerAccount, LedgerError, Posting
from parsetrail.core.ledger_expense_corrections import ExpenseCorrections
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reviewed_reconciliation import ReviewedReconciliation
from parsetrail.core.ledger_store import decode_entry, encoded
from parsetrail.core.ledger_transfers import TransferReview

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_reviewed_reconciliation import finish_cash_card, prepare_custom


@pytest.fixture
def workspace(tmp_path, rebuild):
    rebuild["legacy_metadata"]["Categories"] += [
        {"CategoryID": 2, "Name": "Household", "Type": "Expense", "ParentID": None},
        {"CategoryID": 3, "Name": "Salary", "Type": "Income", "ParentID": None},
    ]
    return prepare_custom(tmp_path, rebuild)


def posted(review, pid="proposal:bank_purchase"):
    review.decide([pid], "accepted")
    return review.decisions()[pid]["entry_key"]


@pytest.mark.parametrize("pid,amount", [("proposal:bank_purchase", 1500), ("proposal:card_refund", 500)])
def test_exact_split_preserves_financial_movement_evidence_and_category_history(workspace, pid, amount):
    with ProposalReview(workspace[0]) as review:
        original_key = posted(review, pid)
        c = review.store.connection
        before = {
            table: c.execute(f"SELECT * FROM {table}").fetchall()
            for table in (
                "SourceTransactions",
                "SourceStatements",
                "SourceMemberships",
                "CategoryDefinitions",
                "CategoryAnnotations",
                "CategoryDecisions",
                "ProposalDecisions",
                "LedgerObservations",
            )
        }
        original = decode_entry(
            c.execute("SELECT payload FROM LedgerEntries WHERE key=?", (original_key,)).fetchone()[0]
        )
        balances = review.store.balances(original.posting_date)
        used = review.store.consumed()
        service = ExpenseCorrections(review)
        db = list(c.iterdump())
        plan = service.preview(original_key, [(2, amount - 100), (1, 100)], "Split personal purchase")
        assert list(c.iterdump()) == db
        assert plan == service.preview(original_key, [(1, 100), (2, amount - 100)], "Split personal purchase")
        replacement_key = service.apply(plan)
        replacement = decode_entry(
            c.execute("SELECT payload FROM LedgerEntries WHERE key=?", (replacement_key,)).fetchone()[0]
        )
        assert replacement.postings[0] == original.postings[0]
        assert replacement.posting_date == original.posting_date and replacement.event_id == original.event_id
        assert replacement.reviewed and replacement.reason == "Split personal purchase"
        sign = 1 if original.postings[0].amount_minor < 0 else -1
        assert [(p.account_id, p.amount_minor) for p in replacement.postings[1:]] == [
            ("category:1", sign * 100),
            ("category:2", sign * (amount - 100)),
        ]
        after_balances = review.store.balances(original.posting_date)
        assert after_balances[original.postings[0].account_id] == balances[original.postings[0].account_id]
        assert after_balances["category:1"] + after_balances["category:2"] == balances["category:1"]
        assert review.store.consumed() == used
        for table, rows in before.items():
            assert c.execute(f"SELECT * FROM {table}").fetchall() == rows
        assert c.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (3,)
        assert review.store.entry_status(original_key)["superseded"]
        saved = list(c.iterdump())
        assert service.apply(plan) == replacement_key
        assert list(c.iterdump()) == saved
    with ProposalReview(workspace[0]) as review:
        assert ExpenseCorrections(review).apply(json.loads(encoded(plan))) == replacement_key
        assert review.store.entry_status(replacement_key)["reviewed"]


@pytest.mark.parametrize(
    "splits",
    [
        [],
        [(1, 1499)],
        [(1, 1600)],
        [(1, 1000), (1, 500)],
        [(1, 0), (2, 1500)],
        [(2, -1500)],
        [(2, True)],
        [(2, 1500.0)],
        [(True, 1500)],
        [(3, 1500)],
        [(999, 1500)],
        [(1, 1500)],
    ],
)
def test_invalid_or_noop_split_does_not_mutate(workspace, splits):
    with ProposalReview(workspace[0]) as review:
        original_key = posted(review)
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError):
            ExpenseCorrections(review).preview(original_key, splits, "Explicit correction")
        assert list(review.store.connection.iterdump()) == before


def test_reason_required_and_unposted_proposal_cannot_be_corrected(workspace):
    with ProposalReview(workspace[0]) as review:
        service = ExpenseCorrections(review)
        with pytest.raises(LedgerError, match="does not exist"):
            service.preview("proposal:bank_purchase", [(2, 1500)], "Correction")
        original_key = posted(review)
        with pytest.raises(LedgerError, match="nonempty"):
            service.preview(original_key, [(2, 1500)], " ")


def test_transfer_and_partial_observation_are_not_expense_corrections(workspace):
    with ProposalReview(workspace[0]) as review:
        transfers = TransferReview(review)
        pair = transfers.snapshot()["pairs"][0]
        transfers.decide([(pair["outgoing_id"], pair["incoming_id"])], "confirmed")
        service = ExpenseCorrections(review)
        transfer_key = review.store.connection.execute("SELECT entry_key FROM TransferEntries").fetchone()[0]
        with pytest.raises(LedgerError, match="Only ordinary"):
            service.preview(transfer_key, [(2, 1000)], "Do not relabel a card payment")
        draft = decode_entry(review.proposals["proposal:bank_purchase"])
        bank, expense = draft.postings
        partial = replace(
            draft,
            key="partial",
            postings=(
                replace(bank, amount_minor=-1000, allocations=(replace(bank.allocations[0], amount_minor=-1000),)),
                replace(expense, amount_minor=1000),
            ),
        )
        review.store.post(partial)
        with pytest.raises(LedgerError, match="whole source"):
            service.preview("partial", [(2, 1000)], "Partial movement needs another workflow")


def test_preview_tampering_and_changed_review_are_rejected(workspace):
    with ProposalReview(workspace[0]) as review:
        original_key = posted(review)
        service = ExpenseCorrections(review)
        plan = service.preview(original_key, [(2, 1500)], "Reclassify")
        changed = json.loads(encoded(plan))
        changed["replacement"]["description"] = "Altered"
        with pytest.raises(LedgerError, match="preview changed"):
            service.apply(changed)
        changed["preview_hash"] = key({k: v for k, v in changed.items() if k != "preview_hash"})
        with pytest.raises(LedgerError, match="inputs changed"):
            service.apply(changed)
        review.store.review(original_key, reviewed=False, reason="Review revised in another window")
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError, match="inputs changed"):
            service.apply(plan)
        assert list(review.store.connection.iterdump()) == before


def test_concurrent_correction_and_correction_chain(workspace):
    with ProposalReview(workspace[0]) as review, ProposalReview(workspace[0]) as other:
        original_key = posted(review)
        first, second = ExpenseCorrections(review), ExpenseCorrections(other)
        stale = first.preview(original_key, [(2, 1500)], "First draft")
        accepted = second.preview(original_key, [(1, 500), (2, 1000)], "Changed split")
        replacement = second.apply(accepted)
        with pytest.raises(LedgerError, match="already corrected"):
            first.apply(stale)
        with pytest.raises(LedgerError, match="active replacement"):
            first.preview(original_key, [(2, 1500)], "Another correction")
        final = first.apply(first.preview(replacement, [(2, 1500)], "Finish correcting category"))
        assert not review.store.entry_status(final)["superseded"]
        assert review.store.entry_status(replacement)["superseded"]
        assert review.store.consumed()["source:bank_purchase"] == -1500
        assert review.store.connection.execute("SELECT count(*) FROM LedgerCorrections").fetchone() == (2,)


def test_atomic_failure_rolls_back_new_category_reversal_replacement_and_allocations(workspace):
    import sqlite3

    with ProposalReview(workspace[0]) as review:
        original_key = posted(review)
        service = ExpenseCorrections(review)
        plan = service.preview(original_key, [(2, 1500)], "Reclassify")
        c = review.store.connection
        c.execute(
            "CREATE TRIGGER fail_correction BEFORE INSERT ON LedgerCorrections BEGIN SELECT RAISE(ABORT,'interrupted'); END"
        )
        before = list(c.iterdump())
        with pytest.raises(sqlite3.IntegrityError, match="interrupted"):
            service.apply(plan)
        assert list(c.iterdump()) == before and "category:2" not in review.store.accounts()
        c.execute("DROP TRIGGER fail_correction")
        service.apply(plan)


def test_correction_invalidates_reconciliation_but_keeps_balances_and_evidence_matched(workspace):
    with ProposalReview(workspace[0]) as review:
        finish_cash_card(review, workspace[1])
        reconciliation = ReviewedReconciliation(review)
        before = reconciliation.snapshot()
        service = ExpenseCorrections(review)
        service.apply(service.preview("accepted:proposal:bank_purchase", [(2, 1500)], "Reviewed category change"))
        assert not reconciliation.is_current(before)
        after = reconciliation.snapshot()
        old = next(r for r in before["statements"] if r["statement_id"] == "s1")
        new = next(r for r in after["statements"] if r["statement_id"] == "s1")
        assert old["reconciled"] and new["reconciled"]
        assert old["balance_check"] == new["balance_check"]
        assert not new["unresolved_observations"]


def test_non_imported_entries_and_transactionless_kernel_primitive_are_rejected(workspace):
    with ProposalReview(workspace[0]) as review:
        original_key = posted(review)
        service = ExpenseCorrections(review)
        plan = service.preview(original_key, [(2, 1500)], "Reclassify")
        original = decode_entry(
            review.store.connection.execute(
                "SELECT payload FROM LedgerEntries WHERE key=?", (original_key,)
            ).fetchone()[0]
        )
        review.store.load_batch(
            accounts=[LedgerAccount("equity:test", "Opening equity", AccountKind.EQUITY, purpose="opening_equity")],
            observations=[],
            statements=[],
            entries=[],
        )
        for origin, counterpart in (("opening", "equity:test"), ("manual", "category:1")):
            review.store.post(
                replace(
                    original,
                    key=origin,
                    origin=origin,
                    reason="Synthetic scope test",
                    postings=(Posting("account:1", -1500), Posting(counterpart, 1500)),
                )
            )
            with pytest.raises(LedgerError, match="Only ordinary"):
                service.preview(origin, [(2, 1500)], "Out of scope")
        with pytest.raises(LedgerError, match="enclosing transaction"):
            review.store._correct(original_key, decode_entry(encoded(plan["replacement"])), reason=plan["reason"])

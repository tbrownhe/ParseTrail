import json
import sqlite3
from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.ledger import AccountKind, LedgerAccount, LedgerError
from parsetrail.core.ledger_expense_corrections import ExpenseCorrections
from parsetrail.core.ledger_expense_interpretations import ExpenseInterpretations
from parsetrail.core.ledger_income import IncomeCorrections, IncomeInterpretations
from parsetrail.core.ledger_opening_review import OpeningReview
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reviewed_reconciliation import ReviewedReconciliation
from parsetrail.core.ledger_store import decode_entry, encoded
from parsetrail.core.ledger_transfers import TransferReview

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_reviewed_reconciliation import prepare_custom


@pytest.fixture
def income_workspace(tmp_path, rebuild):
    rebuild["legacy_metadata"]["Categories"] += [
        {"CategoryID": 3, "Name": "Salary", "Type": "Income", "ParentID": None},
        {"CategoryID": 4, "Name": "Interest", "Type": "Income", "ParentID": None},
    ]
    rebuild["evidence"]["transactions"]["interest"]["AmountMinor"] = 1000
    rebuild["evidence"]["statements"]["s3"]["closing_minor"] = 1000
    return prepare_custom(tmp_path, rebuild)


def test_income_exact_net_receipt_preview_post_and_reopen(income_workspace):
    folder, readiness = income_workspace
    with ProposalReview(folder) as review:
        OpeningReview(review, readiness)
        service, c = IncomeInterpretations(review), review.store.connection
        before = list(c.iterdump())
        assert [r["observation_id"] for r in service.inventory()] == ["source:interest"]
        plan = service.preview("source:interest", [(4, 999), (3, 1)])
        assert plan == service.preview("source:interest", [(3, 1), (4, 999)])
        assert list(c.iterdump()) == before
        report = ReviewedReconciliation(review).snapshot()
        evidence_tables = (
            "SourceTransactions",
            "SourceStatements",
            "SourceMemberships",
            "CategoryAnnotations",
            "ProposalDecisions",
        )
        evidence = {t: c.execute(f"SELECT * FROM {t}").fetchall() for t in evidence_tables}
        entry_key = service.apply(plan)
        entry = decode_entry(c.execute("SELECT payload FROM LedgerEntries WHERE key=?", (entry_key,)).fetchone()[0])
        assert entry.postings[0].account_id == "account:3" and entry.postings[0].amount_minor == 1000
        assert [(p.account_id, p.amount_minor) for p in entry.postings[1:]] == [
            ("category:3", -1),
            ("category:4", -999),
        ]
        assert entry.description == "interest" and entry.event_id == "event:interest"
        assert entry.reviewed and entry.reason == service.default_reason
        assert str(entry.posting_date) == "2026-08-20"
        assert review.store.consumed()["source:interest"] == 1000
        assert not ReviewedReconciliation(review).is_current(report)
        assert not service.inventory()
        assert not ExpenseCorrections(review).entries()
        assert IncomeCorrections(review).entries()[0]["entry"]["key"] == entry_key
        assert all(c.execute(f"SELECT * FROM {t}").fetchall() == evidence[t] for t in evidence_tables)
        after = list(c.iterdump())
        assert service.apply(plan) == entry_key and list(c.iterdump()) == after
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("DELETE FROM IncomeInterpretations")
    with ProposalReview(folder, read_only=True) as review:
        assert not IncomeInterpretations(review).inventory()
        assert IncomeCorrections(review).entries()[0]["active"]
    with ProposalReview(folder) as review:
        assert IncomeInterpretations(review).apply(json.loads(encoded(plan))) == entry_key


@pytest.mark.parametrize(
    "oid",
    [
        "source:bank_purchase",
        "source:bank_payment",
        "source:card_refund",
        "source:card_payment",
        "source:zero",
        "source:loan",
        "source:missing",
    ],
)
def test_income_excludes_outflows_card_credits_and_outside_scope(income_workspace, oid):
    with ProposalReview(income_workspace[0]) as review:
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError, match="positive, eligible"):
            IncomeInterpretations(review).preview(oid, [(3, 1000)])
        assert list(review.store.connection.iterdump()) == before


@pytest.mark.parametrize(
    "splits", [[(1, 1000)], [(3, 999)], [(3, 1001)], [(3, 500), (3, 500)], [(3, 1000.0)], [(4, -1000)]]
)
def test_income_split_rejects_expenses_and_invalid_amounts(income_workspace, splits):
    with ProposalReview(income_workspace[0]) as review:
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError):
            IncomeInterpretations(review).preview("source:interest", splits)
        assert list(review.store.connection.iterdump()) == before


def test_prior_expense_refund_must_be_rejected_before_income_classification(income_workspace):
    with ProposalReview(income_workspace[0]) as review:
        service = IncomeInterpretations(review)
        with pytest.raises(LedgerError, match="existing ordinary proposal"):
            service.preview("source:bank_refund", [(3, 200)])
        review.decide(["proposal:bank_refund"], "rejected", "This deposit is income rather than a refund")
        with pytest.raises(LedgerError, match="nonempty"):
            service.preview("source:bank_refund", [(3, 200)])
        plan = service.preview("source:bank_refund", [(3, 200)], "Reviewed receipt as income")
        service.apply(plan)
        assert review.decisions()["proposal:bank_refund"]["action"] == "rejected"
        assert plan["proposal"]["payload"]["postings"][1]["account_id"] == "category:1"


def test_concurrent_transfer_or_expense_blocks_income_posting(income_workspace):
    with ProposalReview(income_workspace[0]) as review, ProposalReview(income_workspace[0]) as other:
        service = IncomeInterpretations(review)
        plan = service.preview("source:interest", [(4, 1000)])
        TransferReview(other).decide([("source:bank_payment", "source:interest")], "confirmed")
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError, match="already allocated"):
            service.apply(plan)
        assert list(review.store.connection.iterdump()) == before
        review.decide(["proposal:bank_refund"], "rejected", "Review")
        plan = service.preview("source:bank_refund", [(3, 200)], "Income")
        expenses = ExpenseInterpretations(other)
        expenses.apply(expenses.preview("source:bank_refund", [(1, 200)], "Reviewed as refund"))
        with pytest.raises(LedgerError, match="already allocated"):
            service.apply(plan)


def test_income_category_correction_keeps_total_movement_and_history(income_workspace):
    with ProposalReview(income_workspace[0]) as review:
        service = IncomeInterpretations(review)
        original_plan = service.preview("source:interest", [(3, 1000)])
        original = service.apply(original_plan)
        corrections = IncomeCorrections(review)
        before = list(review.store.connection.iterdump())
        plan = corrections.preview(original, [(3, 100), (4, 900)], "Separate salary and interest")
        assert plan["net_income_change_minor"] == 0
        assert list(review.store.connection.iterdump()) == before
        with pytest.raises(LedgerError):
            ExpenseCorrections(review).apply(plan)
        replacement = corrections.apply(plan)
        balances = review.store.balances(date(2026, 8, 31))
        assert balances["account:3"] == 1000 and balances["category:3"] + balances["category:4"] == -1000
        assert review.store.consumed()["source:interest"] == 1000
        assert {r["entry"]["key"]: r["active"] for r in corrections.entries()} == {original: False, replacement: True}
        assert service.apply(original_plan) == original  # Does not resurrect a superseded receipt.
        assert corrections.apply(plan) == replacement
        with pytest.raises(LedgerError, match="unchanged"):
            corrections.preview(replacement, [(3, 100), (4, 900)], "No-op")
        with pytest.raises(LedgerError, match="nonempty"):
            corrections.preview(replacement, [(4, 1000)], "")
        with pytest.raises(LedgerError, match="existing income"):
            corrections.preview(replacement, [(1, 1000)], "No expense conversion")


def test_income_tampering_stale_review_and_mapping_conflict(income_workspace):
    with ProposalReview(income_workspace[0]) as review:
        service = IncomeInterpretations(review)
        plan = service.preview("source:interest", [(3, 1000)])
        changed = json.loads(encoded(plan))
        changed["entry"]["postings"][0]["amount_minor"] = 1001
        with pytest.raises(LedgerError, match="preview changed"):
            service.apply(changed)
        changed["preview_hash"] = key({k: v for k, v in changed.items() if k != "preview_hash"})
        with pytest.raises(LedgerError, match="inputs changed"):
            service.apply(changed)
        original = service.apply(plan)
        corrections = IncomeCorrections(review)
        correction = corrections.preview(original, [(4, 1000)], "Correct category")
        review.store.review(original, reviewed=False, reason="Reconsider receipt")
        with pytest.raises(LedgerError, match="inputs changed"):
            corrections.apply(correction)
        review.store.add_account(LedgerAccount("category:4", "Wrong mapping", AccountKind.EXPENSE))
        with pytest.raises(LedgerError, match="mapping conflicts"):
            corrections.preview(original, [(4, 1000)], "Correct category")


def test_income_transaction_failure_rolls_back_schema_category_and_journal(income_workspace, monkeypatch):
    with ProposalReview(income_workspace[0]) as review:
        service = IncomeInterpretations(review)
        plan = service.preview("source:interest", [(3, 1000)])
        before = list(review.store.connection.iterdump())
        insert = review.store._insert

        def fail(*args):
            insert(*args)
            raise RuntimeError("Storage failure")

        monkeypatch.setattr(review.store, "_insert", fail)
        with pytest.raises(RuntimeError, match="Storage failure"):
            service.apply(plan)
        assert list(review.store.connection.iterdump()) == before


def test_partial_income_cannot_be_reinterpreted_or_corrected_as_whole(income_workspace):
    with ProposalReview(income_workspace[0]) as review:
        service = IncomeInterpretations(review)
        plan = service.preview("source:interest", [(3, 1000)])
        review.store.add_account(LedgerAccount("category:3", "Salary", AccountKind.INCOME))
        entry = decode_entry(encoded(plan["entry"]))
        financial, income = entry.postings
        partial = replace(
            entry,
            key="partial",
            postings=(
                replace(
                    financial, amount_minor=100, allocations=(replace(financial.allocations[0], amount_minor=100),)
                ),
                replace(income, amount_minor=-100),
            ),
        )
        review.store.post(partial)
        with pytest.raises(LedgerError, match="already allocated"):
            service.apply(plan)
        with pytest.raises(LedgerError, match="whole source"):
            IncomeCorrections(review).preview("partial", [(4, 100)], "Partial receipt")

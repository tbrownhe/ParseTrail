import json
import sqlite3
from dataclasses import replace

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_expense_corrections import ExpenseCorrections
from parsetrail.core.ledger_expense_interpretations import DEFAULT_REASON, ExpenseInterpretations
from parsetrail.core.ledger_opening_review import OpeningReview
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reviewed_reconciliation import ReviewedReconciliation
from parsetrail.core.ledger_store import decode_entry, encoded
from parsetrail.core.ledger_transfers import TransferReview

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_expense_corrections import workspace as workspace


@pytest.mark.parametrize("tid,total", [("bank_purchase", 1500), ("card_refund", 500)])
def test_rejected_proposal_split_history_atomic_post_retry_and_correction(workspace, tid, total):
    folder = workspace[0]
    with ProposalReview(folder) as review:
        OpeningReview(review, workspace[1])
        review.decide(["proposal:" + tid], "rejected", "Needs a different category split")
        service, c = ExpenseInterpretations(review), review.store.connection
        tables = (
            "SourceTransactions",
            "SourceStatements",
            "SourceMemberships",
            "CategoryDefinitions",
            "CategoryAnnotations",
            "CategoryDecisions",
            "ProposalDecisions",
            "LedgerObservations",
        )
        before = {t: c.execute(f"SELECT * FROM {t}").fetchall() for t in tables}
        dump = list(c.iterdump())
        plan = service.preview("source:" + tid, [(2, total - 100), (1, 100)], "Reviewed split")
        assert plan == service.preview("source:" + tid, [(1, 100), (2, total - 100)], "Reviewed split")
        assert list(c.iterdump()) == dump
        assert plan["proposal"]["decision"]["action"] == "rejected"
        assert plan["date_provenance"] == ("estimated" if tid.startswith("card") else "unknown")
        report = ReviewedReconciliation(review).snapshot()
        result = service.apply(plan)
        assert not ReviewedReconciliation(review).is_current(report)
        entry = decode_entry(c.execute("SELECT payload FROM LedgerEntries WHERE key=?", (result,)).fetchone()[0])
        observation = review.store.observations()["source:" + tid]
        assert entry.posting_date == observation.posting_date
        assert entry.description == tid and entry.event_id == "event:" + tid
        assert entry.reviewed and entry.reason == "Reviewed split"
        assert entry.postings[0].amount_minor == observation.amount_minor
        assert sum(p.amount_minor for p in entry.postings[1:]) == -observation.amount_minor
        assert review.store.consumed()[observation.id] == observation.amount_minor
        assert all(c.execute(f"SELECT * FROM {t}").fetchall() == before[t] for t in tables)
        assert observation.id not in {r["observation_id"] for r in service.inventory()}
        after = list(c.iterdump())
        assert service.apply(plan) == result and list(c.iterdump()) == after
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("DELETE FROM ExpenseInterpretations")
        replacement = ExpenseCorrections(review).apply(
            ExpenseCorrections(review).preview(result, [(1, total)], "Correct split")
        )
        assert review.store.entry_status(result)["superseded"]
        assert service.apply(plan) == result  # Retry does not resurrect the superseded journal.
        assert review.store.entry_status(replacement)["reviewed"]
    with ProposalReview(folder) as review:
        assert ExpenseInterpretations(review).apply(json.loads(encoded(plan))) == result


def test_unclassified_explicit_selection_uses_optional_note_and_no_schema_writes_on_preview(workspace):
    with ProposalReview(workspace[0], read_only=True) as review:
        service = ExpenseInterpretations(review)
        before = list(review.store.connection.iterdump())
        rows = service.inventory()
        assert {r["observation_id"] for r in rows} == {"source:bank_payment", "source:card_payment", "source:interest"}
        plan = service.preview("source:bank_payment", [(2, 1000)])
        assert plan["reason"] == DEFAULT_REASON and plan["proposal"] is None
        assert list(review.store.connection.iterdump()) == before
    with ProposalReview(workspace[0]) as review:
        service = ExpenseInterpretations(review)
        result = service.apply(plan)
        assert review.store.entry_status(result)["reviewed"]
        assert review.decisions() == {}


@pytest.mark.parametrize("oid", ["source:zero", "source:loan", "source:missing", "source:bank_purchase"])
def test_outside_scope_or_pending_proposal_is_not_bypassed(workspace, oid):
    with ProposalReview(workspace[0]) as review:
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError):
            ExpenseInterpretations(review).preview(oid, [(1, 1500)])
        assert list(review.store.connection.iterdump()) == before


def test_reinterpretation_of_rejected_proposal_requires_reason(workspace):
    with ProposalReview(workspace[0]) as review:
        review.decide(["proposal:bank_purchase"], "rejected", "Review category")
        with pytest.raises(LedgerError, match="nonempty"):
            ExpenseInterpretations(review).preview("source:bank_purchase", [(2, 1500)])


@pytest.mark.parametrize(
    "splits", [[], [(1, 999)], [(1, 1001)], [(1, 500), (1, 500)], [(3, 1000)], [(2, 1000.0)], [(2, -1000)]]
)
def test_invalid_expense_split_never_posts(workspace, splits):
    with ProposalReview(workspace[0]) as review:
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError):
            ExpenseInterpretations(review).preview("source:bank_payment", splits)
        assert list(review.store.connection.iterdump()) == before


def test_concurrent_transfer_consumes_evidence_and_invalidates_preview(workspace):
    with ProposalReview(workspace[0]) as first, ProposalReview(workspace[0]) as second:
        service = ExpenseInterpretations(first)
        plan = service.preview("source:bank_payment", [(2, 1000)])
        TransferReview(second).decide([("source:bank_payment", "source:card_payment")], "confirmed")
        before = list(first.store.connection.iterdump())
        with pytest.raises(LedgerError, match="already allocated"):
            service.apply(plan)
        assert list(first.store.connection.iterdump()) == before


def test_competing_interpretation_and_partial_posting_block_duplicates(workspace):
    with ProposalReview(workspace[0]) as review:
        service = ExpenseInterpretations(review)
        one = service.preview("source:bank_payment", [(2, 1000)])
        two = service.preview("source:bank_payment", [(1, 1000)])
        service.apply(one)
        with pytest.raises(LedgerError, match="already has"):
            service.apply(two)
        review.decide(["proposal:bank_purchase"], "rejected", "Different accounting")
        plan = service.preview("source:bank_purchase", [(2, 1500)], "Reviewed split")
        draft = decode_entry(review.proposals["proposal:bank_purchase"])
        financial, expense = draft.postings
        partial = replace(
            draft,
            key="partial",
            postings=(
                replace(
                    financial, amount_minor=-100, allocations=(replace(financial.allocations[0], amount_minor=-100),)
                ),
                replace(expense, amount_minor=100),
            ),
        )
        review.store.post(partial)
        with pytest.raises(LedgerError, match="already allocated"):
            service.apply(plan)


def test_tampered_preview_and_failed_post_roll_back_schema_and_category_mapping(workspace, monkeypatch):
    with ProposalReview(workspace[0]) as review:
        service, c = ExpenseInterpretations(review), review.store.connection
        plan = service.preview("source:bank_payment", [(2, 1000)])
        tampered = json.loads(encoded(plan))
        tampered["entry"]["description"] = "Changed evidence"
        with pytest.raises(LedgerError, match="preview changed"):
            service.apply(tampered)
        tampered["preview_hash"] = key({k: v for k, v in tampered.items() if k != "preview_hash"})
        with pytest.raises(LedgerError, match="inputs changed"):
            service.apply(tampered)
        before = list(c.iterdump())
        insert = review.store._insert

        def fail_after_insert(*args):
            insert(*args)
            raise RuntimeError("Simulated storage failure")

        monkeypatch.setattr(review.store, "_insert", fail_after_insert)
        with pytest.raises(RuntimeError, match="storage failure"):
            service.apply(plan)
        assert list(c.iterdump()) == before

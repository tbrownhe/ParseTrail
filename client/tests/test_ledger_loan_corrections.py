import sqlite3
from datetime import date

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_categories import LOAN_INTEREST
from parsetrail.core.ledger_loan_corrections import LoanPaymentCorrections
from parsetrail.core.ledger_loan_payments import LoanPayments
from parsetrail.core.ledger_opening_review import OpeningReview
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reviewed_reconciliation import ReviewedReconciliation
from parsetrail.core.ledger_store import decode_entry, encoded
from parsetrail.core.ledger_transfers import TransferReview

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_loan_payments import loan_rebuild as loan_rebuild
from .test_ledger_reviewed_reconciliation import prepare_custom


@pytest.fixture
def correction_rebuild(loan_rebuild):
    e = loan_rebuild["evidence"]
    e["transactions"]["bank_other"] = {
        **e["transactions"]["bank_payment"],
        "id": "bank_other",
        "AccountID": 3,
        "PostingDate": "2026-08-22",
    }
    e["statements"]["s3"]["closing_minor"] -= 1000
    e["memberships"].append({"statement_id": "s3", "transaction_id": "bank_other", "source": "bank", "row": 9})
    return loan_rebuild


@pytest.fixture
def correction_workspace(tmp_path, correction_rebuild):
    return prepare_custom(tmp_path, correction_rebuild)


def post_original(review):
    payments = LoanPayments(review)
    plan = payments.preview("source:bank_payment", "loan")
    payments.apply(plan)
    return plan


def correction(service, oid="source:bank_other"):
    return service.preview("loan", oid, "Selected the wrong bank movement")


def test_atomic_bundle_correction_history_reopen_and_second_correction(correction_workspace):
    with ProposalReview(correction_workspace[0]) as review:
        original = post_original(review)
        OpeningReview(review, correction_workspace[1])
        reconciliation = ReviewedReconciliation(review)
        before_report = reconciliation.snapshot()
        c, service = review.store.connection, LoanPaymentCorrections(review)
        before = list(c.iterdump())
        assert [p["outgoing_id"] for p in service.candidates("loan") if not p["blockers"]] == ["source:bank_other"]
        plan = correction(service)
        assert list(c.iterdump()) == before
        assert len(plan["previous"]["entries"]) == 2 and len(plan["replacement"]["entries"]) == 3
        tables = (
            "SourceTransactions",
            "SourceStatements",
            "SourceMemberships",
            "CategoryAnnotations",
            "LoanPaymentDecisions",
        )
        evidence = {t: c.execute(f"SELECT * FROM {t}").fetchall() for t in tables}
        result = service.apply(plan)
        balances = review.store.balances(date.max)
        assert balances["account:1"] == 0 and balances["account:3"] == -1000
        assert balances["account:4"] == 900 and balances[LOAN_INTEREST.id] == 100
        assert "source:bank_payment" not in review.store.consumed()
        assert review.store.evidence_remaining()["source:bank_payment"] == -1000
        assert all(review.store.entry_status(e["key"])["superseded"] for e in original["entries"])
        assert all(not review.store.entry_status(e)["superseded"] for e in result)
        assert not reconciliation.is_current(before_report)
        assert reconciliation.snapshot()["remaining_observations"]["source:bank_payment"] == -1000
        assert all(c.execute(f"SELECT * FROM {t}").fetchall() == evidence[t] for t in tables)
        after = list(c.iterdump())
        assert service.apply(plan) == result and list(c.iterdump()) == after
        for table in ("LoanPaymentCorrections", "LedgerBundleCorrections", "LedgerBundleOriginals"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                c.execute(f"DELETE FROM {table}")
    with ProposalReview(correction_workspace[0]) as review:
        service = LoanPaymentCorrections(review)
        assert service.histories()["loan"] == [original, plan["replacement"]]
        back = correction(service, "source:bank_payment")
        service.apply(back)
        assert len(service.histories()["loan"]) == 3
        balances = review.store.balances(date.max)
        assert balances["account:1"] == -1000 and balances["account:3"] == 0
        assert balances[LOAN_INTEREST.id] == 100 and balances["account:4"] == 900
        assert service.apply(plan) == result  # Retrying old correction does not reactivate it.
        assert service.histories()["loan"][-1] == back["replacement"]
        assert not review.store.connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize(
    "old_date,new_date,interest",
    [
        ("2026-08-31", "2026-09-02", -100),
        ("2026-09-02", "2026-08-31", -100),
        ("2026-08-31", "2026-09-02", 0),
        ("2026-09-02", "2026-08-31", 0),
    ],
)
def test_different_journal_counts_and_cross_month_balances(tmp_path, correction_rebuild, old_date, new_date, interest):
    e = correction_rebuild["evidence"]
    e["transactions"]["bank_payment"]["PostingDate"] = old_date
    e["transactions"]["bank_other"]["PostingDate"] = new_date
    e["transactions"]["loan"]["PostingDate"] = e["transactions"]["loan_interest"]["PostingDate"] = "2026-08-31"
    e["transactions"]["loan_interest"]["AmountMinor"] = interest
    e["statements"]["s4"]["closing_minor"] = -4000 + interest
    for sid in ("s1", "s3", "s4"):
        e["statements"][sid]["end"] = "2026-09-30"
    with ProposalReview(prepare_custom(tmp_path, correction_rebuild)[0]) as review:
        original = post_original(review)
        service = LoanPaymentCorrections(review)
        plan = correction(service)
        assert len(original["entries"]) != len(plan["replacement"]["entries"])
        service.apply(plan)
        interim, final = review.store.balances(date(2026, 8, 31)), review.store.balances(date.max)
        assert interim["account:1"] == 0 and final["account:1"] == 0
        assert interim["account:3"] == (-1000 if new_date == "2026-08-31" else 0)
        assert final["account:3"] == -1000 and final["account:4"] == 1000 + interest
        assert final.get(LOAN_INTEREST.id, 0) == -interest
        assert all(final[a.id] == 0 for a in review.store.accounts().values() if a.purpose == "clearing")


@pytest.mark.parametrize("problem", ["same", "reason", "allocated", "tampered", "stale", "partial"])
def test_correction_refusal_is_read_only(correction_workspace, problem):
    with ProposalReview(correction_workspace[0]) as review:
        original = post_original(review)
        service = LoanPaymentCorrections(review)
        if problem == "same":

            def attempt():
                return correction(service, "source:bank_payment")
        elif problem == "reason":

            def attempt():
                return service.preview("loan", "source:bank_other", "  ")
        elif problem == "partial":
            replacements = [decode_entry(encoded(e)) for e in correction(service)["replacement"]["entries"]]

            def attempt():
                with review.store._transaction():
                    review.store._correct_bundle(
                        "partial",
                        [original["entries"][0]["key"]],
                        replacements,
                        reason="Selected the wrong bank movement",
                    )
        else:
            plan = correction(service)
            if problem == "allocated":
                TransferReview(review).decide([("source:bank_other", "source:card_payment")], "confirmed")
            elif problem == "stale":
                other = service.preview("loan", "source:bank_other", "Different reason")
                service.apply(other)
            else:
                plan["replacement"]["entries"][-1]["postings"][-1]["account_id"] = "category:1"
                plan["preview_hash"] = key({k: v for k, v in plan.items() if k != "preview_hash"})

            def attempt():
                return service.apply(plan)

        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError):
            attempt()
        assert list(review.store.connection.iterdump()) == before


def test_failed_replacement_rolls_back_reversals_release_schema_and_clearing(correction_workspace, monkeypatch):
    with ProposalReview(correction_workspace[0]) as review:
        post_original(review)
        service = LoanPaymentCorrections(review)
        plan = correction(service)
        before = list(review.store.connection.iterdump())
        insert = review.store._insert

        def fail(entry, usage):
            if entry.key == plan["replacement"]["entries"][-1]["key"]:
                raise LedgerError("Injected replacement failure")
            insert(entry, usage)

        monkeypatch.setattr(review.store, "_insert", fail)
        with pytest.raises(LedgerError, match="Injected"):
            service.apply(plan)
        assert list(review.store.connection.iterdump()) == before


def test_pending_expense_rejected_before_rematch(tmp_path, correction_rebuild):
    annotation = correction_rebuild["annotations"]["decisions"][0]
    correction_rebuild["annotations"]["decisions"].append(
        {**annotation, "legacy_id": 99, "transaction_id": "bank_other", "account_id": 3, "amount_minor": -1000}
    )
    with ProposalReview(prepare_custom(tmp_path, correction_rebuild)[0]) as review:
        post_original(review)
        service = LoanPaymentCorrections(review)
        with pytest.raises(LedgerError, match="Reject"):
            correction(service)
        review.decide(["proposal:bank_other"], "rejected", "This is a loan payment")
        service.apply(correction(service))


def test_single_entry_correction_cannot_recorrect_bundle_original(correction_workspace):
    with ProposalReview(correction_workspace[0]) as review:
        original = post_original(review)
        service = LoanPaymentCorrections(review)
        plan = correction(service)
        service.apply(plan)
        replacement = decode_entry(encoded(plan["replacement"]["entries"][0]))
        with pytest.raises(LedgerError, match="already"):
            review.store.correct(original["entries"][0]["key"], replacement, reason="Another correction")

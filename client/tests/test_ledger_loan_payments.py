import json
import sqlite3
from datetime import date

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_loan_payments import LoanPayments
from parsetrail.core.ledger_opening_review import OpeningReview
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reviewed_reconciliation import ReviewedReconciliation
from parsetrail.core.ledger_store import encoded
from parsetrail.core.ledger_transfers import TransferReview

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_reviewed_reconciliation import prepare_custom


@pytest.fixture
def loan_rebuild(rebuild):
    e = rebuild["evidence"]
    e["files"]["loan"] = {"plugin": "pdf_capitaloneauto_202402", "version": "0.2.1", "status": "parsed"}
    e["transactions"]["loan"].update(Description="Payment Received", AmountMinor=1000)
    e["transactions"]["loan_interest"] = {
        **e["transactions"]["loan"],
        "id": "loan_interest",
        "Description": "Interest Fee",
        "AmountMinor": -100,
    }
    e["statements"]["s4"].update(source="loan", opening_minor=-5000, closing_minor=-4100)
    for m in e["memberships"]:
        if m["statement_id"] == "s4":
            m["source"] = "loan"
    e["memberships"].append({"statement_id": "s4", "transaction_id": "loan_interest", "source": "loan", "row": 2})
    rebuild["annotations"]["decisions"] = [
        a for a in rebuild["annotations"]["decisions"] if a["transaction_id"] != "loan"
    ]
    rebuild["legacy_metadata"]["Categories"].append(
        {"CategoryID": 2, "Name": "Loan interest", "Type": "Expense", "ParentID": None}
    )
    return rebuild


@pytest.fixture
def loan_workspace(tmp_path, loan_rebuild):
    return prepare_custom(tmp_path, loan_rebuild)[0]


def preview(service, category=2):
    return service.preview("source:bank_payment", "loan", category)


def test_payment_interest_atomic_exact_retry_reopen_and_evidence(loan_workspace):
    with ProposalReview(loan_workspace) as review:
        service, c = LoanPayments(review), review.store.connection
        before = list(c.iterdump())
        pair = service.snapshot()["pairs"][0]
        assert not pair["blockers"] and pair["interest_minor"] == 100
        plan = preview(service)
        assert list(c.iterdump()) == before
        assert plan["principal_reduction_minor"] == 900
        assert len(plan["entries"]) == 2
        assert len({e["event_id"] for e in plan["entries"]}) == 1
        assert set(plan["date_provenance"]) == {"unknown"}
        tables = ("SourceTransactions", "SourceStatements", "SourceMemberships", "CategoryAnnotations")
        evidence = {t: c.execute(f"SELECT * FROM {t}").fetchall() for t in tables}
        keys = service.apply(plan)
        balances = review.store.balances(date(2026, 8, 31))
        assert balances["account:1"] == -1000
        assert balances["account:4"] == 900
        assert balances["category:2"] == 100
        assert review.store.consumed() == {
            "source:bank_payment": -1000,
            "source:loan": 1000,
            "source:loan_interest": -100,
        }
        assert all(c.execute(f"SELECT * FROM {t}").fetchall() == evidence[t] for t in tables)
        after = list(c.iterdump())
        assert service.apply(plan) == keys and list(c.iterdump()) == after
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("DELETE FROM LoanPaymentDecisions")
    with ProposalReview(loan_workspace, read_only=True) as review:
        service = LoanPayments(review)
        assert service.decisions()["loan"] == plan
        assert service.snapshot()["pairs"][0]["blockers"]


@pytest.mark.parametrize("bank_date,loan_date", [("2026-08-31", "2026-09-02"), ("2026-09-02", "2026-08-31")])
def test_cross_month_dates_clear_without_duplicate_expense(tmp_path, loan_rebuild, bank_date, loan_date):
    e = loan_rebuild["evidence"]
    e["transactions"]["bank_payment"]["PostingDate"] = bank_date
    for tid in ("loan", "loan_interest"):
        e["transactions"][tid]["PostingDate"] = loan_date
    for sid in ("s1", "s4"):
        e["statements"][sid]["end"] = "2026-09-30"
    folder = prepare_custom(tmp_path, loan_rebuild)[0]
    with ProposalReview(folder) as review:
        service = LoanPayments(review)
        plan = preview(service)
        assert len(plan["entries"]) == 3
        service.apply(plan)
        interim = review.store.balances(date(2026, 8, 31))
        final = review.store.balances(date(2026, 9, 30))
        clearing = next(a["id"] for a in plan["accounts"] if a["purpose"] == "clearing")
        assert abs(interim[clearing]) == 1000 and final[clearing] == 0
        assert final["account:1"] == -1000 and final["account:4"] == 900 and final["category:2"] == 100
        assert interim.get("category:2", 0) == (100 if loan_date < bank_date else 0)


@pytest.mark.parametrize("problem", ["version", "balance", "date", "status", "parser"])
def test_unreviewed_source_contracts_not_admitted(tmp_path, loan_rebuild, problem):
    e = loan_rebuild["evidence"]
    if problem == "version":
        e["files"]["loan"]["version"] = "0.2.0"
    elif problem == "balance":
        e["statements"]["s4"]["closing_minor"] += 1
    elif problem == "date":
        e["transactions"]["loan"]["PostingDate"] = "2026-09-01"
    elif problem == "status":
        e["files"]["loan"]["status"] = "review_pending"
    else:
        e["files"]["loan"]["plugin"] = "pdf_wfloanper_202306"
    with ProposalReview(prepare_custom(tmp_path, loan_rebuild)[0]) as review:
        assert not LoanPayments(review).snapshot()["pairs"]
        with pytest.raises(LedgerError, match="eligible"):
            preview(LoanPayments(review))


@pytest.mark.parametrize("problem", ["missing", "multiple", "shared", "positive", "excess"])
def test_uncertain_interest_components_block(tmp_path, loan_rebuild, problem):
    e = loan_rebuild["evidence"]
    interest = e["transactions"]["loan_interest"]
    if problem == "missing":
        interest["Description"] = "Unrecognized component"
    elif problem in ("multiple", "shared"):
        row = interest if problem == "multiple" else e["transactions"]["loan"]
        e["transactions"]["second"] = {**row, "id": "second"}
        e["memberships"].append({"statement_id": "s4", "transaction_id": "second", "source": "loan", "row": 3})
    else:
        interest["AmountMinor"] = 100 if problem == "positive" else -1001
    e["statements"]["s4"]["closing_minor"] = -5000 + sum(
        t["AmountMinor"] for t in e["transactions"].values() if t["AccountID"] == 4
    )
    with ProposalReview(prepare_custom(tmp_path, loan_rebuild)[0]) as review:
        assert LoanPayments(review).snapshot()["pairs"][0]["blockers"]
        with pytest.raises(LedgerError, match="Interest"):
            preview(LoanPayments(review))


def test_explicit_zero_interest_no_fake_posting(tmp_path, loan_rebuild):
    loan_rebuild["evidence"]["transactions"]["loan_interest"]["AmountMinor"] = 0
    loan_rebuild["evidence"]["statements"]["s4"]["closing_minor"] = -4000
    with ProposalReview(prepare_custom(tmp_path, loan_rebuild)[0]) as review:
        service = LoanPayments(review)
        with pytest.raises(LedgerError, match="zero interest"):
            preview(service)
        plan = preview(service, None)
        assert len(plan["entries"]) == 1
        service.apply(plan)
        assert "source:loan_interest" not in review.store.observations()


@pytest.mark.parametrize("category", [None, True, 999, 2.0])
def test_interest_requires_real_expense_category(loan_workspace, category):
    with ProposalReview(loan_workspace) as review:
        with pytest.raises(LedgerError):
            preview(LoanPayments(review), category)


def test_pending_expense_requires_rejection(tmp_path, loan_rebuild):
    original = loan_rebuild["annotations"]["decisions"][0]
    loan_rebuild["annotations"]["decisions"].append(
        {**original, "legacy_id": 99, "transaction_id": "bank_payment", "amount_minor": -1000}
    )
    with ProposalReview(prepare_custom(tmp_path, loan_rebuild)[0]) as review:
        service = LoanPayments(review)
        assert "Reject" in service.snapshot()["pairs"][0]["blockers"][0]
        with pytest.raises(LedgerError, match="Reject"):
            preview(service)
        review.decide(["proposal:bank_payment"], "rejected", "Payment is a transfer")
        service.apply(preview(service))
        assert review.store.balances(date(2026, 8, 31))["category:2"] == 100


def test_stale_preview_and_tampering_refused(loan_workspace):
    with ProposalReview(loan_workspace) as review:
        service = LoanPayments(review)
        plan = preview(service)
        changed = json.loads(encoded(plan))
        changed["entries"][0]["description"] = "changed"
        changed["preview_hash"] = key({k: v for k, v in changed.items() if k != "preview_hash"})
        with pytest.raises(LedgerError, match="changed since preview"):
            service.apply(changed)
        TransferReview(review).decide([("source:bank_payment", "source:card_payment")], "confirmed")
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError, match="allocated"):
            service.apply(plan)
        assert list(review.store.connection.iterdump()) == before


def test_failure_rolls_back_observations_accounts_schema_and_payment(loan_workspace, monkeypatch):
    with ProposalReview(loan_workspace) as review:
        service, c = LoanPayments(review), review.store.connection
        plan = preview(service)
        before = list(c.iterdump())
        original = review.store._insert

        def fail_on_interest(entry, usage):
            if entry.key.endswith(":interest"):
                raise LedgerError("injected failure")
            original(entry, usage)

        monkeypatch.setattr(review.store, "_insert", fail_on_interest)
        with pytest.raises(LedgerError, match="injected"):
            service.apply(plan)
        assert list(c.iterdump()) == before


def test_payment_updates_cash_reconciliation_without_certifying_loans(tmp_path, loan_rebuild):
    folder, readiness = prepare_custom(tmp_path, loan_rebuild)
    with ProposalReview(folder) as review:
        OpeningReview(review, readiness)
        reconciliation = ReviewedReconciliation(review)
        before = reconciliation.snapshot()
        service = LoanPayments(review)
        service.apply(preview(service))
        assert not reconciliation.is_current(before)
        after = reconciliation.snapshot()
        assert after["outside_scope_statement_ids"] == ["s4"]
        assert not after["ready_for_cutover"]
        assert all(d["transaction_id"] not in ("loan", "loan_interest") for d in after["unmapped_movements"])
        bank = next(s for s in after["statements"] if s["statement_id"] == "s1")
        assert "source:bank_payment" not in bank["unresolved_observations"]
        assert not bank["reconciled"]  # Opening, dates and other activity still need review.


def test_overlapping_sources_do_not_duplicate_interest(tmp_path, loan_rebuild):
    e = loan_rebuild["evidence"]
    e["statements"]["overlap"] = {**e["statements"]["s4"], "id": "overlap"}
    e["memberships"] += [{**m, "statement_id": "overlap"} for m in list(e["memberships"]) if m["statement_id"] == "s4"]
    with ProposalReview(prepare_custom(tmp_path, loan_rebuild)[0]) as review:
        service = LoanPayments(review)
        assert len(service.snapshot()["pairs"]) == 1
        plan = preview(service)
        assert len(plan["source_basis"]["sources"]) == 2
        service.apply(plan)
        assert review.store.balances(date(2026, 8, 31))["category:2"] == 100


def test_multiple_bank_matches_require_choice_and_consume_once(tmp_path, loan_rebuild):
    e = loan_rebuild["evidence"]
    e["transactions"]["bank_other"] = {**e["transactions"]["bank_payment"], "id": "bank_other"}
    e["statements"]["s1"]["closing_minor"] -= 1000
    e["memberships"].append({"statement_id": "s1", "transaction_id": "bank_other", "source": "bank", "row": 99})
    with ProposalReview(prepare_custom(tmp_path, loan_rebuild)[0]) as review:
        service = LoanPayments(review)
        pairs = service.snapshot()["pairs"]
        assert len(pairs) == 2 and all(p["alternatives"] == [1, 2] for p in pairs)
        assert not review.store.consumed()
        service.apply(preview(service))
        assert "source:bank_other" not in review.store.consumed()
        with pytest.raises(LedgerError, match="already confirmed"):
            service.preview("source:bank_other", "loan", 2)

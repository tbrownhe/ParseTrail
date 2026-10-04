from datetime import date

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_categories import LOAN_INTEREST
from parsetrail.core.ledger_loan_corrections import LoanPaymentCorrections
from parsetrail.core.ledger_loan_payments import WF_RULE, LoanPayments
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.gui.ledger_loan_payments import LoanPaymentDialog, LoanPaymentWindow

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_loan_corrections import correction_rebuild as correction_rebuild
from .test_ledger_loan_payments import loan_rebuild as loan_rebuild
from .test_ledger_proposal_review import app as app
from .test_ledger_reviewed_reconciliation import prepare_custom


@pytest.fixture
def wf_rebuild(correction_rebuild):
    e = correction_rebuild["evidence"]
    e["files"]["loan"].update(plugin="pdf_wfloanper_202306", version="0.2.0")
    e["transactions"]["loan"]["Description"] = "PAYMENT"
    e["transactions"]["loan_interest"]["Description"] = "INTEREST PAYMENT"
    return correction_rebuild


def add_row(e, tid, amount, description, posting_date="2026-08-21"):
    e["transactions"][tid] = {
        **e["transactions"]["loan"],
        "id": tid,
        "AmountMinor": amount,
        "Description": description,
        "PostingDate": posting_date,
    }
    e["memberships"].append(
        {"statement_id": "s4", "transaction_id": tid, "source": "loan", "row": len(e["memberships"])}
    )
    e["statements"]["s4"]["closing_minor"] += amount


@pytest.mark.parametrize("interest", [-100, 0])
def test_wf_ordinary_payment_interest_and_correction_preserve_evidence(tmp_path, wf_rebuild, interest):
    e = wf_rebuild["evidence"]
    e["transactions"]["loan_interest"]["AmountMinor"] = interest
    e["statements"]["s4"]["closing_minor"] = -4000 + interest
    add_row(e, "extra_principal", 200, "PRINCIPAL PAYMENT")
    folder = prepare_custom(tmp_path, wf_rebuild)[0]
    with ProposalReview(folder) as review:
        service, c = LoanPayments(review), review.store.connection
        tables = ("SourceTransactions", "SourceMemberships", "SourceStatements", "CategoryAnnotations")
        evidence = {t: c.execute(f"SELECT * FROM {t}").fetchall() for t in tables}
        snapshot = service.snapshot()
        assert snapshot["components"].keys() == {"loan"}
        assert all(p["source_contract"]["name"] == "Wells Fargo Personal Loan" for p in snapshot["pairs"])
        before = list(c.iterdump())
        plan = service.preview("source:bank_payment", "loan")
        assert plan["rule"] == WF_RULE and set(plan["date_provenance"]) == {"unknown"}
        assert list(c.iterdump()) == before
        service.apply(plan)
        assert (
            review.store.balances(date.max)[LOAN_INTEREST.id] == -interest
            if interest
            else LOAN_INTEREST.id not in review.store.accounts()
        )
        assert "source:extra_principal" not in review.store.observations()
        corrections = LoanPaymentCorrections(review)
        correction = corrections.preview("loan", "source:bank_other", "Correct funding movement")
        corrections.apply(correction)
        assert review.store.balances(date.max)["account:1"] == 0
        assert review.store.balances(date.max)["account:3"] == -1000
        assert review.store.balances(date.max)["account:4"] == 1000 + interest
        assert all(c.execute(f"SELECT * FROM {t}").fetchall() == evidence[t] for t in tables)
    with ProposalReview(folder, read_only=True) as review:
        assert LoanPaymentCorrections(review).histories()["loan"][-1] == correction["replacement"]


@pytest.mark.parametrize(
    "problem",
    ["synthetic", "version", "balance", "date", "currency", "missing_interest", "shared_interest", "mixed_contracts"],
)
def test_wf_unsupported_or_ambiguous_evidence_stays_unposted(tmp_path, wf_rebuild, problem):
    e = wf_rebuild["evidence"]
    if problem == "synthetic":
        add_row(e, "synthetic", -5000, "LOAN ORIGINATION")
    elif problem == "version":
        e["files"]["loan"]["version"] = "unknown"
    elif problem == "balance":
        e["statements"]["s4"]["closing_minor"] += 1
    elif problem == "date":
        e["transactions"]["loan"]["PostingDate"] = "2026-09-01"
    elif problem == "currency":
        for t in e["transactions"].values():
            if t["AccountID"] == 4:
                t["CurrencyCode"] = "EUR"
    elif problem == "missing_interest":
        e["transactions"]["loan_interest"]["Description"] = "Unrecognized interest"
    elif problem == "shared_interest":
        add_row(e, "second_payment", 1000, "PAYMENT", "2026-08-20")
    else:
        e["files"]["different"] = {"plugin": "pdf_capitaloneauto_202402", "version": "0.2.1", "status": "parsed"}
        e["statements"]["overlap"] = {**e["statements"]["s4"], "id": "overlap", "source": "different"}
        e["memberships"] += [
            {**m, "statement_id": "overlap", "source": "different"}
            for m in list(e["memberships"])
            if m["statement_id"] == "s4"
        ]
    with ProposalReview(prepare_custom(tmp_path, wf_rebuild)[0]) as review:
        before = list(review.store.connection.iterdump())
        service = LoanPayments(review)
        assert all(p["blockers"] for p in service.snapshot()["pairs"])
        with pytest.raises(LedgerError):
            service.preview("source:bank_payment", "loan")
        assert list(review.store.connection.iterdump()) == before


@pytest.mark.usefixtures("app")
def test_wf_ui_discloses_ordinary_balances_assumed_period_and_fixed_interest(tmp_path, wf_rebuild):
    folder = prepare_custom(tmp_path, wf_rebuild)[0]
    with ProposalReview(folder) as review:
        window = LoanPaymentWindow(review)
        window.page.table.selectRow(0)
        assert "assumes a 31-day" in window.page.details.toPlainText()
        assert "Printed prior/ending principal" in window.page.details.toPlainText()
        assert "synthetic origination stay outside" in window.page.details.toPlainText()
        pair = window.selected()["pair"]
        dialog = LoanPaymentDialog(window.service, pair, 7)
        assert "Loan interest" in dialog.category.text()
        dialog.preview.click()
        assert dialog.apply.isEnabled() and dialog.plan["rule"] == WF_RULE
        dialog.confirm = lambda: True
        dialog.apply.click()
        window.tabs.setCurrentIndex(1)
        window.confirmed.table.selectRow(0)
        assert window.correct.isEnabled()
        assert "assumes a 31-day" in window.confirmed.details.toPlainText()
        window.close()

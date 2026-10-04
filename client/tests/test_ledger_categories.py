import json
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import date

import pytest
from parsetrail.core.ledger import AccountKind, LedgerError
from parsetrail.core.ledger_categories import BUILTIN_CATEGORIES, LOAN_INTEREST, LOAN_INTEREST_KEY, category_accounts
from parsetrail.core.ledger_expense_corrections import ExpenseCorrections, expense_split
from parsetrail.core.ledger_expense_interpretations import ExpenseInterpretations
from parsetrail.core.ledger_loan_payments import LoanPayments
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_store import encoded
from parsetrail.gui.ledger_expense_corrections import ExpenseCorrectionDialog
from parsetrail.gui.ledger_expense_interpretations import ExpenseInterpretationDialog

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_loan_payments import loan_rebuild as loan_rebuild
from .test_ledger_loan_payments import loan_workspace as loan_workspace
from .test_ledger_proposal_review import app as app
from .test_ledger_reviewed_reconciliation import prepare_custom


def test_builtin_catalog_is_fixed_and_independent_of_same_named_custom_categories(tmp_path, loan_rebuild):
    loan_rebuild["legacy_metadata"]["Categories"] += [
        {"CategoryID": 3, "Name": "Loan interest", "Type": "Income", "ParentID": None},
        {"CategoryID": 4, "Name": "Custom hobby", "Type": "Expense", "ParentID": None},
    ]
    with ProposalReview(prepare_custom(tmp_path, loan_rebuild)[0]) as review:
        before = list(review.store.connection.iterdump())
        catalog = category_accounts(review.store)
        assert catalog[LOAN_INTEREST_KEY] == LOAN_INTEREST
        assert catalog[2].name == catalog[3].name == LOAN_INTEREST.name
        assert len({catalog[2].id, catalog[3].id, LOAN_INTEREST.id}) == 3
        assert catalog[3].kind == AccountKind.INCOME
        assert catalog[4].name == "Custom hobby"
        assert LOAN_INTEREST_KEY not in category_accounts(review.store, kind=AccountKind.INCOME)
        catalog.clear()
        assert category_accounts(review.store)[LOAN_INTEREST_KEY] == LOAN_INTEREST
        with pytest.raises(TypeError):
            BUILTIN_CATEGORIES["user"] = LOAN_INTEREST
        with pytest.raises(FrozenInstanceError):
            LOAN_INTEREST.name = "Groceries"
        assert list(review.store.connection.iterdump()) == before


@pytest.mark.parametrize("problem", ["unknown", "wrong_type", "duplicate", "bool"])
def test_category_identity_and_type_are_enforced(loan_workspace, problem):
    with ProposalReview(loan_workspace) as review:
        store = review.store
        splits = [(LOAN_INTEREST_KEY, 1000)]
        kind = AccountKind.EXPENSE
        if problem == "unknown":
            splits = [("builtin:groceries", 1000)]
        elif problem == "wrong_type":
            kind = AccountKind.INCOME
        elif problem == "duplicate":
            splits = [(LOAN_INTEREST_KEY, 500), (LOAN_INTEREST_KEY, 500)]
        else:
            splits = [(True, 1000)]
        with pytest.raises(LedgerError):
            expense_split(store, store.accounts(), store.observations()["source:bank_payment"], splits, kind=kind)


@pytest.mark.usefixtures("app")
def test_mixed_builtin_custom_splits_post_correct_and_preselect_on_reopen(loan_workspace):
    with ProposalReview(loan_workspace) as review:
        service = ExpenseInterpretations(review)
        record = next(r for r in service.inventory() if r["observation_id"] == "source:bank_payment")
        dialog = ExpenseInterpretationDialog(service, record)
        combo = dialog.table.cellWidget(0, 0)
        assert combo.itemText(combo.findData(LOAN_INTEREST_KEY)) == "Loan interest (built-in)"
        assert combo.findData(1) >= 0
        dialog.close()
        plan = service.preview(record["observation_id"], [(LOAN_INTEREST_KEY, 100), (1, 900)])
        assert plan == service.preview(record["observation_id"], [(1, 900), (LOAN_INTEREST_KEY, 100)])
        original = service.apply(plan)
        corrections = ExpenseCorrections(review)
        correction = corrections.preview(original, [(LOAN_INTEREST_KEY, 200), (1, 800)], "Adjust the split")
        replacement = corrections.apply(correction)
        assert review.store.balances(date.max)[LOAN_INTEREST.id] == 200
        assert review.store.balances(date.max)["category:1"] == 800
    with ProposalReview(loan_workspace) as review:
        service = ExpenseCorrections(review)
        record = next(r for r in service.entries() if r["entry"]["key"] == replacement)
        dialog = ExpenseCorrectionDialog(service, record)
        ids = {dialog.table.cellWidget(i, 0).currentData() for i in range(dialog.table.rowCount())}
        assert ids == {1, LOAN_INTEREST_KEY}
        dialog.close()


@pytest.mark.parametrize("problem", ["name", "type"])
def test_loan_workflow_refuses_conflicting_builtin_mapping(loan_workspace, problem):
    with ProposalReview(loan_workspace) as review:
        account = replace(
            LOAN_INTEREST, **({"name": "Groceries"} if problem == "name" else {"kind": AccountKind.INCOME})
        )
        c = review.store.connection
        c.execute("INSERT INTO LedgerAccounts VALUES(?,?,?)", (account.id, None, encoded(asdict(account))))
        before = list(c.iterdump())
        with pytest.raises(LedgerError, match="Fixed loan interest"):
            LoanPayments(review).preview("source:bank_payment", "loan")
        assert list(c.iterdump()) == before


@pytest.mark.parametrize("problem", ["account", "old_rule"])
def test_modified_loan_preview_cannot_override_fixed_category(loan_workspace, problem):
    with ProposalReview(loan_workspace) as review:
        service = LoanPayments(review)
        plan = service.preview("source:bank_payment", "loan")
        forged = json.loads(encoded(plan))
        if problem == "account":
            forged["interest_account_id"] = "category:1"
            forged["accounts"] = []
            forged["entries"][-1]["postings"][-1]["account_id"] = "category:1"
        else:
            forged["rule"] = "capital-one-loan-payments-1"
        forged["preview_hash"] = key({k: v for k, v in forged.items() if k != "preview_hash"})
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError, match="changed"):
            service.apply(forged)
        assert list(review.store.connection.iterdump()) == before
        keys = service.apply(plan)
        assert service.apply(plan) == keys
        assert not ExpenseCorrections(review).entries()  # Loan components cannot use ordinary recategorization.

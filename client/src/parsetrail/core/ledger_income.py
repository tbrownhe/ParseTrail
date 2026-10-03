"""Explicit positive cash-receipt income, limited to the amount actually deposited."""

from parsetrail.core.ledger import AccountKind, LedgerError
from parsetrail.core.ledger_expense_corrections import ExpenseCorrections
from parsetrail.core.ledger_expense_interpretations import ExpenseInterpretations


class IncomeInterpretations(ExpenseInterpretations):
    """An explicit choice, never an inference that a deposit is income.

    Only positive checking/savings evidence is admitted. No gross pay, withholdings,
    negative income adjustments, card credits, transfer or loan treatment is inferred.
    """

    category_kind = AccountKind.INCOME
    rule = "income-interpretation-1"
    default_reason = "Explicitly classified as income received in cash"
    history_table = "IncomeInterpretations"
    key_prefix = "income-interpretation:"

    def __init__(self, review):
        super().__init__(review)
        cash_accounts = {
            a["id"]
            for a in review.plan["accounts"]
            if a["source_account_id"] is not None and a["kind"] == AccountKind.ASSET
        }
        self.scope = {
            oid: o for oid, o in self.scope.items() if o["account_id"] in cash_accounts and o["amount_minor"] > 0
        }

    def _build(self, observation_id, splits, reason):
        if observation_id not in self.scope:
            raise LedgerError("Income requires a positive, eligible checking/savings receipt.")
        return super()._build(observation_id, splits, reason)


class IncomeCorrections(ExpenseCorrections):
    """Category-only corrections of positive cash income; preserve its net receipt."""

    category_kind = AccountKind.INCOME
    rule = "income-correction-1"
    key_prefix = "income-correction:"

    @classmethod
    def _movement(cls, original, accounts, observations, scoped):
        movement, counterparts = super()._movement(original, accounts, observations, scoped)
        if movement.amount_minor <= 0 or accounts[movement.account_id].kind != AccountKind.ASSET:
            raise LedgerError("Income correction requires a positive checking/savings receipt.")
        return movement, counterparts

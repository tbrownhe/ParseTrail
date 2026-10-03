# Explicit cash income receipts

`IncomeInterpretations` admits positive, wholly unallocated checking/savings observations
from the verified cash/card candidate plan. An explicit income classification and existing
income category are required; a deposit's presence in the inventory does not mean it is
income. Transfers, loan proceeds and expense refunds need their own accounting treatment.
Card credits, cash outflows, zero amounts, source exceptions and other financial account
types are excluded. Negative income adjustments remain a separate scope.

The journal debits the financial account by the receipt and credits the selected income
categories by that exact amount. Positive category splits must total the whole deposit.
This records the amount actually received. It does not reconstruct gross salary, payroll
withholdings, taxes or other deductions from a net deposit. Richer payroll evidence would
need a separately reviewed interpretation with its own sources and postings.

The income service reuses the tested read-only preview and atomic posting machinery.
Preview binds source identity, amount, date, description, candidate plan, existing proposal
history, date provenance and category mappings. No category is inferred from legacy labels.
An ordinary income receipt has an optional note and a standard audit reason. A pending
expense/refund proposal must first be explicitly rejected; classifying that rejected
movement as income requires a new reason and preserves the old decision and annotation.

Apply revalidates under the write transaction, creates any required income-account mapping,
posts one balanced reviewed imported entry, consumes the observation once and records the
plan in append-only `IncomeInterpretations`. The table is created only during application.
All writes roll back together. Concurrent transfer/expense posting, partial consumption,
changed review inputs or a tampered preview prevent application. Exact retry and reopen do
not duplicate the journal, even after a later category correction. Source balances, coverage
and estimated dates are not certified by income classification.

`IncomeCorrections` changes only income-category counterparts of an active positive cash
receipt. A required reason and exact preview precede atomic reversal/replacement, preserving
the full original financial posting, allocation, amount, date, description and event.
Current category distribution follows the active replacement; originals and decisions remain
history. Total income and financial movement remain unchanged. No expense conversion,
transfer conversion, negative-income correction or payroll reconstruction belongs here.

The service and its shared expense paths passed 59 focused tests, including 20 new income
cases covering signs, exact splits, scope, proposal history, optional/required reasons,
concurrent transfer/expense consumption, partial postings, stale/tampered previews,
mapping conflicts, atomic rollback, category correction chains, read-only inventory,
retry/reopen and reconciliation invalidation. The income review UI and Windows acceptance
follow this service chunk. Private archive exercises use disposable copies and are not
financial approvals; the active client profile and reports remain unchanged.

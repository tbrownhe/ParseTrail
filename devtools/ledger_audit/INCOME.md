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
retry/reopen and reconciliation invalidation. The income review UI is implemented;
The owner accepted the Windows income workflow and persistence on October 3, 2026.
Private archive exercises use disposable copies and are not
financial approvals; the active client profile and reports remain unchanged.

## Income review window

Prepare a fresh candidate copy from the repository root:

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/review_proposals.py --income --candidates <candidate-folder> --folder <new-review-folder> --prepare-only
```

Open or reopen that workspace:

```powershell
& client/.venv/Scripts/pythonw.exe devtools/ledger_audit/review_proposals.py --income --folder <review-folder>
```

**Unposted movements** lists only positive, wholly unallocated checking/savings receipts
without a pending expense/refund proposal. Its notice explicitly distinguishes receipt
eligibility from income classification. Use **Classify as income…**, choose an existing
income category (none is preselected), and optionally add positive USD category splits
that total the exact deposit. Routine income posting keeps the note optional. A rejected
expense/refund proposal remains accessible through the prior-interpretation filter and
requires a reason for its new classification; its earlier decision remains in history.

The preview shows income and cash received as positive amounts and explains that income
journal credits are stored negative. It preserves the observed amount, date and source
description. It does not infer gross pay or deductions, promote date provenance, or certify
statement reconciliation. Form edits invalidate the preview. Cancel, closing the dialog,
and cancelling final confirmation write nothing. Apply checks for competing allocations
and changed inputs under the transaction before committing.

After posting, the window selects the receipt in **Posted income receipts**. Use
**Edit category split…** to preview a later income-category correction with a required
reason. Its preview shows zero change to total income and cash received, then confirms
reversal/replacement. **Active**, **Superseded**, and **All** filters expose the history;
only active receipts are editable. Income category amounts are displayed positive in
the table and preview. Reopening preserves the posting and correction chain.

For Windows acceptance, select one test receipt in the disposable copy, preview/cancel,
then preview/post. Change or split its income category with a sample correction reason,
preview/cancel once, then apply. Inspect the active replacement and superseded original
and close/reopen to check persistence. These are workflow checks only, not approval of
actual income categorization. `--smoke --income` automates posting and correction checks
with cancellation, history and reopen in a separate disposable copy.

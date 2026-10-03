# Ordinary expense and refund corrections

`ExpenseCorrections` provides a read-only preview and atomic application for changing
the expense-category counterparts of an already posted cash/card purchase or refund.
It follows the accepted [reconciliation review](RECONCILIATION.md). The service and
disposable correction editor passed owner Windows workflow/persistence acceptance on
October 3, 2026. Test choices remain disposable, not approval of actual financial history.

The caller selects an active imported ordinary entry, one or more existing expense
categories, exact positive minor-unit amounts, and a required explanation. Split amounts
must sum to the entire source movement. The source sign determines whether the expense
postings are positive purchase amounts or negative refund amounts. Repeated categories,
zero/negative/floating-point amounts, mismatched totals, unsupported categories and
unchanged allocations are rejected.

```python
service = ExpenseCorrections(review)
plan = service.preview(
    original_entry_key,
    [(first_expense_category_id, 1000), (second_expense_category_id, 500)],
    "Split the original purchase between its evidenced expense categories",
)
# Present and confirm the exact preview before applying it in an interactive client.
replacement_key = service.apply(plan)
```

Preview leaves the database unchanged. The plan binds the candidate workspace,
original journal payload and interpretation-review state, requested split, category
mappings, replacement entry and explanation. Split order does not change its identity.
Applying rechecks the preview against committed inputs under the write transaction;
changed interpretation review or an intervening correction requires another preview.
Exact retries return the original replacement without additional journal entries.

Application preserves the financial posting, source observation/allocation, posting
date, description and economic-event identity. It reverses the old journal and posts a
reviewed replacement with the requested expense counterparts. New expense ledger
accounts may be mapped from retained category definitions, but categories themselves
are not created, renamed or retyped. Mapping, reversal, replacement, allocation release
and correction history commit together; failure rolls them all back.

Original journals, source statements/transactions, verified category annotations and
proposal decisions remain immutable history. A proposal's old accepted decision does
not become a new category assignment; consumers of corrected books must use the active
replacement, not replay the proposal's historical category. Later corrections target
that active replacement. Total expense and financial-account movement do not change;
only category distribution changes. Reconciliation snapshots become stale because the
journal version changed, even when recalculation yields the same exact balances.

## Scope boundaries

The service requires one wholly allocated financial observation with only normal
expense counterparts. Pending proposals still use ordinary accept/reject review;
this service cannot post a new interpretation for an unposted observation. Partial
settlements, transfer/clearing entries, income, loans, asset recognition, openings,
manual journals, source amount/date/account corrections and mixed-sign splits require
separate workflows. In particular, this is not an expense-to-transfer conversion or
an automatic adjustment for a statement difference. Corrections always require a
reason; routine ordinary acceptance retains its optional-note behavior.

Testing uses synthetic fixtures and a fresh disposable archive workspace. Private
purchase/refund decisions made to exercise corrections are UI/service tests, not actual
financial approvals to migrate into rebuilt books. Accepted candidate inputs and the
live profile remain unchanged. No schema migration, dependency, server change or report
cutover is introduced.

## Correction editor

Prepare a fresh copy from accepted unposted candidates (repository root):

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/review_proposals.py --corrections --candidates <candidate-folder> --folder <new-review-folder> --prepare-only
```

Open or reopen that same workspace:

```powershell
& client/.venv/Scripts/pythonw.exe devtools/ledger_audit/review_proposals.py --corrections --folder <review-folder>
```

The fresh **Posted expenses and refunds** tab starts empty. In **Original proposals**,
accept one ordinary expense/refund as a disposable workflow exercise, then return to
the posted tab. Select its active entry and choose **Edit category split…**. Choose
another expense category or add splits, supply a correction reason, then preview.
Amounts use positive USD text with at most two decimal places, without commas or currency
symbols; they must sum exactly to the original movement. Refund amounts reduce expenses.

The preview shows current and replacement category amounts, unchanged financial movement
and total expense, the reason, and reversal/replacement history. Any edit clears the
preview and disables Apply until previewed again. Cancel or closing the editor writes
nothing. Apply requires confirmation and rechecks the committed inputs; another correction
or interpretation-review change invalidates a stale preview.

After applying, the active list selects the replacement. **Superseded** and **All** filters
expose original entries with replacement links; superseded entries cannot be edited.
Later corrections target the active replacement. **Original proposals** retains historical
proposal categories and decisions; current category distribution comes from posted entries.
Returning from proposal review or choosing **Refresh entries** reloads current postings.

For native acceptance, cancel a preview once, then preview/apply a sample correction,
inspect both active and superseded entries, and close/reopen to confirm persistence.
These test choices do not approve the owner's financial history. Native Windows acceptance
precedes broader use; prepare each owner test from unposted candidates rather than copying
earlier test decisions. `--smoke --corrections` exercises cancellation, confirmation,
application, history/filter behavior and reopen in a separate disposable workspace.

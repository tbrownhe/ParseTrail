# Ordinary expense and refund corrections

`ExpenseCorrections` provides a read-only preview and atomic application for changing
the expense-category counterparts of an already posted cash/card purchase or refund.
It follows the accepted [reconciliation review](RECONCILIATION.md). This is the service
chunk; a correction editor and owner Windows acceptance are still required.

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
live profile remain unchanged. No GUI, schema migration, server change or report cutover
is introduced by this service chunk.

Next: an editor that lists active ordinary entries, previews the category split and
reversal/replacement, requires a correction reason, and offers cancellation before
application. Native Windows workflow/persistence acceptance precedes broader use.

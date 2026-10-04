# Capital One loan payments and interest

This disposable workflow follows the accepted [loan-readiness audit](LOANS.md).
The active application still uses its legacy database. Sample review decisions
exercise the workflow; they do not approve the owner's real financial history.

## Bounded source contract

Only USD Loan/Debt accounts parsed by `pdf_capitaloneauto_202402` version `0.2.1`
are supported here. That parser validates printed principal, interest and total
payment components. Its reconstructed opening is still derived, so a matching
source balance equation is not independent reconciliation.

Each positive `Payment Received` row needs exactly one nonpositive `Interest Fee`
row on the same loan/date with a shared statement. Every source membership must
belong to an eligible parsed statement with an exact balance equation and
in-period, USD movements. Missing, multiple or shared interest components block
posting; no missing interest is assumed to be zero. An explicitly zero component
remains source evidence without a zero observation or journal posting. Interest
greater than the payment needs a different interpretation.

An exact opposite checking/savings movement within the selected 0–31-day window
(default seven) is a candidate only. Multiple matches remain visible. The user
explicitly chooses a pair. Nonzero interest always uses the fixed **Loan interest**
built-in category; there is no category picker or service-level category override.
A pending ordinary expense/refund proposal on the bank
movement must first be rejected with a reason. Already allocated movements block
posting. Prior category annotations and rejected proposal history remain intact.

## Accounting and persistence

The full payment debits the loan liability and credits cash. Same-day movements
use one entry; differing dates use two through transfer clearing, preserving both
dates, including when the loan receipt precedes the bank outflow. A separate
interest entry debits expense and credits the loan liability. Thus net principal
reduction is payment minus interest, and the transfer adds no expense itself.
The interest date comes from the source; posting never promotes date provenance.

The read-only preview binds source components, category mappings, date provenance,
reason and journal contents. Blank confirmation notes receive a standard audit
reason. A final confirmation defaults to Cancel. Editing inputs invalidates the
preview; competing allocations or changed inputs reject a stale plan.

One transaction admits only the selected nonzero loan observations, inserts any
needed category/clearing accounts, posts all entries under one economic event and
saves an immutable `LoanPaymentDecisions` record. Any failure rolls everything
back. Exact retries are idempotent. Confirmed payments remain in their own tab,
independent of the candidate date window, with category/reason/source details.
Cash reconciliation notices the new postings and invalidates previous results;
loan statements and opening balances remain outside certification.

The [shared category catalog](../../client/src/parsetrail/core/ledger_categories.py)
keeps built-ins separate from user-defined categories. `builtin:loan-interest` maps
to a fixed expense account; matching display names never establish that identity.
Ordinary expense classification and corrections can use built-ins alongside the
retained user categories, including mixed splits. Catalog reads do not create
accounts; posting creates the required mappings atomically. The loan workflow
enforces its built-in even if a modified preview asks for another category.
Zero interest creates no expense account or posting. Old disposable decisions keep
their actual category in history; version-one previews must be regenerated.

Other loan parsers, fees without this component contract, financing, asset
purchases, disbursements, synthetic origination, openings and loan-component corrections
are separate scopes. The Wells Fargo parser-change deferral remains in force.
No server, dependency, parser or active-profile changes are required.

## Run and Windows acceptance

Use accepted unposted candidates, never a previous workflow's sample decisions:

```powershell
client/.venv/Scripts/python.exe devtools/ledger_audit/loan_payments.py --candidates scratch/accepted-candidates --folder scratch/loan-payment-review --prepare-only
client/.venv/Scripts/python.exe devtools/ledger_audit/loan_payments.py --folder scratch/loan-payment-review
```

The first command refuses an existing destination. Resume with only `--folder`.
An automated offscreen exercise uses a separate new folder with `--candidates`
and `--smoke`; it tests preview, window-close cancellation, final-confirmation
cancellation, posting and reopening. Interest always uses its built-in category.
Screenshots and databases remain in ignored storage.

The owner accepted the Windows workflow on October 3, then requested fixed built-in
categories. The updated fixed label and shared category selectors have automated
coverage. A targeted visual check can use this walkthrough:

1. Select a payment candidate, inspect the bank and loan sources, and open
   **Review payment and interest**. **Loan interest** should be a fixed label.
2. Preview. Check that full cash outflow, interest expense and principal reduction
   are clearly distinguished. Close/Cancel; nothing should be confirmed.
3. Reopen the preview, confirm and post. Check **Confirmed payments** for the
   saved status, category and note (a note is optional).
4. Close and reopen the same folder. The confirmation should persist and the
   payment should no longer be offered for posting.

This acceptance gate tests the UI, not actual financial classifications. Do not
carry its sample decisions into rebuilt books.

## Correcting a bank match

The correction service accepts only the latest active fixed-category loan bundle.
Choose another exact opposite cash movement within the selected 0–31-day window
and supply a reason. Already allocated or pending expense/refund interpretations
block the replacement. Equal amounts remain suggestions; the user confirms the
relationship. A 31-day window is useful for this disposable workflow exercise,
but adjacent monthly payments are not thereby established as interchangeable.

The preview shows the previous and replacement bank/date, unchanged loan payment,
principal and Loan interest, and the return of the previous bank movement to review.
The original withdrawal remains source evidence; releasing its allocation is not
a refund or deletion. Source component/amount/date changes and category changes
are outside this workflow. Explicit zero interest remains zero with no expense.

The kernel reverses every active entry of the original event and posts the whole
replacement in one transaction, preserving economic-event identity. Same-day and
different-date matches can have different journal counts. Clearing is canceled for
the old match and installed for the new dates as needed. New mappings, reversal/
replacement journals, allocation release and `LoanPaymentCorrections` history all
roll back on failure. Repeated identical requests do not repost; stale previews or
competing decisions fail. Subsequent corrections append another history version.
Loan components and source tables remain unchanged. Reconciliation becomes stale.

**Confirmed payments** shows the current match, with **Corrected and posted** after
a correction. **Previous bank matches** shows superseded choices and their reasons.
Earlier category-choice test workspaces stay readable, but correction requires a
fresh fixed-category workspace; sample decisions are never migrated into real books.

For a new workflow-test folder, use the commands above, then launch with
`--corrections` to start at a 31-day candidate window. Add `--corrections` to a fresh
`--smoke` run to exercise cancellation, correction, history and reopen automatically.

The owner accepted the Windows correction workflow on October 3, 2026. The walkthrough is:

1. Confirm one sample payment in the fresh disposable copy.
2. In **Confirmed payments**, select it and click **Correct bank match**. Choose
   another available movement, enter a test reason and preview the before/after effects.
3. Cancel once. Reopen the correction, preview, and apply it. Loan interest and
   principal should stay unchanged; the selected bank/date should change.
4. Check **Previous bank matches**, then close/reopen the same folder. Both the
   current match and prior choice should remain visible with their reasons.

Only sample workflow decisions belong in this test; the live database is untouched.

All shared ledger review tables, including correction candidates and prior matches,
support sorting by clicking any column header; click again to reverse the order.
Amounts/counts sort numerically with exact precision, ISO dates chronologically,
and text case-insensitively. Initial workflow ordering remains until a column is
chosen, and the chosen sort survives filtering and table refreshes. Selection and
posting actions continue to use the underlying record identity.

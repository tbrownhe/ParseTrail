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
explicitly chooses a pair and an existing expense category for nonzero interest;
no category is preselected. A pending ordinary expense/refund proposal on the bank
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

Other loan parsers, fees without this component contract, financing, asset
purchases, disbursements, synthetic origination, openings and loan corrections
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
cancellation, posting and reopening. Its arbitrary category choice is a test.
Screenshots and databases remain in ignored storage.

Native Windows acceptance is pending:

1. Select a payment candidate, inspect the bank and loan sources, and open
   **Review payment and interest**. Choose an interest expense category.
2. Preview. Check that full cash outflow, interest expense and principal reduction
   are clearly distinguished. Close/Cancel; nothing should be confirmed.
3. Reopen the preview, confirm and post. Check **Confirmed payments** for the
   saved status, category and note (a note is optional).
4. Close and reopen the same folder. The confirmation should persist and the
   payment should no longer be offered for posting.

This acceptance gate tests the UI, not actual financial classifications. Do not
carry its sample decisions into rebuilt books.

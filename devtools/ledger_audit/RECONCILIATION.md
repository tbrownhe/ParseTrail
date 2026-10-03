# Reviewed-source reconciliation

This read-only service connects the [saved source reviews and opening positions](OPENINGS.md)
to the exact ledger reconciliation kernel. It checks scoped cash/card statements in
one committed SQLite read snapshot. It never posts journals, changes source assertions,
rewrites raw statements, or treats a category verification as accounting approval.

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/reconcile.py `
  --folder <prepared-opening-review-directory> --output <new-private-output-directory>
```

The workspace must already contain an opening-readiness plan. The exporter opens its
database with SQLite `mode=ro`, rejects database sidecars, validates the prepared
workspace, checks deterministic replay and verifies that input bytes remain unchanged.
It refuses to overwrite an output directory. Private statement IDs, amounts, filenames,
references and hashes remain in ignored `reconciliation.json` and `report.json` files.
The completion report contains input checksums and the reconciliation artifact digest.

Development acceptance starts with a **fresh unposted candidate copy** prepared using
the opening-review command. Prior owner GUI sample decisions are not financial
attestations to carry forward. That fresh copy should report unresolved work, not
produce automatically reconciled books. Synthetic fixtures exercise the positive cases.

## Independent result dimensions

| Result | Meaning |
| --- | --- |
| `balance_check` | The kernel's exact source equation, ledger opening/closing differences, evidence allocation and postings outside statement evidence, using the reviewed endpoint provenance. |
| `reconciled` | The balance check passes, source period timing is reviewed, the opening decision is current, and this statement and its observations have reported posting-date provenance. |
| `posted_interpretations_reviewed` | All active postings affecting this account through the statement end have current interpretation review. This is separate from balance reconciliation and does not imply that unposted evidence was reviewed. |
| `unresolved_observations` | Exact signed amounts still unallocated within this statement; opposite amounts are never netted away. |
| `date_uncertain_observations` | Observations whose posting dates remain unknown or estimated. Any estimated source membership keeps the observation estimated. |
| Account continuity | Source-period bounds, missing periods, overlaps, differing adjacent endpoints and unavailable statements. These are coverage facts, not an account certification. |

For example, Chase statement balances may agree fully while the overall reconciliation
retains `posting_dates_not_verified`. Its transaction-date proxies remain estimated.
A later statement may reconcile while an earlier equal-balance gap remains visible in
account continuity. Neither outcome certifies complete history or a current cash forecast.

Statements in the cash/card scope that cannot enter the kernel remain explicitly
`unavailable`, with their original eligibility reason and source difference. Statements
outside this scope are listed separately. `unmapped_movements` retains missing-membership,
source-review, zero-amount and outside-scope decisions. The global `remaining_observations`
mapping lists each unresolved canonical observation once, even across overlapping sources.

Corrections include the original and reversal in balance arithmetic, but only active
replacement evidence in allocation/interpretation checks. Unbacked manual postings
remain exceptions even when an opposite posting cancels their net amount. Month-crossing
transfers preserve both dates and the intermediate clearing balance.

## Versioning and next workflow

`ReviewedReconciliation.snapshot()` returns a deterministic rule and `input_version`.
The version covers source membership, kernel evidence, journal entries and allocations,
corrections, interpretation reviews, source assertions, opening decisions and the bound
plans. `is_current(report)` compares against a fresh committed read snapshot. Even a
zero-opening decision or a source-review change without a new journal invalidates the
old result. Invalidation is intentionally conservative across the workspace. Exported
files preserve the checked cutoffs, exact differences and version; they are snapshots,
not permanently current certifications.

The old `LedgerStore.reconcile()` remains the raw kernel entry point and still sees
unverified raw endpoints. Reviewed workflows must use this service rather than treating
those older history records as reviewed-source results. No new database history table
or schema migration is introduced by this calculation chunk.

The review UI below now exposes these checks. Split/correction controls, other account
scopes and report cutover remain unfinished; `ready_for_cutover` stays false. The
calculation/export service itself remains read-only.

## Statement review window

Prepare a **new** workflow copy with no earlier owner sample decisions:

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/review_proposals.py `
  --reconciliation --readiness <verified-readiness-directory> `
  --candidates <verified-candidate-directory> --folder <new-private-review-directory>
```

Use `--prepare-only` to create without launching or `--smoke` for a separate offscreen
cancel/save/stale/reopen/recheck exercise. Reopen using only `--reconciliation --folder
<prepared-review-directory>`.

The window has searchable statement checks, evidence for the selected statement,
account coverage, and movements outside the ledger. Statement details show source and
ledger balances, exact differences, source review, interpretation review and exceptions.
Evidence retains original amounts/dates and shows exact unallocated amounts and date
provenance. Unadmitted zero rows do not acquire an invented reported-date assertion.
Clearing the statement selection also clears its evidence and disables source review.

The **Source review** column shows the current saved assertion independently of the
last reconciliation check: **Recorded**, **Not recorded**, or **Unavailable**. Its
dedicated filter combines with the text search. Saving updates this status immediately,
even while the old check is stale; the details distinguish the current review from the
reference used at the last check. Recorded means a review was saved, including a partial
review, not that all evidence was verified or reconciliation passed. Under **Not
recorded**, a newly reviewed row leaves the list; find it under **Recorded**.

**Review selected source** works for any eligible statement, including later periods.
The dialog records opening/closing origin, period timing, posting-date provenance,
a required source reference and an optional note. Cancel or closing the dialog records
nothing. Save appends a source assertion only; it cannot post a transaction or opening,
override source ineligibility, fill coverage gaps, or upgrade known Chase date proxies.
If another window changes that source while editing, save requires reopening the form
instead of silently superseding the unseen review.

The first launch calculates a snapshot. **Check statements** explicitly refreshes it.
The last displayed check is saved atomically in private `reconciliation-view.json`,
with its checksum and evidence/rule bindings; interrupted replacement preserves the
previous file. This is a replaceable display snapshot, not source evidence or an audit
decision. A malformed or mismatched snapshot is rejected and preserved for inspection.
Saved source reviews remain in the append-only database history.

Saving source review marks the old display **STALE** until recalculated. The window
also detects committed changes from another connection; it performs the full version
check only when SQLite's change indicators differ. Close/reopen retains the saved
display and detects its currentness again. A current check can still contain unresolved
differences; currentness does not mean reconciliation passed. Existing raw kernel
reconciliation history remains untouched.

## Windows workflow walkthrough

This is **workflow acceptance only**, not certification of the test financial assertions.
The owner copy starts from unposted candidates, so unresolved balances are expected.

1. Select a statement after the earliest one for an account. Inspect its source/ledger
   differences, then the **Selected statement evidence** and **Account coverage** tabs.
   Filtering the statement list to no matches should clear its evidence selection.
2. Open **Review selected source**. For this disposable exercise, set both balance
   origins to **Printed on statement**, check period timing, and enter **Workflow test**
   as the reference. Leave posting dates unchanged. Cancel once, then repeat and save.
   The main window should show **STALE**, retaining the previous check, while its
   **Source review** column immediately shows **Recorded**. Use the **Recorded** filter
   to find it without recalculating.
3. Close and reopen before recalculating. The stale banner and saved source review
   should persist. Click **Check statements**: the banner should become current,
   with remaining accounting work still visible.
4. Inspect a Chase source: posting dates must remain **Estimated posting dates**, with
   that control disabled. Neither source review nor recalculation posts journals.

Owner Windows acceptance is pending. Automated workflow artifacts and owner test
decisions remain in separate disposable workspaces; no live profile is changed.

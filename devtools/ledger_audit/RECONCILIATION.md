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

Next is a statement-reconciliation review UI: inspect differences and evidence, review
source provenance for statements beyond the earliest period, and make stale results
visible. It requires owner Windows workflow acceptance. Split/correction controls,
other account scopes and report cutover remain unfinished; `ready_for_cutover` stays
false in this service. This service/report chunk itself adds no native GUI or dependency.

# Guided V2 review and responsive workspace

Date: 2026-11-01. Roadmap: V2-UX, V2-3/4/5/6. Branch: feature/client-financial-insights.
Authorization: owner approved implementation of the [evaluated proposals](2026-11-01-v2-ux-performance-evaluation.md), with delegation and reasoning adjusted as needed.
Implementation: complete within approved development scope.
Automated verification: final combined 286 tests passed; changed-file lint/format and documentation links passed.
Design verification: independent screen/state plan and actual working-font integrated Qt inspection completed; identified issues corrected.
Independent integrity review: completed; backup recovery, date provenance and missing-receipt qualification findings corrected and rechecked.
Owner acceptance: not performed; consolidated integrated review remains separate.
Release authorization: not authorized.

## Scope and controlling decisions

Implement the approved workflow/performance improvements: accurate review states,
responsive ordinary/specialized reads, efficient explicitly confirmed ordinary
batch review, embedded account/report working areas, guided document review,
clear setup/empty states and focused coverage/specialized layouts. Preserve exact
money/dates, source provenance, unknowns, explicit account/posting decisions,
whole-event correction and local-only ordinary finance. No schema migration,
live-profile activation, production signing/publication or service changes.

Use public synthetic sources and new disposable profiles only. Existing evaluation
records and owner demos remain evidence; do not mutate their accounting state.
The initial working tree contains only the evaluation record and its index entry.

Ownership: primary integrates workspace/reports, contracts, planning and this
record. Desktop owns ordinary cash/card/register review and new shared GUI job/
filter/batch helpers and their tests. Ledger exclusively owns `v2_profile_store.py`,
new headless batch/read-model helpers and their tests. UI/UX owns read-only design
and actual rendered critique. All specialists avoid unrelated/shared-file edits.
Subsequent specialist assignments and verification results are recorded below.

## Design plan and criteria

Retain Documents / Review / Accounts / Reports; make each a working area.
Document/account/date context and the next useful action remain visible. Completed
account association becomes status plus Change. Ordinary review has search,
status filters, stable selection, exact sorting, next-pending keyboard operation,
and staged explicit multirow purpose/category/reason choices. Batch preview lists
each source/date/account/effect before one atomic confirmation. Separate correction
from new-entry batches. Reviewed-elsewhere rows route to their owning event.

Embed existing qualified account positions/history and report tabs. Explain
empty selected periods without implying complete zero spending. Default coverage
to readable identity and independent compact check dimensions, with full details
discoverable. Collapse rules/unselected detail in specialized reviews and preserve
working table space at 1100×650.

Render loading shells promptly; worker-owned connections return immutable data.
Capture scope/profile/generation, reject superseded results, serialize helper
writes, and retain commit-time stale validation. Cancelling after commit must not
claim rollback. Never skip integrity checks merely to meet a timing target.

Observable criteria: coherent pending/blocked/reviewed/elsewhere/error states;
explicit account/purpose/category/date/reason decisions; stable filtered drafts;
atomic stale/tamper/overlap refusal; readable identity/actions at 1100×650;
predictable keyboard focus; no GUI-thread snapshot work in converted views;
same-workload before/after measurements and exact existing financial regressions.

## Result and review

Implemented the guided workspace and ordinary category batching without changing
profile schema 22 or financial policy:

- Review, Accounts and Reports now contain working views instead of repeated
  modal launchers. Review stays scoped to the selected document, retains account/
  period context and provides related transfers/loan/fee/account/evidence actions.
  Positions and report dates persist across navigation; account review routes
  back to an associated document. Readable profile names retain a copyable path.
- Ordinary cash/card/register activity supports search/status filters, exact
  sorting, next pending, stable row-ID selection, per-row unapplied purpose/
  category/date choices, staged eligible rows and an exact human-readable batch
  preview. Technical postings and source rules remain discoverable. Staging
  discloses hidden rows and an explicit shared reason; cancellation posts nothing.
  Corrections and withdrawal remain separate from new-entry batches.
- The headless batch API binds every exact selection/effect/date/reason to its
  review basis and profile identity, then rebuilds/revalidates inside one immediate
  transaction. Exact retries reuse entries. Unsupported, stale, cancelled,
  tampered, consumed or invalidly rebound members cannot partially post.
- Reviewed-elsewhere rows identify and open their owning loan/transfer/settlement
  workflow. They do not ask for another ordinary purpose. Source date provenance
  reaches the preview; category labels preserve built-in/custom disambiguation.
- Shared worker jobs coalesce reads, retain connections safely and serialize
  their confirmed writes per profile. Ordinary and specialized snapshots/previews
  and cash-movement scope changes run in the background. Closing/profile switching
  waits for confirmed writes, and discarded reads cannot publish late results.
  Backup, restore, export, original recovery, package activation and folder scans
  have scoped outcome/progress ownership. Restore remains independent of a damaged
  current database; destination and verification rules are unchanged.
- Coverage shows six readable primary columns, with independent capture/arithmetic/
  scope/reconciliation detail. Source-review selection survives refresh. Loan and
  settlement views retain useful table space, collapse rules and expose exact
  preview/history separately. Missing-receipt ownership never creates a destination
  posting; component scope and unknown values remain qualified.
- Selected-source reads retain full archive verification while reusing only
  transaction-scoped evidence and compact verified guard/period metadata. Each
  relevant model decodes once per operation; no persistent/global evidence cache,
  duplicate accounting store, migration or removed integrity check was introduced.

Primary assumed ownership of completed specialist files for integrated fixes and
test adaptation after their handoffs. Updated current ledger/store/action contracts
and the client guide describe lasting behavior. No service, website, release,
production-signing, owner-profile or existing-demo runtime was changed.

### Review findings resolved

Independent integrity review found and rechecked three concrete issues: restore
jobs initially validated the damaged current profile before the healthy backup;
cash previews initially guessed observed provenance for derived dates; compact
cash-movement text initially described destination-only expectations as selected
outflows. Connection-free independently verified restore jobs, explicit provenance
and qualified expectation wording correct these cases.

Independent UI inspection found a hidden staged-count update during transitional
proxy filtering, technical-only batch effects and unnamed ordinary tables. A final
filter scope signal, plain account/category effects with posting Details, and named
tables correct those findings. Independent acceptance also reproduced unstaged
choice loss through filtering; entry-bound row-form drafts now preserve those
choices without posting. A successful withdrawal clears prior editor choices for
fresh review. Stale/refused attempts retain authored drafts while visibly asking
the user to inspect refreshed facts before another explicit confirmation.

Legacy GUI tests were adapted to await the actual worker outcomes, explicitly
select All when testing corrections, and answer their new discard prompts. A
test wait using `QTest.qWait` could starve Python workers on this Qt binding;
normal event processing plus `time.sleep(.005)` removed that testing artifact.
No production timeout was padded to conceal it. The offline diagnostic and pinned
demo consumer now await asynchronous review/report completion as well.

## Verification

Baseline: evaluation records 946 synthetic sources / 18,920 unposted rows,
selected 20-row cash snapshot 649–660 ms, synchronous dialog construction
658–668 ms. Tests use existing locked client Python and disposable conftest
profile/null keyring. Additional helpers explicitly isolate home/preferences/
catalog paths before importing application code.

### Performance evidence

Three warm measurements on the same synthetic 946-source/18,920-row workload:

| Operation | Before | After | Qualification |
| --- | --- | --- | --- |
| Selected ordinary dialog shell | 658–668 ms synchronous construction | 2–4 ms construction | Actual Qt constructor measurements; data is deliberately pending. |
| Loaded ordinary review | 649–660 ms open + snapshot | 609–623 ms asynchronous ready | Includes worker scheduling/UI update; full verification retained. |
| UI timer responsiveness during that read | Previously blocked by synchronous construction | Maximum observed 10 ms timer gap 25–48 ms | Three observed runs, not a percentile or native-frame guarantee. |
| Selected snapshot service including open | 649–660 ms | 548–579 ms | Separate headless measurements; snapshot alone 504–520 ms. |
| Whole review-basis serialization | About 186 ms | About 93 ms | Exact digest compatibility checked. |
| Fifty selected ordinary rows among 947 sources | 29.43 s for fifty individual posts, excluding GUI refresh | 615 ms preview + 717 ms atomic posting | Explicit batch amortizes verified work; retry 583 ms. Synthetic exact service workload. |

The 100 ms shell/input target is supported by the measured workload. The proposed
250 ms total selected-snapshot target remains unmet; the application now stays
responsive while this integrity work completes. Cold disk, large originals and
larger populated/corrected histories need additional profiling before extending
these claims. No private archive was benchmarked.

### Independent and focused checks

All client checks use the existing locked `client/.venv/Scripts/python.exe`,
`PYTHONPATH=.;client/src;client`, `QT_QPA_PLATFORM=offscreen` and disposable test
fixtures/null keyring. Tests outside `client/tests` explicitly prepare isolated
synthetic homes/catalogs/profiles before application imports.

- Ledger specialist: 27 new batch/snapshot checks and 96 existing store, snapshot,
  overlap, correction, journal, history and opening regressions passed. The added
  derived-date read-model regression brings the snapshot suite to 9 passing tests.
- Desktop specialist: 13 asynchronous ordinary checks passed, and 28 dedicated
  cash/card/register checks passed before the final integration additions.
- Specialized desktop: 51 existing focused checks passed; final loan/settlement
  rerun 31 passed and coverage/responsiveness rerun 14 passed (overlapping sets).
- Independent integrity: 46 focused checks passed; 3 correction/recovery checks
  plus an explicit derived-date preview reproduction passed after fixes.
- Independent acceptance: 32 integrated responsiveness/workspace checks passed;
  the subsequent 17 ordinary/workspace checks and 4 independent scratch checks
  passed. A three-row task staged two purchases, hid them under a filter, cancelled
  with zero writes, then confirmed exactly two entries/allocations and $7 October
  reviewed spending. Delayed export kept the event loop responsive, refused
  profile switching/close, and delivered one valid workbook/outcome.
- Pinned demo consumers: `devtools/v2_review_demo/test_review_demo.py` and
  `test_final_review_demo.py`: 5 passed after async consumer adaptation. These
  cover preparation, runtime hashes, six-source restore/history parity and
  display-suppressed Windows Qt construction, not native usability acceptance.
- Final primary integration: **286 passed in 269.51 s**, spanning 31 changed or
  directly affected client test modules, including the offline runtime diagnostic.
  Ruff check and format check passed on all 45 changed/new Python files;
  `git diff --check` passed; 113 local documentation links checked with no missing
  targets. Counts in the preceding specialist/reviewer sets overlap and must not
  be summed as a unique suite total.

Reviewed baseline: `0a218f90bf416c29c94346bc85a8a952c22e62e2` plus this working-tree
diff; no commit was made. From the repository root, with the environment above,
the final test argv was `python -m pytest -p no:cacheprovider <31 modules> -vv -x --tb=short`.
The module list and full result are retained locally in
`scratch/guided-review-integration-files.txt` and `scratch/guided-review-integration.log`.
Equivalent reproducible argument construction with the locked interpreter:

```python
import subprocess, sys
names = """card_purchase_review cash_activity_review cash_movement
category_purpose_integration category_purposes_dialog document_browser
guided_workspace hsa_cash_dialog liability_register_dialog loan_integration
loan_payment_dialog ordinary_batch ordinary_review_async ordinary_snapshot_performance
reconciliation_history_dialog register_repayment_category_routes reports_responsiveness
review_read_performance reviewed_reports_dialog runtime_cutover settlement_cash_integration
settlement_review_dialog source_account_bindings source_interpretation_repair_dialog
source_recovery specialized_responsiveness statement_journal_comparison
statement_reconciliation statement_source_review transfer_history_performance workspace_window""".split()
subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
                *(f"client/tests/test_v2_{name}.py" for name in names),
                "-vv", "-x", "--tb=short"], check=True)
```

### UI inspection and local preview

Primary and independent UI/acceptance reviewers inspected actual current Qt
screens with loaded Segoe UI at 1100×650. The first embedded layout expanded the
window; removing duplicate launchers/prose and compacting embedded controls now
leaves approximately nine ordinary table rows without hiding confirmations or
material limits. Accounts/Reports/first-use/empty/loading/blocked/elsewhere,
staging/hidden staging/preview cancellation, source evidence and component/
missing-receipt states were inspected. Ctrl+F/Tab focus and named tables were
checked offscreen. Specialized tests additionally exercised 125% Qt scaling,
long labels, 25 account choices and copyable paths.

Local, ignored synthetic evidence:

- `scratch/v2-guided-optimization-ui/` and `ux-final/`: integrated workspace,
  first use, ordinary staged/elsewhere/exact preview and empty-period reports.
  `batch-preview-final.png` shows the corrected plain-language effects and
  expandable exact posting lines; its preparation cancelled without posting and
  verified the source demo hash stayed unchanged.
- `scratch/v2-guided-specialized-ui/` and `scale125/`: coverage, cash movement,
  loan/settlement selection, missing receipts and exact previews.
- `scratch/time_ordinary_async.py`: same-workload shell/heartbeat timing aid;
  `scratch/v2_perf_evaluation_20261101.py`: initial isolated growth benchmark.
- `scratch/test_acceptance_guided_extra.py`: independent task/export/draft probes.

The Windows automation helper could not enumerate the sandbox-launched app
window. Native interaction, Narrator, installed Windows/Intel behavior and owner
acceptance are not attested by these offscreen checks.

A new independently pinned public synthetic preview is prepared at
`scratch/v2-guided-review-final-20261101/Open-review-demo.cmd`. Initial six-source,
schema-22 exact verification passed. `Batch-review-sample.csv` and
`BATCH-REVIEW.txt` provide an optional 50-row public example for import into that
disposable demo; those sample rows are not already imported or posted. Existing
profiles/demos remain unchanged. Running the preview is not daily-profile or
release activation.

## Remaining work

Development is closed with independent design, integrity and integrated checks.
The 250 ms total snapshot aspiration and broader cold/large-original/posted-history
profiling remain follow-ups; they do not justify weakening source verification.
Windows native interaction/Narrator, installed acceptance, Intel behavior, owner
acceptance and exact-candidate release authorization remain separate and unperformed.
No deployment, production signing/publication or daily-profile activation occurred.

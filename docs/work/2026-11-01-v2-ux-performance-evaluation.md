# V2 client workflow and performance evaluation

Date: 2026-11-01. Roadmap IDs: V2-UX, V2-3/4/5/6. Branch: feature/client-financial-insights.
Authorization: evaluate the current V2 client and propose optimizations. Proposal only; no application changes, daily-profile activation or release.
Implementation: not applicable; proposals only, no application changes.
Automated verification: 38 focused performance/responsiveness checks passed; synthetic timing details below.
Design verification: current-source synthetic Qt screens inspected with usable fonts; findings below.
Independent review: separate UI/UX and desktop performance reviews completed and integrated by the primary.
Owner acceptance: not performed.
Release authorization: not authorized.

## Scope and controlling decisions

Evaluate first use, importing and assigning documents, ordinary and specialized
activity review, reporting, corrections and background work. Preserve exact
accounting, source provenance, unknown facts and explicit posting confirmations.
Prior work is evidence, not a request to repeat completed improvements.

The primary owns this record and its index entry. The UI/UX reviewer and desktop
performance reviewer have no application write set. Only public synthetic data
and new disposable profiles are permitted. No live profiles, archives, root
environment file, service, production signing or publication actions are in scope.

Review criteria: users can identify scope and next steps, distinguish saved
evidence from reviewed books, find a transaction and its original, correct a
decision, and understand pending/error/loading states without internal IDs or
accounting implementation knowledge. Performance claims distinguish measured
latency from code-level risk. Agent inspection does not attest owner acceptance.

## Result and review

The strongest opportunity is to organize the interface around finishing a user's
task. Current screens frequently expose the boundaries between accounting
services: choose an activity tool, launch a dialog, inspect eligibility, leave it
to choose a different tool, then open another dialog for results. A consistent
review surface and explicit next actions would reduce this burden while keeping
the existing ledger services and financial safeguards.

This evaluation does not establish accounting correctness. It found presentation
contradictions and remaining synchronous work, not a reason to replace the ledger
or change financial meaning.

### Existing improvements to retain

- Recognizable document labels/search, contextual document actions, inline and
  batch account assignment, and embedded memory-only originals.
- Background inventory and selected report reads, generation guards, transfer
  planning/recovery and transaction-scoped history verification.
- Report detail disclosure: account positions already show six primary columns,
  with other dimensions discoverable through Details. Do not reintroduce all
  technical information into the default view.
- Unknown openings, component scopes, separate source/accounting dates and
  explicit posting confirmation. Concise wording must preserve their meaning.

### Prioritized findings and proposals

Priority describes recommended implementation order, not an automatic new
release gate. All proposals remain unimplemented.

| Priority | Current finding and evidence | Recommended optimization | Observable result |
| --- | --- | --- | --- |
| P1 | In cash review, the synthetic Capital/Yamaha checking payments show **Already posted to the ledger** beside **Pending explicit review**. The form still asks for a purpose although posting is disabled. See [cash model](../../client/src/parsetrail/gui/v2_cash_activity_review.py), `_ReviewModel.data`, `_update_withdraw`. | Show the owning interpretation, e.g. **Reviewed loan payment**, and **View payment**. Suppress irrelevant ordinary category inputs; route correction to the owning whole event. Card review already distinguishes reviewed-elsewhere rows. | No already-consumed row appears to require another ordinary posting; its reviewed event and evidence are directly reachable. |
| P1 | Ordinary cash/card review is single-row, without search, status filtering or sorting. Each posting requires purpose, category, free-text reason and modal confirmation; after posting the reason clears and the row remains selected. See [cash review](../../client/src/parsetrail/gui/v2_cash_activity_review.py), constructor and `_act`; [card review](../../client/src/parsetrail/gui/v2_card_purchase_review.py). | Add pending/reviewed/blocked filters, search, exact numeric/date sorting, keyboard navigation and **Next pending** first. Then stage explicitly selected eligible ordinary rows with purpose/category and an explicitly chosen shared reason for one exact batch preview and confirmation. Keep corrections separate. | A 50-row mixed review benchmark finishes faster with fewer repetitive actions; no automatic purpose inference, duplicate consumption or silent posting. Selection and filters survive updates. |
| P1 | Review exposes six workflow types overall, with several separate choices for a selected document. Confirm account remains an active step even when already confirmed. Numbered supporting-evidence checks follow activity review although repeat conflicts can block posting. See [workspace](../../client/src/parsetrail/gui/v2_workspace_window.py), review-page construction and `_update_controls`. | Use a contextual queue and status strip: account needed → resolve relevant repeat/blocker → review supported activity → inspect results/checks. Completed assignment becomes status plus **Change**. Route eligible rows to transfers, loan components or fees through contextual actions. | Users can identify the selected document/account, remaining work and next useful action without choosing an accounting subsystem first. No unconditional new overlap/reconciliation gate. |
| P1 | Ordinary review and coverage perform synchronous store reads before the dialog can render, unlike the existing background reports/transfers. See performance evidence below. | Render the shell immediately; load immutable snapshots in worker-owned connections; use cancellation, loading/error/retry states and profile/generation guards. Scope selected-document reads and update only affected rows after a write. | A growing archive does not freeze pointer/keyboard interaction just to open or refresh one document. |
| P2 | Accounts/Reports workspace pages mainly launch more modal windows; account positions are elsewhere. See [workspace](../../client/src/parsetrail/gui/v2_workspace_window.py), Accounts/Reports page construction. | Embed existing positions/history and existing report panels in their workspace pages. Keep selected account, source, date scope and scroll position. Reserve dialogs for bounded edits and confirmations. | Account → activity → original → correction → report is a continuous journey with a reliable return path. |
| P2 | Coverage exposes 11 primary columns. At 1100×650, account identity is truncated while other columns size to content. See [coverage](../../client/src/parsetrail/gui/v2_statement_coverage.py), `_CoverageModel.HEADERS` and constructor. | Default to Account, Period, separate compact review/check states and Next action. Put capture, source arithmetic, endpoints, journal comparison and saved reconciliation detail in a selected-row panel. Preserve readable identity widths and tooltips/copyable detail. | Users can recognize the account and act without horizontal searching. No single overall green check implies completeness or reconciliation. |
| P2 | Loan/settlement dialogs combine long rules, raw tables, details, history and posting controls. At 1100×650 the loan table is about two rows high, with substantial space reserved for unselected detail. See [loan review](../../client/src/parsetrail/gui/v2_loan_payment_review.py) and [settlements](../../client/src/parsetrail/gui/v2_settlement_review.py). | Focus the sequence: choose movements → inspect components/fees → preview exact effects → confirm. Collapse unselected detail, separate history mode, and place blocker explanations beside the blocked action. | Account identity, selected movement, exact financial effect and next action remain visible at the agreed window size. Whole-event corrections remain intact. |
| P2 | Empty first use says to import while Import is disabled pending **Install signed catalog**; users must understand package-folder internals. Profile paths and catalog controls also occupy prime workspace space after setup. See [workspace](../../client/src/parsetrail/gui/v2_workspace_window.py), catalog controls and `refresh`. | Add a deliberate setup state: **Install statement formats to enable import**, with concrete local signed-package instructions. After setup show a compact status plus **Manage**. Use a readable profile name, with full path in Details/Data locations. | Fresh users understand the prerequisite and can reach their first import without guessing. Preserve signature checks and the local/offline catalog boundary. |
| P2 | Reports initially select the current month. In the synthetic profile this shows $0 although earlier reviewed history exists; global pending counts are correctly qualified but visually distant from the task. See [reports](../../client/src/parsetrail/gui/v2_reviewed_reports.py), date controls and `_show_selected_tab`. | Explain empty selected periods and distinguish **no reviewed activity in this period** from a complete zero-spending claim. Show the chosen period, reviewed/pending scope and a contextual route to review. Offer navigation to an available period without silently changing the range. | Users understand why a report is empty and which work can change it; global pending counts are not presented as period-specific counts. |

### Proposed screen and state plan

Keep **Documents / Review / Accounts / Reports** as the stable navigation.

| Working area | Primary content | Context and recovery |
| --- | --- | --- |
| Documents | Searchable account/period document list, import status, recognizable source identity and next action. | Selected summary, original/evidence access and account association; technical parser/hash/path details remain expandable. |
| Review | Pending work across a deliberately selected document/account scope; filter by status, date and text; staged ordinary review. Start with the existing document scope before adding a profile-wide queue. | Selected-row evidence and exact proposed effects; contextual transfer/loan/fee workflows; direct **Resolve** action for blockers and **View reviewed event** for completed work. |
| Accounts | Existing qualified positions, openings and account history directly in the page. | Show whole-account/component scope and unknown state beside values; bounded edits for anchors, closure and dated values. |
| Reports | Existing report tabs, explicit period/as-of scope, totals and entry drill-down directly in the page. | Concise qualifications, contextual pending review, details and explicit export. |

Use consistent states across surfaces: **Needs account**, **Needs decision**,
**Ready to review**, **Reviewed**, **Reviewed elsewhere**, **Unsupported**, plus
**Loading**, **Cancelled**, **Unavailable—Retry**. Financial coverage/capture and
saved/live reconciliation remain separate dimensions. A document can have no
unallocated activity while still having unresolved coverage; do not call that
document globally complete.

For batch review, let users explicitly select eligible rows and assign allowed
purposes/categories. Show the exact selected rows, independent dates and effects
before confirmation. Revalidate all selected sources, account bindings, review
bases and active allocations inside one transaction; refuse stale batches with
actionable explanation and no partial posting. A batch-wide reason is authored
only when the user explicitly selects it. Never generate a fictitious review
reason or accept unsupported rows to make the interface simpler.

### Background operation design

Extend the existing working asynchronous patterns rather than adding unrelated
thread managers to each dialog:

- A shared operation presentation for loading, progress, cancellation, failure,
  retry and completion. Capture profile identity, scope, generation and input
  revision; discard superseded results. Each worker owns its connection and
  returns immutable data; widgets remain on the UI thread.
- Serialize writes per profile and guard confirmation against changes made since
  preview. Read-only navigation during longer work can be enabled only where
  snapshot consistency and operation ownership are explicit. A nonmodal progress
  indicator alone does not make concurrent edits safe.
- Show import progress by current file/stage and completed/remaining counts.
  Explain that cancellation retains completed imports, as the current batch
  results already do. Refusal messages should say what failed and the next
  supported action; keep diagnostic codes in Details.
- Avoid unconditional whole-inventory resets when closing an unchanged review.
  Use revision-aware invalidation and stable row/account selection. Keep explicit
  reload available for external changes; filesystem hints never replace write
  guards.
- Move backup/restore/export, large source-evidence preparation and folder
  enumeration off the UI thread where measured costs justify it. Verify
  publication/cleanup/overwrite behavior and cancellation semantics for each
  operation; report cancellation truthfully when a commit already completed.
- Preserve corruption/format checks, provenance verification and fail-closed
  behavior while removing redundant work. Any integrity-check reuse needs an
  explicit validity boundary and independent review. Do not remove checks merely
  to hit a timing target.

### Recommended implementation sequence

1. **Clarity and measurement:** repair reviewed-elsewhere status, blocker
   navigation, setup state, pending filters and next-pending behavior; instrument
   opening, refresh, confirmation and cancellation. Establish a repeated-use
   task baseline before changes.
2. **Responsive ordinary review:** background ordinary/coverage reads, consistent
   operation states, selected-source query scoping and targeted refresh. Preserve
   existing report/transfer performance and exact financial regression cases.
3. **Review throughput:** staged ordinary batch review with one deliberate
   confirmation and atomic validation. This needs a bounded headless batch API;
   a widget loop invoking individual posting methods is insufficient.
4. **Integrated workspace and focused special cases:** embed existing Accounts
   and Reports views, add scoped review navigation, then simplify coverage,
   loan and fee screens against the shared interaction patterns.

These are proposed bounded packets, not selected implementation or permission to
activate an existing profile. Keep the current schema/services where possible;
no migration, remote finance processing or new forecasting features are proposed.

## Verification

- Initial working tree clean; branch checked with per-command Git safe-directory
  setting because the sandbox identity differs from the repository owner.
- Prepared a fresh disposable public synthetic demo with
  `client/.venv/Scripts/python.exe devtools/v2_review_demo/prepare_demo.py --prepare-at scratch/v2-ux-evaluation-2026-11-01`.
  Its pinned runtime uses current source, schema 22, six embedded originals and
  seeded exact cash, loan, HSA and transfer examples. Initial verification passed.
- Platform: Windows source runtime using the existing locked client environment.

### Measured read performance

The independent performance reviewer created a new isolated synthetic profile,
with 20 CSV activity rows per source, one bound checking account and all rows
unposted. The selected document stayed the same 20-row source as unrelated
documents were added. Each measurement is three consecutive warm runs, including
store opening; these are elapsed Python/Qt constructor or service timings, not
native user task times. Profile size at 946 sources was approximately 25.9 MiB.

| Workload | Store open | Selected cash snapshot | Cash dialog construction | Document inventory | Cash movement read |
| --- | --- | --- | --- | --- | --- |
| 1 source / 20 rows | 8–10 ms | 11–13 ms | 13–15 ms | 10–11 ms | 9–10 ms |
| 64 sources / 1,280 rows | 10–14 ms | 46–49 ms | 49–52 ms | 34–36 ms | 18–19 ms |
| 256 sources / 5,120 rows | 21–22 ms | 169–180 ms | 172–175 ms | 114–115 ms | 54–62 ms |
| 946 sources / 18,920 rows | 59–64 ms | 649–660 ms | 658–668 ms | 416–443 ms | 219–259 ms |

Inventory already runs in a worker. Cash dialog construction and its snapshot
read run on the UI thread, so the last row demonstrates a meaningful interaction
stall even though the selected document is small. Do not describe all service
operations or small profiles as slow.

A separate `cProfile` run of the 946-source cash snapshot attributed about
0.715 s of 0.913 s profiled inclusive time to `source_overlap_posting_blocks`,
including roughly 0.707 s in `_source_overlap_index`. The overlap checks include
streaming verified imports/model validation; separate whole-basis serialization
took about 0.186 s. Profiling adds
overhead; its numbers are attribution evidence and must not be combined with
the unprofiled timing table.

Relevant current code:

- [Cash refresh](../../client/src/parsetrail/gui/v2_cash_activity_review.py),
  `refresh` at line 311; [card refresh](../../client/src/parsetrail/gui/v2_card_purchase_review.py)
  at line 459: synchronous store/snapshot reads, including after ordinary posts.
- [Store](../../client/src/parsetrail/core/v2_profile_store.py),
  `source_interpretation_snapshot` at line 3504; overlap index/basis construction
  around lines 2615–2895 and cash row enumeration around 3700.
- [Coverage constructor](../../client/src/parsetrail/gui/v2_statement_coverage.py)
  at lines 457–473: synchronously prepares coverage, openings, comparisons,
  reconciliation/history and account review state before constructing layout.
  This is a code-level blocking risk; the large-profile coverage constructor
  was not benchmarked here.
- Store `open` at line 1979 runs `_check_format` on a preliminary read-only
  connection and the final connection; `_check_format` at line 1625 includes
  `quick_check` and `foreign_key_check`. Measure and review that boundary before
  changing it. It is not the largest measured cost in the cash snapshot.
- [Report reader](../../client/src/parsetrail/gui/v2_reviewed_reports.py) and
  [inventory reader](../../client/src/parsetrail/gui/v2_document_browser.py)
  install SQLite progress cancellation after `open`; validation during open
  therefore precedes that handler. Python verification loops and shutdown joins
  also need explicit bounded cancellation review. No hang was demonstrated.
- Backup/restore in the workspace and workbook export in reports run
  synchronously. Large-file latency was not measured in this evaluation.
- [Cash movement](../../client/src/parsetrail/gui/v2_cash_movement.py),
  `refresh` around lines 193–204, runs its read synchronously on date/account
  changes; the measured service reaches 219–259 ms at 946 synthetic sources.
  Debounce edits and publish only the final requested scope through a worker.
- [Loan refresh](../../client/src/parsetrail/gui/v2_loan_payment_review.py)
  around lines 314–325 and settlement `refresh` around lines 363–379 run
  snapshots synchronously and can read ordinary then replacement context.
  Request the needed snapshot directly and load selected sections in the
  background. These large-profile dialog latencies were not measured.
- [Batch import](../../client/src/parsetrail/core/v2_workspace.py),
  `import_files`, invokes catalog verification and store opening per file.
  Measure phase costs before proposing safely owned context/catalog reuse;
  preserve per-file transactions, completed imports on cancellation and trust
  checks. This evaluation did not benchmark batch-import throughput.
- Report date/profile cache keys do not include external profile revision.
  Internal anchor edits correctly invalidate reports through
  `_open_selected_account_review` → `_refresh_all_reports`. External-process
  mutation is a lower-priority robustness scenario, not a demonstrated normal
  modal-workflow regression.

### Commands and UI evidence

Focused verification used the existing `client/tests/conftest.py` disposable
profile/home and null-keyring isolation:

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_review_read_performance.py client/tests/test_v2_reports_responsiveness.py client/tests/test_v2_transfer_history_performance.py -q
```

Result: **38 passed in 36.27 s**. These verify existing read/transfer/report
behavior; proposed changes have not been implemented or tested.

The reviewer timing harness is retained locally at
`scratch/v2_perf_evaluation_20261101.py` (ignored, synthetic only). It sets isolated
HOME/USERPROFILE/APPDATA/LOCALAPPDATA and null keyring before imports, constructs
source evidence from the public synthetic cash definition, imports/binds into
a new profile and measures the same selected document at 1/64/256/946 sources.
Run with the existing locked client Python. It is an investigation aid, not a
committed performance test or application feature.

Inspected offscreen Qt renders are retained locally under
`scratch/v2-ux-evaluation-2026-11-01/ux-review/`:

- Workspace: `documents-font.png`, `review-font.png`, `accounts-font.png`,
  `report-launcher-font.png`, `first-use-font.png`.
- Existing reports: `reports-loaded-font.png`, `positions-loaded-font.png`.
- Review: `cash-font.png`, `card-font.png`, `coverage-1100x650-font.png`,
  `loan-1100x650-font.png`, `settlement-1100x650-font.png`.

The UI/UX reviewer loaded system Segoe UI at 10 pt to avoid sandbox font fallback
failure. Initial missing-glyph screenshots and their sizing conclusions were
discarded. The primary independently inspected the first-use, Review, cash,
coverage, loan, reports and positions renders and reconciled them with code.
These screenshots are disposable local evidence and are not tracked artifacts.

The Windows computer-use helper did not enumerate the sandbox-launched app
windows, although the processes reported their expected synthetic window title.
Native click-through was therefore not verified; launched inspection processes
were stopped. No existing owner profile was opened. No private archive was used.

### Acceptance criteria for subsequent implementation

These are proposed engineering targets, not results achieved by this review:

- A fresh reviewer can find the document/account/period, identify remaining work,
  inspect an original, review a supported row and find its report without
  control-by-control instructions. Task time/error rate should be recorded
  before and after changes with the same mixed synthetic scenario.
- Compare 50 ordinary rows including expenses, refunds, income, already-reviewed
  payments, unsupported movements and repeat blockers. Demonstrate less repetitive
  interaction while preserving explicit purpose, category and confirmation.
  Include stale batch, cancelled preview and correction/withdrawal paths.
- Render a useful shell/loading state within 100 ms; target UI event-loop
  stalls below 100 ms and warm local filter/selection feedback below 100 ms at
  the 946-source/18,920-row workload. Track p50/p95 over repeated runs rather
  than treating this three-run baseline as a percentile benchmark. Separate
  background completion latency from input responsiveness.
- For the selected 20-row review, target warm snapshot completion below 250 ms
  on this same environment after query scoping; explain any integrity-driven
  remaining cost. Add posted histories, corrections, large retained originals
  and mixed concurrent reads to the benchmark before declaring archive readiness.
- Cancellation/close/profile change must prevent late results from appearing in
  another scope, keep committed work truthful, and release worker-owned resources.
  Measure cancellation latency and peak memory; neither was measured here.
- At 1100×650, retain account identity, financial effect, blocker and next action;
  verify long labels, empty/loading/failure/retry/correction states, keyboard
  focus/return, accessible names and native 100/125/150% scaling. Test Windows
  Narrator and Intel macOS separately before making accessibility/platform claims.
- Exact-money, separate-date, active-allocation, repeat, immutable-source,
  unknown-opening, correction and atomicity regressions remain required.

## Remaining work

Evaluation and proposals are complete. No implementation packet was selected,
application code changed, profile activated, release performed or owner
acceptance inferred. This record can guide a separately selected improvement
packet under V2-UX without reopening completed transfer work.

Limits: synthetic unposted archive timings do not establish private-profile,
posted-history, cold-disk, large-PDF, native interaction, accessibility, installed
Windows or Intel macOS performance. This was not a complete financial/security
audit. Native usability and actual owner acceptance remain separate from the
agent design review and existing automated checks.

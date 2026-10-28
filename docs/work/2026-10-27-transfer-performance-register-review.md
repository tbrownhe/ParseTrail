# Responsive transfer review, unique-match posting and register repayment routes

Date: 2026-10-27 start. Baseline: 90166f8, clean feature/client-financial-insights.
Scope: reported transfer opening/gap/post latency; explicitly confirmed batch of
matches without competing matches; Yamaha repayment/category workflow confusion.
Completed: 2026-10-28 in development; verified public runtime handoff prepared.
Automated verification: 249 integrated tests passed in 272.75s.
Native/design verification: actual Windows transfer, batch, repayment and category flows passed.
Independent review: financial/cache/index/atomicity/lifecycle checks passed; no material blocker.
Owner acceptance: requested work not yet reviewed. Release authorization: none.

## Decisions and ownership

Transfer dialog construction must yield immediately. Reads and mutations use
worker-owned connections, coalesced date-gap requests and latest-generation
publication. Selection/note updates must not rebuild financial snapshots. Optimize
operation-scoped verified evidence/history reuse without a persistent trust cache
or weakening ordinary posting/correction/source validation.

Review all unique matches shows a final manifest: exact accounts, both posting
dates and their qualifications, amounts, types, current date window/preferences
and excluded ambiguity/blocked counts. Uniqueness means degree one at both legs
among the full current candidate graph, including date-disabled competitors.
One explicit final confirmation posts all eligible pairs atomically after fresh
basis/profile/preferences/graph validation under the write lock. No partial batch,
automatic truth certification, inferred splits, invented entries or preference
changes. Cancellation must distinguish committed outcome from rollback.

Yamaha's current admitted source is a whole-liability register. A repayment is
reviewed with its paying-account counterpart, not forced into income/refund or a
new expense category. Provide a prominent route and selected-row focus in the
transfer review. Other positive credits retain explicit income/refund choices.
No principal/interest split is inferred from source description or amount; ordinary
interest charges retain their explicit expense/category review. The purpose route
itself must not post, allocate or change persisted financial policy.

An adjacent category-management action opens the existing category dialog, with
the needed class suggested where known. Return refreshes current category/basis
and preserves selected row, purpose, accounting date and review reason. Select a
new compatible category without posting. Existing built-in identity and correction
class/date locks remain intact.

Ledger owns store/transfer batch core plus focused headless tests. Desktop owns
transfer dialog/workers/batch confirmation and relevant GUI tests. Primary owns
card/register repayment/category interaction, its tests, contracts/planning,
integration/commits and same-profile public runtime handoff. ui_ux designed before
implementation and will inspect actual UI; integrity independently reviews graph,
atomicity, validation reuse, financial meaning and actual lifecycle paths.

Use public synthetic/disposable profiles, exact-money fixtures and archive-sized
synthetic benchmarks only. No private source/profile inspection or posting to the
owner demo. Public runtime handoff may read its schema marker only; preserve the
same saved profile/catalog/preferences/home and earlier bundles. No schema,
service, signing, release or daily-profile activation is selected.

## Criteria and verification

- Measure initial shell/event responsiveness, candidate-read and confirmed-post
  time separately. Gap changes coalesce, failures clear old actionable state and
  cancelled/superseded workers cannot publish old candidates.
- Pair, bulk, dismiss/reopen, withdrawal/replacement and settlement history remain
  correct. Batch competitors on either leg are excluded; exact source dates,
  clearing, assumptions, overlapping evidence, closed scopes and consumption remain
  guarded. Stale/corrupt/failed/cancelled transactions leave no partial journal.
- Native Qt checks cover loading/error/empty/long manifest, keyboard access,
  selected Yamaha repayment route and missing counterpart, explicit other credit,
  interest category creation/cancel, retained form edits and zero implicit postings.
- Focused/integrated tests and independent review distinguish synthetic/native
  agent evidence from owner, Intel, installed/release acceptance.

Transfer reads/posting now use an operation-scoped context that streams and
verifies each original/definition/evidence/inventory once, retains only immutable
parsed evidence during its owning transaction, and unconditionally clears it.
Bindings, current journal/history, consumption, preferences and lifecycle remain
authoritative. Candidate graph/overlap index work is reused instead of rebuilding
it for each leg or batch pair. No schema, source rewrite or persistent trust cache.

The new `v2_transfer_batch` typed plan captures full current graph scope, basis,
profile identity, preferences and date window. Every selected pair has degree one
on both legs; date-disabled competitors still exclude a pair. Persisted suggestion
decisions and source-overlap blocks retain their existing eligibility rules. Final
Apply revalidates under BEGIN IMMEDIATE, inserts every dated event/allocation in
one transaction and validates history before commit. Cancellation/failure/stale
plans roll back completely; exact retries report already-posted events. Ordinary
confirmed writes drain to a known saved outcome on Close; only batch Close offers
cooperative precommit cancellation. UI wording distinguishes this from undo.

`NearbySourceIndex` retains its complete neighbor/pair/count API and exact order.
Its lazy iterator uses global date-window bisects and precomputed contiguous
same-source run ends. Boolean posting guards stop at the first unresolved edge,
without materializing millions of irrelevant neighbors or scanning every source
in sparse histories. Intermediate eager-merge and source-loop regressions were
found by desktop/integrity probes and replaced; dense and sparse cases both pass.
An overlap-refusal message regression was also corrected using the same candidate
read's blocker map, preserving public error priority without another archive pass.

The dialog opens immediately, debounces gap edits by 150ms, clears superseded
posting state, and loads/saves through retained worker-owned connections. Candidate,
note, history and combo selection use cached facts. Replacement candidates load
only on deliberate request. Batch review lists every selected pair, both account
identities and qualified dates, current policy/window and ambiguity/exclusion
counts, with Cancel as the default and one explicit final post button. Confirmation
context is frozen before nested Qt modal questions, including ordinary actions.

Register navigation recognizes a supported printed payment as a suggested route
only while eligible; other positive credits retain explicit alternatives. Wrong
kind/scope/missing assignment remain visible and blocked. Actual repayments focus
the selected row's counterpart/history and stay pending without receipt evidence.
Category management reuses the existing dialog, preserves row/purpose/date/reason,
refreshes basis/categories and selects only a newly created compatible category.
Creation and navigation post nothing. Completed external interpretations display
Reviewed elsewhere with categorization disabled and an actual history route;
this is based on validated posting state, not inferred financial purpose.

Verification uses locked client Python, isolated homes/null keyring, public
synthetic fixtures and disposable profiles:

- Integrated transfers/batch/async/history/corrections, occurrence matching/index,
  settlements/cash integration, Yamaha/core/register GUI/category routes, card,
  loan payments and workspace: **249 passed in 272.75s**. Initial run found two
  existing overlap error-priority failures (financial refusal still occurred);
  fixed and reran the complete relevant matrix successfully. Focused register/
  category/card run: 26 passed; transfer GUI: 26 passed. Lint/format checked.
- Same public dense profile, 42 sources / 10,001 cash rows / 13.4 MB DB:
  native load **7.509s→0.491s**, post plus reload **15.250s→0.939s**. Cold shell
  0.120s, warm shell 2.30ms; 100 actual clicks median 0.198ms/max 9.28ms and
  zero DB opens; four gap dispatches ≤0.340ms, latest gap load 0.550s, post
  dispatch 0.342ms. A 10ms UI timer's maximum interval was 83ms including modal
  screenshot work. Evidence: `scratch/transfer-performance-20261028/native-final3-after.json`.
- Independent source-equivalence benchmark: **8.144s/168 source verifications →
  0.447s/42**, exact candidate/history/basis equality and unchanged profile bytes.
  Python heap peak 75,145,644 bytes (not total RSS). Parsed-evidence memory scales
  with operation size; this is not a constant-memory archive claim. Evidence:
  `scratch/transfer-equivalence-erlyf3zg/result.json`.
- Actual native three-pair manifest/confirmation saved three events and six
  source allocations in 0.101s including reload. Separate real two-pair and
  ambiguous-three-candidate fixtures posted exactly the isolated pairs; Escape/
  Cancel left exact profile hashes unchanged and remaining competitors pending.
  Evidence: `scratch/transfer-performance-20261028/batch-native/` and
  `scratch/transfer-integration-ux-a7e9e5c7/`.
- Independent integrity tested actual disabled-date competitor exclusion,
  stale graph/profile/preferences and withdrawal/retry behavior; cancellation
  after the first event SQL insert and injected failures restore exact DB hashes
  with no partial event/journal/allocation/clearing. Nine real subprocess cases
  cover read cancellation, confirmed ordinary-write drainage and batch rollback
  under app quit, forced destruction and no-event-loop exit, all exit 0. Later
  corruption on the same store is refused after cache clearing. Evidence:
  `scratch/ux-audit-transfer-performance-20261028/`. Final seeded mixed-row index
  parity and sparse 3,000-source case preserve edges/order while reducing
  1.0118s→0.0027165s; final eight index/modal regressions passed.
- Native ui_ux inspected 1024/1250 main and 1000x650 manifest states, both date
  qualifications, batch exclusion/scope, missing counterpart, actual repayment
  post/return/history, category Cancel/custom/built-in and retained drafts. Full
  internal account identity remains in selected context/tooltip; descriptions
  are readable at 1024. Whole-liability repayment created zero expense/income,
  no principal-component history and exact 2,000-minor clearing between February
  8/10 source dates, then zero. Final return/history evidence:
  `scratch/transfer-integration-ux-81da52ab/`; category/layout evidence:
  `scratch/register-routes-ux-c362ecab/`. The public charge fixture validates
  category interaction, not a claim its parser printed an interest classification.

No private owner statements/profile content were inspected and no live posting,
release, signing or owner acceptance was performed. Windows native/synthetic
evidence does not establish Intel/macOS, installed-release, DPI or screen-reader
acceptance.

Prepared a new immutable public runtime:
`scratch/archive-demo-f92c025/runtime-updates/20261028-transfer-register-review/Open-updated-demo.cmd`.
It copies 284 public code/resource files and reads only the existing demo's schema
marker (22), keeping the same profile/catalog/preferences/home and earlier bundles.
The owner launcher was not executed. A separate disposable pinned-module journey
used the real final-confirmation button to post one isolated pair and leave two
competing suggestions pending; it also verified selected Yamaha repayment
navigation without posting, category creation with retained edits/no journal,
and completed repayment history state. Evidence:
`scratch/transfer-pinned-check-0bd13fd5/result.json`. Pinned-source verification is
recorded beside the launcher after the implementation commit.

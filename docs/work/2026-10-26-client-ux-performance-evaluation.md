# Make the V2 foundation understandable and responsive

Date: 2026-10-26. Roadmap IDs: V2-UX, V2-3/4/5/6/7.
Branch/components: feature/client-financial-insights; current desktop source.
Authorization: evaluation requested, followed by explicit authorization to proceed at will; Normal/Advanced modes are optional, not a requirement.
Implementation: complete for the authorized integrated refinement.
Automated verification: focused source/read/UI/lifecycle and demo integration passed; broader V2 selection passed all product checks, with its single outdated synchronous assertion adapted and verified in the final focused rerun.
Design verification: independent preimplementation screen/state review and actual integrated Qt inspection; Windows native display-suppressed and offscreen synthetic renderings.
Independent review: financial/evidence/read-snapshot and asynchronous lifecycle review passed after findings were corrected; independent synthetic user journey passed.
Owner acceptance: not performed for this implementation; earlier functional walkthrough remains separate.
Release authorization: not authorized; no release actions performed.

## Scope and controlling decisions

Evaluate the active V2 workspace, rather than the independent 1.x UI. Preserve
exact money, typed dates, immutable evidence, append-only reviewed history,
unknown balances and ordinary local-only processing. The owner's aim is versatile,
accurate open-source accounting for people with mixed financial knowledge.
Usability is therefore part of correctness: people must understand which account,
period and reviewed activity a number describes.

Primary owns this record and index/planning links. Read-only specialists:
ui_ux owns interaction critique; desktop owns performance investigation; integrity
owns review of safe simplification. No recursive delegation or application edits.
Only new public synthetic disposable profiles and public code/contracts were
used. No existing private pilot, statements, credentials, root .env, 1.x state,
production services or daily profile were inspected or changed.

The existing archive-read optimization is completed evidence, not a new finding:
[prior performance record](2026-10-26-v2-review-performance.md) measured cash review
12.44s to 1.26s and coverage 24.45s to 1.30s on its authorized 946-source copy.
Those are historical warm Windows measurements, not new cold-start benchmarks.

## Findings and proposed fixes

### P1: documents and next actions are hard to recognize

`v2_workspace_window.py:332` lists only truncated source digests; selected details
at line 368 show parser ID and row count. Fifteen buttons at lines 253-299 compete
with specialized menu routes. The actual 1050x560 rendering confirms a sparse hash
inventory above two dense action rows, without account/period labels or a useful
selected-document next step. Import completion selects the last imported source
and announces pending review (lines 662-675); batch results provide only Close
(`v2_batch_import.py:47`).

Propose a recognizable document list: institution/account ending, printed period
or explicitly labeled activity span, friendly import label/filename when retained,
and outstanding work. Keep digest and parser versions in Details. Do not infer
missing filenames or periods; a saved display label may require a separately
designed metadata addition rather than changing immutable evidence.

Use persistent Documents, Review, Accounts and Reports navigation. Each selected
document has one contextual next action. Import completion offers Review imported
documents. Suggested progression: confirm account, review activity, check statement.
These are available tasks, not a blanket prerequisite chain: missing openings or
capture review need not prevent otherwise supported expense review.

### P1: completion states disagree between screens

`v2_source_account_review.py:172` labels a resolved candidate Automatic match and
line 199 excludes it from unassigned totals. `V2Workspace.account_bindings`
computes those candidates at read time, while `V2ProfileStore.account_bindings`
at line 7344 returns saved explicit assignments. Ordinary cash review uses the
latter at line 3571 and can report Assign a financial account first (line 3623).
Independent synthetic reproduction confirmed the mismatch in actual offscreen
Qt: the assignment screen showed 0 of 1 source identities unassigned and
Automatic match: Card A, while card review showed Assign a financial account
first, no account and disabled posting. Explicit Assign selected identity
resolved the binding. It undermines confidence before any redesign.

Use one shared completion model. Show Suggested account until the required saved
association exists; preselect the candidate and offer Use this account. Verify
unique full numbers, unique eligible suffixes, ambiguous suffixes and unavailable
catalogs. Preserve explicit confirmation and source-specific assignment history.

### P1: report scope and financial meaning take too much effort to read

Reports puts date controls above all tabs although budgets and positions use
different dates (`v2_reviewed_reports.py:368-406`). Cash movement has three kinds
of selection: checked report accounts, source preview and inspect-account target
(`v2_cash_movement.py:86-137`). The prior account-list visibility repair helps
discoverability but leaves that conceptual distinction.

Move date/account controls into the applicable report header. Show selected
account count and exact period beside totals. A friendly inclusive date picker
can translate explicitly to the existing half-open service range. Keep whole-
profile pending counts labeled as such instead of implying they belong to the
visible account/period. Preserve reviewed-only and materially incomplete scope
beside affected totals; expand the full explanation on demand.

Account positions exposes 14 columns with about 2,040px of configured widths
(`v2_reviewed_reports.py:204-226,542`). The actual 1180x780 screen shows about two
accounts above a long details block and history table. Default to account,
supported book position or Unknown, as-of date and next action. A selected-account
panel retains recorded journal movement, opening status, dated source values,
pending activity and separate live/saved reconciliation. Never substitute a
journal sum or source closing value for a supported account balance.

### P1/P2: ordinary review has high repeated interaction cost

Cash review requires one row, purpose, category, a typed reason and confirmation
(`v2_cash_activity_review.py:153-218,326`). Even a three-row synthetic example
leads with a paragraph describing numerous exceptional account shapes. There is
no common inbox that presents missing binding, ordinary classification, repeat
review and special transfer/loan work as understandable tasks.

Use one Review inbox grouped/filterable by account, document and actionable
state. Expose only relevant controls for the selected item, and carry context
between review and source inspection. Use a truthful standard action record with
optional note for ordinary confirmations; retain substantive reasons for changes,
withdrawals and exceptional assertions. This changes authored review behavior
and needs service/contract review, not just hiding a required field.

Later add homogeneous multi-row confirmation with an exact effect preview and
per-row eligibility/staleness checks. Define atomic versus partial completion,
failure and cancellation before implementing; do not loop the single-row UI and
claim safe batch semantics. Category/purpose suggestions remain suggestions.

### P2: recovery, terminology and accessibility need a coherent pass

Replace Assert entire file, Withdraw active interpretation and raw diagnostic
codes in ordinary flows with Assign all rows to this account, Undo this reviewed
entry and an explanation plus recovery action. Retain copyable codes/details.
Import failures should explain what remains saved and offer retry for appropriate
failed/unattempted files; unsupported formats/catalogs need specific remedies.
Do not imply a UI change adds unsupported parser/accounting capability.

Use consistent headings, spacing, status wording, focus return and primary action
placement. Show concise material warnings with expanded technical details;
different evidence dimensions must remain individually inspectable. Add keyboard
shortcuts and accessible names where Qt's defaults are insufficient. Sparse
explicit accessibility annotations are a verification gap, not proof that native
screen readers fail. Check actual Windows/Intel behavior and scaling separately.

## Normal and advanced operation

Recommend a guided default with Show details first; a remembered Detailed workspace
can expose more panels/columns later. Both use the same evidence, accounts,
decisions, ledger, correction history and report services. Switching presentation
must not write financial decisions or toggle risk preferences.

| Choice | Guided/default behavior | Boundary in every presentation |
| --- | --- | --- |
| Recognize an account | Preselect an eligible candidate and ask Use this account | Ambiguous identity requires review; suggestion is not completed binding |
| Remember prior associations | Suggest a scoped previous association for confirmation | Cross-source reuse is new authored policy; current bindings are source scoped |
| Routine purchase/income | Plain purpose/category choice, understandable effect preview | Amount sign alone cannot establish purpose; posting requires confirmation |
| Source review | Prefill immutable facts/reference and put relevant source context nearby | Never record that a person checked a source merely because parsing succeeded |
| Missing opening | Offer a supported candidate or I don't know yet | Unknown is not zero; no balancing plugs or inferred payment |
| Possible repeat | Ask whether examples represent one transaction or separate purchases | No silent deletion/merging from date/amount similarity |
| Transfer/card/loan | Suggest likely related movements; expose focused detailed review when needed | Preserve dates, allocation, unresolved clearing and supported principal/interest |
| Assumed dates/suffix matching | Explain and scope separately from the display mode | Both current preferences default off; mode change must not silently enable them |
| Reports | Concise account/date/reviewed scope and relevant uncertainty | Imported evidence does not become posted money or certified bank balance |

Normal mode can reduce navigation, repeated typing and irrelevant detail. Any
proposal to change accounting/evidence assumptions must identify its specific
rule, saved scope, visible consequence, correction path and verification. A mode
name is not authority to weaken provenance or financial safeguards.

## Performance assessment and proposals

The report constructor eagerly reads spending, income, movement, budgets and
positions before showing its first tab (`v2_reviewed_reports.py:459-461`);
date changes synchronously recompute multiple reports (`:437-438,728`).
Cash report checkbox changes call synchronous refresh (`v2_cash_movement.py:146`).
Selecting documents and rebuilding the workspace triggers saved-evidence/overlap
reads on the GUI thread (`v2_workspace_window.py:307-342,348-377`). The import
worker already runs parsing off-thread; extend responsiveness to reads rather
than claiming all work is currently synchronous.

Remaining account-position reads still call account_bindings and load_import per
source (`v2_profile_store.py:5838`), alongside reconciliation reads. Store opens
also perform repeated format/integrity checks. Preserve checks and corruption
refusal while measuring redundant work; do not simply disable validation.

Independent measurements on a newly constructed valid synthetic archive found:

| Operation | 500 sources / 25,000 rows / 80.5MB database |
| --- | --- |
| Actual Reports dialog construction | 6.842s, 1,500 verified source loads |
| Actual Coverage dialog construction | 0.803s, 500 verified source loads |
| Read-only store open | 0.110s |
| Reports on a separate disposable copy with only a source index added | 1.915s |

Each synthetic source contains 50 activity rows and 100KB source bytes, totaling
50MB embedded originals; accounts are unbound and no posted history is present.
This measures valid constructed immutable snapshots, not parser replay, a real
archive or a cold/installed performance distribution. Original generated-profile
hashes were unchanged. EXPLAIN QUERY PLAN confirmed SCAN SourceObservations for
single-source inventory lookup; the disposable-copy experiment adding
`SourceObservations(source_sha256)` changed it to indexed SEARCH. This supports
a targeted index plus one-pass read optimization; it does not establish that
indexing alone meets the proposed latency targets. A production index requires
the applicable profile-format/lifecycle decision and equivalence/corruption checks.

Proposed order:

1. Instrument open/select/refresh/review actions and GUI event-loop stalls using
   synthetic profiles of increasing source count and evidence size. Include
   bound accounts, posted history, overlaps and embedded-PDF-sized data.
2. Show the workspace/report shell immediately; load only the selected view in
   a read worker with its own read-only connection and consistent snapshot.
3. Coalesce date/account edits, cancel/discard obsolete requests and apply only
   results matching the current profile, scope and read generation. Clear or
   visibly mark outdated/error totals; do not leave an apparently current value.
4. Add the measured missing source-inventory index under the profile lifecycle
   contract. Share verified data within one read operation/snapshot; extend the prior
   one-pass approach to positions and common report summaries where equivalent.
   Keep corruption detection, review bases and concurrent-write consistency.
   Separately profile substantially posted books: `_journal_entries_in_period`
   currently deserializes all journals before filtering (`v2_profile_store.py:5658`),
   which this unposted synthetic archive does not measure.
5. Use model-based bounded visible tables and focused invalidation instead of
   full widget/list rebuilds and content-size scans for large inventories.
   Introduce persistent projections/caches only if profiling still justifies
   them, with explicit freshness/integrity design. No evidence JSON rewrite,
   second authoritative store or broad persistence redesign is justified.

Suggested engineering targets, to calibrate on declared reference hardware:
primary feedback within 100ms; first usable shell within 300ms; no sustained GUI
stall over 100ms; common warmed selected-view reads within 1s for a 1,000-document synthetic
archive, and a visible cancellable loading state for slower operations. Record
cold/warm median and p95, profile bytes/row counts and peak memory. These are
proposed targets, not achieved performance claims or universal platform limits.

## Delivery sequence and acceptance criteria

1. **Recognizable documents and truthful status:** shared completion state,
   document summaries, contextual next action and import-to-review handoff.
2. **Responsive reads:** measured positions/report paths, worker loading,
   selected-tab reads, coalescing and snapshot-safe reuse. Can proceed alongside
   design once read-model ownership and UI contracts are agreed.
3. **Guided daily workflow:** persistent navigation, review inbox, relevant
   purpose/account forms, account overview and report-specific scope.
4. **Efficient repetition and polish:** separately designed batch confirmation,
   optional routine notes, recovery, keyboard/screen-reader/scaling verification.

A fresh reviewer should find a named statement, confirm its account, review a
purchase and locate its report/source without control-by-control instructions.
After import/change/failure, the saved outcome and next action are clear. Missing
openings remain Unknown without blocking supported spending. Same reviewed
inputs yield identical postings/reports in either presentation. Exercise refunds,
card repayments, transfers on different dates, loan splits, repeated imports,
ambiguous accounts, stale review and correction/withdrawal.

At 1024x768 and larger windows and 100/150/200% scaling, ordinary tasks and material
qualifications must remain reachable, with no horizontal scrolling required for
primary decisions. Keyboard-only import/review/confirm/evidence/back navigation
must preserve selection/focus. A passed arithmetic check never becomes a blanket
claim of complete capture/history. Prototype these screen states before widget
implementation, then inspect the actual integrated result independently.

## Evaluation verification and limits

Baseline: clean working tree at `726b899` on feature/client-financial-insights
before review.
Windows source runtime, existing locked client Python/PySide6. New preparation:
`client/.venv/Scripts/python.exe devtools/v2_review_demo/prepare_demo.py
--prepare-at scratch/ux-audit-20261026-demo` passed the helper's exact financial
checks, including six public synthetic originals, pending cash, card/loan/HSA,
unknown/zero openings and unresolved transfer clearing. It does not establish
that every seeded record was inspected interactively.

Primary read-only inspection script:
`client/.venv/Scripts/python.exe scratch/ux-audit-20261026-inspect.py`.
Qt offscreen; explicitly loaded Windows Segoe UI TTF at 10pt before inspection.
Inspected current workspace 1050x560/1366x768, cash review 1050x620, spending and
positions 1180x780, cash movement 1100x780 and coverage 1320x760. Renderings and
aggregate JSON remain in ignored `scratch/ux-audit-20261026-screens`. Initial
fontless images were rejected and replaced; their geometry/timings are not evidence.
The synthetic profile remained byte-identical across all UI reads.

In this six-source warm source run, workspace construction was 0.056s, cash
review 0.084s and all-tab Reports construction 0.845s. These are single
observations, not a benchmark distribution, archive projection or installed
platform claim. Code-based performance findings are identified separately above.
No app code changed, so a broad application test rerun was not warranted.

Independent desktop investigation used locked Python with newly generated,
isolated synthetic source/profile data under `scratch/ux-audit-performance`.
The valid larger probe and disposable-copy index experiment are retained in
`archive-_z9chsfa/measurements.json` and `index-experiment.json` there; a failed
initial fixture construction was excluded from results. Smaller 100/500-source
one-row probes independently confirmed three source reads per position source.

Independent integrity reproduction:
`client/.venv/Scripts/python.exe scratch/ux-audit-binding-integrity-20261026/reproduce.py`.
Synthetic Synchrony fixture, one matching card account, fixture-signed catalog,
explicitly enabled abbreviated matching, isolated home/appdata/preferences/catalog
and null keyring. Runtime assertions passed; read-only views retained profile
hash/zero journals, and explicit assignment resolved the inconsistency. Script,
aggregate result and actual Qt screenshots remain in that ignored directory.

Actual rendered Qt inspection is agent design evidence. Native input, screen
reader, high-DPI, Intel macOS, cold/installed builds, owner usability acceptance
and final release readiness were not established. Recommendations remain
proposed; this review does not select their full implementation or a release.

Documentation closeout: `git diff --check` passed. A local link/whitespace check
passed for all four changed Markdown files (122 local file targets). Changes are
this record, its work index, the TODO recommendation and the roadmap evidence
link. No runtime contract, application source, version or release status changed.

## Evaluation recommendation

Use the sequence above to select a bounded implementation packet, starting with
recognizable documents/truthful assignment status and responsive report loading.
No new per-feature owner approval gate is proposed. Existing owner accounting
review, supported-platform and exact-candidate release gates remain separate.

## Authorized implementation

The owner subsequently clarified that Normal/Advanced modes are not a requirement
and authorized proceeding at will. Decision: build one guided interface with
discoverable details; no mode preference or financial-policy changes.

Selected integrated scope: recognizable searchable documents and contextual
navigation; truthful suggested/confirmed account status; responsive report and
document reads; compact account positions and applicable report scope controls.
Reuse existing supported review/correction dialogs. Batch posting, new parser
capabilities, cross-source automatic policy and release actions remain outside
this implementation. This does not impose a new owner approval gate.

Ownership: primary workspace/source-assignment presentation, workspace adapter,
integration tests/docs; desktop specialist reports dialog and responsiveness tests;
ledger specialist store/read models and focused equivalence tests. ui_ux reviewed
screen/state plan before implementation and will inspect integrated screens.
Independent integrity review follows store and asynchronous integration changes.
All data remains newly generated public synthetic/disposable state.

Agreed criteria: at 1050x700 no competing action wall; search finds recognizable
account/family/period with absent metadata left unknown; contextual tasks retain
necessary confirmations; loading/error/current scope are explicit; reports show
only applicable dates; positions readable without primary horizontal scrolling;
full history/provenance remains reachable; latest asynchronous request wins;
profile changes/close cannot apply stale results. Verify actual Qt, focused and
relevant integration checks, exact accounting equivalence and corruption refusal.

## Implemented result

- One guided workspace, with Documents, Review, Accounts and Reports navigation;
  no Normal/Advanced switch or automatic policy change.
- Searchable document inventory with saved account/source labels, known periods
  or activity spans and explicit estimated/derived dates. Missing filenames are
  not invented. The primary action opens account confirmation or supported
  activity review; supporting and specialized actions remain contextual.
- Account setup now lists configured accounts. Suggested matches are preselected
  but remain unassigned until Use this account saves the explicit association.
  Empty statements with printed account sections still need confirmation, and
  mixed/accountless exports preserve row/file assignment rules.
- Material source-period overlap warnings remain visible, with recognizable
  related document labels and full digests in copyable, scrollable details.
  Conservative unallocated counts visibly qualify supporting repeats instead
  of claiming that every unallocated source row needs another posting.
- Document inventories and selected report views read in worker-owned read-only
  connections. Refresh requests coalesce, older profile/scope results cannot
  publish, read errors clear affected choices/totals and retry remains available.
- Period dates are shown only for applicable report tabs. Compact positions
  retain asset/liability class, supported opening-based position or Unknown,
  opening state, pending rows and tracking scope. Full evidence columns/details
  and account history remain expandable; account-list space is reclaimed.
- Cash/card review starts with a short task-specific introduction and expandable
  detailed rules. HSA component limits, overlap and date warnings remain visible;
  both ordinary cash/card review can open saved source evidence directly.
- Account positions collects pending evidence during reconciliation's existing
  validated source pass. There is no schema/index/evidence-format change; schema
  22 and existing source/pilot compatibility are preserved.

Main write set: `core/v2_profile_store.py`; GUI `v2_document_browser.py`,
`v2_workspace_window.py`, `v2_reviewed_reports.py`, `v2_source_account_review.py`,
`v2_cash_activity_review.py` and `v2_card_purchase_review.py`; focused new tests
and existing GUI integration tests adapted to actual asynchronous reads;
`devtools/v2_review_demo` guidance/smoke lifecycle; client/store documentation and
planning/index links. No backend/dashboard/website, version, signing or daily
profile changes. The initial closeout was uncommitted; the owner subsequently
authorized cohesive commits before creating the archive-based demo.

### Performance evidence

On the same public 500-source/25,000-row, 80.5MB synthetic archive used for the
evaluation (50MB embedded originals, unbound and no posted history):

| Operation | Before | Implemented |
| --- | --- | --- |
| Account positions including store open | 6.708s / 1,500 verified source reads | 0.934s / 500 reads |
| Reports constructor/shell | 6.842s eagerly loading all reports | 0.0058s shell |
| Spending usable | Included in the blocking constructor | 0.1514s |
| Select positions, usable | Included in the blocking constructor | 0.8447s / 500 reads |
| Document summaries including store open | New read model | 0.535s |

Normalized account-position results matched exactly and fixture hashes stayed
unchanged. Unlike the earlier disposable-copy index experiment, the implemented
fix needs no index or profile-format change. These are individual warm Windows
source/offscreen measurements, not p95/cold/installed or reviewed-archive claims.
Substantially posted books still have repeated history-validation work; the
six-source seeded reviewed fixture remained equivalent at approximately 0.2s.
Evidence: ignored `scratch/ux-read-model-324t_t2f/result.json` and
`scratch/ux-audit-performance/archive-_z9chsfa/async-integrated-measurements.json`.

### Review findings resolved

Independent integrity review verified snapshot isolation, corrupted-source
refusal, explicit assignment/pending semantics, no posting during confirmation
and profile-generation rejection. Corrections from review:

- Assumed period dates are labeled estimated, independently of derived dates.
- Full overlapping-source references remain discoverable; the asynchronous
  unbinding regression waits for the actual refreshed result.
- Compact positions retains Class so positive asset values and liability amounts
  owed remain distinguishable even with identical account names.
- Compact pending qualification explicitly says whole profile and all dates.
- Real subprocess checks exposed a report-thread teardown crash (0xC0000409).
  Dialog close is nonblocking; full application/interpreter exit requests
  interruption and drains read connections. Hidden windows stop queued initial
  work even when Qt skips normal close events. Both report and document workers
  are retained independently of widget lifetime until completion. Actual app
  exit and programs that never enter app.exec are covered; no thread termination
  is used. The unchanged independent four-second reproduction now exits 0 with
  zero retained report readers.

### Integrated design and interaction verification

Primary inspected current source through both Qt offscreen and Windows Qt with
display suppressed, explicitly registered Segoe UI 10pt. Main Documents 1050x700
and 1366x768; Review/Accounts/Reports 1024x768; spending/positions 1180x780;
cash review 1050x620; card review 1200x650. Native renderings and aggregate
results: ignored `scratch/ux-refinement-20261026-native`; source helper
`scratch/ux-refinement-20261026-inspect.py --native`. The six-source synthetic
profile was byte-identical after all read-only views. This verifies actual
Windows Qt construction/rendering, not an owner-visible walkthrough.

Independent ui_ux inspected actual integrated screens and the 1024x768 positions
view with 17 long-name accounts. The layout fits without primary horizontal
scrolling; asset/liability class and scope are retained after its finding.
Independent acceptance created its own isolated synthetic profile and completed
import, explicit account confirmation, ordinary expense review, $4 spending,
Unknown opening-based position, one remaining pending row, entry drill-down and
the exact embedded source. Read-only inspection preserved the profile hash.
Keyboard focus from navigation to Import/search/source and an offscreen 150%
render were inspected. Evidence: ignored `scratch/ux-acceptance-20261026`.

### Implementation checks

All Python commands use the locked `client/.venv/Scripts/python.exe`,
`PYTHONPATH=.;client/src;client`, `QT_QPA_PLATFORM=offscreen` unless native is
explicitly stated, pytest `-p no:cacheprovider -q --tb=short`.

- Store/read equivalence and related regressions: 78 passed during development;
  final document-summary suite 22 passed, including empty statement identity,
  accountless/mixed assignments, overlaps, corruption and concurrent snapshots.
- Final combined document summaries/browser/reports responsiveness/workspace/
  source bindings/register integration: 64 passed in 126.75s.
- Ordinary cash/card/HSA/register UI checks after concise introductions and
  source preview: 32 passed in 50.69s.
- Document lifecycle suite after widget-independent worker retention: 6 passed
  in 15.79s, including actual subprocess exit with and without app.exec.
- Reports responsiveness/lifecycle suite: 9 passed, including date coalescing,
  stale profile/scope, error clearing, close and hidden/no-event-loop teardown.
- Disposable review demo plus statement-pilot integration: 17 passed in 53.37s,
  including exact financial/recovery/runtime checks and actual Windows suppressed
  entry/dialog construction. Final updated guidance/prepared-runtime recheck:
  `devtools/v2_review_demo/test_final_review_demo.py`, 4 passed in 21.83s.
- Broader `client/tests -k v2`: 1,018 passed, 3 skipped, 1,157 deselected in
  1109.15s, with one failing old immediate-refresh assertion in
  `test_failed_refresh_after_staging_selection_rolls_back_workspace_and_visible_source`.
  Its existing financial/profile/selection assertions were preserved and made
  to await the asynchronous inventory. Final `test_v2_profile_startup.py` plus
  `test_v2_document_browser.py`: 27 passed in 26.57s. No application fix was needed
  for that timing assertion; a redundant whole-suite rerun was not performed.
- Independent focused selection: 17 passed in 26.37s; independent financial/
  integrity and shutdown reproductions passed after the recorded fixes.
- Ruff check and format checks passed across all changed Python files; local
  links/whitespace passed in six changed Markdown files (160 local file targets).
  Final whitespace and Python formatting checks passed.

No private profiles/statements, production data, credentials or root .env were
accessed. Native screen-reader, installed/Intel macOS behavior, native high-DPI,
cold-start/p95 and owner usability acceptance remain unverified. Explicit workbook
export and some specialized review dialogs retain synchronous reads. These are
limits of this packet, not newly completed platform/release gates.

### Reviewable synthetic runtime

A fresh fixture-signed, pinned disposable example is prepared at
`scratch/ux-refinement-20261026-review/Open-review-demo.cmd`. It uses current
public source and synthetic schema-22 financial data, with separate home,
preferences and catalog. The walkthrough now identifies documents by account
and period, with diagnostic digests in details. Actual Windows display-suppressed
startup passed with the prepared profile unchanged. Existing owner pilots and
their pinned runtimes were not replaced or activated.
All 274 copied client runtime files matched current source hashes; the helper's
separate pinned bootstrap and complete runtime manifest retain their own hashes.

### Follow-up scope

Keep a single interface. Remaining worthwhile work is efficient multi-row review,
optional routine notes with reviewed service semantics, more focused specialized
dialogs, source-page presentation, substantially posted-history profiling and
model-based large cash tables. These remain bounded future work; financial
assumptions cannot change merely as presentation preferences. Existing owner
accounting review, native/platform and exact-candidate release gates remain
separate. No new per-feature human approval gate was introduced.

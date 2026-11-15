# Core desktop journey: imported evidence to reviewed spending

Date: 2026-11-07. Roadmap: V2-UX, V2-3/4/5/6.
Branch: `feature/client-financial-insights`; client only.
Authorization: user requested integrated journey implementation and verification;
synthetic disposable profiles/statements only. No live profiles, private archives,
production, signing, publication or release actions.
Implementation: first-use refinements implemented: independent shared/correction reasons, connected Budget navigation/editing, retained month/return context, category Add/Edit modes and concise task/detail presentation. Earlier queued PDF callbacks, explicit lifetime cleanup and account-first/staged review improvements remain.
Automated verification: the November 14 PDF-loading fail-fast is diagnosed and corrected; the historical 35-test native order and expanded 57-test native sequence pass in one process. The unchanged archived reproducer also now passes all four cycles against current application code in each of offscreen and native Windows runs, with normal GC and clean process exits. Targeted GUI disposal/handoff checks also pass. General long-session heap/thread correctness and the original earlier heap-corrupting operation remain unestablished.
Design verification: actual Windows Qt rendering/software-event checks passed.
Independent review: native captures/symbol matching and focus changes were reviewed; later raw-stack review independently confirmed worker-thread GUI destruction. Earlier bounded passing checks remain valid but do not close this additional lifetime concern.
Owner acceptance: walkthrough feedback recorded; integrated acceptance remains pending. Release authorization: not requested.

## November 14: implement first-use clarity refinements

Owner authorized addressing all six findings from the first-use investigation:
shared-reason scope, budget-month continuity, category task separation, connected
budget setup/results, primary-action hierarchy and concise diagnostic disclosure.
Implementation is complete within the reviewed Windows development scope. No accounting/schema/parser-policy changes were made.
Only fresh synthetic disposable profiles and fixture catalogs are permitted; prior
owner/demo/live profiles, private archives, root `.env`, production and release
artifacts remain outside scope. Existing uncommitted investigation notes remain.

ui_ux established the integrated model before assignments: Documents / Review /
Accounts / Budget / Reports, with Budget and Reports sharing one report instance.
Document handoffs seed period and budget month; ordinary navigation retains choices,
and source corrections return to the exact originating destination. Selected-row
type/category/date and a distinct shared batch reason have separate ownership from
saved-row correction reasons. Category Add mode is separate from selected-category
editing. Required choices, unknown/estimated dates, active blockers, confirmation
effects and report limitations remain visible; utilities/IDs/proof are secondary.

Write ownership: primary workspace/reports/shared initial-focus helper, integrated
journey tests/docs; desktop `screen_inventory` ordinary review/adapters/navigation
and its disjoint tests; desktop `category_evidence_refinement` category/import/
evidence/account forms and its disjoint tests. ui_ux owns design and actual-render
recheck; fresh acceptance and independent integrity review follow integration.
No specialist delegates or commits. Native focus slots are serialized.

Observable criteria: no unrelated Add error after category/budget save; batch reason
persists across selection/filter/correction, with all/hidden staged scope explicit;
refused/cancelled stages preserve captured reason/proposals; saved correction never
changes batch reason; October handoff reaches October budget in a November session;
budget edit opens matching month/category and refreshes result without losing review
drafts; repeat/assumed-date/account blockers remain discoverable; original evidence
and exact posting/provenance details remain available; practical 1050×700 and
1280×800 views have readable controls, clear next actions and keyboard focus.
Functional/scripted checks, design review, fresh goal-derived agent evidence and
actual human/platform/release gates remain distinct.

### Result and finding disposition

| Original finding | Implemented result |
| --- | --- |
| Shared note unexpectedly changes earlier rows | A dedicated Review set reason persists across selection/filter/category setup and is distinct from the selected saved row's correction reason. All/hidden staged scope and captured-versus-edited reason are explicit. Confirmation shows the captured common reason once. Successful staging retains the same headless shared-reason policy; refused/cancelled operations retain prior proposals. |
| Document month lost at Budget | Explicit document handoffs seed both report period and budget month. Ordinary navigation retains the chosen month/dates/non-budget tab. Multi-month context identifies the month shown; unknown dates do not become invented source dates. Source correction returns to the exact origin, including across different source periods. |
| Category success appears invalid | Existing category/budget editing opens separately from Add, with no unrelated red new-name error. Add is explicit, starts on name, clears stale success text and preserves existing budget drafts; empty profiles lead with a compact first-category form. Stable identity, rename/removal/history are secondary. Income categories explain their exclusion from expense budgets. |
| Budget setup/result disconnected | Visible Budget destination and Reports share a single report instance. The selected category/month opens directly in the existing editor; saved budgets refresh that result and keep context. Accounts leads with ordinary account management and optionally exposes balances/history. |
| Routine decisions compete with utilities | Review shell is compact; selected-row type/category/date, the Review set and source access lead. Statement/review/report utilities use named menus. Catalog management/profile path move to menus after setup; the missing-catalog prerequisite remains visible. Opening focus can target the empty-state import/install decision using the window-owned policy. |
| Technical text dominates | Import instructions follow the current step; evidence leads with account/date/source facts and capture limits. Report/drilldown headings show period/effect/reason and nearby pending/coverage limits. Parser/hash/IDs/exact postings remain discoverable through details. Human-readable scope labels replace enum spellings in confirmations. Getting started and current client documentation match the journey. |

Integrated review found and resolved two additional recovery failures within scope:

- **Confirmed async source-landing bug:** a pending refresh restored an empty
  selection after report navigation revealed the exact row. A gated regression
  first failed with zero selected rows. Explicit navigation now replaces only that
  pending selection restoration, preserving unrelated drafts/proposals. The
  regression passes, and fresh-process native recheck automatically selects the
  correct row with correction fields enabled.
- **Independent cross-source return finding:** returning from another source's
  month reseeded the existing Budget and report dates. The integrity reproduction
  changed October to September before the fix. Explicit Back now bypasses seeding;
  its regression and independent reproduction preserve month/dates/report instance.

Other resolved integration findings: insufficient table height with retained staged
work plus correction (now four complete cash rows at 1050×700); an unretained hidden
Reload callback (now a named owner slot); export control reappearing outside its
menu; stale Add success text; and default report-drilldown diagnostic density.
Correction confirmations retain the existing Yes/No dialog API with human-readable
scope and explicit effects in the question. No change to confirmation ownership or
financial policy was introduced.

Application writes span the workspace/reports/drilldown/help/focus helper, ordinary
review/adapters/navigation, category/evidence/import/account forms. New focused
regressions are `test_v2_first_use_budget_workflow.py` and
`test_v2_first_use_category_evidence.py`; existing tests/helpers now address the
explicit batch/correction widgets, Add mode and utility menus. Primary took final
category empty-state/copy integration after its specialist finished. No core,
schema, service, signed-format policy or profile-lifecycle migration changed.

### Verification and actual UI inspection

Platform: Windows 11 AMD64 build 26300, Python 3.13.15, PySide6/Qt 6.11.2,
pytest 9.1.1, pytest-qt 4.5.0. Scripted native renders use Segoe UI 9 at 96 DPI/DPR 1;
the fresh attempt uses Segoe UI 10. All data are synthetic, home/keyring isolated,
catalog signing fixtures ephemeral and profiles disposable. Normal GC/assertions
remain; process-contained tests preserve raw child failures and shutdown outcomes.

Overlapping results, not additive unique-test totals:

- Final integrated **9 passed in 34.18s**, process exit 0: complete native journey
  at both sizes, refusal/retry, cancellation, Budget edit/refresh, month/return and
  cross-source return, empty-category first use and category keyboard/budget setup.
  Four journey child `process.json` records also retain raw return code 0.
- Final empty-category top-alignment cosmetic polish then **2 native checks passed
  in 3.65s**, exit 0, covering empty/Add and saved budget/edit; primary inspected it.
- Primary workspace/report/context/form integration **27 passed in 35.13s** before
  later targeted fixes; final month/core/report group **11 passed in 45.22s**.
- Ordinary review: final native combined retained-set/correction **2 passed in
  7.05s**, exit 0; post-navigation-fix async/source-repair **34 passed in 57.69s**;
  scope-label recheck **8 passed in 18.42s**; final exact-source regression **1 passed
  in 1.90s**. Earlier native reason/staging/card-date group **5 passed in 10.65s**.
- Category/evidence/account focused group **30 passed** offscreen; native new/evidence
  group **9 passed** and additional native states **5 passed** before primary polish.
- Independent integrity: initial **42 passed / 1 obsolete wording assertion failed**;
  corrected-assertion/cancel/stale/refusal/correction **10 passed**; final exact-row
  and cross-source regressions **2 passed**, plus the independent cross-month probe.
  No remaining actionable financial/evidence/persistence finding in reviewed scope.
- Changed-file Ruff check and format check pass for **42 Python files**, including
  the two new test modules; `git diff --check` passes. Test expectations changed for
  intentional copy/navigation/scope presentation; financial/source assertions remain.

Intermediate failures are retained accurately: the early primary 22-case run had
four old wording/navigation expectations (18 passed); they were adapted, then the
27-case group passed. The ordinary broad command had **113 passed / 7 obsolete
scope-text failures** in 369.32s, predating the final navigation fix; all seven are
covered by the eight-case recheck. A primary drilldown/focus/category run had
32 passed / 2 old wording assertions; both were corrected and independently/locally
rechecked. Some early concurrently failing test teardown printed a ProfileJobs
missing-`_timer` callback exception; it did not recur in bounded passing lifecycle,
correction or final integrated processes. No ProfileJobs production workaround,
test skip, GC modification or assertion suppression was added. Do not call an
earlier interrupted/failed broad command an unchanged final all-pass run.

Final scripted native command from repository root:

```powershell
$env:PYTHONPATH='.;client/src;client'
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_qt_journey.py client/tests/test_v2_first_use_budget_workflow.py client/tests/test_v2_first_use_category_evidence.py::test_category_creation_is_first_task_only_for_empty_profile client/tests/test_v2_initial_focus.py::test_categories_open_at_first_choice_and_budget_is_discoverable -q --journey-native --journey-artifacts scratch/first-use-refinement-20261114/final-integrated
```

Actual render evidence under `scratch/first-use-refinement-20261114/`: `integrated`,
`final-integrated`, `category-evidence-final`, `category-polish`, `acceptance` and
`integrity`. Ordinary native final combined states are under
`scratch/first-use-audit-20261114/ordinary-native-final/`. ui_ux and primary inspected
1050×700 and 1280×800 pending/correction/confirmation/evidence/reports/Budget, category
empty/Add/saved states and the actual concise/expanded drilldown. No significant
unresolved UX finding remains in those states. The final optional category empty
whitespace improvement was inspected by primary after two passing native checks.

### Separate fresh task attempt and informed recheck

A fresh acceptance agent received outcome and isolated fixture setup only. It
imported independently chosen October rows, created checking/categories/budgets,
posted four transactions, inspected evidence, corrected Cafe to Dining and returned
to the same October budget. No product-control walkthrough or earlier findings/new
tests were read first. Read-only audit verified exact original bytes/hash, balanced
entries, expense **12995 minor**, income **250000 minor**, net asset movement
**237005 minor** and a linked reversal/replacement correction. Dining showed
1250 spending / 2000 budget / 750 remaining; Essentials 11745 / 10000 / -1745.
Total spending remained unchanged by category correction. SQLite integrity passed.
Normal raw Qt/process exits were 0. The attempt's recoverable zero-selection
observation led to the reproduced async fix described above.

The **informed new-process recheck** on that same synthetic profile automatically
selected River Cafe on first arrival, enabled correction inputs, retained the saved
reason and returned to October/Dining. Concise and expanded drilldown were inspected.
Database bytes stayed unchanged; raw Qt/process exits 0. Evidence:
`acceptance/result.txt`, `persistence.txt`, `recheck-result.txt` and recheck captures.

Limitations: setup supplied an empty profile and fixture catalog; incidental older
neighboring test lines were encountered while locating the setup factory. Native
file-picker transport used a Qt adapter; widget introspection/software events aided
operation. This is assisted agent discovery and informed recheck, not unfamiliar
human or direct OS-input acceptance. Startup catalog acquisition, native pickers,
display scaling, assistive technology, installed/offline/Mac behavior and broad
cold/large-archive profiling remain unverified here. Earlier native/heap-history
limits remain separate, and bounded passing checks do not prove general heap safety.
No live/private data, owner profile activation, commit, signing, push or release
was performed for this implementation. Human/platform/release gates remain open.

### Owner fresh private-input walkthrough prepared

Owner requested a disposable fresh test to execute personally with real statements.
Prepared a new empty workspace at
`scratch/v2-owner-fresh-20261114-6f0c3d9a/`, with
`Open-workflow-test.cmd` and `START-HERE.txt`. It opens the refined application as
**ParseTrail - DISPOSABLE WORKFLOW TEST**, with no seeded documents, observations,
accounts, categories, budgets or journal entries. Existing daily/demo profiles and
private archives were not selected. The owner will select inputs manually; this
preparation did not read/import any private statement.

The local development catalog includes 23 current public pilot definitions and
their account contexts, signed by a new ephemeral test key. Only its public trust
and signature remain, scoped to this test; production signing/global trust are
unchanged. Profile schema 24, explicit preferences, null keyring and app-home are
isolated in that directory. A 299-file public runtime snapshot plus SHA-256 manifest
pins the launcher and bounded workers to the refined source. Startup verifies those
runtime hashes. Preparation reuses the existing runtime-pinning/public-catalog ACL
handoff helpers; no source/runtime dependency install or live-profile activation.

Verified the actual pinned entry point with native Windows Qt rendering suppressed
from display: ready, imports enabled, Documents/Review/Accounts/Budget/Reports,
zero documents, profile SHA-256 unchanged, normal raw Qt/process exit 0. Preparation
also checked zero Sources/SourceObservations/Accounts/CategoryBudgetRates/
JournalEntries and SQLite integrity. Inspected the empty workspace screenshot.
The app remains closed so the owner can execute the launcher. This is preparation/
startup verification only; owner results and acceptance are pending.

**Privacy boundary after handoff:** this folder will contain private financial data
once the owner imports real statements. Do not enumerate/read its profile, logs,
originals or captures after this preparation by inference from this record. Further
agent inspection requires task-specific owner authorization. Closing keeps the test
available; its launcher reopens the same profile. No automatic deletion/reset exists.

## November 14: first-use clarity evidence gathering

Owner selected investigation of the new-user basics: import a statement, inspect
evidence, create accounts/categories, review activity and understand its monthly
budget impact. Reported problems are busy panels, verbose/indirect QLabel text and
unclear next actions. Rarely used controls may move to menus or explicitly secondary
groups. This selects evidence gathering and a subsequent roadmap discussion, not
UI implementation or a changed accounting policy. No additional owner walkthrough
feedback was supplied; development remains active.

The pre-existing documentation diff was committed as `e0d1412` with normal hooks.
Primary owns this record and integrated findings. Fresh ui_ux reviews information
hierarchy/copy and actual screenshots; desktop gathers current native Qt screen/
control inventories; fresh acceptance attempts the end-to-end goal without a
control walkthrough. Specialists own separate ignored subdirectories of
`scratch/first-use-audit-20261114/`, with no application-code write assignments.
Native focus slots are serialized. Only fresh disposable synthetic profiles and
fixture catalogs are permitted; no old demo/live profiles, private archives,
root `.env`, production, signing, activation or release actions.

Investigation criteria: identify a clear next action in each state; distinguish
original evidence, unsaved choices and saved reviewed activity; discover account,
category and monthly-budget setup in context; understand reviewed spending versus
budget, month/account scope and pending/coverage limitations; find secondary detail
and recovery without giving rare actions equal prominence. Check concise direct
copy, readable hierarchy, practical window sizes and keyboard access. Keep scripted
checks, goal-derived agent attempts and human acceptance separate.

### Initial screenshot findings

Current baseline: `e0d1412` (documentation-only change on application baseline
`21cd5d7`). Findings below describe the current rendered application, not proposed
implementation. Prior successful functional checks do not establish first-use
clarity. Screenshot paths are beneath the ignored investigation directory above.

| Priority | Screen/state and observed issue | Refinement to discuss |
| --- | --- | --- |
| High | Categories and budgets: after saving a budget, the red **Required · Enter a name to add a category** prompt remains above the budget editor. The selected category UUID and built-in identity caveat take primary space. | Separate adding a category from editing an existing category/budget; show required cues for the active task, and put stable identity in details. Keep explicit category identity and saved/draft semantics. |
| High | Review: document navigation, search/filter/navigation, purpose/category/reason, staging controls and Reload/Rules/Details/Source evidence share a dense working area. **Unallocated source row(s)**, **Ready for purpose review** and **Not staged** require learning the implementation model before acting. | Lead with selected account/period, imported rows needing attention and one coherent decision/confirmation area. Use direct task language; retain staging, required note and explicit final confirmation. Conservative row counts must not be renamed unique transaction counts. |
| High | Budget setup is reached through **Accounts → Categories and budgets**, while results live in **Reports → Monthly budgets**. The post-review shortcut names spending only. | Connect category creation, budget editing and the month's reviewed result in an obvious journey; assess a visible budget destination rather than relying on users to infer Accounts is the entry point. |
| High, observed task misunderstanding | Staging an income row after two expenses replaced their captured batch note with the income-specific reason. The fresh reviewer caught this in confirmation, cancelled, authored a shared reason and restaged before posting. | Make the shared reason's entire staged scope unmistakable at edit/stage time, including hidden rows. Evaluate a clearly separate batch-note control or explicit scope feedback; do not silently change current note semantics. |
| High, observed context mismatch | Following the October document's spending shortcut into Monthly budgets initially showed November's $0 reviewed spending and $100 remaining. The reviewer changed Budget month to October to see the intended result. | Add an explicit handoff to the relevant budget month, with month selection for multi-month activity and visible context. Keep independently chosen report scopes/dates and all-profile-account semantics deliberate. |
| Medium | Empty Documents: catalog management, folder import, account assignment, search and reload surround the initial import; initial focus is in search despite no documents. | Make importing a first statement the dominant empty-state action. Keep catalog installation prominent when it is required; make ready-catalog management and unrelated empty-state actions secondary. |
| Medium | Import step 2 retains the account-selection instruction from step 1 and stacks recognition, provenance, limitations, assignment summary and readiness text around the table. | Use state-specific heading/instruction and a compact account/date/row/confirmation summary. Keep the inability to replace retained formats visible before import, and keep genuine missing/unknown source facts next to affected decisions. |
| Medium | Source evidence leads with assumed-date settings, parser/definition/source identifiers and capture diagnostics, without a strong account/file heading. | Lead with recognizable document/account/date context and extracted rows; keep material capture/date limitations visible, move diagnostic IDs behind details and keep original/source locations easy to reach. |
| Medium | Spending report has repeated outer/inner all-account/date/reviewed-entry explanations and several advanced actions around a small financial table. | Lead with period, scope, reviewed total and relevant pending/coverage qualification once; disclose fuller explanations and less frequent export/diagnostic actions without hiding active blockers. |
| Medium | Accounts immediately leads with opening-based journal positions, review of source values and clearing explanations. A newly created valid account appears with **Unknown / Not established**, while ordinary account/category management shares the same area. | Lead with recognizable account identity and routine management; explain missing opening/position only beside that value. Put opening/value/history workflows in secondary groups while retaining truthful unknown balances. |

Representative evidence: `inventory/baseline/test_category_and_optional_budget_drafts_become_saved/b2f17a65/02-budget-saved-neutral.png`;
`inventory/baseline/test_empty_profile_to_reviewed_spending_correction_and_recovery_1050x700_/30cbd2f8/01-empty-profile.png`,
`06-ready-for-review.png`, `09-source-evidence.png` and
`10-reviewed-spending-with-pending-limit.png`;
`inventory/import/test_all_groups_account_first_back_preserves_drafts_final_import_assigns_without_posting_1050x700_/6260ce7c/03-single-interpretation-exact-assignment-confirmation.png`.
Primary inspected these actual renders; ui_ux independently inspected both practical
sizes and additional confirmation/correction states. These are agent visual findings.

Corrected supplemental evidence: `inventory/supplemental-corrected/03-populated-accounts.png`,
`06-monthly-budget-1050.png`, `07-monthly-budget-1280.png` and
`08-monthly-budget-1600.png`. Primary inspected loaded Accounts and the actual
1050-wide Monthly budgets tab: October Groceries budget $10, reviewed spending $4,
remaining $6, with two all-date pending source rows. The budget table's arithmetic
and column labels are understandable; date-range controls correctly disappear on
this tab. The main gap is reaching/editing the budget and connecting review to
this result, plus summary prominence and repeated qualifications. Do not infer a
monthly-date-controls defect from static construction code.

Primary/secondary hierarchy to discuss: keep file/account/period, selected-row
description/date/amount, material unknown/estimated-date/capture limits, active
blockers, required type/category/reason, staged scope and explicit posting effect
visible. Keep source/original one consistent action away. Disclose profile path,
ready catalog management, parser/definition/hash/category IDs, detailed journal
proof, reload/rules, export, opening/history and rare specialist routes secondarily.
Bring repeat/date/account checks forward when relevant, rather than burying active
recovery. Preserve the card screenshot's adjacent assumed/different-date warning.

Candidate design directions for the roadmap discussion (unselected): a Documents
library with a dominant first-import action; a coherent selected-document review
workspace with compact context and consistent source access; a recognizable
category/budget destination joining editing to the monthly result; and a posted/
pending outcome with an explicit handoff to the relevant month. Copy changes should
follow that interaction model rather than independently shortening every label.
Examples to evaluate are **Transaction type**, **3 imported rows need review**,
**Review and post N…**, and **Applies to all N staged rows** beside the reason.
These are wording proposals, not changed controls or changed review-note policy.

### Investigation verification

Native screenshot batch: five existing core-journey/refusal/cancel/category-budget
checks passed in 20.37s; three account-first/import/account-form checks passed in
5.41s. The four complete-journey children retain their raw exit 0 in `process.json`.
Runtime: Windows AMD64, Python 3.13.15, Qt/PySide6 6.11.2, pytest 9.1.1,
pytest-qt 4.5.0, native `windows` plugin, Segoe UI 9, 96 logical DPI/DPR 1.
These are scripted captures, separate from the fresh goal-derived attempt below.

The supplemental fixture-seeded native run returned 0 in 5.37s, capturing chooser,
no-catalog Documents, empty/loaded Accounts, account/category forms, spending,
monthly budgets at 1050/1280/1600 widths and a standalone card review. Visible
QLabel/button/group text inventories accompany those captures. Its first 5.16s run
selected the hidden Accounts report instead of the visible Reports view; the
mislabelled budget images and still-loading Accounts image in `supplemental/` are
rejected as budget/loaded-account evidence. The corrected harness selects the
visible view, waits for report readiness and asserts the expected table values
before capture. This was a harness error, not an application defect. Standalone
card review is separate from the embedded workspace and its missing workspace
context is not a finding.

### Fresh goal-derived attempt and outcome

Fresh acceptance received only the outcome, synthetic-input/setup boundaries and
tooling/isolation guidance, not a control walkthrough or the new design findings.
It started with an empty disposable profile and a fixture-installed CSV catalog.
It imported October checking activity, created Everyday checking, inspected source
evidence, created Food and drink / Other income categories, configured a $100
October expense budget, staged and posted three rows, then inspected spending and
Monthly budgets. Product controls needed no route coaching. Its final actual
October screenshot shows $100 budget, $7 reviewed spending and $93 remaining.

Observed misunderstandings/recovery are the shared-note and budget-month findings
above. The exact confirmation exposed the income-specific note on expense rows;
the reviewer cancelled and explicitly restaged with a common reason before any
posting. The October-to-November transition showed a valid but contextually
unexpected $0 reviewed-spending result; selecting October recovered the intended
comparison. The reviewer also understood staging/import/account/category setup
did not post money and that zero pending rows does not establish complete source
coverage. These are an agent's reported comprehension, not human acceptance.

Evidence: `acceptance/29-confirm-posting-QDialog.png` (initial shared note),
`31-corrected-post-preview-QDialog.png`, `35-budget-loaded-november-V2WorkspaceWindow.png`,
and `37-final-budget-V2WorkspaceWindow.png`. Primary inspected the confirmation,
November and final October renders. `acceptance/read-only-results.json` records a
SQLite `mode=ro` verification: one source, three observations, one financial account,
two categories, three reviewed entries, expense 700 minor, income 1000 minor,
financial movement +300 minor, October budget 10000 minor and remaining 9300 minor.
The saved entries share the deliberately corrected common reason. GUI raw exit and
parent process exit were both 0, with normal close and no new native failure.

Assistance/limits: setup bypassed startup chooser/catalog installation, and a native
OS file picker needed a synthetic path-return substitution. Qt combo popup timing
needed explicit selection/activation; a harness Escape cancelled the first import
and a retry preserved empty state before succeeding. Visible-widget introspection
and Qt software events assisted operation. This is a fresh goal-derived **assisted
agent attempt**, not unfamiliar-human/native-input discovery. Screenshot 34 is a
loading state; settled November/October evidence is identified above. The initial
native inventory separately covers chooser/no-catalog states without claiming an
end-to-end starter-package installation attempt.

Reproduction commands for the scripted capture selections, from repository root
with `$env:PYTHONPATH='.;client/src;client'`:

```powershell
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_qt_journey.py client/tests/test_v2_form_cues.py::test_category_and_optional_budget_drafts_become_saved --journey-native --journey-artifacts scratch/first-use-audit-20261114/inventory/baseline -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_import_account_review.py::test_all_groups_account_first_back_preserves_drafts_final_import_assigns_without_posting client/tests/test_v2_form_cues.py::test_account_draft_invalid_choice_and_saved_edit --journey-native --journey-artifacts scratch/first-use-audit-20261114/inventory/import -q
```

Initial evidence gathering is complete. No application or test source changed.
Current findings remain unresolved implementation work for roadmap discussion;
passing functional checks do not close them. Longer lists/labels, scaling,
screen-reader/high-contrast/keyboard-only use, a new full PDF/card first-use journey,
macOS, installed runtime, starter-package acquisition and human task performance
were not established by this run. Historical platform/accounting/release gates
remain separate; no UI implementation, owner acceptance or release is claimed.

## Handover: resume desktop UI development

Prepared November 14, 2026 at the owner's request. The immediate task is complete:
return to improving the V2 desktop journey from statement import through account
setup/assignment, staged review, correction and interpretation of reviewed spending.
No next feature has been selected. This handover supplies context and candidates;
the next user instruction selects implementation scope.

### Start here

- Repository: `C:\Users\tbrow\dev\parsetrail`, branch
  `feature/client-financial-insights`. Application baseline is `21cd5d7`; the
  working tree was clean after the four closeout commits below. This handover
  and its TODO/index refresh are subsequent documentation changes.
- Read `AGENTS.md`, especially **PySide6 engineering rules**, then
  `.agents/skills/parsetrail-workflow/SKILL.md`. Use `README.md`, `development.md`
  and relevant current client contracts for unfamiliar areas. Read this top
  handover and the specific linked evidence sections rather than interpreting
  every older investigation entry as an active problem.
- Keep one primary integrator and one work record. Continue this record for the
  existing journey; use a new packet record only for genuinely separate selected
  work. Do not create competing handover/acceptance logs.
- Use disposable synthetic profiles/statements. Do not reopen old owner/demo
  profiles or private archives by inference from historical paths. Do not load
  root `.env`, touch the independent 1.x fallback, activate a daily profile, or
  access production/signing/release artifacts. Inspect only explicitly relevant
  scratch subdirectories; scratch also contains unrelated/private material.

### Product decisions to preserve

- Documents, assigned accounts and dates should be recognizable throughout the
  journey. Make pending work, confirmation effects and recovery obvious, while
  keeping exact source evidence discoverable and report limits beside totals.
- Pale red means required/invalid input; pale green means a validated choice
  not yet saved; blue distinguishes available save/confirmation actions. Do not
  restore button-like color legends on every page; explain conventions in
  getting-started guidance. Keep button text readable with adequate padding.
- Institutions are managed categories, distinct from supported formats.
  Recognize PDF routes and exact declared CSV header structures automatically;
  resolve remaining ambiguity through institution/account/product context.
  Do not present arbitrary column remapping or contrived semantic choices.
  Existing-account selection must always allow creating a different new account.
  Trusted parser/account-profile metadata can prepopulate kind/product/scope;
  an unknown identity remains unknown. This session's import UX scope is PDF/CSV;
  do not infer XLSX UI work is selected because lower layers contain XLSX code.
- Ordinary review has one staging flow, supports multiple selected rows, and
  distinguishes staged rows from saved review. Hidden staged rows remain part
  of the staged confirmation. Preserve unrelated staged/edited work on cancel,
  category management, navigation and correction.
- Show a saved review note separately from a new reason for correction or
  withdrawal. A saved note must not silently authorize another change.
- Opening focus should reach the first logical editable field or decision.
  Category creation starts with the custom-name field; budget controls use
  recognizable budgeting terminology.
- Imported evidence, reviewed interpretations and reports remain distinct.
  Preserve exact amounts/dates, immutable originals, transactional writes and
  explicit confirmations; internal transfers/repayments do not add spending.

### Current implementation and relevant code

Under `client/src/parsetrail/gui/`:

- `v2_workspace_window.py`: Documents/Review/Accounts/Reports navigation,
  contextual document/account/period selection, embedded views and profile jobs.
- `v2_import_account_review.py`, `v2_batch_import.py`: reusable import queue,
  provisional account decisions and final import confirmation.
- `v2_ordinary_review.py`, `v2_cash_activity_review.py`,
  `v2_card_purchase_review.py`, `v2_review_navigation.py`: staging, multi-row
  selection, row drafts, saved notes and correction recovery.
- `v2_reviewed_reports.py`, `v2_report_drilldown.py`, `v2_evidence_preview.py`:
  qualified spending, report-to-source correction and source facts.
- `v2_document_viewer.py`, `v2_original_document.py`: memory-only original
  viewing, queued PDF UI notifications and explicit reader/viewer disposal.
- `v2_gui_lifetime.py`, `v2_profile_jobs.py`, `v2_document_browser.py`,
  `v2_form_state.py`: one-shot disposal, GUI handoff, inventory, state cues and
  window-owned initial focus. Follow these patterns when adding UI.

Core boundaries are `core/v2_workspace.py`, `core/v2_import_accounts.py`,
`core/v2_format_recognition.py` and `core/v2_profile_store.py`. Read
`docs/client-ledger-contract.md`, `docs/client-v2-parsing.md` and other affected
contracts before changing accounting, source admission or persistence behavior.

### Suggested next UI tasks, still unselected

1. **Post-import format correction/recovery:** currently an incorrectly retained
   format cannot be replaced in place. Design the discovery, impact preview,
   cancellation and recovery journey first. Preserve immutable original bytes,
   affected posting/history meaning and unrelated work. This crosses evidence/
   ledger boundaries and needs their expertise plus independent integrity review.
2. **Specialist history comprehension:** investigate transfer, settlement, loan
   and account histories that still lead with technical event/journal/proof
   detail. Consider concise narratives with supporting evidence behind details.
3. **Source-evidence navigation:** exact report-to-review row navigation exists;
   document evidence does not yet consistently highlight the originating report
   row. Inspect current behavior and choose a coherent source-location affordance.
4. **Practical sizes, larger workloads and accessibility:** recheck older findings
   involving 920x640 windows and many long account names before fixing them.
   Standard inspected sizes are 1050x700 and 1280x800. Cold loads, large originals,
   posted-history growth, scaling and assistive technology remain useful follow-ups.

The user's suggestion to use same-day repeat matching is discussion, not a
selected accounting policy. Do not silently replace the existing matching window.
See `TODO.md` for candidate links; its order is not implementation authorization.

### Verification state and native-failure disposition

- Technical changes, automated checks and agent review are complete for the
  recorded improvement. Actual unfamiliar-human acceptance, owner accounting
  review, macOS/installed-runtime checks and release authorization are separate.
  The user wants UI development to resume; no known failing revised native
  journey is currently blocking it.
- The PDF-load exit is corrected. Its actual raw status was `0xc0000409`,
  `FAST_FAIL_GUARD_JUMPTABLE`, not the shell's reported 1. Synchronous password
  UI changed Windows last-error from 4 to 122 before Qt reread it. Queue both
  status and password UI receivers and reject stale notifications. Keep the
  memory-only buffer/document ownership and cleanup order intact.
- The exact historical 35-case native sequence passes independently; the
  expanded 57-case native sequence also passes in one process, including normal
  shutdown. The archived original reproducer now passes all four cycles in one
  process both offscreen (13.51s) and native Windows (16.59s), raw exits 0,
  normal GC, unchanged assertions and unchanged application/archive sources.
- The older `0xc0000374` corrupting write/free remains unidentified. There is no
  proven upstream Qt/Shiboken defect. Do not describe the PDF fix as proof of
  universal heap safety or reopen version/build/debugger experiments without a
  new failure or a selected investigation. Preserve the diagnostic archive.
- A pre-existing offscreen account-nickname focus timeout was reproduced against
  committed baseline code. All 17 native account-import cases pass. Do not
  silently skip that offscreen limitation or mislabel it as a new UI regression.

Local evidence: `scratch/gui-pdf-exit-20261114/` holds the PDF diagnosis and raw
35/57-process results; `scratch/qt-lifetime-recheck-20261114/` holds both archived
rechecks; `scratch/gui-lifetime-20261114/` holds integrated journey captures and
baseline overlays. These are synthetic diagnostics, not live profiles to activate.

### How to resume

Use the `ui_ux` role to establish the selected journey, states and observable
usability criteria before dividing substantial interaction work. Give desktop
implementation a disjoint write set; add evidence/ledger expertise where the
selected task changes those boundaries. Have acceptance attempt the integrated
task from a goal-only brief separately from scripted checks. Resolve significant
discovery/comprehension findings, not merely failing tests. No routine per-screen
design approval is required; ask only for unresolved product/accounting choices
or actions beyond existing authorization.

Use the existing `client/.venv/Scripts/python.exe` (Python 3.13.15, PySide6/Qt/
Shiboken 6.11.2); dependencies are already installed. From repository root:

```powershell
$env:PYTHONPATH='.;client/src;client'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_qt_journey.py -q --journey-native --journey-artifacts scratch/next-ui-journey
```

Select focused checks for changed behavior. Useful modules include
`test_v2_initial_focus.py`, `test_v2_import_account_review.py`,
`test_v2_ordinary_review_async.py`, `test_v2_correction_notes.py`,
`test_v2_pdf_load_callbacks.py` and the `test_v2_*lifetime.py` files.
`test_v2_qt_journey.py` contains standard process-contained complete journeys;
the archived four-cycle diagnostic is intentionally separate. Raw nonzero exits
must fail verification; do not add pacing, GC changes, skips or indefinite object
retention to manufacture stability. Inspect actual populated/empty/loading/
blocked/correction UI with readable fonts and practical sizes, and keep agent
checks separate from human acceptance. Ordinary native checks are authorized;
computer-use control is not required to run pytest-qt or inspect saved screenshots.

Latest commits: `4b4e58d` lifetime cleanup/tests, `f21285f` queued PDF correction,
`a66d61c` PySide6 rules, `21cd5d7` verification/current guidance. Nothing was
pushed or released. Any future commit should preserve this evidence and the
current financial/evidence safeguards.

## November 14 local commit closeout

Owner requested committing the accumulated changes in logical hunks:

- `4b4e58d`: explicit desktop disposal, weak ownership links, GUI-thread worker
  handoffs and focused lifetime regressions.
- `f21285f`: queued PDF status/password UI delivery and native-load/stale-event
  regressions, separated from the broader lifetime changes.
- `a66d61c`: agreed PySide6 engineering rules in `AGENTS.md`.
- This documentation commit records native failure diagnosis, the passing
  historical/expanded sequences and archived rechecks, current runtime guidance
  and remaining limits.

Commit preparation passed Ruff check/format on all 21 changed/new Python files
and diff checks. Their AST fingerprints remained identical through the code
commit hooks, and the original archived reproducer SHA-256 still matches.
Normal hooks were used without bypass. Existing completed behavioral checks
below provide verification; no additional crash experiments were needed for
committing. Raw logs, source/build snapshots, debugger tools and disposable
profiles remain ignored scratch artifacts. No push, upstream report, live-profile
activation or release action was performed. Earlier no-commit statements below
describe their respective verification checkpoints before this owner-requested
closeout.

## November 14 archived reproducer recheck after lifetime corrections

Owner requested rerunning the archived tests against the current application.
Primary ran the complete `devtools/qt_heap_crash/short_review_cycle.py` once
offscreen and once with native Windows Qt. Each invocation ran all four original
cases in one QApplication/process, including process shutdown. No per-case
process splitting, added pacing, forced/disabled GC, assertion changes,
indefinite object retention, debugger or new application changes were used.

| Mode | Pytest result | Raw child exit | Parent elapsed |
| --- | --- | --- | --- |
| Offscreen | 4 passed in 13.51s | 0 / `0x00000000` | 13.999s |
| Native Windows | 4 passed in 16.59s | 0 / `0x00000000` | 17.042s |

Both runs used the locked Windows CPython 3.13.15 / Qt/PySide6 6.11.2 runtime,
disposable profiles, null keyring and the unchanged synthetic statement/catalog
fixtures. Raw command, PID, timeout/result metadata, console logs, screenshots
and before/after source hashes are retained in
`scratch/qt-lifetime-recheck-20261114/{offscreen,native}/`. The original archived
scenario SHA-256 still equals
`478a7d32dfa9df448f8ba1e01fbc16e9ddaae7e8169e879d0e1eb5480cbf7415`.
Application/archive source hashes remained unchanged throughout both runs.

The archive preserves the scenario/support fixtures while importing current
application code; it does not restore the older UI implementation. The current
implementation passes this previously failing sequence in both modes. This is
additional bounded regression evidence, not identification of the earlier
invalid native write/free or proof of universal long-session/platform stability.
No commit, push, live-profile activation or release action was performed.

## November 14 PDF-load fail-fast diagnosis and correction

Owner explicitly authorized identifying the sequence-dependent native exit,
controlled comparisons, process-local native capture if needed, and a causal
correction while preserving the preceding lifetime fixes. Primary owns the
runner, comparisons, native capture, production correction and this record;
desktop independently mapped synchronous callbacks/upstream code, and acceptance
audited historical status reporting, source/test integrity and final native replay.
All data are synthetic and profiles disposable. No production, signing, release,
live-profile or private archive access was involved.

### Actual termination mechanism

The earlier reported `exit 1` came from the shell/tool status. Those failed
lifetime runs had no separately retained subprocess return code or durable log;
pytest capture could also hide diagnostics when a process died before reporting.
The new bounded runner captures the Python child directly, stores the original
command/order, source hashes, console output, raw return code/hex, timeout and
elapsed time. It does not infer success from the debugger's exit code.

The unchanged native 14-case original-lifetime module passes its first ten
CSV/host cases, then exits with raw `3221226505` / `0xc0000409` during the first
encrypted-PDF case. A portable CDB capture of that same synthetic module records
exception parameter `0x25`, `FAST_FAIL_GUARD_JUMPTABLE`, at
`Qt6Pdf!QPdfDocumentPrivate::updateLastError+0x1a6`, called from private
`load+0x3a3`. The instruction is `int 29h`. This is a native fail-fast, not an
ordinary Python exception, explicit QApplication exit, demonstrated stack-buffer
overwrite, or the older `0xc0000374` heap-corruption report. The debugger completed
with code 0 after capturing the exception; that is not a passing test result.

The [exact Qt 6.11.2 implementation](https://raw.githubusercontent.com/qt/qtwebengine/v6.11.2/src/pdf/qpdfdocument.cpp)
first reads PDFium's error in `tryLoadDocument()`, synchronously emits Error and
password notifications, then reads the error again when control returns to
private `load()`. `updateLastError()` accepts PDFium error values and uses
`Q_UNREACHABLE()` otherwise. Upstream PDFium's Windows error helpers use Win32
thread-local last-error state; its exact bundled source revision was not pinned
in this review. The loaded binary's behavior was tested directly instead.

Diagnostic wrappers observe the production password UI callback enter with
Win32 last-error **4** (incorrect password) and return with **122** (insufficient
buffer). Its enclosing Error-status callback also returns with 122. Qt then
reaches the fail-fast on its second error read. A diagnostic-only wrapper which
restores the incoming last-error value after the same UI work allows all 14
cases to pass. No such OS error manipulation was introduced into production.
This evidence supports synchronous UI work clobbering the parser's error state;
the individual Windows API inside widget layout/focus was not identified.

### Callback and ownership review

For the failing password case, synchronous application calls are
`statusChanged(Error) -> _pdf_status -> _password_required -> labels/body/password
controls/focus -> load_finished(False) -> OriginalDocumentOpen._loaded`.
The opener sees password-needed state, retains the viewer and publishes status
text; it does not close or delete the viewer. The following passwordRequired
signal enters the duplicate-state guard. The failing test has no host or external
status observer at this stage. Native QPdfView status/layout and link-model
receivers also run; they require Ready for rendering, while an empty search
avoids PDF text reads. Ready handling can navigate pages and publish completion;
external completion observers may close a viewer, which is another reason UI
completion must occur after native loading returns.

The viewer retains QPdfDocument, QBuffer, the buffer's internal QByteArray and
the SavedImport source bytes. `setData()` uses QBuffer-owned storage, not an
external QByteArray pointer. Live object/device/data assertions pass across
native loading, on the GUI thread. Existing cleanup first marks closed/stops
timers, detaches view/search documents, closes the document, then closes/clears
the buffer/source before deferred widget deletion. No device lifetime fix is
supported by the comparisons; that order and memory-only production viewing
remain intact.

### Controlled comparisons and preserved order

Runtime remains Windows AMD64, CPython 3.13.15, PySide6/Qt/Shiboken 6.11.2,
pytest 9.1.1 and pytest-qt 4.5.0, native windows plugin. Normal GC and original
assertions remain enabled. Qt6Pdf.dll SHA-256 is retained in `runtime.json`.
Logs, runners, frozen pre-fix viewer, source hashes and comparison commands are
under `scratch/gui-pdf-exit-20261114/`.

| Comparison | Observed outcome |
| --- | --- |
| Production callbacks, original module order | Ten pass, then raw `0xc0000409` |
| Password cases alone, no preceding CSV/host cases | Two pass, raw 0 |
| Original ten cases followed by plain QPdfDocument/QBuffer loading | Eleven pass; returns IncorrectPassword with live bytes/device |
| Same prefix followed by passive status/password observers | Eleven pass; Loading, Error and password events observed |
| Full module with application UI callbacks made passive | Native load returns; three expected UI-readiness assertions time out, eleven pass; raw pytest failure 1, no native fail-fast |
| Full module, production callbacks, synthetic file-path loading | Same native `0xc0000409`; replacing QBuffer does not fix it |
| Full module, callbacks restore incoming Win32 last-error (diagnostic only) | Fourteen pass, raw 0 |
| Full module, application UI callbacks deferred (diagnostic only) | Fourteen pass, raw 0 |
| Frozen pre-fix viewer, exact historical 35-case order | Collects 35, former failure recurs with raw `0xc0000409` |
| Final production correction, independent exact historical order | Collects 35; 35 pass in 52.52s, raw 0 |
| Final correction, expanded combined sequence including existing viewer suite | 57 pass in 59.74s in one process, raw 0 |

The tested failure is sequence-dependent; it is not evidence that CSV bytes
damage a PDF device. Passive/plain controls after the same prefix return safely,
and the error-state trace explains how GUI/focus state can change the outcome.
This is a bounded comparison, not a claim that no other ordering could fail.

Two exploratory metadata details are retained transparently: the directory
`deferred-module-1` actually ran passive callbacks because the first runner did
not forward its diagnostic-mode variable; its LOAD_BEGIN log identifies passive
mode. Earlier original-combined commands used an ineffective root-relative
deselection and actually collected 36, not 35. Those are expanded-order evidence,
not the historical-order proof. Final replay names the original seven profile
cases explicitly (including a two-case parametrization), collects exactly 35,
and excludes no historical assertion. A separate expanded run includes the
later-added profile regression as well. Some exploratory variants ran concurrently;
the definitive frozen/final order replays ran sequentially.

### Minimal production correction and verification

Both QPdfDocument statusChanged and passwordRequired application receivers now
use Qt.QueuedConnection. Merely queuing passwordRequired would leave the direct
Error-status route into the same password UI. The queued status receiver rejects
notifications superseded by the document's current status; it does not convert
an obsolete Loading event into duplicate Ready completion. The password receiver
requires current Error/IncorrectPassword state, avoiding stale prompts after a
successful retry or closure. Existing closed guards and explicit lifetime
cleanup are preserved. No system-wide debugger/heap settings, GC suppression,
exception suppression, indefinite retention or production disk-PDF fallback was
used. The original lifecycle tests and ordinary viewer tests are unchanged.

New focused regressions assert that password UI executes only after native load
unwinds and on the GUI thread, document/device/backing bytes remain live through
load, completion is emitted once, and obsolete error/password events leave a
Ready viewer unchanged. Both pass natively and offscreen. The first test-spy
draft accidentally used a name colliding with the viewer's password field; the
spy now uses the actual callback method name, with its assertions preserved.
Ruff and diff checks pass. Acceptance found no material source concern and
independently verified the final historical 35-case process and raw successful
exit (`acceptance-fixed-exact35/result.json`). No repeated failing test was
split, skipped or retried into a pass.

This closes the identified PDF-loading fail-fast within the recorded native
verification. It does not identify or close the earlier heap-corrupting write,
prove universal long-session safety, establish another platform/installed build,
or attest actual human acceptance. No commit, push, upstream report or release
was requested or performed.

## November 14 GUI lifetime cleanup

Owner authorized implementing the preceding review's recommendation. Primary
owns integration, shared helpers, inventory/workspace cleanup and this record;
desktop specialists own original viewing, profile jobs and audited transient
dialog lifetimes. Acceptance independently reviews final source and bounded
native checks. Synthetic disposable profiles and the existing locked client
environment only; no live profiles, private archives, production or releases.
The November 10 review below remains historical evidence, not a description of
all current reference edges.

Implementation:

- Added `v2_gui_lifetime.exec_disposable()` for one-shot modal result delivery
  with GUI-event-loop deletion in `finally`, including exceptional exit. Ordinary
  review/workspace evidence previews and report/drilldown paths use it.
  Evidence previews also schedule deletion on accepted close/done so other
  existing direct callers share that policy. Reusable forms/active import
  queues do not adopt blanket delete-on-close behavior.
- Replaced ordinary batch-panel/review and recognized-preview/import-owner
  strong back-references with weak references. Queue hide/show and staged drafts
  remain reusable. Import account's deferred focus now uses a parent-owned
  single-shot QTimer and bound slot, cancelled when its dialog is destroyed.
- Original viewers release bytes/PDF/CSV/password state, disconnect host
  callbacks and schedule native deletion on accepted close/done. The unused PDF
  panel and page-text widget now have parents even on CSV/error paths. Viewer
  control lambdas became bound methods; host callbacks use weak captures.
  Openers release completed reader/error/viewer references, disconnect completed
  host/viewer connections and dispose their QObject only after reads and any
  live viewer finish. Shutdown drains stopped reads without opening new viewers.
- Profile jobs retain operation captures until a job-owned queued GUI slot has
  joined the worker, delivered through a weak controller reference and cleaned
  up in `finally`. This still runs when the controller has been destroyed.
  Finalization is claimed before delivery, preventing a reentrant shutdown
  from releasing or deleting a worker inside its live completion callback.
  Shutdown uses the same delivery-before-cleanup path for confirmed writes.
  Reads remain cancellable/coalesced; confirmed writes cannot be discarded.
- Inventory workers similarly own queued GUI cleanup independent of their
  receiver, replacing context-free registry-release lambdas; workspace result
  delivery precedes cleanup and no longer independently deletes the worker.
  Workspace close/profile replacement also clears obsolete success callbacks;
  queued close/inventory/refresh actions now have a QObject context so native
  window deletion cancels delivery rather than invoking deleted controls.
- Chained/grouped error tracebacks are removed at GUI handoff without changing
  exception types, arguments or cause/context relationships. Completed profile,
  inventory, original-read and report-read handoff references are released.
  No production GC disabling, forced collections, GC thresholds or indefinite
  widget retention was introduced.

Focused checks
assert actual native-object invalidation and GUI destruction-thread identity,
not merely window invisibility. The normal process-contained four-case journey
passed (40.78s): both 1050x700 and 1280x800 complete import/account assignment,
staging, evidence, qualified reports, cancellation/correction, restore/reopen;
refusal/retry and in-flight import cancellation also pass. Screenshots/runtime
metadata are retained under `scratch/gui-lifetime-20261114/journey/`; primary
inspected the evidence table and corrected report captures for readability and
retained scope/qualifications. This is software-event/agent verification, not
new human acceptance.

Final combined offscreen helper/inventory/profile/workspace/original lifetime
checks passed 27 (7.09s). Destruction observers use Qt.DirectConnection so thread
assertions measure the actual destructor signal's emitting thread, rather than
a receiver's queued delivery thread. Independent acceptance's final targeted
native helper/inventory/profile/workspace run passed 13 (4.44s, exit 0).
After adding the reentrant-delivery guard, all eight final profile-job checks
passed natively (2.37s); acceptance reviewed the guard without further concerns.
Changed-file Ruff check/format and `git diff --check` pass. No commit, push or
release action was requested or performed for this follow-up.

The final native Windows process-contained 1050x700 journey also passed
(10.90s). The new queued-workspace-disposal check passed: deleting the native
window cancels both its pending close and initial inventory actions. Workspace
and inventory regressions passed 16 checks (104.02s). Shared helper/inventory
checks passed five; profile-job lifecycle checks passed seven. Specialist viewer
and original-opening checks passed 57 initially; the final expanded original
lifetime module passed 14 offscreen. Dialog lifetime checks passed nine natively,
and the final parent-owned import-focus timer's affected case passed again.
The 17 existing native account-import cases passed, including Back/queue drafts,
assignment, cancellation and source-format confirmation. Report/staging focused
regressions passed nine; acceptance separately rechecked two staging/draft cases.
Counts overlap and must not be added into a unique-test total.

An initial combined offscreen preview/drilldown/category/import regression run
ended with 33 passes, 12 failures and two teardown errors. The import failures
were nickname-focus timeouts under the offscreen popup plugin. An isolated
overlay of all changed GUI modules from committed HEAD reproduced the same
line-121 focus timeout (10.39s), confirming that symptom predates this change;
the overlay is retained in `scratch/gui-lifetime-20261114/baseline-gui/`.
Native account-import verification passes. The teardown errors involved queued
workspace close actions reaching deleted controls; QObject-context scheduling
and the new destruction regression address that path. These failures are not
silently relabelled as a passing combined offscreen run.

Independent acceptance found no additional material source correctness issue,
but its combined native run remains incomplete: 22 of 35 new lifetime checks
passed before process exit 1 without a pytest diagnostic, at the first
password-viewer case. The original-lifetime module alone similarly exited after
its preceding ten CSV/host checks. Both password cases passed in isolation, and
the nine dialog cases passed separately. Stage tracing places the stop during
viewer loading, before the password-wait condition, rejection or deferred native
deletion. Final temporary stage tracing places it specifically in the call to
`QPdfDocument.load(self.pdf_buffer)`, including any synchronous signal handling;
the call did not return. Tracing was removed, tests are unchanged/unskipped, and
no application or harness fix was established for that exit. No causal
attribution to the new disposal code is established. This
sequence-dependent native exit remains a material verification limit; isolated
passing cases do not establish aggregate stability. Existing viewer tests were
not reached in that combined native invocation. No new native heap error code,
collector frame or original corrupting instruction is established by exit 1.

An existing async staging test initially failed because the second selected row
had no explicit note after restoring its row draft. Loading the committed HEAD
profile-job and ordinary-review modules into an isolated scratch overlay
reproduced the same line-203 count assertion (15.19s). Its setup now authors the
second row's required note; two-row staging, hidden-row retention and atomic
posting assertions remain. Product staging semantics were not changed for it.
The baseline overlay remains in `scratch/gui-lifetime-20261114/baseline/`.

No archived reproducer, native debugger, new heap capture or standalone GC/crash
experiment was run. Completion of these targeted lifetime changes must not be
reported as proof that the original corrupting operation or upstream fault has
been identified. macOS, installed-runtime and actual human acceptance remain
outside this verification.

## November 10 GUI reference-cycle and disposal review

Owner requested inspection of Python cycles, Qt parent ownership, window-close
disposal and the two saved worker destruction stacks. Primary integrated separate
desktop source reviews and acceptance's independent saved-text-stack review.
This follow-up changed this record only: no application edits, GUI launches,
tests, forced collections, debugger/dump processing or new crash experiments.
Inputs were current client source, the frozen synthetic journey, the two existing
synthetic `console.log` files and official Qt/Python documentation. No live data
or broader scratch/private archive enumeration was used.

### Confirmed reference paths and ownership

- Ordinary review has an unconditional Python cycle: `review.batch` points to
  `OrdinaryBatchPanel`, whose `review` attribute points back to the dialog
  (`v2_ordinary_review.py:90,984-985`). The panel also has the review as its Qt
  parent. Cancellation and dialog completion stop jobs but do not break that
  Python cycle. The workspace's embedded-disposal path does explicitly schedule
  native deletion, so the cycle alone does not prove wrong-thread destruction.
- Account import has another unconditional cycle: `review.preview` points to
  `_RecognizedPreview`, whose `_decision_owner` points back to the review
  (`v2_import_account_review.py:103,209`). `finish_queue()` hides and drops the
  request, not this back-reference. Actual workspace import completion calls
  `finish_queue()`, `deleteLater()` and clears `import_preview`
  (`v2_workspace_window.py:1610-1613`), providing explicit native disposal.
- Workspace `_profile_job_handlers` intentionally holds success callbacks,
  including self-capturing closures and `self._switch_profile`. Those entries
  can form a temporary Python cycle back to the workspace. Normal success,
  failure and rejected-submission paths pop entries (`813-829`). This is not a
  demonstrated persistent leak or part of the short review scenario's crash.
- Stored exceptions retain tracebacks and frame locals. For example, opener
  `self.error = exc` in `v2_original_document.py:140-143` produces
  `opener -> exception -> traceback -> _complete_read frame -> opener`, and can
  retain a partially constructed viewer through an exception's deeper frames.
  Worker exception storage has the same pattern (`v2_profile_jobs.py:65-66`,
  `v2_original_document.py:50-51`); workers have explicit finished/deleteLater
  paths. These failure-path cycles were not established in the successful
  synthetic review sequence.
- Cash/card reload, report table/busy, workspace view and viewer-control lambdas
  capture their GUI owner. Reader cleanup lambdas also capture workers/openers.
  Captures are evident from source; a Python-GC-visible cycle through Qt signal
  storage cannot be asserted merely because a bound method is connected. No
  runtime referrer graph or binding-retention experiment was performed.
- `_InitialFocusPolicy` has a Qt parent and is stored on the root, but stores
  no explicit Python back-reference to it. Its queued lambda captures policy
  and root temporarily; the timer has a QObject context and opening-generation
  checks (`v2_form_state.py:137`). This differs from the context-free import
  account focus timer (`v2_import_account_review.py:432`), which captures the
  dialog until callback delivery without equivalent cancellation/context.

### Close-time disposal: safeguards and gaps

Most inspected controls created without a constructor parent are subsequently
adopted by layouts, splitters or tabs. The source-evidence preview is parented to
its calling review/workspace; its table models are explicitly parented to the
preview, and its QTabWidget/table pages are adopted into its widget hierarchy.
Thus absent constructor arguments alone do not establish missing ownership.
The startup dialog and main window are intentionally top-level; their native
lifetime is not managed by another widget. Inventory/profile QThread wrappers
are deliberately unparented and globally retained until completion, not GUI
widgets lacking an accidental parent.

Current embedded review removal cancels reads, removes/hides the view, calls
`deleteLater()` and clears the workspace reference (`v2_workspace_window.py:726-733`).
Report removal similarly calls `shutdown()`, removes/hides/deletes and drops
the reference (`783-792`). Both participate in workspace close handling.
Staged-review confirmation already uses `finally: dialog.deleteLater()`
(`v2_ordinary_review.py:1383-1389`). These are existing positive safeguards.

By comparison, ordinary-review evidence opening
(`v2_ordinary_review.py:814`), report drilldown (`v2_reviewed_reports.py:803-813`)
and drilldown evidence opening (`v2_report_drilldown.py:337`) call parented modal
dialogs' `exec()` without explicit post-exec deletion. Evidence preview close/done
only cancel original opening (`v2_evidence_preview.py:232-242`). None of these
dialogs enables WA_DeleteOnClose in the reviewed source. Closed native trees
can therefore remain parent-owned until parent destruction; that is delayed
Qt disposal, not proof that these individual children are Python-owned garbage.
Repeated opens can accumulate hidden child trees.

The original-document viewer releases source/PDF/CSV/password data and removes
its global viewer retention on close (`v2_document_viewer.py:523-565`), but does
not schedule native widget deletion. The opener also keeps `self.viewer` after
viewer closure. Parent ownership and wrapper/callback release need separate
consideration here. `v2_external_document.py` has similar exception/callback
patterns, but no current client importer was found; current original viewing
uses `v2_original_document.py`.

### What the two saved stacks identify

Acceptance independently reread the exact existing text captures:

- `scratch/qt-native-debug-20261109/source-1/console.log:778` identifies worker
  thread 41 as `DocumentInventoryWorker`. Lines 797-815 show Shiboken wrapper
  deallocation through QDialogWrapper, QTabWidgetWrapper, QStackedWidget,
  QTableViewWrapper, QHeaderView and layout/scroll-area destruction, interleaved
  with QObject child deletion. This identifies a tabbed dialog's table hierarchy.
  The worker is waiting for the GIL inside an application event filter during
  that destruction (`780-796`).
- `scratch/qt-native-debug-20261109/baseline-4/console.log:710` identifies worker
  thread 40 as `_ProfileJob`. Lines 720-737 show the QBasicTimer::stop warning
  path, item/table/stacked-widget child destruction and Shiboken deallocation.
  Enclosing PySide dialog types are not resolved in this capture; the warning's
  message text is absent. Source capture types cannot be imported into this run
  as though they identify the same instance.

`V2EvidencePreview` is a strong structural candidate: the frozen journey opens
it at `short_review_cycle.py:134-142`, and its tab pages are direct QTableViews
(`v2_evidence_preview.py:183-205`). `V2ReviewedReportsDialog` also matches that
hierarchy and occurs in the journey, including in embedded mode. The entry
drilldown itself has a table but no explicit tab widget. No captured Python
subclass name, window title, objectName or verified this-pointer ties the native
hierarchy uniquely to a dialog. Raw x64 Args-to-Child columns and nearby/repeated
address values do not establish instance identity. Current source comparisons
are not a byte-for-byte reconstruction of the captured historical runtime.

Qt/Shiboken private symbols support the native destruction finding. Python313
has only export symbols in these logs (`source-1:1469`, `baseline-4:872`); high
offset labels such as Py_Dealloc/Py_HandlePending cannot identify an exact
internal Python routine. Neither text stack contains a named collector frame
or a collected-object graph. Therefore worker-thread GUI destruction is
confirmed, while cyclic GC versus ordinary reference release, the exact dialog,
the responsible reference edge and the original heap-corrupting instruction
remain unproven. The main-thread fault detection and concurrent worker teardown
are not by themselves proof of causation.

Next implementation should give one-shot dialogs explicit GUI-event-loop disposal,
break avoidable GUI back-references at final disposal, and clear completed
callback/exception retention where safe. It must preserve deferred confirmed-write
completion, request cancellation, evidence and staged drafts. Any later lifetime
verification should map destroyed types/instances to their owning component and
record actual destruction threads; this review did not restart those experiments
or introduce GC suppression/forced collection as a production workaround.

Reference basis: [Qt object ownership](https://doc.qt.io/qt-6.11/objecttrees.html),
[QWidget close](https://doc.qt.io/qt-6.11/qwidget.html#close),
[QObject deleteLater](https://doc.qt.io/qt-6.11/qobject.html#deleteLater),
[Python finalization](https://docs.python.org/3.13/reference/datamodel.html#object.__del__).
Closing generally hides a widget; deferred deletion requires its owning event
loop to process the deletion, and calling deleteLater after the main loop has
stopped does not delete the object. Python finalization has no creating-thread
guarantee. These documented constraints explain why parents, Python cycles and
final disposal must all be checked, rather than treating any one as proof.

## Local commit closeout

Owner requested committing the accumulated diff in logical hunks:

- `f0863f1`: separate saved review notes from new correction reasons, with
  isolated scenarios, retention checks and user-facing guidance.
- `4a67134`: scope opening-focus filters to their task windows, with lifecycle
  checks and the runtime mitigation/remaining-risk guidance.
- `30562b3`: retain sanitized runtime/style/native evidence and explicit
  incomplete standalone-reproducer status.
- This documentation closeout records verification and the unresolved GUI-thread
  lifetime concern in the existing work record and planning index.

Commit preparation passed changed-file Ruff check/format for 25 Python files,
JSON parsing/privacy-field checks and diff checks. Python AST fingerprints stayed
unchanged through commit hooks; the original frozen reproducer SHA-256 matches.
Hooks normalized generated JSON line endings. Existing behavioral verification
above was retained; no stopped crash/debugger experiment was restarted. Raw
dumps, SDKs, source builds, tools and candidate experiments remain ignored scratch
artifacts. No push, upstream issue or release action was performed.

## Standalone reproducer reduction and thread-lifetime finding

Owner authorized a standalone reduction for a potential upstream report, using
scratch for experiments and `devtools/qt_focus_repro/` for a confirmed small
example. No external posting, product-code change or live/private data was
authorized or performed in this follow-up. The primary owns the result and this
record; specialists investigated disjoint widget/object reductions and reviewed
saved native stacks. The historical archive and final product source are untouched.

Created a clean CPython 3.13.15 environment containing only PySide6 Essentials
6.11.2 and Shiboken 6.11.2, with no base-environment `.pth`, ParseTrail or pytest
dependencies. Synthetic process settings/temp directories are isolated.
Qt-only candidates covered object/widget timers, Python cycles, global/window
filters, modal loops, model/proxy changes, file dialogs, focus, styles, worker
completion and teardown. Normal-GC runs were distinguished from explicitly
requested full collections and lowered-threshold diagnostic variants. These
variants are reproduction experiments, not production GC changes/workarounds.

The widget specialist retained 21 fresh-process trials (1,096 GUI cycles), all
clean, including native controls and explicit collection/pressure variants.
Primary/object trials likewise did not establish a simple main-thread case.
The preserved pre-fix focus helper, loaded only into a disposable full-application
positive control, still reproduced `0xc0000374` (`positive-legacy-2`). The first
positive-control setup attempt failed collection because its helper file was
not yet written; it is not counted as product/crash evidence. The original helper
was subsequently recovered from Git and its SHA-256 matched the original source
manifest. The product's per-window implementation was never reverted.

Reviewing all native thread stacks, rather than only the faulting thread, exposed
an important additional lifetime concern:

- `source-1/console.log:778` identifies thread 41, `DocumentInventoryWorker`.
  That thread's stack contains QObject/layout/QWidget/QHeaderView/QTableViewWrapper/
  QStackedWidget/QDialogWrapper destruction, then `SbkDeallocWrapperCommon`, and
  ends through `QThreadWrapper::run`.
- `baseline-4/console.log:710` identifies thread 40, `_ProfileJob`. Its stack has
  the warning path through QBasicTimer::stop and item/table/widget destruction,
  then Shiboken deallocation and the worker's run path.
- Independent read-only review confirmed both. GUI teardown on worker threads
  is direct evidence; Python cyclic GC as the exact mechanism is a hypothesis
  from these traces, not an explicitly named `gc_collect` frame.

Qt documents that GUI objects belong on the GUI thread and QObject deletion
across threads should use the appropriate deferred-deletion/lifetime mechanism:
[Threads and QObjects](https://doc.qt.io/qt-6.11/threads-qobject.html).
This finding changes the interpretation of the previous focus result: narrowing
the global filter mitigates the reproduced symptom, but does not establish that
GUI destruction is correctly confined or that PySide is independently defective.
A defensible upstream case must account for this thread/lifetime precondition.

A standalone candidate creates GUI widgets on the main thread and performs only
Python allocation/collection in a worker. One earlier explicit-worker-collection
trial (`thread-visible-forced`) exited `3221226356`/`0xc0000374`; a preceding
window-filter control timed out. The owner reported a matching Windows fault
popup at about that time. No causal connection to a security classifier is
established. Targeted, elevated read-only process inspection after the timeout
found no matching candidate Python processes remaining.

Later instrumentation recorded destruction-thread identities and added controls
for GUI-thread collection or explicit GUI-thread disposal. Both subsequent global
worker-collection runs and the GUI/window controls exited 0. Consequently neither
repeatability nor equivalence to the original crash path is established. The
earlier failing candidate bytes were not independently hashed/snapshotted before
instrumentation, so the current script must not be described as a confirmed
minimal reproducer. Raw commands/logs/outcomes remain retained, including negative
results; no repeat has been relabelled as a pass or crash.

One delegated diagnostic turn was explicitly halted by an automated security
classifier; the owner reported further interruptions. The exact classification
reason is unavailable. This is not an exploitability or severity assessment.
Further crash/debugger experiments were stopped after the repeated reports.
Process-local Windows error-dialog suppression was added for the final bounded
trials; it does not change GC, successful-exit criteria or nonzero crash results.
No system debugger registration/security setting was changed.

The reserved `devtools/qt_focus_repro/` contains an explicit incomplete-status
README and environment pins, not a falsely labelled reproducer. All candidates,
trace helpers and generated results remain in ignored
`scratch/qt-focus-reduction-20261110/`; they are not ready to attach as a supported
PySide-only failing case. No external repository, account, issue or upload was
created. Remaining work is to establish correct GUI-thread lifetime in the
application and/or obtain a reliable standalone case with clearly stated legal
ownership/thread preconditions. The previous 40-cycle focus-mitigation evidence
remains historical bounded verification, not closure of this new finding.

## Native heap capture and window-owned opening focus

Owner explicitly authorized beginning native debugging and a matching source
build after the bounded version/styling comparisons. Primary owns the integrated
result, debugger/captures and this record; desktop specialists own the isolated
source build and the reviewed per-window focus implementation. Acceptance
independently inspects isolation, matching symbols, code/lifetimes and raw final
results. No live profile, private archive, production, signing, publication or
release work is selected. Financial services, evidence and all existing journey
assertions remain unchanged. Historical unresolved-heap statements below describe
the state before this focus-scope change.

### Native evidence and source build

Obtained only the x64 console engine/standard extensions from Microsoft's official
WinDbg package into ignored `scratch/qt-native-debug-20261109/tools/`, using HTTP
ranges rather than downloading the full 1.2 GB bundle. CDB, dbgeng, dbghelp and
symsrv Authenticode signatures are valid Microsoft signatures. No AppX install,
system debugger registration, registry/IFEO/PageHeap change or unrelated-process
attachment was performed. CDB launches only the synthetic target and its new
descendants; Windows venv Python is a launcher, so `-o` is required to follow its
real Python child. `-hd` disables the debugger's implicit debug heap.

The target environment allowlists OS variables rather than copying credentials;
profile/appdata/temp directories and keyring are isolated. An initially omitted
SystemDrive variable caused generated Windows cache files beneath a literal
workspace `%SystemDrive%` directory. Moved that generated directory beneath the
ignored diagnostic tools directory and corrected the future launcher environment.
No source/private profile was involved. Full-memory dumps remain ignored and
were taken only from the newly launched synthetic Python target.

Setup attempts 1–3 are retained but are not successful captures: the first watched
only the venv launcher, the second stopped at the child's initial breakpoint,
and the third reached the internal heap breakpoint without a usable stdin pipe.
Authoritative baseline capture is `baseline-4`: one cycle passed, then the next
reported `Critical error detected c0000374`. Windows stopped at an internal
`int3` (`80000003`) before the named heap exception; live `.ecxr` failed. The
current breakpoint registers/stack and full-memory dump were saved, not an
invented `c0000374` exception context. Dump size: 1,082,671,105 bytes. Initial
frames had export symbols only, showing free/heap checking below PySide QObject
wrapping and Qt application event filtering. Debugger exit 0 denotes completed
capture, not a passing application run. Independent targeted PID-only follow-up
confirmed that the debugger, venv launcher and actual Python child had exited.

Built the official 6.11.2 PySide/Shiboken source against matching Qt base/PDF SDKs
with release Python 3.13.15, MSVC 19.51.36260 x64, CMake 4.3.1-msvc1,
Ninja 1.13.2 and Qt libclang 20.1.3. All downloads/checksums, exact commands,
versions and native artifact hashes are under `source-build/`. The successful
module subset is `Core,Gui,Widgets,Network,Test,Pdf,PdfWidgets`, with
`--relwithdebinfo --no-strip --no-qt-tools --limited-api=yes --parallel=4`.
Network is a QtPdf dependency. Shorter build paths fixed a Ninja/CMake path-length
failure. All native compilation/linking completed in 117.9 seconds; packaging
then required an empty generated omitted-Designer plugin directory and an
`--only-package` retry. Neither upstream nor application source was patched for
the build. Matching PDBs and generated wrappers are retained. This demonstrates
this tested compiler/SDK subset, not universal toolchain compatibility.

Fresh `source-1` capture uses those rebuilt binaries, not mismatched PDBs applied
to pip-wheel DLLs. Preflight verifies package origins and unchanged versions of
the other 79 baseline packages; build-environment dependencies are not admitted
into the application's runtime. Three cycles passed, then cycle four reached
the same critical-heap breakpoint. Dump size: 1,087,365,096 bytes. Private matching
PDBs resolve `PySide::getWrapperForQObject` at local `pyside.cpp:843`, generated
watched-QObject conversion/event-filter code, `QObjectWrapper::eventFilter`,
and Qt application event filtering. Corrected offline `.ecxr` restores the saved
breakpoint context; the earlier offline log that selected thread index 2 is not
the authoritative exception-context analysis. One folded generated frame is
labelled `QWinEventNotifierWrapper`, but its ownerClassName local is `QObject`;
this is not evidence that the watched object is a QWinEventNotifier. These
source-backed frames locate detection/cleanup, not the first corrupting write/free
or the Python filter subclass by themselves.

### Controlled focus-policy comparison and implementation

The application-wide opening-focus filter was a concrete lead from that native
path. Its Python type check happens after PySide has already converted the
watched QObject for the Python callback, so checking for dialogs inside that
callback does not restrict which native objects cross the binding boundary.

A narrow diagnostic import overlay disables only `install_initial_focus` while
retaining all colors, repolishing, test assertions and normal GC `(2000,10,10)`.
Two enabled controls heap-aborted. Five independent disabled runs completed all
four archive cycles and exited 0 (20 cycles); both complete journey sizes also
passed with clean exits. Logs confirm filter presence/absence. This implicates
the policy's installation/callback/focus path; the intervention alone does not
separate those effects or prove the native library's original defect. Plugin,
runner, hashes and raw results are retained in the ignored diagnostic directory.

Dropping automatic focus would lose the requested keyboard behavior. Keeping an
application-wide callback would continue observing unrelated Qt internals. Chose
explicit window-owned registration: each V2 task window retains a policy parented
to itself and installs it on itself. Shared styled surfaces pass their root;
startup/workspace and 13 additional editable task-dialog constructors explicitly
register. Three report/evidence/manifest surfaces with no eligible input require
no registration. Embedded views are excluded. No widget sweep, global Qt monkeypatch
or new native dependency is introduced into the product.

The existing eligible-input/tab-chain rules and context-bound zero timers remain.
An opening generation invalidated on hide/deactivate prevents stale queued work
from affecting a reopening or later activation. Destruction cancels context-bound
work; later user focus/typing is preserved. Focused tests cover ownership,
idempotence, unrelated/non-V2/embedded windows, hide/reopen, destruction and
deactivated queued callbacks in addition to existing account/category/Tab behavior.
The 17-file focus change is limited to the helper, registration sites and focused
tests. Existing correction-note changes are preserved. Qt remains pinned at 6.11.2;
the source build is diagnostic only and no GC workaround is shipped.

### Final verification and limits

Final source has one independent manifest with no drift across these checks:

- Unchanged four-cycle archive on normal pip 6.11.2: five offscreen and three
  native Windows fresh processes, **32 cycles passed**, every process exit 0.
- The same archive with source-built 6.11.2 bindings: **4 cycles passed**, clean
  exit, imports verified in the rebuilt package tree.
- A further source-built run under CDB after the fix: **4 cycles passed**, clean
  debugger/test exit, no fault marker or dump. `fixed-debugger-source-1` retains
  that positive control. Total unchanged archive coverage: **40 cycles** across
  ten fresh test processes. The reusable capture tool now defaults to protecting
  the fixed source manifest; `--source-state original` instead requires the
  preserved original-source fingerprint.
- Integrated selection: **17 passed offscreen and 17 passed native Windows**.
  Each mode includes all 11 correction/journey/category child process records
  with exit 0 and no timeout; full journey assertions are unchanged.
- Focus suite: **12 passed** in the desktop specialist's isolated offscreen run
  and **12 passed native Windows** on final source. Disposal/cancel coverage:
  **2 passed**, retaining PDF buffer/hidden-close and destroyed-host async checks.
- Changed-file Ruff and diff checks passed. Independent review found no material
  focus/lifetime or verification finding. Actual native category rendering shows
  readable Segoe UI, first-name focus and existing colors/budget controls. Native
  artifacts confirm the Windows plugin and 100% scaling. Native full-journey
  artifacts cover 1050x700/1280x800 and retain the review/correction/report UI.

The known reproduced Windows failure is resolved by narrowing the focus policy
under these bounded checks. General heap safety, the original native invalid
instruction and whether an upstream PySide/Qt defect should be reported remain
unproven. No installed/offline/macOS/accessibility-tool or actual human acceptance
is inferred. The original diagnostic archive is preserved; it imports current
code and now passes, as expected after the application change. Raw earlier
failures, native dumps, original source manifest, symbols/build inputs and control
results remain available for future investigation. At this diagnostic checkpoint,
the changes were uncommitted; the later owner-requested local commits are recorded
in the closeout above. No release action was performed.

Durable sanitized native/build/control/final-result metadata and a compact native
stack are in [native investigation evidence](../../devtools/qt_heap_crash/native-investigation-20261109.json).
Full dumps, builds, tools, logs and screenshots stay under the ignored
`scratch/qt-native-debug-20261109/` directory. `capture.py` and `verify_fix.py`
are the retained diagnostic entry points; the latter protects the final source
manifest and runs the original archive without an overlay or GC changes.

## November 9: workflow styling and native diagnostic feasibility

Owner requested the proposed styled/unstyled comparison, then asked about
source-built PySide6/Shiboken for meaningful native stacks and supplied two
Stack Overflow references. Primary owns this experiment and record; acceptance
independently checks the import overlay, source hashes, raw outcomes and runtime
artifacts. Desktop separately researches official build/debug guidance and
read-only local tool availability. No product UI, financial logic, assertions,
dependency pins, live profiles, services or release artifacts are changed.

Implemented a diagnostic import-time AST overlay in ignored
`scratch/qt-unstyled-20261110/style_probe.py`, selected explicitly as a pytest
plugin by adjacent `run_probe.py`. It transforms ten presentation sites in only
`v2_form_state`, `v2_review_navigation` and `v2_import_account_review`: three
stylesheet calls, two unpolish/two polish calls, two selection palette colors
and the staged-row BackgroundRole color. Both arms have the same counters;
styled retains each original call, unstyled bypasses it. Counters in the latter
mean reached/bypassed attempts, not executed Qt polish operations. No global
Qt method monkeypatch, GC manipulation, forced collection, delays, retries or
object-retention workaround is used.

Field-state validation, properties, accessible descriptions, initial focus,
geometry/repaint updates and navigation event handling remain. Full journeys run
their original scenario nodes directly, with each size in its own fresh process;
assertions are unchanged. Every probe uses synthetic disposable profiles, null
keyring and isolated HOME/USERPROFILE/APPDATA/LOCALAPPDATA/TEMP/TMP, with user-site
imports explicitly disabled. All 516 frozen Python sources remained unchanged.
The baseline is Python 3.13.15, Qt/PySide6/Shiboken 6.11.2, normal GC thresholds
`(2000,10,10)` and unchanged other dependencies.

| Probe (one fresh-process trial per arm) | Styled | Unstyled |
| --- | --- | --- |
| Four-cycle archive, offscreen | Cycle 4 heap abort | Cycle 4 heap abort |
| Complete journey, 1050x700, offscreen | Heap abort at scenario line 343 | Heap abort at scenario line 343 |
| Complete journey, 1280x800, offscreen | Heap abort at scenario line 343 | Heap abort at scenario line 343 |
| Four-cycle archive, native Windows | Cycle 4 heap abort | Cycle 4 heap abort |

All eight probes exited `3221226356` / `0xc0000374`, without timeout.
Runtime artifacts confirm the requested actual `offscreen`/`windows` plugins
and Segoe UI. Inspected paired actual 1050x700 staged-review screenshots
`06-category-manager-cancel-keeps-staged-choices.png` in each offscreen archive's
first-case artifacts: styled shows green fields/blue action; unstyled has native
fields/button/selection, with the same staged choice and review note. This is
diagnostic visual confirmation, not new usability or human acceptance evidence.

Independent acceptance review confirmed all ten sites, unchanged source hashes
and all eight failure signatures. Removing these workflow shading/repolishing
operations does not eliminate the fault: they are not necessary for this
reproduction. This does not exonerate every rendering/lifetime path. Native
painting, fonts, frames and account display native palette-role remapping remain;
instrumentation changes allocations, though both arms reproduce the signature.
Product colors remain unchanged. Raw logs/screenshots/plugin/runner are retained
in that ignored scratch directory; the durable
[style comparison artifact](../../devtools/qt_heap_crash/style-comparison-20261109.json)
retains commands, outcomes, runtime examples, counters and harness/source hashes.

Reference investigation:

- [CPython C-extension example](https://stackoverflow.com/questions/64957662/cpython-memory-heap-corruption-issue)
  resolved an ownership/reference-count error when returning boolean globals.
  The general use-after-free category is relevant to a Python/C++ boundary, but
  is not evidence that ParseTrail has that particular defect. Its literal old
  True/False deallocation mechanism differs from our Python 3.13 runtime:
  [CPython documents booleans as immortal since 3.12](https://docs.python.org/3.13/c-api/bool.html).
- [Odoo/Windows example](https://stackoverflow.com/questions/61935980/process-finished-with-exit-code-1073740940-0xc0000374)
  reports a system UTF-8 locale workaround, with mixed follow-up results and no
  demonstrated shared native cause. Read-only local measurement: ANSI code page
  1252, OEM 437, preferred encoding cp1252, filesystem encoding UTF-8, Python
  UTF-8 mode off. No Windows language/locale setting was changed. Process-only
  PYTHONUTF8 is not equivalent to changing the system ANSI code page; no locale
  experiment was claimed.

Source-built PySide6/Shiboken can be imported from Python and debugged natively:
[Qt's mixed-debugging guide](https://doc.qt.io/qtforpython-6/tutorials/debugging/mixed_debugging.html)
explicitly supports attaching a C++ debugger to Python. Keep exact matching
PYD/DLL/PDB files and generated wrapper sources; prefer a release-compatible
symbol build first to preserve the failing runtime, verifying the selected
release's actual build options. Qt symbols must match the DLLs actually loaded;
rebuilding Qt is optional when only binding frames or matching Qt symbols are
needed. Importing source-built modules alone does not enrich a Python traceback.
An allocation/free fault may precede the visible detection stack, so a native
debugger plus targeted heap diagnostics may still be needed. No global
`python.exe` PageHeap setting should affect unrelated owner work.

The [Windows full-Debug instructions](https://doc.qt.io/qtforpython-6/building_from_source/windows.html#creating-debug-builds)
use `python_d.exe` and debug Python libraries; that is a separate environment,
not an interchangeable replacement for the current release interpreter.
Required native tooling is not currently on PATH (`cmake`, `ninja`, `cl`, `cdb`,
`windbg`, `gflags`). Exact-path vswhere reports Visual Studio Community 2026,
but C++ workload/toolset availability is not established. No compiler/debugger
installation, Qt/bindings source build or native-debug run was undertaken by
this feasibility check; the meaningful native corruption stack remains missing.

Owner subsequently confirmed installing the C++ toolchain while learning Rust.
Additional read-only exact-path inspection confirms Visual Studio Community 2026
with the x64 C++ tools component, MSVC `14.51.36231` (`cl.exe`), `VsDevCmd.bat`,
and bundled CMake/Ninja under `C:\Program Files\Microsoft Visual Studio\18\Community`.
Their absence from the original PATH is not absence from the machine. The usual
Windows Kit x64 `cdb.exe`/`gflags.exe` paths and `C:\Qt\MaintenanceTool.exe`
are absent; this does not prove no alternate installation exists. Existing
Visual Studio native debugging is the first path to try before a large source
build. Verified the exact upstream
[v6.11.2 options source](https://github.com/pyside/pyside-setup/blob/v6.11.2/build_scripts/options.py):
`--relwithdebinfo` is supported for release-mode builds with debug information,
as are `--module-subset`, `--qtpaths` and `--parallel`. This resolves the earlier
build-option uncertainty. A source build would use matching 6.11.2 Qt development
files and PySide/Shiboken source, a separate environment with Python 3.13.15,
Qt-provided libclang and retained matching PDB/generated wrapper sources. No
compiler/debugger/SDK download or build has started from these read-only checks.

## November 9: bounded Python and Qt version comparison

Owner explicitly authorized trying several runtime combinations for the recurring
Windows heap fault. Primary owns the comparison, integration and this record;
desktop specialists own disjoint candidate environments and acceptance separately
reviews isolation, archive fidelity and observed outcomes. This is diagnostic
work with synthetic disposable profiles, without changing the application,
financial policy, tests, live profiles, production or release artifacts.

Baseline: Windows 11 x64, CPython 3.13.15, PySide6/Qt/Shiboken 6.11.2,
pytest 9.1.1, pytest-qt 4.5.0. New virtual environments hold matched Qt families;
the 79 other installed package versions are shared read-only with the baseline.
The Python 3.13.9 control uses the installed older interpreter with the same
Qt 6.11.2 and other dependencies. These controlled overlays are diagnostic
environments, not independently resolved clean installations. Actual module
origins and Qt runtime versions are asserted; loaded DLL origins are not
inventoried. The baseline environment and dependency pins remain unchanged.

The controller hashes all 516 Python files in `client/src`, `client/tests` and
`devtools/qt_heap_crash` before and after each probe. All remained unchanged, and
independent review verified the frozen reproducer/helper/declaration hashes.
The diagnostic README was deliberately updated with these results; its
historical hash is not claimed to match. Each probe has fresh
HOME/USERPROFILE/APPDATA/LOCALAPPDATA/TEMP/TMP directories, null keyring and
synthetic profiles. Normal GC stays enabled with thresholds `(2000, 10, 10)`;
there are no added waits, retries, GC suppression, forced collection, object
retention or relaxed assertions. Full journeys retain their existing separate
child processes and both 1050x700/1280x800 sizes. Parent invocations use `-s`;
journey children omit it, with redirected user directories mitigating user-site
contamination. No human interaction or acceptance is established by these runs.

Offscreen comparison (one fresh-process trial per cell):

| Python | Matched PySide6 / Qt / Shiboken | Archived four-cycle review | Both full journey sizes |
| --- | --- | --- | --- |
| 3.13.15 | 6.11.2 baseline | Heap abort in cycle 4 | Both child processes heap-aborted |
| 3.13.15 | 6.11.3 | Heap abort in cycle 4 | Both child processes heap-aborted |
| 3.13.15 | 6.10.3 | Heap abort in cycle 4 | Both child processes heap-aborted |
| 3.13.9 | 6.11.2 | Heap abort in cycle 4 | Both child processes heap-aborted |
| 3.13.15 | 6.12.0 + Pdf 6.12.0.140 | Four bodies passed, then fatal shutdown and timeout | Both passed; clean process exit |

These heap aborts are `0xc0000374` / unsigned exit `3221226356`. The archived
wait at line 174 detects corruption during GC; this does not identify where
memory was corrupted. An additional native Windows Qt 6.10.3 probe heap-aborted
in cycle 2. Both native journey sizes instead reported deleted `QAction` wrappers
in workspace `_profile_job_busy`/refresh and failed. Runtime artifacts confirm
the `windows` plugin, Segoe UI and 100% scaling. This gives additional lifetime
failure evidence; it does not establish its causal relationship to heap corruption.

Qt 6.12.0 requires the separately packaged `PySide6-Pdf==6.12.0.140` to supply
the application's QtPdf/QtPdfWidgets imports. Installed that wheel only in its
candidate environment with no dependency resolution, verified its Essentials
6.12.0 requirement and candidate module origins, and recorded it separately
from the unchanged non-Qt dependencies. Its archived four test bodies passed,
then the process reported a fatal abort and Windows access violations after the
pytest summary, apparently during interpreter shutdown (no Python frame).
A pytest pass summary before a process crash is not a
successful probe. The process remained alive until the 240-second timeout;
the controller terminated its own test process (return code 1 after cleanup,
not a natural crash exit). Both complete journey sizes passed with clean process
exit in 11.112 seconds. This is promising but insufficient for adoption while
the archive still fatally fails. Neither 6.12.0 probe logged `0xc0000374`; its
shutdown abort/access violations are a separate observed failure signature.
The taskkill tree-cleanup attempt reported access denied; the controller's
fallback killed its own process. This was an OS cleanup error, without an
approval-review rejection or any targeting of unrelated processes.

Across twelve probe invocations, the bounded comparison found no fully clean
replacement and weakens a Python-3.13.15-only regression hypothesis.
No candidate justifies changing
the 6.11.2 pin or claiming the fault fixed. Further runtime expansion is not
selected; any future investigation should use native memory/lifetime diagnostics
to locate corruption rather than hide it. Independent acceptance review found
no source/assertion/GC workaround and agreed with retaining the existing pin.
Final independent review matched all twelve durable result records and five
runtime records against raw evidence after path sanitization, including the
6.12.0 distinction between a clean journey and a fatal archive shutdown.

Raw setup logs, runtime metadata, command arrays, per-probe `result.json`, stdout,
screenshots, controller and frozen source manifest are under the ignored
`scratch/qt-version-matrix-20261109/` directory, partitioned by runtime and probe.
The durable [comparison artifact](../../devtools/qt_heap_crash/version-comparison-20261109.json)
retains all twelve result records/command arrays, sanitized runtime metadata,
and hashes of the exact scratch controller and source manifest.
Representative invocation from the repository root:

```powershell
& .\client\.venv\Scripts\python.exe -s scratch/qt-version-matrix-20261109/matrix.py probe 6.11.3 --kind archive --mode offscreen --trial 2
& .\client\.venv\Scripts\python.exe -s scratch/qt-version-matrix-20261109/matrix.py probe 6.11.3 --kind journey --mode offscreen --trial 2
```

The controller deliberately refuses to overwrite an existing trial directory.
The archived reproducer remains available independently of these scratch
environments. No current-source correction-note implementation was reverted.

## November 9: separate saved review notes from correction reasons

Owner approved separating read-only saved context from a new correction draft.
Selected outcome: ordinary cash/card/register review shows **Saved review note**
above an initially empty **Reason for correction**. Untouched reviewed entries
have no unsaved cue, enabled correction/withdrawal action or discard prompt.
An actual category change (or already-supported card accounting-date correction)
requires an explicitly authored reason before confirmation. Reason-only input
is an unsaved draft and can support the separate explicit withdrawal confirmation.
No stored note silently authorizes either action. Cancel retains the draft;
successful save refreshes the active saved note and clears the editable reason.

ui_ux reviewed the interaction before implementation: one compact read-only
context row, at most two wrapped lines with keyboard-readable/copyable overflow;
preserve at least four cash/three card table rows at 1050x700 and never hide
nonempty staged work. Row-switch-back/category management/same-entry refresh
retain appropriate drafts. A changed active entry key invalidates its old draft.
Pending/multi/external-owner flows keep their existing staging/ownership model.

Primary owns integrated result, contracts/this record and existing report/cue
regressions. Desktop owns shared/adaptor presentation and focused isolated
correction scenarios; acceptance independently verifies the integrated result.
Synthetic/disposable profiles only. No core/schema/accounting/source-policy
changes, live profiles, production services or release work are selected.
The archived native fault stays deferred; focused Qt cases use process isolation.

Implemented the model in the shared ordinary review plus cash/card adapters
(register inherits card behavior). Saved context is a neutral, read-only
QPlainTextEdit with keyboard/mouse selection and scrolling, bounded to two lines.
Pending/multi/externally owned rows hide it. Reason-only edits are real drafts
but do not enable category correction; correction/date edits show **Unsaved
correction** and require an explicitly entered reason. A user may deliberately
enter the same text as a prior reason; text inequality is not an authorization
rule. The separate withdrawal confirmation still describes the inverse effects.

Fixed the underlying presentation leaks: a row without a matching draft now
clears the preceding row's reason, and asynchronous draft restoration checks both
row ID and active entry key. Same-entry edits/category manager/cancel retain the
draft; stale-entry proposals are removed without discarding unrelated row drafts
or captured staged notes. Successful writes clear the current draft and show the
replacement entry's saved reason. Only an empty staged-summary strip hides in
correction mode; unrelated nonempty staged work stays visible. No ledger/schema,
source policy or financial handlers were changed.

Final native inspection exposed two concrete implementation issues and rechecks:
at 1050x700 the long-note form initially left only 107 pixels versus the required
120 for four cash rows; compacting existing decision margins/gaps recovered the
space without smaller fonts/controls. After a confirmed write disables its action,
native Qt could have no focused widget. Successful refresh now restores table
focus only when this view is visible, its window active and focus absent, leaving
existing focus/other windows alone. Card date remains before saved context/reason
in keyboard order. The focused helper also uses a real Tab event to recover from
an initially unfocused native surface. Long saved notes explicitly enable
keyboard selection, which read-only QPlainTextEdit did not provide by default.

Verification and observations:

- Final offscreen selection: **7 new correction scenarios passed; 2 original full
  journeys failed with heap corruption**, 28.63s total. Each scenario ran in a
  fresh child. New coverage includes long/max-500-character notes at 1050x700 and
  1280x800, keyboard select/scroll/Tab, reason-only/blank states, category-manager
  close, canceled confirmation, row-switch-back/same-entry refresh, save/withdraw,
  unrelated drafts, retained staged notes, stale replacement, card-date and fixed
  register-date policy. Earlier clean new-only check: 7 passed in 21.38s.
- First native combined run: **8 passed, 4 failed** in 45.09s. All original
  journeys/refusal/cancel/category-navigation cases passed; four new cases found
  the layout/focus issues above. After fixes, all **4 affected native cases passed
  in 14.05s**, with no assertion weakening. The other three new native scenarios
  had passed in the first run. These are targeted rechecks, not a claim that a
  single final unchanged 12-case command passed.
- Existing report-return/cash cue regressions were strengthened: **2 passed in
  4.09s**. Targeted existing async/filter, unrelated common proposal, captured
  batch note and card category/date retention checks: **4 passed in 7.29s**.
  Counts overlap; they are not summed as unique coverage.
- ui_ux inspected actual final native images, including 1050x700 long/canceled
  correction and saved card/register states. Two full note lines, internal
  scrolling and four full cash rows are readable; no material remaining design
  finding. Primary inspected the final long-note image too. A final minor hint
  now says "enter a new reason" consistently with the field terminology.
- Acceptance attempted the native 1050x700 report-to-correction goal using its
  own synthetic data and a 500-character original reason, without a control
  walkthrough/new-test inspection. No product wrong turns or assistance were
  reported. It distinguished saved context/blank new input, canceled then saved
  Food-to-Travel correction, returned to unchanged November report dates/tab,
  saw Food $0/Travel $4/total $4/one pending Tea, and declined withdrawal with no
  saved change. PageDown scrolled the long note; Tab reached the editable reason.
  Read-only verification found exact original source/evidence, preserved original
  note, exact new reason, one balanced correction, net checking -400 minor and no
  Tea allocation or withdrawal. This was an agent with prior ParseTrail familiarity,
  not unfamiliar-human acceptance. Its attempt did not separately author an
  unrelated pending draft; scripted checks supply that coverage.
- Acceptance's harness selected rather than deleted its final withdrawal draft
  when sending empty text. That final clear-state recheck was not performed and
  is not claimed. Its normal leave-review prompt then blocked harness shutdown;
  the agent identified and stopped only its uniquely titled disposable process.
  This is distinct from a product hang or crash. Earlier untouched/post-save
  defaults and data checks completed. No owner's app/profile was accessed.
- Eight changed/new Python files passed Ruff check/format; scoped diff checks
  passed. No extra dependency or commit was requested for this follow-up.

The general native/GC defect **recurred** during an intermediate offscreen mixed
run (8 passed, 2 full-child heap aborts) and again in both full journeys of the
final offscreen selection above, at the original post-correction wait (scenario
line 343). Process isolation therefore is not a sufficient guarantee as allocations
change. Native full journeys passed; targeted note scenarios passed on both modes.
A bounded read-only desktop review found no clear new ownership or direct
reason-signal recursion defect, but does not establish cause or innocence. The
crashes remain failures, not skipped/retried/GC-suppressed successes. No deeper
root-cause experiment or production workaround was added. The existing archive
stays unchanged; further investigation remains a separate decision. Integrated
offscreen stability is incomplete despite the implemented/verified note behavior.

Evidence: `scratch/v2-correction-note-primary/` and adjacent
`v2-correction-note-primary-{focused,integrated,retention,native,final-offscreen}.log`,
`scratch/v2-correction-notes-offscreen-clean/`,
`scratch/v2-correction-notes-native-fixes/`, and
`scratch/correction-note-acceptance-20261109/` (images 03-11 and seed.json).
Human acceptance and broader platform/installed/release readiness remain separate.

## November 8: one staging flow for ordinary review

User clarified that identical CSV headers normally create institution/account
ambiguity, with declared column meanings fixed by that context. The earlier
Amount/ReportedBalance alternatives were deliberately contrived test inputs;
normal imports require no such semantic question. No additional parser/accounting
policy change is selected here.

Selected outcome: remove competing immediate-post and staging routes for new
ordinary cash/card/register review. ui_ux established **Choose details → Stage
selected → Review staged → Confirm and post** before implementation division.
One and many rows use this same flow; correction/withdrawal and owning transfer/
repayment/loan/source/repeat routes retain their separate purposes. No new financial
rule, schema, live-profile, service or release scope is authorized.

Compared adding another table column with reusing the existing rightmost purpose
column. Chose **Review choice** with explicit **Not staged / Staged · not saved /
Reviewed** text, preserving the authoritative blocker/status column. Gentle row
fill/weight supplements text and remains meaningful under selection. Stage sits
beside the details form; one staged-summary strip shows total/hidden counts,
review/remove/clear actions. Captured proposal details remain inspectable. Later
form changes must visibly say **Changes not staged** and never silently change the
confirmation. The existing shared review note remains explicitly shared across
all staged rows; its captured value changes only when staging, not while typing.

Primary owns conversation, integrated result, journey/cue/repeat tests, docs and
this record. Desktop owns the shared ordinary GUI, cash/card row presentation,
navigation and staged-state/multirow checks. Test specialist adapts legacy ordinary
functional checks without changing correction/history routes or core expectations.
Integrity independently reviews confirmation/handler/stale/cancel boundaries;
ui_ux rechecks actual rendered states; fresh goal-only acceptance follows.
All work uses disposable synthetic data and preserves earlier working-tree edits
and owner-running windows/profiles.

Implemented the single pending-review path and a leading **Review choice** column
with text/bold/gentle fill. Staging creates no journal entry. Remove selected affects
only captured proposals; Clear keeps an unrelated current form draft; Next unstaged
skips captured proposals. Captured purpose/category/date/note stay inspectable and
are the only values used by exact confirmation. New-entry direct handlers refuse
even if a stale control is manually enabled. Saved correction/withdrawal and owning
event routes retain their separate guards. HSA component/unknown source text and
whole-liability principal/interest limits remain beside confirmation effects.

Integrated findings fixed:

- Goal-only reviewer completed staging Coffee/Tea, hiding both by filtering,
  inspecting/canceling exact confirmation, removing Tea and posting only Coffee.
  The report showed Food $4.00, four pending rows, all-profile scope and date/coverage
  qualifications. Source evidence and correction were discovered afterward.
- Filtering/canceling initially produced false **Changes not staged** badges from
  old individual drafts. Successful staging now establishes the captured selected
  draft baseline, leaving unrelated drafts alone. Fresh-process informed recheck
  confirmed truthful badges and retained Tea choices, removal preserving Coffee,
  Clear returning to Not staged/Ready to stage, then posting Coffee only. Evidence
  `scratch/staging-goal-acceptance/` and `recheck-05-after-cancel.png`,
  `recheck-07-cleared-ready.png`, `recheck-13-correction-route.png`.
- Clear initially refreshed the table but left the form saying Staged. Its bound
  UI action now refreshes both without discarding the current proposal.
- Native 1050×700 checks exposed two real layout regressions (card table below
  three rows, partial-assignment cash table below four). Compacting the embedded
  staged strip restored both; **2 native passed in 4.89s** without weakening the
  visible-row criteria. Stage state remains first/visible when other card columns
  need horizontal scrolling.
- ui_ux found a stale event headline still saying two stages were kept after
  removal/clear. Preview-close feedback now reports only that nothing was posted;
  the strip owns the current count. Its full focused file passed **3 cases in
  9.97s** with normal GC, including removal/clear feedback assertions. Final
  native rerun passed **3 cases in 7.94s**, artifacts `scratch/v2-staging-final-native/`.
- Temporary staged confirmations now explicitly schedule GUI-thread disposal;
  tests verify dismissed/confirmed dialogs are destroyed and normal `gc.collect()`
  remains safe in the focused lifecycle. Model reset does not emit nested staged
  data-change notifications. Models retain one Qt base with shared presentation
  methods. These changes do not establish that every lifecycle issue below is fixed.

Verification to date (overlapping counts, not unique coverage): core independent
financial batch **19 passed**; legacy cash/card/purpose **23 passed**; remaining
ordinary async/HSA/register/repair **67 passed, 1 obsolete text assertion corrected
and focused recheck passed**. Shared helper uses real stage/preview/write services
and replaces only modal interaction; native journeys operate actual confirmations.
Focused stage/multirow **16 passed**, earlier native stage/multirow **15 passed**,
then final focused lifecycle/clear **3 passed**. Primary native full journey/cues/
repeat/category/partial-header **16 passed, 2 layout failures** before the two
native fixes above. Separate primary cues/repeat/category/partial-header group
**14 passed** offscreen. Meaningful existing accounting/date/provenance/stale/
cancel/history assertions were preserved; obsolete immediate-post expectations
were adapted rather than bypassing the new flow.

Current unresolved verification: repeated mixed legacy/core+Qt runs expose Windows
heap corruption `0xc0000374` during Python garbage collection, including native
and offscreen. Pure native task journeys and both independent attempts completed;
mixed-suite stability is not established. GC suppression/retaining all garbage
was diagnostic only and is not a production or passing-check workaround. Explicit
dialog disposal made the pure four-case journey pass, but did not cure the mixed
suite. Model paint roles, mixed inheritance, data-change emissions, app fixture
ownership and several QObject ownership-edge probes have not resolved it. The
primary and a separate read-only Qt lifetime reviewer are narrowing the remaining
cause. A separate read-only lifetime investigation exhausted discriminating
source-level probes without proving a fix; its experiments/logs are in
`scratch/qt-lifetime-investigation/`. It also ruled out report-model detach,
weak owner links, report child callback replacement, thread joins, style
repolishing, live-wrapper release after native destruction and Python's debug
allocator as sufficient fixes. Indefinitely retaining report roots passed two
diagnostic runs but is **not** an implemented workaround or stability evidence.
Normal pure native task checks and goal attempts passed; a combined run still
fails. The next useful evidence is a native heap allocation/free stack; a native
debugger is not installed in this environment. No speculative lifecycle fix or
GC suppression is shipped. No live-profile, service or release action was added.

One minor separate usability observation was recorded: a report-return correction can
prefill the original review note and describe it as a new unsaved note, enabling
withdrawal without a new edit. No withdrawal occurs without confirmation. This is
distinct from the resolved staged-badge finding. The November 9 saved-note/reason
follow-up above implements and verifies its fix; the lifecycle fault remains open.
Actual human acceptance, OS-input/assistive technology, other scaling/platforms,
installed/offline behavior and release authorization remain separate.

### 100 ms harness pacing comparison

User requested a 0.1-second wait between test steps to check whether unusually
fast harness interaction explains the crash. Scratch-only `pacing_probe.py` adds
`QTest.qWait(100)` before QtBot mouse/key input actions and after direct Qt control
updates originating in the two reproducer test files. These waits process Qt
events. The application, worker synchronization, GC settings and object ownership
are unchanged; there is no garbage/object retention workaround. Zero-delay uses
the same instrumentation. Tests use disposable synthetic profiles, default
offscreen mode and the locked Python 3.13.15/PySide6/Qt 6.11.2 environment.

- Instrumented **0 ms control**: `0xc0000374` / process exit `-1073740940` during
  the second full journey. First full journey: **2.927s**, 161 input actions.
- **100 ms run 1**: same heap failure during the second full journey. First full
  journey: **20.279s**, the same 161 input actions.
- **100 ms run 2**: same heap failure during the second full journey. First full
  journey: **20.337s**, again 161 input actions.

Thus the requested waits were active and repeatably did **not** prevent the crash.
This does not rule out all harness/event-loop/lifecycle timing issues or establish
an application versus library cause; it rules out this pacing change as a remedy.
Evidence: `scratch/qt-lifetime-investigation/pacing-control-1.{log,jsonl}` and
`pacing-100ms-{1,2}.{log,jsonl}`. The scratch plugin can be reproduced from the
repository root with:

```powershell
$env:PYTHONPATH='scratch/qt-lifetime-investigation;.;client/src;client'
$env:PARSETRAIL_PROBE_PACING_MS='100' # use 0 for the instrumented control
$env:PARSETRAIL_PROBE_PACING_LOG='scratch/qt-lifetime-investigation/pacing-new.jsonl'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -p pacing_probe `
  client/tests/test_v2_core_journey.py client/tests/test_v2_qt_journey.py -q
```

### Zero-delay reproducer reduction

User requested bounded operation reduction rather than more speculative crash
fixes. All new experiments omit the pacing plugin; its scratch default is now
zero as well. No production files, financial rules, live profiles, Qt versions or
GC settings changed. Primary owns the integrated reductions; an independent
desktop specialist tested standalone report lifecycles and cross-checked a
two-cycle candidate.

**Smallest consistently failing scenario found:**
`scratch/qt-min-repro/test_short_review_cycle.py`, 176 lines plus existing test
fixtures/helpers, one expense-review/correction scenario parameterized four times
in one QApplication/process, each with a fresh synthetic profile. It contains:

1. Cancel the initial file picker, then import the synthetic CSV and create a
   checking account.
2. Open Review and create Food/Travel expense categories.
3. Stage Coffee; reopen/dismiss category management with staging retained; clear,
   restage and confirm **only Coffee** as a Food expense.
4. Open/close source evidence, then open Spending and inspect the Food entry.
5. Return to its source row and confirm Food → Travel category correction.
6. Wait for completion, verify exact journal state and dispose the window before
   the next fresh-profile iteration.

**Three fresh runs failed 3/3 with `0xc0000374`, after the first three cycles
passed, during the fourth cycle's post-correction worker wait (line 174).** One
of these runs was serial with no other probe process running. A single-cycle
control passed; a three-cycle control passed (`3 passed, 1 deselected`). This is
an empirical minimum for this tested workflow, **not proof of an absolute minimum**.
The wait is where corruption is detected, not an identified invalid-free site.

This removes all five preliminary core tests, income posting, date-range edits,
keyboard-navigation assertions, canceled correction, backup/export/restore and
reopening. Earlier two-cycle candidates crashed occasionally but independently
passed twice; they are not offered as reliable reproducers. A larger four-cycle
expense-only candidate also crashed in four fresh runs, but was not as small in
operation types. More aggressive combined cuts lost the failure in two runs.

Useful negative controls: headlessly preseeded report/correction setup passed;
the standalone report/all-tabs/drilldown/lifecycle specialist completed **1,800
cycles across ten subprocess probes** without this heap failure. Pure Qt table-
item and list-item cyclic-GC probes passed 100 cycles each. Thus reports alone,
simple Qt item cycles, and financial state alone did not recreate the failure.
Allocation/collection order still affects repeatability; no component is proven
to be the sole cause, and this is not yet a standalone binding-only reproducer.

Exact reproducer command from repository root:

```powershell
$env:PYTHONPATH='.;client/src;client'
& .\client\.venv\Scripts\python.exe -u -m pytest -p no:cacheprovider `
  -p client.tests.conftest scratch/qt-min-repro/test_short_review_cycle.py -vv
```

Single-cycle control appends the exact node selector
`::test_expense_review_correction[0]` to that filename. Three-cycle control uses
`--deselect='scratch/qt-min-repro/test_short_review_cycle.py::test_expense_review_correction[3]'`.
The selected conftest supplies synthetic-profile isolation and Qt fixtures, not
the old test-suite prerequisite sequence. Windows 11, Python 3.13.15,
PySide6/Qt 6.11.2, pytest 9.1.1, pytest-qt 4.5.0, offscreen Qt.

Machine evidence: `scratch/qt-min-repro/reduction-results.json`; canonical logs
`short-review-cycle-1.log`, `-2.log`, `-serial-final.log`,
`-single-control.log`, `-three-control.log`. Source SHA-256:
`478a7d32dfa9df448f8ba1e01fbc16e9ddaae7e8169e879d0e1eb5480cbf7415`.
The tested diagnostic source is kept byte-for-byte rather than formatted after
validation. Standalone negative probes/results are under `scratch/qt-min-repro/report/`.
Generator scaffolding errors were corrected before candidate comparisons and are
not counted as heap reproductions. Reduction work stops at this verified bound;
the native allocation/free stack and causal fix remain separate unresolved work.

### Comparison without pytest-qt and without the pytest runner

User asked whether accumulation belongs to the harness. Primary compared the
unchanged 176-line scenario above across runners, using the same locked runtime,
1050x700 offscreen UI, synthetic fresh profiles and normal automatic GC. No
input pacing, production edits or lifetime-retention workaround was added.

| Driver / runner | Fresh-process results |
| --- | --- |
| Original pytest-qt baseline (preceding reduction) | 3/3 crashed in cycle 4 after three passing cycles. |
| pytest with `-p no:pytest-qt`, small custom Qt driver | Both runs crashed: cycle 2 in run 1, cycle 4 in run 2. |
| Standalone `QApplication.exec()` with zero-timer scheduling, same custom driver, no pytest runner | Both runs passed six complete cycles and crashed in cycle 7. |

All four new crashes returned `-1073740940` / Windows heap corruption
`0xc0000374`. Their Python stacks again show garbage collection in the
post-correction worker wait at scenario line 174. The custom driver delegates
input directly to QtTest, waits through its own QEventLoop/QTimer and retains
only weak widget references until explicit close/deleteLater cleanup. It does
not use pytest-qt's wait blockers or plugin hooks. Both replacement modes assert
that no `pytestqt` module is loaded; the standalone runner imports the pytest
library only through shared fixture/decorator definitions and never invokes its
runner. All original exact journal assertions are retained. The canonical
scenario's SHA-256 was rechecked unchanged.

These results establish that **neither pytest-qt nor the pytest runner is
necessary**. The changing loop count is consistent with allocation/collection
order affecting detection; it does not prove a memory leak or identify an
application versus Qt/PySide ownership fault. Shared scenario/helpers, QtTest
input and repeated window/profile creation remain common factors. The
standalone has a real outer Qt event loop but still uses nested waits to reuse
the scenario. This is not a pure Qt binding reproducer or an ordinary human
session reproduction. All new comparisons are offscreen, not native-platform
acceptance. Existing native crash evidence remains separate.

An initial custom-driver trial using only `QTest.qWait()` timed out at initial
inventory loading in all eight attempts. It never reached the relevant journey
and is **not** evidence that this mode avoids heap corruption. Replacing that
wait with a custom QEventLoop/QTimer allowed the same scenario to execute and
exposed the crash. No cause is assigned to that separate timeout.

Scratch evidence and reusable drivers: `scratch/qt-harness-compare/`:
`plain_driver.py`, `test_without_pytestqt.py`, `plain-pytest-nested-{1,2}.log`,
`standalone/run_plain.py`, `standalone/run-{1,2}.log` and each run's
`result.json`. JSON is checkpointed before each cycle: after a native abort,
`active_cycle` identifies the unfinished cycle; `status.failed=false` only means
no Python exception handler ran, not that the process passed.

Reproduce from repository root:

```powershell
$env:PYTHONPATH='scratch/qt-harness-compare;.;client/src;client'
& .\client\.venv\Scripts\python.exe -u -m pytest -p no:cacheprovider -p no:pytest-qt scratch/qt-harness-compare/test_without_pytestqt.py -vv -x
& .\client\.venv\Scripts\python.exe -u scratch/qt-harness-compare/standalone/run_plain.py scratch/qt-harness-compare/standalone/new-run
```

Use a new output directory for each standalone run. Investigation remains open;
native allocation/free diagnostics remain the next discriminating evidence.

### Original journey combined into a single workspace session

User asked whether the failure is confined to test modularity/window turnover.
Primary generated `scratch/qt-harness-compare/test_single_session.py` from the
original full journey's UI steps, combining repeated statements into **one test,
one V2WorkspaceWindow, one V2Workspace instance and one profile**. Setup creates
one checking account and Food/Travel/Salary categories only once. Later imports
use the same account through the actual account picker. Synthetic statement
dates advance by month (October, November, etc.) to avoid duplicate/overlap
ambiguity. No root-window close/recreation, profile switch, backup restore,
test-boundary teardown, GC adjustment or input pacing occurs between statements.
Normal internal view changes on document selection remain application behavior.

Each statement preserves the original Coffee expense and Salary income staging/
confirmation, category-manager reopen with staged choices retained, clear/restage,
source-evidence dialog, scoped spending report, keyboard editing of report end,
Food drilldown back to Coffee, canceled then accepted Food-to-Travel correction,
and report return checking retained dates, exact $4 expense and $10 income.
Read-only assertions check the cumulative journal/correction counts, unchanged
workspace identity/profile/account count, each previous statement's pending row,
and the current statement's pending count. Report pending qualifications correctly
accumulate across the profile. The original save-original/backup steps follow
the planned eight statements; no valid run reached them.

| Same-session comparison | Result |
| --- | --- |
| pytest-qt, offscreen (`single-session-run-2.log`) | First statement complete; heap crash after accepting second statement's correction. |
| pytest-qt, native Windows rendering (`single-session-native-1.log`) | Same first-statement completion and second-correction crash. |
| Standalone QApplication event loop/custom driver, offscreen, no pytest runner or pytest-qt (`single-session-standalone-1.log`) | Same first-statement completion and second-correction crash. |

All three terminate with `0xc0000374` / `-1073740940`; stacks show garbage
collection during `test_single_session.py:321`, the post-correction worker wait.
Per-run `session-progress.json` checkpoints show completed `[1]`, current batch
`2`, `correction-confirmed-waiting`, normal GC enabled. The standalone asserts
pytest-qt is absent and reuses the same scenario, importing pytest only for the
shared definitions. Native runtime records verify the `windows` Qt plugin.
No application source, financial rules or dependencies were changed.

An initial scaffold run (`single-session-run-1.log`) completed the first
statement but stopped at a second-statement assertion copied from the one-document
test: it expected one pending source row across the whole profile. Corrected the
probe to expect two there (one per statement). This was a diagnostic expectation
error, not an application bug, and is excluded from the three crash comparisons.
The corrected scenario bytes were identical across those three comparisons.

**Conclusion:** separate test functions, separate profiles and root-window
turnover are not necessary. The suspected restriction to test modularity is not
supported. This is still software-driven reproduction with shared QtTest/modal
helpers, not proof of human-speed reproduction or an identified invalid-free
site. The manual single-profile journey remains a useful next comparison. The
crash remains unresolved and is not downgraded to a test-only failure.

Diagnostic generation, execution and artifacts remain in the same scratch area:

```powershell
& .\client\.venv\Scripts\python.exe scratch/qt-harness-compare/build_single_session.py
$env:PYTHONPATH='.;client/src;client'
& .\client\.venv\Scripts\python.exe -u -m pytest -p no:cacheprovider -p client.tests.conftest scratch/qt-harness-compare/test_single_session.py -vv -s --journey-artifacts scratch/qt-harness-compare/new-single-session
# Add --journey-native for native Windows rendering.
& .\client\.venv\Scripts\python.exe -u scratch/qt-harness-compare/standalone/run_single_session.py scratch/qt-harness-compare/new-single-session-standalone
```

Use a new output path for standalone runs. This is focused crash investigation,
not new usability acceptance, a production workaround or a release check.

### Human-speed single-session reproduction prepared

Owner requested a routine they can perform manually. Prepared a local handoff at
`scratch/qt-human-repro-20261108/`: `ROUTINE.md`, `Start-fresh-attempt.cmd`,
`manual_repro.py` and October/November synthetic checking CSVs. The 19-step guide
follows the combined-session probe, including the initial canceled file picker,
first-import account/category setup, stage/category-manager reopen/clear, expense
and income posting, source evidence, report end-date keyboard edits, drilldown,
canceled then accepted correction, return to report, and second import into the
same account/window. It identifies November's accepted correction as the observed
automated failure point and specifies expected totals and profile-wide pending
counts. No backup/restore/profile switching is part of the manual sequence.

Every launcher invocation creates a new uniquely named attempt directory without
overwriting earlier profiles. The child process receives isolated HOME,
USERPROFILE, APPDATA, LOCALAPPDATA, null keyring and explicit fresh preferences.
It creates the same single-format fixture-signed catalog using an ephemeral key;
only public trust material is persisted. The profile starts with zero accounts,
sources and journal entries. Startup verifies native `windows`, normal GC and
absence of pytest modules. Standard UI source runs without automated inputs,
test helpers, GC tuning or pacing; Qt file dialogs remain non-native as in the
comparison. Title identifies the human synthetic attempt; initial size is
1050x700. Owner-running windows/profiles and other applications are untouched.

A separate parent process captures stdout/stderr including faulthandler output
and persists the actual child exit code in `exit.json` after termination. Each
attempt retains `review.db`, isolated catalog/preferences, `runtime.json` and
`console.log`. `last-attempt.txt` points to the most recent human launch; smoke
checks use a separate `last-smoke.txt`. There is no exception-recovery hook or
claim that a crash handler can keep corrupted memory running safely.

Verification: two separate native startup smoke attempts passed and closed
normally; the second used the final formatted launcher. They verified empty
inventory completion and visible native window without performing the journey.
Primary inspected the first startup screenshot with readable native fonts and
1050x700 client layout. Final scratch launcher Ruff checks passed. Evidence:
`attempts/20261109T073356Z-09a3c4f3/` and
`attempts/20261109T073453Z-6fa93019/` beneath the handoff directory.
The manual routine is a coached diagnostic, not a goal-only usability attempt.
Acceptance independently compared the guide/launcher/CSV bytes with the automated
probe and current controls; no blocking inaccuracies found. This was read-only
review of code and existing smoke artifacts, without further execution or owner
window interaction. Native-abort log preservation is structurally checked, not
verified by inducing a new crash in this manual launcher.
At preparation, actual human reproduction/acceptance remained pending; no human
journey was performed by the preparation or attested by startup checks.

### November 9: owner manual attempt did not reproduce the crash

Owner followed the routine at human speed and reported no crash after the first
or second accepted category correction (step 15 in each pass). Keyboard focus at
step 7 matched the prescribed order. Owner could not find **Review document**
at steps 4 and 18 and used **Review** in the left navigation instead. That route
variation is recorded rather than treating this as identical input replay. No
cause for the missing button's visibility is established by the report.

The pending qualification showed one source row on the October pass and two
on the second pass after November was imported/reviewed. This matches the intended
profile-wide total: one unreviewed Tea row from each document. The prior guide
wording led the owner to look for November information on the first pass.
Updated the guide to say explicitly that November is not present yet, and to
use the sidebar Review route the owner successfully found. This is a guide
correction, not a claim that the reported button visibility issue is fixed.

Exact synthetic attempt: `scratch/qt-human-repro-20261108/attempts/20261110T042942Z-48c97101/`
(the directory timestamp is UTC; the owner report is November 9 Pacific).
Primary read only that attempt's runtime/log files and queried SQLite with
`mode=ro`: **8 journal entries and 2 corrections**, confirming both corrections
were persisted. Runtime reports native Windows, Python 3.13.15, PySide6/Qt 6.11.2,
normal GC, human input and no smoke mode. The console log contained only the ready
message at inspection; no fatal traceback or `exit.json` was present. This records
survival through the reported operations, not a verified normal process exit.
The running application/profile was not changed or closed by the primary.

This is actual owner-performed diagnostic evidence of **non-reproduction** for
one two-statement attempt. It is not broad product acceptance, a completed
step-16 report recheck after the second correction, or proof of a stability fix.
Automated single-session native/offscreen and no-pytest failures remain valid.
Human pacing, event delivery, screenshot capture, helper behavior and allocation/
collection timing differ from those runs; this comparison does not isolate one
cause. Earlier 100 ms input pacing still failed, so speed alone is not established
as the explanation. No further owner repetition was required to record this result.

Follow-up on the owner's button question: inspected actual native comparison
screenshot `single-session-native-1/test_single_workspace_session/716688b8/02-imported-and-assigned-pending-review.png`
under `scratch/qt-harness-compare/`, plus current layout/handlers. The automated
target is visible below the Documents list, labelled **Review activity**, beside
Preview evidence. `review_document_button` is its internal variable; the label
becomes Confirm account for unassigned activity, Review activity for pending rows,
and Review document when fully allocated. The guide incorrectly treated its
constructor/internal name as the label in the imported state. Corrected the guide
to name Review activity and retain sidebar Review as an alternative. No hidden-
button visibility fault is established here; the screenshot shows the actual
first-import button visible. The previous wording about an unidentified visibility
issue is superseded by this label finding.

The owner clicked a different widget. For these already assigned checking
documents, both routes select the same Review page and call `_ensure_review_view`
for the selected source. The button additionally dispatches its pending-activity
route, whose repeated ensure call returns the already-created view. This is not
evidence that the manual user bypassed required assignment or reviewed different
activity. Tests target the widget directly with QtTest and did not explicitly
assert its visibility before this click; current screenshot inspection supplies
visibility evidence for this captured state, not a blanket attestation for all
software-driven clicks. No application code changed in this follow-up.

### November 9: one-second input pacing still crashes

User requested exactly one more automated run with one second between operations.
Ran the native Windows combined-session journey in one window/workspace/profile,
limited to the two statements in the owner's manual attempt. Scratch copy
`test_single_session_two_statements.py` differs from the earlier eight-statement
probe only in `range(8)` becoming `range(2)`; the original probe is unchanged.
No application source, financial rules, worker synchronization or GC settings
were changed. Owner's running manual attempt was not accessed or controlled.

Scratch pytest plugin `one_second_pacing.py` pauses before every QtBot
mouseClick/mouseDClick/keyClick/keyClicks invocation, including nested modal input.
Each pause uses a precise Qt timer and event loop, keeping events and Python Qt
workers able to run. The pause checks monotonic elapsed time to ensure a full
second. Text entry is one keyClicks operation per field; it does not add a second
per character. Harness waitUntil limits were multiplied by ten and the helper's
modal deadline increased from 20 to 200 seconds to prevent unrelated timeouts
from the added input time. No extra delay is added to successful condition checks
or application callbacks. Input metadata is flushed before each event, including
target visibility/enabled state and measured interval.

**Result: heap corruption again (`0xc0000374`, process exit `-1073740940`).**
The first statement completed its postings, evidence inspection, accepted
correction, report return/date/category checks and income check. The crash occurred
while waiting for the second statement's import worker to finish, before its
review/correction. The main Python thread was garbage-collecting inside the
ordinary wait at `test_single_session_two_statements.py:183`; the import worker
was in account/import commit code. This identifies detection context, not the
corruption's origin, and differs from the earlier post-correction detection point.

Pacing evidence: **150 input actions**, minimum recorded pause **1.0000s**,
minimum interval between recorded input dispatches **1.0005s**, last dispatched
input at **156.3779s** after plugin configuration. All 150 targets reported visible
and enabled, including the Documents **Review activity** button. This establishes
neither OS hit-testing/occlusion nor human acceptance; inputs still go directly
through QtTest. Automatic collection remained enabled, native runtime records
show `windows`, and one workspace/profile was retained throughout.

Evidence: `scratch/qt-harness-compare/one-second-native-1.log`, plus
`one-second-native-1/pacing.jsonl`, `result.json`, screenshots/runtime/checkpoint
under `test_single_workspace_session/fb29cc1d/`. The result JSON records source
hashes. Keep the tested scratch files unchanged for stack/line reproducibility.
The plugin is a diagnostic artifact, not a production dependency or general test
fixture; its incidental scratch lint findings do not affect the run and are not
represented as a clean repository lint check.

Command from repository root:

```powershell
$env:PYTHONPATH='scratch/qt-harness-compare;.;client/src;client'
$env:PARSETRAIL_ONE_SECOND_LOG='scratch/qt-harness-compare/one-second-native-1/pacing.jsonl'
& .\client\.venv\Scripts\python.exe -u -m pytest -p no:cacheprovider -p client.tests.conftest -p one_second_pacing scratch/qt-harness-compare/test_single_session_two_statements.py -vv -s --journey-native --journey-artifacts scratch/qt-harness-compare/one-second-native-1
```

Use new log/artifact paths for any separately authorized repetition. This one run
does not support one-second pacing as a remedy. The owner's successful manual
attempt remains separate positive evidence. Input timing alone does not explain
the difference; event delivery, helpers, screenshots and lifetime/collection
behavior remain unresolved factors. No additional test runs or speculative fixes
were added to this request.

### November 9: archive the diagnostic and contain journey tests

Owner explicitly requested retaining the smallest crashing test for possible
future troubleshooting, adjusting the ordinary journey test to avoid the crash,
and moving on. Active root-cause investigation is now **deferred at that request**.
The native defect is unresolved; this change is test containment, not an
application stability fix or release acceptance.

Primary owns the durable archive, documentation and integrated verification.
Desktop moved `client/tests/test_v2_qt_journey.py` byte-for-byte into the
non-discovered `qt_journey_scenarios.py`; all **90 assertions** and original
mouse/keyboard/modal/financial verification remain unchanged. The original test
entry point now has four lightweight wrappers: each full journey size,
refusal/retry and import cancellation. Every wrapper runs its exact scenario node
in a fresh Python process with its own QApplication, profile/settings/temp paths
and null keyring. Child process state cannot accumulate between these cases or
inherit prior core-test Qt state. The separate category-navigation test remains
in the parent. Three tests importing SOURCE/prepare_close now use the scenario
module directly. No product code, dependencies, accounting/evidence policy,
production service, live profile or owner-running window changed.

`qt_journey_process.py` uses the current interpreter and explicit source path,
ordinary child conftest discovery, disabled pytest cache, isolated environment,
180-second timeout and native/artifact flag forwarding. It retains command,
PID/result metadata and stdout/stderr. Nonzero exit, native abort or timeout
**fails the parent**; no retries, skips, GC suppression, garbage retention or
weakened expectations hide failures. Timeout/interruption/error paths terminate
and reap only the owned child/process tree. Successful child exit includes
normal test teardown and process exit; this does not test prolonged activity in
one process or prove that repeated imports/corrections are stable generally.

Durable archive: [devtools/qt_heap_crash](../../devtools/qt_heap_crash/README.md).
The original 176-line four-cycle diagnostic is retained byte-for-byte with
SHA-256 `478a7d32dfa9df448f8ba1e01fbc16e9ddaae7e8169e879d0e1eb5480cbf7415`.
Frozen contemporaneous helpers/full journey and synthetic declaration accompany
a runnable adapter, hash manifest, historical environment/results and sanitized
failure transcript. The adapter changes only the import to frozen support; its
snapshot points to the adjacent declaration. Four explicit cases collection-
checked successfully; none collect when the archive directory is normally
discovered. No further intentional crash execution was required. Historical
failure was observed before import/path adaptation, whose allocation-order
effects are disclosed. Application implementation remains a repository dependency.
Local Ruff exclusion, Git attributes and a narrowly scoped line-ending-hook
exception protect the frozen Python source bytes and line numbers.

Verification:

- Final current-code mixed offscreen sequence (five core prerequisites, four
  isolated journey cases, one category-navigation case): **10 passed in 23.51s**.
  Four distinct child PIDs exited zero, without timeout/retry. Earlier same-group
  containment check: 10 passed in 23.61s (overlapping coverage).
- Final native Windows journey/category replay: **5 passed in 21.26s**. All five
  runtime manifests explicitly record `windows`; all four child processes exited
  zero. Primary independently checked metadata/source parity and inspected the
  1050x700 corrected report screenshot: Food $0, Travel $4, retained October 1-15
  dates and one pending source row remained legible.
- First native containment replay failed four child setups because explicitly
  loading conftest as a plugin with `--noconftest` gave the wrong qapp fixture
  precedence, leaving children offscreen. This was a harness configuration failure,
  not heap corruption. Replaced it with ordinary child conftest discovery; the
  final native and offscreen runs above verify the correction.
- Desktop's five **simulated** process-control checks covered zero/nonzero,
  timeout, KeyboardInterrupt and unexpected wait exceptions. Acceptance independently
  exercised one invalid child node: pytest exit **4** raised parent pytest.fail
  and retained logs/metadata. Crash and real timeout were reviewed structurally,
  not deliberately induced. These checks do not count as journey/UI acceptance.
- Acceptance confirmed byte parity, all archived hashes, non-discovery of the
  deliberate diagnostic and unchanged assertions/no skip/retry/GC workaround.
  Final six changed/new test-support files passed Ruff check/format; scoped diff
  checks passed. The frozen diagnostic sources are intentionally not reformatted.
- The documented `uv run` invocation could not initialize the restricted user's
  external uv cache (access denied) before pytest began. Final verification used
  the existing locked `client/.venv/Scripts/python.exe` with explicit PYTHONPATH;
  no dependency, cache-permission or lockfile change was needed.

Artifacts: `scratch/v2-qt-journey-process-containment/` (final offscreen log,
process logs and simulated control checks),
`scratch/v2-qt-journey-process-native-fixed/` (final native log/screenshots/runtime),
and `scratch/qt-process-acceptance-20261109/641f1c98/` (invalid-node check).
The user-facing test commands remain in `client/README.md`; child process logs
are retained beside the selected artifact root or normal pytest temporary output.

Technical completion here means archived diagnostic plus verified per-scenario
test containment. Owner's earlier two-statement human run did not reproduce the
crash and saved both corrections; it remains a coached diagnostic result, not
general UX acceptance or proof of stability. Native/input/assistive/platform/
installed/release gates and previously recorded product limitations remain
separate. No new packet is selected by ending this investigation.

### November 9: logical commit packaging

Owner requested committing the completed session diff in a few logical groups,
while retaining the unresolved crash for future investigation if it recurs.
Packaged as a diagnostic/archive commit, managed-institution/account-aware import
services, integrated desktop workflow with Qt verification, then contracts/guides
and this work record. Mechanical institution-registration fixture changes were
staged with the core services even where their fixture builders live in GUI test
modules; UI behavior and staging assertions remain with the desktop commit.

Additional pre-commit verification: focused institution/format/account-context/
import group **123 passed in 77.03s**. The prior final mixed 10-case and native
5-case containment checks remain the integrated evidence; no further intentional
heap-crash experiments were run. Repository commit hooks checked staged files;
their line-ending/EOF normalization was verified and restaged. The archive's
original source hash and all archived-file hashes, plus byte parity of the moved
full journey scenario, were rechecked after hooks. A local Git whitespace
attribute recognizes the intentionally preserved CRLF diagnostic source.
No scratch profiles, private statements, production data or release artifacts
were included. These are local commits; publication/push is not part of the task.

## November 8: automatic declared CSV routing, initial focus and budgets

Owner feedback supersedes the earlier interpretation-choice design below: CSV
column meaning belongs to a declared parser, not a user mapping decision. Exact
ordered-header matching was already enforced by the engine; the misleading demo
installed two deliberately conflicting declarations with the same header. Header
recognition cannot distinguish those declarations by itself.

ui_ux established the revised journey before implementation: **Choose accounts →
Review import**. Institution/product metadata narrows supported declarations;
the final activity/account/period/row-count preview is read-only. Compared keeping
a format question with refusing unresolved overlaps. Chose refusal because choosing
Amount versus ReportedBalance asks the user to repair an invalid routing decision.
No fuzzy matching or automatic first-candidate selection is introduced. Different
source-account structures refuse before mapping; other overlapping compatible
formats block confirmation with Back/Skip/Cancel recovery and retained drafts.
This conservative refusal does not yet resolve structurally different groups via
a separate institution-first decision tree. XLSX remains outside scope.

Primary owns integration/workspace freshness, shared initial focus, budget wording,
docs and this record; evidence owns unique core routing and parser tests; desktop
owns import presentation/integrated checks. Integrity independently reviews core
boundaries. Synthetic/disposable data only; existing owner windows and profiles
remain untouched. No schema, money/sign/date rules, duplicate window, production
catalog or release changes.

Implemented safeguards require exactly one account-compatible declaration in
planning and reconstruct the full valid candidate set before commit. Trimming a
preview to a preferred parser cannot bypass this check. Source/catalog are reread
after that last parse; drift requires another explicit confirmation. Lower-level
source-only explicit selection remains an engineering interface, not a desktop
column-choice path. Complete parse validation, hashes, evidence locations,
transaction rollback and generic CSV unknown provenance remain required.

Opening focus follows logical tab order to the first visible enabled editable
text input or dropdown in V2 task windows, skipping read-only/hidden/disabled
controls and combo internals. Applied on opening/reopening, without refocusing on
refresh; contextual in-window navigation remains explicit. Category setup now says
**Monthly budget for selected category**, **Save budget from month** and **Remove
budget from month**. State/history/report labels consistently say budget. Effective
month carry-forward, nullable amounts and no-posting semantics are unchanged.

### Verification and integrated findings

- Evidence core import/recognition **47 passed in 45.10s**, additional final-parse
  cancellation case passed; evidence-profile/catalog-import **22 passed in 43.68s**;
  synthetic engine/admission/source-pipeline pilot **41 passed in 10.90s**. Exact
  header cases cover renamed, reordered, extra, missing and case-different fields,
  declared normalization, metadata routes and conflicting meanings. Counts overlap.
- Primary workspace drift/recognition and budget/report regressions **26 passed
  in 89.23s**, including source/catalog changes during the new final uniqueness
  validation. Final broader workspace/focus/forms/category-purpose **32 passed
  in 67.85s** after the recovery issue below was fixed.
- Desktop final native import/CSV/full journey **27 passed in 86.91s**, including
  review/spending/correction, PDF/MOHELA, queue/skip/cancel, source drift, unique
  and metadata-resolved routes, blocked overlapping definitions, Back/draft recovery,
  200-character accounts and 1050×700/1280×800 windows. Two stronger native Create
  → nickname focus cases passed in 5.07s. Artifacts
  `scratch/v2-declared-routing-native-final/`, matching JUnit XML.
- Primary native focus/budget **3 passed in 1.96s**, empty/saved budget screenshots
  `scratch/v2-header-routing-focus-final/`. Initial tests corrected two test-only
  mistakes (wrong method name and editable-combo focus object). Offscreen reopening
  does not activate a window: the check now verifies per-dialog focus there and
  additionally application focus natively. Focus policy handles first activation
  during opening without stealing focus when returning to an already-open task.
- Broader checks exposed a real existing recovery-status defect: synchronous table
  replacement temporarily cleared selection and erased the pending error notice.
  The notice now survives snapshot rendering with authored choices; later explicit
  reload clears it. Initial broader run **29 passed, 3 failed** included that cash/
  card defect and the offscreen activation limitation above. Both stale-purpose
  cases passed after the fix; full purpose/ordinary-async/multirow regression
  **43 passed in 100.58s**. No financial state rules changed.
- Independent integrity **57 passed in 123.40s**, no actionable Windows routing,
  provenance or atomicity finding. Review recommended repeating profile identity
  checks after final parsing and inside the transaction before exact-source retry.
  Implemented both guards; focused five cases passed, with both injected drift
  cases independently rechecked **2 passed in 6.73s**. A physical replacement probe
  was denied by Windows; macOS replacement behavior remains untested.
- ui_ux rechecked actual final rendered unique/blocked/known PDF/account/budget
  states and current focus implementation/evidence; no material finding remains
  within inspected sizes/fonts. This was screenshot/code review, separate from
  fresh task discovery. Primary also inspected rendered routed import/budgets.
- Ruff check/format passed for all **22** follow-up Python files; whole working
  diff whitespace check passed. Tests use Windows 11, Python 3.13.15/Qt 6.11.2,
  Segoe UI; native checks use Qt software events, not OS input or assistive tools.

Fresh walkthrough prepared but **not launched**:
`scratch/v2-declared-routing-human-20261108-7b2a33e5/Open-journey.cmd`.
It has schema 24, two synthetic existing accounts, zero sources/journals, ordinary
October/November CSVs with one declared format, and a known-product synthetic PDF.
`launch_current.py --check-only` verified those counts. The previous unlaunched
account-first demo deliberately included conflicting declarations and will now
block; it and every older/owner-running profile are untouched.

Fresh goal-only acceptance used a separate reviewer without implementation/test
body reading or control instructions. Successful import created a new checking
account alongside a compatible existing account, with no column questions; Back
kept the nickname/institution/product. The reviewer understood recognized dates,
row counts, account assignment and no-posting effects. For a deliberately conflicting
catalog, Import stayed disabled; Back retained drafts and Skip recovered with zero
new sources/accounts. It required no app-specific coaching. Qt nonnative file
picker use is a harness limitation; downstream windows used native Qt rendering.

The attempt found a small but real keyboard-discovery failure: Categories opened
on the optional built-in dropdown, so typing Food did nothing. The reviewer recovered
by finding the custom-name field, created Food and saved a $250 monthly budget.
Resolved by moving custom creation before optional built-ins and matching tab order;
the name field now receives opening focus. Focus/forms/budget checks **9 passed in
8.81s**. Fresh-process independent recheck passed: immediate Food typing worked,
Tab reached Expense then Add custom category, Space created it, and $250 monthly
budget saved effective November 2026. This informed recheck used the same reviewer,
distinct from the initial goal-only attempt. Evidence
`scratch/routing-goal-acceptance/`, especially `review-import-1.png`,
`conflict-blocked-31.png`, and `recheck-budget-saved-1.png`. Native workspace
1180×820, import 1050×700, categories 600×650. All reviewer processes exited.
ui_ux rechecked the reordered screen and found no material layout/focus issue.
Primary final native focus/budget and stale cash/card recovery checks **5 passed
in 5.07s**, artifacts `scratch/v2-routing-final-focus-recovery/`. Technical
implementation, scripted checks and agent task/recheck criteria are complete;
actual human acceptance remains pending. No app-specific coaching was supplied;
the file-picker harness adjustment is disclosed above.

Technical, agent usability and actual human acceptance are recorded separately. Unverified:
human/OS-input/assistive technology, high-DPI/high-contrast, macOS, installed/offline
release behavior and archive-scale performance. Retained-format replacement stays
unsupported; structurally different ambiguous CSV routes safely refuse as above.

## November 8: account-first PDF and CSV import

User approved implementation of the account-first decision model after discussing
source compatibility versus account identity. PDF/CSV only. Primary integrates;
owner's running schema-23 synthetic profile/window remains untouched. No private
archives, production services, daily-profile activation or release artifacts.
All existing working-tree changes belong to the ongoing session and are preserved.
Repeat date-window policy and retained-format replacement are not selected here.

Baseline: current native unique/ambiguous CSV preview checks passed **3 cases in
5.37 seconds**, artifacts `scratch/v2-account-first-baseline/`. Current import asks
about format first, saves unassigned evidence, then requires separate account
creation/assignment. Account kind/scope incompatibility can surface only in Review;
account product is not persisted. Recognized PDF context currently identifies
institution/class but does not always identify product, so nickname-only setup is
conditional on what the actual admitted format/source establishes.

ui_ux established the integrated model before implementation division: one reused
per-file surface with **Choose account → Check and import**. Every complete
source-account group (including empty PDF sections and unidentified CSV rows) is
mapped explicitly. Compatible existing accounts and **Create a new account…**
remain available together; header compatibility never selects account identity.
Provisional creation asks nickname and only unresolved managed institution/product
choices, prepopulating class/scope from supported format/product relationships.
Remaining date/amount interpretation differences use readable previews, without
technical parser-revision questions. Reliable PDF identification/default matching
retains its source-identity rules and unique signed routing. Generic CSV authored
account choices never become observed institution/product provenance.

The final **Import and assign** action explicitly retains original/evidence,
creates displayed account drafts and assigns all displayed source groups atomically;
it creates no journal/opening entry. Back preserves choices; Skip/Cancel before
confirmation leaves no orphan account/source/assignment. Completed batch files
remain saved. Source/catalog/account drift invalidates stale confirmation. Exact
source retries retain their saved format/assignments and route to the saved document.
Observable criteria include clear recognized versus authored context, complete
group scope, meaningful remaining ambiguity, confirmation effects, recovery,
keyboard traversal and readable 1050×700/1280×800 screens. The alternative technical
format-first flow and a single crowded all-fields form were rejected.

Ownership: ledger owns products/compatibility/planning/atomic store changes and
account-creation drafts; evidence owns signed format relationships, full group
previews, bounded prepared parsing and catalog builder; desktop owns the integrated
account/interpretation surface and product controls; primary owns workspace/worker/
window integration, lasting contracts, planning and this record. Specialists do
not delegate or overlap writers. Independent integrity and goal-only acceptance
follow integration; ui_ux rechecks actual rendered states.

Product metadata requires fresh schema 24. As required by the current pre-release
lifecycle, no migration or activation of the owner's schema-23 profile is implied.

### Implemented decisions and integrated findings

- Managed products persist separately from class/institution/scope. Loan may use
  principal or whole-liability scope; HSA/investment may use whole/cash-component
  scope. Existing unknown metadata stays unknown. Signed format profiles support
  one format/multiple products and multiple formats/product; generic CSV profiles
  remain compatibility only. Product/source identity is not inferred from headers.
- All source groups are retained (100-group bound explicitly refuses excess),
  including empty PDF sections and CSV groups occurring beyond the five preview
  rows. If different account columns produce different groups, an early readable
  account-column question selects the structure before mapping. Remaining date/
  amount differences stay in step 2. A unique remaining candidate is automatic.
- Creation uses provisional UUID accounts, managed institution and compatible
  product choices. Identified Yamaha PDF/MOHELA CSV institutions/products prefill;
  an OCCU bank PDF still asks checking versus savings. Class/scope are derived
  controls, with no editable conflicting asset/liability choice. Source Unknown
  text explicitly says **From document** so it does not contradict authored choices.
- Compatible existing and provisional accounts appear beside Create new. One
  provisional account can serve multiple explicitly selected source groups. Its
  draft survives if another group still references it after its originating group
  changes to an existing account; final commit creates only referenced drafts.
  Explicit manual account-association semantics remain unchanged; header matching
  and a differing printed identifier never silently infer physical identity.
- Confirmation lists each exact group → account/product/scope mapping, activity
  row/group counts and how many new accounts will be created. Source/evidence,
  accounts and assignments use one transaction/savepoint boundary with no money
  or opening writes. Changes to accounts or source/catalog before or during final
  parsing rebuild the review and require explicit confirmation again. Profile
  replacement refuses rather than silently retargeting a confirmed operation.
- Back originally reset an otherwise compatible date/amount choice. ui_ux and
  independent acceptance both found it; the chosen interpretation now survives
  Back/Next only while source/catalog and compatible candidates stay unchanged.
  Stale refresh resets confirmation and applicable account drafts remain available.
  Institution selectors refresh with the read model; reused queue previews are
  re-enabled. Long account labels have bounded width and full text in details.

Primary integration audit found two real schema-24 regressions missed by the first
account/import suite: full-row validators for reserved built-in categories and
transfer clearing still expected nine account columns. Both now include the NULL
product column. The ledger specialist audited all full-row account consumers and
added built-in materialization coverage; broader core checks below cover the
affected shared persistence paths. No financial policy was relaxed to pass them.

### Verification

- Ledger/product/import/persistence group: **58 passed in 129.74 seconds**; schema
  validator follow-up: **31 passed in 154.94 seconds**, including built-in category
  purposes/card correction and different-date transfer clearing. A further focused
  provisional-reuse case passed. Counts overlap and are not unique coverage totals.
- Primary workspace/source/catalog/account drift, cancellation and worker suite:
  **18 passed in 87.45 seconds**. It includes post-reparse drift before persistence.
- Primary broader schema/account/journal/opening/anchor/category-report/export
  regression selection: **115 passed in 259.73 seconds** after validator fixes.
- Initial updated ordinary GUI integration: **22 passed, 1 obsolete form-state
  expectation failed** in 42.53 seconds. The class/scope controls are now derived
  and neutral until product is chosen; corrected that expectation, then its full
  form-cue file passed **3 tests in 6.12 seconds**.
- Desktop final account-first cases: **13 native passed in 45.12 seconds**, artifacts
  `scratch/v2-account-first-native-final/`; manual inline creation/action checks:
  **23 passed in 119.12 seconds**. Actual 1050×700/1280×800 states include all groups,
  provisional/reused accounts, meaningful ambiguity, retained Back choice, known/
  unknown PDF/CSV properties, 200-character account labels, keyboard traversal and
  source/account drift. Earlier implementation runs overlap these checks.
- Evidence: existing recognition/context/catalog/import group **52 passed**;
  focused new metadata cases **10 passed**; real-worker/pilot selection with new
  cases **17 passed, 22 deselected**. Scope covers generic identity boundaries,
  signed products/scopes, complete groups/limits, empty PDF sections, selected
  parse binding, cancellation/truncation and PDF routing ambiguity. No production
  signing/catalog activation or private archive checks were performed.
- Independent integrity narrow final check **9 passed in 18.16 seconds**, including
  the corrected account-column fixture and all eight workspace drift/cancel cases.
  It verified post-parse source/catalog rereads and new explicit confirmation;
  no material provenance/atomicity finding remained in that snapshot. An initial
  concurrently edited test fixture failed declaration admission before reaching
  the planner; the corrected valid fixture passed independently without loosening
  parser admission. Final independent schema/provisional-reuse review also passed
  **6 headless cases in 7.65 seconds**, **2 offscreen GUI cases in 4.01 seconds**
  and a positive/negative synthetic validator probe. It confirmed valid reserved/
  clearing records, refusal of non-NULL product tampering, shared draft identity
  after origin-group changes, compatible class/scope filtering and referenced-only
  creation. No actionable material finding remained.

### Independent goal-only attempt

A fresh acceptance agent received the goal and a synthetic setup recipe, without
new implementation/test bodies or control directions. Starting with Household
checking and a loan, it created **Travel checking** for the ambiguous export,
compared both amount interpretations, chose Coffee −400/Salary +1000/Tea −300,
created Food through the UI, explicitly posted Coffee/Tea, inspected **700 minor
units reviewed spending**, its scope/pending qualifications, Food entry detail and
original source rows. It then imported November activity into existing Travel;
the confirmation said zero new accounts. A separate cancellation probe drafted
another new account then canceled; no source/account persisted for that draft.

Final read-only database: three financial accounts, two sources, two source
bindings, two journal entries; all six activity rows associated with the same Travel
account ID. Salary and November activity remained unposted. No product coaching
was required. Its only application wrong turn was Back resetting interpretation:
final import became disabled, and it recovered by reselecting the reading. That
finding is fixed; an independent informed fresh-process recheck passed. Probe-plumbing
interruptions were kept separate from application findings.

Evidence: `scratch/account-import-acceptance/screen-{35,39,43,47,71,110,135,136,242}.png`.
Native Windows 11 build 26300, Python 3.13.15, PySide6/Qt 6.11.2, Segoe UI; main
windows 1050×760 and 1280×820, import dialog 1050×700. Qt software events and a Qt
file picker were used. Agent task completion is not human acceptance, direct OS
input, assistive-technology, high-contrast/high-DPI, macOS or installed/offline
verification. The final native replay and visual rechecks below passed within
those same platform/input limits.

Prepared (not launched) a fresh schema-24 synthetic walkthrough at
`scratch/v2-account-first-human-20261108-4ba53308/Open-journey.cmd`. It contains two
existing synthetic accounts (Household checking and Existing loan), zero imports/
journals, October/November ambiguous CSVs and a known-product loan PDF. The public
fixture trust, home, preferences and catalog are isolated inside that directory.
`launch_current.py --check-only` verified schema 24, two accounts, zero sources and
zero journal entries. Older profiles and running windows remain unchanged.

### Final integrated rechecks and limits

- Primary final native complete journey/CSV import suite: **10 passed in 23.75
  seconds**, `scratch/v2-account-first-final-journey/`. It covers empty/loading
  inventory, file-picker cancellation, new-account import, explicit transaction
  review, category setup, report interpretation/correction/return, source evidence,
  backup/reopen, import refusal/retry, in-flight cancellation, ambiguous amounts,
  batch waiting/skip/cancel and retained completed files. Earlier scripts were
  updated to use account-first setup rather than the superseded post-import setup.
- Complete known Yamaha PDF/MOHELA CSV imports plus embedded-preview Escape:
  **3 native passed in 7.30 seconds**,
  `scratch/v2-account-first-known-complete-native-final3/`. Both persist exact
  originals/full evidence, correct loan product/scope and all account bindings,
  with zero journals/openings. The PDF preview now uses statement period, signed
  route and qualified normalized amount direction rather than CSV column settings.
  One initial scripted date expectation incorrectly treated a derived Yamaha
  date as printed; it was corrected without changing parser output.
- The reused interpretation renderer is a rendering-only child. Its keyboard
  rejection delegates to the account/import owner; a native Escape from the closed-
  popup step-2 table released the worker, restored controls and retained no orphan
  accounts/source. This closes a child-dialog/adapter ownership gap found during
  primary code review.
- Fresh acceptance Back recheck retained Travel nickname/institution/product and
  the chosen Option 2 through Back/Next, with exact −400/+1000/−300 preview and
  enabled final confirmation. Before confirming, storage still contained only
  Household/Loan and zero sources/bindings/journals. It canceled and exited;
  evidence `scratch/account-import-acceptance-recheck/screen-54.png`.
- ui_ux inspected final existing/new/reused/known/unknown/long-label/stale screens
  at both sizes plus the four completed PDF/component-CSV screens. No significant
  unresolved finding remains in those exercised states. Source-label wording,
  row/group counts and compatible Back choice retention findings were rechecked.
- Changed Python files passed Ruff and formatting checks; the full working diff
  passed whitespace checks. No commit, release, publication, production signing,
  daily-profile activation or migration was performed.

Technical implementation and exercised agent usability criteria are complete.
Actual human acceptance is pending. The preview remains five rows, with all groups
and total counts separately visible. No archive-scale group list, alternate OS,
OS-native input/picker, accessibility technology, high-contrast/high-DPI or installed
build was accepted here. Existing specialist repeat-dialog density and absent
recognizable comparison filenames, whole-document evidence without originating-row
highlighting, and post-import format replacement remain documented limitations;
none was silently treated as fixed by this account-first change. Product metadata
uses schema 24; earlier disposable profiles require a new profile under the current
pre-release lifecycle. The prepared new walkthrough is available without changing
the owner's existing profile or window.

## November 8: cross-document repeat blocker recovery

Owner walkthrough found a blocked ambiguous-CSV transaction whose status appended
"choose a purpose explicitly" to "Cross-source occurrence needs review", while
purpose was disabled and the necessary repeat decision was hidden in Related
actions. This is separate from choosing the CSV format. Primary owns this narrow
presentation/recovery fix and tests; ui_ux reviews the contextual model and integrity
independently checks that repeat/posting safeguards remain authoritative. Reproduce
with synthetic overlapping imports, not the owner's current profile. Show the
actual prerequisite and a direct existing repeat-review route scoped to the
document/row; preserve selection, proposals and prior stages on return/cancel.
No automatic identity choice, source mutation or bypass of posting guards.

Implemented a blue contextual Review possible repeated transactions action; the
blocked single-row Post action is hidden and the message explains the actual
prerequisite. Existing explicit repeat decisions/confirmation remain authoritative.
The dialog opens the first unresolved comparison for the selected row **or its
saved repeat group**, retaining the full profile inventory: a source-only filter
would hide an indirect blocker through a supporting occurrence in another source.
When a capped list omits the required comparison, no unrelated/resolved comparison
is auto-selected and the limitation explicitly says the posting block is not clear.
Returning refreshes the saved basis and preserves the same row and earlier stages/
captured note. Cancel posts nothing; confirmed distinct relationships permit fresh
purpose/category review; supporting occurrences remain blocked from independent
posting. Tab now leaves the comparison table and read-only evidence text panels.
Compact table-only possible-repeat/supporting labels retain full tooltips and
headless statuses, preventing the supporting status from squeezing Description
at 1050 pixels.

Verification: **6 native cases passed in 10.80 seconds**, with final captures under
`scratch/v2-repeat-recovery-native-final2/`. Both 1050×700 and 1280×800 exercise
contextual opening, cancellation, explicit distinct/same-transaction confirmation,
same selected Coffee row and prior Tea stage/captured reason retained, zero journal
entries and unchanged original bytes/evidence. After distinct, the test authors
fresh Coffee choices; it does not claim to restore an editable Coffee proposal
that existed while Coffee was blocked. The confirmed supporting result remains
blocked, with the other retained occurrence eligible. Further cases cover the
indirect supporting-member blocker and a capped missing focus. Existing overlap
dialog/wider matching/multi-row/async regressions: **47 passed in 61.55 seconds**
before the final table-only label shortening; the final native cases cover those
shortened labels and Description width. Changed-file Ruff/format and full diff
whitespace checks passed.

Independent integrity reran six cases and a separate resolved-only-cap probe:
root A on October 1, support B on October 4, outsider C on October 7 opens pending
B↔C. A forced list containing only resolved A↔B selects nothing, disables Save,
discloses the limit and leaves the full-index posting guard intact. No actionable
integrity finding remains. ui_ux inspected the actual blocked/confirmation/return/
supporting screenshots at both sizes; the contextual route is usable. The existing
comparison dialog remains dense, foregrounds technical IDs and rules, lacks
recognizable document filenames and requires scrolling through supporting detail.
This is an unresolved readability limitation, not a demonstrated human acceptance.
No owner's profile was accessed or changed and no new uncoached human attempt was
performed for this narrow fix.

Further owner walkthrough feedback: assigning the ambiguous source to the existing
asset account raised the expected candidate warning; a loan account could not post;
a different asset account enabled purpose/category review. Code inspection confirms
the current generic cash interpretation requires a bound asset account (and its
supported tracking scope); negative amount alone does not infer a transfer. The
account-assignment flow needs to expose supported interpretations/compatibility
earlier. Owner proposed same-day matching rather than a universal three-day span
and parser-provided account types. Discussion only: no date-window, product-type,
assignment-policy or inference change is implemented. Existing signed PDF account
context can supply asset/liability kind; generic CSV compatibility cannot establish
product/institution provenance. Product identity, accounting kind and supported
format interpretations should remain distinct in a future design.

## November 8: action-button clarity and multi-row category review

Owner feedback: green save buttons blend into confirmed/valid draft fields and
labels such as Create account / Use this account are cramped or cut off. Owner
also requested selecting multiple Review rows to categorize together. No new
financial policy, bulk correction, source mutation or profile activation is in
scope. Use the existing exact ordinary-batch preview and atomic posting service.
The owner's running synthetic profile remains untouched.

Before dividing implementation, ui_ux established A1–A8: light-blue available
actions, green valid unsaved fields, red missing fields; stable full-label button
metrics through disabled/ready/focus and text changes; native Ctrl/Shift/keyboard
multi-selection with visible count and shared purpose/category/note; no accidental
single-anchor posting/withdrawal in multi-mode; all-or-none draft staging with
prior stages preserved; per-row dates/overrides retained without copying; cancel/
filter/sort/single-row recovery retains context; exact existing preview/confirmed
posting and practical 1050×700/1280×800 readability. Red save buttons were rejected
because red already marks prerequisites and would imply an unavailable click.

Primary owns shared styles, button geometry/render checks, CSV action-state tags,
integration and this record. Desktop owns ordinary cash/card/register selection,
navigation, staging adapters and focused Qt tests. Integrity consulted the
financial boundaries before implementation: prevalidate the entire selection
before staging; watch selectionChanged, not only currentRowChanged; guard every
single-row mutation; preserve previously staged card overrides; retain current
profile/basis/jobs guards and the 2,000-row limit. Independent checks follow the
implemented result. No specialist delegates or commits.

Existing pre-release schema stays 23; no persistence or money-rule change is
selected. Earlier source-format replacement and platform/human verification limits
remain open separately.

### Implemented interaction and observed task evidence

- Available save/stage/confirm buttons are pale blue, with stable two-pixel
  borders and horizontal/vertical padding across ready, focus and disabled states.
  Valid unsaved fields retain green. Create account / Use this account now retain
  their full labels. Native independent measurements found 28 pixels beyond the
  text width at both effective 9- and 12-point fonts. Requested 620×700 account
  creation expands to 620×744 at 12 points; this checks font size, not OS scaling.
- Review accepts Ctrl/Shift multi-selection and displays the count and common
  purpose/category/note scope. Shared staging prevalidates every row and changes
  none on refusal. Single post/correct/withdraw/owning-event actions cannot operate
  on a multi-selection anchor. Saved entries still require individual correction.
  Card dates remain per row; separately staged overrides survive common choices.
- Zero selected rows cannot appear ready or post the old current anchor. Category
  creation/cancellation returns to the selected rows, common proposal and prior
  stages. Filtering reports hidden staged rows. A partial-assignment document uses
  one compact notice: confirmed rows can be reviewed while other accounts still
  need assignment. At 1050×700 the multi-selection cash form retains at least four
  visible table rows; card forms retain at least three in the exercised fixtures.
- Successful Stage captures the note shared by the staged batch. A later edited,
  refused or merely restored proposal cannot replace it; successful explicit
  restaging can. This fixes an independent P2 reproduction in which an invalid
  mixed proposal overwrote an earlier Salary stage's note.

Fresh acceptance received a goal-only brief and synthetic setup, without the new
tests or control directions. It selected Coffee/Tea together, chose Expense/Food,
staged, canceled the exact preview, recovered and confirmed. The profile contained
exactly two entries (cash −400/Food +400 and cash −300/Food +300); Salary stayed
pending. Reviewed expense was 700 minor units, income zero; source bytes,
definition, evidence, row locations and capture/balance limitations survived.
Account creation/assignment remained separate and posted no entries. Keyboard
dropdown choices, Ctrl/Shift selection and Space activation worked. No product
coaching was required in that attempt; its first modal harness blocked stdin and
was replaced with a queued Qt harness. Later finding rechecks were scripted and
necessarily informed by the findings.

Independent fresh-process recheck preserved the original staged note through
mixed-selection editing/refusal, zero selection, row restoration and filtering
(one staged/one hidden). A direct adapter call additionally exercised refusal
because the corrected UI disables that action. Explicit valid restaging changed
the note as expected. Evidence: `scratch/multirow-acceptance/run3/`, especially
`05-fixed-note-preserved-after-refusal-zero-dialog-9.png`,
`07-fixed-note-preserved-hidden-dialog-9.png` and
`08-fixed-explicit-restage-dialog-9.png`.

Further review found stale table data after assignment while a draft was retained,
a latent common proposal omitted from discard detection, and a single-card Stage
path admitting a blank/noncanonical date despite its Required cue. These were fixed.
Fresh UI recheck used the actual account-confirmation dialog, verified a new review
basis and matching header/table, and retained the selected Coffee/Tea proposal B
and prior staged note A with zero journals/source changes. Hidden common proposals
now trigger discard protection. Successful posting clears only consumed proposals
and retains unrelated row/common work; it leaves no phantom unsaved prompt for
consumed choices. Independent date/discard/cleanup probes passed, including blank
and compact-date refusal without changing prior stages, note or profile bytes.
Preview cancellation now reports that stages were kept and nothing posted, rather
than leaving Preparing exact batch preview displayed after completion.

Evidence for the fresh assignment-dialog check is
`scratch/v2-multirow-design-20261108/assignment-after-fresh.png`; the primary's
regression additionally asserts the refreshed table values, same selected IDs,
common proposal, stages/note and fresh basis at both practical window sizes.
Selected-row emphasis was also strengthened after ui_ux found that the inactive
native selection showed the count but made the actual members hard to distinguish.
Selected rows now retain a pale-blue full-row highlight while a review field has
focus; table focus retains platform painting. A palette-only attempt still rendered
gray on Windows and was rejected. The final narrow table rule was inspected at
both window sizes with the note editor focused. Evidence:
`scratch/v2-multirow-selection-style/` (1050 run `aecc4794`, 1280 `d7a23a72`).

### Verification and closeout

- Final native integrated button/partial-assignment/multi-row suite: **18 passed
  in 29.23 seconds**, artifacts `scratch/v2-actions-multi-integrated-final3/`.
  Includes actual 9/12-point fonts; full button labels/focus/disabled geometry;
  selected/common/staged/hidden/zero/mixed/blocked and individual correction guards;
  exact preview cancellation/posting; card/register dates; category setup recovery;
  assignment refresh; latent discard; invalid date refusal and unrelated proposals.
- Existing workspace/ordinary async/cash/card/register regression selection:
  **43 passed in 64.95 seconds** after the recovery changes. Earlier focused
  batch/form-cue/CSV preview checks: **28 passed in 46.58 seconds**; counts overlap
  other intermediate and specialist runs and are not added as unique coverage.
- Independent acceptance and integrity rechecks are described above. Integrity's
  initial 27-case suite missed the two gaps its separate probes exposed. Its
  current-disk date/discard/success cleanup rechecks passed with no remaining
  actionable finding. One concurrently edited test snapshot initially failed to
  clear an input (`enter_text("")` only selected the existing text); explicit
  Backspace corrected the harness and independent rerun passed. It was not treated
  as proof that blank dates were accepted after the fix.
- Changed follow-up Python files passed Ruff and formatting checks; full working
  diff whitespace check passed. No schema/accounting-service change, commit,
  daily-profile activation or release action was performed.

Technical implementation and the exercised agent usability criteria are complete.
ui_ux's final A1–A8 recheck found no significant unresolved issue in the exercised
states, including the final inactive-selection highlight and actual assignment
dialog refresh. Human acceptance remains open. Existing whole-document evidence without row
highlighting, long account-label elision, large/narrow list density, source-format
replacement and broader platform/assistive-technology limits remain as documented
in the earlier sections; no new blocking usability issue remains in this follow-up's
exercised states. Reopening current source is necessary to load the new UI in an
already-running app; the owner's current work was left intact.

This follow-up uses native Windows 11 build 26300 AMD64, Python 3.13.15,
Qt/PySide6 6.11.2, `windows` platform, Segoe UI 9/DPR 1 and supplementary actual
12-point rendering. Qt software input and screenshots do not establish unfamiliar
human comprehension, OS-native input, assistive technology, high-contrast themes, high-DPI behavior,
long-list performance, macOS, installed-build or release acceptance. The owner's
running synthetic profile/window has not been accessed or relaunched.

## November 8: managed institutions and CSV recognition

User explicitly extended this session into local persistence/account matching and
authorized implementation of managed institution identity plus semi-automatic
format recognition. PDF/CSV only; XLSX integration is excluded. Primary remains
integrator and sole work-record/contracts/planning writer. All earlier edits and
the owner's running synthetic profile/drafts are preserved. Fresh synthetic
profiles and ephemeral signed catalogs are the only development data.

ui_ux established the model before dividing GUI work: institution is a managed
name with stable hidden ID, distinct from supported statement formats. Built-in
and installed-catalog institutions are selectable; unknown is deliberate, not a
shared fictional bank. No free-text code or institution-management editor is in
this slice. Reliable signed parser identification is read-only context; generic
headers never identify the bank. Existing account assignment inherits institution
without asking again or rewriting unknown source provenance.

CSV recognition fully validates compatible installed definitions. Header/column
checks may shortlist but never authorize import alone. A single validated format
has no format-selection question, only a compact exact preview and Import document.
Multiple valid candidates require an explicit choice, differentiated by date and
amount interpretation, with no default first candidate. No match has no force
override. PDF retains unique signed routing and no manual parser override. Reuse
one per-file preview surface within a batch queue; Import, Skip this file and
Cancel remaining keep completed imports distinct from untouched files. Preview
and account setup post no journal entries. Alternative bank-first wizard was
rejected because format compatibility does not establish an institution; an error
only on ambiguity discards useful validated choices.

Observable criteria I1–I10: validated institution names/Unknown with no raw-ID
entry; reliable identification versus authored association remains distinct;
filename/current batch item/loading/cancel are visible; preview identifies
format/account/period provenance/rows/exact amount/date mapping/locations;
ambiguous choice is deliberate and cannot bypass validation; import states local
original/evidence storage and no journal effect; cancel/skip/refusal preserves
originals and unrelated work; source/catalog drift refuses stale previews;
existing Required/Not saved/Saved colors and no legends remain consistent;
1050×700 and 1280×800, keyboard, long names and representative states are inspected.

Ownership: ledger owns institution registry, authoritative store/schema, account
matching and batch-account rules/tests; evidence owns bounded candidate summaries,
selection tokens and source importer/tests; primary owns workspace orchestration,
shared contracts/planning and integration; desktop will own GUI adapters/tests
after this model. Independent integrity review and goal-derived acceptance follow
integration. No specialist delegates or commits.

Persistence decision: schema 22 requires institution text. Schema 23 adds a managed
registry and nullable institution reference. Non-null IDs must be registered;
unknown permits explicit assignment/accounting but never automatic matching or
cross-document seeding. Catalog extensions persist for backup/reopen. Repository
pre-release lifecycle refuses older disposable schema rather than introducing a
migration. No existing profile is activated, modified or converted by this work.

Implemented before/after evidence:

- Institution code was a mandatory regex-constrained text field. It is now a
  searchable managed name selector with deliberate unidentified choice; IDs stay
  hidden. Source identification, authored account metadata and supported formats
  remain separate. A generic CSV's signed bank label cannot become source proof
  through a unique match or manual format choice. A shared finite policy governs
  preview, creation, matching and batch proposals; reviewed MOHELA component
  exports and exact PDF context retain their existing identification behavior.
- CSV ambiguity previously discarded successful matches and stopped with an
  update-package error. It now presents bounded candidates with meaningful date/
  amount/balance mappings, exact values, raw provenance and source locations.
  A single candidate has a readable descriptor without another selection question.
  Source/catalog/definition identity is rechecked and only the chosen definition
  is reparsed for the atomic evidence import. Cancellation, Skip and refusal
  retain originals and completed batch work; no posting is inferred.
- Account registry and source-preview failure paths were tightened after review:
  same-looking IDs and reserved unknown labels refuse; account/catalog metadata
  changes share a headless transaction; catalog activation versus failed profile
  retention are reported separately; a failed preview releases the worker and
  restores recovery controls. Live batch counts expose prior outcomes. Return in
  a selector cannot silently Skip/Import, and completing an institution name does
  not submit account creation. The design reviewer reproduced these fixes.

Independent goal-derived acceptance started with an empty schema-23 profile,
synthetic CSVs and ephemeral signing trust, without the implementation/scripted
journey walkthrough. It completed import → unknown-institution account → explicit
assignment → $4 expense → qualified spending → source evidence → category
correction → retained report. Its chosen November dates were 2026-11-01 inclusive
to 11-04 exclusive; total stayed $4, corrected category $4, prior category $0.
Ambiguous swapped columns showed $996 versus the intended -$4; the chosen import
retained -400/99600 minor units and located evidence. No-match recovery, exact
retry, restart and mixed batch (1 imported / 1 failed / 1 skipped / 1 cancelled /
1 unattempted) preserved originals and completed work. Known institution search
stored Wells Fargo's managed ID; unknown remained NULL, never a matching key.
Both inspected profiles passed SQLite integrity and foreign-key checks.

No route coaching or external product assistance was needed. An initial search
Down action selected Unknown instead of the desired popup completion; the fresh
latest-source recheck selected Wells Fargo via its popup and left the account
unsaved for explicit confirmation. Qt software targeting/focus preparation and
substitution of Qt's file picker for the OS picker qualify discovery evidence.
A scripted 36-document extension checked scrolling, filtering, empty search and
End navigation. Long account names still push review-status columns horizontally.

Verification (overlapping groups, not additive totals): evidence recognition/
import group 33 passed, affected engine/table/source-pipeline group 57 passed;
ledger initial 71 focused checks, final batch 27, offline/anchor 11 and synthetic
overlap helper 2 passed. Follow-up institution collision/atomic-write group 19
passed, reserved-label/institution group 25 passed, shared source-context 18
passed; integrity independently rechecked policy/institutions with 37 passing
cases and read-only Citi/Chase/renamed-family reproductions through reopen/retry.
Primary workspace/catalog 24 passed, core account-context 15 passed, final inline
account-creation 20 passed. Desktop native preview/full-journey 10, native dedicated
preview/queue 6, offscreen 6 and affected account/batch/workspace 20 passed.
Fresh acceptance separately ran 42 native recognition/institution/preview cases
and a final 6-case native preview rerun; primary reran those six after adding the
retained-format notice (6 passed). All 115 changed/new Python files passed Ruff
check/format check before closeout. The broad V2 run completed with 1370 passed,
19 obsolete UI expectations failed and 3 skipped in 1626.30 s; final targeted
expectations were corrected without weakening financial/source assertions. All
19 failed nodes then passed in 19.84 s, and the five affected GUI modules passed
59 cases in 78.47 s. This broad process
collected modules before the final provenance/transaction refinements; their
focused and independent rechecks are listed separately.

Final current-source native replay of `test_v2_qt_journey.py` plus category
navigation returned **5 passed**, but reported **10041.36 s (2:47:21)** elapsed.
The tool call itself did not yield during this interval. Artifact timestamps put
the 1050 case at 14:50:02, the 1280 case starting 14:50:06, and the remaining
three fixtures at 17:37:17–20, America/Los_Angeles on November 8. The long pause's
cause was not established; it must not be represented as normal application
latency or proof of fully autonomous/native OS input. No host-private event logs
were accessed to infer a cause. Earlier native runs and independent attempts
completed in seconds/minutes and remain separate evidence. This anomaly is an
unresolved verification-timing limit, not silently discarded because tests passed.

Native artifacts: `scratch/v2-managed-import-native-final`,
`scratch/v2-managed-preview-queue-final`,
`scratch/v2-managed-preview-retained-format`,
`scratch/v2-institution-csv-design-20261108`, and
`scratch/institution_acceptance` (initial, latest and separate scripted runs).
Full regression log/XML: `scratch/v2-managed-institutions-20261108`.
Final native replay artifacts: `scratch/v2-managed-journey-final`.
The in-app guide was rendered at 680×570 with scrollable content and Close visible.

An empty fresh human-test profile and current-source launcher were prepared at
`scratch/v2-institution-human-20261108-42e3e8d0/Open-journey.cmd`. It contains
Checking-October.csv (one valid candidate) and Ambiguous-example.csv (two),
verified by read-only recognition. It has not been launched or accepted by the
owner. The earlier running schema-22 synthetic profile remains untouched.

Incomplete recovery capability: after a wrong CSV format is imported, the current
profile cannot replace that retained interpretation. Exact retries reuse saved
evidence and reparse comparison is read-only. The limitation is now plainly
visible beside Import before confirmation; comparing/changing/cancelling before
import works. Ordinary category/date corrections are fully separate. A source
replacement/versioning workflow is not implemented, so comprehensive recovery
from post-import format-selection errors is **incomplete**, not waived by passing
tests. No deletion/overwrite workaround was introduced.

Platform/acceptance limits: Windows AMD64, Python 3.13.15, Qt/PySide6 6.11.2,
pytest-qt 4.5.0, Segoe UI at 96 DPI/DPR 1, actual Windows Qt widget renders and
software events. These do not establish OS-native input, screen-reader/high-DPI/
high-contrast/macOS behavior, installed PDF import, human comprehension or owner
acceptance. No live profile, private archive, production service, production
signing/release artifact or global trust settings were accessed or modified (all signing fixtures
were ephemeral synthetic catalogs, not production material). No commit or release
was made.

## November 8: visible decision states and control arrangement

The owner reported the earlier journey was a big improvement, then requested
pale red for required missing choices and pale green for valid choices not yet
stored, with a clearer arrangement. This is limited feedback on the previous
version, not acceptance of this follow-up or release authorization. The running
synthetic human-test profile is left untouched to preserve any owner drafts.

Before implementation, ui_ux established a compact decision card with numbered
fields and one confirmation action, separate from batch controls. Merely coloring
scattered controls would retain unclear ordering; a wizard would hide source
context and slow repeated correction. Chosen approach retains the table/context
and groups transaction decisions beneath it. The primary owns shared cue helpers,
account creation/assignment, category/report cues, workspace integration and this
record; desktop owns ordinary cash/card/register review and its focused Qt tests.
Fresh acceptance receives the goal/data only and independently attempts the
journey. Specialists do not modify shared files or the owner's active test app.

Observable criteria: required active missing/invalid fields are pale red;
individually valid authored choices are pale green until saved; unchanged saved,
read-only evidence and optional empty fields remain neutral. Inline Required,
Chosen / Not saved, Saved and prerequisite text supply meaning without color.
Green never certifies source correctness, report completeness or posting
eligibility; existing headless guards and confirmations still decide writes.
Loading/stale/blocked states make no green readiness claim. Corrections retain
purpose/source/date context and require a fresh explanation; cancel retains the
draft. Practical targets at 1050×700 and 1280×800 include at least four cash or
three card table rows, readable controls and keyboard-reachable decisions.

Owner follow-up during implementation: legend chips look like buttons and confuse
the workflow. Remove all runtime color legends; explain conventions in Getting
started. Inline action-specific summaries remain. This supersedes the initial
legend proposal. The in-app Help > Getting started now explains the convention
in plain text; its 680×570 native Qt render fits with Close visible. The guide is
also available at [Getting started](../client-v2-getting-started.md).

Implemented result and observed before/after:

- Before: ordinary review fields were scattered beside single/batch actions and
  local draft state relied mainly on enabled controls. After: a numbered decision
  group separates purpose/category/date/note, one-entry confirmation and a distinct
  Batch review row. Missing choices are red; individual valid choices are green
  while the rest can remain red. Cancelled confirmation retains the draft.
- Before: saved-idle note appeared required, and repeated document/period headers
  squeezed source rows. After: unchanged saved fields are neutral, the idle note
  says “for changes”, corrections restore the required marker, and the selector
  retains document/period while the duplicate header becomes a compact status.
  Actual 1050×700 checks retain at least four cash or three card rows; 1280×800
  remains readable. Long card/register tables still need horizontal scrolling.
- Account creation, printed-source/file/row/batch assignment, category authoring
  and budget targets use the same state distinction. Accountless assignment now
  starts with an explicit Choose an account placeholder. Creating an account
  remains a separate saved action from assigning source activity. Valid report
  dates apply automatically and stay neutral; reversed intervals are red.
- Independent integrity review caught a stale local budget memo claiming “saved”
  after a newer target was read, and an unreadable built-in claiming saved. The
  current cue compares exact minor units against the fresh persisted monthly
  rate; unavailable state is blocked. Reproduction now retains the former value
  as a green draft, permits reapplication, and leaves profile bytes unchanged
  during read/cue updates. Existing store bounds remain authoritative.
- Independent acceptance measured the initial green border at 2.81:1 against its
  fill. Darkening only that border to `#5C8967` raises it to 3.66:1 against
  `#EDF7EF`; dark text remains 11.07:1 and the blue focus border 5.10:1. These are
  calculations for these explicit colors, not high-contrast-mode acceptance.

Scripted verification for this follow-up (counts overlap; not human evidence):

- Desktop: 33 focused ordinary financial/UI regressions; nine Windows native and
  nine offscreen full-journey/state cases passed. A final note-label adjustment
  then passed five affected native state checks. The journey includes refusal,
  real in-flight cancellation, exact source correction and retained report dates.
- Primary: 64 focused account/assignment/category/budget/batch/report/workspace
  checks were exercised. Initially introduced model-style placement was fixed;
  accountless tests now explicitly choose an account instead of relying on the
  old automatic first item, and unchanged rename is correctly disabled. The
  affected nine assignment cases and 13 assignment/form/category-navigation cases
  passed after fixes. Three form cases rendered natively; seven native
  form/category/budget cases passed after saved-state fixes; the final ten
  form/category/budget/report checks passed after range/copy cleanup.
- Integrity independently passed six scoped stale/profile-switch/cancelled-read/
  batch-guard cases and synthetic saved-state reproductions. No remaining material
  findings in this presentation-only scope; financial service logic is unchanged.
- All 31 changed/new Python files pass Ruff check and format check;
  `git diff --check` passes. One final uv invocation could not access its external
  cache, so equivalent checks used the already locked client virtual environment.

Actual Qt artifacts (ignored disposable synthetic data):
`scratch/v2-flow-cues-20261108-final` (nine-case journey/state run),
`scratch/v2-flow-cues-labels-20261108` (final five state cases),
`scratch/v2-form-cues-20261108-final` (account/assignment/category targets including
fresh-target conflict), and `scratch/v2-color-guide-20261108` (in-app guide).
ui_ux inspected pending/ready/staged/saved/no-op/correction, estimated/invalid/fixed
date, repayment, loading/cancel/reload and account/category target renders and
rechecked its density/required-note findings after fixes. No legend chips remain.

Independent goal-derived acceptance uses its own disposable CSV/profile and
native Qt probe, not the scripted journey implementation. Initial 1050×700
attempt discovered import, account creation/assignment, custom category setup,
post confirmation, qualified spending, source evidence and correction/return
without route coaching. It observed $4 reviewed spending and two pending rows;
Food → Dining correction kept total $4 and report dates while preserving original
row evidence. Final-candidate reload at 1280×800 and 1050×700 retained the expected
state/controls without legends. Screens `42-final-1280-review-main.png` and
`43-final-1050-review-main.png` are in `scratch/color-acceptance-independent`.
Read-only checks after restart found three journal entries (post/reversal/
replacement), one correction, and the original CSV hash unchanged. No product
wrong turns, route assistance or result misunderstandings were observed in this
agent attempt. One probe initially sent Return without reliable combo focus;
that triggered a default dialog action. Deterministic Qt activation/Tab focus
resolved it, so it is recorded as a software-harness limitation, not a discovered
product failure. The probe closed assignment twice during these focus mistakes;
this limits keyboard-discovery evidence. After the border-only contrast fix,
acceptance independently reran all three native form cases (3 passed, 2.48 s) and
inspected the resulting native form. The final image is
`scratch/color-acceptance-independent/final-contrast-recheck/test_account_draft_invalid_choice_and_saved_edit/41a7ae98/03-valid-account-not-saved.png`.
`final-runtime.json` records the environment and read-only stored-result checks.
No significant finding remains open within this implemented core slice.

Limits: Windows Qt 6.11.2 software events, Segoe UI at 96 DPI/DPR 1; explicit
in-process test focus setup is recorded. These do not establish OS-native input,
human discovery/acceptance, screen-reader/high-contrast/color-vision usability,
other scaling, Intel macOS, installed behavior or release authorization. Wide
card/register tables and technical specialist histories remain usability limits.
The owner's running synthetic profile and its drafts were not inspected,
modified, closed or relaunched by this follow-up.

November 8 follow-up: complete — owner requested locked pytest-qt setup and a
repeatable actual-widget test of the complete journey. This record remains the
single home for implementation and verification of that journey.

## Scope and controlling decisions

Primary owns integration, user communication, contracts and this sole work record.
`ui_ux` owns initial native inspection, interaction model/criteria and final design
recheck. `desktop` owned explicitly assigned UI implementation; `acceptance`
received a goal-only brief and independently attempted the integrated journey.
Financial/evidence boundaries remain governed by client ledger, parsing, cutover
and unified-store contracts. No accounting policy or service extension selected.

Baseline is a clean checkout. New ignored runtime:
`scratch/v2-core-journey-20261107`, prepared by the public synthetic demo tool;
`launch_current.py` runs current source without the demo's instructional footer.
It isolates home, app data, preferences, catalog and profile and uses null keyring.
Only generated fixture trust is used. Initial sandbox process was not visible to
Windows computer-use; interactive launch requested through tool escalation.

## Result and review

Before implementation, ui_ux inspected actual Windows Qt renders at 1050×700 and
1280×800 (ignored `baseline-{documents,review,reports}-*.png`). The largest
structural failure: selecting October checking then Reports opens November–December
and $0 despite $4 reviewed October spending. Reports have no correction return
route, and switching review documents requires backing out to Documents. Local
issues include technical status width squeezing descriptions. Document account and
period labels already work and should be retained.

Alternatives: a linear wizard improves initial sequencing but impedes repeated
review/correction; one merged screen adds density and broad restructuring risk.
Chosen first improvement retains four sections with a contextual Review hub,
document switching/next attention, explicit document-date spending handoff, and
report-entry → exact source row → preserved report return. Reports continue to
include all profile accounts; navigation does not add account/document filtering.

Observable criteria agreed before implementation:

1. Recognize source/account and statement period versus activity span; assignment
   and posting remain distinct.
2. Empty/loading/failed states give a safe next action; missing data never implies
   complete zero spending.
3. Contextual next action addresses assignment, pending or correction work;
   attention counts retain unsupported/repeat qualifications.
4. Explicit spending handoff carries known source interval with exclusive end;
   unknown dates require deliberate selection. All-account scope sits beside totals.
5. Report entry exposes recognizable source and exact row correction navigation;
   specialized events retain existing owning workflows. Navigation writes no books.
6. Report dates/tab survive correction and return; saved corrections refresh totals;
   draft cancellation and unrelated saved work survive transitions.
7. Confirmations describe account/date/purpose/effect and correction meaning;
   assignment never claims posting.
8. Practical 1050×700 and 1280×800 sizes, readable controls, keyboard focus and
   accessible names; evidence reachable from review/report.

Write ownership: desktop owns workspace window/review navigation and guided/core
journey tests. Primary owns reports/drilldown and their tests, contracts and this
record. No headless/schema/accounting changes were made.

Implemented files:

- `v2_workspace_window.py`, `v2_review_navigation.py`: contextual document selector,
  next-attention action, assignment/activity guidance, exact source-row handoff and
  retained report return. Unknown dates disable the date shortcut. Draft refusal
  retains the current source and unapplied choices. Sole-pending navigation explains
  why there is no next document; zero captured rows do not claim complete activity.
- `v2_reviewed_reports.py`, `v2_report_drilldown.py`: explicit document-date range,
  all-profile-account scope beside totals, precise empty-spending/income wording,
  recognizable supporting sources and guarded correction navigation. Selected
  financial-account allocations take priority within multi-account sources; loan
  entry-specific source links retain exact raw evidence identity.
- `v2_ordinary_review.py`, cash/card review widgets: verified owning-event identity
  supplies presentation status for raw loan source uses, without changing the
  headless snapshot, eligibility or evidence. New/category/date corrections retain
  existing explicit confirmations; category changes show old → new, and date-only
  card corrections identify the unchanged category.
- `v2_loan_payment_review.py`: opening a requested saved event starts in history,
  avoiding an invalid replacement-draft impression under current date preferences.
  Replacement and whole-event withdrawal guards remain in place.
- `v2_financial_account.py`: account type/amount tracked wording, concrete
  institution-code guidance and inline validation using the existing service regex;
  invalid input retains fields and focus. Stored account choices/defaults unchanged.
- `v2_batch_import.py` and workspace import outcome: unsupported/ambiguous/missing
  format and unavailable-file recovery explanations, with diagnostics retained.
  Partial batch success and explicit signed-format trust remain unchanged.
- Focused tests in `test_v2_core_journey.py`, `test_v2_report_drilldown.py`, ordinary
  review/account-creation/window tests. Current action inventory and roadmap updated.

### Findings and disposition

| Before | Implemented / observed after |
| --- | --- |
| October source opens November report with $0 | Explicit date handoff opens October 1 inclusive–4 exclusive and $4 reviewed spending, visibly all profile accounts. Ordinary report navigation preserves edited range/tab. |
| Report entries cannot lead to correction | Food entry opens exact Coffee source row; Food → Travel correction retains $4 net spending; Back to report preserves dates/tab and refreshes Food $0 / Travel $4. |
| Document switching requires backing out | Review selector and next-attention action operate in context; declining draft discard keeps current source and text. |
| Lender source row leads to disabled ordinary posting | Verified loan ownership displays View reviewed loan payment and opens the exact saved event/history without changing preferences or money. |
| Wells interest-only journal maps first principal row; Savings transfer maps Checking side in same source | Matching loan entry link and selected financial-account posting now choose their own exact raw row. Independently reproduced and rechecked without writes. |
| Read-only tables retain Tab within cells | Tab leaves the table for purpose/category/reason or report/detail controls; arrows retain row navigation. |
| Empty Spending implies no reviewed activity despite income | Empty text names spending or income specifically; $25 reviewed income remains visible in its own tab. |
| Unsupported import modal says only catalog_no_match | Explanation names unsupported installed-format match, source/package recovery and technical details; refusal preserves source and existing reviewed work. |
| Account fallback requires unexplained institution key; invalid fields risk generic service error | Concrete code format and inline recovery retain user input; source opening/closing context stays visible alongside errors. |

Design review additionally found a valid saved loan was presented as an invalid
replacement draft with current assumed dates disabled. Its initial owning-event
landing now shows saved history and explicitly says current date preferences do
not invalidate it. Rechecked at 1050×700. No accounting/date preference was changed.

## Verification

Platform: Windows x64, locked Python 3.13.15, PySide6/Qt 6.11.2. Tests use
`client/tests/conftest.py` temporary home/null keyring and per-test synthetic
profiles. No root `.env`, private archive, live profile, production or release
artifact was accessed. Preparation command:

```powershell
& .\client\.venv\Scripts\python.exe devtools/v2_review_demo/prepare_demo.py --prepare-at scratch/v2-core-journey-20261107
```

Native-source launch through sandbox Start-Process was invisible to computer-use;
an approved interactive-session launch made the window discoverable, but the
computer-use tool then refused control with `product policy blocks this app:
python.exe`. Any App was already enabled (owner confirmed). This is a tool policy
limit, not a missing skill authorization. No restriction bypass attempted.
All rendered design/acceptance checks below used actual Qt `windows` platform
screenshots and legitimate software-test widget activation/events; direct Windows
input and native picker discovery remain unverified.

Automated checks (overlapping suites, not an additive unique-test total):

- 110 passed: guided workspace/document browser/core journey; report drilldown,
  report dialog/responsiveness; cash/card/register ordinary review and async/batch
  behavior; repayment-category routing; loan integration. Command below.
- Final affected-addition run: 54 passed across core journey, inline account
  creation, workspace window and loan payment dialog. Covers exact owner landing,
  batch recovery, draft refusal and invalid account-input retention.
- Earlier targeted report/core run: 22 passed, including separate Wells interest
  row and same-source Savings transfer identity with unchanged profile bytes.
- Changed Python Ruff check and format check: all 16 files passed; `git diff --check`
  passed. Subsequent two-line account-context minimum height was visually rechecked.
- Independent integrity: 43 focused tests, three no-write synthetic routing probes,
  then 2 final owner/recovery regressions; no remaining actionable findings. Final
  loan landing/account-validation/import-guidance additions reviewed independently.
- Independent acceptance: 8 focused offscreen checks plus the separate actual Qt
  goal-derived attempt and state checks described below.

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_guided_workspace.py client/tests/test_v2_document_browser.py client/tests/test_v2_report_drilldown.py client/tests/test_v2_cash_activity_review.py client/tests/test_v2_card_purchase_review.py client/tests/test_v2_liability_register_dialog.py client/tests/test_v2_ordinary_review_async.py client/tests/test_v2_ordinary_batch.py client/tests/test_v2_register_repayment_category_routes.py client/tests/test_v2_reports_responsiveness.py client/tests/test_v2_reviewed_reports_dialog.py client/tests/test_v2_core_journey.py client/tests/test_v2_loan_integration.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_core_journey.py client/tests/test_v2_inline_account_creation.py client/tests/test_v2_workspace_window.py client/tests/test_v2_loan_payment_dialog.py -q
```

### Separate agent usability evidence

ui_ux set C1–C8 before implementation. Its implementation-informed recheck covered
actual rendered populated, loading, empty, unassigned, blocked, failed/reloaded,
pending, reviewed, corrected, cancelled-draft and evidence states. Primary inspected
before/after actual renders too. Main sizes: 1050×700 and 1280×800. Machine-local
screenshots under `scratch/v2-core-journey-20261107/`:
`baseline-*`, `integrated-design4`, `integrated-keyboard-owner-closeout`,
`state-review-form-verified`; earlier scenario captures remain in the same directory.
Criteria C1–C8 passed for the exercised bounded journey after fixes.

Acceptance received only the user outcome and synthetic-data/setup boundaries,
without a control-by-control walkthrough or design/implementation brief. Before
reading changed UI code it attempted the journey on its own new disposable profile:

1. Imported the additional CSV; recognized derived activity dates rather than a
   statement period. Created savings and explicitly applied the document assignment.
   Understood this had not posted activity; then explicitly reviewed $25 income.
2. Used the document-date report action and recognized all-profile-account scope
   and whole-profile/all-date pending counts. Reported the empty-Spending wording
   misunderstanding above; fresh-process recheck confirmed the fix.
3. From October spending $4 Food, inspected Coffee and immutable CSV evidence
   (locations and balances), navigated to exact source row, corrected Food → Travel
   with a reason and net-zero/reversal confirmation, then returned to retained
   October 1–4 Spending. Deposit remained $10 income; Tea remained $3 pending.
4. Restart verified spending 400 minor, income 3500 minor (including the new $25),
   seven sources and one correction. Scripted refusal preserved seven sources,
   19 journal entries and the selected original; cancellation preserved prior work.

Assistance/wrong turns: Qt harness setup required process restarts, file-picker
assistance and a stale-button-label retry. This was a goal-derived **assisted agent
attempt** using visible-widget inspection, not an unfamiliar human's uncoached
native-input test. No product-control walkthrough was supplied; successful control
activation is not proof of human discovery/comprehension. Acceptance separately
checked empty/missing-catalog blocking, invalid-date clearing, draft refusal,
import cancellation/refusal, account validation, keyboard exit and restart.
Its machine-local screenshots and JSON results are under
`scratch/v2-core-journey-acceptance-20261107/`, including `goal-corrected.png`,
`goal-source-evidence.png`, `recheck-refused-import.png` and
`recheck-account-validation.png`. Batch recovery had automated/integrity checks;
acceptance did not independently repeat the batch interaction.

## Remaining work

No remaining significant finding in the exercised first-improvement journey.
Technical completion, agent design/usability verification and independent financial
review are recorded above. Actual human acceptance has not occurred.

- Specialist saved histories still lead with technical event/journal/proof detail;
  making these concise narratives remains further UI work.
- Source evidence opens the whole document, without highlighting the originating
  report row. Exact row/account navigation into Review is implemented.
- At 920×640 Accounts with 55 long names is cramped; Reports expands to approximately
  920×693 to retain controls. Standard 1050×700 and larger inspected sizes work.
- Larger archives/cold loads, native Windows input/discovery, assistive technology,
  display scaling, Intel macOS, installed/offline behavior and unfamiliar-human
  task performance remain unverified here. Source Qt checks do not establish them.
- Consolidated V2-UX human acceptance, separate existing owner accounting review,
  supported-platform and exact-candidate release gates remain open. No production
  signing, daily-profile activation, publication, release or commit was performed.

## November 8: reusable pytest-qt journey verification

Authorization: install necessary development dependencies and test the complete
import → account setup/assignment → review → spending interpretation → correction
journey using screenshots and Qt software-test events. Same synthetic-only boundary;
no native computer-use workaround or live data access.

Roles/write ownership: primary owns dependency lock, shared pytest configuration,
documentation and integration. Desktop owns new Qt journey tests/helpers. ui_ux
reuses C1–C8 and inspects resulting actual renders. A fresh acceptance reviewer
receives only outcome and setup data before independently attempting the task.
All existing uncommitted journey changes are preserved.

Dependency: `pytest-qt>=4.5,<5`, resolved to 4.5.0 in `client/uv.lock`; configured
`qt_api = "pyside6"`. Lock diff adds only pytest-qt and its project references.
`uv lock` and `uv sync` do not load dotenv files; no root `.env` was read. The first
sync encountered existing editable-file permissions; the approved retry installed
the locked dependency in the existing client environment. No runtime package
upgrade was selected. An initial `uv lock --no-env-file` was rejected by CLI parsing
(that flag belongs to `uv run`); the corrected lock command completed.

Shared pytest support provides native-render opt-in and a repository-scratch-only
artifact directory with per-test unique output and Python/Qt/platform metadata.
Default journey runs use offscreen rendering; explicit native runs assert a real
platform plugin. Screenshots and widget event checks remain agent/software-test
evidence, distinct from direct Windows input, OS integration and human acceptance.

### Reusable scenarios and artifacts

`client/tests/test_v2_qt_journey.py` drives the entire journey from an empty
profile at both 1050×700 and 1280×800. Only fixture-signed catalog installation and
synthetic input bytes precede UI interaction. Import, account creation, separate
account assignment, category creation, expense/income review, confirmations,
source inspection, cancelled and saved correction, original recovery, backup,
restore-as-new and reopen all use actual widget events. Store access afterward is
read-only verification. It verifies $4 expense, $10 income, $3 pending; category
correction moves $4 Food → Travel without changing spending/income/pending amounts.
Document dates initially select October 1 inclusive–4 exclusive; a keyboard-edited
exclusive end of October 15 remains after correction and return.

Additional cases cover refused import with actionable recovery, exact-source retry,
and in-flight cancellation. Cancellation holds only the pre-decoder test boundary,
presses the actual Cancel button and forwards the actual worker flag to the real
importer; no source or journal is created. This does not claim mid-decoder native
resource/cancellation timing. `test_v2_qt_category_navigation.py` separately verifies
the original Accounts-page category route refreshes Review and a local manager
close retains row, purpose, category, reason and staged choices without posting.
`qt_journey_helpers.py` supplies condition-driven modal steps and real mouse/key
events; it never replaces application action slots or financial confirmations.

Final native artifacts are machine-local, under
`scratch/v2-qt-journey-20261108/final-native/`. `latest.json` selects the latest
five scenario runs and lists 52 screenshots (22 per full journey, four refusal/
retry and two each cancellation/category-draft cases). Prior debug captures remain
available in separate directories and are not the final evidence. Runtime records
show Windows AMD64, Python 3.13.15, Qt/PySide6 6.11.2, pytest 9.1.1, pytest-qt 4.5.0,
`windows` platform, Segoe UI 9, 96 logical DPI and device-pixel ratio 1.0.
Standalone evidence/drilldown dialogs record their own sizes, not the workspace
parameter. Other scaling and platforms were not checked.

Offscreen initially had no registered fonts and rendered missing-glyph boxes,
spuriously expanding a 1050-wide request to 1194. Those images were rejected as
visual evidence. The journey fixture now explicitly registers installed Windows
Segoe UI only for an otherwise fontless offscreen plugin and records the adjustment.
Native runs retain the platform font unchanged and fit both requested sizes.
Helpers prepare Qt application focus before input, with a narrowly filtered known
Qt deprecation warning; this does not test actual Windows foreground activation.
File pickers are real Qt dialogs with native dialogs disabled for this test scope;
the setting is restored afterward.

### Findings fixed and independently rechecked

| Observed in fresh-profile testing | Result |
| --- | --- |
| Cash review demanded categories but had no adjacent setup action; reviewer searched five menus and Reports before finding the Accounts page | Added Manage categories beside the cash category choice, consistent with card review; appropriate expense/income class and row/reason/staged context retained. |
| Categories created on the Accounts page stayed absent in retained Review until Reload | Category dialog close refreshes retained review with drafts preserved. |
| Report-to-Coffee review still displayed Income posted from an earlier row | Explicit row changes clear unrelated outcome feedback; automatic post-save filter advancement retains fresh completion feedback. |
| Import refusal recommended updating formats while Manage statement formats remained disabled; cancellation had the same stale controls | Import completion restores all controls from current worker/profile state; refusal and actual in-flight Cancel tests and screenshots verify format/account/import recovery actions. |

These are presentation/navigation fixes only. Headless accounting, source evidence,
schema, signed-format authentication and confirmation ownership remain unchanged.

### Independent goal-derived attempt

A fresh acceptance agent received the goal, synthetic CSV schema and empty-profile/
fixture-catalog setup recipe, without the new tests or control directions. It used
visible-widget inspection and Qt events with native Windows rendering. It imported
its independently chosen rows, created and assigned Everyday Checking, reviewed
$17.35 expense and $120 income, inspected immutable source evidence, corrected
Dining → Groceries and returned to October 3 inclusive–6 exclusive report dates.
Final display was Groceries $17.35, Dining $0, Wages $120 and $28.40 still pending.

Wrong turns/recovery: it searched Settings, Accounts, Review, Reports and Profile
menus, then Reports, before finding category creation on the Accounts page. It then
had to discover Reload to see the categories. It also reported the unrelated
Income posted message on correction arrival. All findings above were fixed and
rechecked in a new process; rechecks necessarily had knowledge of those findings.
The agent had read baseline runtime documentation before its first attempt and
used widget introspection/focus preparation, so this remains assisted agent evidence
rather than unfamiliar-human discovery. No task walkthrough or implementation
brief was supplied before the initial attempt.

Independent checks: four exact persistence tests passed against its original and
new recheck profiles. Fresh source bytes, exact source amounts, reversal/replacement
history, income and pending state survived. A further two focused Windows-rendered
refusal/cancel tests passed after the recovery-control fix, and their actual
screenshots were inspected. Artifacts are under `scratch/qt-independent/attempt-02`,
`recheck-03` and `recovery-04`. One independent run could not update pytest's cache;
its tests/artifacts completed. Primary runs disable that cache provider.

ui_ux inspected actual final native screenshots against C1–C8, including loading,
empty, unassigned/blocked, invalid account input, explicit confirmations, category
draft/cancel, exact report scope, correction, evidence, restored state and refusal/
cancel recovery. No significant unresolved obstacle remains in those exercised
states. Its review and the primary's screenshot inspection remain implementation-
informed agent checks, separate from actual human acceptance.

### November 8 verification

- Final Windows-rendered scenario run: **5 passed** in 16.82 seconds, including
  captures of the corrected spending report with the edited dates retained.
- Documented `uv run --project client --extra dev --no-env-file --frozen python -m
  pytest …` path, without a custom PYTHONPATH: **5 passed** in 19.76 seconds,
  with readable offscreen captures under the sibling `final-offscreen` directory.
- Focused current-code integration across new scenarios, workspace/guided review,
  cash, ordinary async/batch and repayment-category routes: **65 passed**.
- Initial focused dependency smoke: 22 passed; intermediate current-code check:
  46 passed. Counts overlap and must not be added as unique coverage.
- Broader existing V2 compatibility run with pytest-qt loaded: **1335 passed,
  3 skipped, 1157 deselected**, with one failed test whose `CaptureDrilldown` spy
  lacked the navigation signal added by the preceding journey implementation.
  Updated that test double to a QObject exposing the real signal contract; its
  affected category/report tests were rerun separately: **23 passed**. The broad run overlapped
  development, so final-code verification is the targeted integration/replay
  above plus the affected-test rerun, not a claim that this broad command passed
  unchanged against every final file. Full run took 1509.72 seconds.
- Changed-file Ruff and diff checks passed; frozen lock validation resolved the
  existing 85-package lock without changing it. Final source includes a corrected
  spending screenshot added after the offscreen replay (native replay verifies it).

Reproduction from repository root (setup uses locked Python 3.13.15):

```powershell
uv sync --project client --extra dev --frozen
uv run --project client --extra dev --no-env-file --frozen python -m pytest client/tests/test_v2_qt_journey.py client/tests/test_v2_qt_category_navigation.py -p no:cacheprovider -q
uv run --project client --extra dev --no-env-file --frozen python -m pytest client/tests/test_v2_qt_journey.py client/tests/test_v2_qt_category_navigation.py --journey-native --journey-artifacts scratch/qt-journey-review -p no:cacheprovider -q
```

The first-development-slice limitations above remain: technical specialist history,
whole-document evidence without originating-row highlighting, narrow/large account
list density, direct OS input/native pickers, assistive technology, other platforms,
installed/offline behavior and actual human acceptance. No live/private data,
production service, daily-profile activation, signing, publication or release action
was involved in this follow-up.

The new complete UI replay uses a synthetic checking CSV export, with derived
activity-span labels rather than a printed statement period. A new full PDF/card/
loan/HSA journey was not replayed by this fixture; their existing V2 checks and
earlier reviewed UI evidence remain separate coverage.

### Owner walkthrough prepared

On November 8 the owner requested opening the revised app to test the journey.
Prepared a new empty synthetic profile at
`scratch/v2-journey-human-20261108-38e7bf7d/review.db`, with the same fixture-signed
CSV definition and `Checking-October.csv` ready to select. No accounts, imports or
journals were preseeded; prior profiles were not selected or modified. Launched
current source in the interactive Windows session as
`ParseTrail - YOUR JOURNEY TEST (synthetic)`; startup reported visible/ready with
the Windows Qt plugin. `Open-journey.cmd` reopens this exact disposable workspace.
This records preparation/opening only; owner task results and acceptance are pending.

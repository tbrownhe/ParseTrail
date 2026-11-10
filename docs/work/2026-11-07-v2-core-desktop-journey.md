# Core desktop journey: imported evidence to reviewed spending

Date: 2026-11-07. Roadmap: V2-UX, V2-3/4/5/6.
Branch: `feature/client-financial-insights`; client only.
Authorization: user requested integrated journey implementation and verification;
synthetic disposable profiles/statements only. No live profiles, private archives,
production, signing, publication or release actions.
Implementation: staging-only ordinary review and prior account-first import/product, routing, focus, budget and color improvements implemented.
Automated verification: focused and process-isolated journey checks passed; unresolved native heap diagnostic archived and active investigation deferred at the owner's request.
Design verification: actual Windows Qt rendering/software-event checks passed.
Independent review: staging usability findings fixed and rechecked; process containment and archive reviewed; correction-note feedback and lifecycle limits remain recorded below.
Owner acceptance: walkthrough feedback recorded; integrated acceptance remains pending. Release authorization: not requested.

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

One minor separate usability observation remains: a report-return correction can
prefill the original review note and describe it as a new unsaved note, enabling
withdrawal without a new edit. No withdrawal occurs without confirmation. This is
distinct from the resolved staged-badge finding and is not attested as fixed.
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

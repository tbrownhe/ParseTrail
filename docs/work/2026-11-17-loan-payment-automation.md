# Opt-in loan payment posting and completion cues

Date: 2026-11-17. Roadmap IDs: V2-3/4/UX. Branch/components: client desktop/core.
Authorization: owner approved the proposed opt-in automation, sole-row selection,
separate transfer resolution and completed-action color correction.
Implementation: complete.
Automated verification: focused core/integration, existing regression and native UI
checks passed; unchanged schema 27 and a fresh pinned runtime verified.
Design verification: agreed journey reviewed before implementation; actual integrated
native screenshots inspected and both disclosure layout findings closed.
Independent review: 15 synthetic authority/accounting cases passed; no unresolved
financial findings. Integrated design found and rechecked disclosure/completion cues.
Owner acceptance: pending; prior owner feedback confirms near-instant import loading
and no unnecessary CAPONE import preview, separately from this new behavior.
Release authorization: not requested.

## Scope and controlling decisions

A default-off global preference authorizes automatic lender-side posting for future
eligible imports. Start with one complete audited Capital loan-history v2 payment,
compatible bound loan-principal account, exact printed principal/interest/gross,
permitted accounting date and no material warning, ambiguity, overlap or prior use.
The existing narrow missing-opening warning exception remains informational.
Origination, unsupported/multiple/incomplete rows and defects stay in manual Review.
Enabling the setting never sweeps existing documents or revives withdrawn postings.

Posting reduces principal, records printed interest under Loan interest and leaves
the paying-account counterpart unresolved in Transfers. It never selects a bank
transaction. Automatic history must say automatic rather than imply human inspection;
retained evidence, whole-event correction, exact money and unknown openings remain.
Import success and subsequent automation failure are distinct results.

User journey: enable the setting beside import preferences or in loan review; import;
see posted principal/interest and unresolved counterpart without a review dialog.
When manual review is needed, show its reason. In fresh focused manual review select
the sole eligible payment automatically. Pending review actions are primary blue;
saved payment/origination inspection is neutral. Completed statement review says
Review complete while retaining optional history and Transfers access.

Observable criteria include discovering the opt-in and its future-import effect,
understanding what was posted and remains unresolved, recognizing completed review,
and reaching existing correction/history without an implied required action.

Ownership: primary owns integration, contracts/planning and work record; ledger
specialist owns core/preferences/result DTOs and focused core checks; desktop
specialist owns GUI and native synthetic checks; integrity specialist independently
reviews authorization, atomicity, cancellation, retry and provenance. Specialists
do not commit or recursively delegate. Existing owner test workspaces and all their
data remain untouched; only public fixtures and newly isolated profiles are allowed.
No service, production, signing, deployment or daily-profile activation is included.

## Result and review

Baseline: 0b2a8fa. Profile schema 27 is unchanged. Core adds
`auto_post_loan_payments`, a workspace setter, a finite headless automation policy
and separate immutable `loan_automation` results on source/batch outcomes. Imported
evidence is committed first; any subsequent automatic-posting refusal/failure rolls
back its financial effects while preserving the saved source. Batch cancellation
keeps that file imported and stops remaining files. Disabled/non-loan/saved-retry
paths do not attempt automation.

Consent and physical profile identity are captured at file-import start. The policy
requires strict true consent, rechecks audited parser/version and all evidence under
the write lock, then rechecks consent/date preference, physical profile and cancellation
before recording and before commit. Every historical use, including withdrawn events,
refuses automation. Exact source retries return the saved source without a posting.
Pre-existing compatible accounts qualify; new account establishment stays manual.

GUI adds a Settings action and a checkbox under the payment panel's existing
details disclosure with future-import wording. Keeping this rare preference in
details preserves the payment table space and established 1100x650 layout.
The sole eligible row is selected once for a fresh manual review; multiple rows,
stale resets and corrections preserve explicit selection behavior. Automatic events
have truthful labels in landing/history; all-complete documents say Review complete.
Saved payment/origination inspection actions are neutral. The active Post action
uses the shared primary style. Batch results distinguish imported evidence, automatic
posting and reasoned manual fallback.

Independent integrity review prompted two closed fixes: strict headless opt-in
enforcement, and cancellation aggregation that retains import success while stopping
the batch. No private data or existing owner candidates were used or modified.

## Verification

Root integration/regression command (locked Windows source runtime, isolated
APPDATA/LOCALAPPDATA; conftest isolates HOME/USERPROFILE and null keyring):

```text
client/.venv/Scripts/python.exe -B -m pytest -q -o cache_dir=scratch/loan-auto-root-test/pytest-cache client/tests/test_v2_loan_automation_integration.py client/tests/test_v2_prepared_import_integration.py client/tests/test_v2_pdf_decode_operation.py client/tests/test_v2_import_automation.py
```

23 passed in 71.72 seconds, raw exit 0. The new integrated case forbids the parser
and PDF worker after confirmation while posting automatically, reading reports,
withdrawing and retrying. It verifies exact saved source/evidence, interest-only
spending, separate unresolved gross, withdrawal inverses and no retry revival.
An earlier one-test pass emitted a pytest-cache permission warning; the final run
used the isolated cache above. Counts overlap and must not be added.

Independent integrity: `scratch/loan-auto-integrity-20261117/review.py` and
`summary.json`, 15 cases, final raw exit 0. Covers default-off/strict consent,
date/new-account/profile/warning/origination/multiple refusals, cancellation at all
four authorization checkpoints, exact 20000 principal/2000 interest/-22000 clearing
minor units without bank leg, active/withdrawn history and unchanged source evidence.
An initial harness used a nonexistent export method; corrected before the successful
complete run.

Core specialist verification: new `test_v2_loan_automation.py` covers 20 passing
cases across the focused suite and targeted rechecks. An initial multiple-row fixture
put its row after the coupon stop and correctly triggered unexplained-content review;
moving it into the activity body tested the intended multiple-payment refusal.
Existing `test_v2_loan_payments.py`, `test_v2_workspace_account_import.py` and
`test_v2_workspace_recognition.py`: 62 passed in 178.84 seconds, raw exit 0.
Changed core Python files passed Ruff check/format and whitespace checks.

Root inspected actual native 1050x700 screenshots under
`scratch/loan-auto-ui-20261117/final`: selected-payment/future-consent, automatic
complete/neutral payment and reasoned manual fallback. Fields/columns/actions are
readable, scope and future-only effect explicit, and completed review remains distinct
from optional Transfers. Native tests use Qt software events; this is separate from
owner acceptance and other-platform, hardware-input and accessibility validation.

Desktop verification: final native Windows Qt suite (new automation UI, existing
loan-document/cues checks) passed 19 cases in 51.09 seconds, raw exit 0. Evidence:
`scratch/loan-auto-ui-20261117/final-native.log` and `final-native/` captures.
Covered Settings persistence/future-only effect, no implicit date permission,
sole-row/multiple-row selection, retained manual draft, truthful automatic history,
saved origination, partial-document completion and reasoned import outcomes.
Actual window sizes include 1050x700, 1280x800 and 1100x650. New disposable views
explicitly verify GUI-thread destruction and native invalidation. Normal GC remains
enabled; no Qt exceptions in the successful final process.

Existing loan-payment dialog, core-journey and specialist responsiveness tests passed
30 cases in 78.85 seconds, raw exit 0, in their intended offscreen process:
`scratch/loan-auto-ui-20261117/final-regression.log`. Old stale-selection tests now
explicitly uncheck the new initially selected sole row before changing context, and
stale-preview tests verify a fresh lender-only manifest/source/basis rather than
expecting bank-less preview to be absent. Source/profile safety assertions remain.

Intermediate integration findings and disposition:

- Persistent preference text crowded the established 1100x650 layout. Moving the
  rare setting under existing details preserved the payment area. Design review
  then found retained blank space after collapse; local maximum vertical policy
  and a settled disclosure-height assertion resolved it at all three sizes.
- The first mixed-mode run let a legacy autouse fixture create an offscreen app
  before native tests. Those native checks correctly refused that mode. Assertion
  aborts also exposed two `ProfileJobs._detach` missing `_timer` messages during
  retained-object GC. No controller code or GC suppression was added: a separate
  20-cycle native QWidget/controller GC probe exited 0, and both corrected final
  processes above exited 0 without Qt exceptions. This does not certify every
  interrupted-assertion/interpreter-shutdown combination.
- Running the legacy layout test under an already-native app also exposed an
  unrelated settlement viewport threshold (81 rather than 100 pixels). The
  unmodified settlement source reproduced that native layout without any loan
  dialog: `settlement-baseline.json/.png`. Its assertion and source were not
  weakened. The legacy suite passes under its intended offscreen fixture;
  broader native settlement layout remains a separate limitation.

Independent UI/UX screenshot/code review verified clear future-only authorization,
neutral completed actions, partial-document readiness, automatic history and optional
Transfers. Final collapsed screenshots have no retained blank band. This is qualified
screen/code review rather than independent live interaction or uncoached discovery.

Expanded compact details initially compressed the payment row. A local 70-pixel
minimum and noncollapsible table preserve header plus a complete row while retaining
the collapsed 1100x650 window. Final targeted native checks passed all three size
cases in 6.46 seconds, raw exit 0, asserting the visible row and settled collapsed
geometry. The affected existing offscreen working-font layout check passed in
7.99 seconds, raw exit 0. Evidence: `final-row-visible-v2/`, including expanded and
collapsed 1100x650 captures in `size2_/033a1050`. Independent design and primary
reinspection closed the blank-space and compact-row findings. All changed Python
files passed Ruff checks/format; normal commit hooks passed.
An additional read-only native 1100x650 geometry probe exited 0: row height 24,
item rectangle fully inside the 42-pixel viewport, confirming full text/checkbox
visibility despite a tight table border (`visible-row-probe.json/.png`).

Code commits: `87695b7` (headless opt-in policy and integration checks), `958dc43`
(desktop setting, completion cues and native regressions).

## Fresh disposable owner test

Prepared `scratch/v2-owner-fresh-20261117-70721fc1/Open-workflow-test.cmd` from code
commit `958dc439b3dc95914e21eaa3a27bee074ae7095a`: 314 pinned runtime files, schema 27,
23 public development declarations and no imported sources, financial accounts,
budgets, journals or transfer/origination/value events. Only the protected Loan
interest category is initialized. The development fixture signing key was discarded.
Global preferences/catalog/app-home are isolated within this new folder; automatic
loan posting and assumed dates both start off. START-HERE explains establishing the
account, opting in, importing subsequent supported payments and checking history,
correction and separate Transfers. Earlier populated test workspaces remain untouched.

Preparation and pinned native-plugin startup commands:

```text
client/.venv/Scripts/python.exe -B -X utf8 scratch/v2-owner-fresh-20261117-70721fc1/prepare_fresh.py
client/.venv/Scripts/python.exe -B -X utf8 scratch/v2-owner-fresh-20261117-70721fc1/runtime/devtools/owner_fresh/fresh_launch.py --open scratch/v2-owner-fresh-20261117-70721fc1 --smoke
```

Both raw exits 0. Startup found an empty Documents view, enabled Import, the six
expected navigation items and unchanged profile bytes; native Qt exit 0. Startup
smoke uses the Windows plugin with its window hidden, separately from the visible
native UI tests above. App left closed. After owner import this folder is private;
preparation does not authorize later inspection of its financial data.

## Remaining work

No implementation or scoped agent-review findings remain. Owner use of this exact
candidate, other platforms/scaling/hardware-input/accessibility and installed/release
validation remain separate; no publication or daily-profile activation is authorized.

# Loan review cues and import confirmation timing

Date: 2026-11-16. Roadmap IDs: V2-UX, V2-3/4.
Baseline: e14851d, clean working tree; local desktop and import evidence only.
Authorization: owner-requested four follow-up refinements and import profiling.
Implementation: complete; committed code and isolated candidate prepared.
Automated verification: focused, integration and native checks passed.
Design verification: pre-implementation state model and actual rendered review passed.
Independent integrity: warning/source and import-reuse findings resolved and rechecked.
Owner acceptance: owner reports successful direct tangible financing, independent
dated depreciation estimate, and correction to unresolved destination in the prior
candidate. This is evidence for those exercised paths, not acceptance of new changes.
Release authorization: not granted.

## Scope and controlling decisions

Use existing blue primary-action and red/green field conventions on the loan
landing, origination and asset-creation screens. Put Create tangible asset in the
destination selector as a command, never a persisted destination. Cancel restores
the prior choice; a created account still requires explicit financing allocation.
Destination not established is valid and must not look like a missing requirement.

For the narrowly supported Capital payment shape with observed closing principal
and complete payment component arithmetic, absent opening may be informational at
import. Keep the opening unknown and full balance equation unverified. Actual
mismatches, unknown components and other monetary defects still require review.

Measure the owner-observed delay after Import and Assign using public synthetic
statements and disposable profiles. Distinguish confirmation/save, worker handoff
and visible inventory refresh; change performance only with a measured cause.
Do not remove integrity checks or introduce persistent evidence caches.

Root owns the three affected loan/asset GUI modules and their focused tests,
integration, contracts and this record. Evidence owns warning projection, audited
loan-history source extraction and their tests. After the measured proposal,
desktop owns `v2_bounded_pdf_text.py`, `v2_workspace.py`, the focused operation
tests and scratch profiling harness. Read-only UI design
review precedes changes; independent warning/performance review follows as needed.
No recursive delegation or concurrent writers per file.

Only public synthetic fixtures and new disposable profiles may be mutated. All
owner-populated candidates, including the last fresh test, stay private and
untouched. One previously authorized Capital payment original was inspected only
in memory to establish finite field grammar and aggregate warning behavior; no
private text, amounts, identities or paths enter Git/routine logs. No archives,
root environment, server or release actions are selected. Preserve ordinary local
import/storage/trust and Qt lifetime boundaries.

Observable criteria: obvious blue next action; a single understandable destination
choice including creation; red only for applicable missing required input and
green for valid pending choices; cancel/reopen/failure recovery; accurate source
qualifications and reproducible timing measurements. Inspect actual Qt screenshots
and process shutdown with normal GC; do not attest human/platform acceptance.

## Result and review

The enabled loan landing Review/View action is blue. Origination's destination
selector includes Create tangible asset as a queued command; there is no
second creation button. The preceding selection is restored before opening its
disposable dialog, including valid None. Cancel retains it; creation selects the
new asset but requires explicit financing confirmation. The command never enters
the financial preview. Required editable fields use red/green cues; valid optional
unresolved destinations and blank annual rates stay neutral. Saved financing
does not acquire a new date-permission requirement; correction needs a fresh reason.

The missing-opening exception requires audited Capital engine
`loan-history-lines-pilot-2`, one supported observed payment with exact complete
components and printed closing principal. It retains the unavailable warning code
with informational qualification, unknown opening, unverified capture and unverified
independent balance. Existing unaudited snapshots do not qualify or get overwritten.

Independent review exposed a prior parser omission: another payment or money
outside the first history end could be ignored, which the new exception would
otherwise conceal. Engine v2 now retains every exterior raw line/location and
audits residual money/dates after consuming exact supported source-field spans.
Known due dates, payment/payoff summaries, blank coupon and explanatory label
references stay separate from activity. Unknown amounts, extra payments, malformed
fields and filled coupons remain review-required/refused. Strict token boundaries
prevent a valid money prefix hiding malformed suffixes. Public counterexamples and
the authorized representative payment verify the distinction. That payment has
zero review-required warnings, while opening remains unknown and both verification
flags remain false. No complete-capture or private-family parity claim is made.

Profiling found four bounded PDF children after confirmation. On the first public
synthetic sample, they consumed 0.738 of 0.817 seconds (90%); catalog verification
was 0.013 seconds, profile validation 0.012, source insert 0.0009 and binding 0.0074.
The improvement reuses only validated immutable decoded pages/metadata during the
confirmed synchronous import operation, keyed by exact bytes, worker mode and
limits. Source/catalog/routing/candidate/account/profile/transactional checks still
run. Cancellation is checked before lookup and again before returning reused/new
output. Finally clears retained references and resets context on every exit;
nested/thread operations are isolated. There is no preview or cross-import cache.

Native click-to-ready median across four public synthetic samples improved from
0.866 to 0.319 seconds (63.2%); actual decoder children decreased from four to one.
The owner's approximately two-second delay was not reproduced. This measures a
small public statement and finite synthetic growth, not private-history performance.

## Verification

Locked Python 3.13.15 on Windows AMD64, Qt 6.11.2 windows plugin, Segoe UI 9,
DPR 1/96 DPI; disposable homes/preferences/catalogs/profiles and null keyring.
Explicit APPDATA/LOCALAPPDATA were isolated for final native/performance/integrity
runs. Commands use `PYTHONPATH=.;client/src;client`,
`client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider ... -q --tb=short`.

- UI baseline origination desktop/loan source: 25 passed offscreen. New cue/creation
  functional selection: 5 passed. Native `test_v2_loan_review_cues.py` plus default
  origination post/reopen/withdraw and loan landing: 7 passed, raw exit 0; added
  saved/correction conditional-state check: 1 passed native, raw exit 0.
- Final warning/source focused selection: 134 passed. Combined warning,
  recognition, catalog, preview, source-evidence, loan, bounded pipeline/family
  and catalog-admission selection: 289 passed in 182.51 seconds.
- Actual audited-engine Capital journal/consumption/report/withdrawal/backup and
  zero-principal/unknown-interest regression: 2 passed.
- Performance author final operation/workspace account import/bounded text/import
  automation selection: 35 passed, raw exit 0. Independent import integration:
  43 passed; final operation cancellation/cleanup selection: 7 passed.
- Independent warning/source recheck: 134 passed plus 14 additional full-PDF
  approved-field/unknown-money/date/coupon/tail counterexamples. No actionable
  integrity finding remains. Counts overlap; they are not additive.
- Ruff check/format passes all 12 changed Python files; diff whitespace clean.

Native UI artifacts: `scratch/loan-cues/` and `scratch/loan-cues-final/`.
Independent read-only design review inspected six rendered states: blue landing,
missing/valid conditional choices, neutral unresolved destination, invalid estimate
and valid estimate; no blocking issue or clipping at 1050x700, 960x540 and 880x620.
Root also exercised keyboard popup command selection/cancel from both None and
an account, successful creation without auto-confirmation, and saved correction.
Hardware input, additional scaling, longer names/narrower windows and human
comprehension were not independently assessed in this pass.

Timing artifacts: `scratch/import-assign-profile-20261116/` (summaries,
timelines, improved cProfiles, native screenshots and measurement details).
One-page 1,172-byte public synthetic Capital PDF, full 23-declaration fixture
catalog; distinct bytes/comments grow profiles without resembling private history.
Backend confirmation-to-save measurements (baseline -> improved), seconds:
1 source 0.817 -> 0.296; 2 sources 0.760 -> 0.265; 12/13 sources
0.743/0.743 -> 0.294/0.322; 52/53 sources 0.736/0.740 -> 0.283/0.287.
Native click-to-ready at 1/2/22/23 sources: baseline
0.958/0.875/0.857/0.858; improved 0.306/0.470/0.316/0.322.
Native baseline was measured by disabling only the new operation context in the
same harness; backend baseline preceded implementation. Baseline summaries retain
original timelines; per-run cProfiles were overwritten by the improved phase.
Cold means process state, not a flushed OS cache. Account choices were prepared
programmatically before the timed native button click. Two initial harnesses were
stopped for QTest wait/GIL starvation; changing harness event waiting fixed them.
Successful native sequences closed/deferred deletion and exited 0 with normal GC.
This does not establish general Qt lifetime safety, installed or other-platform results.

Implementation commits: `3904ce4` UI cues/creation, `0918a45` audited Capital
qualification, `09fcf62` operation-scoped decoding. Normal commit hooks passed.
Current parsing contract and roadmap/TODO/work index updated.

Fresh test: `scratch/v2-owner-fresh-20261116-19b2432e/`, launcher
`Open-workflow-test.cmd`, instructions `START-HERE.txt`. Schema 27, 23 fixture
declarations signed with an ephemeral development key (private key discarded),
312 pinned public runtime files from `09fcf62`, independent home/catalog/preferences.
No documents, financial accounts, budgets or journals preloaded; only protected
Loan interest is seeded. Pinned native startup passed: Windows plugin, six sidebar
steps, import enabled, empty documents, unchanged profile digest, raw exit 0.
The app is closed; relaunch preserves this profile. No earlier populated profile
was read or modified; only two explicitly public preparation-helper code files
were reused. Treat this new folder as private once the owner imports statements.

## Remaining work

Owner verification of actual statement latency and refined controls, broader
source-family parity, hardware-input, installed/Intel and release gates remain
separate. Existing private candidates remain pinned and untouched. No required
implementation or review finding remains open within this finite scope.

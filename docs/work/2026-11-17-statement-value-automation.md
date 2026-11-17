# Opt-in statement value recording after import

Date: 2026-11-17. Roadmap IDs: V2-3/4/5/UX. Components: client core/desktop.
Authorization: owner requested a user setting to record statement value upon
successful import after accepting the Fidelity summary-review journey.
Implementation: complete.
Automated verification: focused core/integration, existing regression and native UI
checks passed; fresh pinned runtime startup passed.
Design verification: existing-journey extension reviewed before implementation;
actual integrated native screenshots rechecked with no significant findings.
Independent review: financial/provenance and transaction/history/cancellation checks
passed; no unresolved actionable findings.
Owner acceptance: pending for this extension; prior summary review accepted separately.
Release authorization: not requested.

## Scope and controlling decisions

Add a separate default-off global Automatically record supported statement values
preference in Settings and under retirement Review's existing details disclosure.
It authorizes eligible future imports only. Initially support the existing finite
Fidelity 401(k) summary family, one explicitly bound compatible section, exact
evidenced closing value/date, no material source warning, conflict or prior value
history for that source. A newly created account can qualify after explicit import
confirmation. Agreeing manual/other-source points remain separate claims and are
not summed; differing values at that date require manual review.

Capture opt-in/profile at file-import start; enabling during a preview affects
later imports. Recheck consent, cancellation and physical profile under the value
write lock and before commit. Use existing source proof, candidate and basis guards.
The automatically recorded value remains a nonposting fact: no journals, individual
transactions, transfers, income, spending or budget changes. The assumed-posting-date
preference is unrelated. No schema, parser, declaration or service changes.

Enabling never sweeps saved statements, records the current Review draft or revives
withdrawn/corrected history. Exact saved-source retries never record another value.
Automatic reasons/results must be truthful rather than claim human inspection.
Import success and subsequent automation refusal/failure/cancellation stay separate;
imported evidence remains saved. Cancelled batches stop after the saved file.

User journey: enable the setting once; import a supported statement; see its value
recorded automatically and summary Review complete, with neutral history access.
An ineligible imported statement gives a specific manual-review reason. The toggle
preserves current reference/reason edits, mirrors Settings and recovers if preference
saving fails. Expanded/collapsed details remain compact at 1100x650 and 1050x700,
with keyboard access and no duplicate confirmation modal.

Ownership: primary owns integration, contracts/planning and this record; ledger owns
preferences/workspace/automation policy/source-value protocol/core tests; desktop owns
controls/results/history presentation/native tests; UI/UX establishes and rechecks
the interaction; integrity independently reviews consent, exact proofs, atomicity,
history, cancellation and privacy. One writer per file, no specialist commits or
recursive delegation. Only public synthetic sources and new disposable profiles;
all existing owner profiles, originals, archives and logs remain untouched.

## Result and review

Baseline: 17c9c53. Core adds `auto_record_statement_values`, its workspace setter and
an immutable `StatementValueAutomationResult` on source/batch outcomes. New source
imports are committed before the separate guarded value write. Disabled, unrelated
and already-imported paths do not record a value. The existing loan automation remains
separate and obeys its original assumed-date and established-account policy.

The headless value policy reuses the exact source closing candidate, proof, basis and
physical-profile checks. Optional trusted `before_write` and `before_commit` lifecycle
callbacks run inside the existing source-value transaction; ordinary manual callers
retain their previous behavior. Policy/consent/history checks run before the historical
receipt branch, preventing that branch from returning a retired receipt as a new
automatic success. Consent/cancellation are checked after insertion/validation and
immediately before commit. Any failure rolls back value metadata while retaining
the source import; batch cancellation stops after that imported file.

UI adds a Settings action and details checkbox with future-only wording and current
Fidelity scope. Both controls synchronize without clearing reference/reason fields or
recording a current saved statement. Automatic results/completion identify automatic
authorization, keep history actions neutral and distinguish nonposting values from
loan postings. Missing-field cues retain priority alongside preference notices;
preference failures restore the previous choice and preserve the manual draft.

No profile schema, parser, declaration, journal or transaction-date policy changed.
No service, contribution, production or daily-profile work was performed. Existing
owner workspaces were not opened or modified. Code commits: `d8d1b13` (core and
integration), `e14c5c5` (desktop controls/results and native checks).

## Verification

Windows source runtime uses locked `client/.venv/Scripts/python.exe`. Tests isolate
APPDATA/LOCALAPPDATA, HOME/USERPROFILE and null keyring; public synthetic sources only.

Root actual-import integration:

```text
client/.venv/Scripts/python.exe -B -m pytest -q -o cache_dir=scratch/statement-auto-root-test/cache client/tests/test_v2_statement_value_automation_integration.py
```

1 passed in 3.56 seconds, raw exit 0. A public signed-catalog PDF creates a new
confirmed account with both automation flags enabled and assumed posting dates off.
Exactly one preparation parse occurs; parser/PDF worker are forbidden after confirmation
through automatic recording, Reports, withdrawal and saved retry. Exact source/evidence,
dated value and truthful automatic reason persist with no journal, category income/
spending or Transfers effect. Withdrawal reopens Review; retry cannot revive it.

Root affected regression:

```text
client/.venv/Scripts/python.exe -B -m pytest -q -o cache_dir=scratch/statement-auto-root-test/cache client/tests/test_v2_loan_automation.py client/tests/test_v2_loan_automation_integration.py client/tests/test_v2_statement_summary_integration.py client/tests/test_v2_prepared_import_integration.py client/tests/test_v2_pdf_decode_operation.py
```

32 passed in 71.76 seconds, raw exit 0. Covers preserved loan opt-in behavior,
manual summary value recording and prepared evidence/zero post-confirm decode.

Core specialist: 21 unique new cases passed across the initial 18-case suite and
targeted active/withdrawn late-history (2) and material-diagnostic (1) checks. An early
test incorrectly treated `summary_extra_column` as a material warning; the fixture was
corrected to exercise the shared projector's actual material-warning class. The shared
warning policy was not changed. Selected existing source-value regressions: 6 passed,
55 deselected in 90.80 seconds, raw exit 0, covering conflict, correction, agreeing
origins, withdrawal/zero/historical retry, stale/failed writes and missing accounts.

Independent integrity: 15 actual public-PDF workspace cases, 13 direct policy cases
and 1 actual batch cancellation case passed with raw exits 0. Tests cover strict/
default-off consent, future-only toggling, new confirmed accounts, manual agreement,
conflicts and later dates, all six authorization checkpoints, late cancellation/
revocation/failure, physical clone/switch refusal, insertion rollback, pre-retry
history refusal, parse-free confirmation and no journal/allocation/transfer/loan/
budget effect. Original evidence remains exact. Evidence beneath
`scratch/statement-auto-integrity-20261117/`: `review.py`, `run-d8c107ee/summary.json`,
`policy-7d546259/summary.json` and `run-3e3052c3/batch-summary.json`.

Desktop: final combined native Windows run passed 25 cases in 73.64 seconds, raw
exit 0, using the new 7 UI cases plus existing retirement and loan-automation cases.
The final defensive Reload preference-read failure check passed separately in 26.90
seconds, raw exit 0. Tests exercise settings synchronization, keyboard toggle,
persistence, save/read failure recovery, retained custom/blank draft fields, automatic
truthful completion/history, composed batch outcomes and expanded/collapsed layouts
at 1050x700, 1100x650 and 1280x800. Explicit disposal verifies GUI-thread destruction
and native invalidation, normal GC enabled and no Qt exceptions in successful runs.

Actual screenshots under `scratch/statement-auto-ui-20261117/final/` were inspected
by primary and independent UI/UX. Key expanded/collapsed/missing-field captures are
in `test_future_import_details_are_readable_and_leave_current_manual_action_size1_/6438e65b/`;
automatic completion is in `test_automatic_value_has_truthful_complete_status_and_history/222543a8/`;
batch fallback is in `test_batch_results_distinguish_value_loan_and_manual_fallback/958aabfd/`.
Future-only scope and current manual action are clear, all summary rows stay readable,
completed actions remain neutral and required red/green cues survive informational
preference notices. No significant scoped design findings remain. This is qualified
screenshot/code and Qt software-event evidence, not independent live/uncoached or
owner acceptance. Other platforms/scaling/hardware/accessibility and installed/release
validation remain separate. All changed Python files passed Ruff check/format,
whitespace checks and normal commit hooks. Counts overlap; do not sum reruns.

## Fresh disposable owner test

Prepared `scratch/v2-owner-fresh-20261117-f788d095/Open-workflow-test.cmd` from code
revision `e14c5c52e5075495485941869a9477c7e0a02cdd`: 317 pinned runtime files, unchanged
schema 27 and 23 public development declarations. No sources, financial accounts,
budgets, journals or loan/transfer/value events were preloaded; only the protected
Loan interest category is initialized. The fixture signing key was discarded and
catalog/preferences/app-home are isolated to this new folder. Both automation
preferences start off. START-HERE explains enabling before import, explicit account
creation, automatic history and withdrawal/retry behavior. Previous populated owner
workspaces remain untouched.

```text
client/.venv/Scripts/python.exe -B -X utf8 scratch/v2-owner-fresh-20261117-f788d095/prepare_fresh.py
client/.venv/Scripts/python.exe -B -X utf8 scratch/v2-owner-fresh-20261117-f788d095/runtime/devtools/owner_fresh/fresh_launch.py --open scratch/v2-owner-fresh-20261117-f788d095 --smoke
```

Both raw exits 0. Windows-plugin startup confirms empty Documents, enabled Import,
six navigation items, unchanged profile bytes and Qt exit 0. Startup smoke hides its
window, separately from visible native UI tests. App left closed. After owner import
this folder becomes private; preparation does not authorize later data inspection.

## Remaining work

No scoped implementation or agent-review findings remain. Exact-candidate owner use,
other-platform/native/scaling/accessibility/installed checks and release authorization
remain separate. No production publication or daily-profile activation is authorized.

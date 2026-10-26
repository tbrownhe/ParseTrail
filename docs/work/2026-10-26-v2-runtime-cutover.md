# Make fresh V2 workspace startup the ordinary runtime

Date: 2026-10-26. Roadmap IDs: V2-1/6/7, P2-3/4/5.
Authorization: continuing approved initial V2/P2 development.
Implementation: default V2 entry and isolated diagnostics complete and frozen.
Automated verification: focused/native source, whole-client, parser and demo checks passed.
Independent review: complete; report publication finding fixed and independently rechecked.
Owner acceptance: pending final integrated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Ordinary source/frozen startup opens the V2 New/Open/Restore chooser without
initializing legacy settings, finance, authentication or the legacy main window.
Keep explicit `--v2` accepted as a redundant current-runtime selector, with explicit
profile/catalog/preferences/create automation. Reject unsupported arguments before
GUI/profile writes. No 1.x aliases, migration or old-profile activation. Preserve
the separately retained published 1.4.2 application/data as an independent fallback.

Keep parser-worker, fixture-verification, runtime-native and offline diagnostic
dispatch ahead of the GUI path. Existing `--offline-session-smoke-test` modes
`fresh`, `cached`, `network-failure` must exercise V2, replacing assumptions about
legacy onboarding/auth/update calls. V2's local catalog has no remote update
channel; denied-network checks must prove zero attempts and local functionality,
not invent expected network failures. Isolate all diagnostics to disposable
synthetic profiles/application home and report actual runtime/platform/results.
Any ephemeral fixture trust is programmatic and local to the explicit diagnostic;
never add a production trust override or persist private signing material.

Close a frozen PyInstaller splash before the chooser's modal event loop so it
cannot cover startup. Set the application icon through safe resource lookup;
do not import the legacy auth/bootstrap module to initialize appearance. Cancel
must create no profile/catalog/preferences or legacy files. Keep old, incompatible
and corrupt profile refusals before writes. Profile switching/restore semantics
remain those already implemented in V2.

Remove obsolete ordinary entry branches, not deferred legacy capabilities or
their research/tests/dependencies. Dependency slimming/ML changes are unselected.
Existing flagged native dependency diagnostics remain separately characterized
and must not become V2 financial acceptance claims. Update any exact offline
report consumers narrowly, preserving CLI mode names used by build scripts.
No version bump, production signing, publication, installer execution or daily
profile activation. Use only public synthetic/disposable inputs.

Writer: `positions_desktop` exclusively owns `main.py`, a new V2 offline diagnostic and
focused startup/offline tests, with narrow diagnostic-consumer fixes if needed.
Primary owns contracts, record, roadmap/TODO and final integrated/native/frozen
verification. Acceptance specialist audited exact callsites; independent review
will verify completed dispatch/isolation/diagnostics. Existing entry/test edits
began only after the accounting packet's commit; no concurrent writer.

## Result and review

Read-only audit found that simply routing default startup to V2 breaks the old
offline diagnostic, which recursively expects legacy onboarding/main-window
widgets. Both build scripts and macOS release checks use those flag modes. The
current V2 path also closes the splash only after chooser selection. Those are
part of this cutover outcome, not reasons to retain a user-facing legacy route.

The audit also identified the old shared installer/bundle identity. The concurrent
[installation packet](2026-10-26-v2-installation-identity.md) separates V2 and fixes
its audit/smoke consumers. No installer has been run on this workstation.

Ordinary entry now routes only to the V2 chooser/workspace, retaining optional
`--v2` and explicit path/create arguments. Strict parsing precedes GUI/config
imports; worker imports stay static for frozen analysis. Splash, safe icon and
plain signal handling avoid legacy logging/auth/bootstrap/settings. Native
dependency smoke is separately isolated, including staging context and network
denial, and retains its provenance gate for frozen release builds.

The self-contained V2 offline diagnostic embeds a finite public synthetic CSV
definition/source, creates ephemeral fixture signing/trust in its own temporary
state, and drives actual create/open/restore chooser actions. It observes paint,
heartbeat and timing while exercising signed catalog/import/retry, exact reviewed
expenses, reports, backup/restore/reopen and original recovery. Every mode denies
network access and requires zero attempts. It refuses an existing Qt application
before window discovery/patching, so programmatic misuse cannot touch an open
workspace. Reports identify V2/schema 2 and actual source/frozen/platform scope;
no legacy onboarding/model/update claims remain.

Independent review reproduced a report-publication race: another writer could
occupy the requested destination during work, causing the old final existence
check to skip publication yet return success. Publication now always attempts
exclusive creation; collision returns failure, preserves the other writer's bytes
and diagnostic log, and prints no success summary. No report/log overwrite is
permitted. No runtime-verifier/production-trust override was introduced.

## Verification

Windows 11 AMD64/Python 3.13.15; `PYTHONPATH=.;client/src;client`, Qt offscreen
except explicit Windows-native display-suppressed checks. Commands use
`client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider ... -q --tb=short`.

- Main/profile-startup/offline/new runtime checks: **50 passed in 41.75s**. Final
  pre-existing-Qt guard/timing additions: **6 passed in 12.36s**. Guards cover
  poisoned legacy environment/imports, default cancel/no writes, New/Open/Restore,
  CLI/early diagnostic dispatch, invalid profile bytes, splash-before-chooser,
  source/frozen icon and signal behavior. No build consumer edits were needed.
- macOS release/fixture-verification adjoining checks before the separate bundle
  identity fix: **62 passed, 1 skipped in 8.22s**. That identity packet records its
  later expanded portable/native-compiler tests independently.
- After the publication fix, runtime/offline checks: **17 passed in 24.71s**.
  Independent final affected report/log checks: **3 passed in 0.95s**; the original
  racing-writer probe now returns 1, preserves bytes/log and emits no false success.
  Earlier independent full startup/offline/packaging baseline was **74 passed,
  1 skipped in 29.37s**, before resolving the three separately reproduced issues.
- Actual default recursive CLI Windows Qt modes `fresh`, `cached`, `network-failure`
  passed with display suppressed, all four surfaces painted, 35/35/36 heartbeats,
  zero network attempts and exact expense 5743 minor units plus backup/recovery.
  Observed total seconds were 2.539/2.501/2.635; reports distinguish observed Qt
  timings from process-wide claims. Source native dependency smoke also exited 0.
- Standalone subprocess modes run from a temporary cwd with package-only Python
  paths and a poisoned legacy canary; no devtools/checkout fixture resources are
  needed and the canary remains unchanged. Forced network/modal failures refuse
  cleanly and unwind nested event loops. Existing Qt-app misuse leaves its window
  visible/logically untouched without invoking the entrypoint.
- Integrated frozen-code source commands: `client/tests` **2121 passed, 4 skipped
  in 977.04s**; `devtools/parser_engine_pilot` **262 passed in 84.59s**;
  `devtools/v2_review_demo` **4 passed in 41.35s**. Full-client environment also set
  process-only `PSExecutionPolicyPreference=RemoteSigned` for native PowerShell
  checks and selected the scratch NSIS compiler for actual fixture compilation.
  No global policy/tool installation changed. No additional implementation edits
  occurred during these runs; documentation closeout followed.
- Focused Ruff/format/whitespace checks passed. Final frozen candidate results
  remain separate and will be recorded at the integrated freeze.

These are synthetic source/offscreen/native-Qt checks. They do not establish owner
UX, actual installation, native Intel, production starter signing or release.

## Remaining work

Freeze the final integrated candidate, prepare the updated disposable owner walkthrough and unsigned
starter-catalog signing inputs, run available Windows checks, and identify only the
actual remaining owner/native/external/signing/release gates.

# Explicit fresh-profile startup and creation

Date: 2026-10-25. Roadmap IDs: V2-6/7.
Authorization: approved roadmap and continued development.
Implementation: complete, primary-owned parallel lifecycle packet.
Automated verification: 30 focused lifecycle/worker checks and 328 V2 tests passed; hooks passed.
Independent review: confirmed switch-failure finding resolved; no remaining actionable finding.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Allow explicit `--v2` launch to offer New/Open/Restore choices without mandatory
profile/cache CLI paths. Preserve existing explicit CLI automation and its safe
failure behavior. Default catalog/preferences locations remain separate local
application data; accept explicit paths for isolated testing. No automatic
last-profile activation, 1.x migration/default-runtime switch, version change or
release action. Startup cancellation writes nothing. New/restore publish only to
new selected paths; invalid choices leave the dialog/current workspace intact.
Add New 2.0 profile to the active workspace with the same safety boundaries and
disable profile changes during imports.

Primary exclusively owns `main.py`, `v2_profile_startup.py`, the workspace's
read-only local-configuration preflight, workspace-window
lifecycle additions and new focused startup tests. Transfer specialists own
different store/transfer GUI files; primary requests any additional services.
Only synthetic/disposable profiles and explicit temporary paths in verification.

## Result and review

Explicit `--v2` without a profile opens New/Open/Restore choices. Optional cache
and preferences arguments support isolated automation; the existing explicit
profile/create flags retain their behavior. Cancellation writes nothing. New
Profile is also available in the active workspace and disabled during imports.
Configuration preflight reads the separate preferences/catalog before creating or
restoring, so malformed configuration does not publish an unwanted new profile.

Independent review found that the initial shared switch assigned the new
workspace before refresh succeeded. A corrupt catalog pointer could therefore
change selection and raise. The fixed switch validates selected reads before
activation, catches refresh failures and restores the old workspace/view; an
unavailable old view clears unsafe source actions while retaining its path.
The exact bad-catalog/New repro now preserves the old profile, creates no new
target and shows a warning. An injected failure after a real target refresh also
restores the original selected source. No owner/native acceptance was performed.

## Verification

Test cancel/no writes, create/reopen/restore, invalid or legacy refusal, existing
destination preservation, failure without switching, CLI compatibility and parser
worker dispatch before GUI. Exercise actual menu/Qt dialogs offscreen, then
focused workspace/lifecycle checks, changed-file Ruff and repository hooks.

Windows/Python 3.13.15, offscreen/disposable home/profile/null keyring:

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_profile_startup.py client/tests/test_v2_workspace_window.py client/tests/test_v2_worker_entry.py client/tests/test_v2_profile_snapshot.py -q
```

Primary: 30 passed in 19.26s; independent reviewer: 30 passed in 23.22s. Includes
New/Open/Restore, cancellation, existing destination preservation, legacy
read-only refusal, CLI create/open compatibility, worker dispatch, import locks,
invalid preferences and both failed-switch regressions. Changed-file Ruff passed.
Primary inspected a synthetic 590x340 chooser render with a temporary Segoe UI
font load; all text/actions were readable. No runtime font override was added.

Final combined integration (including transfer correction) passed 328 tests,
1107 deselected in 180.92s using `pytest -p no:cacheprovider client/tests -k v2 -q`.
Changed-file Ruff check/format, repository hooks, local links and diff whitespace
passed. This packet is committed separately from transfer correction.

## Remaining work

Final integrated daily-workflow UX, native/platform and release gates.

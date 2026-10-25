# Recover embedded source originals

Date: 2026-10-25. Roadmap IDs: V2-3/6.
Branch/runtime: `feature/client-financial-insights`, fresh V2 workspace.
Authorization: approved roadmap and continued development until human gates.
Implementation: complete, independent of reconciliation-history store work.
Automated verification: 31 focused checks and 228 final V2 tests passed; hooks passed.
Independent review: no actionable findings; 31 independent focused checks passed.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Recover an exact selected original from the bytes already embedded in the
profile, including after the selected import file disappears and after verified
backup/restore. Do not introduce a second managed archive or move/delete inputs.
Headless workspace service validates saved evidence and publishes a new file
atomically without overwriting an existing destination. The desktop owns file
selection, cancellation and copyable path/privacy notice. No interpretation or
accounting changes and no schema changes.

Primary exclusively owns `v2_workspace.py`, `v2_workspace_window.py`, new
`v2_source_recovery.py` and `test_v2_source_recovery.py`, plus shared docs/record.
Reconciliation specialists own different store/report/coverage files. Synthetic
disposable profiles only, no original private files or 1.x access. Independent
review covers byte provenance, failed publication, preservation and UI scope.

## Result and review

`recover_source_original` verifies the retained source/evidence read-only, writes
a sibling temporary file, flushes and verifies its digest, then publishes with a
no-replace hard link. Existing or racing destinations survive; failed writes and
publication remove the partial. No catalog or reparse is involved. The workspace
delegates to that service. Profile > Save selected source original selects a
new destination, handles cancellation/failure and presents a copyable path plus
the local unencrypted-data disclosure. It is disabled for empty profiles and
during import; the service also refuses accidental overwrites.

Independent integrity review inspected actual code, publication/failure paths,
byte provenance and GUI state. No actionable findings. Only synthetic local
Windows filesystem/offscreen behavior is established; other filesystems/platforms
and owner UI acceptance remain distinct.

## Verification

Windows/Python 3.13.15 with disposable test home/profile and null keyring:

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_source_recovery.py client/tests/test_v2_workspace.py client/tests/test_v2_workspace_window.py client/tests/test_v2_profile_snapshot.py -q
```

Primary: 31 passed in 12.72 seconds; independent reviewer: 31 passed in 11.42
seconds. Includes missing original, exact CSV/PDF bytes, idempotent repeat import,
catalog-independent restore, existing/racing destination preservation, fsync and
publication cleanup, corrupt retained source refusal, unchanged profile and GUI
cancellation/error/empty states. Changed-file Ruff check/format passed after
normalizing test imports. Final combined V2 integration (including reconciliation
history) passed 228 tests, 1107 deselected in 116.36 seconds:

```powershell
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests -k v2 -q
```

Repository hooks and `git diff --check` passed for the changed files. Shared
documentation/link verification passed. This packet is committed separately from
the reconciliation-history packet despite their shared final integration run.

## Remaining work

Final integrated daily-workflow review and supported-platform/release gates.

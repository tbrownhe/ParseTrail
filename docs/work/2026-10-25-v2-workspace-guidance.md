# Workspace guidance and build identity

Date: 2026-10-25. Roadmap IDs: V2-6/7.
Authorization: owner-approved roadmap and continued development.
Implementation: complete, primary-owned disjoint GUI follow-up.
Automated verification: 9 workspace smoke tests and synthetic menu/layout check passed.
Independent review: not required for this small guidance change; primary code/visual review complete.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Add Help > Getting started and About this workspace with practical local daily
workflow instructions and truthful unchanged pilot build identity. No version,
financial semantics, storage, runtime cutover or service changes. Primary owns
`v2_workspace_help.py` and the corresponding menu actions in
`v2_workspace_window.py`; opening-correction specialists own different files.
Only disposable synthetic UI verification. No private paths/data in artifacts.

## Result and review

The Help menu opens Getting started and About this workspace. Guidance covers
separate 1.x/V2 profiles, local signed-catalog import, explicit binding/repeat and
posting review, qualified reports, backup/restore and embedded-original recovery.
About reports the unchanged build version 1.4.2 and explicitly identifies the V2
workspace as a development pilot, without claiming a released 2.0 application.
Selectable text remains local; no browser/service action or financial mutation.

## Verification

Windows/Python 3.13.15, offscreen Qt, disposable profile/catalog/preferences:

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe scratch/check_workspace_guidance.py
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_workspace_window.py -q
& .\client\.venv\Scripts\python.exe -m ruff check client/src/parsetrail/gui/v2_workspace_help.py client/src/parsetrail/gui/v2_workspace_window.py
& .\client\.venv\Scripts\python.exe -m ruff format --check client/src/parsetrail/gui/v2_workspace_help.py client/src/parsetrail/gui/v2_workspace_window.py
```

9 tests passed in 4.21 seconds; Ruff passed. The ignored scratch check exercised
both actual menu actions, rendered the dialogs, checked labels stayed inside
dialog bounds and verified the synthetic profile bytes were unchanged. Primary
visually inspected 680x570 Getting started and 462x223 About renders using a
temporary Segoe UI font load; text and controls were readable without clipping.
No runtime font override was added. This static guidance does not need committed
tests mirroring its strings. Repository hooks passed; owner native/Intel/installed
review remains separate.

## Remaining work

Other functional workflows and integrated UX/release milestones remain open.

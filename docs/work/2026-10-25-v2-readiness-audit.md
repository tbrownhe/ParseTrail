# Initial-release readiness audit

Date: 2026-10-25. Roadmap IDs: P2-3/4/5, V2-3/6/7.
Branch/runtime: `feature/client-financial-insights`, Windows source runtime.
Authorization: owner-approved roadmap and continued development instruction.
Implementation: complete read-only investigation; no runtime changes.
Automated verification: 256 synthetic checks passed.
Independent review: acceptance specialist investigation reported to primary.
Owner acceptance: not performed; consolidated V2-UX remains open.
Release authorization: not authorized.

## Scope and controlling decisions

Identify actual remaining development versus historical completed slices and
external gates. Only repository code, synthetic declarations/fixtures and
temporary test outputs were used. No private fixture replay, root `.env`, live
profile, production key or external service mutation. Primary owns this record.

## Result and review

All 23 current declarations cover the 22 required families (two MOHELA export
definitions). `devtools/parser_engine_pilot/test_catalog_admission.py` admits
them together in a test-signed snapshot. Fixed workers are client-package code
and dispatch before runtime bootstrap in `client/src/parsetrail/main.py`.
Both native build scripts already call `scripts.frozen_worker_smoke`.
Historical pilot README comments about missing frozen table/XLSX workers do not
describe current code. Do not repeat these package moves or infer source parity
from catalog admission. Existing archived execution/Windows frozen probes are
historical evidence, not acceptance of the current candidate.

Remaining family work is a bounded source-fact readiness/disposition record
against existing evidence, retaining summary/non-activity distinctions, unknown
HealthEquity descriptions, omitted synthetic origination/openings and unavailable
loan openings. Capture remains a separate, often unverified dimension.

`V2Workspace.import_file/import_files` leaves selected originals untouched;
`V2ProfileStore.import_source` embeds exact source, declaration and evidence in
SQLite atomically, and `snapshot_to` retains them. There is no managed V2
SUCCESS/FAIL archive move to recover. The appropriate next recovery packet is
embedded-source recovery/export and lifecycle failure checks, rather than copying
legacy file-move semantics.

Remaining autonomous accounting work includes durable reconciliation history,
opening/transfer/binding and duplicate-posting correction safeguards, refunds and
negative income adjustments, fees/partial settlements, supported loan/HSA/value
interpretations, closures, cash-flow classification and drill-down. Consolidated
human UX review does not block these workflows. DEC-1 was subsequently resolved
in the [positions packet](2026-10-25-v2-account-positions.md); DEC-2/3 remain open.

## Verification

Python 3.13.15, Windows 11 AMD64. Acceptance specialist inspected isolation first;
client conftest provides a disposable home/profile and null keyring.

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider devtools/parser_engine_pilot client/tests/test_v2_catalog_import.py client/tests/test_v2_data_catalog.py client/tests/test_v2_catalog_release.py client/tests/test_v2_worker_entry.py -q
```

256 passed in 18.30 seconds, exit 0. Includes Windows Job Object memory refusal,
timeout/cancellation and bounded synthetic decodes. This is neither Intel nor
installed/offline release acceptance, and does not establish private-source parity.

## Remaining work

Continue bounded development packets. External gates remain DEC-2/3, V2-UX,
targeted Intel native/packaged pipes, exact-candidate packaging and installed
offline/OS behavior, R2's physically absent build-toolchain environment when
available, and specifically authorized production signing/release/publication.

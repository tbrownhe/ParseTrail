# Verify V2 family admission and recovery in a frozen Windows probe

Date: 2026-10-25. Roadmap IDs: P2-3/4/5, V2-6/7.
Authorization: approved roadmap and continued development; test-only probe.
Implementation: diagnostic complete; October 26 integrated freeze/probe execution selected.
Automated verification: source checks passed; frozen probe not yet performed.
Independent review: diagnostic implementation complete, no actionable findings.
Owner acceptance: not performed; UX/native/installed gates remain separate.
Release authorization: not authorized.

## Scope and controlling decisions

Prepare a finite explicitly invoked diagnostic in the actual production entry
point that admits supplied synthetic CSV/PDF fixture bytes through an ephemeral
test-signed catalog into disposable profiles. Verify expected evidence digests,
retry/reopen, zero automatic journals, cancellation/refusal, catalog rollback and
backup/restore/embedded-original recovery without a catalog. Keep fixture sources
and signing material outside the application package and ordinary workspace trust.
Generate a bounded inline manifest with a source-runtime baseline; no arbitrary
code, source filesystem paths, private inputs or current-profile options.

All diagnostic profiles/catalogs/preferences/output intermediates are temporary.
The structured report explicitly identifies test trust and source/frozen probe
status; it does not manufacture release provenance or native owner acceptance.
The diagnostic runs before GUI configuration and never activates a daily
profile. This diagnostic does not change ordinary trust/version; the separate
[runtime cutover](2026-10-26-v2-runtime-cutover.md) now makes V2 the default.
New report destinations cannot overwrite existing files.

Evidence owns the new finite diagnostic module, narrowly assigned main dispatch,
new fixture-manifest generator and focused synthetic tests. Ledger retains sole
store ownership in the disjoint binding packet; no schema or store changes here.
Primary owns docs and integration. Verification specialists are read-only.

After a clean integrated commit, build a disposable onedir/windowed AMD64 probe
with existing PyInstaller production dependency/data options and scratch paths.
Run architecture, all worker pipes and this fixed diagnostic using synthetic
inputs. This is a test build without installer execution, release metadata, version
change, production signing, upload or publication. Record source commit, command,
binary identity, actual environment and limitations.

## Result and review

The October 25 read-only preparation found Python 3.13.15 AMD64, PyInstaller 6.21.0, PySide6
6.11.2, pytest 9.1.1 and Windows PowerShell 5.1 available. NSIS and PowerShell 7
are unavailable. The normal release script requires tagged release metadata and
NSIS; it is outside this probe. Native dependency smoke requires actual release
provenance when frozen; the development probe must not fabricate it. Offline
diagnostics were still 1.x then and have since been replaced by isolated V2 checks.

October 26 continuation: all planned bounded accounting flows are integrated at
schema 22; default V2/runtime diagnostics and unsigned catalog preparation passed
the whole-client/parser/demo checks in their records. A portable NSIS compiler is
now available under ignored scratch and V2 has a distinct installation identity.
The final probe may also compile a clearly labeled unsigned development setup via
explicit NSIS source/output overrides. No installer is executed, no source version
is changed and no tagged/release metadata or production signature is invented.
The separate installation record verifies compiler/identity handling. After the
clean code commit, record its exact identity and all generated artifact hashes.

Five assigned files implement the fixed diagnostic: new
`core/v2_fixture_verification.py`, a five-line pre-legacy dispatch in `main.py`,
`scripts/v2_fixture_manifest.py` and focused client/pilot tests. Generate a new
inline manifest and run the actual entry point:

```powershell
$env:PYTHONPATH='.;client/src;client'
& .\client\.venv\Scripts\python.exe -m scripts.v2_fixture_manifest --output <new-manifest.json>
& .\client\.venv\Scripts\python.exe -m parsetrail.main --v2-verify-fixtures <manifest.json> --report <new-report.json>
```

The manifest contains all 23 fixture definitions and source-runtime evidence
hashes, with explicit placeholder provenance and an in-memory signing key. All
keys/catalogs are confined to temporary diagnostic trust. The runtime has no
fixture file paths, executable operations or user-profile options. It validates
strict JSON/base64, duplicate identities, complete definition coverage, signatures
and finite size limits before creating a profile. A separate internal ephemeral
key tests sequence downgrade refusal and explicit rollback.

Actual imports retain exact source/definition/evidence bytes, retry without
reparsing, and create zero journals. Refused and pre-import-cancelled sources
leave no source rows. Catalog files are physically removed before verified
backup/restore-as-new and exact embedded-original recovery. Original/restored
profile bytes stay unchanged. Environment and temporary output are cleaned before
atomic no-overwrite report publication. Reports disclose baseline equality only,
test trust, process/platform identity, soft deadline scope, unbound evidence-only
profiles and unperformed capture/accounting/installed/owner acceptance.

## Verification

Check bounded manifest validation, no default settings/profile access, source and
frozen invocation, all-family source admission, exact immutable bytes, refusal/
cancellation, backup/reopen/recovery, report no-overwrite and failures. Run focused
source tests, relevant parser integration, Ruff/hooks and independent review
before the frozen probe. Preserve worker limits and tested-platform distinctions.

Windows 11 AMD64, Python 3.13.15, Qt offscreen, synthetic/disposable data:
the broad parser/diagnostic/catalog/worker/snapshot/recovery run passed 319 checks
in 94.11 seconds. After duplicate-parser hardening, the final client/pilot
diagnostic command passed 22 checks in 40.20 seconds. Changed-file Ruff check and
format passed. Independent review ran diagnostic plus pure/existing overlap
checks: 49 passed in 40.62 seconds, with no actionable findings. It inspected
finite validation, dispatch isolation, real workers, temporary trust/environment,
cleanup, refusal/cancellation/rollback, recovery without catalog and report
write/fsync/race refusal. No build or installed execution has occurred yet.

The read-only acceptance specialist also ran 117 relevant non-V2 regressions in
22.92 seconds: main, runtime build provenance, release bootstrap/architecture,
profile, offline startup, ledger kernel and source evidence. Bootstrap harnesses
stopped before dependency sync, building or signing. Windows PowerShell execution
policy was set to RemoteSigned only in that test process; no persistent policy
changed. These checks establish entry/isolation and kernel regressions, not the
actual frozen probe or installed/native acceptance.

## Remaining work

Intel native limits/pipes, installer and installed/offline/OS integration,
no-build-toolchain Intel environment, owner V2-UX and separately authorized
production starter signing/version/publication remain their own gates.

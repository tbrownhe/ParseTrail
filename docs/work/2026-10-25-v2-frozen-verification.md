# Verify V2 family admission and recovery in a frozen Windows probe

Date: 2026-10-25. Roadmap IDs: P2-3/4/5, V2-6/7.
Authorization: approved roadmap and continued development; test-only probe.
Implementation: complete; October 26 frozen Windows probe and development setup compile passed.
Automated verification: source integration and all available frozen Windows checks passed.
Independent review: diagnostic review and separate acceptance-agent execution complete; primary verified hashes/results.
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
V2 Windows builds use Qt startup directly; the optional Tk splash is omitted as
documented in the October 26 tooling finding below.
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

### October 26 exact build finding and correction

After the integrated source checks passed, the exact windowed production-flag
probe at clean `25294e29816c8adf745e3fb2861a8f301c34fd64` failed after 106.27s at
PyInstaller's `--splash` requirement. Analysis/PYZ completed but no executable was
produced. `_tkinter`, Tcl/Tk DLLs and script files exist, yet Tcl initialization
cannot use `init.tcl`, including in the original environment and with explicit/
copied public library paths. Build-home isolation was not the cause. No venv or
third-party source was modified. Exact log/report remain under ignored
`scratch/v2-frozen-25294e2`.

The V2 application uses Qt and has no functional Tcl/Tk dependency. The primary
removed the optional Windows `--splash` flag from the production builder rather
than changing a managed interpreter or bypassing a required application check.
Icon/Qt startup and the defensive close of any existing splash remain intact.
No dependency cleanup, application version change or release action is included.
The next clean freeze/probe uses that same corrected production option set;
record the actual resulting revision and results before claiming a frozen pass.
Focused release-bootstrap and native installation-identity checks after this
one-option change: **35 passed in 2.85s**. Application/ledger/parser code is
unchanged from the fully tested integration; native build verification follows.

### Successful exact Windows probe — October 26

Code freeze: clean `1e61bec33af214930d42396c6ff5f3b9a146e6d4`, application version
unchanged at development `1.4.2`, profile schema 22. Windows 11 AMD64 build 26300,
Python 3.13.15, PyInstaller 6.21.0, PySide6 6.11.2. The acceptance specialist built
the actual production entry as onedir/windowed with the corrected production
option set, all three hidden imports and required assets/notices/licenses/
migrations/alembic data. Every cache/work/spec/home/temp/output path stayed under
ignored `scratch/v2-frozen-1e61bec`; no release metadata was fabricated.

| Stage | Result / elapsed seconds |
| --- | --- |
| Actual frozen build | Passed, 75.10 |
| Isolated PE32+ AMD64 architecture check | Passed, 0.07 |
| All six bounded worker pipes in the windowed executable | Passed, 3.44 |
| External public source-runtime fixture baseline | Passed, 10.91 |
| Frozen all-declaration admission/recovery | Passed, 17.60 |
| Frozen V2 offline fresh/cached/network-failure | Passed, 2.70 / 2.51 / 2.61 |
| Full unsigned development setup compilation | Passed, 38.14; never executed |

All 23 declarations (21 PDF, 2 CSV, across the required families) admitted their
45 synthetic observations with source-baseline equality and exact retries. All
11 trust/reopen/cancellation/refusal/rollback/backup/restore/recovery/zero-automatic-
journal checks passed. These profiles are unbound evidence-only fixtures; this
does not establish private-source parity, complete capture or accounting acceptance.
All three offline modes used actual Windows Qt with display suppressed, painted
chooser/workspace/cash-review/reports, denied all networking with zero attempts,
and retained exact expense 5743 minor units plus backup/recovery. Observed timing
and heartbeat fields are not cold-start benchmarks. Total orchestration: 154.24s.

The 2,481 bundle files were hashed/rechecked. Primary independently read the
structured reports and recomputed these SHA-256 values:

| Artifact under `scratch/v2-frozen-1e61bec` | SHA-256 |
| --- | --- |
| `dist/ParseTrail/ParseTrail.exe` (28,043,635 bytes) | `084b6133d9f540fec14b9ca764a4e7d020cd745f0276cb1b5c07c19b5097a897` |
| `ParseTrail2-development-probe-setup.exe` (150,672,537 bytes) | `3cc543399c7cc9d150506c1475f0adaf27ad8c80194b1c90dc05cc6d07aa0e4e` |
| `bundle-manifest.json` | `a8ca230340920a9055296357ad90d6e8ae080dc2fe9055eb466e26de9cabfa41` |
| `probe-report.json` | `4d7d659981b1bd938d616f952a9d87f5f230f92d35ac48e2050dffa5f2490c45` |

Commands, public inputs, per-stage logs/reports, source-tree identity and limits
are retained beside those files. Git remained clean at the same source commit
through post-checks. Later documentation closeout does not change this tested
binary's source identity. The frozen native dependency smoke was intentionally
not run without genuine tagged release provenance; its gate was not bypassed.
Source native dependency operations passed separately. No installer was executed;
no daily/1.x profile, registry, production key, deployment or publication was touched.

## Remaining work

Owner V2-UX, Intel native limits/pipes, installed/offline/OS integration,
no-build-toolchain Intel environment and separately authorized
production starter signing/version/publication remain their own gates.

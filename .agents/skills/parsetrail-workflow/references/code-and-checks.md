# ParseTrail code and verification map

Paths are relative to the repository root. Read only the areas relevant to the
packet and confirm that symbols and commands still exist before use.

## Runtime and contracts

- `client/src/parsetrail/main.py`: fixed parser worker dispatch, explicit
  `--v2` workspace path, then legacy runtime bootstrap.
- `docs/client-v2-cutover.md`: current fresh-profile launch boundary and dated
  pilot/native acceptance. `docs/client-v2-unified-store.md`: single store.
- `docs/client-ledger-contract.md`: signs, review, dates, corrections and claims.
- `docs/client-v2-menu-inventory.md`: implemented actions and undecided deferrals.
- `docs/client-v2-parsing.md` and `docs/client-v2-parser-inventory.md`: finite
  engine design, family/source evidence and remaining admission gates.
- `development.md`, component READMEs and `docs/engineering-acceptance.md`:
  test isolation, platform policy and accepted release evidence.

## Evidence and catalog

Under `client/src/parsetrail/core/`: `source_evidence.py`,
`v2_source_pipeline.py`, `v2_source_import.py`, `v2_catalog_admission.py`,
`v2_pdf_routing.py`, `v2_data_catalog.py`, `v2_worker_limits.py` and fixed
`v2_*_worker.py` modules. Finite operation modules are in this package;
declaration fixtures and additional synthetic tests remain in
`devtools/parser_engine_pilot/`. Catalog builder: `client/scripts/v2_catalog_release.py`.

Check byte/revision binding, unique routing, malformed/ambiguous input,
duplicate occurrences, raw and derived values, unknown endpoints, summary versus
activity rows, cancellation and native resource refusal. Source-fact parity,
execution coverage, complete page capture and accounting acceptance are different
results. Do not rerun private archive tooling unless its selected inputs are
authorized for that packet.

## Ledger, profile and reports

`core/ledger.py` contains pure exact posting rules.
`core/v2_profile_store.py` owns fresh format checks, authoritative accounts,
immutable imports, account binding, postings/corrections, openings, source
assertions, reconciliation snapshots and report queries. `core/v2_workspace.py`
coordinates selected files, catalog and profile operations.
`core/v2_preferences.py` holds separate global V2 preferences, both matching and
assumed-posting-date opt-ins defaulting off.

Check stale or absent openings, zero openings, current review bases, repeated
imports/decisions, failed transactions, original/reversal/replacement arithmetic,
different-date transfers, incomplete allocation, source overlap and independent
restore. `snapshot_to` backs up source evidence and authored/reviewed data;
catalog cache and global preferences are outside the profile backup.

## Desktop

Under `client/src/parsetrail/gui/`: `v2_workspace_window.py`,
`v2_batch_import.py`, `v2_evidence_preview.py`, account-binding and ordinary/card/
transfer/opening review dialogs, `v2_statement_coverage.py`,
and `v2_reviewed_reports.py`. Workbook serialization is in
`client/src/parsetrail/core/v2_report_export.py`.

Check empty, pending, refused, corrected, stale and cancelled states; restart
persistence; exact numeric ordering; long labels/path copyability and scope
wording. Agents verify the first functional UI and continue development without
per-feature human acceptance. Accumulate useful scenarios for the later integrated
UI/UX pass; prepare its disposable end-to-end launch at that milestone. Preserve
specifically identified native/platform and release gates.

## Windows source verification

Run from the repository root with the existing locked client environment:

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests -k v2 -q
```

For parser changes, select affected tests from the pilot suite. Its synthetic
integration command is:

```powershell
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider devtools/parser_engine_pilot -q
```

`client/tests/conftest.py` isolates home/profile and keyring. Tests elsewhere do
not automatically inherit that conftest: check their fixtures and writes before
running new selections. Do not assume `-k v2` covers every evidence/ledger test;
include `test_source_evidence.py`, `test_ledger_kernel.py` and other affected
non-V2-named modules when their contracts change. From `client/`, the documented
full client suite is `uv run --no-env-file --frozen pytest -q`.

Run Ruff check and format check on changed Python files using the locked client
tooling. Pre-commit uses Ruff and Biome; some hooks fix files, so inspect its diff.
Hosted lint currently lists `backend/app`, `client/src`, `client/tests` and
`scripts/deployment`; explicitly check modified devtools or client scripts too.

For the integrated UI/UX milestone or an explicitly requested earlier review,
use this owner-launched synthetic walkthrough in a fresh PowerShell session without
`QT_QPA_PLATFORM=offscreen`:

```powershell
$env:PYTHONPATH='.;client/src;client'
& .\client\.venv\Scripts\python.exe -m devtools.parser_engine_pilot.open_v2_workspace --demo --comparison
```

The demo owns a temporary profile and test-signed catalog. Extend or choose a
different existing disposable launcher to cover the milestone's integrated flows.
This command is a review aid, not a required human checkpoint after every feature.
Do not treat a sandbox-launched window as the owner's Windows walkthrough.

## Service/web and release checks

- `backend/app/tests/safety.py` configures dedicated test settings before app
  imports. Follow `backend/README.md` with `docker-compose.test.yml`, local
  PostgreSQL and the test database namespace; never use root `.env` production
  settings. Alembic owns schema changes.
- `frontend/src/client` is the compatibility facade. Generate
  `frontend/src/client/generated` with `npm run generate-client`; do not hand-edit.
  Use `npm run lint`, `npm run test:website` and `npm run build` from `frontend/`.
  Playwright uses the disposable `docker-compose.ci.yml` stack.
- Read `docs/privacy-and-data-flow.md` for contributions and local-data bounds.
  Server contribution plaintext never enters temp files or reports; ordinary
  desktop source retention has a separate local storage policy.
- Packaging, offline/frozen workers and publication follow `client/README.md`,
  `docs/client-releases.md`, `docs/client-release-contract.md`, and
  `.github/workflows/client-release.yml`. Windows checks do not establish Intel
  Mac native limits or installed behavior. Build-only output is not a signed
  accepted release. Read the release runbooks when assigned; do not execute
  their external mutations merely because they appear here.

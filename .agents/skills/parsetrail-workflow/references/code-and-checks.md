# ParseTrail code and verification map

Paths are relative to the repository root. Read only the areas relevant to the
packet and confirm that symbols and commands still exist before use.

## Runtime and contracts

- `AGENTS.md` and the workflow skill: project-wide scope, routing and review.
  `ROADMAP.md` and `TODO.md`: affected planned scope, dependencies and release
  gates, not prerequisites for every explicit request. `docs/work/README.md`:
  substantial work plans, decisions and verification.

- `client/src/parsetrail/main.py`: isolated worker/diagnostic dispatch, then
  ordinary fresh-profile startup; `--v2` is optional. The published 1.x fallback
  is independent, not an ordinary legacy bootstrap in this entry point.
- `docs/client-v2-cutover.md`: current fresh-profile launch boundary. `docs/client-v2-unified-store.md`: single store.
- `docs/client-ledger-contract.md`: signs, review, dates, corrections and claims.
- `docs/client-v2-menu-inventory.md`: implemented actions and undecided deferrals.
- `docs/client-v2-parsing.md` and `docs/client-v2-parser-inventory.md`: finite
  engine design, family/source evidence and remaining admission gates.
- `development.md` and component READMEs: setup, test isolation and platform
  policy. `docs/work/`: current packet evidence. `docs/engineering-acceptance.md`
  and `docs/agent-workflow-*.md`: historical indexes, not new work queues.

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
Positions/history use `account_positions`; reconciliation separates live
`statement_reconciliation_checks` from persisted `save_reconciliation_decision`,
`reconciliation_history` and `reconciliation_snapshot`. Read current contracts
and implementations rather than treating completed slices as future dependencies.

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
wording. Substantial interaction work includes an agreed journey/design and
inspection of the actual Qt result with working fonts, relevant window sizes,
long lists and keyboard focus. Apply the workflow's design criteria without
per-feature owner approval. Prepare disposable human walkthroughs when assigned;
preserve concrete native/platform and release gates.

## Backend, dashboard and public website

- Backend entry: `backend/app/main.py`, `backend/app/api`, `backend/app/core`
  and `backend/app/models.py`; schema revisions under `backend/app/alembic`.
  Read `backend/README.md`, `docs/web-authentication.md`,
  `docs/privacy-and-data-flow.md` and the affected API/artifact contract.
- Dashboard: `frontend/src/routes`, `frontend/src/components`, `frontend/src/hooks`
  and `frontend/src/theme.tsx`. Read `frontend/README.md`; handwritten API
  compatibility code lives above `frontend/src/client/generated`.
- Public site: `website/*.html`, `website/assets`, `website/tests` and
  `website/nginx.conf`. The dashboard is an account/admin surface; the public
  site explains the product and distributes artifacts. Neither synchronizes
  ordinary desktop finance data. Match public claims to supported behavior.
- Backend and web agree API changes and designate one generated-output writer.
  Use `scripts/generate-client.sh` or `npm run generate-client` from `frontend`;
  never hand-edit generated transport/schema files. Inspect affected consumers.
- For substantial web interactions use ui_ux plus web, inspect actual browser
  rendering, responsive states, keyboard/focus and failure behavior. Test static
  metadata/configuration rendering without introducing untrusted HTML. Use the
  component's relevant tests rather than making every site edit start a backend.

## Tooling, documentation and instruction work

Choose checks for the changed artifact: TOML parsing and role discovery/schema
for agent files; skill validation and realistic task scenarios for workflow
changes; local links/anchors and current-code checks for documentation. Do not
run unrelated application suites for prose/config-only work. Keep dated task
results in the work record, not in this map.

Deployment/configuration tooling follows `deployment.md` and affected scripts
under `scripts/deployment`; client packaging follows its release contracts.
Inspection or local disposable rehearsal does not itself authorize production
mutation, signing or publication. Component-specific branch/handoff contracts
apply to their scope; do not hardcode the current branch into reusable roles.

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

For assigned integrated human review, `devtools/v2_review_demo/README.md`
describes preparation of a disposable synthetic profile, fixture-signed catalog
and pinned runtime with a Windows launcher. Choose/extend a disposable aid for
the affected journey; do not use a historical demo as the current runtime by
default. Human review runs without `QT_QPA_PLATFORM=offscreen`. Sandbox or
suppressed-display checks do not establish the owner's visible walkthrough.

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

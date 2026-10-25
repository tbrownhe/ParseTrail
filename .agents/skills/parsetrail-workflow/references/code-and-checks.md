# ParseTrail code and verification map

Paths are relative to the repository root. Read only the areas relevant to the
packet and confirm that symbols and commands still exist before use.

## Runtime and contracts

- `ROADMAP.md`: sole ordered milestones, scope decisions and release gates.
  `TODO.md`: selected packet and a short candidate queue. `docs/work/README.md`:
  standard packet plans, decisions and verification; read the linked record.

- `client/src/parsetrail/main.py`: fixed parser worker dispatch, explicit
  `--v2` workspace path, then legacy runtime bootstrap.
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

## Candidate starting points

These are technical entry points, not another queue or authorization. Use TODO
to establish selected scope and create its packet record before substantial work.
Code remains authoritative; recheck schema/runtime and existing checks at pickup.
Here `core/` and `gui/` are under `client/src/parsetrail/`.

### Account positions and history

- Read the ledger report contract, single-store contract and occurrence-review
  contract, plus `docs/work/2026-10-25-v2-source-overlap.md` for the completed
  safeguard and its limits. Current `financial_journal_summary` is period
  movement with openings separate, not an as-of balance.
- Start in `core/v2_profile_store.py`: `financial_journal_summary`,
  `opening_decision`, `statement_reconciliation_checks`, correction reads and
  conservative unallocated-source counts; UI in `gui/v2_reviewed_reports.py`.
- Define the selected report contract before UI: explicit as-of/currency,
  recorded journal versus source-supported position, natural asset/liability
  direction, absent/stale openings as unknown, correction arithmetic, overlap,
  pending/unreviewed scope and freshness. Include exact synthetic sign/date cases.
- Current reconciliation is computed live with a rule/input version. A previously
  saved cutoff requires V2-4 durable reconciliation history. A positions view can
  proceed with truthful live-check wording; it cannot claim that history exists.
- Focused starting tests under `client/tests/`: `test_v2_category_reports.py`,
  `test_v2_reviewed_openings.py`, `test_v2_source_openings.py`,
  `test_v2_statement_reconciliation.py`, `test_v2_reviewed_reports_dialog.py` and
  `test_v2_source_overlap.py`. Add meaningful as-of/unknown/correction cases.

### Remaining review safeguards

- Read the occurrence-review, ledger and single-store contracts and the completed
  overlap record first. The current matcher uses exact bound account, signed
  amount, source date and date role across sources; supporting repeats are not
  allocations. Saved review history currently locks account bindings.
- Select one outcome: wider matching, history-locked binding repair, existing
  double-posting correction, or transfer correction. These are distinct packets;
  do not turn them into a general import rewrite or erase prior review/journals.
- Start at store `source_overlap_inventory`, `record_source_overlap_review`,
  `source_overlap_posting_blocks`, account-binding mutation guards,
  `transfer_candidates` and `post_reviewed_transfer`; GUI adapters are the
  overlap, source/account-binding and transfer review dialogs.
- Starting tests: `test_v2_source_overlap.py`, `test_v2_source_overlap_dialog.py`,
  `test_v2_source_overlap_binding_dialog.py`, `test_v2_transfers.py`,
  `test_v2_reviewed_journal.py` and `test_v2_profile_snapshot.py`. Preserve
  one occurrence per source, stale-form refusal, atomic failure, unique active
  allocation and original/reversal/replacement history.

### Parser and catalog readiness

- Read the current parsing contract and family map. The pilot README is a test/
  tool entry point with historical chronology, not another current work queue.
- Start at `core/v2_source_pipeline.py`, `core/v2_catalog_admission.py`,
  `core/v2_data_catalog.py`, `core/v2_worker_limits.py` and `client/scripts/v2_catalog_release.py`.
  Choose a family/operation/platform or catalog outcome before running broad checks.
- Starting client tests: `test_v2_catalog_import.py`, `test_v2_data_catalog.py`,
  `test_v2_catalog_release.py` and `test_v2_worker_entry.py`; include the affected
  synthetic `devtools/parser_engine_pilot/` modules. Client `-k v2` alone does
  not exercise that directory; inspect isolation before running its tools.
- CSV/PDF workspace admission exists; XLSX remains isolated. Keep execution,
  source parity, capture, accounting, Windows/Intel limits and installed/offline
  trust distinct. Existing fixture authorization does not require broad private
  replay. Production signing/service publication needs its own scope; DEC-2
  settles the first-release service dependency and blocks only dependent work.

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

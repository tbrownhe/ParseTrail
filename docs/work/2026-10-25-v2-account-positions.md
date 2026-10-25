# Account positions and history

Date: 2026-10-25. Roadmap IDs: V2-5. Branch/runtime:
`feature/client-financial-insights`, explicit fresh-profile `--v2` runtime.
Authorization: owner approved ROADMAP.md, selected account positions/history as
the first candidate and authorized continued development until human gates remain.
Implementation: complete.
Automated verification: focused checks, 182 V2 integration tests and hooks passed.
Independent review: integrated financial/service/UI review complete; no actionable findings.
Owner acceptance: pending consolidated V2-UX milestone.
Release authorization: not authorized.

## Scope and controlling decisions

Owner decision, October 25 (DEC-1): manual entry is limited to reviewed openings
and dated values. The owner explained that it was needed for missing new-loan
opening information or missing final statements for recently closed loans.
Arbitrary balanced manual journals are outside scope. Preserve the existing
closure contract: stopping tracking does not establish a settlement or authorize
zeroing a journal balance.

Owner decisions, October 25 (DEC-2/3): local signed-catalog installation suffices
for the first release; the service can follow separately. The owner approved
omitting ML training, recurring detection, appreciation calculation, separate
account-configuration export, standalone backup testing, export presets/pivots,
dashboard charts and server sign-out/contribution for now. These remain important
future capabilities to add, preferably in a future context run. This approves
initial-release deferral, not permanent retirement or present service/release
actions. The [action inventory](../client-v2-menu-inventory.md) retains them.

Deliver explicit inclusive as-of USD account positions and dated journal history.
Distinguish recorded reviewed postings from a position established by a valid
source-backed opening; absent, stale or future openings leave position unknown.
Use natural asset value/liability owed signs for presentation, retain exact debit
signs in the service. Preserve original/reversal/replacement date arithmetic.
Expose pending evidence, unreviewed entries, source cutoff/freshness, coverage and
live reconciliation separately. No current bank-balance/net-worth certification.
A live successful check is not a saved reconciliation cutoff: durable cutoff
history is a subsequent V2-4 packet. No schema change is planned for this packet.

Contracts: client-ledger-contract.md, client-v2-cutover.md,
client-v2-unified-store.md and client-v2-source-overlap.md. Baseline is clean
`feature/client-financial-insights` after the completed overlap safeguard.
Primary owns roadmap/TODO/contracts/this record. Ledger specialist owns the
profile-store read models/queries and focused position tests. Desktop specialist
will own report GUI and interaction tests after service contract agreement.
Integrity specialist independently reviews integrated financial claims.
Only synthetic/disposable profiles and fixtures may be written; no private data,
1.x profile, production signing or service mutations.

Verification targets: missing/zero/stale/future openings; inclusive cutoff;
liability signs; different-date transfers and clearing; corrections/date changes;
unbound/unallocated/repeated evidence; live-check wording; reopen and read-only
snapshot behavior; empty/pending UI. Run focused checks, relevant V2 integration,
changed-file Ruff and applicable repository hooks on Windows.

## Result and review

Implemented `account_positions` and exact immutable result/history models in
`v2_profile_store.py`, without a schema change. One read snapshot includes source
bindings, opening validity, postings/corrections, coverage, live checks and pending
scope. Tests exercise concurrent WAL writing without mixing snapshots, failed-read
rollback and refusal to nest an existing transaction.

The reports dialog appends Account positions without changing existing tab
indices. Its inclusive as-of is independent of report ranges and budget month;
account selection shows original/reversal/replacement history. Failures clear
stale rows. Natural liability signs, unknown versus zero openings, conservative
all-date pending counts, unbound rows, transfer clearing and source/capture
qualifications remain visible. Agents inspected an offscreen 1180x780 synthetic
render; columns, values and history were readable with scrolling/splitter support.
No owner native acceptance was performed.

Independent integrity review covered the actual integrated store/GUI diff,
inclusive dates, missing/stale/future/conflicting and zero openings, correction
chains/date restatement, clearing, source freshness and live-not-saved wording.
No actionable findings remained. Latest source period end may exceed the as-of
date and does not establish coverage; warnings disclose that distinction.

## Verification

Baseline Windows source checks (Python 3.13.15):

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_reviewed_openings.py client/tests/test_v2_statement_reconciliation.py client/tests/test_v2_profile_snapshot.py -q
```

12 passed in 6.52 seconds before implementation.

```powershell
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_account_positions.py client/tests/test_v2_category_reports.py client/tests/test_v2_reviewed_openings.py client/tests/test_v2_statement_reconciliation.py client/tests/test_v2_transfers.py client/tests/test_v2_card_purchase_review.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_account_positions_dialog.py client/tests/test_v2_reviewed_reports_dialog.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests -k v2 -q
& .\client\.venv\Scripts\python.exe -m ruff check client/src/parsetrail/core/v2_profile_store.py client/src/parsetrail/gui/v2_reviewed_reports.py client/tests/test_v2_account_positions.py client/tests/test_v2_account_positions_dialog.py
& .\client\.venv\Scripts\python.exe -m ruff format --check client/src/parsetrail/core/v2_profile_store.py client/src/parsetrail/gui/v2_reviewed_reports.py client/tests/test_v2_account_positions.py client/tests/test_v2_account_positions_dialog.py
```

Service boundary run: 31 passed in 30.27 seconds (10 new service tests). Desktop:
9 passed (6 new interaction tests plus 3 existing report tests). Independent
integrity integration: 33 passed in 31.10 seconds across positions, report UI,
openings, reconciliation and transfers. Primary V2 run: 182 passed, 1107 deselected
in 89.51 seconds. Ruff check and format check passed for all four Python files.

Repository hooks passed for the 12 changed/new files using the installed hook
interpreter, `python -m pre_commit run --files <paths>`, with a process-scoped Git
safe-directory override. Initial sandbox attempts could not write/read the
owner's pre-commit cache; the approved elevated check used existing cached tools
and passed. No global Git configuration was changed. `git diff --check` passed.

## Remaining work

Durable reconciliation history follows separately. Consolidated owner UI/UX,
targeted Intel/native and release gates remain at their roadmap milestones.

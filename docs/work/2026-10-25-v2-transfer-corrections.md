# Review and correct whole transfer interpretations

Date: 2026-10-25. Roadmap IDs: V2-3/4/5.
Branch/runtime: `feature/client-financial-insights`, fresh V2 workspace.
Authorization: approved roadmap, continued development and cohesive tested commits.
Implementation: complete.
Automated verification: 328 V2 integration checks, focused regressions, Ruff and hooks passed.
Independent review: findings resolved; no remaining actionable findings.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Add durable dismiss/reopen decisions for candidate pairs (no postings), whole
confirmed-event withdrawal, and atomic replacement with another explicitly
confirmed supported pair. A different-date event is indivisible: retire every
original leg at its original accounting date. Release only active allocations;
preserve immutable originals, exact inverse history and clearing arithmetic.
Replacement and later reposting use fresh identities, never revive a cancelled
entry. Revalidate selected event/pair context and expected version in the write
transaction; idempotent retries and failures must not partially change books.

No additional expense or income from transfer/card payment correction. Preserve
assumed-date opt-in for new postings, without preventing withdrawal of existing
interpretations. Fees/partial settlements remain a later admitted workflow.
Retain reasons and inspectable decision/version history; unknown/pending source
facts remain visible. Dismissal is a suggestion decision, not evidence allocation.
Account binding changes must not silently reactivate a historical interpretation.

Ledger exclusively owns `v2_profile_store.py`, relevant export additions and new
transfer-correction tests. Desktop owns `v2_transfer_review.py` and new interaction
tests. Primary owns shared contracts/roadmap/TODO/record. Independent integrity
review covers integrated accounting, persistence and failure paths. No recursive
delegation. Synthetic/disposable data only; no private/1.x data, production keys,
service/release actions or arbitrary manual cancellation workflow.

## Result and review

Schema 14 adds immutable transfer events, whole-event actions and pair-review
history. Dismiss/reopen decisions are scoped to their recorded account context;
they allocate nothing. Whole-event withdrawal retires every original leg at its
original date. Atomic replacement and later reposting create fresh identities.
Originals, inverse links, source allocations and reasons remain inspectable.
All mutation forms revalidate their selected snapshot basis. Existing assumed
date decisions can be withdrawn with the preference off; new postings still
require the opt-in. Spending/income are unchanged by transfer correction.

Common reads, allocation counts, reconciliation/overlap versions, verified backup
and workbook Transfer Reviews links include this history. Saved reconciliation
tests prove withdrawal retains the exact old check as stale and removes its
current saved cutoff; pending source allocations remain visible.

Integrity review found two gaps, both fixed: reopening selected the newest row
pair review across different financial contexts, and malformed SQLite TEXT/BLOB
values could raise an uncaught decoder TypeError. Current-context selection now
handles A-to-B-to-A rebindings; strict persisted types fail as ProfileFormatError
before decoding/hashing, allowing the UI to clear unsafe actions. History checks
also validate exact source/entry/allocation/index/clearing shapes, checksums and
all-leg retirement. Cancelled-event history remains valid after later binding
repair and backup. This is corruption detection, not hostile database authentication.
Primary inspected a readable 1250x750 synthetic event/correction render.

## Verification

Test same-day/different-day cancellation/replacement, changed destination,
shared source row, cancelled-pair reposting, stale forms, dismissal/reopen,
transaction failpoints, exact allocations/date/clearing signs, source/correction
provenance, report/export/reconciliation invalidation, backup/reopen and malformed
history refusal. Run focused checks and final V2 integration, Ruff/hooks.

Windows/Python 3.13.15, isolated home/profile/null keyring and offscreen Qt:

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_transfer_corrections.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_transfer_corrections_dialog.py client/tests/test_v2_transfers.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_transfer_corrections.py client/tests/test_v2_transfer_corrections_dialog.py client/tests/test_v2_transfers.py client/tests/test_v2_journal_retirements.py client/tests/test_v2_report_export.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests -k v2 -q
```

Final service regressions: 34 passed in 24.04s. Post-context-fix UI: 12 passed in
13.65s. Independent final integration: 67 passed in 65.83s, plus exact malformed
GUI clearing and future-binding/backup repros. A broader run found two existing
source-overlap refusal-wording regressions (88 passed, 2 failed); restoring the
original guard ordering fixed both (2 passed, 19 deselected in 1.56s). Primary
final V2 integration, including source-overlap and disjoint startup work: 328
passed, 1107 deselected in 180.92s. Changed-file Ruff check/format, repository
hooks, diff whitespace and local links passed. No owner/native/Intel/installed
acceptance or release action was performed.

## Remaining work

Other V2-3/4 safeguards and admitted accounting/report breadth, then consolidated
human UX and supported-platform/release gates.

# Correct reviewed opening decisions without erasing history

Date: 2026-10-25. Roadmap IDs: V2-4/5.
Branch/runtime: `feature/client-financial-insights`, fresh V2 workspace.
Authorization: approved roadmap and continued development; cohesive tested commits.
Implementation: complete.
Automated verification: 267 V2 checks, final affected checks, Ruff and hooks passed.
Independent review: all three findings resolved; no remaining actionable findings.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Correct source-backed opening decisions after the current earliest source basis
is explicitly reviewed. Retain initial decisions and append revisions; never
rewrite immutable source facts, decisions or journals. Revalidate both selected
old-decision version and current source basis in one write transaction. Reverse
the prior active opening at its original cutoff and post a newly supported
opening at its own prior-day cutoff. Zero creates a decision with no fabricated
replacement journal. A basis-only update can retain the existing journal when
amount/date are unchanged. Source conflicts and active pre-opening activity block
the operation; later unexplained differences do not become new openings.

Add the common append-only journal-retirement foundation required for an honest
zero replacement. Centralize active/inactive entry reads and integrate allocations,
source-overlap versions, report/export/correction history and reconciliation
versions. Do not yet add transfer cancellation, duplicate repair or arbitrary
manual journal APIs. Those use the reviewed foundation in later packets.
Advance the unreleased schema, refuse prior disposable pilots before writes and
recreate demos. Preserve one authoritative profile, exact USD/debit signs and
independent source/capture/coverage/reconciliation dimensions.

Ledger specialist exclusively owns `v2_profile_store.py`, `v2_report_export.py`
and focused new opening/retirement tests, with necessary existing test updates.
Desktop specialist owns `v2_opening_review.py` and new opening-correction UI tests.
Primary owns contracts/roadmap/TODO/this record and integration. Independent
integrity review covers actual financial/provenance/persistence/report changes.
No recursive delegation. Only synthetic/disposable data; no private sources or
1.x mutations, production keys or external release/service actions.

## Result and review

Schema 13 adds append-only journal retirements and opening-decision revisions.
Both initial and corrected decisions have validated persisted content versions.
Latest reads do not revive initial openings. Corrections support nonzero/zero,
changed cutoffs and basis-only refresh, with exact dated inverses and no dummy
replacement. Retries are idempotent; partial writes roll back. Revision-12 pilots
are refused before writes. Shared inactive reads, allocation counts, report and
reconciliation/overlap versions include this history. Workbook Retirements links
preserve original/inverse references while transaction rows exclude openings.

The UI shows saved/current openings and newest-first history, with a required
reason and confirmation. Composite snapshots prevent candidate/basis races;
source forms submit loaded expected revisions rather than overwriting newer
reviews. Primary inspected 1080x720 synthetic correction/history renders; amounts,
actions and details were readable. Owner/native acceptance remains pending.

Integrity review reproduced three gaps: an inexact retirement inverse, an
unconfirmed basis substituted into a saved revision, and an unbalanced linked
opening counterpart. All were fixed. Persisted validation checks exact inverse
date/event/accounts/amounts/review/reason, empty payload/index allocations,
disjoint correction graphs, decision content digests and complete balanced
opening shapes. Common reports and backup refuse those corrupt states, while
pending/stale source assertions remain recoverable. Checksums detect accidental
changes; they do not authenticate a database against hostile modification.

## Verification

Required: nonzero-to-zero, zero-to-nonzero, changed cutoff, basis-only refresh,
tied/conflicting sources, stale decision/basis forms, idempotent retry and failed
transaction between retirement/replacement/revision. Check active allocations,
correction chains, export history, position signs/as-of math, saved reconciliation
invalidation and snapshot/reopen. Verify GUI confirmation/cancel/refusal/history
and source-review form freshness. Run focused plus relevant V2 integration,
changed-file Ruff and hooks; record Windows vs unperformed native/owner checks.

Windows/Python 3.13.15, isolated home/profile/null keyring:

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_opening_corrections_dialog.py client/tests/test_v2_reviewed_openings.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_opening_corrections.py client/tests/test_v2_journal_retirements.py client/tests/test_v2_report_export.py client/tests/test_v2_category_reports.py client/tests/test_v2_account_positions.py client/tests/test_v2_reconciliation_history.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests -k v2 -q
```

Desktop: 16 passed in 8.50s (10 new UI cases). Independent 11-module integration:
100 passed in 60.94s; original counterexamples rerun successfully. After the final
stored-only period guard, the writer's six-module affected suite passed 70 tests
in 72.35s and reviewer reran 33 affected opening/retirement/category/export tests
in 38.72s. Primary V2 integration: 267 passed, 1107 deselected in 165.13s; the final
affected checks cover the last guard. Changed-file Ruff check/format, repository
hooks, diff whitespace and local link checks passed. Offscreen Windows does not
establish Intel/native owner/installed/release acceptance.

## Remaining work

Other V2-3/4 safeguards and accounting/report breadth follow; human UX,
supported-platform and specifically authorized release gates remain separate.

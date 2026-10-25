# Durable reconciliation decisions and cutoffs

Date: 2026-10-25. Roadmap IDs: V2-4/5.
Branch/runtime: `feature/client-financial-insights`, explicit fresh V2 workspace.
Authorization: owner-approved roadmap and continued autonomous development.
Implementation: complete.
Automated verification: focused checks, final V2 integration, Ruff and hooks passed.
Independent review: all reproduced findings resolved; no remaining actionable findings.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Persist explicitly confirmed successful reconciliation checks as append-only
history, retaining account/source/cutoff/rule/input version, exact result and
versions of journal entries checked. A save revalidates the expected input version
inside its write transaction; stale/failed checks cannot be saved. Repeated
identical saves are idempotent. Source/capture/coverage/review dimensions remain
distinct. Retain historical decisions after inputs change; mark conservative
global-version changes stale without rewriting the original decision. Saving a
decision must not change its own reconciliation input version.

Show latest historical saved cutoff and currently valid saved cutoff distinctly
from the live check. Saving remains an explicit in-application user confirmation.
No journal posting, source alteration, invented balance or schema migration.
Advance the pre-release schema and refuse older disposable pilots before writes;
recreate demos. Verify backup/restore/reopen preserve complete history.

Contracts: current ledger, unified-store, cutover and overlap contracts.
Ledger specialist exclusively owns `v2_profile_store.py` and new reconciliation
history tests; desktop specialist owns coverage/reports adapters and interaction
tests after API agreement. Primary owns shared records/contracts/roadmap/TODO.
Independent integrity review covers integrated financial/persistence claims.
Only synthetic/disposable profiles and fixtures; 1.x/private data remain untouched.

## Result and review

Schema 12 adds immutable `ReconciliationDecisions`. Explicit saves retain exact
successful reviewed checks, cutoff/rule/input version, original reason and all
journal payload digests. Idempotent saves preserve the first reason; changed
global inputs retain the old decision as stale. Positions show latest saved,
current-input saved and newly computed live cutoffs independently.

Coverage offers explicit confirmation and saved history with exact values,
retained journal versions and current/stale state. Save refusal refreshes stale
forms; cancellation changes nothing. The live/history composite service pins one
snapshot. An admitted source with multiple sections bound to the same account
can leave live reconciliation unavailable without erasing history or blocking
backup. The UI explains that state and disables saving.

Independent review found and implementation corrected three gaps:

- Initially valid-shaped corrupt saved checks/incomplete manifests passed history
  and backup validation; unknown codes could crash details. Semantic successful
  check validation, known warning codes, a saved snapshot digest and exact
  current-version check/manifest comparisons now refuse those states. The digest
  detects accidental changes, not hostile database authentication. Stale retained
  snapshots are also checked. Real supporting-repeat/pending-overlap warnings
  have explicit truthful labels; unknown returned models stay unsupported.
- Initial backup validation recomputed live checks, refusing valid pending
  ambiguous bindings. It now validates retained history structurally and by digest
  independently of current check availability; pending profiles remain recoverable.
- Initial GUI live/history reads could mix committed versions under a concurrent
  change. `reconciliation_snapshot` now supplies both from one read transaction;
  concurrent-WAL tests cover this. Save still revalidates under its write lock.

The primary reviewed offscreen synthetic 1320x760 save/history renders. Labels,
values, confirmation controls and details were readable. This does not establish
owner/native acceptance.

## Verification

Target stale-form race, idempotence, atomic failure, append-only enforcement,
zero/missing opening, version changes/corrections/source review, exact cutoff/sign,
snapshot consistency and backup/restore. Run focused tests, full V2 integration,
changed-file Ruff and applicable hooks on Windows.

Initial service integration: 40 passed in 14.42 seconds across history,
reconciliation, positions, profile format and snapshots. Initial independent
integration: 38 passed in 28.11 seconds, before its additional repros found the
gaps above. Post-fix history regressions: 27 passed in 13.79 seconds. Desktop
post-fix history UI: 8 passed in 5.57 seconds.

Primary broad run, Windows/Python 3.13.15 with isolated test home/null keyring:

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests -q
```

1301 passed, 3 skipped, 2 failed in 293.93 seconds. One failure was an existing
assertion listing exactly four coverage tabs; updated to include Saved
reconciliations. The Windows builder metadata probe was blocked by the sandbox
account's PowerShell script policy, before its harmless mocked metadata command.
It passed separately with a process-only local-script policy, without changing
machine/user policy or signing/building a release:

```powershell
$env:PSExecutionPolicyPreference='RemoteSigned'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_release_bootstrap.py::test_windows_builder_stages_canonical_metadata_and_cleans_up_on_failure -q
```

1 passed in 0.47 seconds. Final post-fix V2 integration covers the changed paths;
the broad run is not recorded as a wholly passing final-candidate run.

Final post-fix commands (same isolated environment):

```powershell
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_reconciliation_history.py client/tests/test_v2_statement_reconciliation.py client/tests/test_v2_account_positions.py client/tests/test_v2_profile_store.py client/tests/test_v2_profile_snapshot.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_reconciliation_history_dialog.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests/test_v2_reconciliation_history.py client/tests/test_v2_reconciliation_history_dialog.py client/tests/test_v2_account_positions.py client/tests/test_v2_account_positions_dialog.py client/tests/test_v2_statement_reconciliation.py client/tests/test_v2_profile_snapshot.py client/tests/test_v2_source_recovery.py -q
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests -k v2 -q
```

Final focused service integration: 55 passed in 28.98 seconds. Desktop: 8 passed.
Independent integrated re-review: 67 passed in 53.29 seconds, with the original
counterexamples re-exercised successfully. Primary final V2 integration: 228
passed, 1107 deselected in 116.36 seconds. The final integration/re-review also
included disjoint embedded-source recovery changes, committed separately.
Changed-file Ruff check and format check passed. Repository hooks passed using
the installed interpreter and process-scoped safe-directory override; no global
configuration changes. Local link audit: 10 changed documents, 114 links, no
issues. `git diff --check` passed. No Intel/native owner/installed acceptance.

## Remaining work

Other approved V2-3/4/5 development follows. Consolidated human UX, targeted Intel
and specifically authorized release actions remain at their own milestones.

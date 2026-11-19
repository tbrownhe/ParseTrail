# Account consolidation and unified import progress

Date: 2026-11-18. Baseline: `159128c`. Scope: client V2-3/4/5/6/UX.
Implementation, native Windows verification and independent review: completed.
Owner acceptance and supported-platform/release authorization: separate, not claimed.

## Intent and boundaries

The owner requests irreversible consolidation of two bookkeeping account records
representing the same actual account or continuing obligation, commonly after a
replacement card number, plus unified compact progress during imports. This is not
an operation for paying off a debt or transferring balances between separate accounts.

Consolidation keeps original account identities, source evidence, journals and proof
history immutable. A durable audited membership records the retained account and
absorbed record; normal choices, future matching and financial presentation resolve
the continuing account. It creates no income, expense or transfer, and cannot sum
duplicate carried-forward opening debt. Preflight exposes counts/identifiers and
specific accounting blockers; stale scope, cancellation/failure and profile changes
must not leave partial state. No Unmerge command; recovery needs a prior backup.
Persisted history requires fresh pre-release schema 28 under the lifecycle contract;
no migration or mutation of existing owner candidates is selected.

The import journey is selection → compact progress → account/review only when input
is required → compact progress → final per-file report. Workspace owns both reusable
surfaces, queued handoffs and phase/generation/current-request validation. Only one
window-modal import surface is visible. Cancel preserves confirmed imports, waits for
the actual worker outcome and never fabricates cancellation of a committed write.
Neutral focus, fixed decisions and deliberate secondary Cancel placement prevent
stale clicks or repeated Enter from skipping/cancelling the next file.

## Ownership and permitted data

Primary owns conversation/integration, consolidation dialog, active GUI choices,
contracts/planning and this record. Ledger owns store/schema/headless consolidation,
import matching and financial read-model helpers/tests. Desktop owns workspace/import
surfaces and native progress tests. UI/UX supplies journey criteria before changes and
actual integrated rechecks. Independent integrity and acceptance follow stable code.
One writer per shared file; specialists do not recurse, commit or revert others.

Use only invented public fixtures and isolated disposable profiles. All owner
originals, populated test profiles, archives, screenshots and logs remain off limits.
Only known public helper code may be reused when preparing a new empty candidate.
No root .env, service/production data, private signing authority, publication or
daily-profile activation. Locked client Python, isolated app data and null keyring.

## Usability and verification criteria

Accounts exposes Consolidate accounts beside ordinary account actions and in its
menu. The user can identify direction, same-obligation meaning, affected statements/
reviewed entries/numbers, blockers, irreversible effect and completion. Pair changes
invalidate prior preview; no unsupported or stale state enables confirmation. Required
fields use established cues. Long names and previews fit 1050x700/1100x650; details
remain discoverable. Retired records are absent ordinary selectors but retained
history/source identity stays inspectable.

Verify unposted and ordinary posted histories, one versus duplicate openings, active/
retired value history, external versus within-obligation transfers, repeat/overlap,
new/remembered/full/abbreviated matching, report/position/drill-down scope, backup and
reopen. Exact amounts, unknown openings, immutable bytes and zero new financial
movement must survive merge, retry, stale/profile mismatch, failure and cancellation.

Verify all-auto and mixed import sequences, warning/account interruptions, fast
completion before a queued handoff, cancellation at each phase, failure/retry and
shutdown. Check current file, phase, completed counts, original-reader cleanup,
editor shortcuts, pointer/Enter safety, GUI-thread destruction and raw exits with
normal GC. Agent checks remain separate from actual owner acceptance.

## Result and remaining work

Accounts now exposes Consolidate accounts beside Edit and in its menu. The preview
explains one actual account, keep/retire direction, retained counts and masked
identifiers, conflicts, unknown opening and irreversible recovery. Confirmation
requires the same-account checkbox; success selects the kept record and refreshes
documents, reports and positions. Account history exposes Combined account records.
The export adds profile-wide decision metadata without changing raw period postings.

The service adds append-only AccountConsolidations and canonical member resolution,
preserving original raw owners and financial bytes. Matching retains authored full
numbers and reliable source identities. Pending original rows can still be reviewed;
historical opening/value correction and withdrawal use their original owner. New
bindings/metadata cannot target retired IDs, including concurrent changes under lock.
Expected-destination matching also resolves old IDs for receipts imported later.
Per-store membership caching tracks both committed and in-transaction change epochs;
rollback cannot leave a stale mapping. Fresh initialization now groups extension DDL,
seeds and validation in one transaction rather than repeatedly fsyncing each table.

Unified import progress is one owned compact QDialog, not QProgressDialog. Filename,
copyable full path, phase, completed counts, outcomes and cancellation consequence
remain current. The large reusable account/review surface is shown only for input.
Neutral waiting state is established before releasing the worker; validated queued
handoffs reject old generations/requests and avoid stale clicks/Enter. Confirmed
writes survive cancellation/shutdown; final reports use actual outcomes. Worker
termination precedes GUI-thread deletion and handoff-reference cleanup.

### Deliberate limits

- No application Unmerge or automatic backup: the preview directs a backup first.
  Restore-as-new from a verified prior backup is the recovery route.
- At most one active opening; missing remains unknown. Conflicting same-date values,
  active within-account relationships and already consumed duplicates block merge.
  Possible pending repeats must be reviewed before posting, not silently deduplicated.
- Lifecycle/closure, saved reconciliation, loan-component and loan-origination
  histories are excluded in this first version. Saving new reconciliation of an
  already consolidated account is refused. These are visible service/UI limits.
- A new source-backed opening owned only by an absorbed member cannot be authored
  under the kept ID; a reviewed manual opening remains available. An existing single
  opening and original-owner value/withdrawal history are preserved.
- Schema 28 requires a fresh disposable pre-release profile. Existing populated
  trials are untouched and continue through their own pinned launchers.

### Verification and findings

Locked Python 3.13.15, Qt 6.11.2 Windows plugin, isolated app data/null keyring;
normal GC retained. Only synthetic/public evidence and disposable profiles used.

- Ledger consolidation suite: 17 passed before the late destination-alias regression;
  posted/unposted histories, original bytes, zero new money, openings/values,
  stale/failure/cancellation/retry, physical clone, metadata/binding races, backup,
  external matching and self-transfer refusal. An 80-source check measured preflight
  0.019s and positions 0.074s. Fresh initialization measured approximately 0.624s.
- Broader accounting regressions: 103 passed; three baseline drill-down tests had
  stale category-count assumptions after protected Loan interest seeding. Updated
  assertions compare stable IDs; all three corruption/refusal checks then passed.
- Export, DTO and account-creation context: 18 passed. Exact original posting IDs,
  separate profile-wide metadata, formula-like strings and empty-period scope checked.
- Native mixed import/OCCU/workspace/queue/CSV combined sequence: 31 passed,
  533.91s, raw exit 0. Native progress handoff-race cases: 2 passed, 76.41s, raw0;
  offscreen equivalents 2 passed, 94.31s, raw0. Final consolidation/history/native
  drill-down run: 8 passed, 14.28s, raw0. Both original-owner withdrawals succeed.
- Late expected-destination regression plus resolution/flexible-funding suites:
  18 passed, 9.21s. Before the fix a later receipt under the kept account appeared
  eligible but failed raw-ID history validation; canonical comparison now preserves
  original proofs and accepts only the intended continuing destination.
- Changed Python files pass Ruff check/format; git diff whitespace check passes.
- Final headless integration across consolidation, export, account matching, batch
  assignment, cash movement and drill-down: 82 passed, 53.72s, raw0. Pytest reported
  only an unwritable node-ID cache warning; test profiles and results were unaffected.

Independent integrity review covered membership corruption, immutable originals,
atomicity, raw-owner history, export strings, duplicate and self-transfer protections,
future expected destinations and backup. Separate post-merge occurrence checks saved
distinct (both exact occurrences post once) and repeat (only retained posts); original
source tables and posting owners remain intact and survive backup/reopen. Injected
post-DDL validation failure leaves no profile or journal. Findings were corrected and
rechecked; no unresolved actionable integrity findings in admitted scope.

UI/UX reviewed the journey before implementation and actual native renders afterward.
At 1050x700/1100x650 workspace sizes, the 900x650 dialog and compact progress fit;
opening-conflict recovery wording was refined to name the correction/withdrawal path.
Retained history is readable without claiming completeness or a financial transfer.

Fresh acceptance independently discovered Accounts → Consolidate, kept ending 5678,
absorbed 1234 and found the retained history without navigation coaching. Spending
stayed $30, one account showed movement -$30, position stayed Unknown, two rows stayed
pending and both numbers/history persisted. Public-PDF batch imported two files via
compact progress/necessary decisions; cancellation after one newly saved file kept
that file and excluded the next. Each owned app closed raw0. Workspace sizes were
1180x820 and 1000x720. Evidence: scratch/consolidation-acceptance-20261118,
scratch/unified-progress-20261118/native-combined and root native test artifacts.

Qualification: acceptance used native QWidget rendering/Qt software events after the
computer-use inventory could not identify its owned window; initial helper probing
was interrupted with exit1 before switching methods. Navigation was independently
discovered, but adjacent synthetic fixture assertions exposed some expected financial
results. It is agent discovery, not human/OS-input acceptance. A standalone offscreen
pending-page focus assertion also fails at unchanged baseline 159128c; native originals
pass, no production workaround added. Other platforms, installed/offline execution,
full accessibility/Tab traversal and broader live archives remain unverified here.

Owner acceptance, other supported-platform checks, signing/publication and daily
profile activation are separate and not claimed. No selected implementation remains.

### Commits and fresh owner test

- `fa61b95`: immutable-account consolidation services, matching/read models and
  accounting/export regressions.
- `0bdfc9c`: consolidation UI/history, active choices and unified import progress,
  with native regressions. Normal pre-commit hooks passed for both commits.
- New isolated empty candidate:
  `scratch/v2-owner-fresh-20261118-consolidation-768800bc/Open-workflow-test.cmd`.
  Runtime is pinned to `0bdfc9c`; 321 public runtime files, 23 development definitions,
  fresh schema 28, no sources/journals/consolidations and only seeded Loan interest.
  Ephemeral catalog signing key was discarded. Native Windows hidden startup smoke
  passed: ready, empty Documents, Import enabled, expected sidebar order, profile
  bytes unchanged and raw Qt exit0. Existing owner trials remain untouched.
  START-HERE explains both workflows and the new-format boundary. After handoff,
  all owner-added content/logs/screenshots in this candidate remain private.

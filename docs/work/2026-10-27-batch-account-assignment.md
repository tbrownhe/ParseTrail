# Assign document accounts in batches and open retained originals

Date: 2026-10-27. Roadmap IDs: V2-3/4/6/UX.
Branch/components: feature/client-financial-insights; local evidence/account review.
Authorization: owner requested parser-known institution read-only in normal use, batched account assignment by institution/document identity with account creation for unmatched groups, and default-app access to original DB blobs with managed temporary files when memory handoff is unavailable.
Implementation: complete in development; verified public runtime handoff prepared.
Automated verification: integrated 100-test run passed; final lifecycle regressions verified separately.
Design verification: ui_ux reviewed grouped batch/confirmation, cancellation, source access and lifecycle states before implementation.
Independent review: integrity reviewed financial association, temporary-file/privacy boundaries and integrated cancellation; reproduced lifecycle findings corrected and independently rechecked.
Owner acceptance: existing Yamaha account creation/assignment reported successful; this batch/original-open work not yet reviewed.
Release authorization: not authorized; no release actions selected.

## Scope and decisions

Baseline clean source 4a89377. Use one batch screen grouping unassigned printed
account sections by exact verified institution, asset/liability kind, tracking
scope and printed identifier/form. Reuse current explicit source associations,
including an opaque masked Yamaha identifier, without reconstructing digits or
parsing display names. Unique complete-number matches may suggest existing
accounts. Abbreviated-number suggestions require the existing explicit default-off
preference and distinct qualification; this feature does not enable it silently.
Conflicting prior associations, ambiguous numbers, missing authority/scope and
accountless exports remain explicit manual/skip cases. Existing assigned sections
and history/correction protections are untouched.

Show repeated documents together, with document/section/account counts kept
distinct. Missing matches raise one prefilled account panel per group. New
accounts and choices are staged in memory. One final Apply summary is the user's
explicit confirmation of all selected associations; it creates selected accounts
and bindings atomically without posting financial entries. Cancel before Apply
writes no profile data. Stale source/account/catalog state refuses without partial
writes; cancellation and commit outcomes must be reported truthfully. Preserve
staged choices for review/refresh where still compatible.

Known parser institution is read-only in document-backed account creation.
Unknown/manual account setup remains explicit rather than guessed. Source facts,
masked identifiers and full account numbers retain their distinct meanings.
No schema migration or automatic financial posting is selected.

Open original retrieves verified retained bytes, independently of the original
import path. Default desktop viewers need a supported local path, so use a private
randomized temporary copy and the OS's default association. CSV/PDF are the admitted
workspace originals; this does not add XLSX import support. Do not launch viewers
from selection/rendering or claim launch dispatch proves the document displayed.
Successful copies stay through the ParseTrail session, with narrowly scoped
cleanup/locked-file handling; no arbitrary temporary-directory sweep. Ordinary
local source copies are authorized here; server contribution plaintext remains
outside this workflow.

## Ownership and permitted data

Primary owns batch GUI, workspace wiring, read-only institution presentation,
shared form staging mode, documentation/integration/commits and public demo handoff.
Ledger owns headless batch planning/apply, store changes and tests. Desktop owns
original-blob/temp lifecycle, Qt opener, evidence-preview integration and tests.
ui_ux designs/critiques; integrity independently reviews actual financial/security
paths. One writer per file, no recursive delegation or independent commits.

Use public synthetic/disposable data and archive-sized synthetic profiles. Do not
apply a batch, create accounts or launch private originals on the owner's current
demo. Public runtime handoff may read its schema marker only and must preserve
its profile, catalog, preferences, review state and earlier runtimes. No original
archive, V1 database/settings, production keys/services or root .env needed.

## Observable criteria

- Planning and apply run off the GUI thread with bounded cancellation/shutdown.
  Archive reads validate retained sources once per operation rather than looping
  expensive full-source reads through single-binding widgets.
- Group screen shows source institution/identity/scope and matching basis,
  compatible account/new-account choice, representative document periods and
  Open original. Exact prior identity associations and opted-in abbreviated
  suggestions are distinguishable; ambiguous groups are never first-row defaults.
- Final summary shows reuse/create/skip decisions and exact source-section counts.
  Cancel, stale refusal and failed transactions leave no partial accounts/bindings;
  successful retries are idempotent. No journals, openings or source facts change.
- Original-open checks use DB bytes and safe admitted suffixes, preserve source
  hashes, avoid arbitrary paths/symlinks, and provide opening/dispatch/failure
  states plus retry/save recovery. Tests never launch external viewers.
- Inspect actual Qt at representative 1024x768/larger sizes with working fonts,
  long identities, missing/ambiguous/empty/failure states, keyboard focus and
  native Windows behavior where proportionate. Distinguish agent inspection,
  owner acceptance and installed/Intel/release evidence.

## Result and verification

The headless `v2_batch_account_assignment` planner returns grouped targets,
typed/provenance-qualified periods, compatible accounts and truthful matching
bases. Apply rechecks profile identity and current inputs, stages referenced new
accounts and selected bindings atomically, and reports exact no-op retries. No
store schema/index changes were required. Protected targets are partitioned from
eligible targets with the same printed identity so one locked section does not
block the remaining statements.

`V2BatchAccountAssignment` uses worker-owned connections, grouped choices and a
final table with institution, printed identifier, account kind/scope, selected
account, action and document/section counts. Missing matches raise one staged
account form per group. Reload retains compatible explicit choices. Stale Apply
is disabled until Reload. Known institution and printed identity use flat,
read-only, selectable fields; unknown/manual institution remains editable.

Original access is available from Documents, both account-assignment reviews,
the batch screen and central evidence preview. Worker reads verify the retained
source independently of import paths; Qt dispatch runs on the GUI thread. Copies
are private randomized admitted PDF/CSV files with atomic publication, bounded
128-file/256-MiB session storage, active-session leases and guarded dead-session
cleanup after 24 hours. Windows owner/DACL and symlink/reparse checks protect
reuse/cleanup; locked successful files are retried later. Opening failures offer
retry or deliberate original recovery rather than claiming that dispatch proves
display. Session exit and no-event-loop teardown drain readers before cleanup.

Focused checks and integrated verification use `client/.venv/Scripts/python.exe`,
`PYTHONPATH=.;client/src;client`, isolated homes/null keyring and synthetic data:

- Integrated batch core/GUI, original lifecycle, inline account creation,
  workspace, document browser, recovery and accountless review: **100 passed in
  90.02s**. Focused core: 23 passed; original plus recovery/preview: 34 passed;
  batch GUI: 7 passed before the final destruction regression.
- A newly generated synthetic 946-source/47,252-row profile with 94.5 MB of
  originals and 163.35 MB database: Plan **0.977s**, Apply 945 sections **0.971s**,
  each exactly 946 verified source reads, zero new accounts/journals, read-only
  plan left profile bytes unchanged. This does not establish performance with
  substantially populated financial history. Evidence:
  `scratch/ux-batch-benchmark-7kfw1khg/result.json`.
- Native Windows/Segoe UI 10 screenshots and real widget/worker journeys at
  1024x768 and 1280x850 cover grouped, ambiguous, manual, empty, long-name,
  staged form, summary and success states. Staging/Cancel preserve profile bytes;
  Back preserves choices; Apply saves four sections/one account with zero
  journals. Final summary wraps names/identifiers and shows kind/scope; empty
  state disables Open original. Tab sequence is logical. Evidence:
  `scratch/batch-account-ux-298fd86d/`. Actual external OS dispatch was mocked.
- Independent integrity checked opaque reuse, suffix preference, guard parity
  for zero-row sections protected by source openings/correction history,
  rollback/stale/idempotence and same-profile binding. Native Windows broad ACL,
  junction and wrong lease-marker probes preserve outside sentinels. Evidence:
  `scratch/ux-audit-batch-originals-20261027/`.

Independent lifecycle review reproduced two missing cancellation paths: parent
destruction during Apply and dialog rejection during a pending original read.
Corrections explicitly cancel their retained jobs, preserve rollback and suppress
late viewer dispatch. Final batch GUI suite: **8 passed in 7.68s**, including
parent destruction after the real staged account SQL insert; accounts, bindings,
journals and exact profile bytes remain unchanged. The independent reviewer's
unchanged probes now show cancellation/rollback and no viewer dispatch after
dialog rejection. Additional actual subprocess `app.quit` and no-event-loop
interpreter-exit probes finish with exit 0 and unchanged profile hashes while a
staged account transaction is pending. Evidence:
`scratch/ux-audit-batch-originals-lifecycle-fixed-20261027/` and
`scratch/ux-audit-batch-originals-20261027/batch-shutdown-result.json`.

Final original-document suite: **25 passed in 11.60s**, including dialog
accept/reject/close cancellation, intentional temporary Hide preservation and
publication/queued-completion races. Independent review reports no remaining
financial, security, privacy or lifetime blocker.

Prepared a new immutable public runtime without replacing prior runtimes or
copying/mutating owner data:
`scratch/archive-demo-f92c025/runtime-updates/20261027-batch-accounts-originals/Open-updated-demo.cmd`.
The pinner reads only the existing demo's schema marker (22), copies 281 public
runtime/resource files and targets its same profile/catalog/preferences/home.
The owner launcher was not executed. A separate disposable synthetic journey
imported two sources through the pinned modules, staged and applied one account
with two assignments, verified zero journals, dispatched exact retained bytes
through a mocked OS opener and confirmed exit cleanup. Evidence:
`scratch/batch-pinned-check-530970f1/result.json`.

This is agent native/synthetic verification, not owner acceptance, real viewer
association testing, screen-reader/high-DPI acceptance, Intel or installed-release
acceptance. No batch was applied to the owner's review profile and no private
original was opened; existing archive/profile/catalog/preferences remain intact.

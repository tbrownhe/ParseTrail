# Correct reviewed source account assignments

Date: 2026-10-25. Roadmap IDs: V2-3/4/5.
Authorization: approved roadmap, continued development and cohesive tested commits.
Implementation: complete.
Automated verification: focused and broad integration checks complete; corrected test setup documented below.
Independent review: complete; ordinary transfer-history bypass resolved and rechecked.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Permit explicit correction or clearing of a printed-identity binding, entirely
accountless whole-file assertion, or selected accountless row assignments after
all affected active source consumption has been withdrawn. Preserve historical
journals under their original financial accounts and refuse live source-backed
opening anchors. Retain immutable prior/new assignment context, reason and
optimistic review basis. No source facts, postings or balances change here.

Affected repeat groups/edges return to pending atomically and durably. A later
A-to-B-to-A binding change cannot reactivate an old repeat decision. Keep one
occurrence per source and exact original review context. Ordinary binding APIs
retain their history locks; a separate reviewed correction service/UI handles
history. Preserve section/file/row mode rules and require explicit clearing
before switching whole-file versus row assignment modes.

Use one committed snapshot for preview, blockers, affected rows/reviews and
history. Revalidate inside one write transaction. Append typed, digested history
and verify it on common reads/backup, with atomic failure and stale-form refusal.
Include all binding inputs in reconciliation versions. Earlier disposable schema
revisions are recreated; no 1.x migration or alias.

Ledger owns `v2_profile_store.py`, necessary report serialization and focused
service tests. Desktop owns both binding adapters, a shared correction dialog
and focused interaction tests. Primary owns documentation, scope and integration;
independent integrity review covers monetary/persistence claims. Synthetic and
disposable data only; no private/1.x mutations, recursive delegation or release.

## Result and review

Fresh schema 16 adds immutable `BindingCorrections` with canonical target,
prior/new scope and effective row mappings, optimistic request version, reason,
timestamp, exact invalidated review manifests and a persisted digest. Section,
whole-file and selected-row correction/clearing are transaction-owned. They
require zero active allocation records and consumption; old originals, inverses,
source facts and allocation history remain unchanged. Reposting under a corrected
account requires fresh interpretation and identity.

The correction snapshots retain all affected overlap graph endpoints and
transfer suggestion decisions with source/date/description/account context.
Connected historical repeat edges receive explicit pending revisions atomically.
Transfer dismissal invalidation retains an exact prior manifest and high-water
mark; an A-to-B-to-A assignment cannot silently make an old dismissal current.
File/row assignment state and correction history now enter reconciliation input
versions. Common reads and backup validate recorded contexts, exact invalidations
and consistency of latest saved mappings with mutable current assignment state.

Both assignment adapters retain ordinary history locks and open a shared
correction dialog with previous/new assignment, reason, confirmation, blockers,
exact affected relationships and retained history. Read failures clear controls;
stale writes refresh the preview. The first offscreen 1080-by-700 layout was
readable with a loaded Segoe UI font; final relationship-tab inspection follows.

Primary review closed two bypass risks: an ordinary assignment after an earlier
unposted correction must use correction history, and existing source-backed
opening anchors must block ordinary as well as reviewed reassignment. Dependency
checking is deliberately conservative: current source-account bindings and
historical statement-source associations with a saved opening (including zero)
block changes. Exact source lists were not persisted in older opening decisions.
Same-period replacement therefore needs the forthcoming explicit opening
withdrawal workflow. This is a development dependency, not a new human gate.

Opening-correction synthetic setup now keeps the old binding and introduces an
explicitly earlier reviewed source when changing the opening basis. The tied
conflict case remains, then separately introduces earlier evidence for the
pre-opening posting-conflict check. Financial assertions were retained; no SQL
bypass was introduced. Sixteen opening checks still pass.

Independent review additionally reproduced an ordinary A-to-B-to-A bypass when
only transfer-dismissal history existed. The fix requires that history to lock
ordinary section/file/row APIs and controls too, after dismissal or reopening;
explicit correction owns its durable invalidation. Independent reproduction
confirmed ordinary reassignment now refuses, reviewed A-to-B-to-A retains two
correction records, the old dismissal stays inapplicable, a fresh candidate is
visible, no journal is created and backup succeeds. No actionable findings remain.

## Verification

Test section/file/row correction and unassignment, mixed-file and mode conflicts,
active ordinary/whole-transfer blockers and successful correction after complete
withdrawal, opening blockers, historical account preservation, repeat-group
invalidation, A-to-B-to-A, optimistic stale review, idempotent retry, failed-write
rollback, malformed stored context, pending counts, saved reconciliation version,
reopen/backup and GUI cancellation/refusal/history. Run focused and relevant V2
integration, changed-file Ruff and hooks; inspect functional offscreen layout.

Windows 11 AMD64, Python 3.13.15, Qt offscreen, synthetic/disposable profiles.
The first 25 binding service checks passed in 18.23 seconds. A seven-module run
covering bindings, transfer correction/transfers, openings, reconciliation,
common integrity and profile store passed 133 checks in 120.47 seconds. An earlier
broader run passed 143 and found one GUI warning capitalization mismatch; desktop
fixed the wording without weakening functional assertions. The checks below
cover the final transfer-history bypass fix and GUI refinement.

Final binding service checks: 31 passed in 41.97 seconds, including all three
assignment modes after transfer dismissal and reopening. Final GUI/adapters:
39 passed in 31.59 seconds. Independent combined binding/service/GUI/adapters:
65 passed in 68.83 seconds, plus six final transfer-history-lock cases in
8.15 seconds; earlier six-module integration passed 125 in 105.39 seconds.
Both primary and desktop inspected final Review/Affected relationships tabs at
1080-by-700 with temporary Segoe UI loading; endpoint context and full references
were readable.

The full V2 run passed 474 checks, deselected 1,107 and failed two prior transfer
test setups in 307.67 seconds. Both used now-forbidden ordinary rebinding after
saved transfer review. Test-only updates require explicit reviewed correction;
the returned A-to-B-to-A case now proves both old dismissals stay stale and a
fresh current-context review is required before GUI reopening. Both full affected
transfer modules then passed 47 checks in 36.48 seconds; the independent two-case
rerun passed in 2.16 seconds and retained all material financial/history
assertions. Runtime was unchanged after the broad run. This is separate broad
and affected verification, not a claimed single 476-check green run.

The disjoint diagnostic/bootstrap acceptance run passed 117 non-V2 checks in
22.92 seconds. Changed-file Ruff check/format, repository hooks, whitespace and
local links passed. No native owner/Intel/installed acceptance or release action
was performed.

## Remaining work

Opening withdrawal, broader source matching and accounting/report breadth remain
separate packets; consolidated UX/platform/release gates remain open.

# Withdraw ordinary interpretations and repair posted repeats

Date: 2026-10-25. Roadmap IDs: V2-3/4/5.
Authorization: approved roadmap, continued development and cohesive tested commits.
Implementation: complete.
Automated verification: focused service/interaction and common integrity checks passed.
Independent review: complete; identified findings resolved and rechecked.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Allow explicit withdrawal of an active supported single-row cash/card category
interpretation, including its active correction replacement. Retire it with an
exact original-date inverse, release its active allocation and leave immutable
source facts pending. Reposting after withdrawal requires a fresh identity and
review context; old originals are never revived. Reject transfer legs and other
unsupported shapes; whole transfers have their own correction workflow.

Repair two already-posted detected repeat occurrences by retaining one reviewed
interpretation, retiring the redundant supported category entry, and recording
the supporting-repeat relationship atomically. Keep one occurrence per source,
stale-form refusal and all original/correction/allocation history. Ordinary repeat
review must not silently exclude journal history; only dedicated repair verifies
the required complete retirement. Allow later explicit distinct/pending review
without silently resurrecting an entry; newly independent evidence still needs
fresh posting review. Keep repeat references distinct from source allocations.

No inferred financial matches, balancing entries, partial settlements, arbitrary
manual cancellation or binding moves in this packet. Broader matching/binding
repair follows. Advance the disposable schema as needed, with no migration.
Preserve report/export/reconciliation exactness, source provenance and recovery.

Ledger solely owns profile-store/export and new focused service tests. Desktop
owns cash/card/repeated-row GUI adapters and new interaction tests. Primary owns
shared docs/contracts/TODO/roadmap/record. Independent integrity review covers
actual integrated financial/persistence/failure claims. Synthetic/disposable
data only; no recursive delegation, private/1.x mutations or release actions.

## Result and review

Disposable schema 15 adds immutable `SourceInterpretationActions` and
`PostedRepeatRepairs`. A composite source snapshot supplies rows, categories,
entries, history, preferences and optimistic review basis. Cash/card adapters
offer explicit withdrawal with reason and confirmation. The exact original-date
inverse releases active consumption, preserves historical allocations and leaves
the source pending. A later reviewed post has a fresh identity.

Posted-repeat repair retains one supported active category interpretation,
retires the redundant one and saves supporting-repeat review atomically.
Corrections and different accounting dates retain their own dated inverses.
Validated repair proof permits subsequent pending/distinct/repeat review without
reviving money. Workbook Source Reviews and Repeat Repairs sheets preserve these
actions separately from active financial totals. Persisted action types, digests,
source/index shapes and exact retirement links are checked by common reads and
backup; malformed history is refused.

Independent review found and resolved two GUI defects: the historical-row guard
blocked reconfirming a repaired repeat after pending review, and old idempotent
receipts overstated the current state after later repost/withdrawal. The former
now requires validated repair proof plus zero active allocation; receipt wording
identifies the historical action and refreshes current state. Independent card
date-restatement and transaction-failpoint checks retained exact totals and full
rollback.

Report integration exposed an additional shared initial-entry integrity gap.
Strict decoding now refuses noninteger, zero, overflow, malformed or unbalanced
postings and non-TEXT payloads for every journal origin. A nonrecursive common
guard checks ordinary initial/historical source and allocation-index shapes,
active bindings/unique consumption and exact correction inverses. Historical
reviewed card dates stay valid after current assumed-date opt-in is disabled.
Pending/unreviewed manual fixtures retain structural validation. Positions,
reports, reconciliation, active consumption and backup apply the guard. This is
shared protection, without another schema change or new manual-entry workflow.

## Verification

Test corrected-entry chains, exact dated inverse and source consumption,
withdraw/repost identities/idempotence, stale review frames, atomic repeat repair,
retained/root corrections, genuine equal occurrences, refusal of transfer legs,
later distinct/pending review, failed transaction rollback, report/budget/history
and saved reconciliation changes, backup/reopen and malformed stored history.
Run focused plus final V2 integration, changed-file Ruff and repository hooks.

Windows 11 AMD64, Python 3.13.15, Qt offscreen, synthetic/disposable profiles:
42 source-repair/overlap checks passed (32.10 seconds), a broader affected service
run passed 82 (68.44 seconds), and the desktop runs passed 19 new checks
(17.09 seconds) plus 12 existing dialog checks (13.88 seconds). Independent
financial/persistence review passed 75 checks (57.64 seconds), with additional
card-date and rollback probes. The final combined repair/drill-down/common-guard
run passed 61 checks (74.42 seconds); the final 13-case integrity suite also passed
(26.32 seconds). Final integration results are recorded below before closeout.

Final V2 integration: 393 passed, 1,107 deselected in 244.61 seconds. The earlier
run passed 390 and failed one saved-manifest test whose old description tamper
now correctly fails the earlier source-shape guard. Retargeting that test to
nonfinancial review reason preserves its independent digest purpose; the final
common-integrity/reconciliation-history run passed 40 checks in 32.65 seconds.
The common-integrity fixture is independent of the later drill-down packet.
Independent final affected integration passed 36 in 43.17 seconds, plus the
earlier broader 103-check run; no actionable findings remain. Changed-file Ruff,
repository hooks, whitespace and local links passed. No native/Intel/installed
or owner acceptance was performed.

A small prior-transfer test follow-up adds BLOB history refusal coverage without
changing transfer runtime behavior; its focused check passed (2.35 seconds).

## Remaining work

Review-locked binding repair, broader matching, admitted accounting/report breadth
and consolidated human UX/platform/release gates remain.

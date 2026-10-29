# Full-window transfer planning and confirmed batches

Date: 2026-10-28. Baseline: 35d6ed8, feature/client-financial-insights.
Roadmap: V2-4/5/UX. Components: local financial services and desktop review.
Authorization: owner accepted full-window automatic preparation, explained
conflict proposals, unresolved ties and one explicit final batch confirmation.
Implementation: complete. Automated verification: 199 core and 60 GUI integrated
checks passed, plus focused audit/pinned-runtime checks. Design verification:
native Windows criteria passed after fixes. Independent review: no material blocker.
Owner acceptance: pending integrated use. Release authorization: none.

## Scope and controlling decisions

Compute one complete candidate graph at the selected maximum date gap, preserving
source/inventory, account scope, exact amount/currency, duplicate/overlap,
consumption, assumed-date and stale-context protections. Unique both-leg pairs
are ready for confirmation. Rank conflicts collectively with a one-to-one
assignment and an unmatched option; do not greedily consume narrower windows or
break equally good interpretations by appearance/import order. Show tentative
reasoning and alternatives beside proposals. Estimated-date permission remains
separate and never silently enabled. No unattended posting or saved rule editor
is included; those were future possibilities in the accepted recommendation.

The current movement model has source descriptions, not typed counterpart
accounts or shared transfer references. Do not manufacture those facts from
arbitrary text. Date-based proposals must be explicitly identified as tentative;
the solver cannot prove financial purpose or statement completeness. Retain
manual individual review and all correction/history/repayment routes.

One explicit confirmation posts the selected compatible pairs atomically after
fresh whole-graph/basis/profile/preferences validation. Preserve idempotence,
cooperative cancellation, exact clearing and whole-event correction. Retain the
planning rule/explanation with posted history. No schema/dependency change unless
an identified need justifies one. Preserve recent posted-history performance.

Ledger owns new core planner, batch/store integration and focused tests. UI/UX
owns read-only design and actual UI critique; desktop owns the two transfer GUI
modules, new planning-dialog tests and one history-tab test adaptation. Integrity owns
independent design and final financial/persistence review. Primary owns the user
conversation, shared contracts/planning, this record, integrated checks, commits
and runtime handoff. Specialists do not recurse, commit or revert others' work.

Public synthetic/disposable data only for development and all mutations. Existing
demo/archive/profile/settings remain read-only; this packet needs no private
financial content. Public code-only runtime packaging may read the existing
schema marker and preserve the same review profile/settings. Do not execute the
owner launcher, reset review state, publish, sign or activate a daily profile.

## Design and verification criteria

Design review precedes widget implementation. The user must find planning from
Review transfers, distinguish Ready/Suggested/Needs review, understand full date
scope and estimated dates, inspect accounts/descriptions/alternatives, and choose
compatible pairs without an arbitrary conflict being pre-approved. A final
manifest shows exactly what will post; cancel/close keeps financial state intact.
Pending/error/stale states disable actions and recover through explicit reload.
Planning and DB work stay off the GUI thread, selection causes no DB reads, and
no per-gap repeated profile scan or silent candidate cap is introduced.

Verify the narrow-window counterexample, permutation invariance, ties, unmatched
rows, assumptions and disabled competitors, duplicate/consumption guards, partial
selection, forged/stale plans, cancellation/failure rollback, idempotence and
rule history. Compare planner output against exhaustive small public graphs.
Use representative posted-history performance and native Windows task inspection
at normal/smaller window sizes with long labels. Offscreen/native agent evidence
does not attest owner, macOS/Intel, installed-release or accessibility acceptance.

## Result and review

### Agreed design before implementation

Plan transfers is the default page; All matches and existing history remain
available. Preparation happens in the background with the saved snapshot. Ready
means neither leg has another candidate in the full selected horizon, not proven
financial purpose. Only non-estimated Ready pairs are initially included.
Suggested pairs are explicitly tentative and unchecked. Estimated isolated pairs
need existing permission plus explicit selection; estimated-date conflict groups
are not date-ranked. Needs review groups remain available through All matches.
Highlighting inspects; Include changes the draft. The final manifest freezes the
exact selection, reason, profile and preference context before its modal loop.

For each bounded connected component, maximize the sum of integer scores
`maximum_gap + 1 - pair_gap`; unmatched scores zero. Do not prioritize maximum
cardinality. Propose only edges present in every optimal assignment, proven by
excluding each selected edge and resolving. Equal optima stay unresolved; sort
order cannot decide financial links. More than 64 legs or 512 edges falls back
to explicit manual review with the complete graph retained, not truncated.
There is no calibrated probability or reference/description matching claim.

UI/UX reviewed the journey before widget implementation. Independent integrity
review accepted the objective only as unchecked tentative ranking with all
material qualifications visible. Implementation and verification are complete.

### Verification

Independent pure-planner review compared 160 small public graphs (62 with tied
optima) against exhaustive unmatched-permitted enumeration. Optimum scores and
the intersection of all optimum edge sets exactly match the implementation;
candidate permutations preserve output. Realizable equal-score one-pair versus
two-pair alternatives remain unresolved. Mixed estimated-date competitors block
the entire component from date ranking. Evidence:
`scratch/ux-audit-transfer-planning-20261028/oracle-result.json`.

Independent store probes cover client-recomputed forged fingerprints, cancellation
after an insert, a second-insert SQL failure, selected ready/tentative posting,
exact retry, new competitors, preferences/profile changes, withdrawal/replacement,
active binding/correction, caller transaction refusal and later source corruption
on the same handle. No remaining actionable finding; failures preserve exact DB
hashes and clear operation state. Unrelated non-graph metadata may permit a
truthful no-write retry after complete current verification; it cannot authorize
a new posting. Evidence: `selected-core/` and `selected-edges/` under the same
independent review directory.

On the unchanged public 946-source / 19,169-row / 631-event fixture, a read-only
snapshot takes 1.159s, planning all 189 Ready pairs adds 8.4ms and building a
selection adds 7.6ms. Original fixture hash remains unchanged. Evidence:
`scratch/transfer-planning-runtime-20261028/representative-result.json`. This is
warm source execution on the Windows development machine, not an installed or
owner-profile performance claim. Integrated UI and source checks are recorded below.

Core checks: 16 new planning cases plus 10 existing batch and 9 populated-history
regressions passed (35 tests, 25.41s); independent rerun of the 16 new cases passed
in 8.28s. A disposable copy of the same public fixture posted all 189 selected
pairs in 1.512s and reloaded in 1.271s, leaving 820 events. Source verification is
once per source per operation (946 for posting and 946 for refresh), not per pair.
Eight bounded stress components containing 512 edges each (4,096 total) plan in
0.424s and correctly retain their ties. No private inputs or schema changes.

Primary integrated core checks cover planning, ordinary/batch transfers,
populated history, correction, overlap matching/index, binding correction,
read-performance and settlements: **199 passed in 153.23s**. Independent review
identified imprecise common audit wording for Ready/estimated pairs; clarified
that only conflicts receive date scores, while Ready/estimated are unranked.
All 17 planning tests then passed in 8.09s with lint/format clean. A separate UI
qualification finding (uncomputed unmatched counts presented as zero) was fixed
before UI closeout.

The headless foundation is committed as ee5535f. Independent final review reports
no material blocker: 160 exhaustive-oracle graphs, 12 core adversarial scenarios,
five actual offscreen GUI flows and three real selected-write shutdown subprocesses
passed. Parent destruction, app quit and no-event-loop teardown after the first
SQL insert each exit cleanly with exact DB-hash rollback and no partial journals,
allocations, events or clearing. Final core/planning-dialog tests: 29 passed in
19.00s. Frozen modal state, preference/profile changes, stale authoring during
confirmation, cancel draft retention and exact selected posting are covered.
Both audit wording and uncomputed-zero findings are resolved. The native UI/UX
review additionally found unused alternatives counted as unresolved work;
the fix distinguishes Alternative from genuinely Needs review groups.

Primary GUI integration (new planning, asynchronous review, correction/history,
loan-register navigation and workspace window): **60 passed in 52.49s**. Combined
with the 199 core checks, this covers 259 distinct integrated cases. Final changed
Python lint/format and diff checks passed. Only one old test needed adaptation
from a numeric tab index to the explicit Confirmed events widget.

Independent native Windows UI/UX reviewed actual 1250 and 1024 views with long
account labels, Ready/Suggested/Alternative/ties, source details, All matches,
estimated-date permission, empty state, failed-read recovery, stale confirmation,
selected posting and retained history. Space/Tab/Escape and default Cancel were
exercised. Mixed fixture counts are 1 Ready, 2 Suggested, 1 Alternative and 1
genuinely unresolved group. Three explicitly selected pairs post neutrally while
ties remain pending. Root inspected the actual 1024 Plan and final manifest.
Evidence: `scratch/transfer-plan-ux-5b77ce47/`.

The last native review found a focused repayment without a counterpart landing
on the unrelated global Plan page. Fixed focused entry to open All matches before
pair/event lookup; an eligible historical event still opens Confirmed events.
The new regression and independent native recheck confirm the recovery message
is visible, individual posting disabled and unrelated Ready pairs are not the
focused action. Evidence: `scratch/missing-focused-plan-9a5e60c8/`.

Final native representative-profile measurements: 9.1ms warm constructor, 1.496s
load including the probe's 150ms gap debounce, 9.0ms background ranking. One
hundred checkbox/highlight operations take 450ms total, maximum 28ms, with zero
DB opens. Actual Review 189 / explicit final confirmation / selected posting /
automatic reload takes 3.035s (12ms selection preparation, 1.568s write worker,
1.329s reload), leaving 820 events. Pristine public fixture hash is unchanged.
1024 Plan/manifest/posted screenshots and metrics:
`scratch/transfer-plan-native-final-20261028/`.

### Same-profile public runtime handoff

New immutable launcher:
`scratch/archive-demo-f92c025/runtime-updates/20261028-transfer-planning/Open-updated-demo.cmd`.
It copies 286 public code/resource files and reads schema marker 22 only, keeping
the same saved demo profile, catalog, preferences and home. Earlier runtimes are
preserved. The owner launcher was not executed; no owner financial data was needed
for development or posted by tools. Final source/commit byte verification is
recorded beside the launcher after the desktop commit.

A separate disposable-profile check loaded the pinned modules and used actual
final buttons. Ready alone was prechecked; a proposal was explicitly added;
Cancel retained exact DB bytes and both selections; Confirm posted exactly the
selected two pairs/four allocations, leaving the other proposal unposted and
retaining the planning rule in history. Evidence:
`scratch/transfer-plan-pinned-check-ebf12f58/result.json`.

Selections are transient review drafts: manifest Cancel keeps them, while saved
state reload resets choices visibly. Memory peak, macOS/Intel, installed-release,
native scaling and screen-reader acceptance were not measured or attested. Owner
accounting acceptance and platform/release gates remain separate. No unattended
posting, saved rule editor, signing, release or publication was performed.

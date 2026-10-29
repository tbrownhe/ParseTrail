# Full-window transfer planning and confirmed batches

Date: 2026-10-28. Baseline: 35d6ed8, feature/client-financial-insights.
Roadmap: V2-4/5/UX. Components: local financial services and desktop review.
Authorization: owner accepted full-window automatic preparation, explained
conflict proposals, unresolved ties and one explicit final batch confirmation.
Implementation: active. Automated/design/independent verification: pending.
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
owns read-only design and actual UI critique; desktop implementation will receive
a disjoint GUI/test write set after screen/service plans agree. Integrity owns
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
material qualifications visible. Implementation and verification pending.

### Verification in progress

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
on the same handle. No actionable finding so far; failures preserve exact DB
hashes and clear operation state. Unrelated non-graph metadata may permit a
truthful no-write retry after complete current verification; it cannot authorize
a new posting. Evidence: `selected-core/` and `selected-edges/` under the same
independent review directory.

On the unchanged public 946-source / 19,169-row / 631-event fixture, a read-only
snapshot takes 1.159s, planning all 189 Ready pairs adds 8.4ms and building a
selection adds 7.6ms. Original fixture hash remains unchanged. Evidence:
`scratch/transfer-planning-runtime-20261028/representative-result.json`. This is
warm source execution on the Windows development machine, not an installed or
owner-profile performance claim. Integrated UI and final source checks pending.

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
qualification finding (uncomputed unmatched counts presented as zero) is assigned
for correction before UI closeout.

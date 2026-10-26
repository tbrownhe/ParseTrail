# Review nearby-date and revised-description source occurrences

Date: 2026-10-25. Roadmap IDs: V2-3/4.
Authorization: approved roadmap and continued development.
Implementation: complete.
Automated verification: service/UI and broader affected checks passed.
Independent review: integrated financial/GUI review and final metadata optimization complete; no findings.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Broaden candidate discovery to different saved sources on the same explicitly
bound financial account, with the same exact signed amount and source dates at
most three calendar days apart. Permit activity/posting date-role differences;
descriptions remain comparison context. Changed amounts/signs and unknown dates
remain outside this bounded rule. A candidate never establishes identity or
changes original dates, source evidence or journals.

Date proximity is not transitive. Repeat groups must remain pairwise eligible,
with one occurrence per source and no chains/cycles/distinct contradictions.
Full posting guards must retain candidate edges found only through supporting
rows. Review each actual row pair between different current groups explicitly,
including supporting-member/outsider pairs; do not infer group-wide distinctness
from one pair. Never silently discard alias-only neighbors or widen a date window
through a chain. A new group member introduces its own candidate edges and review
requirements. Keep explicit decisions scoped to retained source context.

Primary owns `v2_source_overlap.py`, pure tests, documentation and integration.
Ledger now owns `v2_profile_store.py` and focused service tests; desktop owns
`v2_source_overlap_review.py` and focused interaction tests. No writer overlaps.
Replace equality assumptions in discovery/counting, full posting guards,
repeat-group admission, posted-repeat repair and persisted repair validation.
Expose current group roots/relationships for truthful controls and direct
navigation to saved repeat edges, including beyond the ordinary display cap.
Alias-to-outsider distinct review is per actual row pair; it never resolves
unreviewed edges from another group member. Joining/changing a group requires
explicit clearing of conflicting saved repeat edges first. Bump live overlap and
reconciliation rules together so old forms/checks cannot certify a changed rule.
Synthetic/disposable profiles only; independent integrity review is required
before integration closeout. No private data, 1.x mutation or release actions.

## Result and review

Read-only investigation identified equality assumptions in inventory counting,
posting guards, repeat admission, posted-repeat repair and durable repair proof.
Changing only bucket membership is unsafe. Build a shared finite pair predicate,
deterministic date-window index, exact pair counts and full neighbor lookup first;
change the live rule only with complete store/UI integration.

The pure `NearbySourceIndex` now provides exact date-window counts by all sources
or one source, deterministic lazy pair iteration and uncapped neighbor lookup.
Counting uses date searches/source multiplicities without materializing pairs.
Unknown dates, non-activity date roles, zero/noninteger amounts are excluded;
malformed known dates and duplicate row identities refuse. Original exact
`bucket_key` and live rule remain unchanged during preparation.

Pure checks cover a separately computed 90-row pair oracle, per-source counts,
all neighbors, order independence, non-transitive triples and alias-only edges.
A 3,000-source cohort counts 4,498,500 pairs without building a pair list; iterator
display limits do not limit full neighbors. Six pure checks plus 21 existing
overlap checks passed (27 total, 14.57 seconds), Windows Python 3.13.15.
Changed-file Ruff check and format passed. This is preparation, not integrated
wider matching or a completed accounting safeguard.

Independent review also ran 49 combined diagnostic/matcher/existing overlap
checks (40.62 seconds), then checked 100 independently generated datasets and
176,823 pair comparisons. Pair uniqueness/determinism, total/per-source counts
and all neighbors matched its oracle across year boundaries, roles, unknowns,
signs, accounts, multiplicity and journal-history flags. It verified the new
helpers have no live callers and the current exact rule remains unchanged.
Repository hooks and whitespace checks passed for this preparatory commit.

## Integrated result

Overlap rule 2 now uses this index for inventory, exact counts, review admission,
uncapped direct-pair navigation and full posting guards. Reconciliation rule 4
retains prior rule-3 decisions as stale history without relabeling their checks.
Schema remains 16. Group metadata exposes current roots/members and actual saved
repeat edges. Each root's posting guard inspects every member's outsider edges;
one distinct decision cannot resolve another member's unreviewed relationship.
Repeat admission enforces all-pairs date eligibility and one occurrence per
source. Implicit within-group pairs cannot pretend to clear a group; direct
saved edges can be replaced atomically by an explicit distinct decision.

Posted-repeat repair and retained proof use immutable source dates/roles and
original journal accounts, preserving old effective card dates and recoverability
after later binding changes. Stale forms, failed retirement writes and malformed
history retain existing refusal/rollback behavior. No source fact or accounting
date changes merely because the matcher found a nearby candidate.

The GUI shows both dates, roles/provenance, exact account/amount and candidate
reason. Alias-to-outsider direct review is reachable, and saved root edges can
be opened through a coherent direct-pair read beyond the inventory cap. Per-choice
controls prevent implicit clearing and alias joining without clearing conflicting
edges. Original ordinary direct-repeat-to-distinct review remains usable.

Dense inventory scans classify pending/resolved pairs before constructing group
metadata for displayed rows. A 12-member group plus outsider retains 78 candidate
pairs, shows pending work first and constructs only one metadata result at a
one-row display cap, both before and after resolving every actual outsider edge.
This changes no full posting guard or count semantics.

Windows 11 AMD64/Python 3.13.15/Qt offscreen: final service integration passed
173 checks in 204.57 seconds before this metadata optimization; final wider and
existing overlap checks passed 36 in 25.90 seconds afterward. GUI/ordinary repair
interaction checks passed 32 in 24.30 seconds. Independent review passed 22
current service/GUI checks in 27.68 seconds, then reran all 36 affected service
checks after the optimization (35.84 seconds). Its separate 20-scenario/120-row
public-store oracle matched inventory counts and every root/support posting
guard, including genuine same-source occurrences. An earlier independent run
passed 99 and hit one test-only attribute typo; the corrected case is included
in the final checks. No actionable financial/provenance/UI findings remain.

Agent/primary review preserved explicit direct-edge-to-distinct behavior when
effective groups are recomputed after removing that edge. It did not add a
redundant pending-review step. The final 1180-by-760 UI was inspected offscreen
with temporary Segoe UI loading; controls and qualified source details fit.
Final V2 integration passed 512 checks, 1,107 deselected, in 317.74 seconds.
Changed-file Ruff check/format, whitespace and local links passed; repository
hooks passed after normalizing line endings in the new GUI test. No owner/native/
Intel/installed acceptance is claimed.

## Verification

Test exact window/year boundaries, differing roles, revised descriptions, changed
amount/sign/account exclusion, multiplicity, non-transitive groups, alias-only
neighbors, hidden candidates, stale forms, explicit review/reopen, posted repair,
rollback and common reports/backup. Run relevant V2 integration, Ruff/hooks and
independent review; original source dates and prior postings remain unchanged.

## Remaining work

Integrate and independently verify the rule after reviewed-binding correction;
other admitted accounting/report workflows and human/platform/release gates remain.

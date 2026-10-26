# Review nearby-date and revised-description source occurrences

Date: 2026-10-25. Roadmap IDs: V2-3/4.
Authorization: approved roadmap and continued development.
Implementation: active pure-matcher preparation; store integration serialized after binding corrections.
Automated verification: pure index and existing overlap checks passed; live integration pending.
Independent review: pure matcher complete, no actionable findings; live integration pending.
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

Primary owns pure `v2_source_overlap.py` matcher/index and new focused tests
initially. Ledger retains sole store/export ownership while binding work runs;
the subsequent integration write set will be assigned before edits. GUI work is
serialized with its existing owner. Documentation remains primary-owned.
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

## Verification

Test exact window/year boundaries, differing roles, revised descriptions, changed
amount/sign/account exclusion, multiplicity, non-transitive groups, alias-only
neighbors, hidden candidates, stale forms, explicit review/reopen, posted repair,
rollback and common reports/backup. Run relevant V2 integration, Ruff/hooks and
independent review; original source dates and prior postings remain unchanged.

## Remaining work

Integrate and independently verify the rule after reviewed-binding correction;
other admitted accounting/report workflows and human/platform/release gates remain.

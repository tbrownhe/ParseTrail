# V2 cross-source occurrence review

This is the current bounded V2 occurrence-review contract. It implements the
ledger rule that repeated source evidence must not book one movement twice.
[ROADMAP](../ROADMAP.md#v2-3) owns remaining scope; the
[packet record](work/2026-10-25-v2-source-overlap.md) holds its October 25 plan,
implementation, review and verification.

## Contract and boundaries

The fresh V2 store provides a read-only inventory of activity-row candidates
from different saved sources explicitly bound to the same financial account.
Overlap rule 2 requires the same signed exact amount and immutable source dates
within three calendar days. Activity/posting date-role differences are permitted
as candidates; source dates and assumed accounting-date candidates stay separate.
Descriptions and source locations remain available for review; matching values
never establish that two occurrences are the same movement. Equal rows within
one source retain separate occurrence identities. Changed amounts/signs, unknown
dates, unbound and otherwise nonmatching rows remain outside this bounded rule.
Period-overlap warnings describe source coverage independently of row review.
The inventory displays up to 2,000 pairs and prioritizes unresolved work so a
refresh exposes later pending candidates. Posting checks inspect the full
candidate index independently of that display limit.

Each live repeat group contains at most one occurrence from each source. Two
equal purchases in one source cannot both be folded into one row in another
source. Retained representatives and supporting repeats form one-level groups;
chained aliases and cycles are refused.
Every member must also remain pairwise date-window eligible; proximity cannot
extend through a chain of nearby dates. A root's posting checks include outsider
edges found through every supporting member. Distinct review applies to its
actual row pair only; it never certifies all edges between two groups. Direct
saved repeat edges can be replaced by explicit distinct/pending review. Implicit
within-group pairs cannot clear a different edge. Saved edge navigation uses a
coherent uncapped pair read, even beyond the ordinary inventory display limit.

An explicit review either establishes distinct occurrences or chooses one
retained row and identifies the other as repeated supporting evidence. Save the
reason and an append-only review history separately from immutable imports and
journals. A stale form must be refused after changes to relevant bindings,
review decisions or allocations. Decisions do not infer categories, accounting
dates, transfers, openings or reconciliation, and do not post any money.
The optimistic form version is separate from durable decision validity: posting
or correcting the retained row must not reactivate a supporting repeat.
Saving any review locks both rows against ordinary reassignment, including after
returning a pair to pending. Assignment dialogs enforce that history lock. An
explicit [reviewed binding correction](work/2026-10-25-v2-binding-corrections.md)
can change or clear assignments after zero active consumption and opening-anchor
checks, retaining prior mappings and invalidating connected repeat decisions
atomically. Transfer suggestion review history is also locked and invalidated
through this workflow; an account change away and back cannot revive it. A fresh
form and reason can append another occurrence decision.

Unresolved detected candidates block new cash, card and transfer allocations.
Confirmed supporting repeats cannot be allocated independently; the retained
row may be posted after its other candidate conflicts are resolved. Existing
allocations are visible in review. A row with journal history cannot be silently
excluded or reassigned. Two already-posted occurrences remain a visible conflict
until explicit posted-repeat repair retains one supported cash/card category
interpretation and retires the redundant one with an exact dated inverse.
The repair, supporting-repeat decision and immutable proof are saved atomically.
Subsequent pending/distinct/repeat review cannot revive retired money; a new
independent interpretation requires fresh posting review. Historical rows may
support a repeat only with validated complete repair and zero active allocation.
Existing category/date corrections keep their audit trail and remain possible
for already-posted retained rows.

Supported ordinary interpretations can also be explicitly withdrawn with a
reason and optimistic source-review version. Withdrawal retains all evidence and
history, releases active consumption and returns the row to pending. A later
post has a fresh identity. Whole-transfer withdrawal uses its separate event
workflow. Historical binding moves then require the explicit correction workflow
above, with a separate reason, current preview and stale-form protection. See the
[interpretation-repair record](work/2026-10-25-v2-source-interpretation-repair.md).

Conservative allocation and reconciliation reports continue to distinguish
supporting evidence from actual source-row allocations. A duplicate review does
not establish full capture, source arithmetic, complete coverage or a reconciled
balance. No missing movement becomes zero, and no balancing entry is created.

## Implementation packet

The completed [packet record](work/2026-10-25-v2-source-overlap.md) owns file/role
assignments, commands/results, review findings and remaining milestone evidence.
This heading preserves existing links without maintaining a second work log.
The [wider-matching packet](work/2026-10-25-v2-wider-source-matching.md) records
rule-2 integration and group/full-index verification. Reconciliation rule 4 keeps
prior-rule saved decisions as stale history; no old check is silently relabeled.

## Disposable review scenario

From the repository root, launch a temporary profile with two equal purchases
in one source and a possible supporting copy in another:

```powershell
$env:PYTHONPATH='.;client/src;client'
& .\client\.venv\Scripts\python.exe -m devtools.parser_engine_pilot.review_source_overlap --demo
```

Compare the locations. Retaining the single copy cannot collapse both original
occurrences into one. Date shifts up to three days can now produce candidates;
they remain explicit review, not automatic identity or accounting-date changes.
Closing the demo removes its temporary profile. This is an optional reproducible
scenario for the later integrated UX pass, without a per-feature owner gate.

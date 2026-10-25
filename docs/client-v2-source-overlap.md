# V2 cross-source occurrence review

Packet selected October 25, 2026: a bounded V2-3/V2-4 safeguard before
V2-5 account positions. This implements the existing ledger rule that repeated
source evidence must not book the same movement twice.

## Contract and boundaries

The fresh V2 store provides a read-only inventory of activity-row candidates
from different saved sources explicitly bound to the same financial account.
The first matcher requires the same signed exact amount, source date and date
role. Descriptions and source locations remain available for review; matching
values never establish that two occurrences are the same movement. Equal rows
within one source retain their separate occurrence identities. Date-shifted,
different-date-role, unbound and otherwise nonmatching rows are outside this
first matcher. Period-overlap warnings continue to describe source coverage,
independently of row review.
The inventory displays up to 2,000 pairs and prioritizes unresolved work so a
refresh exposes later pending candidates. Posting checks inspect the full
candidate index independently of that display limit.

Each live repeat group contains at most one occurrence from each source. Two
equal purchases in one source cannot both be folded into one row in another
source. Retained representatives and supporting repeats form one-level groups;
chained aliases and cycles are refused.

An explicit review either establishes distinct occurrences or chooses one
retained row and identifies the other as repeated supporting evidence. Save the
reason and an append-only review history separately from immutable imports and
journals. A stale form must be refused after changes to relevant bindings,
review decisions or allocations. Decisions do not infer categories, accounting
dates, transfers, openings or reconciliation, and do not post any money.
The optimistic form version is separate from durable decision validity: posting
or correcting the retained row must not reactivate a supporting repeat.
Saving any review fixes both rows' account bindings in this pilot, including
after returning a pair to pending. Assignment dialogs explain and enforce that
history lock. A fresh form and reason can append another occurrence decision.

Unresolved detected candidates block new cash, card and transfer allocations.
Confirmed supporting repeats cannot be allocated independently; the retained
row may be posted after its other candidate conflicts are resolved. Existing
allocations are visible in review. A row with journal history cannot be silently
excluded or reassigned. Two already-posted occurrences remain a visible conflict;
this packet does not introduce journal cancellation or rewrite earlier books.
Existing category/date corrections keep their audit trail and remain possible
for already-posted retained rows.

Conservative allocation and reconciliation reports continue to distinguish
supporting evidence from actual source-row allocations. A duplicate review does
not establish full capture, source arithmetic, complete coverage or a reconciled
balance. No missing movement becomes zero, and no balancing entry is created.

## Implementation packet

- Store and service owner: the assigned ledger agent; one writer for
  `v2_profile_store.py`, new occurrence-review services and their synthetic tests.
- Desktop owner: the assigned desktop agent; the occurrence-review dialog,
  workspace entry point and synthetic interaction tests.
- Primary: integration, this contract, TODO, component guidance and dated
  verification records. Independent integrity review inspects actual changes
  and refusal/correction paths before packet closure.
- Data: synthetic/disposable V2 profiles only. No private source access,
  1.x writes, parser/catalog changes, server work or release actions.
- Schema: the existing pre-release replacement policy applies if durable
  review storage changes the schema. Recreate earlier disposable profiles;
  do not add migration or alias machinery.
- Verification: focused inventory/review/guard tests, restart and backup/restore,
  stale and concurrent forms, allocation failure rollback, multiplicity,
  same/different-date transfers, cash/card corrections and offscreen dialog
  interactions; then the V2 integration suite and changed-file Ruff/hooks.
- Remaining milestone: consolidated human UI/UX review and separate platform/
  release gates. Automated and agent verification do not attest owner acceptance.

## Disposable review scenario

From the repository root, launch a temporary profile with two equal purchases
in one source and a possible supporting copy in another:

```powershell
$env:PYTHONPATH='.;client/src;client'
& .\client\.venv\Scripts\python.exe -m devtools.parser_engine_pilot.review_source_overlap --demo
```

Compare the locations. Retaining the single copy cannot collapse both original
occurrences into one. A shifted-date deposit is deliberately outside this matcher.
Closing the demo removes its temporary profile. This is an optional reproducible
scenario for the later integrated UX pass, without a per-feature owner gate.

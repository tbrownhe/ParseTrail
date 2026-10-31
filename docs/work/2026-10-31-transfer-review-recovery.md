# Actionable manual transfer review and correction

Date: 2026-10-31. Baseline: 8ed5740, feature/client-financial-insights.
Roadmap: V2-4/5/UX. Scope: desktop transfer workflow recovery.
Authorization: owner reports remaining Needs review rows have no usable action
and confirmed-event withdrawal/replacement controls are grey after earlier manual
matching. Implementation: complete. Automated verification: 151 distinct focused/
integration cases pass across runs plus pinned-runtime checks. Native UI and
independent review: passed with no material blocker. Owner acceptance: pending
integrated use. Release authorization: none.

## Scope and controlling decisions

Diagnose with public synthetic/disposable profiles, including mixed manually
posted and planner-posted history. Existing owner demo/archive/profile/settings
remain read-only; no private financial content is needed. All development writes
are disposable. Public runtime packaging may read the existing schema marker
and preserve the same review profile. Never reset or withdraw owner matches by
tools, execute the owner launcher, delete reviewed history or perform release.

Actual code and independent reproduction show no origin-specific correction
lock. Plan intentionally excludes unresolved candidates from automated Include,
but its manual review path is hidden behind All matches. Confirmed-event actions
require a selected active event, current basis and a reason; replacement also
needs a different eligible loaded pair. The required reason is only explained
by a placeholder, while status tells users to load replacements even for undo.

Add direct manual review from a Needs review/Alternative row, with cached
same-group candidates, both source accounts/descriptions/dates/qualifications,
clear blockers and one explicit pair-posting confirmation using existing ledger
services. Do not loosen the planner's automatic eligibility or silently choose
a tie. An all-Needs-review state must present a discoverable enabled next step.
Keep All matches and focused repayment/history routes available.

Make correction prerequisites persistent and state-specific: visibly group
Correct or undo selected transfer, label Reason (required), and explain select
active event / enter reason / load alternatives / choose different eligible pair
as applicable. Preserve reason gating, explicit whole-event confirmation,
inverse entries at original dates, exact consumption, history and fresh checks.
No destructive reset, bulk undo or accounting-policy/schema change is included.
Manual category interpretations are separate from transfer history and must
retain their existing source-interpretation correction workflow.

Freeze the available group, scope, basis, preferences, profile and initial note
before manual review. Capture the pair/note deliberately chosen inside that
frozen review on its final button. Other confirmations freeze their pair/event,
reason and context before opening. After modal return refuse changed context
rather than reading another main-window selection or writing another profile.
No per-selection database reads or new GUI-thread financial queries. Preserve
asynchronous latest-result handling, cancellation and worker shutdown safety.

## Ownership and design

UI/UX owns read-only preimplementation design and native critique. Desktop owns
`gui/v2_transfer_review.py`, `gui/v2_transfer_plan.py`, new targeted recovery tests
and necessary existing planning/correction GUI adaptations. Integrity independently
reviews source and actual public mutation/refusal paths. Primary owns scope,
contracts/planning, integrated checks, this record, commits and runtime handoff.
One writer per file; no recursive delegation or specialist commits.

Design was reviewed before implementation. Observable criteria: user opens a
ties-only Plan and can find manual resolution, compare the relevant candidates,
inspect both source effects and confirm one selected pair; the remaining graph
refreshes. Manual and automated confirmed matches expose the same correction
steps. Reason requirements are visible at 1024 and inactive/complete-manifest/
no-alternative/date-blocked states explain their own limits. Cancel preserves DB
bytes, withdrawal restores both movements through dated inverses, and replacement
is all-or-none. Empty, pending, stale, failure and recovery paths stay honest.

## Verification and results

Independent public reproduction confirms an older manual transfer can be
withdrawn after planner postings: Cancel preserves exact DB bytes; confirmed
withdrawal preserves originals/source bytes, appends dated inverses and releases
both rows while the planner event remains active. A separately authored category
interpretation consumes a source row but creates no TransferEvent; its existing
source-interpretation withdrawal restores eligibility. Native desktop read-only
inspection reproduces both origins' hidden-reason gating and different-pair
replacement requirement with unchanged profile hash. Evidence:
`scratch/ux-audit-transfer-recovery-20261031/` and
`scratch/transfer-recovery-investigation-20261031/`.

Independent review additionally reproduced a material legacy confirmation-scope
bug: switching the workspace from displayed disposable A to an identical clone B
inside the withdrawal question allowed B to be changed because event ID and basis
were identical. All question-based actions in this panel must freeze and recheck
the profile/preferences/generation context and pass the captured profile into
the writer. Both profiles must remain unchanged after a context switch; the
financial basis alone cannot distinguish identical copies. Evidence:
`scratch/ux-audit-transfer-recovery-20261031/cross-profile/`.

The same guard must bind the loaded snapshot even if the workspace changes
before a click, not merely capture the new path at click time. Independent
before-click and during-question clone checks now preserve both hashes. Profile
and policy changes refuse the old context, then reload; the profile header must
also update when the accepted new snapshot is published so subsequent actions
cannot show the old profile name while operating on the new one.

### Implemented and independently verified

The Plan page exposes Review this pair manually and highlights a reviewable row
when no automatic pairs remain. Its read-only comparison uses the cached complete
component, with separate sent/received description columns, qualified dates,
accounts, amount and full supporting details. The user can choose a different
candidate and edit the prefilled note inside that review. The final button freezes
that deliberate result; later main-window or dialog changes cannot substitute
another pair or note. Estimated-date blockers remain explicit and never enable
the global policy automatically. A successful individual posting refreshes the
graph, removing competing edges and allowing newly unique pairs to be prepared.

Confirmed events visibly groups Correct or undo selected transfer and labels
Reason for correction (required). Live instructions distinguish missing reason,
unloaded alternatives, no different eligible pair, blocked dates, inactive history
and complete settlement manifests. Both posting origins use the same actions.
Withdrawal keeps the original dated entries, adds inverses and releases the whole
source allocation; replacement remains atomic. No ledger/service/schema change.

Loaded snapshot profile/preferences now bind all five question-based actions and
cached-event settlement inspection. Both before-click and during-modal switches
to identical clones refuse without writes. Accepted reloads synchronize the
visible profile header; a new explicit action can then affect only the newly
displayed profile. Independent two-step verification preserves A while the new
explicit B operation changes B. Independent stale SQL, gap generation, preference,
out-of-group result and actual date-blocked acceptance probes also pass.

New recovery tests: **21 passed in 23.59s**; independent rerun **21 passed in
24.98s**, plus **13 existing correction GUI tests in 15.86s**. These cover all five
legacy question actions against profile switches before and during confirmation,
loaded policy changes, frozen manual pair/note, cancellation and cached selection
without DB reads, mixed manual/planned history, guarded settlement launch, unknown
source-description qualification and the profile-header transition.

Independent native Windows UI/UX passed the actual mixed-history journey at 1024
and 1250 with long account labels: direct manual action discoverable, both source
descriptions distinguish tied rows, Cancel/Return leaves exact bytes unchanged,
a deliberately different clicked pair posts exactly once with its note, and the
remaining graph becomes Ready. Manual/planned correction reasons and next steps,
actual replacement/withdrawal No/Yes, no-alternative/inactive/full/date-blocked
states and full-manifest inspection all pass. Focused loan pending, posted and
missing-counterpart routes remain correct. Four row/note changes with DB opening
forbidden pass. Primary inspected actual 1024 manual and correction screenshots.
Evidence: `scratch/transfer-recovery-ux-52916193/`,
`scratch/focused-loan-recovery-58fc9a00/` and
`scratch/missing-focused-plan-e542daff/`.

Independent integrity review has no remaining material blocker. Five actual
new-entry shutdown probes distinguish unconfirmed modal quit/destruction (exact
no-write) from confirmed ordinary writes (drain to one durable outcome, including
forced destruction/no-event-loop exit). Visible app quit during an ordinary write
waits for the saved result, then exits after a subsequent quit, preserving the
existing Close contract. Evidence:
`scratch/ux-audit-transfer-recovery-20261031/` including
`manual-lifecycle-verified-result.json`.

Primary integration covers existing ordinary transfers, planning, asynchronous
review, correction GUI/core, batch/history performance, loan-register review,
full settlements and workspace: initial **128 passed / 2 failed in 150.35s**.
Both failing settlement tests still assumed synchronous transfer reads/writes and
a numeric tab index from before Plan was added. Updated those tests to wait for
actual worker completion and use the Confirmed events widget, preserving every
financial/date/inverse assertion. The whole settlement GUI module then passed
**11 tests in 13.30s**; no product change was needed for those failures. Together
the matrix covers 130 legacy integration cases plus 21 new recovery cases:
151 distinct passing cases. One ordinary-transfer test only needed its old empty
state copy expectation updated. Changed Python lint/format and diff checks pass.

### Same-profile public runtime handoff

New immutable launcher:
`scratch/archive-demo-f92c025/runtime-updates/20261031-transfer-review-recovery/Open-updated-demo.cmd`.
It copies 286 public code/resource files, reads schema marker 22 only, and retains
the existing demo profile, catalog, preferences and home. Earlier runtimes and
saved owner history are preserved. The owner launcher was not executed and no
owner matches were reset, posted or withdrawn by tools. Final committed-source
byte verification is recorded beside the launcher after committing.

Pinned-module disposable-profile check seeds an earlier manual transfer, a later
planned transfer and four tied candidates. Actual final buttons verify manual
Cancel preserves exact bytes, a deliberately different candidate posts exactly,
the remaining tie becomes Ready, and withdrawing the earlier manual match retains
the later planned event and all original source bytes. Its dated inverses release
the correct original rows. Evidence:
`scratch/transfer-recovery-pinned-e1c0abdb/result.json`.

No owner data was posted or changed. Native/offscreen agent checks do not attest
owner, macOS/Intel, installed-release, scaling or screen-reader acceptance. No
archive-sized timing or memory measurement is claimed; browsing the new review
uses cached data. No ledger policy/schema change, destructive reset, signing,
deployment, publication or daily-profile activation was performed.

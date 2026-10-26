# Work records

This is the standard home for substantial packet plans, completed work,
verification and dated decisions. [ROADMAP](../../ROADMAP.md) owns priorities,
scope and release gates; [TODO](../../TODO.md) points to selected work. Current
contracts own lasting behavior. Start with those documents, not historical logs.

## Current records

| Record | Roadmap scope | Implementation / evidence |
| --- | --- | --- |
| [Explicit profile startup](2026-10-25-v2-profile-startup.md) | V2-6/7 | Completed development and independent review; New/Open/Restore, safe configuration and switch-failure recovery. |
| [Transfer review/correction](2026-10-25-v2-transfer-corrections.md) | V2-3/4/5 | Completed development and independent review; context-scoped suggestions, whole withdrawal/replacement and validated history. |
| [Workspace guidance/build identity](2026-10-25-v2-workspace-guidance.md) | V2-6/7 | Completed small primary-verified change: local workflow help and unchanged pilot version disclosure. |
| [Correct reviewed openings](2026-10-25-v2-opening-corrections.md) | V2-4/5 | Completed development and independent review; append-only retirement/revision and integrated report/export history. |
| [Recover embedded source originals](2026-10-25-v2-source-recovery.md) | V2-3/6 | Completed development and independent review; originals recover without catalog/import path, preserving profile bytes. |
| [Durable reconciliation history](2026-10-25-v2-reconciliation-history.md) | V2-4/5 | Completed development and independent review; saved/current/live cutoffs and recoverable pending states. |
| [Account positions and history](2026-10-25-v2-account-positions.md) | V2-5, DEC-1/2/3 | Completed development and independent review; owner scope decisions recorded; integrated UX remains open. |
| [Initial-release readiness audit](2026-10-25-v2-readiness-audit.md) | P2-3/4/5, V2-3/6/7 | Completed read-only code and synthetic verification audit; remaining development and external gates distinguished. |
| [Roadmap and instruction consolidation](2026-10-25-roadmap-consolidation.md) | DOCS-1, cross-cutting documentation | Complete; preservation, links, configuration and independent pickup review recorded. |
| [Cross-source occurrence safeguard](2026-10-25-v2-source-overlap.md) | V2-3/4 | Completed development; automated/independent review recorded; integrated human UX remains open. |

Use `YYYY-MM-DD-<packet>.md`. One record can begin with the packet plan and
become its closeout; update it when correcting its evidence. Put implementation,
automated verification, independent review, actual owner acceptance and release
authorization in separate fields. Use `not performed`, `pending` or `not applicable`
with the reason rather than treating an omitted check as passed.

For small changes, a concise dated entry in an appropriate existing work record
can be sufficient. Do not create a separate plan, handover, acceptance report and
decision log for the same packet. Record useful UX scenarios here for the later
integrated milestone; a new feature alone does not create a human gate.

## Packet template

```markdown
# <Outcome>

Date: YYYY-MM-DD. Roadmap IDs: <IDs>. Branch/runtime: <scope>.
Authorization: <owner request/decision and limits>.
Implementation: planned | active | complete | incomplete.
Automated verification: <result or not performed>.
Independent review: <result or not performed and why>.
Owner acceptance: <actual result, pending milestone, or not applicable>.
Release authorization: <explicit result or not authorized/not applicable>.

## Scope and controlling decisions
Outcome, non-goals, contracts, owned files/roles, permitted data/write boundary,
financial claims and meaningful verification. Capture unresolved decisions and
their dependent work; retain any actual owner decision with its date/basis.

## Result and review
Behavior/files changed, reviewed code reference or baseline/diff, failure paths,
review findings/resolution, and preserved unknowns. Update lasting contracts.

## Verification
Exact commands, platform/runtime, results and untested limits. Link committed
synthetic checks; keep private paths, data, secrets and raw reports out of Git.
Distinguish source replay/parity, offscreen tests, native checks and human review.

## Remaining work
Roadmap IDs, actual blockers, pending UX/platform/release gates and reproducible
synthetic scenarios. Link back from the roadmap where relevant and clear TODO.
```

Do not require a record to contain its own eventual commit hash. Identify the
reviewed baseline/diff or implementation commit when available; Git retains the
record's history. Reporting a commit requires that a commit was actually made.

## Historical records

The October 25 snapshots in [archive](archive/) preserve wording from before
this consolidation. Relative Markdown links were rebased; historical evidence,
decisions and acceptance were not promoted to current scope. Archived prose may
contain superseded rules and unresolved status contradictions.

| Original entry point | Archived record |
| --- | --- |
| [Earlier TODO](../../TODO.md) | [Roadmap/work history snapshot](archive/2026-10-25-TODO.md) |
| [Engineering acceptance index](../engineering-acceptance.md) | [Earlier acceptance record](archive/2026-10-25-engineering-acceptance.md) |
| [Workflow handover](../agent-workflow-handover.md) | [Historical handover](archive/2026-10-25-agent-workflow-handover.md) |
| [Workflow proposal](../agent-workflow-proposal.md) | [Installation/review history](archive/2026-10-25-agent-workflow-proposal.md) |
| [Client development review](../client-development-review.md) | [Historical review/proposals](archive/2026-10-25-client-development-review.md) |
| [Cutover contract](../client-v2-cutover.md) | [Earlier cutover plan/log](archive/2026-10-25-client-v2-cutover.md) |
| [Single-store contract](../client-v2-unified-store.md) | [Earlier schema/design history](archive/2026-10-25-client-v2-unified-store.md) |
| [Ledger contract](../client-ledger-contract.md) | [Earlier ledger audit/migration history](archive/2026-10-25-client-ledger-contract.md) |
| [Parser contract](../client-v2-parsing.md) | [Earlier parser plan/log](archive/2026-10-25-client-v2-parsing.md) |
| [1.x action inventory](../client-v2-menu-inventory.md) | [Earlier action inventory](archive/2026-10-25-client-v2-menu-inventory.md) |
| [Evidence-storage decision index](../client-v2-evidence-storage-proposal.md) | [Original approved storage decision](archive/2026-10-25-client-v2-evidence-storage-proposal.md) |
| [Upstream review index](../client-v2-upstream-boundary-review.md) | [Pre-store boundary review](archive/2026-10-25-client-v2-upstream-boundary-review.md) |
| [Preservation inventory index](../client-v2-preservation-inventory.md) | [Legacy preservation research](archive/2026-10-25-client-v2-preservation-inventory.md) |
| [Parser family map](../client-v2-parser-inventory.md) | [Family coverage and operation-cost history](archive/2026-10-25-client-v2-parser-inventory.md) |

Existing release/platform runbooks and named historical native acceptance files
retain their original locations. They are linked evidence, not alternate work
queues. New packet records belong here; do not append new entries to the old
acceptance monolith or generate another current-work handover.

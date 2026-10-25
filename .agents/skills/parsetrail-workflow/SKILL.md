---
name: parsetrail-workflow
description: Coordinate bounded ParseTrail engineering packets across statement evidence, ledger/profile services, desktop workflows, and independent verification. Use for substantive implementation, integration, or repository review; simple edits need no role ceremony.
---

# ParseTrail engineering workflow

Keep one primary agent responsible for scope, owner conversation, integration
and acceptance. Use specialists only when their deliverable adds value and the
session permits delegation. If delegation is unavailable or prohibited, perform
the relevant checks in the primary agent.

## Establish current behavior

Read `README.md` and `development.md` for orientation/setup, then `ROADMAP.md`
for milestones, scope and release gates and `TODO.md` for selected work. Read the
linked packet record and relevant component contract. For V2, use
`docs/client-v2-cutover.md` and `docs/client-v2-unified-store.md`; add the ledger
or parsing contract for those claims. Use [the code and verification map](references/code-and-checks.md)
selectively. Dated records live under `docs/work/`; the old acceptance monolith,
handovers and proposals are historical indexes, not startup instructions.

Check branch, working-tree changes, runtime entry point and current code.
Distinguish published 1.x, isolated historical experiments and the fresh V2
workspace. Current owner decisions supersede old migration/category preservation.
Do not repeat implemented slices or select a task from an old checkbox. If no
packet is selected, use the current user request to establish scope; recommended
queue entries alone do not authorize product implementation.

## Define one work packet

State the outcome, non-goals, controlling decisions, relevant symbols, owned
files, data/write boundary, financial claims, verification and remaining gate.
For substantial work, create or update one `docs/work/YYYY-MM-DD-<packet>.md`
record using `docs/work/README.md`. It begins with scope and becomes the same
packet's closeout; do not create separate plan/acceptance/handover logs. Small
edits can use a concise entry in an appropriate existing record.

Make system and interaction design choices within the selected scope and agreed
product/accounting contracts autonomously. Ask the owner only when an unresolved
decision changes agreed scope or financial meaning and cannot be settled from
those contracts. Present exact synthetic examples and alternatives, then continue
independent work that does not assume an answer. A new feature, a substantial UI
change or an ordinary architecture choice does not itself require owner review.
Existing authorization carries forward and does not need to be requested again.

## Route by deliverable

| Agent | Use when | Required output |
| --- | --- | --- |
| `evidence` | Declarations, extraction, source models, routing, workers or family parity change. | Evidence changes, locations/provenance, bounded refusal cases, tests and capture limits. |
| `ledger` | Accounting, imports, profile schema, backup/recovery or common report reads change. | Exact sign/date examples, atomicity/idempotence effects, unknown states and tests. |
| `desktop` | A desktop review, report or import interaction changes. | Functional GUI behavior, agent verification, offscreen checks and notes for the integrated UI/UX pass. |
| `integrity` | Independent financial/provenance/persistence review is warranted. | Findings with locations, failing scenarios and remaining verification limits. |
| `acceptance` | Integrated checks or native/platform/release evidence need a separate pass. | Exact commands, platform/results, verification limits and milestone review readiness when assigned. |
| `service_web` | A separately scoped service, dashboard, website or API task is selected. | Interface/privacy implications, implementation if authorized, and isolated checks. |

Assign one writer per shared file or schema. In particular,
`v2_profile_store.py`, `source_evidence.py`, `ledger.py`, shared declarations and
roadmap/contracts need explicit ownership. A ledger/profile packet has one
store writer; an evidence or desktop agent requests additional service edits
through the primary. Parallelize disjoint work and read-only investigation.
Do not start a full team by default or let specialists recursively delegate.

Give each specialist the packet outcome, exact write set, required contracts,
allowed data, verification and return format. Primary retains shared ROADMAP, TODO,
contract and packet-record ownership. Specialists report boundary changes
rather than silently expanding their assignment. Use the existing checkout
unless a task actually needs isolation; do not switch branches under other work.

## Preserve ParseTrail boundaries

- Normal finance data and ML remain local. Keep live 1.x databases, archives
  and statements read-only; write only synthetic/disposable profiles for
  development. Use only specifically authorized confidential fixture inputs.
  Do not inspect secrets or load root `.env` merely to discover data. Keep
  private paths, source contents, account identities and reports out of Git
  and routine output. Decrypted server contributions stay in process memory.
- V2 uses one authoritative fresh SQLite profile. Do not attach the legacy
  prototype store, add 1.x aliases/migrations or write the old profile. Check
  the actual pre-release revision; recreate disposable pilots when its approved
  schema changes. Released 2.x evolution follows its migration contract.
- Preserve exact money, typed dates and original source locations/provenance.
  Parser output and account matching do not authorize postings. Keep unknown
  values unknown, balance entries exactly, allocate evidence once, preserve
  correction history and never invent a balancing movement.
- Review transfer/card-payment double counting, separate source dates and
  clearing, opening validity, stale review inputs and liability display signs.
  Keep capture, source arithmetic, allocation, interpretation, reconciliation,
  period coverage and freshness independently visible. Reports and exports
  cannot claim more than the common ledger query establishes.
- Keep JSON operations finite and decoders behind fixed bounded workers.
  Preserve signed-catalog admission and rollback/atomic activation checks.
  Test-signing with ephemeral fixture keys does not grant production key access.
- Current client pilots stay on `feature/client-financial-insights`. A required
  server interface gets a reviewed design and the documented separate-branch
  handoff after accepted client integration. A separately authorized service/web
  task follows its own branch and contracts. Do not bump versions, sign with
  production keys, activate daily profiles, deploy or publish without that scope.

## Implement, review and close

Establish the service/data contract and meaningful synthetic checks before UI
integration. Reuse pure ledger validation and the V2 store rather than copying
legacy services into a second runtime. Keep prompts/progress in GUI adapters.

For changes to financial semantics, stored evidence, profile integrity or report
claims, get an independent integrity review when delegation is permitted;
otherwise make an explicit separate review pass and disclose the limitation.
Review the actual integrated changes, including failure/cancellation/correction
paths. Resolve findings and rerun affected checks. Do not infer correctness from
an agent's success summary alone.

Run focused checks while editing and the relevant integration suite at the
packet boundary. Parser work may need tests under `devtools/` in addition to
`client/tests`. Record exact commands and tested platform. Use changed-file Ruff
and repository hooks as applicable; keep unrelated files untouched.

### V2 UI review policy

Design and implement a usable first functional UI within the agreed contracts,
verify it with meaningful automated interaction/service checks and agent review,
fix observed problems, and continue to the next authorized packet. Include
layout, wording, pending/failure states and truthful financial claims in agent
review; deferring human polish review is not permission to ship broken UI.
Neither a new feature nor a small or substantial UI change requires a per-feature
human walkthrough, screenshot approval or acceptance checkpoint by default.

Consolidate human review into a later integrated UI/UX milestone covering the
daily workflow across import, account binding, review/correction, reports and
profile backup/reopen. Keep useful UX observations and reproducible scenarios as
work proceeds; prepare a disposable end-to-end walkthrough when that milestone
is reached, rather than requiring a new owner demo for each packet. An explicit
owner request can select an earlier human review.

Ask for human input on unresolved product/accounting decisions that the agreed
contracts cannot settle, or a specifically identified native/platform, release
or live-profile gate that requires owner action. Run available native checks
autonomously; a platform check does not itself require a human. Name the actual
gate and stop only its dependent work; pending consolidated UX review does not
block unrelated development.
Windows/Intel decoder, packaging and installed/offline checks remain required
where applicable. Record the platform actually tested; an offscreen pass or
sandbox window never becomes owner native acceptance. When human native review
is due, the owner launches the prepared demo in their own session.

This policy supersedes older per-slice GUI acceptance language for ongoing V2
development. Preserve earlier acceptance records as history. Complete an
implementation packet after its automated/agent checks pass, and track pending
integrated human review or release acceptance at the appropriate milestone.
This engineering review policy does not remove the application's explicit user
confirmation of account bindings, source assertions or accounting postings.

Return behavior, changed files, commands/results, review findings/resolution,
limits and the precise remaining decision. Distinguish implemented, automated
verified, independently reviewed, owner accepted and release authorized.
Update the packet record with exact commands/platform/results, review findings,
actual owner decisions/acceptance and untested limits. Update affected contracts
and ROADMAP status/dependencies, link the record, and clear the selected TODO
entry. Do not copy validation narratives into ROADMAP/TODO, append new work to
historical acceptance archives, or generate another current-work handover.
Record substantive owner decisions in that packet record and apply their current
rule in the relevant contract/roadmap. Label agent verification separately from actual owner
acceptance. Close implementation work
when its development checks pass while leaving aggregate UX/release milestones
open until their own gates pass. Report a commit ID only if a commit was made
within the authorized task. Do not equate a pilot with release.

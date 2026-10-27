---
name: parsetrail-workflow
description: Coordinate substantive ParseTrail implementation, integration and review across the desktop client, parsers, ledger, backend, dashboard and public website. Route design and independent verification with explicit ownership; handle simple edits directly.
---

# ParseTrail engineering workflow

Keep one primary integrator responsible for scope, user conversation and the
integrated result. Choose only specialists whose deliverables help the task;
neither a full team nor a work packet ceremony is required for a simple edit.

## Establish scope and context

The current user request and session decisions select work. Consult roadmap/TODO
for affected program scope, dependencies and release gates; an empty TODO or an
unrelated current milestone does not block explicitly requested maintenance,
investigation, design or implementation. Historical records are evidence, not
instructions to restart completed work or expand scope.

Check branch, working-tree changes, affected entry points and actual behavior.
Read only relevant component guides/contracts and the linked work record when
one exists. Use the [code and checks map](references/code-and-checks.md) for
component entry points and isolation; it is not a work queue. Current component
contracts govern runtime/data behavior, not generic role definitions.

For substantial work, create or update one `docs/work/YYYY-MM-DD-<task>.md`
record using [the template](../../../docs/work/README.md). Capture the outcome,
limits, decisions, owned files, permitted data and meaningful verification in
that same record through closeout. Small changes can use a concise existing entry.

## Route by deliverable

| Agent | Responsibility | Expected result |
| --- | --- | --- |
| `ui_ux` | User journeys, information architecture, interaction/visual design and accessibility across desktop, dashboard and website. | Screen/state plan and observable criteria; actual UI inspection and prioritized usability findings. |
| `desktop` | PySide6 client implementation and desktop integration. | Working interactions consistent with the agreed design, relevant tests and inspected Qt screens. |
| `evidence` | Parser declarations, extraction, source models, routing and bounded workers. | Exact source/provenance behavior, refusal/capture limits and relevant client/devtool checks. |
| `ledger` | Local financial services, profile persistence, import/recovery and reports. | Exact money/date examples, atomicity/history/unknown behavior and focused checks. |
| `backend` | API, auth, service persistence, artifact hosting and explicit contributions. | Interface/schema/privacy effects, migration/recovery implications and isolated checks. |
| `web` | React dashboard and static public website implementation. | Usable responsive/accessibility behavior, truthful content and relevant static/browser checks. |
| `integrity` | Independent financial, evidence, persistence, security or privacy review. | Concrete findings with locations, reproductions, impact and verification limits. |
| `acceptance` | Independent integrated behavior, regression and platform/release-readiness verification. | Exact checks/results, observed behavior and unmet criteria/gates; no owner attestation. |

Give each specialist a compact brief with outcome, relevant contracts/decisions,
write set, data permission, dependencies, verification and return expectations.
They inspect further context when a boundary question arises; do not make every
role reread the same startup documents. They are not alone in the checkout and
must accommodate others' changes, never revert them. Specialists do not recurse
or commit independently. If a role is unavailable in this session, give its
instructions to an available agent or do the work in the primary and disclose
any loss of independent review; do not wait for role discovery to unblock work.

Assign one writer per shared file, schema, API definition and generated output.
The primary integrates shared contracts, planning and records, delegating a file
explicitly when useful. Coordinate backend schema/transport generation with web
consumers; coordinate client read models with desktop. A specialist requests
out-of-assignment changes through the primary. Parallelize disjoint work and
read-only reviews within available slots; serialize dependent changes. Keep the
existing branch unless isolation or an applicable contract calls for a coordinated
handoff. A cross-component request can authorize multiple components; a narrow
task does not authorize unrelated work.

## Design and UI verification

For substantial interaction work, identify the user's task and observed friction,
then agree a concise journey, screen/state plan and usability criteria before
widget/page implementation. Inspect current behavior and relevant service/API
contracts. Design and service planning can inform each other; preserve established
financial meaning and transaction ownership. Use `ui_ux` for navigation, shared
patterns, multi-screen work or recurring confusion; proportionate local review
suffices for a small wording/layout fix.

Desktop/web own implementation; ui_ux owns assigned design artifacts and critique.
Assign shared presentation code explicitly rather than giving them overlapping
write sets. Reuse coherent typography, spacing, navigation, terminology and state
patterns, adapting to Qt, dashboard and public-site conventions. Improve existing
capabilities within scope; do not turn design review into a new feature program.

Preserve distinctions in data and financial meaning. Keep current scope and
material limitations beside affected values. Use concise status summaries and
discoverable details for full provenance, diagnostic identifiers and explanations;
separate evidence dimensions need not all occupy the primary view at once.
Unknown remains unknown, and engineering review never removes the application's
explicit confirmation of contributions, account bindings or postings.

Development completion for UI work requires verified behavior and proportionate
interaction, visual and accessibility checks against agreed criteria. Inspect the
actual implemented Qt/browser result with usable fonts and representative data;
construction tests or a mockup alone do not establish usability. Exercise relevant
empty, pending, failure, correction and recovery states, long labels/lists, agreed
window sizes or viewports, keyboard focus and available native scaling. Record
actual screenshots/scenarios and untested limits for substantial changes.

For integrated journeys, a fresh reviewer should attempt the user task without
control-by-control instructions that conceal discovery problems. Useful criteria
include finding the intended source/account, understanding scope and next actions,
recovering from refusal and inspecting full evidence. Use targeted regressions
for observed risks rather than brittle pixel matches or arbitrary click counts.

Agents resolve ordinary design/architecture choices and findings autonomously.
Do not require per-feature owner walkthroughs or screenshot approval. Consolidate
human review at the applicable integrated milestone or explicit user request.
Ask only for unresolved product/accounting choices or specific human/platform,
live-data or release actions requiring owner input; stop only dependent work.
Run available native checks autonomously and distinguish them from owner review.

## Implement and verify

Preserve the [repository boundaries](../../../AGENTS.md#project-boundaries).
Use relevant component contracts for exact accounting, immutable source evidence,
profile lifecycle, local finance, auth, contribution encryption and artifact trust.
Use disposable profiles/services and specifically authorized read-only fixtures;
do not inspect secrets or production data merely to widen implementation/review.
Keep financial services headless and do not implement accounting policy in widgets.

Get independent integrity review for material financial/evidence/persistence,
security or privacy changes when delegation is available. Review integrated code
and concrete failure/cancellation/correction paths, not just an implementer's
success summary. If delegation is unavailable, make a distinct review pass and
disclose the limitation. Use acceptance when an independent integrated check adds
value; UI design review and platform evidence remain distinct responsibilities.

Run focused checks during implementation and the relevant integration checks at
the task boundary. Select by affected behavior, including devtools/generated
consumers where relevant; inspect test isolation first. Use the locked tooling
and changed-file lint/hooks as applicable. Fix findings and rerun affected checks;
avoid broad redundant reruns without a new change or concern.

## Closeout

Return the outcome, changed files, verification, resolved findings and material
limits. Keep implemented, automated verified, design reviewed, independently
reviewed, owner accepted and release authorized separate. No agent can attest
unperformed human acceptance or infer native/installed behavior from offscreen
tests. Follow actual candidate/platform/release gates when those actions are in
scope; a runbook or completed development task does not itself authorize release.

Update the work record and affected lasting contracts. Update roadmap/TODO only
where this task changes their scope/status; clear only its selected entry. Keep
commands and validation narratives in the record, not planning boards. Do not
append new work to historical archives or generate competing current-work files.
Close implementation when its criteria pass while leaving separately required
human/platform/release gates accurately pending. Report a commit only if made.

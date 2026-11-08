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
| `ui_ux` | Integrated user journeys, information architecture, interaction/visual design and accessibility across desktop, dashboard and website. | Journey/screen/state plan and observable criteria; actual UI inspection, prioritized usability findings and rechecks. |
| `desktop` | PySide6 client implementation and desktop integration. | Working interactions consistent with the agreed design, relevant tests and inspected Qt screens. |
| `evidence` | Parser declarations, extraction, source models, routing and bounded workers. | Exact source/provenance behavior, refusal/capture limits and relevant client/devtool checks. |
| `ledger` | Local financial services, profile persistence, import/recovery and reports. | Exact money/date examples, atomicity/history/unknown behavior and focused checks. |
| `backend` | API, auth, service persistence, artifact hosting and explicit contributions. | Interface/schema/privacy effects, migration/recovery implications and isolated checks. |
| `web` | React dashboard and static public website implementation. | Usable responsive/accessibility behavior, truthful content and relevant static/browser checks. |
| `integrity` | Independent financial, evidence, persistence, security or privacy review. | Concrete findings with locations, reproductions, impact and verification limits. |
| `acceptance` | Independent integrated behavior, task discovery/comprehension, regression and platform/release-readiness verification. | Separate functional and uncoached task results, observed misunderstandings and unmet criteria/gates; no owner attestation. |

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

Translate the feature request into the user's intended outcome and inspect current
friction and relevant service/API contracts. For substantial interaction work,
establish a concise end-to-end journey, screen/state plan and observable usability
criteria before dividing UI implementation assignments. Include entry, decisions,
result and correction/recovery across affected existing features. Examine whether
current navigation and screen boundaries serve that journey. Use `ui_ux` for
navigation, shared patterns, multi-screen work or recurring confusion; a small
wording/layout fix needs proportionate local review.

Within scope, ui_ux owns the integrated interaction model and may propose combining,
reordering or restructuring existing screens. Desktop/web own implementation;
assign shared presentation code explicitly without overlapping writers. The primary
resolves design/engineering conflicts and coordinates necessary read-model changes.
Preserve financial meaning, transaction ownership and component authorization;
route new capabilities or changed accounting policy through the primary rather
than expanding scope through design review.

Define criteria for discovery and comprehension separately from functional success:
can the reviewer identify account/period/scope, what needs attention and why, the
next action, the effect of confirmation, and what a result includes or leaves
unknown? Add relevant recovery and repeated-use criteria. Reuse coherent typography,
spacing, table density, amount/date formatting, terminology, statuses, focus and
action placement, adapting to each surface.

Preserve distinctions in data and financial meaning. Lead with the answer or task,
keep scope and material limitations beside affected values, then make next actions
clear and supporting detail discoverable. Use concise status summaries with full
provenance, diagnostic identifiers and explanations available through details;
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

For integrated journeys, give a fresh reviewer the goal and permitted data, without
control-by-control instructions or an implementation walkthrough. Record completion,
wrong turns, assistance, misunderstandings of results and recovery; if coaching or
prior implementation knowledge was needed, qualify the discovery evidence. Keep
these attempts separate from scripted functional checks. Agent inference is not
evidence that an unfamiliar person will understand the UI. Use targeted regressions
for observed risks rather than brittle pixel matches or arbitrary click counts.

The primary owns the disposition of UX findings; ui_ux rechecks affected interactions
after fixes. Close the loop against the original task and observed friction, not
just a checklist of edits or test counts. Significant inability to discover, complete,
understand or recover from the task leaves that usability outcome incomplete until
resolved or explicitly dispositioned with impact and remaining work. Do not silently
defer it because functional tests pass. Keep technical completion and demonstrated
usability distinct in the work record.

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

# ParseTrail repository guidance

ParseTrail includes a local-first personal-finance desktop client, a FastAPI
account/artifact/explicit-contribution service, a React dashboard and a static
public website. Ordinary financial data and analysis stay local.

## Scope and context

Use the current user request and existing session decisions to establish scope.
Read `README.md` for unfamiliar project context and `development.md` for setup
and isolation, then the relevant component guides/contracts and actual code.
Consult [ROADMAP.md](ROADMAP.md) and [TODO.md](TODO.md) when work affects planned
product scope, dependencies or release gates. They do not restrict ordinary
maintenance, investigation or explicitly requested work to the current milestone.
Historical plans and queue recommendations do not select additional work.

Use [parsetrail-workflow](.agents/skills/parsetrail-workflow/SKILL.md) for substantive
implementation, integration or repository review. It owns role routing, design
review and verification; handle simple edits directly. Read references selectively.
Keep current runtime and component contracts separate from dated work evidence.

For substantial work, use one [work record](docs/work/README.md) for scope,
decisions and verification. Update affected contracts and planning status when
applicable; clear only the TODO entry belonging to that task. Do not create
parallel plan/acceptance/handover logs or append new work to historical archives.

## Team and ownership

Subagent use is authorized within the user's task when it adds value and the
session permits it. Use the smallest useful team from [.codex/agents](.codex/agents/):
`ui_ux`, `desktop`, `evidence`, `ledger`, `backend`, `web`, `integrity`, `acceptance`.

- One primary integrator owns the user conversation, scope, cross-component
  contracts and integrated result. Specialists do not recursively delegate.
- Give specialists a compact brief: outcome, relevant decisions/contracts,
  explicit write set, allowed data, verification and expected return. They need
  not repeat broad repository orientation for a narrow assignment.
- Assign one writer per shared file/schema/generated output. Parallelize disjoint
  implementation and read-only investigation; serialize dependencies. Never
  revert others' edits or switch a shared checkout's branch under ongoing work.
- Use independent review for material financial, evidence, persistence, security
  or privacy changes. If delegation is unavailable, make a separate review pass
  and disclose that limitation. Routine small work does not need a full team.
- Delegation inherits existing permissions; it does not authorize private-data
  access, production mutations, publication or release.

## Design and human review

Desktop, dashboard and website work includes usability and visual quality.
Substantial interaction changes receive agent design review before implementation
and inspection of the actual integrated UI afterward. Small fixes need only
proportionate checks. Follow the workflow's [design criteria](.agents/skills/parsetrail-workflow/SKILL.md#design-and-ui-verification).

Agents make ordinary implementation and design decisions within scope. No new
feature or substantial UI change creates a per-feature owner approval gate.
Consolidate human review at the applicable integrated milestone or an explicitly
requested review. Ask only for unresolved product/accounting choices or specific
human, platform, live-profile or release actions that need owner input. Continue
independent authorized work. Record agent verification, actual owner acceptance
and release authorization separately.

<a id="v2-development-and-human-review"></a>
This policy supersedes earlier first-functional-UI and per-feature human-review
wording for ongoing development; historical acceptance remains evidence.

## Project boundaries

- Preserve exact money, typed dates, source locations and provenance. Keep
  imported evidence, reviewed interpretations and derived reports distinct.
  Unknown stays unknown; never invent balancing entries or count internal
  transfers/card repayments as another expense. Keep material qualifications
  beside affected values and full supporting detail discoverable.
- Use synthetic/disposable profiles and isolated test services for development.
  Live profiles, statements and archives remain read-only unless the task
  explicitly authorizes otherwise. Keep private content, credentials and signing
  material out of Git and routine logs; do not load root `.env` to discover data.
- The current client uses one authoritative fresh profile with an independent
  1.x fallback. Follow its lifecycle contract; do not introduce legacy migrations
  or aliases by interpreting historical experiments as current requirements.
- The service receives ordinary finance data only through the explicit statement
  contribution flow. Preserve its confirmation and encryption boundaries;
  decrypted contributed statements stay in process memory. Artifact signing
  authority remains separate from public hosting.
- Follow applicable branch/API/release contracts. A client-only assignment does
  not authorize service changes; an explicitly scoped full-stack task may cover
  multiple components with coordinated ownership. Deployment, production signing,
  publication and daily-profile activation require their authorized scope.
- Run meaningful focused checks and relevant integration checks. Verify isolation
  before running tools; record actual platforms and untested limits. Offscreen
  or browser automation does not establish owner acceptance or another platform's
  native behavior.

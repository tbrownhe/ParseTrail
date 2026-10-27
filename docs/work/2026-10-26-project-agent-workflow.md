# Project-wide agent team and workflow

Date: October 26, 2026. Roadmap IDs: project-wide engineering guidance; V2-UX coordination only.
Branch/components: `feature/client-financial-insights`; repository instructions/configuration.
Authorization: owner approved the proposed project-wide team and requested generic guidance for most ParseTrail tasks, beyond the current roadmap.
Implementation: complete; instructions/configuration and related current references aligned.
Automated verification: eight TOML roles, skill validation, 181 local links/anchors and diff whitespace passed.
Design verification: not applicable; application UI unchanged.
Independent review: seven task scenarios reviewed; fixture-access ambiguity corrected and independently rechecked, no remaining actionable findings.
Owner acceptance: configuration direction approved; no application/native acceptance implied.
Release authorization: not applicable; no release actions authorized or performed.

## Scope and controlling decisions

Replace the client/milestone-centered role setup with a reusable team for desktop,
parsers, local financial services, API, dashboard, static website, tooling and
documentation. Add cross-surface `ui_ux`; split `service_web` into `backend` and
`web`. Retain one primary integrator, explicit shared-file ownership and independent
review proportional to material financial, evidence, persistence, security and
privacy claims. Primary owns all files for this task; reviewers are read-only.

The current request/session decides scope. Roadmap/TODO remain authoritative for
affected planned work and release gates without limiting explicit maintenance or
investigation requests to the current milestone. No branch changes, migrations,
financial/UI implementation, private data access, deployment or signing are part
of this task. Existing user confirmations and release/platform gates remain.

## Result and review

- Updated AGENTS.md and the workflow for selective context loading, smallest-useful
  team routing, coordinated cross-component work and a fallback when a newly
  configured role is unavailable in the current session.
- Added `ui_ux`, `backend` and `web`; removed `service_web`. Updated all retained
  role files to use compact assignments and relevant contracts rather than a
  mandatory roadmap startup sequence. Models/reasoning inherit session defaults.
- UI development completion includes proportionate design, interaction, visual
  and accessibility verification of the implemented result. Design review and
  owner acceptance remain separate; no per-feature approval gate is introduced.
- Clarified concise presentation of material qualifications with discoverable
  supporting provenance, while preserving financial meaning and unknowns.
- Aligned development/cutover policy, packet template and planning links. Replaced
  stale candidate instructions with stable component entry points, corrected
  startup/reconciliation references and the pilot index, and closed the workflow
  review prerequisite without selecting broad UI implementation.

The independent acceptance reviewer evaluated seven hypothetical requests:
public-site typo, dashboard navigation, API authorization plus schema/generated
consumer, duplicate-expense overlap investigation, developer-helper maintenance
with empty TODO, desktop import/review redesign, and candidate release-readiness
evidence. Routes and ownership were workable across all seven: small tasks stay
lightweight; substantial UI receives design/actual-render review; API generation
has one writer; financial/security claims receive independent review; release
evidence does not authorize publication. These were instruction/source exercises,
not application executions or evidence of improved human usability.

Review found an existing development-guide paragraph that could imply blanket
private-fixture permission through root `.env`. Clarified that retained fixture
authorizations apply to task-relevant explicitly identified inputs, prohibit
`.env` discovery/widening, and preserve live sources/profiles read-only. The
reviewer read the correction and confirmed resolution with no new findings.

New role names are not claimed to have executed in this already-running session;
the reviewer used the existing acceptance role with a bounded read-only brief.

## Verification

Windows AMD64/PowerShell, existing locked Python environments:

- `client/.venv/Scripts/python.exe scratch/team-config-20261026/validate_changes.py`:
  all **8** role TOMLs parsed with `tomllib`; unique names match filenames and
  required nonempty `name`, `description`, `developer_instructions` fields;
  no model/permission overrides. **10** changed Markdown files and **181**
  local links/anchors checked. The one-off validator/results are ignored local
  audit artifacts, not new application tests.
- `backend/.venv/Scripts/python.exe <installed skill-creator>/scripts/quick_validate.py .agents/skills/parsetrail-workflow`:
  **Skill is valid!** The initial client-environment attempt lacked PyYAML;
  the existing backend environment supplied it, without dependency changes.
- `git -c safe.directory=<checkout> diff --check`: passed. The ownership
  exception was scoped to commands; no global Git configuration was changed.
- Current-code checks confirmed ordinary V2 startup, persisted reconciliation
  entry points, backend/Alembic paths and generated-client boundary. Repository
  search found no active routing references to the removed `service_web` role;
  historical names in this record/archives remain evidence.
- Independent read-only scenario review and correction recheck: all seven
  routes remain workable, no remaining actionable findings in reviewed scope.

Application suites were not run: application code, data formats and behavior are
unchanged. No private inputs, live profiles, production services or release
operations were accessed. Actual fresh-session role discovery remains untested.

## Remaining work

Validate actual discovery of new role names in a fresh supported session. Current
sessions may retain their initial role inventory; the workflow provides a usable
fallback without claiming new roles were executed here. UI redesign and existing
owner accounting/platform/release reviews remain separately scoped work.

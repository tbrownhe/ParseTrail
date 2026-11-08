# Journey ownership and usability verification

Date: 2026-11-07. Roadmap scope: project-wide engineering guidance; no product scope or release-gate changes. Branch: feature/client-financial-insights.
Authorization: owner requested the instruction edits proposed in this conversation.
Implementation: complete.
Automated verification: all eight agent TOML definitions parsed; workflow skill validation passed.
Design verification: instruction-only; no application UI inspected or changed.
Independent review: acceptance specialist applied six realistic scenarios; no material contradictions found.
Owner acceptance: owner authorized these edits; application usability acceptance not performed.
Release authorization: not applicable.

## Scope and decisions

Update AGENTS.md, the parsetrail-workflow skill and the existing ui_ux and
acceptance definitions. The primary writes these files and this record/index;
an acceptance specialist reviews realistic task scenarios read-only. Use only
repository instructions, with no private profile, statement, service or secret
access. Keep the existing agent set and owner-review policy.

## Result and review

- Feature requests establish user outcomes; agents translate them into coherent
  journeys before dividing substantial UI implementation work. Existing screen
  and navigation boundaries are open to examination within scope.
- ui_ux owns the integrated interaction model and rechecks findings after fixes;
  desktop/web retain implementation ownership. The primary resolves design and
  engineering conflicts and remains responsible for integrated UX findings.
- Discovery and comprehension criteria include context/scope, attention needed,
  next actions, confirmation effects and result limitations. Presentation keeps
  answers, material qualifications, actions and supporting details legible.
- Independent task attempts remain separate from scripted functional checks and
  record wrong turns, assistance, misunderstandings and recovery. Prior coaching
  or implementation knowledge qualifies the evidence.
- Significant unresolved usability findings keep the affected outcome incomplete
  even when tests pass. Technical completion, agent verification and human
  acceptance remain distinct; no per-feature owner approval was added.

## Verification

Windows, existing locked local Python environments; no application imports or
application tests needed for this instruction-only change.

- Parsed all `.codex/agents/*.toml` using client Python `tomllib`; checked nonempty
  name, description and developer_instructions fields: eight valid definitions.
- Ran skill-creator `scripts/quick_validate.py .agents/skills/parsetrail-workflow`
  with backend Python: passed. Initial client Python attempt lacked PyYAML;
  reused the existing backend environment without installing dependencies or
  loading service configuration.
- Validated 85 local Markdown links and referenced anchors across the four changed
  Markdown files; `git diff --check` passed.
- Independent acceptance reviewed a cross-feature spending comparison, a typo,
  a misunderstood partial total despite passing tests, an out-of-scope backend
  dependency, unavailable native automation and a previously coached reviewer.
  Expected routing, completion/stopping behavior, qualified evidence and existing
  owner-review boundaries were consistent; no material corrections requested.
  Transparent deferral does not establish usability, and pending platform gates
  do not waive agreed UI criteria. This was scenario review, not runtime evidence.

## Remaining work

These instructions do not demonstrate improved application usability. A focused
journey redesign and observed task attempts remain future product work, not
selected or implemented by this request. No roadmap/TODO status was changed.

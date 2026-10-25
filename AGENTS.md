# ParseTrail repository guidance

ParseTrail is a local-first personal-finance desktop application with a separate
account, artifact and explicit statement-contribution service. Keep ordinary
financial data and analysis local.

## Workflow and context

Read `README.md` and `development.md` for orientation/setup, then
[ROADMAP.md](ROADMAP.md) for authoritative milestones, scope and release gates,
and [TODO.md](TODO.md) for selected work. Read its linked packet record and the
relevant component contracts before substantive work. Use
[parsetrail-workflow](.agents/skills/parsetrail-workflow/SKILL.md) for substantive
implementation, integration and repository review; handle simple edits directly.
The skill owns role routing, packet execution and verification.

For V2, the cutover, unified-store, ledger and parsing documents are component
contracts, not parallel roadmaps. Check current code and dated owner decisions.
A recommended candidate, historical checkbox or handover does not select work.

Substantial packets use one `docs/work/YYYY-MM-DD-<packet>.md` record for scope,
implementation, decisions and verification; see [the template](docs/work/README.md).
At closeout update that record, affected contracts and roadmap status, then clear
the selected TODO entry. Small edits can use a concise entry in an existing record.
Keep validation logs out of ROADMAP/TODO. Historical acceptance/handover archives
remain evidence; do not append new work there or create a competing CURRENT file.

## V2 development and human review

Within the selected scope, agents may design the system and implement and verify
a first functional UI without a human checkpoint for each feature or UI change.
Use automated checks and agent review to finish development packets and continue
implementation. Consolidate human review into a later integrated UI/UX pass,
with a disposable end-to-end walkthrough prepared at that milestone.

Ask the owner for unresolved product/accounting decisions that existing contracts
cannot settle, an explicitly requested human review, or a specific native/platform,
release or live-profile gate that requires owner action. Run available native
checks autonomously. A new feature or substantial UI change alone does not
create a human gate. Record unperformed human acceptance honestly and keep
unrelated authorized development moving. This prospective policy supersedes
older per-feature GUI acceptance wording; historical acceptance records remain
valid, and release/platform gates remain separate.

## Subagents

Subagent use is authorized for work within the user's task. The primary agent
may delegate without asking for additional permission when a specialist or
independent review adds value and the session supports it. Use the custom
agents in [.codex/agents](.codex/agents/): `evidence`, `ledger`, `desktop`,
`integrity`, `acceptance` and `service_web`.

- Keep one primary integrator responsible for the user conversation, scope,
  shared contracts, integration and acceptance records. Specialists return
  findings and decisions to the primary; they do not recursively delegate.
- Give each assignment an outcome, relevant contracts, explicit write set,
  permitted data, verification and return expectations. Assign one writer per
  shared file or schema, especially `v2_profile_store.py`. Parallelize disjoint
  work or read-only investigation; serialize conflicting edits.
- Use independent integrity review for material accounting, evidence,
  persistence or financial-report claims as described in the workflow. Small
  tasks do not require a full team. If delegation is unavailable, perform the
  relevant checks in the primary and disclose any review limitation.
- Delegation carries the task's existing authorization and session permissions;
  it does not grant access to additional private data or authorize release,
  deployment, publication or live-profile actions.

## Project boundaries

- Preserve exact money, typed dates, source locations and provenance. Keep
  imported evidence, reviewed interpretations and derived reports distinct.
  Unknown values stay unknown; do not invent balancing entries or count card
  repayments/internal transfers as a second expense.
- V2 uses one fresh authoritative SQLite profile. Keep 1.x databases, archives
  and statements read-only during development; write synthetic/disposable
  profiles. Do not add 1.x migrations or aliases to the V2 runtime. Keep private
  paths, contents, credentials and signing material out of Git and routine logs.
- Keep client work on the active client branch. Follow the documented separate
  service-branch handoff when a client feature needs a server interface. Existing
  roadmap approval does not authorize unselected features or release actions.
- Run meaningful focused checks and the relevant integration suite. Parser work
  may require `devtools/parser_engine_pilot` tests beyond `client/tests`. Follow
  the workflow's isolation and command guidance. Record tested platforms;
  offscreen success does not establish owner native acceptance or Intel support.

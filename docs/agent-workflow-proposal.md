# ParseTrail agent workflow

Review date: October 25, 2026. Reviewed branch: `feature/client-financial-insights`,
HEAD `ed0a2ef`. The initial working tree was clean. The owner approved this
workflow and its repository installation on October 25, 2026, retaining the
`parsetrail-workflow` skill name and shortening the six agent names. Installation
does not select or authorize a roadmap item. The role specifications in
`agent-workflow-handover.md` were used as context and checked against current
contracts and code.

## Recommendation

Use one primary integrator and six optional custom agents. Organize them around
evidence, accounting, desktop interaction, independent integrity review,
acceptance, and separately scoped service/web work. Select roles per packet;
ordinary small changes can stay with the primary agent.

Keep profile implementation with the assigned ledger/store writer. A separate
profile writer would compete with the ledger writer in the same SQLite service.
Keep independent integrity review separate from implementation. The primary
agent owns the conversation, financial/product questions, shared contracts,
integration, and acceptance records; it is not another spawned agent.

The installed skill is at
[`.agents/skills/parsetrail-workflow/SKILL.md`](../.agents/skills/parsetrail-workflow/SKILL.md),
with its `references/` directory. The six installed TOML files are in
[`.codex/agents/`](../.codex/agents/). These are the authoritative workflow files;
the temporary draft copies have been removed.

## Repository review and implications

This was a workflow-oriented repository review: root and component READMEs,
TODO, development and cutover/accounting/parser contracts, relevant runtime
paths, tests, and CI/release configuration. It is not an exhaustive security
audit or a claim that every parser family is financially accepted.

| Finding | Evidence | Consequence for the workflow |
| --- | --- | --- |
| Two client execution paths coexist. The default application remains 1.x; the `--v2` path opens an explicit fresh workspace before legacy settings bootstrap. | `client/src/parsetrail/main.py:55`, `:90`, `:129`; root and client READMEs | Every packet names its runtime. Do not wire a V2 feature into a historical conversion tool or accidentally initialize 1.x. |
| The V2 store already combines immutable source bytes, definitions, evidence, authoring, allocations, journals, corrections and source review. Its current pre-release schema is 10. | `core/v2_profile_store.py:43`, `:592`, `:600`; `docs/client-v2-unified-store.md` | Assign one writer to the shared store and its schema. Recheck the revision at task start; do not encode revision 10 as a permanent requirement. |
| Reconciliation is a versioned read over one committed SQLite snapshot. Page capture, calendar coverage and interpretation review are separate from the balance check. | `core/v2_profile_store.py:2485`; `client/tests/test_v2_statement_reconciliation.py`; `gui/v2_statement_coverage.py` | Reviewers must check both the arithmetic and the claim conveyed by the UI. Do not restore the obsolete page-capture blocker. |
| Account movement is a period-change report, not an as-of balance. Reviewed reports disclose profile-wide unallocated evidence separately from the report's journal date filter. | `core/v2_profile_store.py:1433`, `:1518`; `gui/v2_reviewed_reports.py:356` | An account-position feature needs an explicit new contract, including opening validity, dates, corrections, signs, and source cutoff. It is not just a renamed column. |
| Parsing, account binding and journal decisions are distinct boundaries. Exact-source retry skips parsing; reparse produces a comparison. | `core/v2_source_import.py:55`, `:94`, `:181`; `core/ledger.py:117`; `core/source_evidence.py` | Evidence engineers do not decide postings. Ledger engineers preserve allocation identity, signs, append-only corrections and pending cases. |
| Signed JSON admission, fixed worker dispatch and native resource limits already exist. XLSX decoding exists but workspace imports currently accept CSV/PDF. | `core/v2_data_catalog.py:122`; `core/v2_worker_limits.py:159`, `:179`; `core/v2_workspace.py:76`; parser inventory | Verify admission and supported operations rather than invent a general parser language. A synthetic decoder test does not authorize runtime XLSX support. |
| A significant parser regression surface is outside `client/tests`. There are 50 `test*.py` files in `devtools/parser_engine_pilot`; normal client CI runs pytest from `client`, whose testpaths is `tests`. | `client/pyproject.toml`; `.github/workflows/test-backend.yml:112`; `devtools/parser_engine_pilot/` | Parser packets explicitly include relevant pilot tests. Adding their synthetic suite to CI is a useful separate follow-up, not a change made by this proposal. |
| Roadmap checkboxes aggregate broader work than their accepted pilot slices, and some prose describes superseded stages. For example, V2-3 still says the shell does not post and that ledger integration remains open; later V2-4 entries and current code implement narrow posting. | `TODO.md` V2-3/V2-4; `client/README.md` application-service section; cutover updates | Check current code and dated decisions before opening a packet. Preserve historical context without treating it as a requirement to reimplement accepted behavior. |
| Service finance boundaries are real code boundaries. Contributions are decrypted and re-encrypted in memory; only ciphertext is written. Browser transport uses cookies through the generated-client facade. | `backend/app/api/routes/statements.py:211`; `backend/app/tests/safety.py`; `frontend/src/client/index.ts`; service READMEs | Keep service/web work on demand and on its separately authorized branch. Preserve test isolation, contribution privacy and generated-client ownership. |
| The website loader issue recorded as W1 is still present: the head dynamically appends `main.js`, while the footer loads it after jQuery. | `website/download.html:18`, `:79`, `:85`; TODO W1 | A service/web role has a concrete use outside desktop work. This inspection confirms duplicate loading; the timing failure was not reproduced in a browser here. |
| Build/test artifacts and release authority are intentionally separate. CI builds use build-only output and carry no release signing credentials. | `.github/workflows/client-release.yml`; release contracts | Acceptance work can gather evidence, but cannot infer signing, deployment, publication or daily-profile activation authorization. |

Paths abbreviated as `core/` and `gui/` above are under
`client/src/parsetrail/`. The fresh-profile cutover, single-store design and
current decisions take precedence over old migration/rebuild instructions.
The handover's 956-PDF replay result was not rerun; it remains recorded
execution evidence, not page-capture or accounting acceptance.

## Roles and ownership

| Agent | Normal assignment | Write boundary and return |
| --- | --- | --- |
| Primary integrator | Select a packet, trace current behavior, settle scope, assign files, integrate results and communicate with the owner. | Own shared contracts, TODO and acceptance records. Return behavior, validation, remaining limits and decisions. |
| `evidence` | Finite declarations, source evidence, routing, decoder workers and family comparisons. | Assigned parser/worker/model files and synthetic tests. Return source-to-evidence behavior, refusal cases and coverage limits. |
| `ledger` | Exact accounting services, V2 profile integrity, imports, recovery, reconciliation and common report queries. | Assigned store/service files and synthetic tests; exclusive shared-store writer when needed. Return sign/date examples, transaction effects and unknown states. |
| `desktop` | PySide6 adapters, review/report flows, cancellation presentation and disposable walkthroughs. | Assigned GUI files and interaction tests. Return concrete owner steps and visible states. Request service changes through the integrator. |
| `integrity` | Independent review of financial semantics, provenance, transactions, freshness and failure paths. | Review only; no repository edits. Return actionable findings with locations, examples and unverified limits, or no findings within the named scope. |
| `acceptance` | Select and run appropriate checks, inspect test/CI scope, prepare native/platform or release-readiness evidence. | Verification only; may create disposable test output. Return commands, results, platform, untested gates and owner walkthrough. No acceptance attestation on the owner's behalf. |
| `service_web` | Separately scoped FastAPI, dashboard, public-site, API or deployment-tool implementation. | Read-only interface proposal during a client packet; implementation only in an explicitly authorized service/web packet and branch. No deployment/publication. |

These are instructions, not per-agent filesystem permission policies. Review
agents inherit the parent session's permissions. The primary agent must choose
appropriate session permissions and supervise write ownership.

## Packet lifecycle

Use the skill's short packet contract, then implement the service boundary and
meaningful synthetic tests before connecting the UI. Independent work can run
concurrently only with disjoint write sets; shared-store/schema/contract changes
are serialized. Have integrity review inspect financial or persistence changes
after implementation, and acceptance verify the integrated result as needed.

The owner clarified the review policy on October 25, 2026: agents design the
system and implement a first functional UI within agreed scope, verify it through
automated checks and agent review, and continue without per-feature human
acceptance. This includes new features and substantial UI changes. Human UI/UX
review is consolidated at a later integrated milestone, with a disposable
end-to-end walkthrough prepared then. See the
[current policy](../AGENTS.md#v2-development-and-human-review).

Record implementation, automated verification, independent review, actual human
acceptance and release authorization separately. Development packets may close
while aggregate UX/release milestones remain open. Ask for unresolved
product/accounting decisions that contracts cannot settle, an explicitly
requested review, or a specifically identified native/platform or release gate;
stop only dependent work. Ordinary system/interaction design choices do not
require owner approval. Historical native acceptance records remain valid.

For the candidate V2-5 account-position packet, the primary should first define
an explicit as-of date, recorded versus source-reconciled position, liability
direction, missing/stale openings, correction arithmetic and source cutoff.
Then use ledger implementation, integrity review, desktop implementation and
acceptance as sequentially needed. This example is not selection or approval
of that feature. An unresolved duplicate-source packet may be a better first
choice depending on the report's intended claim.

## Installation and configuration choice

| Installed component | Repository location |
| --- | --- |
| Workflow skill and code/verification reference | `.agents/skills/parsetrail-workflow/` |
| Six standalone custom agents | `.codex/agents/{acceptance,desktop,evidence,integrity,ledger,service_web}.toml` |

The current official schema uses standalone TOML custom agents with `name`,
`description` and `developer_instructions`. These configs intentionally inherit
the parent model and reasoning settings. They do not set sandbox, approval,
provider, MCP, thread-limit or release settings. Current discovery requires no
per-role registration block in `.codex/config.toml`.
See [official subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents).
The repo skill belongs under `.agents/skills/`, per the
[official skill documentation](https://learn.chatgpt.com/docs/build-skills).

The local executable reports `codex-cli 0.164.0-alpha.11.1`. TOML parsing is
validated, but custom-agent discovery in this installed client has not been
exercised. Verify all six names in a new session and perform one
bounded read-only task before implementation delegation. If the host lacks
custom roles or delegation, the primary can perform the same role checks itself.

The owner subsequently requested [root `AGENTS.md`](../AGENTS.md). It provides
the repository entry point, links the workflow and explicitly authorizes scoped
subagent use. Role definitions remain in the skill and custom agent configs.
No framework dependency, custom runner, generated role registry, permanent model
pins or mandatory full-team ceremony is needed.

## Verification performed

- Windows source/offscreen V2 regression: **139 passed, 1,107 deselected**.
- Parser pilot synthetic regression: **232 passed**.
- Installation copied and SHA-256 verified all eight workflow files. The
  bundled `quick_validate.py` passed on the installed skill. All six installed
  TOML configs parsed with the required fields and unique matching short names;
  skill role references, local links and whitespace checks passed.
- No owner native walkthrough, Intel Mac checks, installed-app test, private
  archive replay, backend database suite or browser test was performed.

The installation changes this review record and repository-local skill/agent
configuration only. Application code, existing contracts and TODO status are
unchanged. The test counts above are from the preceding repository review;
application tests were not repeated for this configuration-only installation.

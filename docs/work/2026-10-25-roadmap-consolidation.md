# Roadmap and repository instruction consolidation

Date: October 25, 2026. Roadmap scope: DOCS-1, documentation across all tracks.
Branch: `feature/client-financial-insights`. Reviewed baseline: `d9dab3e`.
Authorization: owner approved the proposed consolidation and requested implementation.
Implementation: complete; documentation and instruction/configuration files only.
Automated verification: documentation/link/configuration checks passed as below.
Independent review: completed; identified omissions restored, no remaining actionable findings in reviewed scope.
Owner acceptance: documentation structure approved; no product/native acceptance implied.
Release authorization: not applicable; no signing, activation or publication scope.

## Scope and controlling decisions

- Make root `ROADMAP.md` the sole ordered plan for outcomes, scope, dependencies
  and release gates. Keep TODO as the short selected-packet board.
- Put substantial plans, decisions and verification together under `docs/work/`.
  Keep current technical/accounting rules in component contracts.
- Preserve existing work, approvals, unresolved decisions, release gates and
  historical acceptance without treating old migration prose as current scope.
- Align AGENTS, the workflow skill/reference, development guide, client overview
  and custom-agent instructions. No application, schema or test-behavior changes.
- Primary owns shared planning/instructions/records; ledger owns the ledger/store
  contract cleanup; evidence owns parser/action-inventory cleanup. Reviewers are
  read-only. All inputs are repository documentation/code; no private data access.

## Result and review

The roadmap retains initial V2/P2 milestones, later CF2-5 direction, unselected
C/F/W proposals, deferred platform/privacy/distribution work and separate service
scope. It maps old L/CF IDs without reopening superseded migrations. It keeps
remaining 1.x action dispositions, Wells personal-loan parser deferral and native/
installed release checks explicit.

Status reconciliation addresses the old non-posting-shell claim, C1/C2a startup
guidance, pending-versus-accepted card/export statements, and the completed narrow
overlap safeguard. No broad duplicate-resolution completion is claimed. DEC-2
records a conflict between older mandatory pre-release server publication and
the open local-catalog alternative; neither is silently chosen.

Fourteen original documents were archived under `archive/2026-10-25-*.md` before
rewrites. Their original wording/headings remain; relative Markdown links were
rebased so the archive is usable. Historical acceptance/handover/review entry
points retain their heading destinations and direct readers to archived evidence.
The work index lists source-to-archive mappings. The last overlap packet is also
normalized into its own record, explicitly carrying forward prior test evidence.
Approved unique matching constraints and evidence scopes/row roles remain in
current contracts. The family map retains all 22 family IDs while moving replay
and operation-cost chronology behind archive links.

Independent review found a transferred-record link error, omitted CF5 forecast
acceptance (exact projections/backtests/reserve once/uncertainty), and a compressed
durable reconciliation-history target. All were corrected. The ledger contract
now distinguishes implemented read-only checks from the retained durable-history
requirement. A fresh-session pickup followed AGENTS/skill to TODO and continued
DOCS-1, leaving the product candidates unselected; it identified the same packet
record as the place for evidence and the closeout action as clearing TODO.
After closeout, a second fresh-session exercise reported no selected packet,
proposed a bounded V2-5 candidate for scope selection, and identified the same
record location and separate UX/platform/release gates. It did not resume DOCS-1
or repeat the completed occurrence safeguard.

## Verification

Windows source documentation/configuration checks, October 25, 2026:

```powershell
& .\client\.venv\Scripts\python.exe scratch/verify_roadmap_docs.py
$repoRoot = (Get-Location).Path.Replace('\', '/')
git -c "safe.directory=$repoRoot" diff --check
```

The one-off, ignored scratch audit checked 39 changed Markdown files and 601
local file/fragment links; all passed. It compared all 14 archived bodies against
`git show d9dab3e:<original>` after canonicalizing relative link targets, and
verified legacy heading sets remain reachable. Exact text was preserved apart
from the documented relative-link rebasing. All 32 menu labels and all 22 parser
ID/source-version/family tuples were retained. Six TOML configs parsed with the
same role names/required fields; all 45 changed files were Markdown or TOML and
passed file-size/BOM/newline/whitespace boundary checks. Scratch audit scripts are
local verification aids, not new runtime tools or committed framework dependencies.

The workflow skill's bundled validator passed. The client interpreter initially
lacked PyYAML; the installed Git-hook interpreter supplied that dependency:

```powershell
$hookText = Get-Content .git/hooks/pre-commit -Raw
$hookPython = [regex]::Match($hookText, "INSTALL_PYTHON='([^']+)'").Groups[1].Value
$skillValidator = Join-Path $env:USERPROFILE '.codex/skills/.system/skill-creator/scripts/quick_validate.py'
& $hookPython $skillValidator .agents/skills/parsetrail-workflow
```

Repository hooks ran with the installed interpreter and the explicit 45 changed
file paths using `python -m pre_commit run --files <paths>`. The process received
a scoped `safe.directory` override, without changing global Git configuration.
Large-file, case-conflict, merge-conflict, TOML, final-newline, whitespace,
line-ending and BOM hooks passed; YAML, Ruff and Biome had no applicable files.
`git diff --check` passed. These checks performed no release or external actions;
the owner subsequently authorized the documentation commit after context-readiness review.

Application suites were not rerun for this documentation-only packet. Prior
overlap test/native results remain linked historical evidence. Independent review
was selective for scope/meaning; the separate archive comparison covered all
archived body text. No private data, credentials or production artifacts were read.

## Context readiness before commit

The owner requested a final pickup-context check before starting a new session.
The three TODO candidates now link the workflow reference's technical starting
points: controlling contracts, actual store/GUI symbols, focused synthetic tests,
known limits and decision dependencies. All 15 named starting test files exist.

Independent review identified two gaps and verified their resolution: V2-5 must
distinguish a live computed reconciliation check from a previously saved cutoff
that depends on unfinished V2-4 history; the parser pilot README needed to label
its incremental narrative historical and identify current CSV/PDF workspace
admission and isolated XLSX scope. Positions work can proceed with truthful
live-check wording. No product candidate was selected during this audit.

The repeated documentation audit passed for 40 changed Markdown files, 645 local
links, 14 archived bodies/legacy heading sets, 32 menu labels, six TOML configs and
46 documentation/configuration files. The final independent read found no remaining
actionable context gaps. Application tests were not rerun; Git commit hooks verify
the staged documentation/configuration files at the authorized commit.

## Remaining work

DOCS-1 is cleared from the selected TODO entry. No product implementation is
selected by this cleanup. Account positions,
remaining review safeguards and parser/catalog readiness remain roadmap candidates;
DEC-1/2/3 and UX/platform/release gates retain their dependent work.

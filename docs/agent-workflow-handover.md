# ParseTrail agent workflow handover

Snapshot: October 25, 2026. Branch: `feature/client-financial-insights`.
Implementation baseline commit: `0ce2365` (`Record reconciliation wording acceptance`).
The working tree was clean when this handover was prepared.

This is a handover for designing an agent-as-code or BMAD-style workflow. It
describes the current work and proposes roles; it does not activate a new agent
runner, grant access to private data, or change the release process.

## Where work stands

ParseTrail 1.4.2 is the published desktop release. Client 2.0 is a fresh-profile
development effort on this branch. The owner chose to re-enter authored data in
2.0. The 1.x database, archive and application remain an independent fallback;
there is no 1.x database migration, alias layer or automatic carry-forward of
verified categories. The current pre-release 2.0 profile schema is revision 10.
It uses one authoritative SQLite store for source evidence, account decisions
and the double-entry ledger; disposable pilot profiles are recreated when this
pre-release schema changes.

The current 2.0 pilot has:

- A finite, signed JSON parser catalog and bounded source decoders. The owner
  requires every current parser family in the first 2.0 release, including the
  recent Citi PDF layout. The read-only successful-archive replay routed and
  parsed 956 PDFs plus one MOHELA CSV; this establishes execution coverage, not
  complete page capture or accounting acceptance.
- A separate fresh 2.0 profile, immutable imported source/evidence snapshots,
  account binding, selected-file and batch import, and verified backup/restore.
- Explicit account/category/budget editing, cash income/expense and card purchase
  review, whole-movement transfer/card-payment review, opening decisions and
  append-only source provenance review. Journal corrections preserve source
  history. Unsupported interpretations remain pending.
- Reviewed spending, income, account movement, monthly budgets and transaction-row
  workbook export. These reports disclose their incomplete source scope.
- Statement coverage, printed openings, journal comparison and a read-only,
  versioned Reconciliation check. The owner accepted the native Windows tab and
  its revised page-capture wording.

The most recent accounting slice is in `client/src/parsetrail/core/v2_profile_store.py`
and `client/src/parsetrail/gui/v2_statement_coverage.py`. Commit `30011b4` added
the reconciliation check; `bab5ba7` made unverified page capture a visible
evidence limit instead of a balance-reconciliation blocker. The check compares
printed and journal opening/closing positions, source arithmetic, allocations,
source review, posting-date provenance and the current opening decision in one
SQLite read snapshot. It returns a deterministic rule and input version. Page
capture, period coverage and interpretation review remain separate dimensions.
The owner accepted the revised native wording; `0ce2365` records that acceptance.
The V2 automated suite last passed with 139 tests.

No account-balance or balance-history implementation was started after that
acceptance. I inspected the existing account-movement report as a possible next
slice, then stopped so the owner could change the working process. No native UI
acceptance or accounting decision is currently awaiting an answer.

## Boundaries already decided

| Boundary | Working rule |
| --- | --- |
| Private finance data | Live statements, databases and archives are read-only during development. Use synthetic or disposable profiles for writes. Keep private paths, contents and reports out of Git and routine logs. |
| Client/server | Continue client work on this branch. No server changes, deployment or publication here. A needed server interface should be designed and reviewed before a separate server branch. |
| Release | No version bump, installer release or 2.0 activation yet. The 1.4.2 profile remains independent. |
| Accounting | Preserve exact money, source locations and observed/derived/assumed/unknown provenance. Parsers emit evidence, not postings. No inferred balancing entries or double-counted transfers/card repayments. |
| Uncertainty | Keep source capture, posting-date certainty, allocation, reconciliation, interpretation review, period coverage and report freshness visible as distinct facts. An equal balance equation cannot establish missing-history coverage. |
| User decisions | Stop for ambiguous accounting semantics or a major design change. Prepare code, tests, a disposable walkthrough and precise alternatives before asking. Native GUI acceptance is an owner gate; automated/offscreen tests do not substitute for it. |
| Design preference | Favor a clean final 2.0 state over compatibility machinery. Make financial claims truthful first, then offer explicit controls that remove avoidable friction. |

The owner approved a global abbreviated-account auto-match toggle, default off,
and a global assumed posting-date toggle, default off. A parser may supply signed
institution/account-class context for a unique match. An assumed date remains
marked as assumed in source evidence and can be corrected later in the journal.

## Next work packet to consider

**V2-5 account positions and balance history** is a useful next bounded packet.
The existing Account movement tab reports reviewed changes and an opening
position separately; it does not display an account balance. The reconciliation
check now provides a source-backed cutoff that can anchor a cautious position
view. This is a candidate, not an accepted implementation plan.

Before coding, define the report contract in one short design note:

1. Choose an explicit as-of date and show asset value or liability owed in its
   natural direction. A missing or stale opening decision is unknown, never zero.
2. Specify whether the displayed figure is the recorded journal position or a
   source-reconciled position. Show the last reconciled statement cutoff and
   pending activity separately. Do not label a journal sum as a current bank
   balance or net worth.
3. Include original/reversal/replacement entries correctly in arithmetic;
   retain unreviewed interpretation and source-overlap warnings.
4. Implement the read-only store query and meaningful tests first, then the UI
   and owner-launched disposable walkthrough. Request native acceptance before
   treating the UI slice as complete.

Other launch work remains open in `TODO.md` and the 1.x menu inventory: duplicate
or overlapping source resolution, transfer correction and partial/fee handling,
loan/HSA/investment interpretations, manual values and closures, balance reports,
production-signed starter catalog and installed offline checks, targeted Intel
Mac decoder checks, final daily-workflow UX, and explicit decisions on remaining
1.x actions. Forecasting and complete historical loan reconstruction are later
work. The cutover plan remains the release authority; older TODO paragraphs may
describe historical pilot states, so verify against code and newer acceptance
notes before opening a packet.

## Proposed agent workflow

Use one **integrator** to own the user conversation, work packet, branch state
and final acceptance record. Give specialists narrow deliverables with file
ownership, a clear read/write boundary and an acceptance test. Parallelize
independent research or disjoint code areas; serialize edits to shared store,
schema, accounting contract and roadmap files. Specialists return evidence and
questions to the integrator; they do not silently decide financial semantics.

Each work packet should contain:

```text
Outcome and non-goals:
Authoritative contracts and current code:
Files or area owned by this role:
Data access and write boundary:
Financial claims/provenance to preserve:
Tests and disposable native walkthrough:
Decision or acceptance gate:
Handoff: changes, evidence, limits, open questions, commit:
```

Suggested sequence: (1) inventory the relevant current behavior and contract;
(2) write a bounded service/data design; (3) implement and test with synthetic
fixtures; (4) have a different role inspect provenance, signs, corrections and
failure paths; (5) integrate UI and prepare an owner-launchable disposable
profile; (6) record native acceptance in the cutover notes; (7) commit a clean
slice. Reserve production signing, installation, publication and live-profile
actions for their explicit release gates.

## Suggested role briefs for subagent config

These are capabilities, not a recommendation to run every role on every task.
For the next account-position packet, the integrator, ledger reviewer, desktop
implementer and acceptance reviewer are sufficient. The owner remains the
product/accounting decision maker and native GUI acceptor.

| Role | Owns and returns | Required independent check |
| --- | --- | --- |
| **Integrator / product steward** | Turns `TODO.md` and the cutover plan into one bounded packet; assigns non-overlapping work; tracks owner decisions, commits and acceptance. Returns a concise decision log and remaining release risks. | Checks proposed behavior against the owner's clean-profile and privacy choices; stops on ambiguous accounting or server/release boundaries. |
| **Parser and evidence engineer** | Finite declarations, bounded decoding, source locations, exact values, date/balance provenance and per-family parity. Returns a source-to-evidence audit with unresolved rows and limitations. | Ensures `capture_verified` and an independent balance equation mean different things; never promotes parser output to a journal decision. |
| **Ledger and reconciliation engineer** | Journal posting/correction, allocation, opening, transfer, reconciliation and read-only financial report contracts. Returns exact sign/date examples and exception behavior. | Reviews double-entry balance, duplicate source use, reversals, last-four/assumed-date gates and any claim of reconciliation or account balance. |
| **Profile and integrity engineer** | The single 2.0 SQLite store, schema lifecycle, import idempotence, backup/restore, snapshot/version validity and recovery. Returns integrity tests and a statement of write effects. | Rejects accidental 1.x writable access, hidden migrations/aliases and stale or partial accounting writes. Coordinates shared-store edits with the ledger role. |
| **Desktop workflow engineer** | PySide6 review/report views, clear provenance and pending-state language, accessible table sizing, and a disposable native walkthrough. Returns screenshots or concrete owner steps and UI tests. | Verifies that toggles remove friction without changing evidence; no GUI label may overstate source coverage, reconciliation or report completeness. |
| **Acceptance and release engineer** | Test matrix, signed-catalog/package/offline checks, Windows and targeted Intel Mac probes, release evidence. Returns exact commands, outcomes and untested limits. | Uses disposable profiles and fixtures; separates automated/offscreen success from owner native acceptance and never signs/publishes/deploys on its own. |
| **Service and web engineer (on demand)** | Backend/frontend/website contract work when a client feature truly needs a service change. Returns a separate branch proposal and API/privacy impact. | Keeps local finance data and statement contribution boundaries intact; does not bundle server work into routine client slices. |

The integrator should seek a ledger review before changing `Statement`,
`Account`, `Transaction`, journal or reconciliation semantics; parser and
profile reviews before changing stored evidence; and a separate native GUI
acceptance for a material review flow. This is a review routing rule, not a
veto against improving shared models.

## First files and repeatable checks

- Orientation: `README.md`, `development.md`, `client/README.md`.
- Scope and decisions: `TODO.md`, `docs/client-v2-cutover.md`,
  `docs/client-v2-parsing.md`, `docs/client-ledger-contract.md`,
  `docs/client-v2-menu-inventory.md`.
- Current 2.0 implementation: `client/src/parsetrail/core/v2_profile_store.py`,
  `client/src/parsetrail/core/v2_source_import.py`,
  `client/src/parsetrail/core/v2_workspace.py`,
  `client/src/parsetrail/gui/v2_workspace_window.py`,
  `client/src/parsetrail/gui/v2_statement_coverage.py`,
  `client/src/parsetrail/gui/v2_reviewed_reports.py`.
- Parser work: `client/src/parsetrail/core/v2_*`,
  `devtools/parser_engine_pilot/`, `docs/client-v2-parser-inventory.md`.
- Service work when separately authorized: `backend/README.md`,
  `frontend/README.md`, `docs/privacy-and-data-flow.md`.
- Synthetic owner walkthrough from the repository root:

  ```powershell
  $env:PYTHONPATH='.;client/src;client'
  & .\client\.venv\Scripts\python.exe -m devtools.parser_engine_pilot.open_v2_workspace --demo --comparison
  ```

  The owner must launch this in their own Windows session. A sandbox-launched
  window or profile may be invisible or prompt for administrator credentials.
- V2 regression loop from the repository root:

  ```powershell
  $env:PYTHONPATH='.;client/src;client'
  $env:QT_QPA_PLATFORM='offscreen'
  & .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests -k v2 -q
  ```

Run relevant narrower tests while editing and the V2 suite at an integration
gate. Use the repository's Ruff and pre-commit checks on changed code. Record
the exact tested scope and platform; do not infer Intel Mac acceptance from a
Windows result.

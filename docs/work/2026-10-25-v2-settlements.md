# Review transfer fees and partial settlements without balancing plugs

Date: 2026-10-25. Roadmap IDs: V2-4/5, CF2.
Authorization: approved roadmap and continued initial V2/P2 development.
Implementation: complete after category-purpose closeout (`1a2f79d`); schema 18.
Automated verification: 681 V2 checks plus final affected GUI/controller checks passed.
Independent review: financial/persistence/cash/export and functional GUI complete;
no actionable findings remain.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Extend the existing reviewed transfer event and correction machinery for one
source-backed asset outflow, one or more distinct owned-account receipts, and
explicit exact source-backed fee allocations. Retain whole-pair APIs as narrow
wrappers. No inferred fee from an amount mismatch, estimated interest, arbitrary
manual journals, loan component accounting or unsupported source-role promotion.
All source legs retain their complete signed financial allocation and original
reviewed dates. Unknown counterpart history stays unknown.

Example: cash outflow 100, explicitly reviewed fee 10, receipt 60. At the outgoing
date credit cash 100, debit expense 10 and transfer clearing 90. At the incoming
date debit the receiving financial account 60 and credit clearing 60. Remaining
clearing 30 is visibly unresolved/in transit, never an invented expense, equity
plug or zero settlement. Fee details require an exact reviewed amount, category,
reference and reason; typed difference arithmetic does not authorize the fee.
No fee is selected by default. Also admit explicitly reviewed receiving-side fees:
outflow 100 and net receipt 90 with fee 10 post debit receiving cash 90, expense
10 and credit clearing 100 at the receipt date. The raw receipt remains +90;
gross settlement 100 is a reviewed allocation, not a printed source amount.
Every fee identifies its source leg, exact amount, expense category and reference.

Use the one authoritative profile and immutable TransferEvents/history/actions,
generalizing the validated event manifest rather than creating an unvalidated
parallel posting path. Pre-release schema evolution recreates disposable profiles.
Adding later receipts may atomically replace the whole old event, preserving
every inverse/original date and source-use history. Settled receipt sums plus
explicit fees must not exceed the full outflow (receiving-side fees add to their
receipt's gross settlement). Source repeats, existing active
consumption, binding and stale-selection guards apply to every member.

Common reads, original/replacement/retirement validation, binding correction,
reconciliation, backup, export and financial positions must understand the full
manifest. Cash movement must keep exact selected-account totals while separating
fee spending from transfer portions without double counting an entry/source.
Same-day internal scope cancellation and different-date clearing remain visible.
Loan interest remains a separate later packet; no gross payment is allocated as
principal merely because its amount matches a cash row.

`category_service` (ledger) owns the store/schema, new pure settlement module and
service tests; `positions_desktop` owns transfer/settlement review GUI and its
tests; the primary owns shared contracts, cash/report integration and workspace
navigation wiring. `positions_integrity` performs independent accounting and
persistence review; `cash_movement_integrity` independently reviews GUI/reports.
Agreed APIs precede dependent edits; keep one writer per file.
Only synthetic/disposable sources/profiles; no private, 1.x or daily-profile writes.

## Result and review

The pure `v2_settlements.py` defines immutable typed movements, fees and finite
manifests (one outgoing, 1..32 incoming rows, at most 64 fees), canonical encoding
and exact source-dated entries. The store uses a tagged manifest in the existing
TransferEvents history, with schema revision 18 refusing earlier disposable
profiles. Legacy whole-pair APIs retain their existing behavior; validated events
also expose their complete settlement. General events have no projected pair.

Each advanced source leg creates one balanced entry at its own reviewed date,
including same-day legs. The full raw financial amount is allocated once; fee
and clearing postings balance that exact effect. Receipts can precede the sending
date, retaining negative interim clearing rather than rewriting evidence dates.
Preview is read-only and committed; full creation/replacement/withdrawal is atomic.
Replacing to add a later receipt retires all old entries with exact dated inverses.

Cash movement keeps one row per journal entry and exact selected financial
effects. A selected net receiving asset +90 with fee 10 decomposes as transfer
+100 and expense -10 on that receiving date. An unselected/card-side fee creates
no selected cash row. Purpose buckets sum these components, and a record can
participate in two counts; the GUI explicitly says counts are not additive.
Partial manifests stay qualified as unresolved clearing; full event context may
include other dates and never adds money to a selected period.

The common workbook conditionally includes Settlement Events, Settlement Legs
and Settlement Fees metadata. It retains raw signed amounts, exact transfer/fee
minor-unit text, source IDs/dates, references/reasons, status and versions,
including out-of-period legs and withdrawn event history. Only active in-period
entries/postings contribute money. A formula-like review reference remains text.
Workspace Review navigation opens the full settlement dialog and guards an
ongoing import. Both the direct and legacy/nested routes are guarded. The full
desktop workflow supports explicit source selection, complete fee fields, exact
preview, source inspection, whole replacement/withdrawal and historical manifests.

Independent early review found two material integrity gaps in the earlier
transfer path: malformed clearing-account class could enter expense totals, and
an additional pending source allocation could duplicate a transfer's source use.
The store writer added exact code-owned clearing validation and sole-active
source allocation checks across all pair/generic legs. A deeply nested damaged
manifest also needed bounded/controlled decoding rather than leaking a recursion
error. Public account authoring rejects the reserved internal namespace before
writing. Final financial/persistence/cash/export review found no actionable
findings. A concurrent writer could not mix movement rows with newer category or
basis data; stale posting refused with no journals.

Final independent GUI review resolved three concrete issues: legacy generic
history now distinguishes reviewed account names/kinds/IDs; parent transfer review
synchronizes its global assumed-date checkbox after nested review; both menu/button
routes into settlement authoring are disabled/guarded during import. Draft captions
remain accurate and long account/source captions do not widen the window.

## Verification

Test exact/partial/multiple receipts, explicit fees, over-allocation, dates/order,
unresolved clearing at intermediate cutoffs, no automatic mismatch fee, source
overlap/consumption, stale/idempotent/retry/rollback, whole replacement/withdrawal,
historical binding correction and saved reconciliation invalidation. Test common
reports/positions/export/backup against exact independently calculated examples,
including cash-scope subsets and mixed fee/transfer entry classification. Test
malformed manifests and every failure/cancellation path. Focused plus relevant
integration, independent review, offscreen GUI inspection, Ruff/hooks required.

Windows 11 AMD64, Python 3.13.15, Qt offscreen; synthetic/disposable inputs only.
Tests use `PYTHONPATH=.;client/src;client`, `QT_QPA_PLATFORM=offscreen` and
`client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider ... -q`.

- Primary first four cash/metadata integration cases plus legacy cash/export:
  **19 passed in 25.42s**. Final primary six integration cases, including actual
  cash components display and workspace action/import guard: **6 passed in 5.14s**.
  Module: `client/tests/test_v2_settlement_cash_integration.py`.
  The final root integration/cash/export/workspace suite passed **30 checks in
  24.31s** on the frozen financial services.
- Service final five-module suite: **134 passed in 147.29s**, including **39** new
  settlement cases and all final depth/identity/allocation hardening. Arguments:
  `client/tests/test_v2_settlements.py client/tests/test_v2_transfers.py
  client/tests/test_v2_transfer_corrections.py client/tests/test_v2_binding_corrections.py
  client/tests/test_v2_category_purposes.py -q --tb=short`.
  Earlier 24 settlement cases passed in 31.68s; expanded settlement/old transfer/
  correction/binding checks passed 105 in 84.52s before final hardening.
- Independent settlement/cash/legacy transfer/correction suite: **67 passed in
  76.04s**, before the final malformed-depth branch. A separate 1,000-case seeded
  pure-manifest oracle checked exact balances, allocations, original dates,
  fee location, clearing residuals and encode/decode round-trips. This is pure
  arithmetic evidence, not source admission or platform acceptance.
- Final independent settlement/cash/export/binding/reconciliation/common-journal
  suite: **118 passed in 135.09s** with all final service hardening. Arguments:
  `client/tests/test_v2_settlements.py
  client/tests/test_v2_settlement_cash_integration.py client/tests/test_v2_report_export.py
  client/tests/test_v2_binding_corrections.py client/tests/test_v2_reconciliation_history.py
  client/tests/test_v2_common_journal_integrity.py -q`.
- Additional independent public-service probes preserved stale reconciliation
  inputs after a changed interpretation, kept successful per-source closing
  separate from global unresolved clearing, and preserved old manifest accounts
  after whole withdrawal and reviewed binding correction, including backup/reopen.
- Final broad V2 suite: **681 passed, 1,107 deselected in 518.26s** with
  `client/tests -k v2 -q --tb=short`. This run began on the frozen financial service
  before the last bounded GUI label/preference/import-guard refinements. Their
  focused final checks cover those changes; no second full run is implied.
- Desktop first actual settlement/legacy-flow suite: **22 passed in 20.26s**;
  final focused desktop run **24 passed in 23.75s** using
  `client/tests/test_v2_settlement_review_dialog.py
  client/tests/test_v2_transfer_corrections_dialog.py -q`. Independent final **11 settlement
  GUI cases passed in 9.50s**, and the final workspace guard case passed **1.23s**.
  Prior independent new/legacy flow suite passed **22 in 29.87s**, and final root
  cash/export/workspace suite **30 in 35.72s**. Primary final guard case passed
  **1 in 1.25s**. Final module: `client/tests/test_v2_settlement_review_dialog.py`.
- Independent full-size probe selected all 32 receipts/IDs, previewed exactly 33
  entries and correct residual, routed outgoing/last-receipt source previews,
  and left profile bytes unchanged. Segoe UI offscreen inspection found source,
  fee and preview tabs readable at 1180x790; this is not owner native acceptance.
- Changed-file Ruff/format, repository hooks, `git diff --check` and local
  documentation link checks passed. No production signing, installation, release,
  private/live data or Intel acceptance was performed.

## Remaining work

Loan/HSA/source-observed dated values and their cash/report classification, then
integrated UX/runtime/platform/release gates. Multi-outflow events, foreign currency
and unsupported source shapes remain visibly pending; no blanket accounting
completeness claim. The approved program does not require exhaustive historical
reconstruction.

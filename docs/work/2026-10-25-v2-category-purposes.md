# Review refunds and income adjustments with stable category identities

Date: 2026-10-25. Roadmap IDs: V2-4/5.
Authorization: approved roadmap and continued development.
Implementation: complete after account-anchor closeout (`4628dd7`); schema remains 17.
Automated verification: 625 V2 checks and final affected GUI/report checks passed.
Independent review: financial/persistence and functional GUI/report review complete;
no actionable findings remain.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Admit explicit source-backed ordinary category purposes for supported account-
total cash/card rows: expense, expense refund, income and income adjustment as
appropriate to the exact financial effect and selected category class. Positive
cash is not automatically income; a positive card credit is not automatically a
refund rather than an owned payment. Offer clear purpose/category/reason review;
do not infer purpose from sign, merchant words or amount matches. Preserve all
source amounts, locations, roles and dates, existing date/assumption gates,
unique active consumption and cross-source posting guards. No arbitrary manual
journals, new loan/HSA scope, splits or undocumented source-role promotion here.

Source financial postings retain their exact original effect. Refunds credit an
expense; income adjustments debit income. Owned transfers/card payments remain
their own reviewed workflow and never create another expense. Category/date
corrections retain purpose/class; a genuine purpose change uses explicit
withdrawal and fresh review. Common initial/historical validators, withdrawal,
posted-repeat repair, reconciliation, backup/export and cash-movement reporting
must understand the admitted shapes. Unknown or unsupported cases stay pending.

Establish the existing contract's code-owned built-in category catalog, starting
with stable `builtin:loan-interest` / Loan interest / expense. Reserve its namespace
and immutable name/type; a custom matching display name remains a separate ID.
Catalog reads stay pure/read-only. Materialize a selected known built-in only
through explicit authoring or inside the posting transaction that needs it.
Do not silently add a default interest category on ordinary report reads, select
it for unrelated spending, or admit loan postings in this packet. Future loan
interest must use this semantic key; this is its prerequisite.

`category_service` (ledger) owns `v2_profile_store.py`, service checks and narrowly
coordinated headless assertion updates. `positions_desktop` owns the cash/card
review dialogs, `v2_categories.py` and their interaction checks. The primary owns
the pure built-in catalog, cross-report integration checks, shared contracts and
this record. `positions_integrity` reviews accounting/persistence independently;
`cash_movement_integrity` reviews the functional GUI/report integration. No recursive delegation. Use only
synthetic/disposable profiles; no private/1.x mutations or release actions.

## Result and review

The narrow API appends saved `purpose` and allowed purposes to cash/card review
rows. Posting receives the explicitly selected purpose; existing narrow service
callers retain ordinary expense/income wrappers. Exact source sign plus reviewed
category class determine the admitted shape, while the initial key records its
purpose and correction history must retain that class. GUI initial choices have
placeholders; no positive amount automatically selects income/refund. An active
purpose is locked until withdrawal and fresh review.

`v2_builtin_categories.py` is a pure immutable code catalog. The store's explicit
`ensure_builtin_category` creates only known fixed categories; selected built-ins
can also materialize inside a posting/correction transaction. Optimistic selection
is checked before this transaction's own category materialization. Read/list/report
calls never create accounts. Common guards reject reserved unknown IDs and altered
built-in metadata; custom same-name identities stay separate.

Primary integration checks establish a concrete negative-net example: expense
400 and refund 1,000 yield spending -600; income 500 and adjustment -700 yield
income -200. Cash movement is +400. Budgets, inclusive positions, active history,
source allocations, drill-down, workbook exact minor-unit columns and a reopened
independent backup agree. Missing opening and one unreviewed source receipt stay
visible. No cash-report algorithm change was necessary: its existing validated
category-class branches now receive actually admitted refunds/adjustments.

Independent review found that a malformed SQLite BLOB account ID escaped the new
built-in validation as a TypeError. The store writer added typed persisted-ID
refusal and malformed metadata checks. Primary review reproduced a first-use
built-in card correction failure: the replacement validated against an account
map loaded before category materialization. The service writer reordered that
operation; primary and service regression checks pass. Independent late-failure
injection after materialization/journal inserts proved full transaction rollback.

Final financial/persistence review found no actionable findings. Additional
four-purpose duplicate-repair/correction/withdrawal/fresh-opposite-purpose cycles
retained one exact financial effect/allocation and backed up correctly. A saved
reconciliation check became stale after income was withdrawn and re-reviewed as
a refund even though the live closing remained unchanged and successful; saved
history retained its original inputs. These are accidental-corruption/invariant
checks, not authenticity against arbitrary hostile SQL rewriting.

Independent GUI review found matching built-in/custom report names remained
indistinguishable. A shared pure `category_labels` helper now supplies authoring,
review, spending/budget, cash-note and drill-down labels; selected IDs and totals
are unchanged. Drill-down shows identity in its header/tooltip/posting details.
The new integrated same-name scenario verifies both displays and navigation to
the correct category ID/effect. A late budget-read/write refusal also now clears
saved amounts, history, category authoring/rename controls and selection, while a
plain invalid typed amount retains the verified saved state. Correction
confirmations now label replacement-entry effects separately from the prior
inverse: category-only correction adds no financial movement and preserves its
class total; card date changes explicitly show both dates and period restatement.
Final independent GUI/report review found no actionable findings.

## Verification

Test cash/card refunds, negative income corrections and ordinary income/expense
without sign inference, double-counted repayments or changed source dates;
cross-type correction refusal, withdrawal/fresh posting, exact dated inverse and
repeat repair, historical assumed-date opt-out, pending/zero/unsupported rows,
stale/version/idempotence/rollback, net budget/income/spending/cash summaries,
backup/reopen/export and malformed stored shapes. Test built-in reserved IDs,
fixed identity/name/type, custom same-name separation, atomic materialization and
read-only catalog discovery. Run focused plus relevant V2 integration, Ruff/hooks
and independent financial/functional GUI review.

Windows 11 AMD64, Python 3.13.15, Qt offscreen, synthetic/disposable profiles:

- Primary focused source interpretation/repair, cash movement and first three
  integration cases: **37 passed in 48.16s**. The first-post built-in selection
  basis case subsequently passed separately (**1 passed, 3 deselected in 2.18s**).
- Final primary integration module: **5 passed in 9.65s**, including both report
  dialogs, first built-in posting with its selected basis, and first built-in
  card correction after the reproduced failure/fix.
- Service final focused five-module suite: **57 passed in 55.47s**, including
  24 purpose/built-in cases, ordinary journal, budgets, reports and source repair.
- Independent final purpose/integration/card/reconciliation/journal suite:
  **67 passed in 64.12s**; earlier purpose/integration/source-repair/common-journal
  suite **61 passed in 93.35s** preceded the final card materialization reorder.
- Primary final label/report/cash integration: **33 passed in 54.42s** using
  `client/tests/test_v2_category_purpose_integration.py
  client/tests/test_v2_reviewed_reports_dialog.py
  client/tests/test_v2_report_drilldown.py client/tests/test_v2_cash_movement.py`.
- Desktop focused cash/card/categories/source-withdrawal suite **42 passed in
  33.17s** before the final late budget failure clear; the final budget/category
  branch then passed **8 checks, 12 deselected in 9.32s**, and the shared helper's
  built-in GUI cases passed **4 checks, 12 deselected in 4.62s**.
- Independent final label/failure-clear checks: purpose GUI/categories/budgets
  **20 passed in 38.37s** and integration/report/drill-down **20 passed in 34.72s**.
  An earlier pre-refinement cash/card/category/report/source-withdrawal run passed
  **50 checks in 68.43s**. Final correction confirmation tests: desktop **9 passed,
  11 deselected in 12.56s**; independent **8 passed, 12 deselected in 10.49s** and
  the card-date GUI case **1 passed in 1.91s**.
- Changed-file repository hooks passed with no fixes; changed-file Ruff/format,
  `git diff --check` and local documentation link checks passed. Readable layout
  inspection explicitly loaded Segoe UI at cash 1050x620, card 1200x650 and
  category manager 600x650. This is Qt offscreen evidence, not native acceptance.
- Full V2 suite: **625 passed, 1,107 deselected in 515.47s** using
  `client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider client/tests -k v2 -q`.
  The broad run began before final
  budget-clear/identity/confirmation UI refinements; their focused checks above
  and final review cover those later changes without implying another full run.

Tests use `PYTHONPATH=.;client/src;client`, `QT_QPA_PLATFORM=offscreen` and
`client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider ... -q`.
Final independent module arguments: `client/tests/test_v2_category_purposes.py
client/tests/test_v2_category_purpose_integration.py
client/tests/test_v2_card_purchase_review.py
client/tests/test_v2_reconciliation_history.py
client/tests/test_v2_reviewed_journal.py`.

## Remaining work

Fees/partial settlements, admitted loan/HSA/source-value interpretations and their
cash/report classification, then integrated UX/runtime/platform/release gates.

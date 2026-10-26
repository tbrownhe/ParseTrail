# Classify reviewed movement over an explicit cash-account scope

Date: 2026-10-25. Roadmap IDs: V2-5, CF2.
Authorization: approved roadmap and continued initial-release development.
Implementation: complete for currently admitted ordinary/whole-transfer shapes.
Automated verification: focused cash/drill-down/workspace checks passed.
Independent review: complete; account-identity finding resolved and independently rechecked.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Report exact active reviewed non-opening journal movement for an explicit
user-selected set of financial asset accounts and inclusive/exclusive period.
Select no accounts by default: asset kind does not itself establish cash scope.
Classify admitted ordinary cash category entries and validated owned transfer/
card-payment events, preserving their actual posting dates and clearing timing.
Known card purchases affect spending when reviewed but do not become cash
movement merely because they are expenses. Transfers create no second expense.

Retain one read snapshot for common journal rows, account scope and validated
transfer metadata, including counterpart legs outside the report period.
Selected-account effects sum exactly to the common movement query. Entries
outside scope, unreviewed/opening exclusions, pending source rows and unclassified
reviewed movement remain visible; no complete/certified cash-flow claim. Unknown
or future unsupported shapes remain unclassified. Later admitted refunds,
income adjustments, loan components and partial settlements must extend these
checks before their classification is treated as complete. No forecasts/charts.

Primary owns new core/GUI cash-movement modules, workspace Reports-menu wiring
and focused synthetic tests. Ledger retains sole store ownership in wider source
matching; desktop owns only that review adapter. No schema/store mutations here.
Independent integrity review covers report, snapshot and sign claims. Synthetic/
disposable profiles only; no private/1.x/profile activation or release actions.

## Result and review

New core/GUI cash-movement modules read the common active reviewed journal query
and validated transfer history within one committed snapshot. Explicit asset IDs
define scope; no account is guessed or selected by default. Category effects
classify admitted cash income/expense (including sign-aware refund/adjustment
labels when admitted); card purchases alone stay outside cash scope. Known
transfers distinguish within-scope, across-boundary and card-payment movement.
Different dates retain actual cash posting dates and clearing context. Historical
metadata outside the period adds no money. Unsupported reviewed shapes remain
unclassified; openings/unreviewed entries stay excluded.

The workspace Reports menu opens the dialog. Purpose totals and entry records
sum to exact selected-account effects; details show posting lines, reasons and
immutable source preview. Account inspection reuses the common drill-down with
the cached expected account total. Global unallocated counts, out-of-scope rows,
unreviewed/opening exclusions and classification/coverage limits remain visible.
Failures clear all values, details, source choices and inspection actions.

Independent review found permitted duplicate account names could make scope
selection ambiguous. Choice/inspection/posting/event labels now use institution,
kind and account ending, with a unique ID fallback when still ambiguous. Labels
come from the same financial snapshot; full numbers are not displayed. A GUI
regression selects the second same-named account (500), then both (800), and
checks distinct inspection choices and ID fallback. No actionable findings remain.

## Verification

Compare exact selected-account movement with common summaries; test income/
expense versus noncash card purchase, same/different-date card payments and asset
transfers inside/outside selected scope, partial periods/in-transit, correction/
withdrawal/replacement, empty/no/invalid scope, unclassified reviewed shapes,
WAL snapshot consistency, immutable source preview and failed refresh clearing.
Verify no profile writes. Run focused and relevant integration, Ruff/hooks and
independent review, plus readable offscreen UI inspection.

Windows 11 AMD64, Python 3.13.15, Qt offscreen, synthetic/disposable profiles:
the initial 11-check run passed 10 and found a test-only INSERT column omission;
explicit columns fixed the fixture. Cash/workspace checks then passed 21 in
27.87 seconds. After account-label hardening, cash/drill-down/workspace tests
passed 33 in 22.80 seconds; independent review reran those 33 in 36.64 seconds.
Coverage includes common-summary agreement, card versus cash, both transfer date
shapes and scopes, partial periods, replacement/withdrawal, unknown reviewed
shapes, strict scope, opening/unreviewed exclusions, WAL withdrawal between row
and event reads, exact source preview, corrupt-journal clearing and menu wiring.
Profile bytes remain unchanged by reads and GUI use. Primary and independent
review inspected readable 1100-by-780 offscreen Segoe UI rendering, including
amount alignment, explicit scope and qualified controls. Final V2 integration
passed 512 checks, 1,107 deselected in 317.74 seconds. Changed-file Ruff
check/format, whitespace, local links and repository hooks passed.
No owner/native/Intel/installed acceptance is claimed.

## Remaining work

Extend classification for subsequent admitted accounting shapes, then integrated
daily-workflow UX and supported-platform/release gates.

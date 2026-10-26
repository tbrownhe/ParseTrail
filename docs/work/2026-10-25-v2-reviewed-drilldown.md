# Inspect reviewed report entries and source provenance

Date: 2026-10-25. Roadmap IDs: V2-5.
Authorization: approved roadmap and continued development.
Implementation: complete.
Automated verification: focused scope, provenance and GUI checks passed.
Independent review: complete; both findings resolved and independently rechecked.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Make spending/income, monthly-budget spending and non-opening account movement
inspectable as current active reviewed journal entries over the same explicit
period/account scope. Reuse the common reviewed journal query within one read
snapshot; do not reconstruct money from source rows or invent financial scope.
Show exact selected-account effects, entry/posting details, retained correction
links and immutable source preview. Distinguish current rows from a stale parent
summary, and keep whole-profile pending/capture/coverage limitations visible.
No postings, source mutations, charts, cash-flow certification or complete-income/
spending claims. Charts/pivots remain deferred per DEC-3.

Primary owns new core/GUI drill-down modules, report-dialog integration and
focused synthetic tests. Store writer retains all profile/schema ownership;
desktop specialist owns different cash/card/repeat-review files. Independent
integrity review checks report/provenance claims. Only synthetic/disposable
profiles; no private data or release actions.

## Result and review

New core/GUI drill-down modules expose current reviewed entry effects for the
selected spending/income category, financial-account movement or independent
budget month. All monetary rows and audit links share one SQLite read snapshot.
Natural liability/income signs match common summaries. The dialog shows selected
effects, raw debit/credit postings, reasons, immutable source previews and related
original/reversal/replacement records, including links outside the selected
period and cross-source posted-repeat repair history. Related historical records
are provenance only and are excluded from current totals.

Reports provide Inspect entries and double-click navigation, plus explicit
Refresh reports. A stale parent-total notice identifies changes since the parent
summary. Empty activity is scoped recorded activity, never complete coverage.
Read failures clear rows, totals, audit details, preview choices and actions;
parent reports clear monetary/budget/position values and disable export/inspection
when common journal validation fails. Invalid global period selection preserves
the separately scoped valid budget month.

Independent review verified scope, signs, correction dates, snapshot consistency,
read-only operation and readable offscreen layout. It found malformed initial
ordinary journals could reach common totals and backups. The store owner fixed
that shared boundary in the companion interpretation-repair packet; parent and
drill-down failure states were verified against those refusals. A further review
found isolated budget/position refresh could leave known-unavailable parent
totals visible; one shared clearing helper now invalidates every displayed report
on shared profile errors, without recursive reads. No write APIs or
source interpretation are added by drill-down.

## Verification

Compare drill-down sums with common summaries, retain correction/withdrawal/date
semantics, asset/liability/income signs, monthly budget boundaries, empty/invalid
periods, stale parent notice, immutable source previews and failed refresh clearing.
Verify profile bytes unchanged. Run focused checks, relevant V2 integration,
changed-file Ruff/hooks, and inspect readable offscreen layout.

Windows 11 AMD64, Python 3.13.15, Qt offscreen, synthetic/disposable data:
the initial report/positions interaction run passed 17 checks (11.93 seconds),
and the combined repair/drill-down/common-integrity run passed 61 (74.42 seconds).
Tests include WAL concurrent correction between entry and audit reads, independent
budget scope, immutable source preview, withdrawal/fresh repost and duplicate
repair history, failed refresh clearing and valid recovery. Independent review
reproduced both unbalanced and fractional-money refusal through reports,
positions, reconciliation, drill-down and backup; already-open dialogs cleared
their old values without changing profile bytes or publishing a partial backup.
The 1040-by-700 dialog was inspected offscreen; no owner/native acceptance is
claimed. Final focused/integration and hook results follow before closeout.

The final parent/drill-down/positions interaction run passed 20 checks in 23.80
seconds. Independent review passed 36 final affected checks in 43.17 seconds
and an earlier 103-check broader run in 143.80 seconds. Both identified findings
were independently reproduced as fixed; no actionable findings remain in scope.
Final V2 integration passed 393 checks, 1,107 deselected in 244.61 seconds.
Changed-file Ruff check/format, repository hooks, whitespace and local links
passed. No owner/native/Intel/installed acceptance or release action occurred.

## Remaining work

Cash-flow classification, remaining accounting safeguards and consolidated human
UX/platform/release gates.

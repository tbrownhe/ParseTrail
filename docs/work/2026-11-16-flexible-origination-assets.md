# Flexible financing destinations and tangible assets

Date: 2026-11-16. Roadmap IDs: V2-UX, V2-3/4/5.
Branch/components: feature/client-financial-insights; local desktop, evidence and ledger.
Authorization: owner-approved next refinement round; disposable development only.
Implementation: complete; fresh isolated candidate prepared.
Automated verification: focused financial/evidence/desktop and combined native checks pass.
Design verification: pre-implementation journey and final native screenshot recheck passed.
Independent review: financial/evidence review passed after two verified fixes.
Owner acceptance: pending integrated candidate. Release authorization: not granted.

## Scope and controlling decisions

Record exact loan funding independently of acquisition cost and estimated value.
Financial-account destinations remain unresolved until separately reviewed in
Transfers. Explicit confirmation that financing funded a tangible asset may
allocate the exact financed portion without a bank/purchase counterpart; full
acquisition cost remains unknown. Never infer downpayments or balancing money
from an estimated value. General tangible assets use nicknames, dated nonposting
values and optional signed annual value change; blank future rates stay unknown.
Origination-created values default to the source activity date.

Support either sign of liability transfer and exact debt-to-debt matching while
retaining separate fees and legacy settlement limits. Include protected Loan
interest from fresh-profile creation. Precisely classify known legacy Citi
summary/disclosure monetary content; unknown amounts still require review.
Advance to the next incomplete statement only after successful initial posting
completes the current statement, preserving source/correction/report context.

One writer per file: ledger owns profile/schema/origination/resolution/products,
financial read/export/category services and financial tests; evidence owns legacy
Citi classification and warning tests; desktop owns origination/tangible dialog
implementation after design; root owns workspace integration, contracts and this
record. Independent design, integrity and integrated acceptance review follow.

Only public synthetic fixtures and disposable profiles may be mutated. Existing
owner-populated candidates remain private and untouched. The single explicitly
named Citi original may be read in memory, without source text in logs/Git. No
archive enumeration, private Wells input, migration, server, signing, publication
or daily-profile activation is selected. Unknown Wells origination formats remain
unsupported until defensible source evidence is available.

Observable UX criteria: discover loan destination and exact amount, distinguish
financing from estimates and full cost, record with absent bank coverage, find
remaining matching work in Transfers, create generic assets with appropriate date
and signed rate, and complete consecutive statements without unnecessary clicks.
Inspect actual Qt screens and cancellation/correction/repeated workflows; tests
do not attest owner acceptance or another platform.

## Result and review

Baseline: da1fde0, clean working tree. Approved service proposal: fresh schema27,
generic tangible_asset product, separate loan-funding API and optional expected
destination, explicit exact-principal tangible allocation. Existing finite full
acquisition API remains separately supported. No inferred cash or purchase cost.

Financing now posts the exact borrowing independently, with optional financial
destination metadata or explicitly confirmed tangible allocation. Nickname-only
tangible creation and independent dated estimates support signed annual changes;
origination supplies the default date. Card transfers admit either sign and later
exact debt-to-debt/debt-to-asset matching. Loan interest is seeded and protected.
Initial review has a separate successful-post handoff; completion advances only
after a fresh summary and retains an announced route back. Source-return contexts
are preserved. A late Transfers refresh previously consumed the return-row target;
the integrated test reproduced this and the target now survives the pending read.

Finite legacy Citi roles distinguish source summaries/disclosures without changing
activity, amounts, dates or raw fragments. A final dollar-numeric inventory also
surfaced whole-dollar disclosures omitted by the previous decimal-only inventory;
final role classification and counts are checked below. Standalone amounts without
established grammar require review. Independent balance stays verified; capture
remains unverified. Engine identity advances; retained evidence and exact source
retry remain immutable. No missing reported balance-transfer row is invented.

Final memory-only source recheck: 4 unresolved monetary lines (detached repayment
illustration amount, coupon amount, savings-region amount, unproved explanatory
line). The initial 15-line inventory had excluded nine whole-dollar disclosures;
the final inventory includes those before classification. Twenty finite summary,
payment, credit-term, repayment-example, interest-detail and APR roles are
informational. Whole-dollar non-activity credit terms are legitimate; this does
not broaden financial activity or period-total money grammar. Unknown numeric
dollar content and malformed financial amounts still require review/refusal.
The final extension passed independent altered/context/extra-money counterexamples
without changing financial values/fragments or capture qualification.

Independent integrity review found a stale export heading describing signed rates
as decline and standalone truncated dollar-numeric input escaping monetary
inventory. Both were fixed and independently rechecked. Extra unknown/truncated
amounts remain unresolved; dated parallel incomplete money refuses admission.
Independent mismatch/account/date refusals, source-use/event tampering through
common reads, unlink/withdraw/repost, no extra expense and verified backup passed.
No remaining actionable financial/evidence findings were reported.

Final design review identified ambiguous old/new statement names, success text
overwritten by estimate refresh, repeated financing copy, enabled empty-state
controls and unexplained unknown projected values. The integrated fixes include
both statement periods and a return action, retain distinct asset/estimate save
acknowledgements until the next edit/selection, consolidate financing qualifications,
use a smaller default dialog, disable inapplicable empty controls and explain unknown
values in tooltips. Focused tests reproduce acknowledgement/empty-state behavior.
The independent design recheck inspected the updated default-size, saved, empty
and completion screens and closed all five findings. Tooltip explanation was
confirmed in code; actual hover rendering was not captured. No remaining
significant design issue was reported in the reviewed scope.

## Verification

All commands use locked `client/.venv/Scripts/python.exe`,
`PYTHONPATH=.;client/src;client` and `-p no:cacheprovider`; client conftest isolates
home/null keyring. Offscreen checks use `QT_QPA_PLATFORM=offscreen`; native checks
use `--journey-native --journey-artifacts=scratch/<synthetic-root>`.

- Financial author: loan-payments/transfers/ordinary-batch 67 passed;
  funding/origination/resolution 22 passed; final funding suite 10 passed,
  including exact financing versus independent value, atomic link/insert failures,
  physical clone/stale proof, separate refinance interest and corrupt backup refusal.
- Evidence author: bounded PDF/source/catalog/family checks 102 passed; root
  legacy-Citi/warnings regression 46 passed after standalone truncation fix.
  Final finite whole-dollar disclosure extension and independent recheck: 60 passed.
- Root integration: review advance/core journey/Transfers/ordinary batch/import
  accounts/profile store 77 passed. Category/review cues/loan-payment dialog 25
  passed after updating seeded-category and earlier initial-review/transfer
  expectations. The category creation regression also passes after hiding already
  included optional built-ins.
- Desktop author: final origination desktop/inline account/anchor checks 44 passed;
  initial native 14 passed, final native image refresh 4 passed, raw exits 0.
- Root after final design fixes: origination desktop and review advance 26 passed.
  Final native render recheck: 7 passed, 20 deselected, raw exit 0; includes actual
  default 960x540, both saved acknowledgements, empty controls and both periods.
- Root combined native: review advance, financing integration, Transfers and
  workspace lifetime 18 passed, raw exit 0 with normal GC. This includes negative
  card staging, confirmed financing/receipt match, source/Transfers return,
  correction/report contexts and cancelled review.
- Independent integrity: initial focused 61 passed, updated selection 47 passed,
  verified-backup corruption check 1 passed, plus independent synthetic refusal
  and tampering scenarios. These counts overlap other suites and are not additive.
- Ruff check/format check passes all 36 changed Python files; diff whitespace clean.

Inspected synthetic native artifacts: `scratch/flexible-funding-native-final/`
(financing pending/saved at 1050x700 and 1280x800, generic asset with long nickname
at 760x620, empty origination at 760x560); `scratch/fund-root/` (next-statement
announcement, negative-card staging, financing and repayment relationships).
Windows AMD64, Python 3.13.15, Qt 6.11.2, Segoe UI 9, DPR 1 and 96 DPI.
Qt software events and screenshots verify rendered behavior, not direct OS input,
uncoached human understanding, owner acceptance or macOS/installed behavior.

Fresh acceptance completed the label-led borrowing, optional asset, cancellation,
saved financing and later checking-receipt journey in a separate disposable native
process. It rejected negative valuation inline, retained a blank-rate future value
as unknown, explained expected destination versus actual posting, and discovered
Transfers' manual unreviewed counterpart choice. Independent persistence check found
exactly the lender and later bank entries with zero clearing, no duplicated principal.
Automatic advancement caused one wrong turn on reopening; the completion banner and
return action explained it. Signed-card discovery reached Transfer/card repayment;
full card/ordinary completion and correction were not attempted in that goal run
(separately covered by root scripted native checks). Setup helpers exposed part of
the origination test beforehand, so discovery is qualified; imported-fixture setup
does not verify import discovery. Initial modal polling deadlocked in its test
harness and required terminating that disposable process. The replacement harness
reached raw Qt exit 0 with normal GC; an earlier denied CIM query left its enclosing
shell exit 1. No application shutdown crash was observed. Artifacts are synthetic
`scratch/fund-accept-20261116/`, before the final wording/acknowledgement fixes.
Actual QObject destruction-thread tracing, hardware-input and human comprehension
remain untested. No additional material product finding arose in that attempt.

Code commits: `788f7c4` financial services, `4bb4ba3` evidence/warnings,
`5f7e262` desktop journeys. Normal repository commit hooks passed for each.
Current ledger, unified-store and parsing contracts and roadmap/TODO were updated.

Fresh candidate: `scratch/v2-owner-fresh-20261116-e3184fdd/`, with
`Open-workflow-test.cmd` and `START-HERE.txt`. It contains no imported documents,
financial accounts, budgets or journals; the only account row is protected Loan
interest. Schema 27, 23 public signed-development declarations, 312 pinned public
runtime files from `5f7e262`; ephemeral test signing key discarded. New isolated
home/catalog/preferences and manifest verification; no old profile/data copied.
Pinned native startup smoke passed with Windows plugin, six sidebar steps,
import enabled, empty documents, unchanged profile digest and raw process exit 0.
The app is closed and the launcher preserves this candidate across reopen. Earlier
owner-populated test folders were not read or modified (only two explicitly public
preparation-helper source files were reused). After handoff, this new candidate
is private if the owner imports statements; no automatic deletion/reset.

## Remaining work

Owner test of the prepared candidate, broader native-input/accessibility,
Intel/installed and release acceptance remain separate gates. Unknown Wells
origination formats, unsupported source classifications and source-defect repair UI
remain outside this finite pass. No implementation or review finding remains open
within the admitted workflow scope.

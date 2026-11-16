# Loan origination and separate transfer resolution

Date: 2026-11-16. Branch: feature/client-financial-insights.
Authorization: owner approved the discussed changes after testing the November 15
candidate, including a separate Transfers sidebar task. Implementation: complete.
Focused agent verification/design/integrity review: passed. Owner acceptance of this pass:
pending. No release, production signing, publication or daily-profile activation.

## Scope and decisions

Baseline `19a0a2a`, clean working tree. The owner-populated
`scratch/v2-owner-fresh-20261115-a34ed800` and earlier profiles, logs, originals
and captures are private and remain untouched. Use synthetic disposable profiles,
ephemeral fixture catalogs, isolated home and null keyring. No root `.env`.
The prior read-only named Capital origination check established positive observed
Amount Financed/principal, absent interest, unknown opening and separate printed
closing principal. No further private statement access is needed.

Approved outcomes:

1. Sidebar order Documents, Accounts, Review, Transfers, Budget, Reports. Review
   handles source interpretation/posting; Transfers resolves relationships later.
   Preserve source, row, draft and return context. Never force matching after review.
2. Reviewed loan principal/printed interest can post against unresolved clearing
   without bank evidence. Known source dates remain independent. Generic explicitly
   reviewed transfers can post their observed side independently. Each unresolved
   item stays visible even when aggregate clearing cancels. Later matching posts
   only missing source legs or links two posted legs without duplicate money.
   Automatic proposals require explicit transfer/loan designation; manual selection
   remains separately explicit. Final match confirmation remains required.
3. Amount Financed opens a distinct origination workflow. Destination is required
   for complete accounting; evidence import may remain pending. Vehicle accounts
   carry independently entered acquisition value/date. Exact value equal to financing
   is supported; a larger value requires one evidenced bank downpayment equal to the
   difference. Complex trade-ins/fees/incomplete funding stay pending with exact
   explanation, without fabricated balancing entries or asset value. Dated vehicle
   values and optional annual estimated decline are separately authored nonposting
   valuations; never silently create monthly budget expense.
4. Loan controls fit actual 1050×700 and 1280×800. Specific missing prerequisites,
   editable evidence-derived references, human-readable effects and keyboard-accessible
   Show details/Hide details replace cramped tables and collapsed checkboxes.
5. Import warnings have two classes: Informational and Requires review. Date
   assumptions and generic unverified full-page capture are informational. Unverified
   statement monetary balances, actual mismatch and unresolved amount-bearing content
   require review with specific scope/location. Unavailable verification is distinct
   from failed arithmetic. CSV exports do not invent absent statement balance checks.
   Posting-date permission remains independent. Known account assignment need not
   be reconfirmed because a content warning requires preview. No defect-repair UI now.
6. Zero-value rows support explicit purpose/category/reason review without zero
   journal entries, clearing ordinary pending state while retaining evidence/history.
7. PDF-import-created institution/product metadata is locked in service and UI;
   nickname remains editable. Parser-established and authored provenance stay distinct.
8. Stage selected is disabled when all exact selected proposals and captured shared
   reason are unchanged. New/changed rows, dates or shared reason re-enable staging.

## Ownership and implementation contract

Primary owns conversation, work record/contracts, workspace/sidebar, new Transfers
hub and origination/tangible-asset dialogs, import atomic integration and nav tests.
Ledger exclusively owns schema (fresh revision 26, no migration), financial core,
loan/transfer/origination/zero-review/identity-lock APIs and headless tests.
Desktop owns ordinary/loan/import/account review widgets and specific UI tests.
Evidence owns import-warning DTO/policy, recognition projection and warning rendering.
UI/UX established the journey above before implementation and will inspect renders.
Independent integrity review and fresh acceptance follow integration. No specialist
delegates, commits or modifies another writer's assigned files. Native focus slots
are serialized. Existing owner candidates stay pinned and unchanged.

Service contracts: loan manifests permit a missing bank leg; resolution snapshots
provide individually identified posted/unposted sides and explicit links. Matching
revalidates profile/basis/source uses under one write lock. Origination previews bind
source principal, authored acquisition details, actual downpayment where required and
destination. Atomic PDF import locks metadata only after its source is retained.
Mixed ordinary batches capture zero reviews, category postings and unresolved-transfer
postings together. Common reads/backup validate new histories and source consumption.

## Observable verification criteria

An unfamiliar reviewer can identify account/period/scope, what is saved/posted and the
next unmet prerequisite. Lender-only payment posts exact principal/interest and gross
clearing, survives restart, then resolves without another interest/principal posting.
Two independently posted sides can be linked without new journals. Cancellation,
stale/retry/withdrawal and source corruption preserve exact history and unique use.
Origination is visibly separate from repayment and asset valuation; unknown destination
or missing funding cannot be reported as completed acquisition. Zero review has no
money effect. Locked identity and duplicate staging behave as described. Main actions,
headers, long names and details fit both target sizes with keyboard operation and
normal GUI-thread destruction/GC. Record raw process exits and actual platform.

## Integrated result

All selected outcomes implemented within the explicit finite funding policy.
Implementation commits with normal hooks: `cfc62b0` financial services/schema,
`b6d9145` warning policy and `e7d35f5` integrated desktop workflows. Documentation
and owner-test preparation follow together.
Review and Transfers are distinct persistent sidebar tasks in the approved order.
Loan review posts lender-only principal/interest against clearing, with editable
evidence-derived references, exact previews and visible date assumptions. Explicit
Transfers handoff closes the modal before navigating, focuses its source side and
preserves source-return selection, filter and valid drafts. Saved match inspection
names both accounts, dates, amount, match note and counterpart evidence. Corrections
are secondary disclosures with separate blank reasons. Matching already-posted sides
is link-only; deliberate unreviewed alternatives have a distinct manual action and
ownership confirmation. No automatic posting occurs from a proposal alone.

Origination recognizes positive Amount Financed separately from repayment. Vehicle
creation/dated valuation is nonposting and independent of the entered acquisition.
Exact financing or financing plus one evidenced downpayment posts each actual leg at
its own date; unknown prior openings remain qualified. Active acquisition inspection,
reasoned withdrawal/inverses, re-review, backup and profile-bound confirmation work.
Estimated annual decline uses Decimal projection separately from journals/budgets;
blank rate preserves an unknown later estimate, explicit zero permits a flat estimate.

Zero rows support persisted category/reason review, fresh correction/withdrawal and
reviewed filtering with no zero journal/allocation/budget effect. Mixed category,
zero and transfer effects are atomic and independently counted in confirmation.
Unchanged staged choices/reason disable Stage; edits or new rows re-enable it.
Card transfer dates retain their source candidate and explicit date permission;
switching from an edited category date explains its reset instead of ignoring it.
PDF-import-created institution/product are locked after complete binding inside the
import transaction and across backup; nickname remains editable. Vehicle classification
cannot be changed into cash-account metadata after value/acquisition history.

Warnings visibly separate Informational from Requires review. All rows participate,
including rows beyond the bounded preview. Specific reasons, codes, locations and
occurrence counts remain discoverable; no parser/declaration or repair override was
introduced. Known automatic assignments bypass account setup even when the content
preview is required. Monetary verification unavailable versus mismatch remains distinct.

Reports retain unresolved-side counts even when clearing nets zero. These counts use
actual leg dates and current relationships, without claiming historical match dates.
Multi-date loan items preserve every assumed date, use all dates for matching windows
and count once when any actual leg satisfies the complete report bounds. Exports retain
resolution legs/links, origination events, zero decisions and value history separately
from the selected journal period. Source/report drilldown supports bank-free loan events.

## Findings closed

Independent integrity identified and rechecked missing-leg retry identity, replay of
wider date windows, physical-profile binding before origination retry, same-date valuation
A→B→A correction, and multi-date report inclusion. Exact retry, retired-link refusal,
source-use tamper refusal and atomic failure rollback remain enforced. A lender-only
report drilldown dereferencing an absent bank was fixed and independently reproduced
successfully afterward. Missing decline rate no longer silently projects a flat value.

Design/native review identified modal handoff remaining open, conditional rather than
exact match effects, missing saved-counterpart context, cramped/overheight loan layout,
invisible source/account scope and lost date qualifications. All P1/P2 findings were
closed against current rendered captures. The fresh task reviewer found a minor source
return status incorrectly referring to Reports; it now names Transfers, with a native
regression verifying the return action and filter preservation.

## Verification

Windows x64, Python 3.13.15, Qt 6.11.2 native Windows plugin or explicitly offscreen,
Segoe UI 9 pt/96 DPI. Disposable public synthetic sources/catalogs, isolated home/null
keyring. Tests below overlap and must not be summed as one suite. Normal GC/assertions
retained; no retry-to-pass workaround or production/private input was used.

- Financial integration: **100 passed in 160.42s**, raw exit 0, covering ordinary batches,
  loans, transfers/planning, positions and workbook export. Final new-workflow financial
  selection **13 passed in 35.57s**; late date/estimate/report selection **13 passed in
  20.69s**. Schema 24/25 refusal **2 passed**, incompatible bytes unchanged.
- Warning/recognition/automation: **46 passed**; final focused warning suite **11 passed**;
  selected pilot admission/decoder/source-output suites **78 passed**. Independent
  warning checks **23 passed** plus hidden-sixth-row unknown-money refusal and benign
  informational-only automatic-import probes.
- Desktop integration: **70 combined offscreen passed in 174.73s**, raw exit 0. Native
  lender/ordinary/zero/metadata/pending sequence **15 passed in 60.12s**, raw exit 0.
  Late vehicle/date-override and origination landing-state checks passed separately.
- Primary source/report/Budget/Transfers integration **20 passed in 36.17s**. Final
  one-process native sequence **34 passed in 56.61s**, raw exit 0: origination, vehicle
  values, exact match dialogs, actual main-window modal handoff, ordinary/zero/metadata
  review, original/PDF/dropdowns and core journey. After final return-filter refinement,
  affected native checks **4 passed, 4 deselected in 8.58s**, raw exit 0.
  The final Transfers suite including child-review/global-menu preference sync
  passed **9 offscreen cases in 16.31s**, raw exit 0.
- Main surfaces inspected at actual **1050×700 and 1280×800**; vehicle manager 880×620.
  Full manual-transfer dialog and original viewer retain their independently recorded
  dimensions; they are not claimed as 700-high acceptance. Current match/loan headers,
  evidence actions, assumed dates, saved counterpart and origination/value differences
  received final design review with no remaining P1/P2 finding.
- Independent integrity verified actual synthetic PDF account import/lock/binding and
  backup, clone refusal, exact origination/downpayment/source dates, no acquisition
  expense/invented opening, corrupt source-use refusal, mixed rollback/stale-zero guards,
  export/reopen, multi-date windows/counts and optional-rate unknown/zero distinction.
  Final bounded checks and independent probes reported no actionable findings.
- All **46 changed Python files** pass Ruff check/format; diff whitespace checks pass.
  Normal repository commit hooks remain enabled.

Artifacts: `scratch/loan-resolution-desktop-20261116/`,
`scratch/transfer-resolution-root-20261116/`, `scratch/resolution-root-20261116/`,
`scratch/resolution-final-native/`, `scratch/resolution-final-context-native/` and
`scratch/resolution-acceptance-20261116/`. These contain only disposable synthetic data.

## Independent task attempt and acceptance limits

A fresh acceptance specialist imported genuine public synthetic PDFs through the
signed catalog/account workflow, created a separately valued vehicle, posted the
supported acquisition and lender-only payment, found Transfers and matched later bank
evidence, reviewed a zero Fee, checked unchanged Stage readiness and attempted locked
metadata edits while saving a nickname. Persisted readback confirmed two acquisition
entries plus one lender entry and only one later bank entry; zero review added none.
An independent valuation remained different from acquisition cost. A second native
process reopened that same synthetic workspace and verified matched qualifications,
source return context, metadata locking and saved results. Both processes exited 0.

Discovery qualification: fixture-helper extraction exposed adjacent import/account
control helpers, so import discovery was partly coached. Subsequent new journeys were
chosen from rendered UI without new-feature implementation/test assertions. Inputs used
Qt software events and direct QDateEdit fixture date entry; this is not physical-input
or human-comprehension evidence. Owner acceptance, screen readers, varied scaling,
large lists, other platforms, installed/offline checks and release remain unperformed.

No selected implementation item remains. Complex trade-ins, financed extras and other
funding shapes remain explicitly incomplete under the agreed bounded policy; source
defect repair is deliberately unselected. Prior owner candidates remain unchanged and
private. Schema 26 requires a fresh development profile; no migration is provided.

## Fresh owner workspace prepared

Prepared `scratch/v2-owner-fresh-20261116-90abd782/` with `Open-workflow-test.cmd`
and `START-HERE.txt`, ready for manually selected owner statements. Twelve authored/
financial tables were checked empty, including accounts, sources, observations,
budgets, journals, pending/resolution/origination/zero/value histories and PDF identity
locks. SQLite integrity passed. No owner statement or populated profile was selected.

A 311-file public runtime snapshot/digest manifest pins application and worker code
to `e7d35f5`. The 23 public declarations use a fresh ephemeral development signature;
only public trust remains. Profile/catalog/preferences/app-home/null keyring are local
to this new directory; no production trust or daily-profile activation. Usual defaults
remain Always previews and default-off abbreviated matching/assumed posting dates.

The actual pinned helper passed native Windows startup with display suppressed:
ready, zero Documents, Import enabled, six sidebar tasks in the approved order,
profile digest unchanged and raw Qt/process exit 0. The empty screenshot was inspected.
The app was closed after verification. Reusing the launcher retains the owner's work;
there is no automatic reset/deletion. Earlier private candidates remain untouched.

Privacy boundary after handoff: the new folder may contain owner financial data.
Do not enumerate/read its profile, logs, originals or captures without new task-specific
authorization. Source preparation helpers contain no private inputs and do not authorize
inspection of subsequent owner imports. This preparation is not owner acceptance.

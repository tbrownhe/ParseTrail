# Engineering acceptance record

This document preserves durable acceptance evidence previously embedded in the
July-October 2026 TODO. It records completed work, not a new live-system audit.
Dates, release IDs, and evidence locations are retained as recorded; old runtime
identifiers are historical references, not instructions to reactivate them.
Current unfinished work belongs in [TODO](../TODO.md).

## Loan bank-match correction — October 3, 2026

The owner authorized correcting confirmed loan-payment matches. The
[service and review UI](../devtools/ledger_audit/LOAN_PAYMENTS.md#correcting-a-bank-match)
replace only the bank movement of an active fixed-category Capital One payment.
Loan payment/interest source components, principal, dates and the Loan interest
built-in remain fixed. The previous bank movement becomes unallocated evidence
requiring review; it is not deleted or refunded. A correction reason is required.

The kernel now supports whole-event reversal/replacement when the number of
journal entries changes between same-day and different-date matches. It checks
the entire active event, validates collective evidence release and replacements,
preserves event identity and original reversal dates, then writes everything
atomically. Optional append-only bundle tables supplement single-entry corrections.
Consumption, entry status and reconciliation recognize both forms of supersession.
New account mappings and correction history share the same transaction. Exact retries
remain no-ops, including after another correction; stale/competing requests fail.

The UI previews previous/replacement bank dates and unchanged loan/expense totals.
Input changes invalidate previews and confirmation defaults to Cancel. Confirmed
payments show the current match; Previous bank matches retains superseded choices
and reasons. Earlier category-choice workspaces remain readable, but these corrections
require a fixed-category workspace. Source-component correction remains a separate scope.

Fourteen new service tests cover chained corrections, immutable history, unchanged
evidence, reopen, reconciliation invalidation, competing allocations, stale/tampered
plans, pending expense rejection, partial-event refusal, rollback after inserted
reversals/replacements, and transitions in both directions across month boundaries
with zero and nonzero interest. Six new UI tests cover cancel/apply/reopen, history,
selection/filter/date-window/note invalidation and stale allocation refusal.
The complete Windows suite passed **1,032 tests, 3 skipped** in 205.49 seconds
with offscreen Qt and process-only `RemoteSigned`. Ruff lint/format passed across
**249 files**.

The archive-sized offscreen exercise passed initial posting, correction preview,
window-close/final-confirmation cancellation, apply and reopen. Its screenshots
were inspected. A separate read-only audit compared final balances with the active
replacement, verified unchanged source/category tables against accepted candidates,
confirmed release of the previous bank movement and passed SQLite integrity/foreign
keys. Private source details, amounts, reports and screenshots remain ignored.
A fresh owner workspace contains no previous sample decisions. **Windows native
correction acceptance is pending.** No live database, parser, dependency or server
changes occurred, and report cutover remains closed.

## Built-in ledger categories and enforced loan interest — October 3, 2026

The owner accepted the loan-payment workflow and requested fixed built-in categories
alongside user-defined categories. The shared catalog starts with **Loan interest**,
using a stable semantic key and fixed expense type. User-defined names/IDs remain
separate; a matching display name never overrides the built-in or merges history.
Catalog reads are read-only, and posting installs account mappings atomically.

Loan payment previews no longer take a category argument or show a category picker.
The service requires the catalog's Loan interest account for nonzero interest and
refuses conflicting mappings or modified previews. An explicit zero component
still creates no expense posting. The rule version changed so an earlier preview
must be regenerated. Earlier saved decisions remain immutable and display their
actual original category; they are not silently relabeled.

Ordinary expense classification/corrections expose built-ins alongside custom
categories, marked “built-in” in the selector. Mixed category splits retain exact
money, deterministic ordering, correction history and reopen selection. Income
workflows cannot use expense built-ins. Loan components remain excluded from
ordinary category corrections.

The focused categories, loan, expense and income suites passed **121 tests**.
The complete Windows suite passed **1,012 tests, 3 skipped** in 244.59 seconds
with offscreen Qt and process-only `RemoteSigned`; Ruff passed across **245 files**.
The archive smoke passed preview/cancel/post/reopen with the fixed category and
its screenshot was inspected. A read-only check of the preceding disposable
workflow confirmed that its original category still displays accurately and its
database hash is unchanged. Native acceptance applies to the prior workflow;
the new fixed label/category selectors have automated coverage. The live database,
server and dependencies are unchanged.

## Capital One loan payment and interest workflow — October 3, 2026

Following owner acceptance of the read-only loan view, the
[bounded payment service and UI](../devtools/ledger_audit/LOAN_PAYMENTS.md) admit
only explicitly selected Capital One Auto payment/interest bundles. A matched
bank payment transfers its full amount to the loan; the separate source interest
component adds expense once. Net principal reduction is payment minus interest.
Different source dates use clearing, including receipts preceding bank outflows.
All journal entries, new observations, mappings and the immutable decision save
atomically. No opening balance or loan reconciliation is inferred.

Versioned parser contracts, exact amounts, eligible source memberships and a
single unshared interest component are required. Missing interest is not zero;
an explicitly zero component remains evidence without a zero posting. Pending
ordinary expense/refund interpretations require explicit rejection, and allocated
movements block confirmation. Category annotations and original evidence survive.
Read-only previews, optional notes with a standard reason, cancel-safe confirmation,
stale-input refusal and idempotent retries are covered. Confirmed payments have
a persistent status tab independent of the candidate date window. Other loan
parsers, financing, synthetic origination, openings and corrections remain separate.

Windows verification passed **1,003 tests, 3 skipped** in 214.30 seconds with
offscreen Qt and process-only `RemoteSigned`. The **29 new focused tests** cover
payment/interest accounting, cross-month clearing in both date orders, source
contract refusal, ambiguous/missing/shared/zero components, category validation,
competing allocations, tampered previews, rollback after partial insertion,
overlapping statements, multiple bank matches, exact retries, unchanged evidence,
cash-reconciliation invalidation and GUI cancel/edit/filter/status/reopen behavior.
Ruff lint/format passed across **243 files**.

The archive-sized smoke exercised preview, window-close cancellation, final
confirmation cancellation, posting and reopening; screenshots were inspected.
A separate disposable audit previewed and posted the supported unambiguous
bundles, checked account totals against source payment/interest arithmetic,
balanced entries, exact retries, SQLite integrity and reopen persistence. Source
tables/categories and accepted candidate/fresh/legacy file hashes stayed unchanged.
Private values, identifiers, reports and screenshots remain ignored. A separate
owner workspace starts with no sample decisions. The owner subsequently accepted
the Windows workflow and requested fixed categories, recorded above.
The active database, parsers, server, dependencies
and report cutover are unchanged.

## Read-only loan evidence readiness — October 3, 2026

After the owner accepted the cash-income workflow, the next L1 checkpoint inventoried
loan source evidence before admitting it to the ledger. The
[loan-readiness service and view](../devtools/ledger_audit/LOANS.md) expose loan accounts,
source balance equations and distinct movements, with source membership and recorded
parser manifests. They distinguish principal/register balance meaning, derived endpoints,
assumed periods and activity ranges. Equation agreement never certifies independent
reconciliation or coverage. This checkpoint does not check cross-statement continuity.

Payment, interest, financing, purchase/asset-funding and capitalized-interest hints are
explicitly unreviewed. Synthetic Wells Fargo origination retains estimated provenance;
the owner's parser-change deferral remains in force. Missing/failed sources, malformed
memberships, out-of-period rows and unsupported parser/account/currency contracts remain
visible or are refused. Overlapping membership never duplicates account movement totals.
No observations are admitted, interpretations confirmed, loan postings proposed, parser
files altered or report cutover enabled.

The private archive-sized report reproduced identically in independent output folders;
accepted plan/fresh/legacy input hashes remained unchanged. The offscreen view passed
selection, text filtering, detail clearing and close across all three tabs. Screenshots
were inspected. Archive inspection exposed an interest-description/purchase-hint overlap;
the final rules prioritize interest and have a regression for “Interest Charge on Purchases.”
Private account details, amounts and screenshots remain ignored. The owner accepted
all three tabs, clear hints and reopening on Windows on October 3. No states were
changed because this view intentionally has no decision or posting controls.

Windows full-suite verification passed **973 tests, 3 skipped** in 199.21 seconds with
offscreen Qt and process-only `RemoteSigned`. After the final hint-ordering and detail-view
refinement, the focused loan suite passed **21 tests**, including the additional regression.
Coverage includes exact money, parser provenance, synthetic/financing limits, overlapping
evidence, missing/failed sources, date/balance exceptions, malformed membership/periods,
non-USD display, checksum refusal, inactive-source/overwrite guards, unchanged source bytes,
deterministic reports and GUI selection/filter behavior. Ruff lint/format passed across
**238 files**. No dependency, server, active-profile or financial posting change occurred.

## Positive cash income receipts and category corrections — October 3, 2026

The owner accepted expense rejection/recategorization/persistence and authorized continued
ledger work. The [income service and review window](../devtools/ledger_audit/INCOME.md)
explicitly classify positive, wholly unallocated checking/savings receipts into existing
income categories. Inventory eligibility does not imply income; transfers, loan proceeds
and refunds need their own treatment. The posted amount is exactly the observed receipt,
without inferred gross pay or deductions. Card credits, outflows and other account types
remain outside this income scope.

Read-only previews bind source facts, proposal history, date provenance, category mappings
and exact split amounts. Posting atomically creates required income mappings, a balanced
reviewed journal, one full source allocation and append-only interpretation history.
Pending ordinary proposals block the action until explicitly rejected; earlier rejection
and category annotations remain preserved. New ordinary income notes are optional;
reinterpreting rejected evidence and later corrections require explanations.

The UI requires an explicit income-category choice and displays income amounts positively
while storing income credits with the correct negative journal sign. Category corrections
preview zero net change in income and cash received, then atomically reverse and replace
the journal. Active/superseded history, retry and reopen retain original evidence and
interpretations. Concurrent allocations, changed review state and tampered previews are
rejected; preview edits and cancellation leave no posting.

An archive-sized offscreen workflow passed income preview/cancel, cancelled confirmation,
posting, correction preview/cancel/apply, active/superseded history and reopen. Screenshots
were inspected. The fresh owner copy contains the unchanged candidate tables with no
decisions, postings, allocations or income interpretations; integrity and foreign-key
checks passed. Private source details and screenshots remain ignored. Sample decisions
are disposable workflow exercises, not financial approvals. The owner accepted the
Windows workflow and persistence on October 3 and authorized continued ledger work.

Windows verification: **953 tests passed, 3 skipped** in 200.91 seconds with offscreen
Qt and process-only `RemoteSigned`. **20 new service cases** cover income signs and exact
splits, excluded scopes, optional/required reasons, prior refund rejection, competing
transfer/expense postings, partial consumption, stale/tampered plans, mapping conflicts,
rollback, correction history, read-only inventory and retry/reopen. **4 new GUI cases**
cover preview/cancel/post/correct/reopen, positive income display, category selection,
required correction reasons, exact amounts, preview invalidation, rejected history,
stale transfer handling and filter clearing. The focused service suite passed **59 tests**;
the combined new/existing editor suite passed **24 tests**. Ruff lint/format passed
across **234 files**.

The new income services reuse the tested category split, interpretation transaction and
correction machinery. No new dependency, server interface, active-profile migration or
financial report cutover was introduced. The isolated workspace creates its append-only
income interpretation table on first posting. Negative income adjustments and richer
payroll interpretations remain separate scopes.

## Unposted expense/refund interpretation service and UI — October 3, 2026

After accepting the correction editor, the owner authorized the next ledger chunk.
The [interpretation service and UI](../devtools/ledger_audit/EXPENSE_INTERPRETATIONS.md)
explicitly classify wholly unallocated eligible cash/card evidence without an ordinary
proposal, or after explicit rejection of that proposal. No expense classification is
inferred from inclusion in the list. Pending proposals, source exceptions, other account
types and partially/wholly allocated evidence remain outside this workflow.

Exact category splits preserve the complete source movement, date, description and event.
Ordinary new classifications have an optional note; reinterpreting a rejected proposal
requires a reason. Preview binds the source/proposal state, date provenance and category
mappings. Apply rechecks these inputs and atomically saves category mappings, one balanced
reviewed journal, evidence consumption and an append-only interpretation plan. Exact
retries survive reopen and later corrections without duplicating or resurrecting journals.
Source evidence, verified annotations and original rejection history are preserved.

The new Unposted movements tab provides searchable unclassified/rejected rows, provenance,
prior rejection/category details and explicit category selection. Preview reports the
expense/refund and financial movement being added. Form edits invalidate preview;
cancellation and closing write nothing. Posting selects the active entry in the accepted
correction editor and removes it from the unposted list. Historical proposal decisions
remain distinct from current postings.

The archive-sized offscreen exercise passed rejection, preview/cancel, cancelled final
confirmation, posting, history and reopen; screenshots were inspected. A fresh owner copy
preserves all original candidate tables and starts with no decisions, journals, allocations
or interpretations; integrity and foreign-key checks passed. Private source identifiers,
amounts and screenshots stay ignored. Sample choices are workflow tests, not approvals of
the owner's financial history. The owner accepted Windows rejection, recategorization
and persistence on October 3 and authorized continued work.

Windows verification: **929 tests passed, 3 skipped** in 173.28 seconds with offscreen
Qt and process-only `RemoteSigned`. **18 new service cases** and **5 new GUI cases**
passed; the focused new/existing editor suite passed **20 tests**. Ruff lint/format
passed across **230 files**.

The focused tests cover expense/refund signs, optional/required reasons, exact splits,
read-only preview/inventory, scope rejection, stale/tampered plans, competing transfer and
partial postings, duplicate interpretations, rollback including schema/category creation,
preserved source/category history, retry/reopen, correction chains and reconciliation
invalidation. GUI tests cover explicit category choice, preview invalidation, cancel/post,
stale transfer handling, filter clearing, history and persistence. The isolated workspace
gains an append-only interpretation table on first posting; no active-profile migration,
dependency, server change or financial report cutover is introduced.

## Ordinary expense/refund correction editor — October 3, 2026

The owner authorized implementation of the next ledger chunk without routine check-ins.
The [correction editor](../devtools/ledger_audit/EXPENSE_CORRECTIONS.md#correction-editor)
lists posted ordinary expenses/refunds separately from historical proposals, with active,
superseded and all-entry filters. It supports category reassignment and exact USD splits,
requires a correction reason, and previews the unchanged financial movement and total
expense alongside the replacement category amounts. Any form edit invalidates the preview.
Cancellation and window close write nothing; Apply requires confirmation and revalidates
the committed inputs. Superseded entries cannot be edited; later corrections target the
active replacement. Verified source-category annotations remain preserved history.

A separate archive-sized offscreen exercise passed acceptance of a sample proposal,
preview/cancel, cancelled confirmation, application, history/filter behavior and reopen;
both screenshots were inspected. The fresh owner copy preserves all original candidate
tables and starts with zero proposal decisions, journals, allocations and corrections.
Integrity and foreign-key checks passed. Sample choices remain disposable workflow tests,
not financial approvals. Private source identifiers, amounts and screenshots stay ignored.

Windows verification: the full offscreen suite returned **905 passed, 3 skipped** and
one build-script test blocked by PowerShell execution policy in 179.51 seconds. That
single test passed on rerun with process-only `RemoteSigned` in 0.47 seconds, for
**906 passing tests overall**. The focused service/UI suite passed **36 tests**, including
**15 new UI/inventory cases**. Ruff lint/format passed across **226 files**.

The new focused UI/inventory tests cover purchase/refund signs, exact decimal input,
required reasons, split totals and no-op rejection, preview invalidation, cancellation,
active/superseded history, stale concurrent corrections and persistence. The owner accepted
the Windows walkthrough without errors on October 3 and authorized continued work.
Sample choices remain disposable workflow tests. No dependency, schema migration,
server, live-profile change or report cutover was introduced.

## Ordinary expense/refund correction service — October 3, 2026

After accepting the source-review visibility follow-up, the owner authorized continued
ledger work. The [correction service](../devtools/ledger_audit/EXPENSE_CORRECTIONS.md)
previews category reassignments and exact splits for already posted ordinary cash/card
expenses and refunds. It preserves the entire financial movement and source allocation,
date, description and economic event. Corrections require explanations; routine ordinary
acceptance remains unchanged.

Applying revalidates the original entry/review and retained category mappings. Category
account creation, reversal, replacement, allocation release and correction history
share one transaction. Stale previews, invalid amounts/categories, no-op requests,
partial movements and other accounting scopes are rejected. Exact retry/reopen is
idempotent; later corrections target the active replacement. Imported evidence, original
journals, proposal decisions and verified category annotations remain immutable history.

A fresh private archive exercise covered purchase and refund splits, deterministic
preview, reversal/replacement, exact retries and reopen. Financial-account balances,
total expense and evidence consumption were unchanged. Reconciliation became stale
after correction, then retained identical balance-check results. Raw evidence and
annotation tables were preserved and candidate input hashes remained unchanged. The
sample decisions are disposable exercises, not financial approvals; private artifacts
and identifiers remain ignored.

Windows verification: **891 tests passed, 3 skipped** in 161.50 seconds with offscreen
Qt and process-only `RemoteSigned`. **21 new tests** cover purchase/refund signs,
read-only/deterministic preview, exact split validation, scope/no-op rejection,
required reasons, stale/tampered previews, concurrent correction, replacement chains,
atomic rollback including category creation, unchanged annotations/evidence, retry/reopen
and reconciliation invalidation with unchanged balance results. The focused correction,
kernel and reconciliation suite passed **73 tests**; Ruff lint/format passed across
**224 files**.

The next chunk is the correction editor and owner Windows preview/cancel/persistence
walkthrough. This service adds no GUI, schema migration, dependency, server, live-profile
change or report cutover. Unposted interpretations, transfer/clearing, loan, asset,
opening and source corrections remain unfinished.

## Statement reconciliation review UI — October 3, 2026

The owner authorized the next UI chunk after the reviewed-source service passed.
The [statement review window](../devtools/ledger_audit/RECONCILIATION.md#statement-review-window)
exposes searchable saved statement checks, source/ledger differences, selected-statement
evidence, account coverage and movements outside the ledger. Unresolved amounts and
date provenance remain explicit; numeric agreement cannot hide coverage or review limits.

Source review is available for every eligible statement, including later periods.
Save appends explicit balance/date/timing assertions with a source reference; cancellation
or closing the dialog writes nothing. A concurrent edit to the same source requires
reopening the form. Known Chase estimates remain locked. The window cannot post journals,
confirm openings, override source ineligibility or certify the owner's rebuilt books.

The last displayed check is saved atomically outside the immutable evidence, with
checksum/rule/evidence bindings. Source or ledger changes leave the old results visibly
stale until explicit recalculation, including after close/reopen. SQLite change indicators
trigger currentness checks for other-window commits without continuously rehashing the
workspace. Failed replacement retains the previous snapshot; malformed/mismatched
snapshots are preserved and rejected. Rechecking does not write raw reconciliation history.

An archive-sized offscreen exercise passed source-dialog cancellation, later-statement
save, stale display, reopen and recalculation; screenshots were inspected. The separate
owner copy preserves every original table and begins with zero source assertions,
opening decisions, journals, allocations and kernel reconciliation records. Private
artifacts, source identifiers, amounts and screenshots remain ignored.

Windows verification: **869 tests passed, 3 skipped** in 154.47 seconds with offscreen
Qt and process-only `RemoteSigned`. **12 new tests** cover dialog cancellation/save,
later and ineligible sources, exact differences and coverage display, locked estimates,
unadmitted zero-date provenance, filter clearing, concurrent editing, stale reopen and
recalculation, transient-check retry, atomic saved-view failure, tampering and malformed
snapshot refusal. Ruff lint/format passed across **222 files**.

The owner accepted the Windows reconciliation workflow, source-review persistence and
status/filter visibility on October 3. This is a
disposable UI exercise, not approval of its sample financial assertions. No dependency,
server, live-profile or financial report cutover change occurred. Remaining interpretations
and split/correction workflows remain open.

Owner follow-up confirmed that source review persisted but found its status unclear
in the table and filters. The table now has a current **Source review** column and
dedicated **Recorded / Not recorded / Unavailable** filter. Saving, reopening and
other-window commits update that status independently of the last reconciliation check.
Details show both current provenance and the reference used at the last check. A partial
review is recorded without implying verification or reconciliation. Rows leaving the
not-recorded filter clear their selected evidence safely. **13 focused UI tests passed**,
including the new combined-filter regression and extended save/reopen/concurrent-change
assertions; lint/format and a separate archive-sized smoke passed, with its screenshot
inspected. The owner accepted the visibility update and authorized continued work;
the original owner workspace remains a disposable test, not approved financial history.

## Reviewed-source reconciliation service — October 2, 2026

After accepting the opening workflow, the owner authorized continued ledger work.
The [reviewed-source reconciliation service](../devtools/ledger_audit/RECONCILIATION.md)
connects saved endpoint/timing assertions and current opening decisions to the exact
kernel checks. Each calculation uses a committed SQLite read snapshot. It writes no
journals, assertions, raw evidence or kernel reconciliation history. The exporter
opens the prepared workspace in SQLite read-only mode and preserves input bytes.

Results retain exact opening/closing/source differences, unallocated evidence and
postings outside statement membership. Balance agreement, interpretation review,
posting-date certainty and source coverage remain independent. Known estimated dates
prevent an unqualified reconciliation result even when balances agree. Reconciling a
later statement never fills an earlier coverage gap. Ineligible statements and unmapped
movements remain visible, including missing memberships and unsupported account scope.
Canonical unresolved observations are listed once globally, without netting opposites.

Versioned exports preserve checked periods and input identities. Source assertions,
zero-opening decisions, interpretation reviews, new entries and corrections invalidate
prior results. Corrections retain reversal arithmetic and active replacement allocations;
month-crossing transfers retain their source dates and intermediate clearing balances.
The original raw-kernel reconciliation API remains unchanged.

Two independent exports from a fresh unposted private workspace produced identical
artifact bytes. Every original candidate table was preserved, and source/decision/
journal tables remained untouched. The report correctly inferred no financial approval
or reconciliation; estimated dates, unresolved evidence and gaps stayed explicit.
Private amounts, counts, source names and artifacts remain ignored.

Windows verification: **857 tests passed, 3 skipped** in 151.87 seconds with offscreen
Qt and process-only `RemoteSigned`. **17 new tests** cover reviewed/estimated/unverified
provenance, exact unresolved differences, interpretation independence, stale results,
zero openings, full/partial corrections, canceling unbacked postings, equal-balance
gaps, ineligible/overlapping sources, missing membership, month-crossing transfers,
read-only enforcement, deterministic export/reopen and overwrite/active-input refusal.
Ruff lint/format passed across **219 files**.

The next chunk is the statement-reconciliation review UI, including source review
beyond the earliest period and stale-result handling. That UI requires owner Windows
acceptance. This calculation/report chunk adds no GUI, dependency, server, live-profile
change or report cutover. Split/correction controls and other account scopes remain open.

## Source provenance and opening review implementation — October 2, 2026

After accepting the opening-readiness audit, the owner authorized the next bounded
chunk. The [opening review](../devtools/ledger_audit/OPENINGS.md#source-provenance-and-opening-confirmation)
uses a fresh copy of accepted unposted candidates, bound to the readiness artifact.
Earlier GUI sample decisions are not migrated. Proposed amounts, dates and earliest
source sets are checked against raw evidence before review.

Append-only source assertions record balance origin, inclusive-period timing, date
provenance and source references. Explicit confirmation atomically records the opening
decision and a balanced opening-equity journal for nonzero positions. Zero positions
record a decision without a journal or equity account. Neither consumes transaction
evidence or creates expense/income. Raw statements and observations remain unchanged.
Retries are idempotent; prior openings/earlier postings and stale review cannot be
silently offset. Later assertion changes mark an existing opening stale without
rewriting it. Known Chase date estimates cannot be upgraded by user attestation;
ordinary/transfer details now also show conservative source-date provenance.

Windows verification: **840 tests passed, 3 skipped** in 145.52 seconds with offscreen
Qt and process-only `RemoteSigned`. **17 new tests** cover source gates, signed/zero
openings, prior-posting conflicts, atomic rollback, stale/concurrent source review,
immutable history, invalid/tampered evidence, date-label consumers, cancellation and
persistence. Ruff lint/format passed across **216 files**. An archive-sized offscreen
exercise passed cancellation, source review, nonzero/zero confirmation and reopen;
its screenshot was inspected. A separate owner copy initially preserved every original
table and had no source assertions, opening decisions, journals or allocations. Private
financial data and artifacts remain ignored.

The owner accepted the Windows opening workflow and persistence on October 2,
confirming that it worked as intended. This accepts UI behavior, not the disposable
sample financial assertions or report cutover. Raw reconciliation still
uses unverified endpoint provenance; connecting the reviewed view to independent,
date-aware reconciliation is next. Coverage gaps, correction/split workflows and
other account scopes remain open. No dependency, server or live-profile change occurred.

## Opening-position readiness and continuity audit — October 2, 2026

After accepting transfer workflow/persistence, the owner authorized continued ledger
work. The [read-only opening audit](../devtools/ledger_audit/OPENINGS.md) binds the
accepted rebuild and cash/card candidate artifacts, preserves their hashes and emits
deterministic private reports. It does not use GUI test decisions, open databases
for writing, post opening journals or promote source provenance.

The service retains all earliest-period statements for each scoped account and their
exact opening signs. Conflicting earliest balances produce no chosen amount; missing
or ineligible earliest sources cannot be bypassed with later statements. Conditional
cutoffs follow the kernel's before-inclusive-start convention and remain subject to
source review. Zero openings require no zero journal but still require timing and
provenance. Every candidate remains unreviewed, with explicit posting/cutover blockers.

Continuity uses the furthest covered endpoint, preventing nested statements from
creating false gaps. Equal-date endpoint conflicts remain visible, and missing periods
remain gaps even when boundary amounts agree. On the private reference archive all
directly adjacent cash/card boundary amounts agreed; uncovered card periods remained
explicit. The unused archive inventory did not identify corresponding missing-period
sources. Private dates, monetary amounts, counts and filenames remain ignored.

Source inspection also confirmed that the current Chase parser has only transaction
dates and uses statement-bounded posting-date proxies. The audit records that limitation;
it does not label normalized dates as independently established bank posting dates.
Other endpoint/date provenance also remains uncertified by this audit. The next chunk
must attach explicit source provenance before reviewed opening entries and independent
reconciliation can rely on it. No parser or accepted source data was changed here.

Windows verification: **823 tests passed, 3 skipped** in 150.52 seconds with offscreen
Qt and process-only `RemoteSigned` for the builder probe. **14 new focused tests**
cover signed/zero openings, unresolved provenance, earliest-source conflicts, adjacent
agreements/differences, zero-difference gaps, nested periods, conflicting prior closings,
missing sources, snapshot binding, deterministic reports, immutable inputs, overwrite
refusal and tamper/active-input rejection. Ruff lint/format passed across **213 files**.
Two independent private audit runs produced identical readiness and completion report
bytes. This calculation/report chunk introduces no GUI, dependency, server, installer
or live-profile change, and requires no additional native walkthrough.

## Transfer and card-payment matching/review — October 2, 2026

The owner clarified that earlier disposable ordinary-review decisions exercised the
UI rather than certifying accounting interpretations, then authorized transfer/card
payment handling. The [new workflow](../devtools/ledger_audit/TRANSFERS.md) starts from
a fresh copy of verified unposted candidates; prior test decisions are not migrated.

Candidate generation uses eligible cash/card evidence, exact opposite amounts,
matching currency, distinct owned accounts and a configurable 0–31-day posting-date
window. It exposes unique/ambiguous candidates, pending expense conflicts, allocated
movements and missing candidates without automatically matching from labels or
verification flags. Unsupported loans, investments, cash advances, card-to-card
activity, fees and partial settlements remain outside this interpretation workflow.
Repeated source membership does not duplicate an economic movement.

Explicit confirmation atomically records a reviewed balanced journal, evidence usage
and event links. Same-day pairs use one entry; different-date pairs use two entries
through dedicated transfer clearing, preserving each source date and the intermediate
in-transit balance, including when the receiving bank posts first. Both forms have
zero expense/income effect. Failure rolls back clearing creation, both dated entries,
allocations and the decision. Whole or partial prior allocations block reuse. A pending
expense proposal must be rejected explicitly before its evidence can become a transfer;
the historical verified category remains intact. Dismissal affects only the pairing.

The UI shows both observations and source statements, candidate/decision filters,
all-source movement allocation states, and an ordinary-interpretation tab for conflicts.
Confirmation has an optional note and a standard audit reason; dismissal requires an
explanation. Cancellation, stale allocation checks and persisted decisions are covered.
The window explicitly identifies itself as a disposable workflow test. Different-date
confirmation, dismissal, filtering and close/reopen passed an archive-sized offscreen
smoke. A separate owner copy has zero decisions/postings and byte-equivalent contents
for every original table; matching is deterministic and does not write to that copy.
Private candidate counts, artifacts and screenshots remain ignored.

Windows verification: **809 tests passed, 3 skipped** in 137.53 seconds with offscreen
Qt and process-only `RemoteSigned` for the builder probe. **19 new tests** cover exact
matching, ambiguous alternatives, source overlap, same-account/fee exclusions, source
scope, conflicting expense review, partial allocations, same-day and month-crossing
postings, idempotency, transactional failure, GUI selection/cancellation/dismissal,
cross-tab conflict resolution and persistence. Ruff lint/format passed across **210
files**. No server, dependency, packaging, live-profile or report-cutover change occurred.

The owner confirmed the Windows transfer workflow and persistence on October 2.
This accepts the UI behavior, not the disposable sample accounting decisions.
Opening anchors, split/correction workflows, independent reconciliation and report
cutover remain open.

## Ordinary proposal review and posting — October 2, 2026

The owner authorized the next TODO chunk. The
[ordinary proposal review workflow](../devtools/ledger_audit/PROPOSALS.md#ordinary-proposal-review-and-posting)
creates a separate writable workspace from checksum-verified unposted proposals.
The workspace binds to the original proposal plan; reopening checks integrity,
foreign keys and proposal identity without treating the writable database as an
unchanged snapshot. Original proposal/evidence artifacts and the active profile
remain untouched.

The window supports pending/posted/rejected filters, text search, multi-row selection,
source statements and plain-language cash/card effects alongside debit/credit details.
Required reasons and cancel-default confirmation precede writes. Acceptance posts a
reviewed entry and records the decision in one transaction; rejection records its
reason without allocating evidence. Kernel validation preserves exact balance,
ownership, signs, dates and allocation limits. Whole-batch rollback, identical retries
and stale/conflicting decisions are covered. Proposals and category assertions remain
immutable; these controls do not implement corrections, transfers or opening anchors.

Windows verification: **789 tests passed, 3 skipped** in 164.07 seconds, with offscreen
Qt and process-only `RemoteSigned` for the builder probe. The **13 new tests** include
filtered selection, confirmation cancellation, posting/rejection persistence,
concurrent conflicting decisions, duplicate evidence consumption, malformed batches,
mid-batch database failure, checksum rejection and workspace identity. Ruff lint and
format passed across **207 files**. A private archive-sized offscreen smoke completed
cancel/accept/reject/filter/close/reopen and preserved all source/category/proposal
tables. A separate owner workspace was prepared with zero decisions or postings.
Private screenshots, identities and artifact data remain ignored.

The owner subsequently confirmed the Windows workflow behaved as described on
October 2, including cancel, accept/reject and persistence. Ordinary review/posting
is accepted. The owner requested less friction for routine expenses: acceptance now
uses "Accepted as ordinary expense/refund" when no optional note is supplied, while
rejection and accounting corrections retain explanatory-reason requirements.
The effective reason is displayed before confirmation and saved with both the
decision and posting. **40 focused proposal/review tests passed** after this change,
including default-note persistence, idempotent retries and note-required rejection;
Ruff lint/format passed. This small follow-up has automated coverage, not a second
native acceptance claim. No server, dependency, installer, active-profile or
report-cutover change occurred. Transfer/card-payment interpretation is next.

## Fresh cash/card journal proposal service — September 27, 2026

The owner approved connecting accepted fresh evidence to the isolated kernel.
The [proposal service](../devtools/ledger_audit/PROPOSALS.md) copies checksum-bound
rebuild artifacts into a new private directory and preserves the original source,
category, account and reviewed asset-value records. Checking/savings/card movements
retain their signs, posting dates, ownership and overlapping source memberships.
Known parser/account contracts and exact statement equations gate kernel evidence;
unknown contracts, date/balance exceptions and other account types remain explicit.

Restored verified expense categories generate balanced, unposted expense/refund
proposals. Category verification remains separate from accounting review. Proposals
cannot claim review, partially allocate an observation, duplicate its consumption,
or rename an existing proposal for the same observation. Immutable registration is
transactional and retryable after interruption. No income/transfer interpretation,
opening position, reconciliation certification or balancing adjustment is inferred.
Endpoint provenance remains conservatively assumed until independently established.

The accepted private rebuild passed all in-scope statement equations. Two independent
proposal runs produced identical plan/database bytes and completion reports. Every
original source/category/asset-value table and original account mapping remained
unchanged. Posted journal, allocation, review and reconciliation tables stayed empty.
Private counts, identities, monetary amounts and artifact hashes remain in ignored
storage. The live database and normal application were not changed.

Windows verification: **776 tests passed, 3 skipped** in 141.46 seconds with offscreen
Qt and process-only `RemoteSigned` for the builder probe. The **26 new focused tests**
cover cash/card purchase/refund signs, overlaps, category ownership, source exceptions,
exact allocation, review separation, immutable replay, interrupted registration,
checksum rejection and independent-copy preservation. Ruff lint/format passed across
**203 files**. No dependency, server, packaging or GUI change was introduced. Ordinary
proposal review/posting controls and owner Windows acceptance are the next checkpoint;
broader interpretation workflows and report cutover remain unfinished.

## Historical parser compatibility and complete annotation preservation — September 27, 2026

The owner approved repairing historical source compatibility and continuing the
fresh rebuild. `pdf_citicc_201505` 0.3.1 routes historical split date headers while
producer metadata separates them from the accessible-PDF generation handled by
`pdf_citicc_202506` 0.3.1. Its tables now use text row boundaries without vertical
snapping: sub-point glyph boxes previously collapsed the final row boundaries.
The date/description separator uses the column gutter so it retains the first
description character. Missing table extraction remains an error. A synthetic
thin-glyph PDF tests the last row and left-shifted descriptions with actual PDF
extraction, alongside unique routing tests for historical/newer layouts.

`pdf_fidelity401k_201810` 0.2.1 accepts standard, browser-printed, headerless and
inline-continuation plan headers while retaining existing plan-label account keys.
Unknown/ambiguous labels fail closed. All archived retirement account mappings
were checked against their saved source/account associations. The HSA parser did
not require changes. Existing endpoint validation remains enabled throughout.

Full archive replay followed by targeted replay of every source using the final
Citi table fix passed routing, parsing, validation and exact account mapping for
all referenced successful sources. All source hashes remained unchanged. Private
fixture counts, monetary contents, account names, source identifiers and artifacts
remain in ignored storage. This is source verification, not a signed parser-catalog
publication or an installed-client upgrade.

Rule `fresh-evidence-2` preserves repeated-detail category decisions only when every
contributing source group retains its complete, unique balance inventory. Changed,
added, removed and indistinguishable groups still remain pending. The owner also
confirmed a legacy manual vehicle entry represents a rounded initial asset value.
Snapshot-bound manual review retains that value and historical category verification
in `AssetValuations`, without posting another purchase, cash movement or rounding
adjustment. The input is fully validated before mutating the plan; immutable SQLite
history retains the decision and review reason.

The final private artifact accounts for the complete verified-expense inventory:
all source-linked decisions are restored, and the reviewed manual decision is
retained as an asset-value observation. No category decision remains pending.
Independent materializations of the saved plan have identical database bytes.
Original signed annotation counts/amounts equal restored plus pending plus retained
asset values for every account/category/currency group. Journals, opening positions,
transfer interpretations and report cutover remain separate unfinished work.

Windows verification: **750 tests passed, 3 skipped** in 133.05 seconds with offscreen
Qt and process-only `RemoteSigned` for the builder probe. Ruff lint/format passed
across **200 files**, as did Git whitespace checks. The final private artifact passed
the offscreen read-only tab/filter/selection/detail/close smoke, including **Asset
values**. The owner accepted the updated Windows category-preservation and asset-value
review on September 27, closing L4R. This acceptance covers evidence/annotation
preservation, not journal posting, statement reconciliation or report cutover.
No new dependency, server operation, installer build or Intel acceptance is claimed.

## Fresh archive rebuild and category preservation — September 27, 2026

The owner approved a breaking fresh database rebuilt locally from the retained
statement archive, with verified expense categories preserved. The
[rebuild guide](../devtools/ledger_audit/REBUILD.md) documents this first disposable
evidence/category checkpoint. It does not activate a new application database or
post journals. The original database and archive remain intact.

Normal routing/validation reparses hash-verified successful sources into a separate
evidence schema. Categories, hierarchy and unambiguous category verification are
retained independently of accounting interpretation. Exact counts and signed amounts
partition every verified expense into restored or pending, with source/match reasons.
Manual-only decisions remain retained. Unknown accounts, parser failures, warnings
and changed account coverage cannot silently restore verification.

Two full private archive passes reproduced canonical transaction evidence, source
membership and source outcomes. At this first checkpoint, historical Citi routing
and Fidelity account-header failures blocked complete replay; ambiguous categories
remained pending. No compatibility fallback or balancing adjustment was introduced. Private
counts, statement identities, mappings and artifacts remain in ignored storage.

Replay verification caught numeric source-map keys changing canonical checksum order
after JSON reload. The final source maps use string keys and database insert order is
explicit. A regression test exercises nonlexical numeric identities, saved-plan reload
and repeated construction. Final databases materialized from independently reparsed
evidence have identical bytes, matching embedded/serialized plan checksums, unchanged
source/archive hashes, and identical category decisions. Existing output is refused;
immutability triggers protect restored assertions from replacement by ML or edits.

Windows verification: the full client suite passed **724 tests, 3 skipped** in
147.55 seconds using offscreen Qt and process-only `RemoteSigned` for the existing
builder probe. After the serialization fix, **21 rebuild/preview tests** passed.
Ruff lint/format passed across **198 files**. The complete private review artifact
passed the offscreen tab/filter/selection/detail/close smoke. Windows owner native
category-preservation acceptance remains pending. No dependency, server change,
installer/catalog release, Intel acceptance or report cutover is claimed.

## First shadow ledger and read-only review — September 27, 2026

The owner approved corrected HSA evidence in a disposable shadow migration while
retaining remaining printed-balance discontinuities. The
[converter and acceptance guide](../devtools/ledger_audit/SHADOW.md) document the
rule version, artifact contracts and native walkthrough. Every source HSA file
matched its recorded content hash, account identity and period. Reparsed additions,
surviving rows, endpoints and remaining continuity differences matched the exact
owner-reviewed preview. Live history and current reports were not changed.

The shadow retains legacy database bytes and annotations, constructs stable
account/observation/membership identities, and posts supported legacy income/expense
categories only as unreviewed interpretations. Transfers remain candidates;
closures remain control evidence. Synthetic loan positions, valuation activity,
manual interpretations and opening anchors stay unresolved where evidence or
policy is missing. No suspense or balancing adjustment was introduced. Other
historical statement balances are explicitly unverified rather than certified by
the current source parser's implementation alone.

Atomic batch loading validates evidence and journals together. Same-plan replay
adds no entries. Two independent clean builds produced identical plans, ledger
contents excluding creation timestamps, retained legacy bytes and reconciliation
results. Reconciliation reports are bound to the ledger checksum and show why
unallocated activity/unverified endpoints cannot establish reconciled history.
Private plans, source rows, account mappings, counts, file identities and reports
remain in ignored storage. No report cutover or live historical repair occurred.

The read-only window verifies artifact checksums and exposes transaction review
states, possible counterparts, original/corrected closings, continuity gaps and
unposted opening proposals. It has no mutation/activation controls and imports
no active profile, credentials or network service. An automated offscreen smoke
on the complete private artifact passed tab selection, filtering, detail display,
no-match clearing and close. The owner accepted the Windows read-only review
window on September 27. This closes L5a only; transfer/split/correction editing
and report cutover still require their own acceptance.

Windows source verification: **707 passed, 3 skipped** in 137.92 seconds for the
full client suite, with offscreen Qt and process-only `RemoteSigned` for the
existing builder probe. **51 focused migration/kernel/preview tests** passed.
A final selection-reset refinement passed the **3 preview tests** and full-data
offscreen smoke, ensuring reselecting the same row after filtering restores its
details. Ruff lint/format passed across **194 Python files**; Git whitespace checks
passed. No new dependency, server change, installer/catalog release or Intel
acceptance is claimed. Windows native acceptance is the owner result above.

## Ledger recovery and isolated kernel — September 27, 2026

The owner authorized proceeding through recovery preparation and the kernel,
while keeping historical interpretation and native GUI acceptance gates explicit.
The [recovery tool](../devtools/recovery/README.md) creates a consistent read-only
SQLite snapshot and a manifest-bearing database/managed-archive ZIP. It verifies
every statement's recorded source hash and retains pending/failed/duplicate import
material, including opaque ZIP/text export companions. Profile configuration,
authentication and application runtime artifacts are outside the selected scope.

The authorized private bundle passed both its internal disposable restore and an
independent restore invoked with only the bundle and a new destination. Database
integrity, foreign keys, schema/record fingerprints, file hashes and statement
references matched. The initial archive-type check stopped at export companion
files; the complete run includes those files as opaque evidence, without nested
extraction. All bundles, snapshots, reports and real account mappings remain in
ignored private storage. A workspace-local recovery copy is not an off-device
disaster backup. No live database, archive, profile or report was modified.

The [isolated ledger kernel](client-ledger-kernel.md) implements exact USD debit/
credit posting, explicit account mappings, canonical observations and allocation
limits, idempotent processing, atomic reversal/replacement, append-only review,
and versioned statement reconciliation. It rejects changes to posted history and
source facts. The SQLite store is explicitly created at a new path and does not
initialize legacy application databases. No production Alembic migration, import
integration, private-history conversion or report cutover is included.

**18 recovery tests and 35 kernel tests** cover committed WAL, unavailable source
paths during restore, archive corruption/missing files, traversal/overwrite
refusal, exact monetary values, card purchase/repayment, refunds, fees, loan
splits, cross-month clearing, partial evidence, duplicate processing, unsupported
currency, opening equity, suspense, correction rollback, overlapping statement
membership and stale reconciliation. The full-suite rehearsal exposed a Windows
file lock in a test fixture; its SQLite connection is now explicitly closed before
simulating unavailable source paths. This was a fixture lifetime issue, not a
failure of the independently exercised recovery bundle.

After correcting that fixture, the full Windows source suite passed **691 tests,
3 skipped** in 130.70 seconds with offscreen Qt and process-only `RemoteSigned`
for the existing builder probe. Ruff lint/format passed across **188 Python files**;
Git whitespace checks passed. A final read-only comparison confirmed the live
database's schema/record fingerprint and all bundled archive-source hashes still
matched the verified backup. No new dependencies or platform-specific runtime
integration were introduced. No native GUI acceptance or Intel execution is claimed.

L1 remains open for reviewed source corrections and migration interpretations.
The private review document proposes identity mappings and lists HSA, synthetic
loan, account-closure, tangible-asset and unconfirmed-transfer cases. Wells Fargo
parser changes remain deferred at the owner's request. L4 will preserve these
decisions explicitly; it must not turn unresolved differences into balancing
entries. F4 GUI integration and L5 Windows native acceptance remain future work.

## LendingClub and Capital One balance evidence — September 27, 2026

The owner requested source-parser fixes against the authorized local statement
archive after the balance-evidence audit. `pdf_lendingclubsavings_202601` version
`0.1.1` now extracts both endpoints from the separately printed six-column
summary. It requires a unique recognized summary, validates its arithmetic,
compares Balance Forward to the summary opening, and checks every running balance
and the final activity total exactly. Missing tail activity can no longer select
its own closing balance from the last parsed transaction.

`pdf_capitaloneauto_202402` version `0.2.1` requires a unique printed closing
principal balance and validates principal plus interest against each printed
transaction total. It reads the whole history through the payment-coupon boundary,
allows blank lines/repeated identical column headers, and rejects unsupported
columns, malformed/unrecognized rows, missing boundaries, out-of-period dates,
and empty histories without explicit no-activity evidence. Payment/interest signs,
descriptions, and transaction ordering retain the existing representation.

The Capital One source format supplies no independent opening principal balance.
The parser reconstructs it from the separately printed principal components;
this is still derived, not independent within-statement reconciliation. An entire
missing row can evade the component checks. A separate prior closing observation
is needed to check completeness across statements. No database lookup or inferred
prior balance was added to the parser. The archive review found consecutive
printed closings consistent with the reconstructed openings; this was an audit,
not a new automatic import-time cross-statement check.

Every applicable authorized archived PDF matched its recorded content hash and
passed revised parsing. Outputs matched both the previous parsers and stored
history, including transaction multiplicity, dates, amounts, descriptions, and
statement balances. The disposable database snapshot hash was unchanged. Private
sources, counts, identities, amounts, dates, extracted text, and verification
reports remain in ignored storage; committed regression fixtures are synthetic.

The focused suites passed **27 tests**, covering independent summary evidence,
missing tails, inconsistent running balances, corrupt summary/component amounts,
zero savings activity, origination, payment/interest preservation, blank/repeated
table headers, malformed and unsupported layouts, and boundary requirements.
The full Windows source suite passed **638 tests, 3 skipped** in 129.99 seconds
with offscreen Qt and process-only `RemoteSigned` for the existing builder probe.
Ruff lint and format passed across **181 Python files**; Git whitespace checks
passed.
No dependencies, parser interface, schema, live history, server, signed plugin
catalog, or installed application were changed. Publication and historical repair
remain separate actions; these source fixes require no new native GUI acceptance.

## HealthEquity cash continuation parsing — September 27, 2026

The L1 source audit reproduced a client parser defect: `pdf_hehsa_201810` stopped
at an interest-rate table even when cash activity continued on later pages. It
also missed table rows/labels preceded by extracted underscore borders. Deriving
the closing balance from the last parsed transaction let incomplete activity
pass the within-statement equation.

Source parser version `0.2.1` reads the cash section through its independently
printed EndingBalance, normalizes leading underscore borders, and requires unique
ordered opening/closing boundaries. It checks every running balance and the final
printed balance exactly, and excludes the investment-portfolio section after the
cash closing boundary. Unknown/truncated/mismatched layouts fail rather than
manufacturing a closing balance. The plugin interface and dependencies are unchanged.

**17 focused tests passed** across parser and audit tooling. Parser fixtures are
synthetic and cover continued pages, underscore rows/labels, ignored portfolio
rows, missing/duplicate/reversed boundaries, running-balance mismatch, truncated
activity, and zero activity. The complete authorized local source fixture set
also passed corrected parsing; each archived PDF matched its recorded content
hash. A private impact preview preserves every existing transaction, identifies
omitted rows, and lists residual differences between consecutive printed balances.
Those remaining differences are not resolved by this parser fix. Private sources,
counts, dates, amounts, identities, reports, and archive locations are not committed.

The final full client suite passed **614 tests, 3 skipped** in 127.41 seconds,
using offscreen Qt and process-only `RemoteSigned` for the existing builder probe.
No machine/user execution policy changed.

Ruff lint/format passed for client source/tests and both analysis/audit devtools
(**180 Python files**); Git whitespace checks passed. No live history repair,
ledger migration, plugin catalog publication, server operation, or installer build
occurred. Normal reimport can skip known content hashes; historical repair needs
an explicit reviewed procedure and recovery checks. L1 remains open at that boundary.

## Client L1 ledger contract and initial audit — September 27, 2026

The owner approved the double-entry foundation in
[client-ledger-contract.md](client-ledger-contract.md), ahead of cash-flow totals.
TODO now sequences accounting design/audit, recovery preparation, the ledger
kernel, parallel migration/reconciliation, and Windows review UI acceptance.
These are staged commitments, not claims that ledger migration has occurred.

The [standalone auditor](../devtools/ledger_audit/README.md) opens the authorized
source read-only, uses SQLite online backup into a new ignored directory, and
audits only the snapshot. It imports no application settings/credentials/network
components. Existing output cannot be overwritten. Source main/WAL hashes and
snapshot immutability are recorded privately. Reports contain no raw descriptions
or account/category names; all reports, snapshot hashes, source identities,
counts, dates, monetary differences, and source-PDF investigations remain local.

The authorized snapshot passed integrity/foreign-key checks and its stored
within-statement amount/balance equations. The audit identified unresolved
counterpart candidates, manual-origin rows, coverage gaps, and adjacent-statement
discontinuities. Passing equations do not independently verify balances computed
by historical parsers. The source files were unchanged during snapshot creation;
the read-only audit left the snapshot unchanged and reproduced its original
results after adding manual-origin markers.

The owner clarified that legacy manual closure rows are bookkeeping instructions,
not money movements; the contract maps their intent to lifecycle metadata while
preserving evidence and exposing unexplained residual balances. Source-PDF review
then reproduced HSA continuation-page omissions in the current parser. L1 remains
open for parser correction, source-repair review, and explicit migration mappings.

Windows source verification: **604 passed, 3 skipped** in 148.36 seconds for the
full client suite (offscreen Qt, process-only `RemoteSigned` for the existing
builder probe). The final audit suite passed **8 tests**, including the origin
marker test added after full-suite collection. Tests cover read-only enforcement,
source preservation, WAL-aware snapshots, overwrite refusal, independent copies,
overlapping evidence, empty history, balance/count/ownership/date discrepancies,
candidate ambiguity/currency/date/account limits, and description exclusion.
No live repair/migration, schema change, new dependency, server operation, release,
or native GUI acceptance occurred.

## Client CF1 coverage service verification — September 26, 2026

The client feature branch now has a headless `CoverageService` with read-session
ownership, immutable statement provenance, and explicit empty-account handling.
Inclusive overlapping/adjacent statement ranges share one merger with the
existing Completeness Grid. The grid retains its existing query window and
datetime drawing inputs; analytics use an unfiltered history snapshot instead.

The service reports uncovered intervals and separates the last covered date
from import time. It selects the latest fully covered adjacent-month or
year-over-year pair across every selected account, excluding the current month.
It never replaces missing data with zero activity. Coverage reflects declared
statement intervals, not an independent institution-export audit; calendar
reference dates do not replay historical import availability.

Windows AMD64 source evidence (Python 3.13.15, PySide6 6.11.2):

- **16 focused tests passed**, including 100 deterministic calendar cases checked
  against independent day sets, overlaps/duplicates/adjacency, one-day gaps,
  empty and missing accounts, differing cutoffs, stale history imported today,
  future dates, leap years, year boundaries, and fully covered comparison pairs.
- Full client suite: **597 passed, 3 skipped** in 122.15 seconds, with offscreen
  Qt and process-scoped `RemoteSigned` for the existing PowerShell builder probe.
  No machine/user execution policy changed.
- A real temporary SQLite fixture verifies statement provenance, old history,
  zero-transaction statements, empty accounts, and session closure. A manual
  transaction outside statement coverage does not extend coverage. Read errors
  remain errors rather than masquerading as empty history.
- The grid adapter preserves its padding, account order, merged intervals,
  datetime bounds, and empty response. A fresh-process import verifies no Qt
  dependency in the service.
- Ruff lint/format passed for client source/tests and the local-analysis devtool
  (**177 Python files**); Git whitespace checks passed.

No private financial data was accessed. No database schema, dependency, server,
installer, or release version changed. There is no new visual workflow in this
service chunk; no additional native GUI acceptance is required. No Intel run or
hosted CI is claimed. Future spending UI will expose these service results under
its own Windows acceptance gate.

## Client C2a-2 verification and Windows acceptance — September 26, 2026

On `feature/client-financial-insights`, both model-training actions now use the
local-analysis worker lifecycle. The worker owns the verified-training-data
session, fits the existing classifier, and returns scalar evaluation data or a
serialized, reloaded candidate beside the destination model. Test plots and
atomic model publication run on the GUI thread after accepted completion.
Canceled results are discarded even if computation has finished and Qt delivery
is pending. Fit, serialization, validation, or replacement failure preserves the
previous model. Settings are updated only after publication; preference-save
failure reports the saved file separately and restores the previous selection.

Cancel/Close/Escape/window-X wait for an active library step while the GUI keeps
processing events. Application shutdown joins workers and cleans up staged
output. This chunk adds no dependency, schema, server, or release-version change.

Windows AMD64 source evidence (Python 3.13.15, PySide6 6.11.2):

- Focused training, shared-worker, and isolated-launcher checks: **41 passed**.
  Covered actual worker-owned SQLite reads, GUI heartbeat/plot/commit thread,
  Cancel/Escape/X, both late-cancellation boundaries, shutdown cleanup, failed
  replacement, partial serialization, reload validation, and preference failure.
- Full client suite: **581 passed, 3 skipped** in 122.98 seconds, with offscreen
  Qt and process-scoped `RemoteSigned` for the existing PowerShell builder probe.
  No machine/user execution policy changed.
- All three synthetic training modes passed: save/reload, evaluation without
  save, and injected partial-write failure preserving the original model bytes.
  Existing recurring launch modes and profile/environment isolation also passed.
- Ruff lint/format passed for client source/tests and the acceptance devtool
  (**175 Python files**); Git whitespace checks passed.

No private database/model was accessed, no installer was built or published,
and no hosted CI or Intel run is claimed. The owner reported the requested
Windows training test successful at `1b75c90`; this closes the C2a-2 native gate
and completes C2a. No optional failure-demonstration or Intel acceptance is
inferred. CF1 may proceed. The [synthetic training walkthrough](../devtools/recurring_acceptance/README.md#c2a-2-background-training-acceptance)
remains available for regression checks with a temporary profile.

## Client C2a-1 verification and Windows acceptance — September 26, 2026

On `feature/client-financial-insights`, recurring analysis now runs outside the
Qt GUI thread in both Identify Recurring and Transaction Review. Identify
Recurring opens/closes its read session in the worker. Review supplies immutable
scalar snapshots, leaving its editable records and Qt models on the GUI thread.
Results are delivered after worker exit; cancellation discards even a completed
result that is still queued for GUI delivery. Refreshing review rows invalidates
the old analysis.

Cancellation checks cover text preprocessing, stage boundaries, and filter-group
boundaries. SQLite/scientific-library calls already in progress finish before
cancellation takes effect. Canceling leaves the interface responsive and restores
controls when the worker settles. Escape/Close/window-X defer closing until the
worker exits; main-window close cancels child analyses and waits asynchronously.
The application-quit guard cancels and joins workers before Qt destroys them.
No thread termination, dependency, database schema, server, or release-version
change is involved. Model training remains the separate C2a-2 chunk.

Windows AMD64 source evidence (Python 3.13.15, PySide6 6.11.2):

- Focused analysis/control/launcher checks: **61 passed** before the final two
  lifecycle test additions.
- Full client suite: **555 passed, 3 skipped** in 114.10 seconds. Used offscreen
  Qt and process-scoped `RemoteSigned` for the existing PowerShell builder probe;
  no machine/user policy changed.
- Final worker suite: **14 passed**, including two tests added after full-suite
  collection for the actual review window's `WA_DeleteOnClose` behavior and
  programmatic quit cleanup. Covered read-session thread ownership, GUI heartbeat,
  result delivery thread, Cancel/retry, queued-result suppression, failures,
  duplicate start, review refresh, dialog Escape/Close/X, and parent-window close.
- Both isolated synthetic launchers passed with a one-second simulated library
  step (`--smoke-test --slow-seconds 1`, with and without `--review`).
- Ruff lint and format passed for client source/tests and the acceptance devtool
  (**172 Python files**); Git whitespace checks passed.

No private database was accessed, no installer was built/published, and no hosted
CI or Intel execution is claimed. The owner clarified in `c9809b2` that ordinary
client features need not wait for duplicate Intel walkthroughs. The owner tested
`7411bd0` on Windows and confirmed Cancel works both with and without `--review`.
The owner subsequently confirmed that window-X worked as described (responsive
while waiting for the current step, then safe close). This closes the Windows
Cancel/Close/responsiveness gate for C2a-1; C2a-2 may proceed. The
[delayed-analysis walkthrough](../devtools/recurring_acceptance/README.md#c2a-1-background-analysis-acceptance)
remains available for regression checks with a temporary profile and visible
heartbeat. No Intel native acceptance is inferred from the Windows result.

## Client C1 verification and Windows acceptance — September 26, 2026

Client branch `feature/client-financial-insights` starts at `stable-1.4.2`
(`effced9`). The roadmap was recorded in `4060469`. C1 corrects sign-dependent
recurring amount filtering and its Decimal incompatibility, uses exact squared
dispersion comparisons, returns no matches for unusable descriptions, and keeps
source data unchanged. Amount filtering abstains on singleton, nonfinite,
zero-valued, and mixed-sign groups. Optional amount features use magnitudes so
debit/credit mirrors receive equivalent clustering inputs.

The Identify Recurring controls now pass percentages as ratios and the minimum
interval under its actual parameter name. Both analysis windows explain ordinary
no-match results; Identify Recurring clears obsolete results/export availability
after empty or failed analysis. This is not scheduling/forecasting or background
execution, and makes no server, database schema, or release-version change.

Windows AMD64 source evidence (Python 3.13.15, PySide6 6.11.2):

- Focused recurring/core and Qt-control checks: **46 passed**.
- Full client run with offscreen Qt: **542 passed, 3 skipped, 1 failed** in
  99.79 seconds. The failure was the unchanged Windows release-builder metadata
  test: its child PowerShell refused local script execution under the sandbox
  account's default policy, before reaching its stubbed builder probe.
- Reran that one test with process-scoped `RemoteSigned`: **1 passed**. No user
  or machine execution-policy setting changed. Across these runs all 543 runnable
  checks passed; the three platform skips remain explicit.
- Ruff lint and format checks passed for client source/tests and the new
  recurring-acceptance devtool (**168 Python files** formatted).
- The full suite includes two isolated launcher smokes and a snapshot-isolation
  test. Environment canaries remain untouched; editing a copied SQLite database
  does not change its source bytes. Synthetic Identify Recurring and Transaction
  Review smokes also passed when run directly.

No private database was opened by the agent for this implementation, and no
installer was built or published. Hosted CI and Intel execution have not been
obtained for this chunk. The owner accepted C1 (`148cc2f`) and explicitly
confirmed Windows-only testing. No claim is made about which optional private
fixture steps were exercised. The owner also clarified that routine client
features do not require rigorous duplicate cross-platform walkthroughs, absent
dependency changes or a concrete platform concern. C1 is closed and C2a may
proceed. The [prepared walkthrough](../devtools/recurring_acceptance/README.md)
remains available for repeat checks and targeted platform testing.

## Where the lasting contracts live

| Completed work | Maintained documentation |
| --- | --- |
| P0.1 test isolation and CI boundaries | [Development contracts/checks](../development.md), [backend tests](../backend/README.md#tests-and-static-checks), [deployment CI boundary](../deployment.md#ci-boundary). |
| P0.2/P0.4 memory-only contributions, limits, reconciliation, key ownership | [Privacy inventory](privacy-and-data-flow.md), [backend guide](../backend/README.md), [server-statement devtool](../devtools/server_statements/README.md). |
| P0.3 artifact trust and completed P1.5 release gates | [Desktop release guide](../client/README.md#signed-plugin-releases), [artifact rollback](artifact-rollback.md), [release/incident response](release-and-incident-response.md). |
| R4 preserved release publication | [Public-key-only publication](artifact-publication.md), [artifact rollback](artifact-rollback.md). |
| P0.5/P1.2 import recovery and exact financial schema | [Client data/import guide](../client/README.md#local-database-and-exact-financial-values), [import acceptance sandbox](../devtools/import_acceptance/README.md). |
| P0.6 runtime/dependency baseline and PostgreSQL cutover | [Contributor setup](../development.md), [client requirements](../client/README.md#requirements), [PostgreSQL runbook](postgresql-17-upgrade.md). |
| P0.7 deployment, staging isolation, rollback, proxy and backup boundaries | [Deployment](../deployment.md), [staging](staging.md), [release/incident response](release-and-incident-response.md). |
| P1.1 deterministic headless parser routing | [Parser architecture](../README.md#parser-architecture), [client plugin architecture](../client/README.md#plugin-architecture), [local batch tool](../devtools/local_statements/README.md). |
| P1.3 authentication and P2.3 web cleanup | [Backend account guarantees](../backend/README.md#account-state-guarantees), [web authentication](web-authentication.md), [dashboard guide](../frontend/README.md). |
| P1.4/P2.1 responsive networking and application service ownership | [Client service boundaries](../client/README.md#application-service-boundaries), [desktop login](../client/README.md#desktop-login-storage). |
| Completed P1.6/P2.2 startup, onboarding, and backup behavior | [Offline startup](../client/README.md#offline-startup-and-update-checks), [first run and backups](../client/README.md#first-run-and-database-backups). Native fresh-user acceptance remains in TODO. |
| P2.4 documentation/privacy alignment | [Root guide](../README.md), [privacy](privacy-and-data-flow.md), [threat model](threat-model.md), component guides and operational runbooks. |

Transient audit counts, bundle sizes, and module line counts from earlier
checkpoints remain in Git history. They are not current dependency-health or
performance guarantees. Locks, tests, and fresh release checks are authoritative.

## Desktop releases and financial-data acceptance

- **Windows client 1.3.0 and Intel macOS client 1.3.1** passed native build,
  regression tests, frozen-runtime smoke, offline signing, independent
  verification, immutable publication, public download, installation,
  credential-store, and signed-plugin update gates. These results do not establish
  Apple Silicon support or close the later P1.6/P2.2 fresh-user walkthroughs.
- The Windows signing rehearsal included the **22-plugin catalog**. The encrypted
  offline Ed25519 key and its passphrase have separate password-manager recovery
  copies. Only public trust keys ship with the application.
- **18 authorized statements** routed uniquely through the in-memory headless
  batch and imported through the signed 1.3.0 desktop build. The server-statement
  UI also decrypted and parsed an authorized encrypted contribution through
  `ParseInput.data`, with no new plaintext file outside its original fixture
  location.
- A temporary copy of the **18,668-row client database** passed shadow migration,
  redacted structural checks, and populated-GUI review of exact money, duplicates,
  and overlapping statement membership. The owner reported no visible correctness
  concerns. The precise schema is intentionally not downgradable in place;
  recovery uses the validated pre-migration `.dbb` copy.
- Import acceptance exercised overlapping and multi-account statements, one
  canceled batch, and an injected archive failure followed by safe recovery.
  The repeatable procedure lives in the linked sandbox guide.
- Parser work accepted during this period included Citi `202511` accessible-PDF
  layouts (obscured and continuation rows, single-date payments, multiline fees),
  Chase Sapphire against all five supplied statements, LendingClub LevelUp/Happen
  Bank against seven supplied statements, and the corrected Synchrony/Amazon
  plugin identity without the erroneous `.py.pyc` suffix. Earlier Citi routing
  signatures remained distinct.
- The source client review at **`1766ceb`** ran **253 tests on Windows** and passed
  Ruff check/format for source, scripts, migrations, and tests. Its limits and
  new findings are in [the client review](client-development-review.md).

## Release bootstrap follow-up

The R1 implementation passed **283 client tests on Windows**, client-wide Ruff
check/format, and PowerShell/Bash syntax checks. The tests include package-free
startup, uv's inline minimum-version enforcement, Windows builder failure
propagation, and rejection before project sync for invalid uv, Python pins,
hosts, and interpreter properties.

The real Windows bootstrap passed against both the existing managed interpreter
and a new temporary uv installation directory. Both inspections identified
standard 64-bit CPython 3.13.15 on Windows x64 with uv 0.12.5. No client packages,
installer, signing operation, or public artifact activation were needed for
these checks.

The owner pulled `fix/client-release-bootstrap` on the Intel Mac and ran
`uv run --no-env-file --script scripts/release_bootstrap.py check --platform macos`.
It returned the success report with `interpreter`, `python_version`, `target`,
`uv`, and `uv_version`. That report is emitted only after uv, the exact pinned
CPython interpreter, and the native 64-bit Intel target pass validation. This
completes R1 bootstrap acceptance on both active platforms; native packaging and
installed-app checks remain separate gates.

## Intel Mac packaging implementation follow-up

R2's implementation passed **326 client tests on Windows**, with the one native
Mac Bash integration test skipped. Client-wide Ruff check/format and the Mac
builder's Bash syntax check passed. Synthetic tests cover missing toolchain
inputs, old Rust, wrong archive architecture, static-build environment overrides,
cached-wheel avoidance, release-launcher failure propagation, unresolved/external
library references, dynamic OpenSSL rejection, inventory evidence validation,
and frozen-process timeout/failure. The native dependency smoke exercised the
installed Windows Python libraries with network connections denied.

The audit parser uses synthetic `otool` output in these tests. This evidence does
not claim a real Mac `.app` was audited or installed. The remaining
[Intel Mac release gates](../client/README.md#intel-mac-release-gates) cover the
packaged Mach-O, frozen smoke, and installed app. Source-build inputs,
dependency-audit results, and the bounded smoke
result are preserved under `native_build` in each new Mac release inventory.

On **2026-09-06**, the owner ran the tool-only preflight from
`fix/intel-macos-packaging` successfully on a **2020 Intel MacBook Air**. It reported:

| Input | Accepted preflight observation |
| --- | --- |
| Target | `macos`, `x86_64` |
| Running macOS (separately reported) | **15.7.9**, build **24G830** |
| OpenSSL | Homebrew `openssl@3`, OpenSSL **3.6.3** (9 Jun 2026), static inputs enabled |
| Rust / Cargo | **1.98.0**; Cargo Homebrew build `797e8a9bc` (2026-08-05) |
| clang | Apple clang **12.0.5**, `clang-1205.0.22.9` |
| macOS SDK | **11.3** |
| pkg-config | **3.0.6**, resolving OpenSSL **3.6.3** |
| create-dmg | **1.2.3** |

The verified Intel static archive SHA-256 values were
`libcrypto.a`: `71f4297ec46ebb05962f1d58d616d80812d26103dd249c7b9a457b928ff62987`
and `libssl.a`:
`aa542ff72245c61b2e16d3e369caed549cf4e0f6d139dfdb5e90267759bb852a`.

This accepts the original tool-presence/static-input preflight, not a native
dependency build or frozen artifact. That report did not include the running
macOS version; SDK 11.3 cannot establish it. The owner separately confirmed
**macOS 15.7.9 (24G830)**, meeting the client's macOS 13 minimum. The follow-up
preflight records the running OS and rejects older or unknown hosts; **80 focused
release tests passed on Windows**, with the native Mac Bash test skipped, and
Ruff check/format passed.
The owner agreed to update the Apple tools after checking OS compatibility.
Keep tool updates compatible with Sequoia on
this machine: Apple's [Tahoe compatibility list](https://support.apple.com/en-us/122867)
includes the M1 2020 Air, not the Intel 2020 Air. An Apple Silicon replacement is
not an active project prerequisite. As checked on 2026-09-06, Apple's
[Xcode matrix](https://developer.apple.com/xcode/system-requirements) lists Xcode
26.3 for macOS 15.6 or newer and 26.4.1 for macOS 26.2 or newer; do not assume
the latest tools support this host. Inspect the active developer directory and
Software Update's compatible offerings before selecting an update.

The owner subsequently confirmed that `xcode-select --print-path` returns
`/Library/Developer/CommandLineTools` and `softwareupdate --list` reports no new
software. The old SDK therefore comes from the selected standalone tools, rather
than an older Xcode application selected in their place. After following the
manual **Command Line Tools for Xcode 26.3** update path, the owner reran preflight
successfully. It now reports **Apple clang 17.0.0 (`clang-1700.6.4.2`)**, **macOS
SDK 26.2**, and **running macOS 15.7.9**. The Intel target, OpenSSL 3.6.3 static
archive hashes above, Rust/Cargo 1.98.0, pkg-config 3.0.6, and create-dmg 1.2.3
remain the same. This accepts the tools update and the complete preflight on
the owner's Intel Mac; the native build/audit, frozen smoke, and installed-app
walkthrough remain open.

## Client installer architecture contract follow-up

R3a introduces the [version-2 installer target contract](client-release-contract.md)
for the prepared client **1.4.0** source. Windows x64 and Intel Mac now have
explicit signed targets and architecture, target-specific filenames/channels,
and matching API/website selection. Legacy channels return manual-upgrade
instructions after deployment. The transition and rollback runbooks preserve
existing signed 1.3 artifacts and require coordinated staging acceptance.

The implementation passed **352 client tests on Windows**, with the native Mac
Bash test skipped, **31 isolated installer API tests**, and **8 website JavaScript
tests**. The client and changed backend modules passed Ruff check/format; the
API module passed mypy, and both native builders passed syntax parsing. After
the source version became 1.4.0, **91 focused client/release tests** passed and
`uv lock --offline --check` confirmed the existing lock remains valid.

Coverage includes both active targets at one version, missing/mismatched
architecture, unsupported/legacy targets, altered signed target/filename bytes,
wrong-channel manifests, no network request on unsupported client processes,
legacy HTTP 410 guidance, and explicit website labels without browser CPU
guessing. These are source/interface results: no native installer, release tag,
public activation, API deployment, or 1.3 profile upgrade was performed. R3b and
the native release/offline walkthroughs remain open in TODO.

## Frozen executable architecture gates follow-up

R3b's portable header checks and bootstrap/target/toolchain regressions passed
**106 focused tests on Windows**, with the Mac Bash integration test skipped.
The checks inspected the real Windows CPython executable as PE32+ AMD64 and
rejected synthetic ARM, 32-bit, DLL, universal, cross-platform, and truncated
candidates without executing them. Mac header fixtures are synthetic; no real
Mac frozen binary was inspected here.

Both builders now gate the frozen executable before smoke/packaging, and Mac
PyInstaller explicitly targets x86_64. Hosted source CI selects Windows x64 and
`macos-15-intel`, provisions/verifies exact native CPython before dependencies,
and checks the resulting client environment target. The Intel runner label was
verified against GitHub's published runner matrix. The new hosted run and final
native frozen builds remain pending; this record does not mark R3b complete.

The owner then ran the requested Intel bootstrap, `macos_release.py sync
--fresh-cryptography`, and the offscreen full client suite. The clean cryptography
**49.0.0** source build completed in **2m 22s** and the editable client reported
**1.4.0**. The suite passed **371 tests with 2 Windows-specific skips in 128.87s**.
This accepts the locked Intel dependency build and source-test gate on the
updated macOS 15.7.9 machine. The transcript did not record a Git commit; the final
tagged native build must retain its inventory/source commit. Static build inputs
and successful source tests do not replace the final bundle library audit,
frozen smoke, installed Keychain, and offline walkthrough.

## Preserved artifact publication follow-up

R4 adds the shared [publish-existing operation](artifact-publication.md) for
Windows x64, Intel Mac, and plugins. Native builders now stop after signing and
recording a dry run. Publication uses public keys and the recorded inventory
digest, validates saved source/target identity, confirms the displayed release,
and uploads a verified temporary copy without changing the saved output. The
old build/publication switches are retired.

The implementation passed **441 full client tests on Windows**, with three
platform-specific skips: the native Mac Bash builder and two Linux/POSIX `flock`
integration cases. Client-wide Ruff check/format and both native builder syntax
checks passed. Real temporary Ed25519 signatures cover both installer targets
and plugin catalogs; fake transport checks preserved bytes, changed/missing
evidence, source/target mismatch, declined publication, reused sequences,
concurrent activation, post-move SSH interruption, unknown outcomes, and public
smoke failure. The compare/move shell condition also ran in Windows Git Bash;
the native Linux locking primitive still needs staging acceptance.

No release signing key, financial fixture, SSH destination, or public artifact
directory was accessed. These local checks complete R4's implementation gate;
the staged publication and resulting native walkthroughs remain in TODO.

## Offline entry-point and frozen-session follow-up

O1's [diagnostic and owner procedure](client-offline-acceptance.md) cover fresh,
cached, and failing-network sessions through the real entry point/event loop.
The implementation passed **446 full client tests on Windows**, with the native
Mac Bash builder and two POSIX `flock` cases skipped. Client-wide Ruff
check/format and both native builder syntax checks passed.

An **unsigned Windows x64 diagnostic freeze** built with PyInstaller **6.21.0**,
CPython **3.13.15**, and the locked dependencies passed all three modes using its
actual bundled resources. The executable passed PE32+ AMD64 inspection and had
SHA-256 `a945140fb53bbd137f724696f29cef73f186614e46c2c1cd2b16fe51ea13f697`.
Each report showed `frozen: true`, five onboarding pages, and **151 heartbeat
ticks**. Fresh/cached runs attempted **zero** requests; the failure case attempted
only the **two** documented background manifest GETs. Cached/failure runs both
parsed/imported exact synthetic amounts, retained the copied source, detected
duplicate import, predicted with an existing model, and trained/saved/reloaded
a new local model.

The source tests also supplied hostile profile/settings/credential environment
overrides and verified that an existing canary file and surrounding profile were
untouched. The diagnostic uses its own temporary profile and ephemeral signing
key, never the release key or financial fixtures. Reports refuse to overwrite an
existing file. This is a diagnostic build from the working branch, not a tagged
release installer, installation/upgrade acceptance, or native credential test.
Intel source diagnostic acceptance was subsequently completed below. Both final
tagged frozen builds, hosted CI, and the installed offline/P2.2 walkthroughs
remain open.

### Intel offline timeout follow-up: September 19, 2026

The owner ran the source probes on `test/client-offline-session` and reported
**3 timeouts and 2 passing guard tests in 228.00s**. Each real-entry-point mode
hit the 75-second subprocess limit. This did not invalidate the earlier native
dependency-build/suite result; it exposed a separate offline-harness failure.

The harness identified the new-database message by its window title.
[Qt 6.11.2 ignores that title on macOS](https://github.com/qt/qtbase/blob/v6.11.2/src/widgets/dialogs/qmessagebox.cpp#L2509).
An untitled-message simulation reproduced the incorrect rejection on Windows.
Additionally, the failure path stopped its timer and called `app.exit()` during
a startup modal, allowing a later main event loop to wait indefinitely.
The harness now checks the expected message's temporary database path, parent,
icon, and buttons; failures unwind subsequent modals and prevent another main
event loop from starting.

Elapsed stage messages and a 60-second independent Python stack dump now survive
a blocked GUI. Source pytest failures and Mac build errors expose the captured
diagnostics; windowed Windows probes retain a separate diagnostic log on failure.
The 35-second GUI deadline and 75-second outer timeout are unchanged.

The revised full Windows client suite passed **451 tests with 3 skips in
103.59s** (native Mac Bash integration and two POSIX `flock` cases). Regressions
cover untitled messages, unexpected messages/dialogs followed by another modal,
stack capture without a Qt event loop, and preservation of existing log files.
Client-wide Ruff check/format and the Windows builder syntax check passed.

A rebuilt unsigned Windows diagnostic freeze also passed PE32+ AMD64 inspection
and all three offline modes. Its executable SHA-256 was
`358894fedb6d8b3a3c02ef0c3689f7094142e09a31244c64e440ca945d85e7a6`.
Fresh/cached/network-failure reports had five onboarding pages, respectively
153/152/153 heartbeat ticks, and 0/0/2 intercepted network requests; cached modes
completed the synthetic import/model checks. Successful windowed runs removed
their temporary diagnostic logs. This remains a diagnostic freeze rather than
a tagged installer or native installation test.

After the `fc273e5` fix was pushed, the owner reran
`pytest -q -x tests/test_offline_session.py` on the Intel Mac and reported
**10 passed**. This accepts the Intel source offline diagnostic, including all
three session modes and the modal-failure/diagnostic regressions, on the
previously recorded macOS 15.7.9 environment. The reply did not include elapsed
time or a separate commit report; `fc273e5` identifies the fix supplied for that
retry. The final native bundle audit/frozen probes and installed-app walkthrough
are separate acceptance gates; the Intel build result follows below. The
[offline procedure](client-offline-acceptance.md)
retains a single-case command for future investigation.

### Signed Intel Mac candidate: September 19, 2026

The owner completed the tagged Intel Mac dry build and reported:

| Field | Recorded value |
| --- | --- |
| Client / target | `1.4.0` / `macos-x86_64` |
| Requested source candidate | `client-v1.4.0` at `42a3dac970459327d8f3144f40195f4166a98cc9` |
| Signed release sequence | `20260919222343` |
| Signature verification | Passed; one installer artifact |
| Inventory SHA-256 | `dff66e320cf2d97c3e8924707f1104de13f693926a7735808fd827c87776a655` |
| Release files | Three: DMG, client manifest, and detached signature; inventory retained alongside them |

The owner used the sibling `parsetrail-resources/clients/macos-x86_64` output
directory configured on that machine.
Retain that complete directory and the recorded inventory digest for later
verification/publication. The candidate tag remains pinned to its build source;
documentation-only acceptance commits do not change the built artifact.

Completion of the unchanged guarded Mac builder means the locked dependency
sync, full client tests, bundled public-key check, thin Intel executable check,
native library audit, 30-second runtime smoke, and all three 75-second offline
session probes passed before DMG creation and manifest signing. This accepts
the Intel tagged build/audit and O1 frozen-session gates. The supplied transcript
contains the final success lines rather than the complete inventory or test
summary; no precise test count, Mach-O file count, or DMG hash is asserted here.

The installer manifest is signed with ParseTrail's existing Ed25519 release key.
Apple Developer ID signing/notarization remains deferred. No artifact publication
was performed. Installed GUI first start/restart without networking or build-tool
paths, Keychain persistence, and the P2.2 walkthrough remain open, along with the
Windows tagged build and hosted CI results. Use the installed-app procedure in
[offline acceptance](client-offline-acceptance.md) with this preserved DMG. The
owner confirmed that the Intel Mac's staging profile was new before starting
the installed-app first-launch check.

### Intel installed candidate verification: September 19, 2026

The Mac assistant fetched and fast-forwarded the clean handover checkout from
`42a3dac` to `1f69b6e`, then created `test/intel-macos-native-acceptance`.
The existing ignored release configuration and preserved artifacts were retained.
Direct checks confirmed macOS **15.7.9 (24G830)** and **x86_64**.

- **PASS — preserved release:** `client-v1.4.0` still resolves to
  `42a3dac970459327d8f3144f40195f4166a98cc9`. The inventory SHA-256 remains
  `dff66e320cf2d97c3e8924707f1104de13f693926a7735808fd827c87776a655`.
  Public-key verification accepted release **20260919222343**, with one artifact.
- **PASS — installer identity:** the verified DMG is **126452768 bytes**, SHA-256
  `679b1e431cda4711146394a17662f70c19040142a006255dbd815d4d6c04b781`.
  The saved inventory records **379 Mach-O files**, one cryptography extension,
  a passing system-only-PATH runtime smoke, and passing `fresh`, `cached`, and
  `network-failure` frozen probes. Its actual build tools include **uv 0.12.7**,
  CPython **3.13.15**, and PyInstaller **6.21.0**; uv 0.12.5 in the earlier record
  was the preflight baseline. An exact final source-suite count was not recovered.
- **PASS — separate installation:** mounted the preserved DMG read-only, created
  the previously absent `~/Applications/ParseTrail-1.4.0-candidate` directory,
  copied `ParseTrail.app` with `ditto`, and compared bundle files with `diff -qr`
  successfully before ejecting the DMG. This was a command-line installation;
  Finder drag-and-drop and owner launch-prompt observations remain separate.
  The installed executable passed thin x86_64 Mach-O inspection. Its embedded
  version, source commit, tag, and target match the preserved candidate.
- **PASS — installed offscreen diagnostics (backend corrected September 26):**
  reran all three probes against the installed executable with system-only
  `PATH`. The diagnostic forces offscreen Qt internally. All reported
  `frozen: true`, `passed: true`, and five onboarding pages. Fresh/cached/failing
  network modes recorded **190/189/190 heartbeat ticks** and **0/0/2 intercepted
  requests**, respectively. Both cached modes completed synthetic local import
  and model operations. Each diagnostic owned a temporary profile; the staging
  profile remained absent afterward. These checks do not establish physical
  network disconnection, actual staging catalog access, or Keychain persistence.
- **FAIL — offscreen diagnostic attempt:** an initial sandboxed run with
  `QT_QPA_PLATFORM=offscreen` aborted in Qt's Mac wizard with
  `NSInvalidArgumentException` (`-[NSBundle initWithURL:]: nil URL argument`).
  The subsequent runs outside the sandbox all passed, also using the internally
  forced offscreen backend. The cause of the sandboxed failure is not isolated; no runtime fix
  or candidate rebuild is justified by this result alone. Use native Qt for
  the installed-app walkthrough, as specified in the handover.

**PASS — owner offline first start and restart:** after receiving the native,
system-only-PATH launch command and the five-step offline checklist, the owner
reported, "Everything ran fine as [STAGING] with no errors." This accepts the
requested fresh start, five-page guide, ten-second wait, local views/Preferences,
normal quit, and offline restart with database/onboarding persistence and no
blocking login. No launch error was reported; individual macOS prompt wording
was not supplied. A subsequent read-only check confirmed onboarding version 1,
an existing selected database inside the staging profile, automatic update
checks enabled, and no model files. This covers responsive empty-profile use
with enabled checks; supported imports after failed checks remain separate.

The `ParseTrail-Staging` profile was absent before that walkthrough and now
contains acceptance state. Preserve it. The results below include the completed
Move/Leave retention checks and final offline prediction audit.
Sanitized `PATH` does not establish operation on a machine where build
tools are physically absent.

**Owner backup report:** the owner reported successful backup creation and the
backup test function, then confirmed a STAGING window and a retained backup.
The supplied file was outside the staging profile and had older revision
`e0ecdd6abcc6`; read-only checks passed SQLite integrity and foreign keys, but
its schema and row counts differ from the current staging database. The latter
also passed integrity/foreign-key checks at `0003_precise_financial_schema`.
This accepts the owner's test of an existing older backup, not creation of a
current staging backup. No second SQLite file was found inside the staging
profile. A fresh **Back Up Database** / **Test Database Backup** check was
requested with a new destination inside the staging profile, preserving both
existing databases. No database was changed by these inspections.

**Staging prerequisites:** unauthenticated checks from this Mac initially failed
with curl exit **6**, HTTP **000** (hostname resolution), for
`https://api.staging.parsetrail.com/api/v1/` routes `plugins/manifest`,
`plugins/manifest-signature`, `clients/macos-x86_64/manifest`, and
`keys/public-key`. The owner confirmed connection to the staging LAN/VPN.
The documented LAN address with curl `--resolve` and normal HTTPS verification
returned **200/200/404/200**, respectively. No system hosts entry existed for the
API hostname; an attempted additive update stopped at `sudo`'s password
requirement without changing the file. The owner was given the local command.
The owner then reported applying it. A subsequent request to
`plugins/manifest` using ordinary hostname resolution and normal HTTPS
verification returned **HTTP 200**, closing the local DNS prerequisite.

The public plugin catalog's signature and schema verified against the installed
candidate's bundled keys, and all **22 artifacts** passed runtime compatibility
checks: release **20260829091732**, manifest SHA-256
`4a68f8035cc833f8bdc1e6f70578f84100d308a3eb3337c934eef92c7458a093`.
**PASS — staging login and signed plugin installation:** the owner subsequently
signed in with the staging account, downloaded the plugins, and confirmed they
appeared in Plugin Manager. A read-only verification of the staging profile's
active release checked its pointer, manifest signature, all **22 artifact sizes
and SHA-256 digests**, and runtime compatibility against the installed app's
public keys. Release sequence and manifest digest match the catalog above.
The native `ParseTrail-Staging` Keychain item exists; the metadata-only lookup
discarded its output and did not retrieve the token. The staging configuration
contains no nonempty plaintext access token.

**PASS — Keychain restoration and synthetic contribution:** after quitting and
reopening the installed staging candidate, the owner submitted the prepared
one-page synthetic PDF through **Statements > Send for Plugin Development** and
its normal confirmation. No second login was requested, and the server-accepted
popup appeared. The generated document contains only "ParseTrail smoke"; SHA-256
`625fa34df0e8181c6421cde3a26ae9c7c7ffb91c62486bb90482c05c28c9826b`.
No real financial fixture was uploaded. This accepts native credential reuse
after restart and the explicit contribution flow against staging.

**PASS — sign-out:** the owner confirmed **File > Sign Out of Server**, then
repeated the synthetic submission flow and canceled the newly displayed login
dialog. No second upload was intended. A subsequent metadata-only Keychain
lookup for the staging service/account returned **44** (item not found),
confirming deletion; the earlier lookup had returned **0**.

Five synthetic cumulative CSV fixtures were prepared locally for the remaining
offline import/model walkthrough. The installed signed MOHELA parser accepted
them without validation errors or warnings. Expected statement rows/balances
are **8/-396.00**, **10/-495.00**, **12/-594.00**, **14/-693.00**, and
**16/-792.00**. Original and working copies are separate. This is fixture
preparation; the owner's installed walkthrough and audit follow.

**PASS — owner offline import/model walkthrough, with recorded order variation:**
the owner reported that all checks passed while noting they did not follow the
order precisely. This covers the requested disabled/enabled-update offline
sessions, local responsiveness, installed-parser use, no-model guidance, training,
restart, and prediction. The report does not reconstruct the precise chronology.
The owner clarified that the two files originally proposed for Move and Leave
were imported with **Copy to Archive** instead. Those two retention choices were
therefore tested separately in the final check below, not inferred from this run.

The read-only audit found one synthetic account, **5 statements**, **16 canonical
transactions**, and **60 statement memberships**. Every fixture hash appears in
exactly one statement, with **8/10/12/14/16** memberships and matching end balances
**-39600/-49500/-59400/-69300/-79200 USD minor units**. All synthetic transaction
dates, descriptions, amounts, and running balances match the generated inputs
exactly. SQLite integrity and foreign keys pass at revision
`0003_precise_financial_schema`. The five preserved originals and working files
remain, each managed archive matches its input hash, and the folder-import input
was consumed while its fixture copy remained. This corroborates duplicate and
overlap handling, copy retention, and the reported folder-import move.

The local model is inside staging, uses bundle version `1.0-category-bundle`, and
records **16 training samples and 2 categories**. Independent reload predicted
all 16 saved rows into their stored categories. All 16 rows are categorized,
9 are verified, and automatic update checks are enabled in the saved config.
Because the model contains all initial 16 rows, two final synthetic exports with
new rows were prepared for Move/Leave and prediction without retraining after
another offline restart. They should yield **18/-891.00** and **20/-990.00**.
The final result follows below; the independent reload of the existing training
rows alone was not presented as prediction on unseen transactions.

**PASS — fresh staging backup and test restore:** following the clarified
instructions, the owner's all-checks-passed report includes creation and testing
of the new staging backup. The retained snapshot is inside staging, has the
current schema, and passes integrity/foreign-key checks. It contains the empty
pre-import state (zero accounts/statements/transactions), so row counts correctly
differ from the populated live database. A separate disposable restore matched
every row in every backup table and passed integrity checks. The live database,
snapshot, and earlier non-staging backup were preserved. Switching the installed
app to a new restored path was optional and **NOT RUN**.

**PASS — final Move/Leave and offline saved-model prediction:** the owner reported
following the final checklist precisely, with everything passing. It required
normal quit, network disconnection, native STAGING restart with system-only
`PATH`, importing two new synthetic exports into the existing account, and
categorizing their new rows with the saved model without retraining.

The final read-only audit confirmed:

- **Move to Archive:** the working source disappeared, its managed archive
  matches SHA-256 `ca8066ac1c70ab08e64c7de8f16795afddb433d6e0089783012d61f3426ce9b3`,
  and the preserved original remains. Its statement contains **18 rows** and
  ends at **-89100 USD minor units**.
- **Leave in Place:** the working source remains unchanged, no managed archive
  exists for it, and the preserved original remains. SHA-256 is
  `4779689f33560279261c3258c8ea7e7da27473284b6e5cee7784bae037fee41e`; its statement
  contains **20 rows** and ends at **-99000 USD minor units**.
- The final database has **7 statements**, **20 canonical transactions**, and
  **98 statement memberships**. Every expected synthetic date, description,
  amount, and running balance matches exactly. SQLite integrity and foreign keys
  pass at `0003_precise_financial_schema`; all seven fixture originals remain.
- The saved model still records **16 training samples and 2 categories**. Its
  independently reloaded predictions agree with all saved categories, including
  the **4 new rows** beyond the training export. The earlier **9 verified rows**
  remain verified. Onboarding version 1 and enabled automatic update checks persist.

This completes the approved Intel installed offline and P2.2 walkthrough using
synthetic fixtures. Local verification also reconfirmed the release signature,
original inventory digest, and pinned tag after the final check. No runtime
source change or replacement build was needed. Documentation changes passed
`git diff --check`; no full source-suite rerun or release rebuild was necessary.
The final dry-build source-suite count remains unavailable. Windows native
acceptance, hosted CI results, preserved-artifact publication, the coordinated
1.3-to-1.4 transition, and a machine with build tools physically absent remain
open; optional installed restore-to-new-path and Apple Silicon were not run.

The **404** for the 1.4 Intel installer manifest is a service
prerequisite for the later coordinated transition; no server change was made.
No replacement candidate, artifact activation, tag push, merge, or deployment
was performed.

### Windows tagged build preparation: September 19, 2026

After reviewing the completed Intel handover, the Windows assistant created an
isolated, clean checkout of the existing `client-v1.4.0` tag at
`42a3dac970459327d8f3144f40195f4166a98cc9`. The tag was neither moved nor pushed,
and no merge into `main` was needed. The build started on September 19 local
Pacific time (September 20 UTC), using a new client virtual environment.

- **PASS — bootstrap and locked sync:** native Windows 11 build 26200 / AMD64,
  managed CPython **3.13.15**, uv **0.12.5**, PyInstaller **6.21.0**, NSIS **3.12**.
  The package-free bootstrap ran before installing the locked client dependencies.
- **PASS — full source suite:** **451 passed, 3 skipped in 138.08s**. The skips
  cover Mac Bash integration and two POSIX `flock` cases. Bundled trust-key
  validation also passed.
- **PASS — tagged frozen build:** the unchanged tagged builder produced a
  **PE32+ AMD64** executable, then passed the bounded runtime smoke and all three
  real-entry-point offline modes: `fresh`, `cached`, and `network-failure`.
  These automated Windows checks used `QT_QPA_PLATFORM=offscreen`; installed
  native GUI and physical network-disconnection checks remain separate.
  This completes the Windows O1 frozen-session gate.
- **PASS — installer packaging:** NSIS produced
  `parsetrail_1.4.0_windows-x86_64_setup.exe`, **154450323 bytes**, SHA-256
  `08ee28ce3e64dd44f7efcbedf733fe2e31fda05f044ea8f08b7c8939731ccf07`.
  The frozen application executable SHA-256 is
  `655bfa4492f4fcda935e342e9206ccfbb2a224daf0ba45f06d0b06f19ec4c7ce`.
  Its embedded metadata independently matches version **1.4.0**, the pinned
  source/tag, Python **3.13.15**, and target **windows-x86_64**.

The assistant stopped the builder at its signing boundary so the owner can
enter the encrypted key's passphrase in their own terminal. At that boundary,
the target output directory contained only the installer: **no signed manifest,
detached signature, or release inventory existed yet**. The local handoff checks
the clean checkout, tag, and installer digest before using the tagged
`scripts.client_release sign` / `verify` and `scripts.release_inventory` commands.
It preserves these bytes and does not repeat packaging. At this stage the
candidate awaited signing; the completed signed dry run is recorded below.

The ignored local checkout is `scratch/windows-1.4.0-candidate`; its full build
log is `scratch/windows-1.4.0-build.log`, SHA-256
`6405c67818a9a7973fbfa8c96918a65b2f4e0c2c31510f556d78a1c4166a7936`.
The operator signing handoff is `scratch/sign-windows-1.4.0.ps1`; its PowerShell
syntax check passed. These are local operator files rather than release payloads.

An installed ParseTrail application and a `ParseTrail-Staging` profile already
exist on this Windows account. Preserve both. A separate Windows account can
isolate user data and credentials, but installation state is machine-wide:
the NSIS installer detects and uninstalls a previous installation registered in
HKLM. Neither another account nor an alternate install directory isolates that
installation. Use a disposable VM/second PC for a fresh installation, or prepare
an owner-approved upgrade of the existing installation with retained backups.

The focused `test/windows-native-acceptance` branch was pushed for a draft PR.
SSH Git access works, but no authenticated GitHub API/CLI credential was
available to create the PR automatically. The owner received the prepared PR
link; hosted CI remains pending until it is opened. No installation, artifact
publication, release-tag push, merge, or deployment was performed.

### Signed Windows candidate: September 19, 2026

The owner ran the local signing handoff and reported successful signing,
verification, and inventory generation. A subsequent independent read-only
review accepted the public-key signature, matched the reported inventory digest,
and verified the sizes and SHA-256 digests of all three recorded release files.

| Field | Recorded value |
| --- | --- |
| Client / target | `1.4.0` / `windows-x86_64` |
| Source | `client-v1.4.0` at `42a3dac970459327d8f3144f40195f4166a98cc9` |
| Signed release sequence | `20260920064925` |
| Inventory SHA-256 | `7661e24a9b46edb5709091f8d29271b7b9cea49cf58b8b23275ee6196971b8a1` |
| Installer SHA-256 | `08ee28ce3e64dd44f7efcbedf733fe2e31fda05f044ea8f08b7c8939731ccf07` |
| Installer size | `154450323` bytes |

The installer bytes are identical to the already-tested, pre-signing artifact.
The inventory agrees with the pinned source/tag, target, architecture, manifest
schema **2**, release sequence, version, and recorded build tools. Retain the
complete sibling `parsetrail-resources/clients/windows-x86_64` directory and the
original inventory digest. This completes the Windows tagged signed dry run;
its source tests, native build, and frozen checks are recorded immediately above.
No rebuild or repeated source suite was necessary for this signing follow-up.

The signature is ParseTrail's Ed25519 manifest signature; Windows Authenticode
remains deferred. No installation or publication was performed. This Windows
host reports edition **Core (Home)**, version **25H2**, and no Windows Sandbox
launcher. The owner is choosing a disposable Windows VM/second PC or preparation
of a backed-up upgrade on this PC for the native installed walkthrough; the
owner subsequently selected this PC, as recorded below.

The GitHub read-only check still found no PR or Actions run for
`test/windows-native-acceptance`; hosted CI remains pending. The existing
prepared draft-PR link starts that work without merging into `main`.

### Windows upgrade safeguards: September 20, 2026

The owner approved using this PC after preparing backups. The installed app is
registered as **1.3.0** in the 32-bit HKLM view. No ParseTrail process was running
during preparation. Before installation, the assistant copied and independently
verified **3,654 files / 588511211 bytes** covering the old installed app, both
profiles, the configured financial database, managed statement archive, models,
and reports. It also retained **two registry exports** and created **two SQLite
snapshots**. Each snapshot passed integrity and foreign-key checks and matched
its source's complete logical SQL dump digest.

The private backup is retained locally at
`scratch/windows-1.4.0-upgrade-backup-20260920T065839Z`. Its completion manifest
SHA-256 is `f8307f5fd9c06b5b3720e93d76ecfbb56733bb8c436123ce7a6124edec36aca4`.
The manifest and copied financial files are ignored local material, not Git
artifacts. No OS credentials were exported. Restoring the prior application
and machine registry would require owner administrator action; no rollback was
performed or claimed as tested.

A sandbox-context metadata lookup found no `ParseTrail-Staging` credential;
that lookup did not establish absence in the owner's Credential Locker. After
backup verification, the existing staging folder was preserved beside its original
location as `ParseTrail-Staging.pre-1.4.0-20260920T065839Z`; the active staging
path is now absent for the fresh-profile walkthrough. The production profile
and its configured data remain in place. This isolates application data for
the walkthrough while allowing the approved machine-wide installer upgrade.

The ignored owner handoffs are `scratch/install-windows-1.4.0.ps1` and
`scratch/launch-windows-1.4.0-staging.ps1`. The installer handoff rechecks every
backup file, the unchanged original sources (including the preserved staging
folder), installed version, and candidate installer hash before showing the
native installer. It then checks the installed executable hash. The separate
launcher uses native Qt, system-only `PATH`, and the staging API/profile.
Both scripts passed PowerShell syntax checks, and the complete backup/source
verification passed again after preserving the staging folder. **The installer
and installed app have not yet been run.** Owner steps are in
[Windows installation and first offline launch](client-offline-acceptance.md#windows-140-candidate-installation-and-first-offline-launch).

**Installer handoff interruption:** the owner's first attempt ended with
`KeyboardInterrupt` while reading a backup file, before launching the installer.
The subsequent read-only registry check still showed **1.3.0**. The local helper
now reports progress and elapsed time every two seconds, handles cancellation
without a Python traceback, and supports `-VerifyOnly` through the same
PowerShell entry point. Its standard-library verifier uses isolated, unbuffered
Python (`-I -u`) and does not require Conda activation. Running that entry point
with `-VerifyOnly` in the owner's normal execution context passed all **7,312
file checks in 34.5 seconds**, followed by the candidate installer hash check.
The backup, original app/data, and prepared fresh staging state still matched.
This follow-up did not launch the installer or change the signed candidate.

### Windows installed offline acceptance: September 20, 2026

The owner completed the prepared installer and staging launcher and reported
the **[STAGING] 1.4.0** window open. Read-only verification confirmed the machine
registry now reports **1.4.0** and all **2,528** packaged application files match
the tagged build exactly. The installed executable SHA-256 remains
`655bfa4492f4fcda935e342e9206ccfbb2a224daf0ba45f06d0b06f19ec4c7ce`.
All **1,091** backed-up production profile/database/archive/report files still
match their original hashes. The prior staging folder remains preserved.

**PASS — fresh offline first start and restart:** the owner explicitly confirmed
networking was disconnected during the initial launch and again for the second
staging launch, and reported that the requested checks all passed. This accepts
the five-page onboarding, offered staging database location, ten-second wait,
responsive local views and Preferences, normal quit, and offline restart with
the database retained, onboarding complete, and no blocking login. No installer
or launch error was reported. The independent config check found onboarding
version **1**, enabled automatic update checks, the staging API URL, an existing
database inside the staging profile, no trained model, and no plaintext token.
Installed-parser/model use and the rest of P2.2 remain pending.

**OPEN — Windows About provenance:** the file comparison also exposed a release
packaging defect. Windows copies the correctly populated metadata into the bundle
under a random `parsetrail-build-<id>.json` filename, while the application's
resource reader requires `parsetrail/build-metadata.json`. Resolving the actual
installed resource directory through that reader returns no metadata and the
About label `development source`. The signature, inventory, and file hashes
remain valid; the defect is the application's access to its embedded provenance.
Correct the Windows resource filename and add a frozen smoke gate before the
next candidate. Preserve the signed 1.4.0 bytes and tag; a replacement must use
a new version/tag. Continue the remaining native workflow checks on this
identified candidate while collecting any additional fixes.

**PASS — source fix and diagnostic frozen gate:** the Windows builder now stages
`build-metadata.json` inside a unique temporary directory, preserving the
canonical bundled filename and cleaning up after early failures. Frozen runtime
smoke requires readable schema-2 metadata whose version and target match the
running client. Source runs continue to work without release metadata. Regression
coverage uses the real resource resolver for the About label and smoke path,
rejects missing/misnamed/mismatched metadata, and exercises PowerShell builder
cleanup before dependency sync. The complete Windows client suite passed
**459 tests, 3 skipped**; Ruff check/format and PowerShell syntax checks passed.

An unsigned diagnostic freeze of the changed source passed runtime smoke with
the canonical resource and a system-only `PATH`. Renaming only that diagnostic
resource to the old filename pattern caused exit **1** with the expected missing
metadata error; the canonical resource was then restored byte-for-byte. This
probe used explicitly synthetic source metadata and is not a release candidate.
The installed app, signed installers, and `client-v1.4.0` tag remain unchanged.
The replacement candidate and its installed About check remain open.

**PASS — signed plugin installation and Windows credentials:** the owner
reconnected, downloaded plugins using staging credentials, and confirmed they
installed correctly. Independent local verification against the installed app's
public keys accepted all **22** artifacts in release **20260829091732**, including
runtime compatibility, sizes, and digests. The manifest SHA-256 is
`4a68f8035cc833f8bdc1e6f70578f84100d308a3eb3337c934eef92c7458a093`.
An owner-context, metadata-only Credential Locker lookup found the staging
credential; no secret was read or exported, and config contained no plaintext
token.

After quitting and restarting online, the owner successfully submitted the
generated one-page PDF containing only `ParseTrail smoke` through the normal
confirmation flow, without another login. This accepts Credential Locker
restoration across restart. The PDF SHA-256 is
`625fa34df0e8181c6421cde3a26ae9c7c7ffb91c62486bb90482c05c28c9826b`.
The owner then signed out and repeated the flow: it requested credentials, and
signing back in allowed a second successful synthetic submission. This accepts
functional sign-out/relogin. The owner completed login rather than cancelling
the dialog, so credential-store absence between those actions was not observed.
No real financial fixture was submitted.

**Fixture preparation correction — offline imports remain pending:** the first
generated MOHELA CSVs reached `NoParserMatchError` because CSV-writer escaping
doubled quotes in the header marker. The earlier preparation check invoked the
parser directly and missed the application's raw-text routing step. Reproducing
the error against the complete installed catalog identified the fixture problem.
Corrected copies preserve the parser's expected export header and pass
`parse_any` against all 22 authenticated plugins, selecting only
`csv_mohela_202411` with no validation diagnostics. The seven files produce
8/10/12/14/16/18/20 transactions and final balances from **−396.00** to **−990.00**
USD. The original attempted fixtures remain unchanged; corrected masters,
working copies, and expected hashes are retained under the ignored local
`scratch/windows-1.4.0-native-fixtures/routing-checked` directory. This routing
check does not substitute for the pending installed-app imports.

**PASS — installed offline one-off imports, duplicates, and overlap:** the owner
successfully imported the corrected first two fixtures and reported the expected
**−495.00 USD** total. Read-only verification found one synthetic account, two
statements, **10 canonical transactions**, and **18 statement memberships**. All
dates, descriptions, integer amounts, running balances, and currencies matched
the synthetic expectations exactly. Both archived statements matched the
expected SHA-256 digests; both working sources and master originals remained
unchanged. SQLite integrity and foreign-key checks passed. The application log
also recorded the repeated first file as a retained duplicate, with no added
statement or transaction. Automatic update checks were disabled.

The owner reported missing-categorization-model errors after each import. The
profile has no model; all 10 transactions remain uncategorized and unverified.
The log contains three missing-model exceptions, consistent with categorization
being attempted after both successful imports and the duplicate retry. The
current UI reports `Auto-categorization Failed` after data has already committed.
This accepts the local import/data-preservation behavior, not the quality of
first-use guidance. Actionable no-model guidance remains part of the unapproved
F1 proposal; no feature implementation was started. Folder import, training and
prediction, Move/Leave choices, enabled-check offline behavior, and database
backup/test restore remain pending.

**PASS — installed offline folder import and training inputs:** the owner
completed **Statements > Import All** for the prepared third fixture, then copied
the fourth and fifth fixtures into the archive through one-off import, reporting
the expected **−792.00 USD** total. Read-only verification found **five statements,
16 canonical transactions, and 60 statement memberships**. Every transaction
matched the synthetic expected dates, descriptions, integer amounts, running
balances, and USD currency. All five archived files matched their expected
SHA-256 digests, and the third fixture no longer existed in the managed input
folder. All seven master and working copies remained unchanged. SQLite integrity
and foreign-key checks passed, and automatic update checks remained disabled.

The 16 imported rows were still uncategorized and unverified at this checkpoint;
no categories or model existed. The last two fixture hashes were absent from the
database, preserving four new transactions for prediction acceptance after
training. Native category assignment, model training/restart/prediction,
Move/Leave choices, enabled-check offline use, and backup/test restore remain
open. This checkpoint does not claim model acceptance.

**PASS — native offline category review and model training:** the owner completed
the category assignment and **Train Model for Deployment** steps and reported a
saved `.mdl` file. Read-only verification found all **16** training rows verified,
with eight payment rows assigned `Synthetic Payment` and eight interest rows
assigned `Synthetic Interest`. The profile-selected model exists inside the
staging profile and loads as bundle version **1.0-category-bundle**, recording
**16 samples and two categories**. Its size is **2923 bytes**, SHA-256
`eaa000e540b85524a8e0c8f9be8d76254ab0a6cc8b88a7ebe143a331092f8894`.
The database retains five statements and 60 memberships; integrity and
foreign-key checks pass. Automatic update checks remain disabled.

Both remaining prediction fixtures still match their original hashes in the
working directory. The model checksum is retained locally for comparison after
restart and prediction, so successful use of this saved model can be separated
from retraining. This accepts native labeling, persistence, and training only;
restart, predictions on new rows under both offline update settings, Move/Leave
choices, and backup/test restore remain pending.

**PASS — installed offline saved-model predictions and Move/Leave choices:**
the owner followed both restart sequences with networking disconnected, first
with automatic checks disabled and then enabled, and imported the final two
fixtures with **Move to Archive** and **Leave in Place**, respectively. The owner
reported **−990.00 USD** and no further errors. Read-only verification found
**seven statements, 20 canonical transactions, and 98 memberships**, with every
financial field matching the synthetic expectations. The four new rows have
the correct payment/interest categories and confidence values and remain
unverified; all 16 original manual labels remain verified. The model SHA-256
is unchanged from training, proving the saved model was used without retraining.

The moved working file is absent and its archive hash matches. The Leave source
remains unchanged without a managed archive copy. All seven masters and the
other six working sources retain their original hashes. SQLite integrity and
foreign-key checks pass. Config now enables automatic checks; the log records
client and plugin update failures during the second restart, while the subsequent
local import and prediction succeeded without a blocking login or model error.

This completes **Windows P1.6 installed offline acceptance**, alongside the
previously accepted Intel walkthrough and automated source/frozen network-denial
checks. Physical disconnection demonstrates local usability; the automated
interception checks provide the evidence for zero network attempts when checks
are disabled. The empty-profile parser starter pack and improved no-model
guidance remain F1 proposals. Windows database backup/test restore remains the
last P2.2 walkthrough item; replacement-candidate provenance, hosted CI, and
publication/transition rehearsal remain separate release gates.

**PASS — native database backup and disposable restore test:** the owner reported
both **Backup Verified** and **Restore Test Passed** for the final synthetic
database. Independent read-only checks accepted the backup's SQLite integrity,
foreign keys, schema revision **0003_precise_financial_schema**, and complete
logical dump equality with the live database. Both contain **one account, seven
statements, 20 transactions, 98 memberships, and two categories**. The active
database path remains unchanged; no switch to a restored database was requested.

The local `windows-native-final.dbb` is **106496 bytes**, SHA-256
`ced63f582732093456380f3d53883ef4e23aee0dc3a9d2b2ae0bca42ffbf9917`.
The matching logical dump SHA-256 is
`4cc4de89780006493529035de6af078720c5f317eb141c5b9a31d724ca059363`.
The backup remains inside the staging profile and contains database data only,
not statement files or the model. This completes the **Windows P2.2 native
walkthrough**. Windows and Intel P1.6/P2.2 acceptance is now recorded; retain the
1.4.0 candidates as evidence and prepare a separately versioned candidate for
the Windows provenance fix. Later cleanup/features remain outside authorization.

### Windows 1.4.1 candidate: September 20, 2026

The complete Windows walkthrough exposed only the already-fixed release
provenance defect within the approved implementation scope. The no-model error
wording remains a recorded F1 proposal. A new **1.4.1** version preserves the
signed 1.4.0 artifacts and tag rather than replacing their bytes.

| Field | Recorded value |
| --- | --- |
| Build branch | `release/client-1.4.1` |
| Exact source / local tag | `0261f1f9d4efc4ba6aa7e7e31df4f421ef628ebd` / `client-v1.4.1` |
| Client / target | `1.4.1` / `windows-x86_64` |
| Installer | `parsetrail_1.4.1_windows-x86_64_setup.exe` |
| Installer size | `154450316` bytes |
| Installer SHA-256 | `7bd95d347c72ce9aebefc9d7741d60b6483c6b400c6c89ff288fcd520c558f0b` |
| Frozen executable SHA-256 | `89712148036e7b7647f3ec44cdfe91fd5e267a8785deb4dea3245cc6684a9bc6` |
| Canonical metadata SHA-256 | `2767ac98f34b7a167804e27cec947670d46e2ca700e70487139e4f87c7c8dbb4` |
| Signed release sequence | `20260921030412` |
| Release inventory SHA-256 | `1883101dd467ae52d35e2c8d892a6dc501560240279f1103922f578490b84584` |

**PASS — tagged build:** an isolated clean checkout at the exact tag completed
the pinned Python **3.13.15** bootstrap and locked sync, **459 tests / 3 skipped
in 91.63 seconds**, public trust-store check, PyInstaller freeze, **PE32+ AMD64**
architecture gate, frozen runtime smoke including provenance, all three frozen
offline modes, and NSIS packaging. The local lock check also passed without any
dependency changes. These automated Qt checks used the offscreen platform;
replacement installed-app acceptance remains separate.

The canonical resource contains the exact source/tag/version/target above, and
the application's resource reader against the actual bundle now returns About
label **`client-v1.4.1 (0261f1f9d4ef)`**. No misnamed metadata file remains. The
complete build log is retained locally as `scratch/windows-1.4.1-build.log`,
SHA-256 `9e8ae2843e8c096f227fbd480936024981a782f08a21812d6a690c1d5410abff`.

The preserved signed candidate is in
`scratch/windows-1.4.1-release/windows-x86_64`; its source checkout is
`scratch/windows-1.4.1-candidate`. The owner completed the separate signing handoff
without rebuilding the installer. **PASS — signing verification:** independent
public-key verification accepted the release, and all three inventory file sizes
and SHA-256 hashes matched. Source, tag, version, target, and sequence matched the
candidate; the installer retained its pre-signing hash above. Local evidence is
`scratch/windows-1.4.1-signed-verification.json`. Signing did not install or publish
the candidate.

The old 1.4.0 installer, manifest, signature, and inventory retain all recorded
hashes. The installed application remains 1.4.0; no replacement installation,
artifact publication, release-tag push, merge, or deployment has occurred. The
1.4.1 tag is local only. Documentation commits may advance the branch after the
pinned build source. The [Intel 1.4.1 handover](intel-mac-1.4.1-handover.md) specifies
that same source and separate artifact/app locations.

Hosted checks run on pull requests or main pushes. The owner opened PR #38 as
recorded below; merging into main is not required for local builds or hosted checks.

### Windows 1.4.1 private database-copy preparation: September 21, 2026

The owner agreed to a short local acceptance check with their existing financial
data before merging. **PASS — preparation:** with ParseTrail closed, the completed
synthetic staging profile was preserved, SQLite's online backup API produced a
consistent snapshot of the live database, and the snapshot matched its source's
table counts, logical digest, integrity, foreign keys, and current schema revision.
The working database, model, managed statement archive, and authenticated staging
plugin catalog were copied into a separate directory inside the staging profile.
Every copied file passed checksum verification; the source database and both
active profile configurations remained unchanged.

The pinned candidate's settings validation accepted the prepared configuration.
All 22 signed plugins loaded, and the copied model loaded without warnings or
missing database categories. Automatic update checks are disabled. No pending
live import files were copied into the working import queue, and OS credentials
were not exported. Private data, file inventories, hashes of financial files, and
model contents remain in ignored local evidence rather than this repository.

The owner handoff `scratch/launch-windows-1.4.1-real-data.ps1` verifies preserved
evidence and the candidate identity before selecting the copied database. Its
`-VerifyOnly` run passed without selecting a profile or opening the GUI. Normal
invocation runs the frozen 1.4.1 executable directly with a system-only `PATH`;
`-RestoreSynthetic`, after closing the app, restores the saved synthetic staging
configuration while retaining both databases and the working copies. This local
launcher is specific to the prepared evidence and is not a distributed tool.

The owner opened the prepared frozen build and reported the desktop regressions
below. Native acceptance remains incomplete; subsequent checks must use the fixes.
Direct execution of a frozen build does not complete installer replacement
acceptance. The installed application remains 1.4.0, and no merge or publication
has occurred.

### Windows desktop control regressions: September 21, 2026

The private-copy walkthrough exposed three failures in the preserved 1.4.1
candidate: Category Spending's Select All could clear but not check items,
Budgets always showed its failure placeholder, and the configured log file was
absent. Local inspection found the budget traceback in the default staging log;
logging had ignored the saved custom path.

Branch `fix/client-desktop-controls` corrects these existing behaviors:

- Both dashboard Select All controls consume the checkbox's boolean `toggled`
  signal. The previous integer `stateChanged` value did not equal PySide6's enum.
- Budget, appreciation, and recurring-input date controls use PySide6's
  `QDate.toPython()`. The old `toPyDate()` raised `AttributeError`.
- Budget spending-share aggregation keeps small-category amounts as `Decimal`
  until chart presentation. Fixing date conversion exposed a second failure when
  a small category was added to the float accumulator for Other.
- Startup logging uses the loaded settings' log path and creates its parent
  directory. Normal and staging profiles honor their saved paths.

**PASS — regression checks:** all ten new synthetic checks failed before the
fixes. The focused UI, budget-service, settings/profile, and offline checks then
passed **40 tests**. The full client run passed **468 tests / 3 skipped**, with one
Windows builder test blocked by the sandbox's PowerShell execution policy; that
single test passed when rerun in the owner's normal context without changing
policy. Ruff lint/format passed. No recurring-analysis algorithm, financial
schema, feature proposal, or infrastructure change is included.

**PASS — confidential read-only check:** the real Budgets widget rendered eight
combinations of month/custom range, category/type grouping, and inactive-category
filtering using the preserved database snapshot. Its checksum and the original
live database checksum remained unchanged. Only aggregate pass/fail evidence is
recorded here; private labels, amounts, dates, and log contents remain local.

**PASS — native control retest:** the owner confirmed the fixes while using the
prepared database copy and fixed source at `1a002e3`. Local verification confirmed
that the configured log file exists and is nonempty and the live database remains
unchanged. During this walkthrough, the owner reported blank transaction-review
dates; that separate defect is recorded below.

Signed 1.4.0/1.4.1 bytes and existing tags remain unchanged; neither contains these
repairs. A new version/tag must identify the replacement builds on Windows and
Intel macOS. The previous Intel 1.4.1 build handover remains on hold.

### Transaction review date rendering: September 21, 2026

The review service returned valid Python calendar dates, but Qt's table delegate
rendered those objects as empty text. Qt's proxy also could not sort the opaque
objects chronologically. The fix in `gui/review_models.py` returns ISO
`YYYY-MM-DD` strings for the date column's display and sort roles. Service records
and stored dates retain their calendar-date types; no database writes or migration
are needed.

**PASS — regression checks:** three synthetic tests reproduced blank delegate
text and incorrect ascending/descending ordering before the fix. The repaired
model passes those tests, including a leap-day date and year/month boundaries;
the combined review-service/model and previous desktop/logging regression run
passed **19 tests**. Ruff lint/format passed.

**PASS — confidential read-only check:** every review date in the preserved
database snapshot reached the real Qt delegate as its expected ISO text, and both
sort directions matched calendar ordering. The snapshot and live database hashes
remained unchanged. Financial dates, descriptions, and account identifiers were
not printed or committed.

**PASS — native acceptance:** the owner confirmed dates work after the requested
display and two-direction sorting retest, using fixed source at `c567330`. The
owner then accepted the existing feature set and requested development closeout.

### Client development closeout: September 21, 2026

The owner accepted the existing client feature set after the Windows controls,
budget/logging, and transaction-review date retests. This closes the client
development and supplemental private-copy investigation in the approved scope.
No additional feature proposals or C1–C3 implementation were started. The original
Windows and Intel native synthetic walkthrough evidence remains applicable to
the preserved candidates; the later desktop fixes have Windows native source
acceptance and the regression evidence above.

The final repairs are `1a002e3` (desktop controls, budget rendering, configured
logging) and `c567330` (review-date display and sorting), developed on
`fix/client-desktop-controls`. The closeout advances the existing
`release/client-1.4.1` review branch to include those commits for
[PR #38](https://github.com/tbrownhe/ParseTrail/pull/38). The branch name does not
change the immutable source of the already signed 1.4.1 artifacts.

Private test data, models, logs, working copies, and preserved profiles remain
local and untracked. The source-review launcher still selects the prepared copy
inside STAGING; the original live database and preserved synthetic profile are
retained. Closing the app and using the original handoff's `-RestoreSynthetic`
mode remains the way to return STAGING to its saved synthetic configuration.
The supplemental duplicate-import, model, and backup walkthrough on real data
was not performed; those workflows already have native synthetic acceptance.

The development closeout does not claim a replacement installer or published
release. New Windows and Intel candidates must include these repairs under a new
version/tag, pass their frozen and native release gates, and rehearse preserved
artifact publication and the 1.3-to-1.4 transition before public activation.
Operation on an Intel machine physically lacking build tools remains a recorded
acceptance gap. Apple Silicon remains deferred. These unfinished release items
and the unapproved future proposals stay in TODO; no further native test is
requested as part of this development closeout.

### Windows 1.4.2 candidate: September 21, 2026

After the owner merged PR #38, the remote main commit
`7bf64c7f453ea9c0ec46986cba3196664a9861d5` was verified to contain all accepted
client repairs. Branch `release/client-1.4.2` changes only the client version at
its pinned build commit; the dependency lock remains unchanged and its offline
check passed. Later branch commits contain release documentation.

| Field | Recorded value |
| --- | --- |
| Exact source / local tag | `4585f4c57d20101c1c6ac4f625b726e51913e562` / `client-v1.4.2` |
| Client / target | `1.4.2` / `windows-x86_64` |
| Installer | `parsetrail_1.4.2_windows-x86_64_setup.exe` |
| Installer size | `154450900` bytes |
| Installer SHA-256 | `733e5f6b0856f5225b56ba94bbd49c8543e6f758fde84aff68e677cd62ba7cd0` |
| Frozen executable SHA-256 | `d517e06fa842d07b34a7510ca7bfec3657a5d0e21d29607e49e7cdd933e9dca0` |
| Canonical metadata SHA-256 | `4927f076adf5aa9e50288d3113693c001012c8abf48f28b108528a0a2c584f27` |
| Signed release sequence | `20260922070935` |
| Release inventory SHA-256 | `37b23405475eeda83a732d7ebe2962b59b7bdf6e6901bc095656a40fa3df0162` |

**PASS — tagged Windows build:** the isolated clean checkout completed the pinned
Python 3.13.15 bootstrap/locked sync, **472 tests / 3 skipped in 96.21 seconds**,
public trust-store check, PyInstaller build, PE32+ AMD64 architecture gate, frozen
runtime/provenance smoke, all three frozen offline modes, and NSIS packaging.
Automated Qt checks used the offscreen platform. The canonical build metadata
matches the exact source/tag/version/target above. The full local build log is
`scratch/windows-1.4.2-build.log`, SHA-256
`b0e6986d7851763ac9a5471d35f4b86dd70e4e7b659d67a4d36987fe56c8c9e9`.

The signed installer is preserved in `scratch/windows-1.4.2-release/windows-x86_64`
and its tagged checkout in `scratch/windows-1.4.2-candidate`. The owner completed
`scratch/sign-windows-1.4.2.ps1`, supplying the passphrase privately, after its
verification-only mode had checked the source/tag, pristine checkout, installer
and metadata hashes, prerequisites, and preserved older release files.

**PASS — signing verification, September 22:** independent public-key verification
accepted sequence `20260922070935`. The inventory matched the owner's recorded
digest above; all three listed file sizes and SHA-256 hashes matched. Source,
tag, target, version, architecture, and interpreter matched the pinned candidate.
The installer retained its pre-signing hash, and all preserved 1.4.0/1.4.1 release
files remained unchanged. The tagged checkout is clean. Local evidence is
`scratch/windows-1.4.2-signed-verification.json`.

**PASS — native release acceptance, September 26:** Windows and Intel installed
walkthroughs subsequently passed; see the records below and the
[Intel return note](intel-mac-1.4.2-return-note.md). The local candidate tag has
not been pushed and no artifact has been published. The old signed candidates
and tags remain unchanged.

**Read-only interface preflight:** staging's client listing still advertised
legacy `win64` 1.3.0 and `macos` 1.3.1 channels, and its legacy Windows manifest
reported schema 1. The planned API/download-page transition must therefore be
rehearsed with the new target channels before public activation. Direct production
listing/manifest requests returned HTTP 403; this probe does not establish its
active contract. Verify it from the authorized operator path during publication
review. No deployment or server setting was changed by these checks.

**PASS — refreshed Windows upgrade preparation, September 26:** with the app
closed, copied and verified **4,643 files / 817,266,779 bytes**, two consistent
SQLite snapshots, and two application registry exports. Backup manifest SHA-256
is `b054ce0897df9590fd4d30370e6cd4769e570a233adec9c6cc3bbe584975dff9`.
The prepared installer helper passed **9,296 pre-install checks**, including all
backup hashes, unchanged originals, selected private staging copy, registered
1.4.0 application, pinned inventory/artifacts, and public-key signature verification.
No installation or launch occurred. The [Windows handoff](windows-1.4.2-acceptance.md)
contains owner steps and the private evidence location.

**PASS — Windows installed acceptance, September 26:** the owner confirmed
STAGING/About identity, repaired controls, and offline restart. Independent
closed-app checks accepted the complete installed tree against the build,
registered version and pinned executable/metadata hashes, signed artifact, and
all **4,647 backup records**. **2,112 original data files**, including production
files and the staging model/plugins/archive, are unchanged. The selected working
database retained every application/internal table's schema and rows despite
file-byte changes; integrity and foreign keys passed. Staging configuration is
unchanged. Its configured custom log appended **22 entries / 2,970 bytes**, latest
**16:54:55**, with zero new ERROR/CRITICAL entries. Local evidence is
`scratch/windows-1.4.2-owner-acceptance-verification.json`; the
[Windows acceptance record](windows-1.4.2-acceptance.md) preserves details.

### Intel 1.4.2 candidate: September 26, 2026

The pinned clean source `4585f4c57d20101c1c6ac4f625b726e51913e562` and local
`client-v1.4.2` tag completed the native Intel build on macOS 15.7.9 (24G830).
The source suite passed **470 tests with 5 skipped**. Thin x86_64 architecture,
the **379-file** native loader audit with one cryptography extension, frozen
provenance/runtime smoke, all three offscreen offline modes, DMG packaging,
private Ed25519 signing, and independent public-key verification passed.

Release sequence is `20260926200410`. The DMG is **126446802 bytes**, SHA-256
`b3a25c5b6f1f0611acefb41fa29187883064eb1abff4b40b7526e93d4a07e7b5`.
Inventory SHA-256 is
`677c6cc99eccacf8956010cc1758ea71e37fb14d9d4848f841731284ec2311ae`;
every listed size/hash matched, and canonical metadata matches the pinned
source/tag/version/target. The full evidence and remaining acceptance status are
in the [1.4.2 Intel return note](intel-mac-1.4.2-return-note.md).

The separately installed DMG app matched all **2,141 file/symlink entries** in
the built bundle and passed thin x86_64 inspection. Its isolated installed
runtime smoke and all three offscreen offline probes passed with system-only
`PATH`; heartbeat counts were **189/190/189**, intercepted requests **0/0/2**.
**PASS — owner native GUI acceptance:** the owner confirmed all checklist tests
passed, including STAGING 1.4.2/About `client-v1.4.2 (4585f4c57d20)`, preserved
synthetic data/model/plugins, responsive offline views, both Select All controls,
budget date/grouping modes, review-date rendering/sorting, configured logging,
and offline quit/reopen without blocking login. No defect was reported.

With the app closed, independent verification found the selected custom staging
log with **15 current-day entries**, preserved prior log/config backup, intact
SQLite integrity/foreign keys, unchanged application-table rows, and unchanged
cached plugin/model bytes. Only internal SQLite planner statistics changed.
All original backup and older-release checksums still match. This accepts the
Intel owner walkthrough separately from automated diagnostic backend coverage.

The earlier release files, installed 1.4.0 app, and original release config
matched their pre-build checksums. The closed staging profile was backed up and
all 44 file copies verified before candidate use. No release tag was pushed,
artifact published, or production deployment performed.

**Resolved handover wording, September 26:** the pinned offline diagnostic explicitly forces
`QT_QPA_PLATFORM=offscreen`; clearing the caller's variable does not make it
native. Its installed runs must be reported separately from the native owner
walkthrough. The same code exists in 1.4.0, so the earlier native-diagnostic
description does not establish its backend. This clarification preserves the
original return note and does not alter the separate owner GUI acceptance.
The original offline acceptance contract separates automated source/frozen
probes from the native owner walkthrough. Both passed. The 1.4.2 handover's added
request for three native automated offline runs was a documentation error;
correcting it requires no source change or candidate rebuild. No native backend
coverage is claimed for these probes. R2's physically absent build-tool
environment remains open, as does the coordinated staging publication/upgrade
rehearsal. Windows installed acceptance subsequently passed as recorded above.

### Simplified desktop release workflow: September 26, 2026

The owner required simplification before publishing 1.4.2. Commit
`c80306b13f9084cae43aec0249d3084965d7800e` on `feat/client-release-workflow` adds
key-free native packaging, one GitHub Actions matrix, and a paired local release
command. It retrieves/validates CI artifacts, prompts once for signing both
targets, preserves native builder provenance, and manages reviewed staging/public
promotion from one saved release record. The adoption path copies existing signed
output unchanged. The [short operator guide](client-releases.md) replaces bespoke
scripts for the routine path.

The full local Windows suite passed **500 tests / 3 skipped**. Two further
rejection cases were added afterward; the final focused run passed **30 tests**.
Coverage includes rejected validation/fork/failed CI runs, unsafe archives,
changed inputs, both-target validation before signing, one passphrase prompt,
unchanged adoption, preserved native metadata, staging-before-production, and
resumption after a partial second-target upload without replacing existing bytes.
Python lint/format, PowerShell/Bash syntax, and pre-commit YAML checks passed.

[Hosted run 36282715627](https://github.com/tbrownhe/ParseTrail/actions/runs/36282715627)
passed **both Windows x64 and Intel macOS packaging jobs**, plus the paired
completion job. Each native builder ran the source suite, architecture and
frozen-runtime/offline gates and produced its installer/build record without a
signing key. These are test-only outputs from an isolated validation checkout;
the release command rejects their push-triggered run and artifact names.
No release tag was created on the remote or moved, and the accepted signed
1.4.2 files remain unchanged.

| CI validation artifact | ZIP size | ZIP SHA-256 |
| --- | --- | --- |
| `client-validation-windows-x86_64` | `154563937` | `c9907179f8569e60263011ff255cb1a1266d97ef9accc00d510ed4ea042fc5ab` |
| `client-validation-macos-x86_64` | `126558834` | `7b56cb7f5b4bd80071f1004ca34976c48f42b40e978631e80ab10cd41a665558` |

Read-only operator inspection also confirmed both environments still have schema-1
Windows 1.3.0/Mac 1.3.1 channels and no new target channels. Their legacy pointer,
manifest, and plugin-pointer hashes match. Staging runs `fedd236` image digests;
production runs `0ec65f2`. The deployment inventory enumerates only legacy target
names, an exposed client-contract gap to address during the one-time transition.
No API/website deployment or artifact activation occurred.

Windows 1.4.2 passed the existing command's local publication review against the
explicit staging destination. Its preserved files have been copied and verified
in the new paired input layout. The new ignored operator configuration is ready;
the signing key was not opened. Mac input and real paired adoption/review remain
pending the owner's private transfer, followed by the coordinated staging
transition. A private empty inbox was prepared outside the public resource tree.

The owner subsequently transferred all four Mac release files to that inbox.
Remote and local verification matched the accepted inventory digest
`677c6cc99eccacf8956010cc1758ea71e37fb14d9d4848f841731284ec2311ae` and the
126,446,802-byte DMG digest
`b3a25c5b6f1f0611acefb41fa29187883064eb1abff4b40b7526e93d4a07e7b5`.
The new command adopted both installers unchanged into the private
`scratch/desktop-releases/1.4.2/desktop-release.json` layout. Paired `status` and
staging publication review passed with an empty publication record. No signing
key was opened and no remote channel was activated. This completes R4's real
adoption/review acceptance; the one-time API/website staging transition remains.

The deployment interface fix records both explicit targets alongside legacy
channels and accepts the reviewed paired record for staging only. It verifies
all candidate bytes, retains plugin/legacy parity, and binds later phases to the
preflight inventories. All **50 deployment-tool tests passed**, including nine
candidate tests covering unreviewed targets, modified files, changed identity or
pointers, unsafe inventory names, and drift after preflight. Both real accepted
installers also passed that verifier in a private local transition layout.

### Client 1.4.2 staging transition: September 26, 2026

The simplified workflow is accepted through real staging publication. The
transition implementation is commit `919a1ad5690f462c038d31b06388db400cc35ae7`
on `fix/client-release-staging-transition`; its parent includes the CI packaging
workflow. The trusted local builder produced and pushed these immutable server
images once:

| Service | GHCR image digest |
| --- | --- |
| Backend | `ghcr.io/tbrownhe/parsetrail-backend@sha256:4937901aba6295af774ac5328ea42d04f76a993c5e822ece68462aecbb668b7c` |
| Dashboard | `ghcr.io/tbrownhe/parsetrail-frontend@sha256:01b8d6ad4d633adfb771fce20858f6daa4e6d63ecf4d189be34cf65a273dafe1` |
| Website | `ghcr.io/tbrownhe/parsetrail-website@sha256:69a091ec50c817c2ede2574949abcf1dff7d80ae362eff3f8caa94f7400ad120` |

The descriptor is retained privately on the builder and at
`/srv/parsetrail-staging/release-input/release-919a1ad-client-transition.json`.
An isolated clean checkout under staging was used; the production checkout was
not changed. The accepted client pair still comes from tag `client-v1.4.2`,
commit `4585f4c57d20101c1c6ac4f625b726e51913e562`, with the same installer,
manifest/signature and inventory bytes recorded above.

The first restore attempt stopped before mutation because the running staging
backend used `:local`, not its recorded immutable image. Read-only comparison
found all 84 application/script/project/lock files identical to the recorded
`fedd236` source. Only that staging backend was reconciled to the recorded
digest, without migration; its old local image remains available and the finding
is recorded in staging's private `client-1.4.2-baseline-reconciliation.json`.
Production's actual running images already matched its release record.

A fresh staging whole-boundary backup/restore drill then passed with IDs
`staging-pg17-restore-20260927T032000Z`,
`staging-files-restore-20260927T032000Z`, and
`staging-keys-restore-20260927T032000Z`. Database, resource-file and submission-key
comparisons passed; the staging backend resumed healthy. Restore evidence is at
`/srv/parsetrail-staging/restore-drill/client-1.4.2-20260927T031931Z/restore-evidence.json`;
the deployment backup evidence was verified at `2026-09-27T03:20:11.468466Z`.

Both accepted installers were uploaded and verified in the new staging channels,
preserving the legacy channels. The explicit paired candidate reference passed
deployment preflight. These records all passed **eight public smoke checks**:

- Initial deployment: `20260927T032123Z-919a1ad5690f`.
- Rollback to the previous API/website: `rollback-20260927T032444Z-fedd236fb82a`.
- Redeployment of the same new images: `20260927T032510Z-919a1ad5690f`.

The schema revision remained `3b7a1f4c2d91`. Health, dashboard, website, login,
authenticated plugin catalog/range, client catalog/range, invalid contribution
rejection without a write, and oversized-request rejection without a write all
passed. The paired desktop release record now marks both staging targets
`verified`; independent read-only checks after redeployment again matched each
public manifest/signature and installer range to the accepted local files.

A headless browser exercised the actual staging download page before and after
rollback/redeployment. Both labeled buttons selected the correct 1.4.2 target and
returned HTTP 206 for a one-byte installer range. For each legacy `win64` and
`macos` target, manifest, signature, and latest-installer routes returned HTTP 410
with the manual-upgrade URL. There were no page JavaScript errors. The private
local result is `scratch/client-1.4.2-staging-browser.json`.

Final inventory comparison confirmed the production inventory and all legacy and
plugin inventories remained unchanged. Production still runs `0ec65f2`; no new
production channel was activated. A local-only paired production publication
review passed. Public promotion still needs owner approval, fresh production
restore evidence, and the normal deployment gates. Reuse the exact server
digests and accepted installers above; do not rebuild either pair.

### Client 1.4.2 production release: September 26, 2026

The owner explicitly approved production promotion subject to fresh backup
verification and merged the release-workflow/staging-transition branch into
`main` at `5ad8475`. Production uses the **exact three image digests** accepted
on staging above, from source `919a1ad5690f462c038d31b06388db400cc35ae7`.
The merged backend, dashboard, website, and Compose sources match that build.
The original client tag `client-v1.4.2` was pushed unchanged at
`4585f4c57d20101c1c6ac4f625b726e51913e562`; neither installer was rebuilt or
re-signed.

The existing encrypted production backup and its automatic restore drill had
also succeeded on September 27 UTC at approximately 02:00/02:06. A separate
consistent pre-release snapshot briefly quiesced the production backend and
resumed it healthy before testing restoration. All **seven database tables**
matched restored row counts, **78 resource files** matched their inventory, and
all **five submission-key files** matched after restoration into isolated,
memory-backed disposable containers. Environment, release state/inputs, and
recovery credentials were retained privately on the server. No production data
or keys were transferred to the workstation or committed. Disposable restore
containers were removed after verification.

Fresh restore evidence was verified at `2026-09-27T04:01:00.527144Z`:

- Details: `/srv/parsetrail-production/restore-drill/client-1.4.2-20260927T040022Z/restore-evidence.json`.
- Deployment gate: `/srv/parsetrail-production/release-input/client-1.4.2-backup-evidence.json`.
- Restore IDs: `production-pg17-restore-20260927T040022Z`,
  `production-files-restore-20260927T040022Z`, and
  `production-keys-restore-20260927T040022Z`.

Production preflight, migration, health and all **eight public smoke checks**
passed under deployment **`20260927T040207Z-919a1ad5690f`**. The schema remained
`3b7a1f4c2d91`. The previous immutable `0ec65f2` API/website release remains the
recorded rollback target. Legacy client channels and plugin inventories were
unchanged; staging and production again have exact signed-artifact parity.

The paired publication command verified both production manifests/signatures,
complete remote release-file hashes, and public installer ranges, then recorded
both targets as `verified`. The final record is retained locally under
`scratch/desktop-releases/1.4.2/desktop-release.json` and privately on the server
as `release-input/client-v1.4.2-publication-record.json`. Public downloads are:

- [Windows x64 1.4.2](https://api.parsetrail.com/api/v1/clients/windows-x86_64/1.4.2).
- [Intel Mac 1.4.2](https://api.parsetrail.com/api/v1/clients/macos-x86_64/1.4.2).

A real headless browser verified both labeled links on the public download page,
correct 1.4.2 target URLs, and HTTP 206 one-byte installer ranges. All six legacy
manifest/signature/latest routes returned HTTP 410 with the manual-upgrade URL.
The additional zero-console-error assertion **failed** on a pre-existing theme
race: the version-driven head script can execute `main.js?v=1.0.1` before jQuery.
That loader is identical in the previous and released website source. The normal
bottom-of-page theme load still initializes correctly and both download links
work. This non-blocking website cleanup is tracked as W1; the approved release
images were not changed to hide or fix it. The private browser evidence is
`scratch/client-1.4.2-production-browser.json`.

Windows x64 and Intel macOS 1.4.2 publication is complete. Users on 1.3 require
one manual installer upgrade from the public download page. Apple Silicon and
the existing physical-no-build-tools Intel acceptance gap remain deferred.

### Hosted client gates and backend test annotations

The owner opened [PR #38](https://github.com/tbrownhe/ParseTrail/pull/38) from
`release/client-1.4.1`. At commit `198339c0cb62c307fd5e52622bfb2aa1921e6c63`, both
the [Windows x64 job](https://github.com/tbrownhe/ParseTrail/actions/runs/35556261970/job/106200377581)
and [Intel macOS x86_64 job](https://github.com/tbrownhe/ParseTrail/actions/runs/35556261970/job/106200377568)
completed successfully. These jobs include native interpreter/target assertions
and the source suite; this closes **R3b hosted architecture acceptance**. Backend,
frontend, Python lint/format, deployment-tooling tests, and Compose validation
also passed. Intentionally skipped workflow jobs are not claimed as executed.

The backend type job found four client-installer API tests missing parameter and
return annotations. Commit `bef7b10af601173fbcfc0482455654170b5dbeed` adds the existing
fixture types (`TestClient`, `Path`, `pytest.MonkeyPatch`), string parameter types,
and `None` returns. Local strict mypy passed all **61 backend files**, and Ruff
lint/format passed. The [hosted backend-types rerun](https://github.com/tbrownhe/ParseTrail/actions/runs/35570356972/job/106240515742)
and Python lint job also passed. Other jobs on that rerun were still running at
this checkpoint; their earlier successful client results apply to unchanged
client source. This test-only correction does not change the pinned 1.4.1 build
source, local tag, or preserved candidate bytes.

## Staging migration and recovery: August 2026

The PostgreSQL 12-to-17 rehearsal preserved the source volume and matched every
public-table count in a new isolated volume. Initial restore target
`parsetrail_app-db-data-pg17-staging-20260829T1927Z` exposed a mount-depth mismatch
when started through Compose. The helper and regression contract were corrected,
then the checksum-verified dump was restored with count parity into
`parsetrail_app-db-data-pg17-staging-20260830T065841Z` under the authoritative
`PGDATA` mount. Fourteen copied submission rows were removed after preserving the
restore evidence.

Owner testing demonstrated that changing staging `SECRET_KEY` invalidates tokens
but does not disable copied production password hashes. The guarded sanitizer
therefore preserves audit UUIDs while anonymizing/disabling copied users,
invalidating hashes/token generations, and removing copied submissions before
application traffic. This requirement is now in the staging runbook.

The isolated staging stack reached Alembic `3b7a1f4c2d91` at `fedd236` image
digests and passed all seven authenticated proxy checks. The owner completed
signup, captured-email verification, explicit sign-out/login, plugin download,
statement contribution, memory-only admin retrieval/parsing, and password recovery
using Mailpit. Staging mail had no relay or SMTP host port, no Mailpit egress,
a constrained loopback UI proxy, and a staging-domain recipient allowlist.

The independent restore drill matched public-table counts, resource contents and
modes, and submission-key hashes across:

- `staging-pg17-restore-20260830T204123Z`;
- `staging-files-restore-20260830T204123Z`;
- `staging-keys-restore-20260830T204123Z`.

The `580b4cc` deployment record `20260830T204303Z-580b4cc2aad7` passed its smoke
gate. Rollback record `rollback-20260830T204722Z-fedd236fb82a` restored the prior
images and passed all seven checks. The full recovery rehearsal required the
real migration command to reject `restore_drill_missing_revision`, activated
`fedd236` against the independently restored database/resources/keys, matched
table counts, and passed all seven checks. It then restored the untouched normal
staging mounts and passed again. Evidence was preserved under
`recovery-rehearsal/20260830Towner-acceptance`.

### Staging secret incident closure

A recovery-helper logging defect exposed staging container environment values
in the 2026-08-30 operator transcript. Staging JWT, PostgreSQL, and smoke-account
credentials were rotated immediately and verified; production secrets were not
exposed. The master key was initially retained to avoid stranding ciphertext.

After the owner authorized abandonment of staging submissions, the guarded reset
found zero rows and zero files, rotated `MASTER_KEY`, restored the recorded
immutable release, and passed all seven smoke checks. Obsolete restore/recovery
volumes, retired-key backups, bulky archives, and stale evidence were removed
after preserving nonsecret acceptance records under
`release-state/acceptance/20260830`. Historical restore target names above do not
imply that those disposable targets still exist. New deployments require new
restore evidence; the closed incident is not a standing credential-rotation task.

## Production hardening and backup acceptance: September 2026

- The application deployment initially retained PostgreSQL 12.22 and its original
  volume, migrated to `39e1c1c2a803`, and activated the signed client/plugin
  releases. Owner acceptance covered login, a fresh plugin store, multiple
  statement contributions, encrypted devtool retrieval, and parsing. The stale
  bootstrap password was rotated; release smoke uses a dedicated account.
- Production then moved by logical dump/restore to **PostgreSQL 17.11** on
  **`parsetrail_app-db-data-pg17`**. The newer server never opened the PostgreSQL
  12 data directory. The release dump recorded on **2026-09-06** was
  checksum-verified and restored in a disposable, network-isolated PostgreSQL 17
  container with all seven user tables and table-data sections present.
- The dedicated production smoke credential at
  `/srv/parsetrail-production/secrets/smoke.json` was mode `0600` and independently
  verified through the frontend. The guarded `0ec65f2` production release and
  post-certificate-cutover rerun passed all eight public checks without bootstrap
  credentials.
- Public production hostnames passed through Cloudflare Full (strict), including
  authenticated artifacts and bounded statement submission. A disposable DNS-01
  proof preceded migration of all eight production/staging ParseTrail certificates
  into the private Cloudflare ACME store. The proof and five obsolete DuckDNS
  certificates were removed. Turing's certificate remained in its separate
  HTTP-01 store; public staging apex/wildcard A records were removed after LAN
  HTTPS and DNS-01 renewal verification.
- The Docker-aware origin firewall and repeated five-minute repair cycles passed
  on `eno2`. Production passed all eight public checks and staging remained
  healthy over the LAN. From a Mac on a phone hotspot, a direct connection pinned
  to the historical origin timed out after seven seconds while the normal
  Cloudflare route was healthy. Rollback removes only the component-owned chains.
- `silicide`'s LAN address **`192.168.1.89`** was reserved in DHCP; staging smoke
  and owner-machine hosts entries agreed and all seven staging checks passed
  without command-line overrides.
- The unused host Postfix listener was restricted to `127.0.0.1:25` and
  `[::1]:25`. `postfix check` and restart passed; restart also refreshed the stale
  chroot resolver copy and the files matched afterward.
- The sibling infrastructure backup script gained pipeline failure propagation,
  encrypted-device cleanup traps, and passphrase handling outside process
  arguments. The **2026-09-05 scheduled encrypted USB backup** and automatic
  restore drill verified checksums, memory-backed decryption, file/mode
  boundaries, all five submission-key files, and all seven user tables in an
  isolated PostgreSQL 17 restore without changing live state.

Server P0 is accepted. Deployment remains manual and non-deploying CI retains no
production credentials. The non-root backend ownership migration remains a
separate unfinished item; these records do not claim it was performed.

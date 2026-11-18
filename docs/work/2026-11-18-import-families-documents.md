# Statement-family import refinements and Documents table

Date: 2026-11-18. Roadmap IDs: V2-3/4/5/UX. Components: client evidence/core/desktop.
Authorization: owner requested investigation and implementation for VAN401k, CITIAA,
CITISIMP and FIDHSA review warnings, a sortable/filterable Documents table, and
first-use multiple-file OCCU checking/savings import failure.
Implementation: completed within the finite source-role policy; older ambiguous
Citi layouts retain manual preview as detailed below.
Automated verification: core/parser/native boundary checks passed.
Design verification: pre-implementation journey review and actual native rechecks passed.
Independent review: integrity and qualified fresh agent task completed.
Owner acceptance: pending for this pass; owner accepted prior automatic statement-value
recording separately.
Release authorization: not requested.

## Scope and controlling decisions

Investigate the source dispositions behind the reported warnings, classify only
evidenced finite harmless shapes, and preserve material unexplained money/date,
unknowns, capture qualifications and exact original evidence. Missing transaction
dates alone are not assumed to explain Citi warnings. Preserve posted/transaction
date meaning and never fabricate activity to make balances agree.

Vanguard period summaries should use the existing nonposting value journey where
their source shape qualifies, consistent with Fidelity. Confirm the Fidelity HSA
source shape before deciding its appropriate summary routing. Existing guarded
automatic source-value recording may apply to newly admitted finite summary shapes;
no cash, payroll, security/cost-basis or journal-policy expansion is included.

Documents becomes a real Qt model/proxy table with Account(s), Institution, Period,
Type and Review columns, typed sorting, global Find and compact column/date filters.
No original filename is invented. Source digest identifies selection; sorting,
filtering, refresh, draft protection, report return and next-review context must stay
coherent. Unknown dates remain qualified, multiple accounts remain separate and empty/
loading/error states give a clear next action. Rare technical details remain tucked
away. Verify 1050x700, 1100x650 and 1280x800 actual Qt layouts and keyboard paths.

Reproduce OCCU first-run multiple-file import through the actual batch/dialog flow.
Checking 2215 and savings 7634 remain distinct account groups and bindings. Preserve
atomic creation/assignment/import, authentic prepared evidence, profile/catalog/source
freshness, retry and cancellation; no financial movement is created by assignment.

Ownership: primary owns integration/contracts/planning, finite summary-family admission
and this record; evidence owns parser/disposition policy and synthetic source checks;
ledger owns OCCU import investigation plus its account-review dialog if needed;
desktop owns Documents table/window integration and GUI tests; UI/UX owns interaction
review and independent integrity/acceptance review follows material changes. One writer
per file; specialists do not commit, recursively delegate or revert each other's work.

Allowed data: public synthetic fixtures and newly disposable profiles. Owner-requested
original PDF filename families in the previously identified statement folder may be
read-only inputs for focused diagnosis/replay, with private bytes/text kept in process
and only aggregate/redacted findings recorded. Never inspect existing owner trial
profiles, archives, screenshots or logs; no private fixture, original copy or source
content enters Git/routine logs. No root .env, service/production/signing/publication
or daily-profile activation is included.

## Result and review

Baseline: d74171a. The OCCU failure is reproduced with a balance-only savings
section. Account-origin locking required an activity-row binding, so the first
atomic import rolled back and the next file appeared to forget both new accounts.
The write guard now also accepts an authenticated saved PDF section association.
Unrelated accounts, nonexistent section identities and non-PDF sources remain
refused. The owner's six selected shapes have zero savings activity in files
1/2/4/5/6 and activity in file 3; public invented fixtures reproduce that pattern.
All 113 permitted OCCU originals parsed in memory without failures. No originals
or private extracted evidence were persisted by investigation.

Vanguard and Fidelity HSA account-total period summaries join the existing finite
statement-value journey and default-off future-import recording preference. The
dated source closing remains independent of journals, cash, payroll, transfers,
budget spending and opening-based account position. HSA cash-activity statements
remain outside this summary family. HSA account context masks full identifiers;
wording describes statement accounts rather than retirement-only plans.

Documents now has a real model/proxy table with five columns, typed sorting,
Find and compact facets/date filters. Source identity preserves selections and
drafts; dirty filtering can be cancelled, filtered report/next-review handoffs
reveal their target explicitly, and complete View actions remain neutral.

Independent integrity review found unexpected money/date text could escape review
in Vanguard row tails, HSA footnotes and a Citi legal-text span. Those finite rules
were tightened with public counterexample regressions. Chart outer ticks must also
have a proven source role; arbitrary labelled money/date text cannot establish one.
The original Fidelity plan-label envelope and row identity versions remain pinned
while changed engines record new policy versions. An attempted
equal-balance empty-Citi warning exception was withdrawn: equal endpoints and an
empty parsed table do not prove absence of uncaptured activity.

Remaining older Citi source-role limits are concrete: some decoded layouts detach
currency values from their printed labels or interleave incomplete legal prose with
other columns. A nearby disclosure heading alone cannot establish what an amount
means. Unlabelled values and unexplained parallel-column text retain review warnings;
missing transaction dates are not their cause. Finite complete labelled clauses and
proven repayment-example equations may be informational. The empty-source warning
also remains conservative without a printed no-activity declaration. There is no
blanket waiver merely because extracted activity balances agree.

## Verification

Completed checks so far (all successful runs raw exit 0):

- OCCU core/import/nonposting: 36 passed; four native dialog/window scenarios
  include manual/automatic batch account reuse, rollback/cancellation/retry and
  retained locks on reload. No source movement, fabricated full numbers or journals.
- Documents/browser: 14 passed; corrected existing profile/accountless/workspace
  assertions: 34 passed; core journey/initial advance: 11 passed.
- Documents native Windows at 1050x700, 1100x650 and 1280x800: three passed.
  Keyboard sorting/Tab traversal, filters, hidden targets and completion cues checked.
  Final screenshots: `scratch/documents-table-ui-20261118-final`.
- Summary family core/signed-catalog integrations: seven passed. Exact Vanguard/HSA
  source values, strict whole-account scope, withdrawal/reopened completion, retained
  evidence, no journals/Transfers and zero PDF decoding after confirmation verified.
- Combined native HSA/summary/automation GUI sequence: 17 passed, normal GC and
  explicit GUI-thread destruction. Three prior assertions expecting Fidelity-only
  help text were updated for retirement/HSA scope; the complete sequence then passed.
  Screenshots: `scratch/hsa-summary-ui-20261118-final`. Root inspected actual HSA
  bridge, masked account, visible closing/date and one blue Record action.
- Summary/source-value/automatic-recording/prepared-import core and integration
  boundary: 76 passed, 201.07 seconds. Existing future-only consent, withdrawal,
  conflicts, cancellation/atomicity, saved retries and immutable prepared evidence
  regressions remain active.
- Full native Qt journey subprocess wrapper: four passed, 23.90 seconds, every
  child raw exit 0. Empty import, spending review, correction/report return, source
  recovery, refused-import retry and in-flight cancellation covered. Earlier two
  assertions expected only three authored categories and omitted the already-seeded
  Loan interest category; assertions now include its stable ID and full rerun passes.
- Independent UI/UX inspected six actual Windows screenshots and ran a separate
  public native multi-account/filter/sort/clear check, raw exit 0, with disposal
  invalidation. No significant visual findings remain in the inspected scope.
  Evidence: `scratch/design-recheck-20261118` plus final Documents screenshots.
- A fresh goal-only software-event attempt located the newest multi-account savings
  statement, narrowed unfinished statements, recovered from no results and opened
  the correct review. Fixture-helper reading exposed some existing test expectations,
  so this is qualified agent discovery, not uncoached human evidence. Its period
  truncation finding is fixed with a persistent qualified period label and selector
  tooltips. Nine combined Documents/HSA native checks and three long-name/window-size
  checks passed. Root and independent UI/UX inspected final screenshots and confirmed
  complete dates and working actions fit. Existing wide transaction columns can still
  scroll/elide long names. Evidence: `scratch/documents-discovery-20261118` and
  `scratch/documents-table-period-long-20261118`. Owned app exit 0; the initial harness
  process was deliberately terminated to add event control (exit 1, not an app crash).
- Final evidence/warning/preview suite: 152 passed, 10.20 seconds. Twelve permitted
  originals replayed read-only in memory; all parsed and exact financial fields/date
  roles/locations matched baseline after excluding intentional engine-bound row IDs,
  engine policy version and dispositions. Vanguard warning occurrences 5 to 0;
  Fidelity HSA tail warnings 13 to 0; CITIAA unclassified money 24 to 2 and percentage
  warning 1 to 0; CITISIMP unclassified money 31 to 9. Four older Citi samples retain
  ambiguous roles; one also retains no_activity_captured. This is representative
  replay, not all-family complete capture or owner accounting acceptance.
- Independent integrity: 173 combined checks passed, followed by 37 affected tests
  after the final chart correction and 114 legacy-Citi/warning checks after grouped
  dollar/Savings-whitespace/conditional-fee changes. Direct public counterexamples
  confirmed refusal/review of arbitrary extra amounts/dates and malformed totals.
  No remaining actionable finding within the reviewed finite scope.

Final changed-file Ruff check/format and normal commit hooks passed. The full native
journey subprocess wrapper passed all four cases again after the final period-label
change (23.44 seconds, all child/raw exits 0).
Agent Windows source-runtime checks do not establish owner, other-platform,
hardware-input/accessibility, installed or release acceptance.

## Remaining work

Retain manual preview for the stated ambiguous older Citi layouts; broader label/
column capture is outside this finite-role change. Owner testing, other platforms,
hardware/accessibility/installed validation and release authorization remain separate.

## Commits and disposable owner test

Code hunks: `074f245` OCCU source provenance; `1a18d24` finite evidence/warning roles;
`b66499e` summary family routing; `8b77e54` Documents table/Review period continuity.
Contracts/planning/this record are a separate closeout commit.

Prepared `scratch/v2-owner-fresh-20261118-c542c241` from code revision `8b77e54`,
schema 27, with 23 development-catalog definitions and 318 hash-pinned runtime files.
Only helper code was reused from an earlier candidate; no profile/data/logs were read
or copied. The development signing key was discarded. The profile contains zero
sources, financial accounts, budgets, journals, account-origin records or transfer
events; the single seeded Loan interest category is present. Existing candidates
and original statement files remain untouched.

Open `Open-workflow-test.cmd` in that folder; `START-HERE.txt` covers the six requested
outcomes, future-only settings and remaining Citi warning limits. The Windows native
startup smoke returned ready/empty/import-enabled, unchanged profile hash and raw
Qt/process exit 0. Root inspected its actual empty screen. The folder becomes private
once the owner imports statements; no further inspection is implied by this handoff.

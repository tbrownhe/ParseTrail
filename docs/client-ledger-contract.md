# Client double-entry ledger contract

Status: authorized September 27, 2026; recovery rehearsal and an isolated kernel
are implemented. The first approved shadow conversion is complete; unresolved
interpretations remain open before posting them or changing reports.
This is the implementation target, not a claim that the current database is a ledger. The
active sequence and acceptance gates are in [TODO](../TODO.md). All work remains
local and client-only on `feature/client-financial-insights`.

The initial authorized audit is complete; L1 remains open for correction of
source-parser omissions and explicit migration mappings. Source investigation
identified HealthEquity cash activity continuing after a page-one interest table,
plus extraction underscores before some continuation rows/balance labels. The
legacy parser stops early and derives its closing balance from incomplete rows.
The corrected source parser now reads the complete cash section and validates
printed running/closing balances. The private correction preview preserves all
existing transactions and identifies omitted rows. Separate differences between
consecutive printed statement balances remain unresolved; do not convert them
into automatic journal adjustments. The owner approved using corrected HSA evidence
only in the disposable shadow conversion, with remaining gaps explicit. Live
historical correction has not been applied.
The standalone [auditor](../devtools/ledger_audit/README.md)
reproduces structural checks without loading application settings or opening the
live database through a writable connection.

The [recovery tool](../devtools/recovery/README.md) has verified a database/archive
bundle and independent disposable restore. The [isolated kernel](client-ledger-kernel.md)
implements posting, evidence allocation, correction and statement-reconciliation
rules against synthetic fixtures. It does not migrate live history or drive reports.
Wells Fargo personal-loan parser changes are deferred at the owner's request;
legacy synthetic loan entries require explicit migration provenance rather than
being silently treated as observed disbursements.
The [first shadow converter and read-only review](../devtools/ledger_audit/SHADOW.md)
preserve the legacy database byte-for-byte, bind HSA corrections to the approved
preview, and leave unknown counterparts/openings unposted. Existing supported
income/expense categories are provisional, unreviewed accounting interpretations.
Legacy Verified flags are retained, not promoted to confirmed transfers or reviewed
journals. Other historical balance endpoints remain unverified until source review.

## Evidence and books

Keep three separate layers:

1. Imported evidence: statements, their declared intervals/balances, normalized
   transaction observations, and source membership. Existing IDs, hashes, money,
   dates, descriptions, and category/verification values survive migration.
   Existing normalized rows are not guaranteed to be verbatim bank records:
   parser-computed balances and historical edits may lack separate provenance.
2. Accounting interpretation: ledger accounts, economic-event groups, journal
   entries, postings, evidence allocations, and review/correction history.
3. Derived views: spending, account cash movement, net worth, coverage, and
   forecasts. Forecasts, hypothetical valuations, and ML suggestions never enter
   posted historical books merely because they were calculated.

Many statement memberships can support one existing transaction observation.
Many observations can support one economic event (such as two banks reporting a
transfer). One observation can support multiple accounting allocations (such as
principal plus interest). Importing evidence twice must not book an event twice.

## Account and journal invariants

- Ledger account classes are Asset, Liability, Equity, Income, and Expense.
  Existing financial accounts map to ledger accounts through explicit identity
  mappings. Existing category names may map to income/expense accounts; a Transfer
  category does not become an expense account or establish a destination.
- Represent postings with exact signed amounts: debit positive, credit negative.
  Assets/expenses normally have debit balances; liabilities/equity/income normally
  have credit balances. UI display conventions do not alter stored signs.
  Verify legacy financial-account sign conventions in migration; do not infer
  them solely from whether an observed balance is positive or negative.
- Every posted journal entry has at least two nonzero postings and debits equal
  credits exactly. Accounts exist and accept the relevant denomination. All
  postings, evidence allocations, state changes, and idempotency records commit
  atomically. Invalid/incomplete entries can be drafts, never posted entries.
- Exact single-currency entries are the first kernel scope. Amount storage uses
  currency precision, not binary floats. Different currencies cannot cancel
  numerically; cross-currency posting stays blocked until explicit quantities,
  valuations, exchange rates, rounding, and FX clearing rules are implemented.
  Account/commodity identity must allow a later exact-quantity securities model;
  cash transfers alone do not model investment performance or cost basis.
- Evidence allocations exactly account for each finalized observation, preserving
  its sign, denomination, and financial account effect. No observed amount may
  be consumed twice in active interpretations. Supporting duplicate statement
  memberships are references, not extra money. Partial allocations stay visible.
- A source-independent manual entry requires explicit origin and review. Never
  fabricate an imported counterpart or source statement to make an entry balance.

## Dates, transfers, and incomplete evidence

For initial statement-derived books use the financial account's observed posting
date, retaining original transaction dates separately. Effective accounting date,
source posting date, creation time, and reconciliation cutoff are distinct fields.
Source-specific opening/closing balance timing must be established before using
a statement as an opening anchor.

A same-day confirmed card payment debits the card liability and credits checking.
The two source observations support that entry without duplicating the payment.
For different posting dates, use two dated balanced entries in a shared economic
event: checking to transfer clearing, then clearing to the card. Clearing retains
the amount in transit at intermediate cutoffs. No forced common posting date.
Transfers within owned assets and card repayments create no second expense.

Matching equal and opposite amounts in the same currency on different accounts
within a date window produces candidates only. Category labels and legacy
Verified flags are supporting evidence, not confirmed links. Resolve multiple
matches, duplicates, fees, partial settlements, and multiple-leg transfers before
posting. A match never overwrites imported dates or amounts.

Unknown purpose can remain a draft; where representing a known account movement
requires a posted entry, use an explicitly identified suspense account with an
unresolved review state. Approved migration policy must specify its account class
and presentation. Suspense must not disappear from reports, stand in for income
or expense without qualification, or mark history reconciled/classified by fiat.
Do not infer whether a missing counterpart is an owned account, an external
payment, or a missing import merely from a Transfer label.

Opening positions use an evidenced, dated opening-equity entry. An opening card
debt is not current-period spending, and an initial checking balance is not
income. A later unexplained balance difference is a reconciliation exception,
not another opening balance or an automatic plug to equity. Gaps in coverage
remain gaps even when observed endpoints balance.

The owner confirmed that the audited legacy manual account-closure entries were
bookkeeping instructions to zero closed accounts, not actual money movements.
Preserve these rows and that review decision, but classify them as legacy control
evidence excluded from cash-posting allocation. Their intent maps to account
lifecycle/tracking metadata. The recorded date is not proof of a bank settlement
date. Closing/stopping tracking must not zero a ledger balance or manufacture an
expense, payment, or equity adjustment. Any residual historical balance without
settlement evidence remains an explicit reconciliation exception; a closed status
must not make incomplete net-worth or liquidity figures look fully reconciled.
Other manual entries require their own interpretation and are not covered by
this confirmation.

## Splits and reversals

| Evidence/event | Debit | Credit |
| --- | --- | --- |
| Card grocery purchase 100 | Grocery expense 100 | Card liability 100 |
| Card repayment 100 | Card liability 100 | Checking 100 |
| Loan payment 500 with evidenced breakdown | Loan liability 400; interest expense 100 | Checking 500 |
| Savings contribution 300 | Savings 300 | Checking 300 |
| Grocery refund 20 to a card | Card liability 20 | Grocery expense 20 |

Split totals equal the source amount exactly. Interest, fees, and principal must
come from evidence or an explicit reviewed allocation, not an estimated schedule
silently substituted for actual history. Avoid recognizing interest twice if the
loan register already has a separate interest charge. Loan proceeds reduce no
expense and are not salary. Personal consumption, asset purchases, reimbursements,
and external payments require their actual interpretation; payment rails such as
ACH or peer-to-peer transfers do not determine it.

Drafts can change. Posted entries retain an audit trail through explicit reversal
and replacement entries linked to the original, including reason and provenance.
Changing a category's name/type must not rewrite historical postings. Prevent
reusing evidence between an original and its active replacement. Reconciliation
must be invalidated or reopened explicitly when a correction changes its result.

## Review, reconciliation, and report contracts

Track independently: balanced/posted state, interpretation review, evidence
allocation completeness, statement reconciliation, and coverage/freshness. A
legacy Verified flag supplies only the historical category-review assertion.

Reconcile account-level ledger movements against statement membership and opening
and closing balances. Retain unresolved differences with evidence and exact
amounts. Enforce consistent account/currency ownership on statement links. Treat
overlapping exports as repeated observations, not additive activity. Persist a
reconciliation's cutoff and the versions of the entries it validated.

Expense/income accounts support spending reports; selected financial-account
postings support cash movement. Net worth derives from assets and liabilities,
with unresolved/valuation limits visible. Account selection does not transform
an internal transfer into income or personal spending. Contributions can be
shown separately in liquidity views. Incomplete classifications, scope, currencies,
coverage, and stale inputs must remain visible. CF1 supplies statement coverage;
it cannot establish accounting correctness by itself.

## Migration and rollout

### Verified expense categories during a fresh rebuild

The owner approved a breaking database rebuild through local statement
archive replay to simplify legacy conversion. Preservation of verified expense
categorization is required for that path; the original database/archive remain
retained throughout. Fresh parsing must not erase the owner's completed review work.

Carry category definitions and hierarchy through an explicit identity mapping.
On an unambiguous canonical transaction match, restore both the expense category
and its category-level verified assertion, recording the legacy decision and match
evidence. The user should not have to reconfirm that category merely because the
transaction was reparsed. Ledger interpretation, transfer confirmation and statement
reconciliation remain separate assertions; preserving category verification cannot
silently certify them. Automatic categorization must not replace restored verified
decisions.

Match using established account identity, source-file/statement membership and
exact transaction evidence. Dates and amounts alone are insufficient; positional
row IDs can shift after parser fixes. Repeated/overlapping statements must converge
on one canonical transaction. Changed descriptions, duplicate indistinguishable
rows, split/merged parser output and other ambiguous matches require explicit
review; fuzzy matching may suggest candidates but may not restore a verified flag.
Manual-only records and verified expenses with no reimported counterpart remain
visible exceptions, with their old annotations intact in retained evidence.

Before cutover, the carry-forward report must account for every legacy verified
expense as restored or pending with a reason. Check counts and exact amounts by
account/category, preserve refunds, reject conflicting annotations and prove rerun
idempotency. A partial transfer of annotations must never be reported as complete.

The first [fresh-replay checkpoint](../devtools/ledger_audit/REBUILD.md) implements
source evidence and category preservation in a disposable new format. Historical
rows commonly lack a transaction date; exact posting date remains required, and
known transaction dates must agree. No journal is posted by annotation restoration.
Parser failures and ambiguous matches remain visible cutover blockers.

The second checkpoint permits a running balance to distinguish repeated exact
transaction details only when the complete, unique balance inventory is unchanged
in every contributing source group. Changed/added/removed or indistinguishable
evidence still requires review. Confirmed manual asset-value observations retain
their original category verification as history, separately from cash evidence or
expense postings. Rounded asset values must not create balancing adjustments to
purchase funding. Category accounting includes these retained observations explicitly.

### Existing staged rollout

1. L1 audits a consistent read-only snapshot. Inventory schema, exact amounts,
   category review, source links, balance equations, coverage, and candidate
   transfers. Preserve private diagnostics locally. Resolve material exceptions
   with the owner; do not reinterpret actual history automatically.
2. L2 proves complete backup and disposable restore, including referenced archive
   coverage. A SQLite snapshot alone is not the complete backup gate.
3. L3 implements and tests the kernel on synthetic data before any migration.
4. L4 builds shadow books beside retained legacy data. A deterministic conversion
   manifest records source identity, rule versions, mappings, unresolved cases,
   and output identities. Repeated runs/imports create no duplicate postings.
5. L5 provides review/reconciliation UI and Windows acceptance before report
   cutover. Preserve old reports during comparison; explain intentional differences.

Kernel tests must cover atomic rollback, imbalance rejection, exact splits,
duplicate evidence/imports, correction history, month-crossing transfers, partial
settlements, fees, unknown counterparts, currency rejection, opening equity, and
statement reconciliation with overlapping/missing history. Source/restore bytes
and semantic contents must be checked in recovery rehearsals. Routine development
must never migrate the live database in place.

References informing the design: [GnuCash entry concepts](https://www.gnucash.org/docs/v5/C/gnucash-guide/basics-entry1.html),
[accounts](https://www.gnucash.org/docs/v5/C/gnucash-guide/chapter_accts.html),
[opening balances](https://www.gnucash.org/docs/v5/C/gnucash-guide/cbook-accounts1.html),
and [Actual's transfer/date treatment](https://actualbudget.org/docs/transactions/transfers/).
The migration and provenance rules above are ParseTrail design decisions.

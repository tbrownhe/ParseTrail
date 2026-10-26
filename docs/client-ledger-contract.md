# Client double-entry ledger contract

This is the accounting contract for the fresh V2 profile. It preserves the
owner's September 27 ledger decision and October 13 clean-profile decision.
The rules include accounting targets beyond the currently admitted workflows;
a rule or example does not by itself select or implement a feature.

The [roadmap](../ROADMAP.md) owns scope, sequence and release gates;
[TODO](../TODO.md) identifies selected work. The [cutover contract](client-v2-cutover.md)
and [single-store contract](client-v2-unified-store.md) define runtime/profile
boundaries. Work, commands, review and acceptance evidence belong in
[packet records](work/README.md). The
[archived contract](work/archive/2026-10-25-client-ledger-contract.md) retains
superseded migration/audit narrative and its historical evidence links.

The current workspace supports narrow reviewed asset cash expense/income,
negative card purchases, whole-movement owned transfers/card payments and printed
openings. Cash-category, card-category/date and source-backed opening corrections
are available. Supported ordinary interpretations can be withdrawn, then freshly
reviewed; posted-repeat repair retains one interpretation and retires its
redundant counterpart atomically. Whole transfers can be withdrawn or atomically
replaced while retaining every dated leg and allocation history. General refunds,
splits, loans, manual entries, suspense and valuations require their own admitted
workflows; examples below specify financial meaning rather than availability.

## Evidence and books

Keep three separate layers:

1. Imported evidence: statements, their declared intervals/balances, normalized
   transaction observations, and source membership. 2.x imports retain source
   bytes, hashes, exact money, typed dates, descriptions, locations and the exact
   parser definition/engine versions. Observed, derived, assumed and unknown
   source facts keep their distinct provenance.
2. Accounting interpretation: ledger accounts, economic-event groups, journal
   entries, postings, evidence allocations, and review/correction history.
3. Derived views: spending, account cash movement, net worth, coverage, and
   forecasts. Forecasts, hypothetical valuations, and ML suggestions never enter
   posted historical books merely because they were calculated.

Many statement memberships can support one existing transaction observation.
Many observations can support one economic event (such as two banks reporting a
transfer). One observation can support multiple accounting allocations (such as
principal plus interest). Importing evidence twice must not book an event twice.
The current [occurrence-review contract](client-v2-source-overlap.md) preserves
separate imported rows while explicitly relating supporting repeats; it does
not merge immutable observations or allocate additional money.

## Account and journal invariants

- Ledger account classes are Asset, Liability, Equity, Income, and Expense.
  Imported financial accounts map to ledger accounts through explicit identity
  mappings. Category names may map to income/expense accounts; a Transfer
  category does not become an expense account or establish a destination.
- Represent postings with exact signed amounts: debit positive, credit negative.
  Assets/expenses normally have debit balances; liabilities/equity/income normally
  have credit balances. UI display conventions do not alter stored signs.
  Verify source financial-account sign conventions on import; do not infer
  them solely from whether an observed balance is positive or negative.
- Every posted journal entry has at least two nonzero postings and debits equal
  credits exactly. Accounts exist and accept the relevant denomination. All
  postings, evidence allocations, state changes, and idempotency records commit
  atomically. Invalid/incomplete entries can be drafts, never posted entries.
- The current V2 runtime admits exact USD single-currency entries. Amount storage
  uses currency precision, not binary floats. Different currencies cannot cancel
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
  The owner's October 25 DEC-1 limits manual entry to reviewed openings and dated
  values, including missing new-loan opening information and missing final
  statements on recently closed loans. Arbitrary manual journals are outside the
  initial scope. A reviewed value does not establish an unsupported settlement.

## Dates, transfers, and incomplete evidence

For initial statement-derived books prefer the financial account's printed
posting date, resolving a printed month/day against its statement period when
needed. When no posting date is printed, retain the original activity or
transaction date and mark the parser's posting candidate `assumed`. A global
choice defaults off; enabling it permits reviewed entries to use these guesses
without per-row date entry. Corrections to an accounting date use an append-only
reversal and replacement rather than changing source evidence. Effective
accounting date, source posting date, creation time, and reconciliation cutoff
remain distinct facts.
Source-specific opening/closing balance timing must be established before using
a statement as an opening anchor.

A same-day confirmed card payment debits the card liability and credits checking.
The two source observations support that entry without duplicating the payment.
For different posting dates, use two dated balanced entries in a shared economic
event: checking to transfer clearing, then clearing to the card. Clearing retains
the amount in transit at intermediate cutoffs. No forced common posting date.
Transfers within owned assets and card repayments create no second expense.

Matching equal and opposite amounts in the same currency on different accounts
within a date window produces candidates only. Category labels are supporting
evidence, not confirmed links. Resolve multiple matches, duplicates, fees,
partial settlements, and multiple-leg transfers before posting. A match never
overwrites imported dates or amounts.

Unknown purpose can remain a draft; where representing a known account movement
requires a posted entry, use an explicitly identified suspense account with an
unresolved review state. The 2.x accounting policy must specify its account class
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
Those original rows remain in the independent 1.x history; their reviewed intent
informs 2.x account lifecycle/tracking metadata, not cash-posting allocation.
The recorded date is not proof of a bank settlement date. Closing/stopping
tracking must not zero a ledger balance or manufacture an
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
Opening corrections also support exact dated retirement inverses without a
replacement when the newly reviewed opening is zero. Initial decisions and
append-only revisions retain persisted content versions; stale forms cannot
authorize a different source basis. Basis-only changes can retain a journal.
This does not authorize a later unexplained balance plug.
Built-in categories have stable semantic keys in a code-owned catalog, with fixed
names and income/expense types. User-defined categories occupy a separate identity
namespace and can extend the catalog without overriding a built-in. The first is
`builtin:loan-interest`, displayed as **Loan interest**. A loan-interest workflow
must post to that built-in; arbitrary expense recategorization is not available
for its interest component. Ordinary expense classification can select built-ins
or user categories and split across them. A matching custom display name neither
establishes built-in identity nor merges previously verified history. Any required
ledger-account creation performed during posting belongs to that atomic write;
explicit source-account binding remains a separate, non-posting decision.
Catalog reads remain read-only.

Changing a category's name/type must not rewrite historical postings. Prevent
reusing evidence between an original and its active replacement. Reconciliation
must be invalidated or reopened explicitly when a correction changes its result.

## Review, reconciliation, and report contracts

Track independently: balanced/posted state, interpretation review, evidence
allocation completeness, statement reconciliation, source capture, and
coverage/freshness. An equal balance equation does not establish full-page
capture or missing-history coverage.

Reconcile account-level ledger movements against statement membership and opening
and closing balances. Retain unresolved differences with evidence and exact
amounts. Enforce consistent account/currency ownership on statement links. Treat
overlapping exports as repeated observations, not additive activity. A
reconciliation result identifies its cutoff, deterministic rule and input
version; changing relevant entries or review assertions changes that version.
Explicit confirmation can retain a successful check's cutoff, rule, input version,
exact result and journal payload versions as append-only durable history. The
save revalidates its expected input version atomically and requires reviewed
posted interpretations. Failed or stale checks cannot be saved. Capture and
coverage qualifications remain part of the saved result, not implied acceptance.
Identical saves reuse the original record. Later profile-wide input changes
conservatively mark saved decisions stale; originals remain inspectable. Saving
history does not itself invalidate the live version. Latest saved, currently
valid saved and newly computed live cutoffs are separate report fields.
A supporting-repeat decision does not stand in for a source-row allocation.

Expense/income accounts support spending reports; selected financial-account
postings support cash movement. Net worth derives from assets and liabilities,
with unresolved/valuation limits visible. Account selection does not transform
an internal transfer into income or personal spending. Contributions can be
shown separately in liquidity views. Incomplete classifications, scope, currencies,
coverage, and stale inputs must remain visible. Statement coverage cannot
establish accounting correctness by itself. A reviewed journal sum must not be
labeled a current bank balance or complete net worth without the required
opening, source cutoff, pending-activity and coverage qualifications.

`account_positions(as_of=...)` reads current reviewed books through an inclusive
USD accounting-date cutoff in one committed SQLite read snapshot. It retains
debit signs; desktop presentation multiplies liabilities by -1 to show amounts
owed. Recorded sums and opening-based journal positions are distinct. Missing,
stale, future or conflicting opening decisions leave the position unknown;
a valid zero opening is known zero. Pending source counts cover all dates,
including supporting repeats, with unbound rows separately identified. Source
period ends/activity dates, coverage/capture warnings and live successful checks
remain separate qualifications. A live-check cutoff is computed now, independently
of saved reconciliation decisions; neither proves complete history.

Account history includes originals, reversals and replacements, restating the
books by accounting date as they stand now rather than reconstructing what was
known in the past. Same-day date/key running order does not establish intraday
source timing. Different-date transfers retain their clearing amount at interim
cutoffs. These reads do not certify a bank balance or complete net worth.

## Fresh-profile rollout

Client 2.0 creates a new ledger profile. It does not migrate or open the 1.x
database for writable initialization, restore old category verification, or
retain old identity aliases. The owner re-enters accounts, categories, budgets,
manual values and transaction decisions. Original documents chosen for 2.0
are imported as new evidence and reviewed under the accounting rules above.
The 1.4.2 database, archive and application remain separate and untouched.

The [cutover contract](client-v2-cutover.md) defines the independent fallback
and fresh-format boundary. The [roadmap](../ROADMAP.md#v2-7) records remaining
cutover and release gates. Ordinary 2.x migrations apply only between released
2.x revisions; earlier disposable pilot schemas are refused and recreated.
Historical rebuilds, shadow conversions and legacy category preservation are
read-only research evidence, not runtime migration requirements.

References informing the design: [GnuCash entry concepts](https://www.gnucash.org/docs/v5/C/gnucash-guide/basics-entry1.html),
[accounts](https://www.gnucash.org/docs/v5/C/gnucash-guide/chapter_accts.html),
[opening balances](https://www.gnucash.org/docs/v5/C/gnucash-guide/cbook-accounts1.html),
and [Actual's transfer/date treatment](https://actualbudget.org/docs/transactions/transfers/).
The accounting and provenance rules above are ParseTrail design decisions.

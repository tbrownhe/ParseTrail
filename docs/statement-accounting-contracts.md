# Retained statement accounting declarations

Parsers can declare optional `ACCOUNTING_CONTRACT` JSON metadata describing their
normalized output. This selects an existing accounting workflow; it cannot approve
a transaction, choose a bank counterpart, certify balances/dates, or run custom code.
The first supported representation is `loan-total-and-interest`, schema version 1.
Capital One Auto 0.2.2 and Wells Fargo Personal Loan 0.2.1 declare it. Their financial
extraction is unchanged.

```python
ACCOUNTING_CONTRACT = {
    "schema_version": 1,
    "representation": "loan-total-and-interest",
    "label": "Example Loan",
    "payment_description": "Payment Received",
    "interest_description": "Interest Fee",
    "association": "same-account-date-statement",
    "balance_basis": "derived-opening-principal",
    "period_basis": "printed-activity-range",
    "date_basis": "unverified",
    "excluded_descriptions": [],
    "unposted_descriptions": [],
}
```

The representation means a positive total-payment row and one nonpositive interest
row on the same loan/date, sharing a source statement. Their sum is principal
reduction. Interest is expensed once through the fixed Loan interest category.
Explicit zero interest is retained without a zero posting. Missing, multiple or
shared interest, wrong signs, interest exceeding payment, inconsistent memberships,
non-USD evidence, failed source equations and allocated movements still block posting.
The human must select and confirm the matching bank outflow.

Version one's exact description selectors identify semantic roles in existing
normalized rows; they do not classify arbitrary descriptions by fuzzy matching.
Selectors must be distinct. `excluded_descriptions` disqualifies the entire source
statement; `unposted_descriptions` documents standalone rows outside this workflow.
All rows other than selected payment/interest components remain unposted by this
workflow. Wells Fargo excludes `LOAN ORIGINATION` and leaves separate
`PRINCIPAL PAYMENT` rows unposted. Its synthetic origination behavior is unchanged.

Allowed balance bases are `derived-opening-principal` and `printed-principal`;
period bases are `printed-activity-range` and `assumed-31-days`. These describe
ordinary source evidence and supply review notices, not independent verification.
Date provenance remains `unverified`. New accounting representations or provenance
semantics need a separately implemented and tested schema/workflow; metadata cannot
silently extend the rules.

## Capture, validation and dispatch

The loader validates the optional declaration without adding it to the mandatory
string-only parser interface. Parsing takes a detached copy from the executed parser
class into `Statement.accounting_contract`. Subsequent parser/catalog changes cannot
alter that statement's copy. Known declarations reject missing/extra fields, conflicting
selectors and unsupported semantics. Future positive schema versions or unknown
representation names are retained as JSON but have no posting workflow.

Ordinary imports persist canonical JSON in `Statements.AccountingContract`.
Migration `0004_statement_accounting` adds a nullable column and leaves all old rows
NULL; it does not infer historical declarations. The existing shadow migration and
backup mechanism applies. Duplicate imports keep the already retained statement.

Fresh archive replay captures the declaration in each source statement payload and
the immutable `SourceStatements.accounting_contract` column. Column/payload agreement
is checked before loan posting. Rebuild/candidate hashes and payment previews bind
the entire declaration, including provenance and selectors. Source parser/version
and declaration must agree across overlapping memberships; mixed versions/contracts
remain review-only. No current parser lookup occurs while reviewing retained evidence.

Both declared loan formats dispatch to `declared-loan-total-and-interest-1`, using
the same review, posting, clearing, fixed-interest and whole-event bank-match correction
services. A new parser using this supported representation needs its declaration and
source validation, not another parser-specific ledger workflow.

## Existing evidence and scope

Old disposable rebuilds without an `accounting_contract` payload key retain a frozen
compatibility adapter for Capital One 0.2.1 and Wells Fargo 0.2.0. This preserves
accepted previews, immutable decisions and correction history. The adapter never
overrides an explicit NULL, unsupported or invalid declaration. It will not be extended
for new parser versions. Old active-profile statements remain undeclared until an
explicit fresh replay; installing a parser never rewrites their meaning.

This change does not publish parser artifacts or change the server/catalog interface.
The optional declaration is authenticated as part of the existing signed parser bytes.
There are no new dependencies. Other loan representations, per-row semantic tags,
multi-account statements with different accounting representations, source-component
corrections, openings and loan reconciliation remain separate chunks. General
declarative extraction/parser cleanup was outside this implemented chunk. On
October 4 the owner included it in 2.0 under the
[parsing-engine and catalog plan](client-v2-parsing.md). The current accounting
declarations remain implemented as described above until that redesign is built.

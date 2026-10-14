# Client 2.0 clean-profile cutover plan

Planning update: October 13, 2026. The owner chose a fresh 2.0 profile and will
re-enter authored data. This supersedes the October 4 required-rebuild and
automatic preservation plan. Keep development on
`feature/client-financial-insights`; do not change the application version,
server or live financial data during these pilots.

## Release boundary

Client 2.0 uses the double-entry ledger as its only accounting model. It creates
a new 2.x database and profile. It does not open a 1.x database for writable
initialization, migrate it, import its transaction/category decisions, or retain
aliases and compatibility layers for old IDs. Unknown, corrupt and newer formats
fail before writable schema initialization. Ordinary migrations are supported
only between released 2.x schema revisions.

The existing 1.4.2 application, database, archive, exports and recovery material
remain independent and untouched. They are the reference for old history and the
fallback if 2.0 is not ready. The owner may choose original documents to import
into 2.0 and review them there from scratch. There is no promise that every
historical document must be re-imported before first use. Any comparison against
the old database is read-only development evidence, not a runtime migration
contract.

Accounts, custom categories, budgets, manual values and transaction verification
are entered afresh in 2.0. Verified categories in 1.x are not automatically
promoted. A later one-time export/import convenience feature would need its own
review and would not become a permanent compatibility path. No 2.0 report may
label missing re-imported history as zero activity or claim complete coverage.

The first 2.0 release still needs usable daily imports, explicit review and
correction, spending, cash movement, account balances, budgets and exports from
one ledger model. Unsupported evidence remains visible and unposted. Forecasts,
securities cost basis, complete loan history and new ML insights are later work.

The [ledger contract](client-ledger-contract.md) and
[parser design](client-v2-parsing.md) remain the technical boundaries. The
prior [preservation inventory](client-v2-preservation-inventory.md) is a
read-only record of the 1.x data and parser archive. It is no longer an
activation checklist or a reason to build a database updater.

## Evidence and accounting rules

- Retain original imported bytes, source digest, exact parser definition and
  engine/extractor versions, raw values and source locations in the new profile.
  A parser emits evidence, not journal postings or category verification.
- Distinguish statement coverage from CSV/XLSX activity spans. Unknown printed
  balances remain unknown. Calculated balances never overwrite printed ones.
- An imported financial movement becomes a balanced journal entry only through
  a reviewed interpretation. Expense, refund, income, transfer, card payment,
  loan components and openings have distinct rules. Do not invent a balancing
  transaction for a source gap.
- An identical source import is idempotent. Revised, overlapping or ambiguous
  sources require evidence review; they cannot silently replace prior decisions.
- Reports and exports share ledger scope rules and show pending/uncovered work.
  A card purchase contributes to spending once; repayment moves cash and
  liability without a second expense.
- Keep source evidence and 2.x decisions durable across parser/catalog updates.
  Reparse is a comparison, not an overwrite of old evidence or reviewed entries.

## Parser and decoder direction

The target remains a locally shipped finite engine with signed versioned JSON
definitions. New operations require a client release. Declarations cannot
execute Python, SQL, shell commands or arbitrary expressions. Keep only needed
built-in exceptions. The 1.4 bytecode catalog belongs to the old application;
2.0 does not need a compatibility loader for it.

The representative CSV, Chase, HealthEquity and Wells pilots match the accepted
reader on their tested archive fields. The XLSX decoder has synthetic coverage
only. Citi's recent layout combines table, text and fee channels. Across eight
hash-verified recent-layout sources, a read-only audit found 410 table and 350
text candidates: 330 exact occurrences, 11 unresolved overlaps and nine
text-only candidates. The accepted reader recovered 10 text rows and one fee;
these counts alone do not establish which unmatched candidates are new financial
activity. A page-level follow-up classified nine overlaps as incomplete text
copies containing only a date, one as a table copy missing the first character
of the text description, and one as an additional identical occurrence at a
distinct source line. The nine text-only rows comprise three payments, two
interest charges and four purchases. A finite, read-only channel resolver now
retains table/text/fee locations, accepts only those explained candidate shapes,
and reproduces all 421 accepted date/amount row occurrences and all eight printed
balance equations. It makes two explicit description corrections: the fuller
one-character text copy and a fee description with its amount removed.

These particular overlap conflicts do not show a foreign-transaction multiline
pattern. A separate dated-line scan found 71 lines outside the simple text-row
matcher, including foreign transactions split across lines and rows interleaved
with legal text. Their source dispositions are not yet complete. The pilot uses
the old unbounded PDF extractor, so neither row parity nor balancing authorizes
2.0 import. Complete a named, client-built Citi handler with full dated-line
dispositions and bounded decoding if this layout is admitted; do not add a
general declaration language just for this case.

All unbounded PDF decode, word extraction and table finding must run behind a
separate worker boundary with source/output size, page and row limits, a wall
clock timeout and an operating-system memory limit. Windows x64 and Intel Mac
need native limit/termination checks. Until then, the current PDF pilots are
development comparisons, not runtime import admission. The same rule applies
to XML decoding in the XLSX pilot before runtime use.

## Implementation chunks

| Order | Deliverable | Gate |
| --- | --- | --- |
| V2-1 | Freeze the fresh-profile contract and identify old-profile fallback. Keep the completed 1.x inventory for reference only. | No automatic old-DB import or aliases in the 2.x target. |
| P2-1 to P2-3 | Finish finite evidence/declaration pilots, Citi conflict handling and decoder worker limits. | Exact source provenance, explicit unresolved candidates, bounded execution and representative fixture checks. |
| V2-2 | Create an explicit 2.x format and fresh-profile lifecycle. | New empty profile opens; 1.x, unknown, corrupt and newer databases fail before writes. |
| V2-3 | Integrate a single source import path, then add supported families. | Immutable source/evidence, account mapping, idempotent retry, overlap review and cancellation recovery. |
| V2-4 | Connect account/category/budget editing and accepted ledger review/correction services to the application. | Ordinary import-to-review workflow, manual values and pending decisions survive restart; owner Windows GUI acceptance. |
| V2-5 | Replace legacy dashboard, budget and export queries with common ledger reads. | Spending/cash/balance totals agree across services, UI and exports with visible incomplete scope. |
| V2-6 | Add new-profile backup/restore and deliberate profile selection. | Independent restore, failed-switch recovery and native reopening. No old-database activation or migration assistant. |
| P2-5 / P2-S | Finish signed offline JSON catalog locally; handle server publication later on its own reviewed branch. | Tamper, rollback and offline checks; no server change during client pilots. |
| V2-7 | Remove obsolete runtime financial paths, set 2.0 version when ready, package and accept. | Relevant automated suite and owner Windows/targeted Intel Mac native walkthrough. Publication remains separately approved. |

The isolated [fresh-profile stop/go slice](../devtools/v2_fresh_slice/README.md)
exercises one synthetic CSV from parsed evidence to a disposable ledger and
explicit expense review. It proves a useful service boundary without a 1.x
database updater. It is not the application import UI, a production 2.x schema,
a signed catalog or native acceptance.

## Current stop/go decision

**Go** for fresh-profile service integration and finite parser work. The
synthetic slice keeps the source and parser evidence, leaves rows unposted,
posts one explicitly reviewed expense exactly once, and leaves a credit
pending. **No go** for 2.0 activation or release yet: the PDF/XLSX decoder
limits, complete Citi dated-line dispositions, durable evidence across engine updates,
ongoing import/recovery, common reports and native GUI acceptance remain open.

A proposed 2.0 profile is separate from 1.x. If the owner returns to 1.4.2,
it opens only the retained 1.x profile; it never reads a 2.x database. Work done
in either profile is not synchronized or backported. Do not switch the owner's
daily workflow until the exact 2.0 build and new profile pass native acceptance.

No version bump, live activation, installer build, server deployment or public
publication is authorized by this planning document.

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

Bounded table-row continuation is shared by Citi, Synchrony, LendingClub and
Wells parsers, so it belongs in the declarative engine. A shared finite pilot
now pairs exact occurrences across extraction channels while leaving financial
disposition to the caller. The Citi resolver uses it; this is not a commitment
to a permanent institution-specific subsystem. Reserve a Citi-specific
extractor for page geometry or fee-section shapes that the shared operations
cannot express clearly.

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

The recent Citi PDF layout is in scope for the 2.0 release. Its overlap conflicts
are separate from the foreign-transaction multiline pattern. A dated-line scan
found 71 lines outside the simple text-row matcher in the earlier eight-source
cohort. The [source-line ledger](../client/src/parsetrail/core/v2_citi_source_dispositions.py)
now checks the ten recent-layout archive PDFs: all 486 dated starts map one to
one to resolved rows, including 72 table copies and one fee; all ten printed
balance equations pass. This accounts for dated starts in the tested sources,
while other source regions still need the normal capture review. Keep the shared
continuation and occurrence operations finite; do not add a general declaration
language just for this case.

All unbounded PDF decode, word extraction and table finding must run behind a
separate worker boundary with source/output size, page and row limits, a wall
clock timeout and an operating-system memory limit. Windows x64 and Intel Mac
need native limit/termination checks for each admitted operation. Until then,
the current PDF pilots are development comparisons, not runtime import
admission. The same rule applies to XML decoding in the XLSX pilot before
runtime use.

The isolated simple-text PDF worker now has those limits for text extraction.
Windows native tests exercised memory refusal and deadline termination; its
output matched the existing decoder on nine recent-layout Citi archive PDFs
with unchanged source hashes. The Wells word/table pilot now uses the same
worker: 21 archive PDFs returned exactly the in-process cells and regions, with
unchanged source hashes. The Citi word/table pilot now also uses that worker
boundary: 543 raw rows matched the current extractor across ten recent-layout
archive PDFs, with unchanged hashes. Full page capture, runtime integration and
Intel Mac native checks remain open, so this does not admit PDFs to runtime imports.
The shared PDF line and continuation operations, anchored table engine, Wells
table engine and their workers now live in the client package. A windowed
Windows x64 probe passed both table worker pipes and parent resource
boundaries on synthetic evidence.
The three PDF text layouts, first-page date annotation decoder and shared
worker limit runner now live in the installed client package. The app routes a
fixed worker argument before profile or GUI bootstrap. A windowed Windows x64
probe passed both worker pipes, a positive annotation decode and native
timeout. All fixed decoder workers now live in the client package. Windowed
Windows x64 probes passed text, annotation, XLSX, anchored table, Wells table
and Citi table pipes. The client build scripts gate those worker pipes. Intel
Mac native checks remain open.
The read-only Citi audit now feeds its candidate resolver from the bounded text
and table workers. The shared continuation operation forms 471 table rows and
retains 36 post-amount travel/lodging detail rows as source evidence; no detail
line becomes a financial row. Its legacy parser remains the accepted-result
baseline.
The bounded text worker supplies metadata to classify the recent layout, while
the bounded candidate path reads the
statement period, account suffix and printed balances from capped worker
evidence. Those fields matched the old reader on all ten archive statements.
The standalone [recent Citi evidence path](../client/src/parsetrail/core/v2_citi_evidence.py)
now runs without the old reader or any profile writes. The old reader remains
only in the separate comparison audit.
It also labels every dollar-sign line outside dated transaction spans:
183 first-page payment, summary, credit-term, repayment-example and visible
text-extraction artifact lines, plus 98 later-page summaries, APR information,
notices and disclosure lines. No dollar-sign line is unresolved in the
ten-source sample. Five first-page summary lines and ten later-page cardholder
subtotals are visibly garbled by simple-text extraction; their amounts are not
used as transaction or balance evidence.
The XLSX adapter also runs in a fixed, bounded worker and matches the
in-process synthetic evidence. It has no referenced archive workbook and
still needs Intel Mac native checks before runtime admission. The shared table
engine, XLSX adapter and worker now live in the client package. A windowed
Windows x64 probe passed its synthetic worker pipe and parent resource boundary.

## Implementation chunks

| Order | Deliverable | Gate |
| --- | --- | --- |
| V2-1 | Freeze the fresh-profile contract and identify old-profile fallback. Keep the completed 1.x inventory for reference only. | No automatic old-DB import or aliases in the 2.x target. |
| P2-1 to P2-3 | Finish finite evidence/declaration pilots, shared continuation/channel rules, Citi source dispositions and decoder worker limits. | Exact source provenance, explicit unresolved candidates, bounded execution and representative fixture checks. |
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
a signed catalog or native acceptance. Its saved evidence snapshot now reopens
without reparsing, and strict format checks refuse legacy, unknown and newer
profile shapes before ledger writes in synthetic tests.
The owner approved the [released evidence storage boundary](client-v2-evidence-storage-proposal.md).
The [upstream boundary review](client-v2-upstream-boundary-review.md) identifies
the parser-output and admission changes to make before V2-2/V2-3 storage work.
Recent Citi remains in the 2.0 import contract without a 1.x database migration.
The first [fresh 2.0 SQLite source store](../client/src/parsetrail/core/v2_profile_store.py)
now saves exact source, definition, strict evidence and unposted observation IDs
atomically. A temporary profile reopened ten recent Citi PDFs with 486 rows and
803 dispositions; the originals were read-only and their hashes unchanged.
The fresh profile now also stores user-authored financial accounts and explicit
accountless-export decisions. A whole-file assertion says every row belongs to
one account; a mixed export uses row assignments. The modes cannot coexist for
one source. These editable decisions remain separate from immutable evidence
and do not post ledger entries. The isolated
[account assignment review](../client/src/parsetrail/gui/v2_account_binding_review.py)
uses the same fresh profile and shows a pending count, source rows, the asserted
account and the basis of each decision. Its
[six-row disposable demo](../devtools/parser_engine_pilot/review_accountless_export.py)
can be opened from the repository root with:

```powershell
$env:PYTHONPATH='.;client/src;client'
.\client\.venv\Scripts\python.exe -m devtools.parser_engine_pilot.review_accountless_export --demo
```

The demo writes only to a temporary 2.0 profile and deletes it on close. The
owner accepted the native Windows interaction on October 23, 2026. A separate
[2.0 workspace service](../client/src/parsetrail/core/v2_workspace.py) now
creates or opens only a marked 2.0 profile, requires a verified offline catalog,
reads a selected CSV/PDF without changing the original, and stores pending
evidence. Refused input leaves no import. The separate desktop shell described
below now connects this service. The existing 1.x main window still initializes
its own database and account/report services during startup.
The isolated [V2 source import service](../client/src/parsetrail/core/v2_source_import.py)
now checks an exact-source retry before invoking a parser and returns the saved
snapshot. Revised bytes remain a separate pending import. Parser failure and
post-parse cancellation leave the new profile unchanged. This is a service
boundary only; installed catalog admission, archive
recovery and main-window integration remain open.
The local catalog-admission pilot now validates all 23 checked-in definitions in
one test-signed snapshot. With a verified catalog, the service checks parser
identity and revision before saving pending evidence. CSV imports can select the
only matching verified definition; zero or multiple matches leave no source
write. All 21 PDF declarations now require a bounded body rule and allow header
and metadata predicates. A verified catalog decodes PDF text once for routing
in the bounded worker,
requires one route before parsing, and refuses zero, multiple or explicitly
mismatched selections before writing a source. A read-only bounded routing scan
identified one definition for all 956 PDFs in the successful archive (20 families), with no ambiguous or
missing matches; three separately sampled Synchrony PDFs covered the remaining
family. This scan checks recognition, not transaction extraction or accounting.
One read-only archived source from each of the 21 PDF families also passed the
installed source-to-evidence pipeline after routing. That spot check does not
establish full archive extraction parity or ledger interpretation.
An October 24 replay of both successful-archive folders through a locally
test-signed snapshot and the bounded source pipeline parsed all 956 PDFs
across 20 represented PDF families (20,095 evidence rows) and the one MOHELA
account-history CSV (29 rows). No source failed routing or extraction. The
archive has no Synchrony PDF; its separate ten-source pilot remains the fixture
for that family. This replay checks execution and evidence identity for the
current declarations, not full-page capture, legacy row parity, ledger
interpretation or production-signed installed-client trust. A separate queued
folder has six bank transaction-export CSVs and 21 Amazon-related CSVs that
match neither current CSV declaration; these are outside the successful-archive
replay and do not add a shipped parser family.
The same 957 distinct sources then passed the verified-catalog import service
into one disposable 2.0 profile: 957 new imports, zero retries or failures.
Each import saved and reloaded its evidence, and the complete profile reopened
read-only with 957 sources. The temporary profile was removed. This checks
cross-source storage and schema integrity, not ledger posting or accounting.
Installed-client trust remains open.

The local [catalog artifact builder](../client/scripts/v2_catalog_release.py)
validates, signs and re-verifies all 23 checked-in definitions into a new local
directory using an encrypted key kept outside the repository. The existing
plugin release key is selected for catalog signing; the release command checks
its public half against the shipped trust store. A shared
[public trust loader](../client/src/parsetrail/core/release_trust.py) lets 2.0
verify that key without importing the 1.x plugin manifest module. An actual
production-signed starter catalog, installed offline acceptance and server
publication remain open. The separate 2.0 workspace now installs a locally
selected signed release pair into its verified cache. It refuses tampering,
untrusted signatures, conflicting same-sequence releases and rollback before
changing the active pointer. The desktop offers Install signed catalog and
keeps source import unavailable when no verified release is active. Synthetic
service and offscreen UI tests pass; the owner accepted the native Windows
install interaction on October 24, 2026. An actual production-signed starter
pair and installed offline acceptance remain open.

The finite parser operations, bounded adapters and source pipeline now live in
the client package. Verified-catalog import uses that installed pipeline by
default; a synthetic signed CSV import saves and reopens its evidence without
an injected parser. The frozen runtime smoke now exercises a synthetic V2
parse and pulls the pipeline into packaging. A windowed Windows x64 probe
passed that runtime smoke and all six worker pipes after the package move.
The runtime smoke now also activates and reopens a synthetic signed catalog,
imports one CSV through the verified path, and reopens its fresh 2.0 profile.
A rebuilt windowed Windows x64 probe passed this smoke and all six worker pipes
with synthetic build metadata. This remains a local packaging check, not an
installed release or native GUI acceptance.
Production catalog packaging remains open. A separate 2.0 desktop shell now
opens only an explicitly chosen fresh profile and verified catalog cache. It
lists saved sources, imports CSV/PDF with a cancellable background thread,
previews unposted evidence, creates financial accounts and opens the accepted
accountless-export review. The entry point branches before 1.x profile/settings
startup. Offscreen interaction tests passed, and the owner accepted this shell
on native Windows on October 23, 2026. This is an isolated pilot,
not the daily 2.0 profile picker or ledger workflow.

The next review slice retains one explicit, reversible ledger binding for each
source account identity printed by a statement or identified export. It also
allows row assignment when an export mixes identified and unidentified rows.
Source evidence and financial accounts remain unchanged; these decisions do not
post entries. The fresh pre-release profile schema is revision 4. The shell now
offers separate review buttons for printed identities and unidentified rows.
Offscreen tests pass; the owner accepted the printed-identity dialog on native
Windows on October 24, 2026. Automatic suffix matching remains pending because the current evidence
does not yet carry trustworthy source institution and financial-account class
for the matching policy. The 2.0 global preference must become operational
before exposing that switch in the 2.0 shell.

For a native review without live data, launch the disposable synthetic demo from
the repository root in PowerShell:

```powershell
$env:PYTHONPATH='.;client/src;client'
& .\client\.venv\Scripts\python.exe -m devtools.parser_engine_pilot.open_v2_workspace --demo
```

The demo signs a temporary two-definition catalog with a generated key, creates
a temporary profile, and imports a six-row accountless export plus a one-row
identified cash export. Its status line gives the path of a third synthetic file
for testing Import source and a second test-signed release folder for testing
Install signed catalog. Closing the window removes the temporary workspace.
The real `--v2` entry requires `--profile` and `--catalog-cache`; it opens an
existing 2.x profile unless `--create-profile` is explicitly supplied. It will
not import until that cache contains a verified catalog.

The bounded decoder worker now polls a cancellation callback and terminates its
child on cancellation. The source pipeline also polls its CSV row loop and
passes the callback to PDF decoder workers. A cancelled catalog import leaves
the temporary profile without a new source. Native Windows worker cancellation
passes; the separate 2.0 shell now wires Cancel import through this callback.
Owner native shell acceptance and Intel Mac native limits remain open.

An explicit reparse comparison can read the saved source and test a candidate
definition without replacing the original evidence snapshot or decisions. A
changed definition revision changes the candidate output while the stored
snapshot survives reopening unchanged.
The global abbreviated-account matching preference now defaults off and appears
under File > Preferences. A unique same-institution, same-class suffix match can
bind automatically only when enabled; ambiguity always requires review. The
2.0 account review UI must show the candidate and an inline option to enable
this preference while it is off. Source and ledger persistence will converge
into one user-database service before activation.

## Current stop/go decision

**Go** for fresh-profile service integration and finite parser work. The
synthetic slice keeps the source and parser evidence, leaves rows unposted,
posts one explicitly reviewed expense exactly once, and leaves a credit
pending. **No go** for 2.0 activation or release yet: full-page capture review,
Intel Mac decoder-limit checks, production snapshot integration, ongoing
import/recovery, common reports and native GUI acceptance remain open. The
recent Citi layout is a required 2.0 format and has passed its dated-start
and bounded table-extraction pilots on the ten archived statements.

A proposed 2.0 profile is separate from 1.x. If the owner returns to 1.4.2,
it opens only the retained 1.x profile; it never reads a 2.x database. Work done
in either profile is not synchronized or backported. Do not switch the owner's
daily workflow until the exact 2.0 build and new profile pass native acceptance.

No version bump, live activation, installer build, server deployment or public
publication is authorized by this planning document.

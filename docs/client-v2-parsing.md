# Client 2.0 parsing engine and declarative catalog

Scope added by the owner on October 4, 2026. Engine review, simplification and a
declarative catalog are part of [2.0 cutover](client-v2-cutover.md), before finalizing
evidence storage and ongoing imports. This is an initial architecture proposal,
not an implemented engine or proof that every parser fits one declaration.
The October 13 clean-profile decision removes automatic 1.x database replay
from the 2.0 release contract; archive checks remain read-only parser evidence.

## Target and distribution

Distribute versioned parser definitions as data, interpreted locally by a tested
engine shipped with the client. The target removes downloaded `.pyc` execution
from normal 2.0 parsing. Routine institution/layout fixes update definitions;
genuinely new engine operations require a client release. Financial documents and
analysis remain local.

A server table can hold catalog metadata and JSON definitions. Clients should
consume immutable published snapshots, independent of server table layout, rather
than unversioned mutable rows. Keep signatures, hashes, compatible engine/schema
versions and atomic catalog activation: declarations still control financial meaning.

Start with one catalog JSON snapshot and a detached signature, using the existing
offline signing model. Suggested envelope fields are release sequence, schema
version, source revision and parser entries. Sign exact serialized bytes; do not
reserialize changing database rows under an old signature. Git-reviewed JSON can
be the authoring source, with a server table storing/indexing published definitions.
Choose storage after the pilot; avoid two authoritative copies. A database editing
UI, per-parser downloads and delta synchronization are not prerequisites.

Validate a complete catalog before activation, retain the last good release, reject
unsupported required capabilities and prevent silent downgrade/mixed-release use.
Cache verified definitions for offline parsing of 2.x sources. Preserve key rotation and
explicit rollback semantics. Consider a verified starter catalog at packaging time.
The server holds definitions/signatures, not statements or the private signing key.
Keep the 1.4 bytecode catalog separate for rollback; do not repurpose its manifest
contract. Installer manifests need not change because parser distribution changes.

## Initial code findings

| Inspected code | Redesign implication |
| --- | --- |
| `core/parse.py` separates PDF/CSV/XLSX readers and registry dispatch; recognition already supports search expressions, headers and PDF metadata. | Reuse useful readers and unique-match diagnostics; replace class dispatch with declaration/engine dispatch. |
| `core/interfaces.py` requires classes returning `Statement`; `core/validation.py` requires numeric account endpoints. | Introduce typed statement, export and observation evidence without invented dates or balances. |
| If any transaction lacks a balance, `sort_and_compute_balances()` recomputes all row balances before shared statement validation. | Separate observed and calculated values; calculations must not overwrite printed evidence. This finding is not a new claim of corruption in the owner's data. |
| LendingClub savings and HealthEquity independently validate printed summary/running balances in parser code. | Centralize reusable mandatory checks when independent evidence exists; a derived endpoint cannot independently validate its input rows. |
| The detailed MOHELA reader preserves components and unknown balances outside the ordinary interface. | Bring those evidence types into the common engine instead of retaining a permanent institution-specific side path. |
| Chase uses bounded sections/line patterns; Fidelity handles wrapped account labels; Wells Fargo business uses page words and dynamic table boundaries. | Pilot simple and difficult layouts. Column mappings alone are not proven sufficient for the archive. |
| `core/accounting_contracts.py` snapshots accounting roles/provenance separately from later plugin changes. | Carry that contract into source evidence; declarations describe evidence and never authorize postings. |
| Plugin manifests/store/manager bind `.pyc`, Python tags/magic bytes and loaded classes; server routes serve immutable artifacts and metadata. | Data definitions remove bytecode/compiler compatibility and duplicated class metadata. Reuse release/trust concepts while versioning the new wire contract. |

This was a review of shared boundaries and representative parsers. Full parser and
archive coverage, regression parity and actual complexity reduction remain work
under P2-1 through P2-4 below.

## Definition and engine boundary

| Definition group | Contents |
| --- | --- |
| Identity | Stable parser ID, revision, institution/document label, suffix, schema version and required engine capabilities. |
| Recognition | Required headers, text/metadata predicates, layout variants, explicit ambiguity rules. |
| Extraction | Page/section/table selectors, account groups, column maps/named captures, bounded table-row continuation and section-boundary rules. |
| Normalization | Exact money formats, explicit signs, date formats/year rollover, bounded inherited-date rules and text normalization. |
| Evidence | Statement/export/observation kind, original fields and locations, printed/derived/assumed/unknown provenance, principal/interest/fee roles. |
| Validation | Required/unique fields, row/component equations, independent balance checks where available, allowed absences and diagnostics. |
| Help | Download instructions and known source limitations. |

Use a strict schema and a finite set of named engine operations. No Python, SQL,
shell, `eval`, arbitrary module references, filesystem/network actions or general
expression execution in declarations. Support bounded row iteration and explicit
exact-money operators. Bound document size, nesting, extraction work and pattern
execution; regex length limits alone do not bound matching time. Prove cancellation
and failure behavior before choosing a regex/execution mechanism.

Do not create a general programming language merely to express every PDF quirk.
For an exceptional layout, first test whether shared finite operations cover
the behavior. Keep a small named handler shipped with the client only for the
remaining layout-specific extraction, selected from a fixed registry. Inventory
each exception and its client release cost; declarations cannot load downloaded
handlers. Measure complexity across engine, definitions, tests and publication,
not simply Python line count.

## Evidence and validation

Emit immutable observations, not journals. Preserve source signs, components, raw
bytes and locations where available: PDF page/line/region, CSV row/column, XLSX
sheet/cell. Observed balances and derived balances are different fields; unknown
is not zero. Multi-account and multi-loan identities must survive without counting
both an aggregate and its components as separate economic movements.

Separate field validity, internal arithmetic, independent source checks, accounting
review and ledger reconciliation. Activity spans, requested export ranges and
capture times do not establish statement coverage. Missing independent evidence
is valid uncertainty, never permission for a fabricated endpoint. Declarations
cannot mark history complete, reconciled or financially approved.

Within a declared activity section, account for candidate rows as parsed, explicitly
ignored with a reason, or unresolved. Unexpected date/amount rows, continuation
pages and incomplete sections must be visible. Test missing rows and malformed
boundaries, not only closing totals. Source-check failures stop normal admission
and retain diagnostics; do not generate balancing transactions.

Retain source digest, exact definition/revision/digest, engine and extraction-library
versions, normalization settings, output schema and diagnostics. Catalog updates
never rewrite old evidence or decisions. Reparse produces an explicit comparison
and new evidence version; changed output requires revalidating affected categories
and accounting decisions. Definition hashes alone do not guarantee identical results
across engine/library versions. Keep archived output usable if its original engine
cannot be replayed; distinguish restoration from reproducible parsing.

## Small implementation chunks

| Chunk | Deliverable | Acceptance |
| --- | --- | --- |
| P2-1 | Inventory every shipped parser, needed archive layout, authoring/debug/release tool and relevant dependency alongside V2-1. Group common operations and custom behavior. | Family matrix, fixture coverage, synthetic/derived behavior and explicit unsupported cases. |
| P2-2 | Design evidence output and minimal declaration schemas; prototype a local engine on synthetic fixtures. | Exact values, nullable/provenanced endpoints, location references, multiple accounts, schema/capability refusal and no executable escape hatch; inform V2 storage before schema freeze. |
| P2-3 | Pilot detailed MOHELA CSV, a simple bank/card PDF, a continuation-heavy PDF and a layout/table case; include synthetic XLSX mappings. | Corrected archive evidence comparison, account identity stability, malformed/truncated/ambiguous inputs, duplicate occurrences, bounded work and cancellation. Review intentional corrections rather than reproduce old bugs. |
| P2-4 | Convert supported daily-use families in small batches, centralize validation and expose definition/source diagnostics in the developer preview. | Archive comparison for converted families, explicit built-in exceptions, maintainability comparison; owner walkthrough for changed troubleshooting UI. No automatic 1.x category carry-forward. |
| P2-5 | Signed data-catalog client/cache/update and publication tooling against local fixtures; evaluate starter-catalog packaging. | Signature/tamper/rollback/incompatibility/cancel checks, atomic activation, installed offline replay on supported targets, no catalog bytecode compilation. |
| P2-S | Separate server catalog storage/serving/publication after merging accepted client work. Choose table/file storage from the reviewed contract. | Contract/staging checks on exact reviewed bytes, retained 1.4 catalog, no financial uploads, explicit deployment/publication acceptance. |

P2-1 through P2-3 have isolated pilot evidence; the next gate is decoder
isolation and a fresh-profile import/review integration. P2-4 proceeds by
supported family alongside integration. Complete P2-5/P2-S before public 2.0
release. Local prototypes need no server deployment. At the server boundary,
merge accepted client work first, then use a short-lived server branch; server P0
remains closed outside this interface change.

The [P2-1 parser inventory](client-v2-parser-inventory.md) lists all shipped
parser IDs, source-level fixture coverage, repeated operations and likely
client-built exceptions. Read-only archive replay and installed-catalog checks
have been performed; declarative parity and fixture gaps remain open.

The isolated [P2-2 table pilot](../devtools/parser_engine_pilot/README.md)
demonstrates strict JSON validation, exact components, source locations,
nullable balances and cancellation. Its first P2-3 read-only comparison matched
an authorized detailed CSV against the accepted reader row for row. It is not
a runtime parser, an XLSX/PDF decoder or a final evidence schema. A separate
page/line pilot matched source locations on representative Chase and cross-page
HealthEquity PDFs. A finite Chase statement-line pilot now matches the accepted
reader across the authorized Chase fixtures while retaining uninterpreted dated
details and derived-date labels. Bounded PDF decoding, independent capture
checks and other continuation/layout parsing remain open before
the interface decision gate. A separate finite HealthEquity cash-section pilot
matches the accepted reader on account, period and printed cash values across
the authorized closed archive, including continuation pages. It verifies each
printed running-balance equation, retains non-dated section lines unresolved
and leaves descriptionless rows unknown. This establishes cash evidence parity
with the accepted reader, not investment coverage, full capture or account
reconciliation. A synthetic workbook now passes a read-only XLSX decoder pilot
with ZIP expansion, member and sheet limits; formula and typed numeric/date
cells are explicitly refused. A bounded XLSX worker now runs that adapter under
Windows process memory and time limits with exact synthetic evidence parity.
No referenced archive XLSX source exists and Intel Mac limits need native
checks. A read-only Wells Fargo business
archive pass found retained rows classifiable as dated activity or wrapped
description, with no date-looking first-column row after the existing table
stop. It also confirmed that missing printed row balances are common. A
page-local geometry operation remains a prototype candidate, not an accepted
schema or license to derive those balances. An isolated geometry pilot now
retains each Wells table row's raw cells and region with an explicit disposition;
all referenced Wells Fargo business sources matched the accepted reader on
retained cells and dated-candidate count. A [bounded Wells worker pilot](../devtools/parser_engine_pilot/bounded_wells.py)
now moves word extraction and table finding out of process. Its evidence exactly
matched the in-process pilot on 21 archive PDFs (1,029 extracted rows) without
changing source hashes. Neither comparison proves full page capture; Intel Mac
native limits and runtime integration remain open.

The October 13 read-only Citi channel audit found that the current recent-layout
reader needs text and fee recovery in addition to tables. Its date/amount-only
occurrence subtraction can also overlap text and table candidates with different
descriptions. The exact-description comparison leaves additional candidates
whose financial meaning cannot be inferred from counts alone. Page-level review
of the eight referenced sources found nine date-only incomplete text copies,
one table copy missing the text description's first character, and one
additional identical occurrence on two distinct lines. The nine text-only rows
comprise three payments, two interest charges and four purchases. A finite
[Citi channel resolver pilot](../devtools/parser_engine_pilot/citi_channels.py)
now reproduces all 421 accepted date/amount row occurrences and balances on
the eight sources; it preserves source locations and refuses other overlaps.
Two descriptions intentionally differ: the fuller text copy and a fee label
without its trailing amount. The 20 overlap/text-only candidates are not the
foreign multiline pattern. A separate scan found 71 other dated lines outside
the simple text-row matcher, including foreign multiline rows and legal-text
interleaving. The repeated row-continuation behavior belongs in a bounded engine
operation: Citi, Synchrony, LendingClub and Wells all use it. A strict
[table-continuation pilot](../devtools/parser_engine_pilot/table_continuations.py)
now covers two finite shapes with column selectors and source-row references.
The [shared occurrence pilot](../devtools/parser_engine_pilot/channel_occurrences.py)
now pairs exact table/text copies one to one under a strict same-page rule and
leaves all other occurrences for explicit disposition. The refactored Citi
audit passed on nine recent-layout archive files with 428 resolved occurrences
and nine printed balance equations; each source hash was unchanged. Leave only
genuinely Citi-specific geometry or fee-section selection in a named built-in
extractor if the shared operations cannot express it simply.

A [Citi dated-line ledger](../devtools/parser_engine_pilot/citi_source_dispositions.py)
now checks page, date, signed amount, occurrence order and ordered description
words against table rows; it also checks the printed fee-section span. In the
nine-file sample, it accounts for all 67 extra dated starts as 66 table copies
and one fee. Three table descriptions lost their first character, so the
ledger records the fuller printed word. Adding the first recent-layout
statement gives ten archive PDFs: 486 dated starts map one to one to 486
resolved rows, including 72 table copies and one fee. There are no unresolved
dated starts, and all ten printed balance equations pass. This is a dated-start
capture result, not a claim about every non-dated item elsewhere on a page.

Before any PDF or XLSX pilot is used for normal import, run library decoding in
a separate worker with input/output, page/row, wall-clock and OS memory limits.
An isolated [PDF simple-text worker pilot](../devtools/parser_engine_pilot/bounded_pdf_text.py)
now covers that path: on Windows its Job Object memory cap and deadline passed
native synthetic checks, and its text matched the existing decoder on nine
recent-layout Citi PDFs without changing source hashes. Wells and Citi word/table
extraction now use the same boundary. The [bounded Citi table pilot](../devtools/parser_engine_pilot/bounded_citi.py)
returned exactly the current reader's 543 raw table/interest rows and retained
page, row and table-region locations on those ten archive PDFs. Their hashes
were unchanged. The [shared continuation operation](../devtools/parser_engine_pilot/table_continuations.py)
now retains 36 post-amount travel/lodging detail rows separately from 471
table transactions. The [Citi date/money adapter](../devtools/parser_engine_pilot/citi_table_candidates.py)
matches the current table rows in order without promoting those details to
financial activity. The Citi audit now feeds its candidate resolver from both
bounded text and table workers; the old reader remains its accepted-result
baseline. The Citi worker now also returns a capped first-page character stream,
and the PDF text worker returns capped metadata for routing. A
[finite header adapter](../devtools/parser_engine_pilot/citi_statement_header.py)
reads the billing period, account suffix and printed balances with source
locations. Bounded layout classification and all header fields matched the
old reader on ten archive statements. The standalone
[`read_recent_citi`](../devtools/parser_engine_pilot/citi_evidence.py) path
builds source-linked candidates without the legacy reader; the audit invokes
that reader afterward for comparison. Runtime integration and Intel Mac native
limits remain open.
An additional [money-line ledger](../devtools/parser_engine_pilot/citi_money_lines.py)
disposes all 281 dollar-sign lines outside dated transaction spans across the
ten recent statements. They include printed summaries, payment information,
credit terms, APR information, fee notices, disclosure and unreadable
extraction artifacts; none becomes a transaction. Unknown dollar-sign lines
refuse the standalone path. A deterministic
[partial-date operation](../devtools/parser_engine_pilot/partial_dates.py)
now refuses invalid, distant or ambiguous year resolution and retains row
parity on all ten statements. Non-money text and native import acceptance
remain open.
The [XLSX worker pilot](../devtools/parser_engine_pilot/bounded_xlsx.py)
uses the same fixed process limiter and matches synthetic in-process evidence;
it still lacks an archived workbook fixture. Intel Mac memory and timeout
behavior still need native checks.
The [fresh-profile service slice](../devtools/v2_fresh_slice/README.md) uses a
synthetic CSV with an explicit posting-date role, so it can exercise
evidence-to-ledger review without making a PDF-decoder or Citi claim.

The release gate is a reviewed engine and declarative catalog, coverage of
supported daily-use formats, explicit client-built exceptions and signed offline
distribution. If a family becomes more complicated as declarations, stop with a
concrete comparison and propose a smaller built-in operation. Do not quietly defer
the redesign or disguise arbitrary Python as JSON. This plan changes no runtime,
server deployment, dependencies or live financial data.

# Client 2.0 parsing engine and declarative catalog

Scope added by the owner on October 4, 2026. Engine review, simplification and a
declarative catalog are part of [2.0 cutover](client-v2-cutover.md), before finalizing
evidence storage and ongoing imports. This is an initial architecture proposal,
not an implemented engine or proof that every parser fits one declaration.

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
Cache verified definitions for offline parsing/rebuilds. Preserve key rotation and
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
| Extraction | Page/section/table selectors, account groups, column maps/named captures, continuation and section-boundary rules. |
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
For an exceptional layout, prefer a small named handler shipped and tested with
the client, selected from a fixed registry. Inventory each exception and its client
release cost; declarations cannot load downloaded handlers. Measure complexity
across engine, definitions, tests and publication, not simply Python line count.

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
| P2-1 | Inventory every shipped parser, needed archive layout, authoring/debug/release tool and relevant dependency alongside V2-1. Group common operations and custom behavior. | Family matrix, fixture coverage, synthetic/derived behavior, explicit unsupported cases; no parser silently dropped. |
| P2-2 | Design evidence output and minimal declaration schemas; prototype a local engine on synthetic fixtures. | Exact values, nullable/provenanced endpoints, location references, multiple accounts, schema/capability refusal and no executable escape hatch; inform V2 storage before schema freeze. |
| P2-3 | Pilot detailed MOHELA CSV, a simple bank/card PDF, a continuation-heavy PDF and a layout/table case; include synthetic XLSX mappings. | Corrected archive evidence comparison, account identity stability, malformed/truncated/ambiguous inputs, duplicate occurrences, bounded work and cancellation. Review intentional corrections rather than reproduce old bugs. |
| P2-4 | Convert needed families in small batches, centralize validation and expose definition/source diagnostics in the developer preview. | Archive replay and category-preservation parity per family, explicit built-in exceptions, maintainability comparison; owner walkthrough for changed troubleshooting UI. |
| P2-5 | Signed data-catalog client/cache/update and publication tooling against local fixtures; evaluate starter-catalog packaging. | Signature/tamper/rollback/incompatibility/cancel checks, atomic activation, installed offline replay on supported targets, no catalog bytecode compilation. |
| P2-S | Separate server catalog storage/serving/publication after merging accepted client work. Choose table/file storage from the reviewed contract. | Contract/staging checks on exact reviewed bytes, retained 1.4 catalog, no financial uploads, explicit deployment/publication acceptance. |

P2-1 and V2-1 are next. P2-2/P2-3 inform V2-2 evidence storage and precede V2-3 import
integration; P2-4 proceeds by family alongside integration. Complete P2-5/P2-S before
public 2.0 release. Local prototypes need no server deployment. At the server boundary,
merge accepted client work first, then use a short-lived server branch; server P0
remains closed outside this interface change.

The release gate is a reviewed engine and declarative catalog, archive-preserving
coverage of needed formats, explicit client-built exceptions and signed offline
distribution. If a family becomes more complicated as declarations, stop with a
concrete comparison and propose a smaller built-in operation. Do not quietly defer
the redesign or disguise arbitrary Python as JSON. This plan changes no runtime,
server deployment, dependencies or live financial data.

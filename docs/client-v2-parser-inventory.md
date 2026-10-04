# P2-1 parser and engine review: first pass

Started October 4, 2026 on `feature/client-financial-insights`. This records
source-code and synthetic-test coverage for the [declarative parser plan](client-v2-parsing.md).
No private archive was opened. Archive parity, installed signed-catalog
availability and precise exception costs remain P2-1 work.

## Shipped parser and fixture matrix

All 22 modules below define `Parser(IParser)` in `client/src/parsetrail/plugins`:
21 PDF and one CSV. There is an XLSX router and a synthetic router test, but no
shipped XLSX parser. “Targeted” means a test names the parser and exercises its
output/behavior; it does not imply full private-archive regression coverage.

| Parser ID (source filename without `.py`) | Source version | Family/layout | Current targeted evidence | Pilot operation or gap |
| --- | --- | --- | --- | --- |
| `csv_mohela_202411` | 0.2.1 | Legacy life-of-loan CSV | Loan readiness/replacement tests reference it | Its ordinary `Statement` adaptation is distinct from `core/mohela_export.py` detailed evidence; pilot the detailed reader and compare old history without invented endpoints. |
| `pdf_capitaloneauto_202402` | 0.2.2 | Auto loan PDF with payment components | Accounting and balance-evidence tests | Preserve principal/interest and printed principal; distinguish origination and missing activity. |
| `pdf_chasecc_202602` | 0.1.0 | Section/line credit-card PDF | Chase synthetic tests | Simple card pilot, section boundaries, fee/payment rows and date handling. |
| `pdf_citicc_201505` | 0.3.1 | Older Citi line credit-card PDF | Routing/classification only | Archive fixture and row coverage required. |
| `pdf_citicc_202506` | 0.3.1 | Citi table credit-card PDF | Thin-glyph table test | Table boundaries and final-row retention. |
| `pdf_citicc_202511` | 0.4.0 | Citi table plus text/fee recovery PDF | Missing-table-row and multiline-fee tests | Dynamic headers; compare table/text occurrences without double counting. |
| `pdf_fidelity401k_201810` | 0.2.1 | Retirement PDF, wrapped account labels | Fidelity synthetic test | Multiple account identity/section handling and noncash activity scope. |
| `pdf_fidelityhsa_202001` | 0.2.0 | HSA line PDF | No parser-specific test found | Archive fixture and identity/balance evidence required. |
| `pdf_happenbank_202606` | 0.1.0 | Savings line PDF | Savings-layout routing/parser test | Printed balances and line activity; distinguish from older LendingClub layout. |
| `pdf_hehsa_201810` | 0.2.1 | HealthEquity cash and continuation PDF | Continuation, boundary and running-balance tests | Continuation pilot and independent printed cash checks; retain unresolved investment scope. |
| `pdf_lendingclublus_202506` | 0.2.0 | Older savings table PDF | No parser-specific test found | Layout variant, archived fixture and table row coverage required. |
| `pdf_lendingclubsavings_202601` | 0.1.1 | Savings line PDF | Savings/balance-evidence tests | Printed summary and row balances; reject truncated tail. |
| `pdf_occubank_201409` | 0.2.0 | Multi-account bank PDF | No parser-specific test found | Separate checking/savings sections; date fallback from PDF annotations needs an explicit operation or built-in handler. |
| `pdf_occucc_201904` | 0.2.0 | Credit-card line PDF | No parser-specific test found | Interest synthesis from printed evidence and complete section capture require review. |
| `pdf_synchrony-amzncc_202501` | 0.3.0 | Store-card table PDF | No parser-specific test found | Word-header matching, dynamic table geometry and continuation. |
| `pdf_transamerica_202104` | 0.2.0 | Retirement line PDF | No parser-specific test found | Quarterly period and noncash/account sections need archive comparison. |
| `pdf_usbankreicc_201405` | 0.2.0 | Credit-card line PDF | No parser-specific test found | Metadata/line extraction and row-boundary coverage. |
| `pdf_vanguard_202210` | 0.2.0 | Retirement line PDF | No parser-specific test found | Quarterly period, account identity and activity semantics. |
| `pdf_wfbankbus_202110` | 0.2.0 | Business bank dynamic table PDF | No parser-specific test found | Layout/table pilot: word coordinates create per-page table boundaries. |
| `pdf_wfbankper_202105` | 0.2.0 | Personal bank table PDF | Ledger candidate tests reference it | Table layout and cash movements; add direct extraction fixture. |
| `pdf_wfloanper_202306` | 0.2.1 | Personal-loan line PDF | Accounting/loan tests reference it | Preserve legacy synthetic-loan uncertainty; no speculative history repair. |
| `pdf_yamahafin_202306` | 0.2.0 | Auto-loan line PDF | Loan-readiness tests reference it | Interest/principal evidence and printed endpoint checks. |

The matrix is a coverage map, not a claim that every source instance fits its
family. A signed installed catalog can differ from this checkout's parser
versions. P2-1 must join actual legacy `Plugins`/`Statements` references to
verified installed artifacts and archived source families before conversion.

## Shared engine and repeated behavior

| Current path | Reusable operation or change needed |
| --- | --- |
| `core/parse.py`: PDF `pdfplumber` reader, UTF-8-SIG CSV row reader and `openpyxl` workbook reader | Retain bounded byte readers and explicit suffix routing. Preserve PDF page/word, CSV row/column and XLSX sheet/cell references in new evidence. Today the routers pass extracted objects without durable source locations. |
| `core/parser_classification.py`, `parser_routing.py`, `search_expression.py` | Keep normalized metadata/header/body recognition and unique-match refusal. Declarations require strict syntax and finite capabilities; routing must not execute arbitrary expressions. |
| `core/interfaces.py`, `validation.py` | Replace class-returned `Statement` as the sole output with typed statement/export/observation evidence. Current `Account` requires numeric opening and closing balances. Unknown balance must remain null, not zero. |
| `core/parse.py` calling `Account.sort_and_compute_balances()` | Split printed/observed from calculated balances. If one row lacks a balance, today's helper recalculates every row in that account. Do not overwrite or mislabel printed source evidence. |
| Parser-specific line searches, regex captures, date rollover, amount signs and account sections | Candidate declarative operations: unique section marker; bounded row pattern; continuation/inherited date; exact money/sign format; account-group key; required end marker; explicit ignored/unresolved row. |
| Parser-specific `pdfplumber` word coordinates/crops/tables (Citi, Synchrony, Wells Fargo) | Candidate finite table operation with page-local header anchors and bounded geometry. Citi text/fee recovery and OCCU annotation fallback may need named client-built handlers if a small operation cannot express them. No downloaded code hook. |
| LendingClub savings, HealthEquity and MOHELA detailed checks | Centralize independently printed endpoint, row running-balance and component-equation checks. A derived endpoint cannot validate the same rows independently. Missing independent source evidence is an explicit uncertainty. |
| `core/accounting_contracts.py` and detailed `core/mohela_export.py` | Preserve statement/export kind, component roles, source signs, unknown balances, source hash and per-row occurrence. Declarations emit evidence; they never authorize journals, completeness or reconciliation. |

`core/mohela_export.py` already preserves loan identity, principal/interest/fee,
raw row, row number, duplicate occurrence and `Unavailable` principal as null.
Its activity span is not statement coverage. It should be the CSV pilot's
comparison baseline; the older CSV plugin is retained as legacy provenance.

## Archive layouts and developer/release coupling

- The managed archive is derived from the database stem. Root files are a drop
  zone; `SUCCESS` holds canonical imported originals, `FAIL` failed imports and
  `DUPLICATE` duplicate inputs. Companion ZIP/text exports may be present. One
  archived source can be linked to multiple accounts/statements; a ledger row
  can appear in overlapping statement memberships. P2 must replay all referenced
  `SUCCESS` bytes and retain other files as opaque history.
- `devtools/local_statements/batch_plugin_tester.py` compiles checkout parsers
  into a temporary directory and runs headless local fixtures. Its default
  output uses short digests. The ledger audit/rebuild tools compare historical
  sources, category annotations and MOHELA replacements. Developer previews
  need source-location and declaration-revision diagnostics under P2-4.
- `build_plugins.py`, `scripts/plugin_release.py`, `core/plugin_manifest.py`,
  `plugin_store.py`, `plugin_manager.py` and `plugin_loader.py` compile/load
  `.pyc` under a signed whole-catalog manifest. Artifact metadata includes
  Python tag/magic, hashes and compatibility. A 2.x data catalog must keep
  signature, sequence, offline cache, atomic activation and rollback checks,
  while separating its wire contract from the 1.4 bytecode catalog.
- The client pins `pdfplumber==0.11.10` and uses `openpyxl` for XLSX. Engine and
  extraction-library versions belong in replay provenance. The client release
  is required for new built-in extraction operations; definition-only layout
  fixes can follow the signed catalog after verification.

## P2-1 gaps before schema or conversion work

1. On an authorized private copy, count archived sources by referenced plugin
   ID/version, suffix, layout generation, and `SUCCESS`/`FAIL`/`DUPLICATE`/root
   location. Bind installed signed artifact availability and record any missing
   or incompatible parser. Keep names, paths and financial examples private.
2. Select representative corrected archive fixtures for detailed MOHELA CSV,
   a simple bank/card PDF, HealthEquity continuation and a layout/table PDF.
   Add a synthetic XLSX mapping. For each, record independent printed checks,
   every candidate/ignored/unresolved activity row and source locations.
3. Compare proposed finite operations against the difficult parsers above.
   Record any explicit client-built exception with its fixture, reason and
   engine release cost. Do not silently drop a parser or encode Python/SQL/eval
   in a JSON declaration.
4. Feed output-shape findings to V2-2 before freezing evidence tables. Source
   hashes, definition/revision/digest, engine/library versions and diagnostics
   must survive a reparse comparison without rewriting old decisions.

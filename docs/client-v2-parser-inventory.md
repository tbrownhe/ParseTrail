# P2-1 parser and engine review

The October 13, 2026 clean-profile decision makes this a read-only research
inventory. It does not require 2.0 to replay every 1.x archive source or carry
old parser IDs. The owner subsequently requested **all 22 currently shipped
parser families** in the first 2.0 release. Each family therefore needs an
accepted 2.0 extraction path; historical documents remain accessible through
the retained 1.4.2 profile while conversion is under way.

Started October 4, 2026 on `feature/client-financial-insights`. This records
source-code and synthetic-test coverage for the [declarative parser plan](client-v2-parsing.md).
An authorized closed-copy replay and installed signed-catalog verification have
since been completed. This review identifies conversion and fixture gates; it
does not claim declarative parity for unconverted families.

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

An authorized closed-copy replay subsequently parsed every referenced archive
source with current checkout code; all resulting account statements retained
their expected source membership. One shipped parser had no referenced fixture
in that archive, so synthetic coverage remains its only available check. The
source database remained byte-identical and no SQLite sidecars were created.
The active installed bytecode catalog also passed signature and artifact
verification in a separate read-only check. These checks do not establish
declarative-engine parity or treat old parser IDs as one-to-one names for the
current implementations. Private source counts and identifiers remain outside Git.
The verified installed catalog and checkout contain the same 22 parser names.
An authorized source-by-source binding check found no unresolved historical
statement, but one historical Citi name **and version** routes to two current
layout parsers. Therefore a historical name/version is not a safe replacement
key: retain the original reference and bind each source through its hashed
bytes, recognized layout, current parser version and replay result. The
read-only replay probe now reports these bindings and ambiguous revisions.

## Shared engine and repeated behavior

| Current path | Reusable operation or change needed |
| --- | --- |
| `core/parse.py`: PDF `pdfplumber` reader, UTF-8-SIG CSV row reader and `openpyxl` workbook reader | Retain bounded byte readers and explicit suffix routing. Preserve PDF page/word, CSV row/column and XLSX sheet/cell references in new evidence. Today the routers pass extracted objects without durable source locations. |
| `core/parser_classification.py`, `parser_routing.py`, `search_expression.py` | Keep normalized metadata/header/body recognition and unique-match refusal. Declarations require strict syntax and finite capabilities; routing must not execute arbitrary expressions. |
| `core/interfaces.py`, `validation.py` | Replace class-returned `Statement` as the sole output with typed statement/export/observation evidence. Current `Account` requires numeric opening and closing balances. Unknown balance must remain null, not zero. |
| `core/parse.py` calling `Account.sort_and_compute_balances()` | Split printed/observed from calculated balances. If one row lacks a balance, today's helper recalculates every row in that account. Do not overwrite or mislabel printed source evidence. |
| Parser-specific line searches, regex captures, date rollover, amount signs and account sections | Candidate declarative operations: unique section marker; bounded row pattern; table-row continuation/inherited date; exact money/sign format; account-group key; required end marker; explicit ignored/unresolved row. Citi, Synchrony, LendingClub and Wells share continuation shapes. |
| Parser-specific `pdfplumber` word coordinates/crops/tables (Citi, Synchrony, Wells Fargo) | Candidate finite table operation with page-local header anchors and bounded geometry. Exact occurrence reconciliation between table/text channels is an engine-operation candidate. Only layout-specific Citi geometry/fee selection and OCCU annotation fallback may need named built-in extraction if a small operation cannot express them. No downloaded code hook. |
| LendingClub savings, HealthEquity and MOHELA detailed checks | Centralize independently printed endpoint, row running-balance and component-equation checks. A derived endpoint cannot validate the same rows independently. Missing independent source evidence is an explicit uncertainty. |
| `core/accounting_contracts.py` and detailed `core/mohela_export.py` | Preserve statement/export kind, component roles, source signs, unknown balances, source hash and per-row occurrence. Declarations emit evidence; they never authorize journals, completeness or reconciliation. |

`core/mohela_export.py` already preserves loan identity, principal/interest/fee,
raw row, row number, duplicate occurrence and `Unavailable` principal as null.
Its activity span is not statement coverage. It should be the CSV pilot's
comparison baseline; the older CSV plugin is retained as legacy provenance.

The source review found specific synthetic/derived behavior that declarations
must label rather than promote to observed balances or activity:

| Parser | Current behavior | P2 evidence rule |
| --- | --- | --- |
| `csv_mohela_202411` | Uses zero as opening, builds running balances from export rows and uses the last row as closing; splits interest into a second legacy transaction. | Treat these endpoints and split rows as legacy adaptation, not printed statement evidence. Detailed export components and unknown principal belong in one source row. |
| `pdf_capitaloneauto_202402` | Reads a printed closing principal but derives opening principal from parsed components because no opening is printed. | Retain closing as printed, opening as derived, and component equations separately. |
| `pdf_wfloanper_202306` | For an empty activity section, emits a loan-origination row and sets opening to zero. | Retain the source boundary and inferred origination separately; do not silently post it as cash or certified history. |
| `pdf_occucc_201904` | Creates an interest transaction from a printed header amount rather than an activity-line row. | Keep header location and evidence role; verify that it is included once. |
| Shared balance filling | Recomputes all row balances when any row lacks one. | Preserve every printed balance independently and store calculations in a separate field. |

## Representative PDF operation cost review

These are source-code cost estimates, not accepted declaration designs. A
corrected archive comparison must check every extracted, ignored and unresolved
row, page/line location and independently printed value before any operation is
frozen. A new engine operation requires a client release; changing values in an
already supported declaration can use a signed catalog release.

| Family and source behavior | Minimum reusable operation and evidence rule | Cost or exception gate |
| --- | --- | --- |
| Chase card: whole-page line matches, printed range/account/endpoints, two-digit transaction dates and a posting-date proxy clamped to the statement range | Unique printed header fields, bounded candidate lines, explicit year resolution and liability sign; label the clamped posting date derived. Require a disposition for every transaction-shaped line and refuse ambiguous printed labels. | Medium engine work. The current parser takes the first matching balance label and scans all page text, so parity alone cannot prove complete capture. |
| HealthEquity HSA: unique beginning/ending cash balances around continuation pages, dated lines amid rate tables, printed running balances and a later investment section | Ordered unique cash boundary anchors, bounded cross-page line window, dated cash candidates and independent running/closing equations. Keep the portfolio outside cash scope and record ignored rate/continuation lines. | Medium engine work. Existing synthetic tests prove that missing or duplicate boundaries, truncated cash rows and running-balance mismatches must fail. |
| Wells Fargo business bank: per-page word-header anchors define crop/column coordinates, then a text-strategy table yields wrapped descriptions and optional row balances | Page-local anchored geometry with bounded coordinate offsets, row cells and continuation, plus a required table-end disposition. Printed row balances stay separate from later calculations. | High engine/adapter work. No direct targeted fixture test was found; the current parser stops at the first empty/ending row, so archived final-row coverage is a gate. |
| Citi 2025 card: partial word-header recovery, dynamic geometry, table rows, simple-text recovery, multiline fee section and occurrence subtraction | Use shared bounded row continuation and exact occurrence reconciliation; keep table/text/fee source locations and require section/end checks before merging. | High extraction cost. Date/amount-only recovery keys are insufficient to certify identity. A named built-in is limited to geometry or fee selection that remains layout-specific after shared-operation trials. |

The Chase and HSA shapes appear suitable for a small finite line/section pilot.
Wells Fargo needs a bounded PDF table adapter before declarations can express its
layout. Citi combines extraction channels; try that combination as a finite
engine operation before declaring an exception. None of these cost estimates
authorizes a transaction, inferred posting date or statement reconciliation.

A later read-only pass over all referenced Wells Fargo business sources found
that each retained table row was either a dated row or a wrapped description
row. The current first-empty/`Ending` stop left no date-looking first-column
row after the stop in this archive. Many dated rows have no printed row balance;
that absence must remain unknown evidence even if the accepted reader later
calculates a balance. These observations make a finite page-local geometry
pilot plausible, but do not prove complete capture, justify discarding other
post-stop content or settle how the client should bound PDF word/table work.
The referenced source files remained unchanged. A subsequent isolated
[geometry pilot](../devtools/parser_engine_pilot/README.md) emitted raw table
cells and page/row regions, with explicit dated, continuation, terminator and
post-stop dispositions. Its retained cells and dated-candidate counts matched
the accepted reader on every referenced Wells Fargo business source. This is
extractor parity only: PDF decoding/table-finding budgets, independent capture
checks and optional printed-balance evidence still need work.

A read-only archive check selected representative sources for all four families;
each routed and parsed with checkout code, and source bytes were unchanged. A
cross-page HealthEquity source and a Chase source were then compared with the
[page/line provenance pilot](../devtools/parser_engine_pilot/README.md). For
those two fixtures, the pilot's flattened text matched the accepted PDF reader
and each transaction-shaped candidate had a unique page/line location. The
candidate counts matched the current parsers' rows. This is a location and
legacy-parser comparison, not proof that the parsers captured every financial
row or that printed balances were independently preserved by the pilot.

The isolated [card-line pilot](../devtools/parser_engine_pilot/README.md)
subsequently matched every Chase-referenced source in the authorized closed
archive on account, period, printed balances and rows. It retained the
date-prefixed three-letter detail lines as uninterpreted auxiliary evidence;
the current parser omits them from its transactions. This is deliberate source
retention, not a currency conversion or a claim of complete activity coverage.
The PDF decoder and final section/row disposition rules remain open.
The bounded Chase path now emits the strict V2 envelope from its finite line
pilot on all five authorized Chase archive PDFs: 139 rows and 99 dated
auxiliary dispositions with unchanged source hashes. Full capture and native
release acceptance remain separate gates.
The finite savings-line operation also emits strict V2 evidence for both
referenced Happen PDFs. It matched the accepted reader's account, period,
printed endpoints and eight located rows with running balances. The 11
dispositions include repeated headers, balance-line tails and activity markers;
full-page capture is still unverified.
Its second finite operation covers the older LendingClub savings line layout.
All five referenced archive PDFs matched the accepted reader on account,
period, printed endpoints and 24 rows; their 20 located dispositions preserve
balance-forward and section headers. The printed six-value summary and running
chain check independently. The inherited date and period-end interest date
remain derived, and complete page capture is still unverified.
The HealthEquity cash pilot now maps to strict V2 evidence with explicit
`cash_component` balance scope. A bounded read-only pass over all 60 referenced
PDFs produced 236 rows and retained 489 unclassified lines between printed
cash boundaries; 260 of these contain decimal values. The old parser's cash
fields already matched the finite pilot, but the unclassified monetary lines
must be dispositioned before normal import admission. Investment valuation
remains outside the cash statement scope.

## Remaining family operation costs

These estimates complete the source-code review for the other 18 modules in
the matrix. They group shared operations; each listed parser still needs its own
fixture and accepted evidence comparison under P2-3/P2-4. A "high" cost is a
conversion priority signal, not permission to embed Python in a declaration.

| Parser families | Candidate finite operations and source-evidence rule | Cost and conversion gate |
| --- | --- | --- |
| `csv_mohela_202411` | Strict CSV header/column mapping, account-group key, component equation, located duplicate occurrences; emit an activity export with unknown principal where printed `Unavailable`. | Low engine cost; high accounting review. Never carry the legacy invented zero opening or split interest rows into observed evidence. |
| `pdf_capitaloneauto_202402`, `pdf_yamahafin_202306`, `pdf_wfloanper_202306` | Bounded loan history section, row components, exact principal and interest signs, printed principal endpoint, full versus partial transaction dates. | Medium. Capital One has no printed opening; Wells invents origination and groups interest/principal into a payment; Yamaha's date extraction must be checked against located source text. Preserve raw components before any posting decision. |
| `pdf_citicc_201505`, `pdf_citicc_202506` | Old layout uses a page-local text-column boundary and at most five continuation lines; middle layout uses page word anchors, table cells and inherited continuation. Both need exact dated-start dispositions and liability sign. | Medium to high. Run separate archive fixtures for both layouts; the recent-Citi resolver cannot be presumed equivalent. Refuse a candidate that reaches a new dated start without an amount. |
| `pdf_fidelity401k_201810`, `pdf_fidelityhsa_202001`, `pdf_transamerica_202104`, `pdf_vanguard_202210` | Unique period/plan or account anchors, bounded balance sections, amount-bearing lines, explicit cash versus investment scope and a source-labeled date role. | Medium. The old readers often assign period-end dates to undated rows; retain those as derived, and do not turn investment valuation changes into cash activity without printed evidence. Fidelity 401(k) headerless/browser-print plan labels need a finite recognized variant. |
| `pdf_happenbank_202606`, `pdf_lendingclubsavings_202601` | Bounded text sections, exact dates and amounts, optional inherited transaction date, printed running balances and independent closing equation. | Low to medium. LendingClub's `Interest Paid` date substitution is derived; require explicit row and tail dispositions and preserve printed source date. |
| `pdf_lendingclublus_202506`, `pdf_wfbankper_202105` | Page-local anchored table geometry, debit/credit cells, continuation descriptions, optional printed running balance and exact partial-date resolution. | Medium to high. Reuse the Wells geometry operation only after per-layout crop/header checks; do not fill missing row balances. |
| `pdf_occubank_201409`, `pdf_occucc_201904` | Multiple account sections for bank statements; ordered text-date then annotation-date source selection; located row balances. Card interest printed in a header needs a separately identified source occurrence. | Medium. Annotation decoding may need a finite shipped decoder field operation. Its precedence and location must be explicit; synthesized card interest is not an ordinary activity-line capture. |
| `pdf_synchrony-amzncc_202501` | Bounded partial-word table header recognition, page-local geometry, dated row continuation and liability sign. | High. Existing parser silently skips unmatched rows and pages; require full candidate and post-table dispositions before acceptance. |
| `pdf_usbankreicc_201405` | Use one bounded simple-text representation for both routing and extraction; optional second date and explicit `CR` sign, with unique printed account/period/balance anchors. | Medium. Current reader deliberately selects simple text because layout text breaks credit indicators; archive fixtures must cover that difference. |

Together with the four representative rows above, these entries cover every
shipped parser. No named built-in exception has been
approved. Reusable finite section, row continuation, geometry, annotation and
channel-reconciliation operations should be tried before a layout-specific
built-in is accepted.

## Archive layouts and developer/release coupling

- The managed archive is derived from the database stem. Root files are a drop
  zone; `SUCCESS` holds canonical imported originals, `FAIL` failed imports and
  `DUPLICATE` duplicate inputs. Companion ZIP/text exports may be present. One
  archived source can be linked to multiple accounts/statements; a ledger row
  can appear in overlapping statement memberships. P2 must replay all referenced
  `SUCCESS` bytes and retain other files as opaque history.
- The authorized closed-copy database has no referenced XLSX statement. An
  unreferenced workbook remains part of the archive and must be retained as
  opaque history. A read-only adapter now decodes synthetic XLSX workbooks
  under ZIP expansion and sheet limits, retaining sheet/cell locations. There
  is no archive parity fixture; formula and typed numeric/date cells are
  refused, and XML decoder time/cancellation limits remain open before future
  XLSX imports.
- `devtools/local_statements/batch_plugin_tester.py` compiles checkout parsers
  into a temporary directory and runs headless local fixtures. Its default
  output uses short digests. The ledger audit/rebuild tools compare historical
  sources, category annotations and MOHELA replacements. Developer previews
  need source-location and declaration-revision diagnostics under P2-4.
- `devtools/v2_inventory/replay_probe.py` loads checkout parser classes without
  the writable application settings module, replays referenced archive files
  against a closed database copy and reports aggregate parse/category-match
  counts plus historical-to-current parser revision bindings. It flags a
  historical revision that routes to multiple current layouts and produces no
  evidence database. It does not validate installed release trust; use the
  separate signed-release verifier for that check.
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

## Conversion and release gates after P2-1

1. Repeat source/package binding on the frozen cutover snapshot, including the
   ambiguous historical Citi revision. Keep original parser references and
   source bytes; do not substitute parser names. Keep source names, paths and
   financial examples private.
2. Detailed MOHELA CSV, Chase card, HealthEquity cash, Wells Fargo business
   table and recent Citi pilots have tested evidence. The recent Citi path
   accounts for 486 dated starts and 803 located dispositions across ten
   archive PDFs, but full-page capture and native worker acceptance remain
   open. Synthetic XLSX decoding has no referenced archive fixture.
3. Convert all 22 families using the operations above; for each, compare all
   extracted, ignored and unresolved rows and independently printed values.
   Record any necessary client-built exception with a fixture, reason and
   engine release cost. Do not encode Python, SQL or eval in JSON definitions.
4. The strict V2 evidence shape and fresh source store now preserve source,
   definition, engine/extractor versions and diagnostics. Before freezing a
   released schema, prove reparse comparison without rewriting old decisions,
   account mapping and ledger review in the unified user-database service.

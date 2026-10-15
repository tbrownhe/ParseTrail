# P2-2 bounded declaration and evidence pilot

This is an isolated prototype for the [2.0 parser plan](../../docs/client-v2-parsing.md).
It is not imported by the desktop client, not a signed catalog and not accepted
for real-statement ingestion. No database or server code is changed.

`engine.py` accepts an exact JSON declaration under
[`declaration-schema-v1.json`](declaration-schema-v1.json). The Pydantic model
rejects extra fields and unsupported schema versions, suffixes, evidence kinds
or required capabilities. The pilot operations are controlled table-header mapping,
fixed date/money formats, account grouping by an observed column or a fixed
loan-ID operation, and an optional principal + interest + fees = total check.
The declaration now labels the date as an activity date or posting date; the
default for existing export pilots is activity date. A ledger observation can
use it as a posting date only when the source contract says so explicitly.
The detailed CSV comparison also exercises a first-header-cell download prefix
and an exact empty trailing column. Definitions contain no code,
user-supplied regex, module reference, SQL or general expression language.

The prototype returns immutable activity-export evidence: source and exact
definition hashes, engine and extraction-adapter versions, normalization formats,
raw and normalized fields, CSV record/column or synthetic XLSX sheet/cell
locations, duplicate occurrences, explicit blank-row
dispositions and nullable reported balances. It leaves statement endpoints
unknown and coverage/reconciliation false. Component arithmetic is an internal
source check; it does not prove statement coverage or authorize postings.
Row identities include the source, definition, engine and extraction-adapter
versions, so a reparse under changed code cannot silently reuse an old row ID.

CSV bytes are bounded before decode, rows/cells/field lengths are bounded during
parsing, and cancellation is checked for each row. Errors expose a code and row
number without source values. PDF page/section extraction and observed statement
endpoints are outside this table pilot.

`xlsx_adapter.py` exercises the same table engine on a real, synthetic `.xlsx`
workbook. It limits compressed and expanded ZIP bytes, member count and member
size, checks every member before `openpyxl` decoding, and selects one explicit
sheet with bounded dimensions. It accepts string/blank cells only, rejecting
formulas and typed numeric/date cells until their exact-value and display
semantics are specified. Sheet/cell locations and extractor version remain in
the evidence. [`bounded_xlsx.py`](bounded_xlsx.py) now runs that adapter in the
same fixed-worker resource boundary used for PDF text. It matched the
in-process evidence on a synthetic workbook, refused formulas and terminated
at its deadline on Windows. No archived statement exercises XLSX parity, and
Intel Mac native limits remain untested. This is not a runtime import path.

`pdf_lines.py` is a separate P2-3 provenance experiment for text already
extracted by a trusted PDF reader. It binds each raw/normalized line to the
source hash, extractor version, page and line, with in-memory page/text/line
limits and cancellation. It does not open or decode a PDF, select transaction
lines, assign account identities, or prove printed balance checks. A bounded
PDF decoder remains open. Read-only checks on an authorized Chase PDF and a
cross-page HealthEquity PDF found that its flattened lines match the accepted
reader, and each compared transaction-shaped candidate has a unique page/line
location. Source bytes stayed unchanged. These checks do not establish complete
capture or declarative parity.

`card_lines.py` adds a finite statement-line experiment under the strict
[`card-declaration-schema-v1.json`](card-declaration-schema-v1.json), using
[`chase-card-pilot-definition.json`](chase-card-pilot-definition.json). It
requires unique printed period, masked account and opening/closing balances;
keeps their page/line locations; records the source sign before liability
normalization; and labels transaction year and clamped posting date as derived.
Dated three-letter detail lines are retained as uninterpreted auxiliary evidence.
Any other unmatched dated line, duplicate printed field or oversized candidate
fails the whole parse. Parsing checks cancellation per line. Coverage and balance
reconciliation remain false; the auxiliary details authorize no conversion or
posting.

`card_source_output.py` now maps that finite Chase result into the shared strict
V2 statement envelope. The bounded source pipeline admits only the exact checked
in Chase pilot definition, retains each printed balance and row line, marks
year/posting proxies as derived, and carries dated auxiliary lines as located
dispositions. In a read-only pass, all five authorized Chase archive PDFs
produced 139 rows and 99 auxiliary dispositions; source hashes stayed unchanged.
Capture remains false, and this is still a development pilot without signed
catalog routing or Intel Mac native worker acceptance.

`savings_lines.py` adds a strict finite PDF line operation for the Happen Bank
LevelUp savings layout, under
[`savings-declaration-schema-v1.json`](savings-declaration-schema-v1.json).
It accepts exact printed period, masked account and balance fields; bounds the
transaction section; keeps each printed running balance; and refuses a broken
chain or unrecognized dated/money line. Repeated page headers, balance markers
and other summary values sharing a balance line have located dispositions.
Both referenced Happen statements matched the accepted reader on account,
period, endpoints and all eight activity rows. Their strict V2 evidence reopened
from a temporary profile with 11 dispositions and unchanged source hashes.
Full-page capture, signed catalog routing and native worker acceptance remain
open.

The same `savings_lines.py` engine now has a second finite operation for the
older LendingClub LevelUp layout, under
[`summary-savings-declaration-schema-v1.json`](summary-savings-declaration-schema-v1.json).
It checks the printed six-value summary and balance forward, carries inherited
row dates and the period-end interest date as derived, and verifies every
printed running balance. All five referenced archive PDFs matched the accepted
reader on account, period, printed endpoints and 24 rows. Their strict evidence
reopened from a temporary profile with 20 located dispositions; source hashes
were unchanged. Complete page capture and native admission remain open.

`investment_summary_lines.py` adds a finite account-value summary operation
under [`investment-summary-declaration-schema-v1.json`](investment-summary-declaration-schema-v1.json).
It distinguishes printed period components from dated activity using a required
`period_summary` row role and `statement_period_end` date role. The source's
year-to-date column and all lines after the printed endpoint inside the bounded
summary window remain located dispositions. All 59 referenced Fidelity HSA
PDFs matched the accepted reader on account, period, printed endpoints and 133
summary rows. The printed account-value equation passed on each source. A
temporary V2 profile reopened all 59, indexing 133 summary rows and retaining
472 dispositions with unchanged source hashes. These summary components are
not ledger transactions: investment value change is not cash activity, and
the period-end date is a derived label. Complete page capture, accounting
review, signed routing and native acceptance remain open.

`two_date_card_lines.py` adds a finite card statement operation with separate
printed transaction and post date columns, an exact trailing-minus credit
format, and a source-to-liability sign rule. All 37 referenced Yamaha PDFs
matched the accepted reader on masked account, derived period, printed
balances and 74 posted rows. Every printed balance equation passed. The archive
prints equal values in both date columns; a synthetic fixture tests distinct
dates. A temporary V2 profile reopened all 37 sources, 74 rows and 74 header
dispositions with unchanged source hashes. Complete section/page capture,
signed routing and native acceptance remain open.

`loan_history_lines.py` adds a bounded Capital One auto history operation with
one located row per printed history line and exact principal/interest/total
component checks. All 26 referenced PDFs matched the accepted reader on full
account, printed activity range and closing principal. Their 26 source rows
carry 51 printed components; the accepted reader's 51 split ledger-shaped rows
can be reconstructed for comparison without storing those splits as source
facts. The opening principal remains unknown because it is not printed. The
closing principal and signed row components remain in source-native form, and
the generic printed `Date` has an `activity_date` role. A temporary V2 profile
reopened all 26 sources, 26 rows and 104 history dispositions with unchanged
hashes. Full-page capture, accounting review and native acceptance remain
open.

`dual_text_card_lines.py` uses bounded fixed-tolerance layout text for US Bank
REI's printed period/account/balances and bounded simple text for dated rows.
The same exact checked-in definition declares both channels, an optional
printed transaction date and the `CR` source sign. All 97 referenced PDFs
matched the accepted reader on account, period, balances and 2,137 posted rows;
all printed balance equations passed. The 9 dated-looking interest-period
headers remain located dispositions. A temporary V2 profile reopened all 97
sources, 2,137 rows and 150 dispositions with unchanged source hashes.
Seventy-seven activity rows have no printed transaction date and retain it as
unknown. Complete page capture, signed routing and native acceptance remain
open. The fixed layout worker shares the simple decoder's input, output,
deadline and native memory limits.

`single_column_summary.py` adds a finite Vanguard account-value summary
operation. It extracts the first printed period amount from each declared
component label, retains extra columns and unlabeled summary lines as located
dispositions, and checks the printed opening-to-closing equation. The six-digit
plan identifier stays opaque. All ten referenced PDFs matched the accepted
reader on identifier, period, printed balances and 45 summary components;
all ten equations passed. A temporary V2 profile reopened ten sources, 45
period-summary rows and 65 dispositions with unchanged source hashes.
Market gain/loss remains a period summary component with a derived period-end
date; accounting review, complete page capture and native acceptance remain
open.

The same summary module now has a finite Fidelity 401(k) plan-label operation
with printed, browser-print and headerless plan header variants. It limits
identity text to the recognized header-to-title region and checks that
repeated statement periods agree. All 107 referenced PDFs matched the
accepted reader on plan label, period, printed balances and 194 account-value
components; all 107 printed equations passed. A temporary V2 profile reopened
107 sources, 194 explicitly tagged period-summary rows and 55 located blank
summary lines with unchanged source hashes. Later fund sections remain outside
the current summary capture; full-page capture, accounting review and native
acceptance remain open.

`occu_card_lines.py` uses a bounded default-layout text worker because the
accepted OCCU NICE card reader uses `pdfplumber` layout extraction at its
default tolerances. Its normalized text matched the accepted decoder on all
32 archived PDFs. The finite operation separates 187 dated activity rows from
32 printed header interest charges, labeling the latter `header_charge` with
a derived statement-end date and its own header location. The masked account
is labeled `last_four`. All 32 PDFs matched the accepted reader on account,
period, balances and 219 row dates/amounts in order; every printed balance
equation passed. A temporary V2 profile reopened 32 sources, 219 observations
and 96 located dispositions with unchanged source hashes. The second
`PreviousBalance` belongs to the rewards points section and is explicitly
located as a nonfinancial disposition. Synthetic tests
refuse missing interest, conflicting balances and unresolved dated lines.
Complete page capture, signed routing and native acceptance remain open.

`pdf_annotation_worker.py` decodes only OCCU bank's first-page `FROM_DATE` and
`TO_DATE` fields under the same source, output, memory and deadline limits as
the other fixed workers. `occu_bank_lines.py` first checks printed text dates,
then uses those bounded annotations only when both text dates are absent.
The dates keep a `pdf_annotation` page and ordinal location. The operation
separates savings and checking by their printed account headings, preserves
each dated row's amount and running balance, and verifies both account chains.
All 113 archived PDFs matched the accepted reader on period, 226 accounts,
6,427 rows and printed endpoints; 78 used annotation dates. Six ATM balance
inquiries without transaction amounts remain nonfinancial dispositions. A
temporary V2 profile reopened all 113 sources, 6,427 observations and 295
located dispositions with unchanged source hashes. Optional personal credit
line sections stay outside this two-account pilot; complete capture, signed
routing and native acceptance remain open.

`legacy_citi_lines.py` adds a finite older-Citi text-column operation over
the bounded default-layout decoder. It uses the printed `Amount` header edge
and up to five same-page continuation lines; an unresolved dated start refuses
the statement. All 135 routed archive PDFs (including two direct fixtures)
matched the accepted reader on period, account, printed balances and 1,740
dated rows, including foreign multi-line detail. Every printed equation
passed. Five zero-activity statements retain zero rows only with matching
printed balances. Repeated headers/balances and parallel column text are
547 located dispositions include four `No Late Fee` amounts excluded from
activity. All 135 snapshots reopened from a temporary V2 profile with
unchanged source hashes. Complete monetary-line dispositions, full page
capture, signed routing and native acceptance remain open.

`anchored_table.py` and its bounded worker implement a reusable PDF table
operation: strict declarations name header words and finite column edge or
midpoint rules, with capped row cells, page regions, source hashes and worker
limits. The middle Citi definition matched the accepted parser's selected
cells on all eight routed archive PDFs. `table_card_source_output.py` forms
323 dated card observations from 382 located table rows and retains the other
929 of 1,311 raw rows as dispositions. A repeated header in a cross-page
foreign transaction is dispositioned while the amount continuation is kept.
All eight archive statements matched account, period, printed balances and
row order; each printed equation passed. Temporary V2 storage reopened all
eight with unchanged source hashes. Monetary table tails, full page capture,
signed routing and native acceptance remain open. The shared Citi header
reader now resolves a single embedded closing balance or a matching anchored
copy, and refuses conflicting copies.

`table_bank_source_output.py` reuses the bounded anchored-table worker for
older LendingClub savings. Its seven header words locate five data columns;
the bank operation checks the printed six-value summary and every dated
running balance. All seven routed archive PDFs matched 18 accepted rows,
account, period and endpoints. Temporary V2 storage reopened seven sources,
18 observations and 225 located dispositions with unchanged hashes. Twenty-
eight money-bearing summary/disclosure table rows remain unclassified, so
full-page capture and native acceptance remain open.

`wells_personal_source_output.py` applies a finite six-column Wells personal
bank operation to the same header-anchor worker. The declared 3-point vertical
snap reproduces the accepted text rows, and complete-line header matching
handles repeated `balance` words. All 148 routed archive PDFs matched the
accepted reader on account, period, printed balances and 6,618 transactions;
1,512 printed running balances and every closing equation passed. The worker
retains 5,473 located terminator or after-stop dispositions. Full-page
capture, signed routing and native acceptance remain open. A temporary V2
profile reopened all 148 sources and their observations without changing
source hashes.

`transamerica_summary_lines.py` retains quarterly retirement value components
as period summaries rather than cash activity. All 12 routed archive PDFs
matched the accepted reader on period, printed endpoints and 49 components;
every printed equation passed. The six-digit plan prefix is opaque source
identity. Temporary V2 storage reopened 12 sources, 49 observations and 92
located interleaved-text dispositions with unchanged hashes. Full-page
capture, account-identity review and native acceptance remain open.

`wells_loan_lines.py` retains printed Wells personal-loan interest and
principal allocations separately. The statement start stays unknown, and a
scope-aware source-evidence check verifies prior-to-ending principal using
principal components only. All 45 archive PDFs matched the accepted reader on
account, printed statement end and closing principal; 41 also matched its
opening. Four zero-activity PDFs expose the old reader's synthetic origination,
and two extra principal allocations remain separate instead of being grouped
into a synthetic payment. Temporary V2 storage reopened 45 sources, 84 source
rows and 45 located identity-copy dispositions with unchanged hashes. Posting
treatment, full-page capture and native acceptance remain open.

Every Chase-referenced fixture in the authorized closed-copy archive matched
the accepted reader's account, period, printed balances and rows in a read-only
comparison. The comparison also accounted for every date-prefixed line as a
transaction or uninterpreted detail. This is parity with the current reader,
not independent proof of complete capture. Run the comparison on an authorized
source with:

```powershell
client/.venv/Scripts/python.exe -m devtools.parser_engine_pilot.compare_chase C:\private\card-statement.pdf
```

The comparison uses the existing PDF decoder outside the pilot's bounds. A
bounded decoder and section/row coverage checks are still required before
runtime use or a final declaration schema.

`hsa_cash_lines.py` adds a finite HealthEquity cash-section pilot under the
strict [`hsa-cash-declaration-schema-v1.json`](hsa-cash-declaration-schema-v1.json)
and [`hsa-cash-pilot-definition.json`](hsa-cash-pilot-definition.json). It finds
unique printed account, period and cash boundaries across pages, retains each
cash row's page/line and printed amount/running balance, and checks the full
printed cash chain. Non-dated lines inside the cash window remain unresolved.
Rows without a printed description keep an unknown description; the accepted
reader's fallback label is not carried into source evidence. Investment content
after the printed cash closing boundary is outside this check. The result does
not claim complete capture or whole-account reconciliation.

Every HealthEquity-referenced fixture in the authorized closed-copy archive
matched the accepted reader on account, period, printed cash balances, dates,
amounts and running balances. Printed descriptions also matched. The comparison
is parity with the accepted reader, not independent proof that every cash row
was captured. The inputs and closed-copy database were unchanged. Reproduce on
an authorized source with:

```powershell
client/.venv/Scripts/python.exe -m devtools.parser_engine_pilot.compare_hsa C:\private\hsa-statement.pdf
```

This comparison uses the existing unbounded PDF decoder. Complete candidate-row
disposition and separate investment evidence remain open before runtime use or
schema freeze; the bounded-worker pass below is development evidence.

`hsa_cash_source_output.py` maps the cash pilot into the strict shared V2
envelope with `cash_component` balance scope. Its printed cash equation remains
separate from whole-HSA valuation. A bounded read-only pass produced strict
output for all 60 referenced HealthEquity PDFs: 236 cash rows and 489 located
cash-window lines outside the dated row grammar, with unchanged source hashes.
Of those 489 lines, 260 contain decimal values, including rate, balance and fee
disclosures. They remain unclassified and `capture_verified` is false. This
family is absent from the bounded source-import entry point until those
monetary lines have accepted dispositions.

`wells_table.py` pilots one named, finite page-local geometry operation under
[`wells-table-declaration-schema-v1.json`](wells-table-declaration-schema-v1.json).
It finds the printed five-word header on each table page, derives column lines
from those words, and retains raw six-cell rows with page/region references.
Every extracted row is labeled as a dated candidate, wrapped-description
continuation, terminator or unresolved row after the first table stop. An
unexpected retained row or a date-looking first-column row after the stop
fails. The operation does not normalize amounts, fill missing printed balances,
establish complete page capture or reconcile the account.

The pilot's retained raw cells and dated-candidate counts matched the accepted
Wells Fargo business reader for every referenced source in the authorized
closed-copy archive. The source files stayed unchanged. Reproduce on an
authorized source with:

```powershell
client/.venv/Scripts/python.exe -m devtools.parser_engine_pilot.compare_wells C:\private\business-statement.pdf
```

[`bounded_wells.py`](bounded_wells.py) now runs PDF decoding, word extraction and
table finding inside the fixed worker boundary. Its returned cells, regions and
dispositions exactly matched the in-process pilot on 21 authorized archive PDFs
(1,029 extracted table rows); every source hash remained unchanged. A synthetic
PDF also passes the worker test. Complete page capture, Intel Mac native limits
and runtime integration remain open; this is not an accepted declaration shape.

`wells_statement_output.py` now joins declared description continuations and
maps the bounded cells plus bounded page lines into the strict V2 statement
envelope. The same checked-in definition declares summary anchors, exact money,
partial dates and the shared continuation rule. All 29 business PDFs referenced
by the authorized closed-copy profile matched the accepted reader on account,
period, printed balances and all 225 rows. Their temporary V2 profile reopened
225 rows and 1,073 located terminator/post-stop dispositions with unchanged
source hashes. Printed row balances remain optional; absent values stay null.
`capture_verified` is false, and the after-stop rows and full page still need
capture review before normal admission.

`audit_citi_channels.py` is a read-only recent-Citi channel probe. It compares
table and text candidates by transaction date, posting date, amount, normalized
description and duplicate occurrence. Text with only a date/amount overlap is
unresolved, not automatically a new transaction. The eight referenced
recent-layout sources in the authorized archive produced 410 table candidates,
350 text candidates, 330 exact table occurrences, 11 unresolved overlaps and
nine text-only candidates. The accepted reader recovered 10 text rows and one
fee. These are different classification methods, not a parity claim; no
unmatched candidate is automatically admitted. Inputs were hash-verified and
unchanged.

A second read-only page-level check found that nine overlaps are incomplete
date-only text copies on the same page as their table row, one table copy has
lost the text description's first character, and one is an additional exact
occurrence on a distinct source line. The nine text-only rows are three payments,
two interest charges and four purchases. The finite
[`citi_channels.py`](citi_channels.py) pilot retains each table/text/fee candidate
location, pairs only explained occurrences and refuses other overlaps or a
failed printed balance equation. On the eight authorized sources it reproduces
all 421 accepted date/amount row occurrences and all eight printed balance
equations. Two descriptions intentionally differ from the old reader: the
fuller text version of a truncated table description and a fee description
without its trailing amount. No journal posting or category decision is made.

The audit also counts 36 dated lines with money and 35 without money that the
simple text-row matcher does not accept. Some are foreign transactions split
across lines; others mix transaction text with legal copy. This is a separate
complete-capture gate: each such line needs a source disposition before the
layout may be used for normal imports. The pilot still uses the old unbounded
PDF decoder and table extractor.

A later nine-file read-only sample found 67 such dated starts. The finite
[`citi_source_dispositions.py`](citi_source_dispositions.py) ledger now accounts
for all of them: 66 are table copies linked by page, date, signed amount,
occurrence order and ordered description words; one is in the printed fee
section. Three table descriptions lost their first character, so the ledger
records that extraction artifact. The eight-file counts above and the
nine-file sample are different cohorts.

Including the first recent-layout statement, all ten archive PDFs have 486
dated starts, each linked to exactly one of 486 resolved rows. The ledger reports
72 table copies, one fee and zero unresolved dated starts. Ten printed balance
equations pass; source hashes were unchanged. This check covers dated starts,
not every non-dated item on every page. The read-only audit still uses the old
in-process reader as its accepted-result baseline. Its candidate path now uses
the bounded text and table workers. [`bounded_citi.py`](bounded_citi.py) moves
Citi word/table extraction to the shared resource-limited worker. It returned
the same 543 raw table/interest rows as the accepted reader across those ten
sources and retained page, row and table-region locations. Synthetic PDF parity
and redacted invalid-source refusal also pass. Runtime integration and Intel
Mac native limits remain open.

[`table_continuations.py`](table_continuations.py) is a shared finite operation
pilot over already decoded table cells. Its strict declaration selects start
and break columns, description and optional amount columns, one of three
continuation modes, a maximum group size and cross-page behavior. It retains
every raw page/row reference and refuses orphan, truncated or undeclared
continuations. Synthetic fixtures cover the amount-on-last-row shape used by
Citi/Synchrony and the following-description shape used by Wells/LendingClub.
The third mode retains detail lines printed after an amount separately from
the transaction description. The [Citi table adapter](citi_table_candidates.py)
uses that shared mode over bounded cells: ten archive PDFs produced 471 table
transactions from 543 raw rows, preserving 36 supplemental travel/lodging
detail rows. The transaction descriptions and amounts matched the accepted
reader in order. No supplemental line was promoted to a financial row.
This is the proposed engine boundary; the Citi candidate resolver remains a
pilot. Its common occurrence-matching logic now lives in
[`channel_occurrences.py`](channel_occurrences.py): a strict same-page rule pairs
exact table/text copies one to one and labels additional exact, coarse overlap
and text-only occurrences without admitting a financial row. Citi-specific
artifact rules and the printed balance equation remain in `citi_channels.py`.
The refactored read-only audit passed on ten recent-layout archive files,
reproducing 486 accepted date/amount occurrences and ten printed balance
equations; each input's hash was unchanged. The dated-start ledger and bounded
table worker results above extend that comparison without posting rows.

Run one authorized source with:

```powershell
client/.venv/Scripts/python.exe -m devtools.parser_engine_pilot.audit_citi_channels C:\private\recent-citi.pdf
```

[`citi_evidence.py`](citi_evidence.py) now exposes `read_recent_citi` as a
standalone, read-only candidate path. It calls the bounded PDF workers and the
finite header, table and channel operations, then applies the dated-start gate.
The audit calls that path before opening the old reader for comparison. All ten
archive statements still match 486 accepted rows and ten balance equations,
with one printed dated start per resolved row and unchanged source hashes. A
synthetic non-Citi PDF is refused before Citi table extraction. This remains a
pilot and does not post to a profile or prove capture of non-monetary content.

The [money-line ledger](citi_money_lines.py) also accounts for every dollar-sign
line outside dated transaction spans in the ten sources: 183 first-page lines
cover payment information, account summaries, credit terms and repayment
examples; 98 later-page lines cover printed totals, annual summaries,
cardholder subtotals, APR tables, fee notices and legal disclosure. Five
first-page summary lines and ten later-page cardholder subtotals have visibly
garbled simple-text extraction and are retained as artifacts. Zero lines
remain unresolved. An unfamiliar dollar-sign line refuses the standalone
evidence path. These labels retain source locations and do not create
transactions or claim that every non-money item on a page is understood.

The Citi worker also retains a capped first-page character stream; the shared
PDF text worker returns capped metadata for routing. The
[statement-header adapter](citi_statement_header.py) reads the
billing period from that stream and finds the account suffix and printed
balances at bounded text line locations. The audit now independently routes
and builds candidate fields from bounded evidence, then compares them to the
old reader. All ten archive statements passed header, routing, row and balance
parity. The old reader remains only the audit's comparison baseline.
The [partial-date operation](partial_dates.py) now resolves printed `MM/DD`
dates with a finite year window and explicit refusal for invalid, distant or
ambiguous results; the ten-source Citi comparison remains unchanged.
The [recent Citi pilot definition](recent-citi-pilot-definition.json) now
selects routing, table continuation, channel occurrence, source-sign and
finite geometry operations. The bounded Citi path no longer imports the 1.x
parser; only the separate comparison audit does. Its
[shared output adapter](citi_source_output.py) reopens all ten statements from
strict JSON with 486 observations and 803 located source dispositions,
including 36 supplemental detail rows. It leaves capture verification false
and creates no accounting postings or profile writes.

The [source pipeline](source_pipeline.py) binds input and definition bytes to
that strict output under explicit size limits. The same entry point builds
synthetic CSV evidence and recent Citi PDF evidence; unknown Citi layouts and
changed definition bytes are refused. A temporary fresh 2.0 SQLite profile
saved and reopened all ten recent Citi archive files through this path without
writing the originals. This remains a pilot, pending full page capture and
native import acceptance.
The Citi definition's `usd_symbol_minor_v1` operation now rejects undeclared
money spellings and computes integer cents directly. All ten recent-layout
archive PDFs retain 486 rows and 803 dispositions under pilot revision 2.

[`bounded_pdf_text.py`](bounded_pdf_text.py) starts a separate PDF text worker
with source, output, page, line and extracted-text limits plus a wall-clock
deadline. The decoder workers use [`worker_limits.py`](worker_limits.py): Windows uses
a Job Object committed-memory limit; POSIX workers set
`RLIMIT_AS` before importing decoder libraries. The Windows synthetic test exercised
actual memory refusal and deadline termination. Isolated text extraction exactly
matched the existing decoder on nine recent-layout archive PDFs, and source
hashes remained unchanged. The Wells and Citi workers separately cover their
word/table extraction. Intel Mac native limits still need a target-machine
test. No runtime import calls these pilots.

Run the synthetic tests from the repository root:

```powershell
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_engine.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_pdf_lines.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_card_lines.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_hsa_cash_lines.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_xlsx_adapter.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_wells_table.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_audit_citi_channels.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_citi_channels.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_citi_source_dispositions.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_citi_evidence.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_citi_money_lines.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_table_continuations.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_channel_occurrences.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_bounded_pdf_text.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_bounded_xlsx.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_bounded_wells.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_bounded_citi.py
```

`mohela-pilot-definition.json` exercises those three finite layout/identity
operations against the accepted `read_export` behavior. The read-only comparison
can be run with an authorized detailed CSV:

```powershell
client/.venv/Scripts/python.exe -m devtools.parser_engine_pilot.compare_mohela C:\private\detailed-export.csv
```

It reports only aggregate parity booleans and never writes the input. An
authorized archived detailed export matched the accepted reader row for row,
including raw signs, zero components, unknown principal balances, duplicate
occurrences and activity span. The source file was unchanged. This is one
fixture comparison, not a declaration-schema freeze or accounting acceptance.
The accepted reader's more permissive money syntax still needs a disposition
for other exports, and revised/ambiguous exports must never overwrite previous
evidence. Citi's layout-specific extraction remains an exception candidate.
These results should inform V2-2 storage before its schema is frozen.

The detailed MOHELA export now uses the `mohela_detailed_export` identity in the
strict source pipeline. The one authorized detailed export matched the accepted
reader across 299 rows and ten loan identities. Its source, declaration and
evidence reopened from a temporary 2.0 profile; 208 unknown printed principal
balances remained unknown. The older life-of-loan CSV has no loan identity
column, so it remains a separate unresolved accounting format.

The HealthEquity cash operation now classifies all 489 non-dated lines inside
the printed cash boundaries as headings, rate tables, fee summaries or interest
disclosures. A new shape remains explicitly unclassified and the bounded source
pipeline refuses it. All 60 authorized PDFs passed the pipeline, with 236 cash
rows and 489 located dispositions, and reopened from a temporary 2.0 profile.
The evidence remains scoped to cash and does not claim full-page capture or
whole-account value.

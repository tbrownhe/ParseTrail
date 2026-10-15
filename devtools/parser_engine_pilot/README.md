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

This comparison uses the existing unbounded PDF decoder. A bounded decoder,
candidate-row disposition and separate investment evidence remain open before
runtime use or schema freeze.

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
in-process reader for comparison. [`bounded_citi.py`](bounded_citi.py) now moves
Citi word/table extraction to the shared resource-limited worker. It returned
the same 543 raw table/interest rows as the accepted reader across those ten
sources and retained page, row and table-region locations. Synthetic PDF parity
and redacted invalid-source refusal also pass. Runtime integration and Intel
Mac native limits remain open.

[`table_continuations.py`](table_continuations.py) is a shared finite operation
pilot over already decoded table cells. Its strict declaration selects start
and break columns, description and optional amount columns, one of two
continuation modes, a maximum group size and cross-page behavior. It retains
every raw page/row reference and refuses orphan, truncated or undeclared
continuations. Synthetic fixtures cover the amount-on-last-row shape used by
Citi/Synchrony and the following-description shape used by Wells/LendingClub.
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

The audit uses the existing unbounded PDF decoder for comparison. The pilot's
finite resolver and dated-start inventory are not runtime parsers or full-page
capture proof.

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

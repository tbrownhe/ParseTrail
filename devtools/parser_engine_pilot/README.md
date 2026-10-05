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
number without source values. The XLSX test supplies already decoded synthetic
rows; real workbook ZIP/XML expansion still needs a bounded adapter before
untrusted XLSX input. PDF page/section extraction and observed statement
endpoints are outside this table pilot.

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

Run the synthetic tests from the repository root:

```powershell
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_engine.py
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_pdf_lines.py
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
evidence. Other representative pilots are a simple card/bank PDF, a
continuation-heavy HSA PDF, a dynamic table PDF and a bounded real XLSX adapter.
These results should inform V2-2 storage before its schema is frozen.

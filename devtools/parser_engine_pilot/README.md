# P2-2 bounded declaration and evidence pilot

This is an isolated prototype for the [2.0 parser plan](../../docs/client-v2-parsing.md).
It is not imported by the desktop client, not a signed catalog and not accepted
for real-statement ingestion. No database or server code is changed.

`engine.py` accepts an exact JSON declaration under
[`declaration-schema-v1.json`](declaration-schema-v1.json). The Pydantic model
rejects extra fields and unsupported schema versions, suffixes, evidence kinds
or required capabilities. The only operations are exact table-header mapping,
fixed date/money formats, account grouping by an observed column and an optional
principal + interest + fees = total check. Definitions contain no code,
user-supplied regex, module reference, SQL or general expression language.

The prototype returns immutable activity-export evidence: source and exact
definition hashes, engine and extraction-adapter versions, normalization formats,
raw and normalized fields, CSV row/column or
synthetic XLSX sheet/cell locations, duplicate occurrences, explicit blank-row
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

Run the synthetic tests from the repository root:

```powershell
client/.venv/Scripts/python.exe -m pytest -q devtools/parser_engine_pilot/test_engine.py
```

Before P2-3 can use detailed MOHELA exports, the accepted reader's download
header prefix/trailing empty column and loan-ID extraction need explicit finite
operations. The pilot currently groups by the complete observed `LoanName`
field and requires an exact header. The P2-3 comparison must retain unknown
principal balances, zero components, raw signs and duplicate occurrences, and
refuse revised/ambiguous exports without overwriting prior evidence. Other
representative pilots are a simple card/bank PDF, a continuation-heavy HSA PDF,
a dynamic table PDF and a bounded real XLSX adapter. These results should inform
V2-2 storage before its schema is frozen.

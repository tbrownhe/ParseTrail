# 2.0 parser boundary review before storage

The owner approved a fresh single-database profile with immutable source and
evidence snapshots and invited core routing, utility and model changes. This
review separates upstream evidence work from the storage implementation. It
does not change the running 1.4.2 profile, server or application version.

## Findings and 2.0 action

| Current code behavior | Why it blocks the clean evidence path | 2.0 action |
| --- | --- | --- |
| `core/parse.py` passes each format's decoder output directly to a plugin, then forces `sort_and_compute_balances()` on every account before validation. | One absent running balance recalculates **all** rows, including rows whose printed balance was observed. The result loses which numbers came from the source. | Make bounded decode and evidence extraction separate stages. Preserve printed and derived fields separately; no implicit balance filling in admission. |
| `core/validation.py` requires `Statement` dates and numeric account endpoints; `Transaction` requires both date roles and a description. `Statement` also carries archive path, plugin name, content hash and database IDs. | Activity exports, unknown printed balances, absent transaction dates and unreadable descriptions cannot be represented honestly. Parser evidence and import bookkeeping are mixed. | Introduce immutable, strict `statement` and `activity_export` evidence payloads under one versioned envelope. Keep import paths, ledger IDs and authored state outside it; replace the output shape instead of widening the 1.x dataclasses. |
| The shared balance validator allows a one-cent discrepancy and checks endpoints that may have been derived from the same rows. | It can mistake self-consistency for independent source validation. | Check exact integer minor-unit equations only when printed independent endpoints exist. Record field, capture, arithmetic, independent source, interpretation and reconciliation states separately. |
| `Transaction.hash_transactions()` requires a running balance and fingerprints normalized financial fields. | A source row with unknown balance cannot get an identity, and overlap matching is not the same as source identity. | Key observations to exact source digest, evidence snapshot and located occurrence. Keep duplicate source copies and later accounting allocations separate. |
| `PDFRouter` uses in-process `PDFReader`; `XLSXRouter` loads a workbook without worker limits and omits zero-valued cells from routing text. | Untrusted decoding is unbounded, while routing and extraction may see different representations. | Decode once behind the bounded worker, preserving pages/cells/metadata and zeros. Route from that same capped evidence, require exactly one declaration, then extract. Native Intel Mac worker-limit checks remain a release gate. |
| `core/utils.py:get_absolute_date` searches a set of years and chooses the nearest candidate without explicit tie or malformed-input refusal. `parse_money` accepts multiple sign styles implicitly. | Date and money interpretation cannot be audited from a declaration. | Use finite, explicit date and money operations. The new deterministic partial-date pilot refuses invalid, distant or ambiguous dates and matches ten recent Citi archive statements. Keep exact source strings and normalization settings. |
| The recent Citi pilot still imports 1.x parser constants and its geometry method. | A standalone bounded evidence path is not yet a 2.0 engine path. | Move routing/field/section rules into strict 2.0 definitions and page-local geometry into a finite shipped operation if the shared table rule cannot express it. Keep the old parser only in a read-only comparison audit. |

## Recommended pipeline

`source bytes → bounded decoder → validated catalog route → finite extraction →
strict evidence output → source checks → immutable import → explicit account map
and accounting review`.

The decoder must return enough located raw material for both routing and
capture checks. The extractor emits candidate rows plus parsed, ignored or
unresolved dispositions for declared sections. The evidence envelope holds
source/definition digests, parser/engine/extractor versions, raw and normalized
fields, provenance, locations and diagnostics. A statement declares printed
coverage and optional printed balances; an activity export declares an activity
span without claiming statement coverage. Neither kind contains postings,
categories or verification flags.

Admission fails on unknown routing, unsupported capabilities, unresolved
financial-looking source lines, contradictory printed fields, failed exact
source equations or decoder limits. A missing independent balance stays
unknown and may still be valid evidence. Accounting decisions happen only
after evidence is admitted and an explicit source account is mapped.

## Order before the approved store

1. Specify and test the shared immutable evidence envelope with separate
   statement/export payloads, source locations and exact money/date provenance.
2. Remove the Citi pilot's dependency on the 1.x parser from its bounded path;
   keep the ten-file comparison audit as a regression baseline. Reuse finite
   continuation and channel-occurrence operations.
3. Route and validate the typed output through one bounded admission function,
   with the synthetic CSV and recent Citi as the first two proof sources.
4. Implement the approved SQLite source/evidence transaction against those
   admitted outputs; then connect ledger observations and user review.

This sequence avoids baking the 1.x `Statement` shape or the CSV-only pilot
snapshot into the released 2.0 database. It does not require replaying old
profiles or carrying compatibility aliases.

The first upstream proof is now in [`source_evidence.py`](../client/src/parsetrail/core/source_evidence.py):
a strict, immutable version-1 envelope with distinct statement and activity
export payloads, typed PDF/CSV/XLSX locations, observed/derived/unknown value
provenance, source fragments and dispositions. It rejects accounting fields,
duplicate row IDs and unsupported versions. Statement balances use exact
minor-unit equations only when both endpoints and row amounts are observed.
The [table adapter](../devtools/parser_engine_pilot/table_source_output.py)
round-trips a synthetic CSV with an unknown balance through this contract.
The recent Citi adapter and bounded admission function remain the next proof;
this schema is not yet the released stored snapshot.

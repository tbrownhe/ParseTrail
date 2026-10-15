"""Map parsed table evidence into the shared, immutable 2.0 output contract."""

from __future__ import annotations

from parsetrail.core.source_evidence import (
    ActivityExportPayload,
    ComponentEvidence,
    CsvCell,
    CsvRow,
    DateValue,
    MoneyValue,
    ObservationEvidence,
    SourceDisposition,
    SourceEvidence,
    SourceFragment,
    TextValue,
    XlsxCell,
    XlsxRow,
)

from devtools.parser_engine_pilot.engine import CellLocation, Evidence, FieldEvidence


def _cell(location: CellLocation) -> CsvCell | XlsxCell:
    if location.suffix == ".csv":
        return CsvCell(kind="csv_cell", row=location.row, column=location.column)
    if location.sheet is None:
        raise ValueError("missing XLSX sheet")
    return XlsxCell(kind="xlsx_cell", sheet=location.sheet, row=location.row, column=location.column)


def _row(location: CellLocation) -> CsvRow | XlsxRow:
    if location.suffix == ".csv":
        return CsvRow(kind="csv_row", row=location.row)
    if location.sheet is None:
        raise ValueError("missing XLSX sheet")
    return XlsxRow(kind="xlsx_row", sheet=location.sheet, row=location.row)


def _money(field: FieldEvidence) -> MoneyValue:
    if field.normalized is not None and type(field.normalized) is not int:
        raise ValueError("invalid table money")
    return MoneyValue(
        raw=field.raw,
        minor=field.normalized,
        provenance=field.provenance,
        locations=(_cell(field.location),),
    )


def _date(field: FieldEvidence) -> DateValue:
    if type(field.normalized) is not str:
        raise ValueError("invalid table date")
    return DateValue(
        raw=field.raw,
        iso=field.normalized,
        provenance=field.provenance,
        locations=(_cell(field.location),),
    )


def _text(field: FieldEvidence) -> TextValue:
    if type(field.normalized) is not str:
        raise ValueError("invalid table text")
    return TextValue(
        raw=field.raw,
        text=field.normalized,
        provenance=field.provenance,
        locations=(_cell(field.location),),
    )


def from_table(evidence: Evidence) -> SourceEvidence:
    """Preserve mapped raw cells, unknown balances and explicit activity span."""
    if evidence.kind != "activity_export" or evidence.activity_start is None or evidence.activity_end is None:
        raise ValueError("unsupported table evidence")
    rows = []
    for row in evidence.rows:
        fields = [row.account, row.date, row.description, row.total]
        fields.extend(field for _, field in row.components)
        if row.balance is not None:
            fields.append(row.balance)
        rows.append(
            ObservationEvidence(
                row_role="activity",
                row_id=row.row_id,
                occurrence=row.occurrence,
                source_account=row.account.normalized,
                source_account_form="opaque",
                date_role=evidence.date_role,
                date=_date(row.date),
                transaction_date=None,
                description=_text(row.description),
                amount=_money(row.total),
                running_balance=_money(row.balance) if row.balance is not None else None,
                components=tuple(
                    ComponentEvidence(role="fee" if role == "fees" else role, amount=_money(field))
                    for role, field in row.components
                ),
                fragments=(
                    SourceFragment(
                        channel="table",
                        location=_row(row.date.location),
                        raw_values=tuple(field.raw for field in fields),
                    ),
                ),
            )
        )
    earliest = min(evidence.rows, key=lambda row: row.date.normalized)
    latest = max(evidence.rows, key=lambda row: row.date.normalized)
    location = earliest.date.location
    dispositions = tuple(
        SourceDisposition(
            code=item.reason,
            location=CsvRow(kind="csv_row", row=item.row)
            if location.suffix == ".csv"
            else XlsxRow(kind="xlsx_row", sheet=location.sheet, row=item.row),
        )
        for item in evidence.ignored_rows
    )
    return SourceEvidence(
        schema_version=2,
        source_sha256=evidence.source_sha256,
        definition_sha256=evidence.definition_sha256,
        parser_id=evidence.parser_id,
        definition_revision=evidence.definition_revision,
        engine_version=evidence.engine_version,
        extractor_version=evidence.extraction_adapter,
        payload=ActivityExportPayload(
            kind="activity_export",
            activity_start=DateValue(
                raw=None,
                iso=evidence.activity_start,
                provenance="derived",
                locations=(_cell(earliest.date.location),),
            ),
            activity_end=DateValue(
                raw=None,
                iso=evidence.activity_end,
                provenance="derived",
                locations=(_cell(latest.date.location),),
            ),
            rows=tuple(rows),
            dispositions=dispositions,
        ),
    )

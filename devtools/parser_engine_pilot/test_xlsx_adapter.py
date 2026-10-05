"""Synthetic workbook decoding and refusal cases for the table pilot."""

from __future__ import annotations

import io
import json
import zipfile

import openpyxl
import pytest

from devtools.parser_engine_pilot.engine import EngineError
from devtools.parser_engine_pilot.xlsx_adapter import XlsxError, parse_xlsx

HEADER = ("Date", "Account", "Description", "Total", "Balance")


def definition() -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "parser_id": "synthetic_xlsx_table",
            "revision": "1",
            "suffix": ".xlsx",
            "kind": "activity_export",
            "capabilities": ["table_rows_v1"],
            "header": HEADER,
            "columns": {
                "account": "Account",
                "date": "Date",
                "description": "Description",
                "total": "Total",
                "balance": "Balance",
            },
            "date_format": "MM/DD/YYYY",
            "money_format": "usd_symbol_2dp",
            "unknown_balance_literals": ["Unavailable"],
        }
    ).encode()


def workbook(*, formula: bool = False, number: bool = False) -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Activity"
    sheet.append(HEADER)
    sheet.append(("10/01/2026", "Account A", "Payment", "-$1.00", "Unavailable"))
    sheet.append(("10/01/2026", "Account A", "Payment", "-$1.00", "Unavailable"))
    sheet.append((None,) * len(HEADER))
    if formula:
        sheet["D2"] = "=1+1"
    if number:
        sheet["D2"] = 2
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_real_xlsx_decoder_preserves_sheet_cell_and_duplicate_occurrence() -> None:
    source = workbook()
    evidence = parse_xlsx(definition(), source, sheet="Activity")
    assert evidence.extraction_adapter.startswith("openpyxl-")
    assert len(evidence.rows) == 2
    assert (evidence.rows[0].occurrence, evidence.rows[1].occurrence) == (0, 1)
    assert evidence.rows[0].row_id != evidence.rows[1].row_id
    assert evidence.rows[0].total.normalized == -100
    assert evidence.rows[0].total.location.sheet == "Activity"
    assert evidence.rows[0].total.location.cell_reference == "D2"
    assert evidence.rows[0].balance.normalized is None
    assert evidence.rows[0].balance.provenance == "unknown"
    assert evidence.ignored_rows[0].row == 4
    assert evidence.coverage_verified is False and evidence.balance_reconciled is False


@pytest.mark.parametrize(
    ("source", "code"), [(workbook(formula=True), "formula_cell"), (workbook(number=True), "cell_type_or_size")]
)
def test_formula_and_nontext_cells_are_refused(source: bytes, code: str) -> None:
    with pytest.raises(XlsxError) as exc:
        parse_xlsx(definition(), source, sheet="Activity")
    assert (exc.value.code, exc.value.row) == (code, 2)
    assert "Account A" not in str(exc.value)


def test_archive_and_sheet_boundaries_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    source = workbook()
    with pytest.raises(XlsxError, match="source_size"):
        parse_xlsx(definition(), b"", sheet="Activity")
    with pytest.raises(XlsxError, match="missing_or_excess_sheets"):
        parse_xlsx(definition(), source, sheet="Absent")
    with pytest.raises(XlsxError, match="xlsx_structure"):
        parse_xlsx(definition(), b"not a workbook", sheet="Activity")

    import devtools.parser_engine_pilot.xlsx_adapter as adapter

    monkeypatch.setattr(adapter, "MAX_EXPANDED_BYTES", 100)
    with pytest.raises(XlsxError, match="expanded_size"):
        parse_xlsx(definition(), source, sheet="Activity")


def test_duplicate_zip_member_and_cancel_are_refused() -> None:
    source = workbook()
    altered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(altered, "w") as output:
        for item in original.infolist():
            output.writestr(item, original.read(item))
        with pytest.warns(UserWarning, match="Duplicate name"):
            output.writestr("xl/workbook.xml", b"duplicate")
    with pytest.raises(XlsxError, match="archive_member"):
        parse_xlsx(definition(), altered.getvalue(), sheet="Activity")
    with pytest.raises(XlsxError, match="cancelled"):
        parse_xlsx(definition(), source, sheet="Activity", cancelled=lambda: True)


def test_table_validation_still_controls_decoded_rows() -> None:
    source = workbook()
    changed = json.loads(definition())
    changed["header"][0] = "Wrong"
    changed["columns"]["date"] = "Wrong"
    with pytest.raises(EngineError, match="header_mismatch"):
        parse_xlsx(json.dumps(changed).encode(), source, sheet="Activity")


def test_sparse_sheet_dimension_is_rejected_before_row_iteration() -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Activity"
    sheet.append(HEADER)
    sheet["A100001"] = "sparse"
    output = io.BytesIO()
    book.save(output)
    book.close()
    with pytest.raises(XlsxError, match="sheet_dimensions"):
        parse_xlsx(definition(), output.getvalue(), sheet="Activity")

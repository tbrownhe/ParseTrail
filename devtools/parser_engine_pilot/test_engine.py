"""Synthetic P2-2 declaration and evidence pilot cases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from devtools.parser_engine_pilot import engine
from devtools.parser_engine_pilot.compare_mohela import DEFINITION, compare
from devtools.parser_engine_pilot.engine import (
    MAX_SOURCE_BYTES,
    Definition,
    EngineError,
    parse_csv,
    parse_table,
)

HEADER = ["Date", "LoanName", "Description", "Principal", "Interest", "Fees", "Total", "UnpaidPrincipalBalanceValue"]


def definition(*, suffix: str = ".csv", components: bool = True) -> bytes:
    columns = {
        "account": "LoanName",
        "date": "Date",
        "description": "Description",
        "total": "Total",
        "balance": "UnpaidPrincipalBalanceValue",
    }
    if components:
        columns.update(principal="Principal", interest="Interest", fees="Fees")
    return json.dumps(
        {
            "schema_version": 1,
            "parser_id": "synthetic_mohela_table",
            "revision": "1",
            "suffix": suffix,
            "kind": "activity_export",
            "capabilities": ["table_rows_v1", *(["components_v1"] if components else [])],
            "header": HEADER,
            "columns": columns,
            "date_format": "MM/DD/YYYY",
            "money_format": "usd_symbol_2dp",
            "unknown_balance_literals": ["Unavailable"],
        },
        separators=(",", ":"),
    ).encode()


def data() -> bytes:
    return (
        b"Date,LoanName,Description,Principal,Interest,Fees,Total,UnpaidPrincipalBalanceValue\n"
        b"10/01/2026,Loan A,Payment,-$80.00,-$20.00,$0.00,-$100.00,$900.00\n"
        b"10/02/2026,Loan B,Payment,-$50.00,$0.00,$0.00,-$50.00,Unavailable\n"
        b"10/02/2026,Loan B,Payment,-$50.00,$0.00,$0.00,-$50.00,Unavailable\n"
    )


def test_csv_evidence_preserves_components_unknown_balance_locations_and_occurrences() -> None:
    declaration = definition()
    source = data()
    evidence = parse_csv(declaration, source)
    assert evidence.source_sha256 == hashlib.sha256(source).hexdigest()
    assert evidence.definition_sha256 == hashlib.sha256(declaration).hexdigest()
    assert evidence.output_schema_version == 1
    assert evidence.date_role == "activity_date"
    assert evidence.extraction_adapter.startswith("python-csv-")
    assert evidence.account_identities == ("Loan A", "Loan B")
    assert (evidence.activity_start, evidence.activity_end) == ("2026-10-01", "2026-10-02")
    assert evidence.statement_opening_minor is None and evidence.statement_closing_minor is None
    assert evidence.coverage_verified is False and evidence.balance_reconciled is False
    first = evidence.rows[0]
    assert first.total.normalized == -10000
    assert dict(first.components)["principal"].normalized == -8000
    assert first.total.location.row == 2 and first.total.location.column == 7
    assert first.total.location.suffix == ".csv" and first.total.location.sheet is None
    assert evidence.rows[1].balance.normalized is None
    assert evidence.rows[1].balance.provenance == "unknown"
    assert evidence.rows[1].balance.raw == "Unavailable"
    assert (evidence.rows[1].occurrence, evidence.rows[2].occurrence) == (0, 1)
    assert evidence.rows[1].row_id != evidence.rows[2].row_id
    changed = json.loads(declaration)
    changed["revision"] = "2"
    revised = parse_csv(json.dumps(changed).encode(), source)
    assert revised.rows[0].row_id != evidence.rows[0].row_id
    synthetic_rows = [
        HEADER,
        ["10/01/2026", "Loan A", "Payment", "-$80.00", "-$20.00", "$0.00", "-$100.00", "$900.00"],
    ]
    adapter_a = parse_table(declaration, source, synthetic_rows, suffix=".csv", extraction_adapter="adapter-a")
    adapter_b = parse_table(declaration, source, synthetic_rows, suffix=".csv", extraction_adapter="adapter-b")
    assert adapter_a.rows[0].row_id != adapter_b.rows[0].row_id


def test_reviewed_declaration_schema_matches_model() -> None:
    path = Path(__file__).with_name("declaration-schema-v1.json")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == Definition.model_json_schema()
    assert saved["additionalProperties"] is False
    assert saved["$defs"]["Columns"]["additionalProperties"] is False


def test_synthetic_xlsx_mapping_retains_sheet_and_cell_locations() -> None:
    rows = [
        HEADER,
        ["10/01/2026", "Loan A", "Payment", "-$80.00", "-$20.00", "$0.00", "-$100.00", "$900.00"],
        [None] * len(HEADER),
    ]
    evidence = parse_table(definition(suffix=".xlsx"), b"synthetic workbook", rows, suffix=".xlsx", sheet="Activity")
    assert evidence.rows[0].total.location.sheet == "Activity"
    assert evidence.rows[0].total.location.row == 2
    assert evidence.rows[0].total.location.cell_reference == "G2"
    assert evidence.ignored_rows[0].row == 3 and evidence.ignored_rows[0].reason == "blank_row"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda row: row.__setitem__(6, "-$99.00"), "component_equation"),
        (lambda row: row.__setitem__(0, "10/2/2026"), "invalid_date"),
        (lambda row: row.__setitem__(7, "0"), "invalid_money"),
    ],
)
def test_invalid_activity_refuses_whole_output_without_private_values(change, code) -> None:
    rows = [HEADER, ["10/01/2026", "Loan A", "Private merchant", "-$80.00", "-$20.00", "$0.00", "-$100.00", "$900.00"]]
    change(rows[1])
    with pytest.raises(EngineError) as exc:
        parse_table(definition(), b"private source", rows, suffix=".csv")
    assert exc.value.code == code
    assert exc.value.row == 2
    assert "Private merchant" not in str(exc.value)
    if code == "invalid_date":
        assert exc.value.__context__ is None or exc.value.__suppress_context__ is True


def test_schema_capability_and_executable_escape_hatch_refused() -> None:
    for change in (
        {"schema_version": 2},
        {"capabilities": ["table_rows_v1", "eval_v1"]},
        {"python": "import os"},
        {
            "columns": {
                "account": "LoanName",
                "date": "Date",
                "description": "Description",
                "total": "Total",
                "python": "x",
            }
        },
    ):
        raw = json.loads(definition())
        raw.update(change)
        with pytest.raises(EngineError, match="invalid_definition"):
            parse_csv(json.dumps(raw).encode(), data())


def test_unknown_account_key_requires_absent_account_column() -> None:
    raw = json.loads(definition())
    raw["account_key"] = "unknown"
    with pytest.raises(EngineError, match="invalid_definition"):
        parse_csv(json.dumps(raw).encode(), data())
    raw["columns"].pop("account")
    raw["header"].remove("LoanName")
    source = (
        b"Date,Description,Principal,Interest,Fees,Total,UnpaidPrincipalBalanceValue\n"
        b"10/01/2026,Payment,-$80.00,-$20.00,$0.00,-$100.00,Unavailable\n"
    )
    evidence = parse_csv(json.dumps(raw).encode(), source)
    assert evidence.account_identities == ()
    assert evidence.rows[0].account is None


def test_cancellation_and_size_limits() -> None:
    checks = 0

    def cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(EngineError) as exc:
        parse_csv(definition(), data(), cancelled=cancel)
    assert (exc.value.code, exc.value.row) == ("cancelled", 3)
    with pytest.raises(EngineError, match="source_size"):
        parse_csv(definition(), b"x" * (MAX_SOURCE_BYTES + 1))


def test_row_cell_and_csv_structure_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        HEADER,
        ["10/01/2026", "Loan A", "Payment", "-$80.00", "-$20.00", "$0.00", "-$100.00", "$900.00"],
        ["10/02/2026", "Loan B", "Payment", "-$50.00", "$0.00", "$0.00", "-$50.00", "Unavailable"],
    ]
    monkeypatch.setattr(engine, "MAX_ROWS", 2)
    with pytest.raises(EngineError, match="row_limit"):
        parse_table(definition(), b"synthetic", rows, suffix=".csv")
    monkeypatch.setattr(engine, "MAX_ROWS", 100_000)
    monkeypatch.setattr(engine, "MAX_CELLS", len(HEADER))
    with pytest.raises(EngineError, match="cell_limit"):
        parse_table(definition(), b"synthetic", rows, suffix=".csv")
    monkeypatch.setattr(engine, "MAX_CELLS", 1_000_000)

    def oversized_row():
        for _ in range(engine.MAX_COLUMNS + 1):
            yield "x"
        pytest.fail("parser read beyond its column limit")

    with pytest.raises(EngineError, match="cell_limit"):
        parse_table(definition(), b"synthetic", [HEADER, oversized_row()], suffix=".csv")
    with pytest.raises(EngineError, match="csv_structure"):
        parse_csv(definition(), ",".join(HEADER).encode() + b'\n"unfinished')


def mohela_download() -> bytes:
    return (
        b"<!DOCTYPE html>Date,LoanName,Description,Principal,Interest,Fees,Total,UnpaidPrincipalBalanceValue,\r\n"
        b"10/01/2026,1-01 Direct Loan,DISBURSEMENT,$5.00,$0.00,$0.00,$5.00,Unavailable,\r\n"
        b"10/02/2026,1-01 Direct Loan,PAYMENT,-$1.00,-$0.20,$0.00,-$1.20,$4.00,\r\n"
        b"10/02/2026,1-01 Direct Loan,PAYMENT,-$1.00,-$0.20,$0.00,-$1.20,$4.00,\r\n"
    )


def test_detailed_mohela_operations_match_accepted_reader() -> None:
    source = mohela_download()
    declaration = DEFINITION.read_bytes()
    assert all(compare(source, declaration).values())
    evidence = parse_csv(declaration, source)
    assert evidence.account_identities == ("1-01",)
    assert evidence.rows[0].account.raw == "1-01 Direct Loan"
    assert evidence.rows[0].balance.normalized is None
    assert (evidence.rows[1].occurrence, evidence.rows[2].occurrence) == (0, 1)


def test_detailed_mohela_refuses_trailing_data_or_conflicting_name() -> None:
    source = mohela_download()
    declaration = DEFINITION.read_bytes()
    with pytest.raises(EngineError, match="trailing_column"):
        parse_csv(declaration, source.replace(b"$4.00,\r\n", b"$4.00,unexpected\r\n", 1))
    with pytest.raises(EngineError, match="account_name_conflict"):
        parse_csv(declaration, source.replace(b"1-01 Direct Loan,PAYMENT", b"1-01 Changed Loan,PAYMENT", 1))

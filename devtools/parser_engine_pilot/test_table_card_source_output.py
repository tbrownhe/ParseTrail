"""Declared table-card rows and supplemental table cells stay distinct."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_anchored_table import (
    ENGINE_VERSION as TABLE_VERSION,
)
from parsetrail.core.v2_anchored_table import (
    AnchoredPage,
    AnchoredRow,
    AnchoredTableDefinition,
    AnchoredTableEvidence,
)
from parsetrail.core.v2_pdf_lines import page_lines

from devtools.parser_engine_pilot.table_card_source_output import TableCardError, from_anchored_card

DEFINITION = Path(__file__).with_name("middle-citi-table-pilot-definition.json").read_bytes()
SOURCE = b"%PDF-synthetic"


def evidence(changes: dict[int, tuple[str, str, str, str]] | None = None):
    raw = [
        ("01/05", "01/05", "Payment", "-$20.00"),
        ("", "", "DETAIL", ""),
        ("01/10", "01/09", "FOREIGN", ""),
        ("date", "date", "", ""),
        ("", "", "PURCHASE", "$10.00"),
        ("", "", "", ""),
    ]
    for index, replacement in (changes or {}).items():
        raw[index] = replacement
    rows = tuple(
        AnchoredRow(1 if index < 3 else 2, index + 1 if index < 3 else index - 2, (10.0, 10.0, 100.0, 20.0), cells)
        for index, cells in enumerate(raw)
    )
    table = AnchoredTableEvidence(
        1,
        hashlib.sha256(SOURCE).hexdigest(),
        hashlib.sha256(DEFINITION).hexdigest(),
        TABLE_VERSION,
        "pdfplumber-synthetic-anchored-table",
        "Billing Period: 01/01/26-01/31/26 Account number ending in: 1234",
        (
            AnchoredPage(1, "table", (10.0, 10.0, 100.0, 20.0), (10.0, 20.0, 40.0, 80.0, 100.0)),
            AnchoredPage(2, "table", (10.0, 10.0, 100.0, 20.0), (10.0, 20.0, 40.0, 80.0, 100.0)),
        ),
        rows,
        False,
    )
    text = page_lines(
        SOURCE,
        [
            "Account number ending in: 1234\nPrevious balance $100.00\nNew balance $90.00",
            "Account number ending in 1234",
        ],
        extraction_library="pdfplumber-bounded-layout-default-v1",
    )
    return table, text


def test_table_card_source_rows_and_cross_page_continuation() -> None:
    output = from_anchored_card(DEFINITION, *evidence())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    account = output.payload.accounts[0]
    assert (account.opening.minor, account.closing.minor) == (-10000, -9000)
    assert [(row.date.iso, row.amount.minor, row.description.text) for row in account.rows] == [
        ("2026-01-05", 2000, "Payment"),
        ("2026-01-09", -1000, "FOREIGN PURCHASE"),
    ]
    assert account.rows[1].transaction_date.iso == "2026-01-10"
    assert len(account.rows[1].fragments) == 2
    assert {item.code for item in output.payload.dispositions} == {
        "nonactivity_table_row",
        "repeated_table_header",
        "blank_table_row",
    }


def test_new_start_before_amount_or_unbalanced_statement_refuses() -> None:
    with pytest.raises(TableCardError, match="new_row_before_amount"):
        from_anchored_card(DEFINITION, *evidence({4: ("01/11", "01/11", "NEXT", "$10.00")}))
    with pytest.raises(TableCardError, match="printed_card_balance_equation"):
        from_anchored_card(DEFINITION, *evidence({4: ("", "", "PURCHASE", "$11.00")}))


def test_declaration_schema_and_executable_field_refusal() -> None:
    assert AnchoredTableDefinition.model_validate_json(DEFINITION).operation == "anchored_columns_table_v1"
    schema = json.loads(Path(__file__).with_name("anchored-table-declaration-schema-v1.json").read_text())
    assert schema == AnchoredTableDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(ValueError, match="invalid_definition"):
        from_anchored_card(json.dumps(raw).encode(), *evidence())

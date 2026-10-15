"""Single-column account values remain period summaries, with extra text located."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence

from devtools.parser_engine_pilot.pdf_lines import page_lines
from devtools.parser_engine_pilot.single_column_summary import (
    SingleColumnSummaryDefinition,
    SingleColumnSummaryError,
    parse_single_column_summary,
)

DEFINITION = Path(__file__).with_name("vanguard-summary-pilot-definition.json").read_bytes()


def lines(changes: dict[int, str] | None = None):
    source = [
        "ACCOUNT SUMMARY: 01/01/2026 - 03/31/2026",
        "Some plan information",
        "EMPLOYEES�� 123456",
        "Beginning balance $100.00 $300.00",
        "Your contributions $50.00 $500.00",
        "$1,500",
        "Employer contributions $25.00",
        "Market gain/loss -$5.00 $20.00",
        "Other transactions $0.00",
        "Ending balance $170.00 $820.00",
    ]
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    return page_lines(b"%PDF-synthetic", ["\n".join(source)], extraction_library="synthetic-pdf-1")


def test_period_summary_rows_and_unresolved_secondary_values() -> None:
    output = parse_single_column_summary(DEFINITION, lines())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    account = output.payload.accounts[0]
    assert account.source_identity == "123456" and account.source_identity_form == "opaque"
    assert (account.opening.minor, account.closing.minor) == (10000, 17000)
    assert [row.amount.minor for row in account.rows] == [5000, 2500, -500, 0]
    assert all(row.row_role == "period_summary" and row.date_role == "statement_period_end" for row in account.rows)
    assert {item.code for item in output.payload.dispositions} == {
        "summary_window_unclassified",
        "summary_extra_column",
    }


def test_wrong_equation_and_missing_primary_money_refuse_statement() -> None:
    with pytest.raises(SingleColumnSummaryError, match="printed_summary_equation"):
        parse_single_column_summary(DEFINITION, lines({9: "Ending balance $171.00"}))
    with pytest.raises(SingleColumnSummaryError, match="missing_summary_amount"):
        parse_single_column_summary(DEFINITION, lines({7: "Market gain/loss unknown"}))


def test_definition_schema_and_unknown_field() -> None:
    assert SingleColumnSummaryDefinition.model_validate_json(DEFINITION).operation == "single_column_value_summary_v1"
    saved = json.loads(Path(__file__).with_name("single-column-summary-declaration-schema-v1.json").read_text())
    assert saved == SingleColumnSummaryDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(SingleColumnSummaryError, match="invalid_definition"):
        parse_single_column_summary(json.dumps(raw).encode(), lines())

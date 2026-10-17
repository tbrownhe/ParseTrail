"""Wells business table cells become scoped, located statement evidence."""

from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_wells_table import extract_table_rows

from devtools.parser_engine_pilot.test_wells_table import FakePage, cells
from devtools.parser_engine_pilot.wells_statement_output import WellsStatementError, from_wells_business

DEFINITION = Path(__file__).with_name("wells-table-pilot-definition.json").read_bytes()
SOURCE = b"%PDF-synthetic"


def statement_text() -> list[str]:
    return [
        "\n".join(
            (
                "October 31, 2026 Page 1 of 1",
                "Statement period activity summary Account number: 1234567890",
                "Beginning balance on 10/1 $100.00",
                "Ending balance on 10/31 $101.00",
            )
        )
    ]


def table_cells() -> list[list[str | None]]:
    result = cells()
    result[0][0] = "10/1"
    return result


def build(values: list[list[str | None]] | None = None):
    table = extract_table_rows(
        DEFINITION,
        SOURCE,
        [FakePage(values if values is not None else table_cells())],
        extraction_library="synthetic-pdf-1",
    )
    lines = page_lines(SOURCE, statement_text(), extraction_library="synthetic-pdf-1")
    return from_wells_business(DEFINITION, table, lines)


def test_printed_balance_and_continuation_round_trip() -> None:
    output = build()
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.start.iso == "2026-10-01" and output.payload.start.provenance == "derived"
    assert output.payload.end.iso == "2026-10-31" and output.payload.end.provenance == "observed"
    account = output.payload.accounts[0]
    assert account.balance_scope == "account_total"
    assert (account.opening.minor, account.closing.minor) == (10000, 10100)
    assert len(account.rows) == 1
    assert account.rows[0].description.text == "Printed description continuation"
    assert len(account.rows[0].fragments) == 2
    assert account.rows[0].running_balance.minor == 10100
    assert len(output.payload.dispositions) == 2
    assert output.payload.independent_balance_verified is True
    assert output.payload.capture_verified is False


def test_wrong_printed_running_balance_refuses_statement() -> None:
    values = table_cells()
    values[0][5] = "$102.00"
    with pytest.raises(WellsStatementError, match="printed_running_mismatch"):
        build(values)

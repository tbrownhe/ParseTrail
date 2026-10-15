"""Finite summary and inherited-date savings operation."""

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence

from devtools.parser_engine_pilot.pdf_lines import page_lines
from devtools.parser_engine_pilot.savings_lines import (
    SavingsLineError,
    SummarySavingsDefinition,
    parse_summary_savings_lines,
)

DEFINITION = Path(__file__).with_name("lendingclub-savings-pilot-definition.json").read_bytes()


def pages() -> list[str]:
    return [
        "\n".join(
            (
                "************************* LevelUp Savings 1234567890 ***********************",
                "Date_Description________Deposit___Withdrawal___Balance",
                "09/16 Balance Forward -----------> 100.00",
                "09/20 Deposit 20.00 120.00",
                "09/22 Withdrawal 5.00- 115.00",
                "Interest Paid 1.00 116.00",
                "Previous Statement Date: 09/15/26",
                "Beginning Interest Service Ending",
                "Balance + Deposits + Paid - Deductions- Charge = Balance",
                "100.00 20.00 1.00 5.00 0.00 116.00",
                "Statement from 09/16/26 thru 10/15/26",
            )
        )
    ]


def parse(text_pages: list[str] | None = None, definition: bytes = DEFINITION):
    lines = page_lines(
        b"%PDF-synthetic", text_pages if text_pages is not None else pages(), extraction_library="synthetic-pdf-1"
    )
    return parse_summary_savings_lines(definition, lines)


def test_summary_equation_inherited_date_and_printed_chain() -> None:
    output = parse()
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    account = output.payload.accounts[0]
    assert account.source_identity == "1234567890" and account.source_identity_form == "full"
    assert (account.opening.minor, account.closing.minor) == (10000, 11600)
    assert [row.amount.minor for row in account.rows] == [2000, -500, 100]
    assert [row.date.iso for row in account.rows] == ["2026-09-20", "2026-09-22", "2026-10-15"]
    assert account.rows[-1].date.provenance == "derived"
    assert len(account.rows[-1].date.locations) == 2
    assert output.payload.independent_balance_verified is True
    assert output.payload.capture_verified is False


def test_summary_or_activity_gap_refuses_output() -> None:
    broken = pages()
    broken[0] = broken[0].replace("100.00 20.00 1.00 5.00 0.00 116.00", "100.00 20.00 1.00 5.00 0.00 117.00")
    with pytest.raises(SavingsLineError, match="summary_equation"):
        parse(broken)
    broken = pages()
    broken[0] = broken[0].replace("09/22 Withdrawal 5.00- 115.00", "09/22 Withdrawal 5.00-")
    with pytest.raises(SavingsLineError, match="unresolved_activity_line"):
        parse(broken)


def test_summary_definition_schema_and_cancellation() -> None:
    saved = json.loads(
        Path(__file__).with_name("summary-savings-declaration-schema-v1.json").read_text(encoding="utf-8")
    )
    assert saved == SummarySavingsDefinition.model_json_schema()
    for change in ({"schema_version": 2}, {"python": "import os"}, {"capabilities": ["pdf_lines_v1"]}):
        raw = json.loads(DEFINITION)
        raw.update(change)
        with pytest.raises(SavingsLineError, match="invalid_definition"):
            parse(definition=json.dumps(raw).encode())
    with pytest.raises(SavingsLineError, match="cancelled"):
        parse_summary_savings_lines(
            DEFINITION,
            page_lines(b"%PDF-synthetic", pages(), extraction_library="synthetic-pdf-1"),
            cancelled=lambda: True,
        )

"""Finite savings line operation retains printed balances and located rows."""

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence

from devtools.parser_engine_pilot.pdf_lines import page_lines
from devtools.parser_engine_pilot.savings_lines import SavingsDefinition, SavingsLineError, parse_savings_lines

DEFINITION = Path(__file__).with_name("happen-savings-pilot-definition.json").read_bytes()


def pages() -> list[str]:
    return [
        "\n".join(
            (
                "Statement Period: 09/16/2026 - 10/15/2026",
                "LevelUp Savings Account Number: XXXXXX1234",
                "Beginning Balance as of09/15/26 100.00 Interest for Period Ending10/15/26 0.00",
                "Ending Balance as of10/15/26 110.00 Penalty YTD 0.00",
                "Transactional Detail",
                "Date Description Amount Balance",
                "09/16 Beginning Balance 100.00",
                "09/20 Interest Paid 10.00 110.00",
                "10/15 Ending Balance 110.00",
                "Overdraft/Return Item Summary",
            )
        ),
        "Statement Period: 09/16/2026 - 10/15/2026",
    ]


def parse(text_pages: list[str] | None = None, definition: bytes = DEFINITION):
    lines = page_lines(
        b"%PDF-synthetic", text_pages if text_pages is not None else pages(), extraction_library="synthetic-pdf-1"
    )
    return parse_savings_lines(definition, lines)


def test_printed_chain_and_repeated_header_round_trip() -> None:
    output = parse()
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    account = output.payload.accounts[0]
    assert account.source_identity == "1234" and account.source_identity_form == "last_four"
    assert (account.opening.minor, account.closing.minor) == (10000, 11000)
    assert len(account.rows) == 1
    assert account.rows[0].date.iso == "2026-09-20"
    assert account.rows[0].date.provenance == "derived"
    assert account.rows[0].running_balance.minor == 11000
    assert account.rows[0].fragments[0].raw_values == ("09/20 Interest Paid 10.00 110.00",)
    assert {item.code for item in output.payload.dispositions} == {
        "activity_header",
        "balance_marker",
        "balance_line_tail",
        "repeated_period_header",
    }


def test_unknown_activity_and_wrong_printed_balance_refuse_whole_output() -> None:
    broken = pages()
    broken[0] = broken[0].replace("09/20 Interest Paid 10.00 110.00", "09/20 Interest Paid 10.00")
    with pytest.raises(SavingsLineError, match="unresolved_activity_line"):
        parse(broken)
    broken = pages()
    broken[0] = broken[0].replace("09/20 Interest Paid 10.00 110.00", "09/20 Interest Paid 10.00 109.00")
    with pytest.raises(SavingsLineError, match="printed_running_mismatch"):
        parse(broken)
    broken = pages()
    broken[1] = "Statement Period: 09/16/2026 - 10/16/2026"
    with pytest.raises(SavingsLineError, match="duplicate_period"):
        parse(broken)
    broken = pages()
    broken[0] = broken[0].replace("09/20 Interest Paid 10.00 110.00", "09/20 Interest Paid 1,0.00 110.00")
    with pytest.raises(SavingsLineError, match="unresolved_activity_line"):
        parse(broken)


def test_definition_refuses_executable_fields_and_cancel() -> None:
    saved = json.loads(Path(__file__).with_name("savings-declaration-schema-v1.json").read_text(encoding="utf-8"))
    assert saved == SavingsDefinition.model_json_schema()
    for change in ({"schema_version": 2}, {"python": "import os"}, {"capabilities": ["pdf_lines_v1"]}):
        raw = json.loads(DEFINITION)
        raw.update(change)
        with pytest.raises(SavingsLineError, match="invalid_definition"):
            parse(definition=json.dumps(raw).encode())
    with pytest.raises(SavingsLineError, match="cancelled"):
        parse_savings_lines(
            DEFINITION,
            page_lines(b"%PDF-synthetic", pages(), extraction_library="synthetic-pdf-1"),
            cancelled=lambda: True,
        )

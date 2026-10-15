"""Older Citi layout date starts and bounded continuation remain located."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence

from devtools.parser_engine_pilot.legacy_citi_lines import (
    LegacyCitiDefinition,
    LegacyCitiError,
    parse_legacy_citi,
)
from devtools.parser_engine_pilot.pdf_lines import page_lines

DEFINITION = Path(__file__).with_name("legacy-citi-pilot-definition.json").read_bytes()


def lines(changes: dict[int, str] | None = None, extra: tuple[str, ...] = ()):
    source = [
        "www.citicards.com",
        "Account number ending in: 1234",
        "Billing Period: 01/01/26-01/31/26",
        "Previous balance $100.00",
        "New balance $90.00",
        "Date Date Description Amount",
        "01/05 AUTOPAY AUTO-PMT -$20.00",
        "01/10 01/09 FOREIGN PURCHASE",
        "            LOCATION $10.00",
    ]
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    source.extend(extra)
    return page_lines(
        b"%PDF-synthetic",
        ["\n".join(source)],
        extraction_library="pdfplumber-bounded-layout-default-v1",
    )


def parse(changes: dict[int, str] | None = None, extra: tuple[str, ...] = ()):
    return parse_legacy_citi(DEFINITION, lines(changes, extra))


def test_bounded_continuation_and_liability_equation() -> None:
    output = parse()
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    account = output.payload.accounts[0]
    assert account.source_identity == "1234" and account.source_identity_form == "last_four"
    assert (account.opening.minor, account.closing.minor) == (-10000, -9000)
    assert [(r.date.iso, r.amount.minor, r.description.text) for r in account.rows] == [
        ("2026-01-05", 2000, "AUTOPAY AUTO-PMT"),
        ("2026-01-09", -1000, "FOREIGN PURCHASE LOCATION"),
    ]
    assert account.rows[0].transaction_date is None
    assert account.rows[1].transaction_date.iso == "2026-01-10"
    assert len(account.rows[1].fragments) == 2
    assert account.rows[1].date.locations[0].end_line == 9


def test_missing_amount_or_changed_balance_refuses() -> None:
    with pytest.raises(LegacyCitiError, match="unresolved_dated_start"):
        parse({8: "            LOCATION"})
    with pytest.raises(LegacyCitiError, match="printed_card_balance_equation"):
        parse({4: "New balance $91.00"})
    with pytest.raises(LegacyCitiError, match="missing_or_ambiguous_account"):
        parse({1: "Account number absent"})


def test_parallel_column_and_repeated_balance_are_located() -> None:
    output = parse(
        {
            2: "Billing Period:01/01/26-01/31/26 01/05-01/31",
            6: "01/05 AUTOPAY AUTO-PMT -$20.00 No Late Fee: $10.00",
        },
        ("Please pay New balance $90.00 promptly",),
    )
    assert [row.amount.minor for row in output.payload.accounts[0].rows] == [2000, -1000]
    assert [item.code for item in output.payload.dispositions] == [
        "parallel_no_late_fee",
        "repeated_closing_balance",
    ]
    with pytest.raises(LegacyCitiError, match="ambiguous_parallel_money"):
        parse({6: "01/05 AUTOPAY AUTO-PMT -$20.00 Unknown $10.00"})


def test_zero_activity_requires_printed_equal_balances_and_table_header() -> None:
    output = parse({4: "New balance $100.00", 6: "", 7: "", 8: ""})
    assert output.payload.accounts[0].rows == ()
    with pytest.raises(LegacyCitiError, match="printed_card_balance_equation"):
        parse({6: "", 7: "", 8: ""})
    with pytest.raises(LegacyCitiError, match="missing_activity_rows"):
        parse({4: "New balance $100.00", 5: "", 6: "", 7: "", 8: ""})


def test_definition_schema_and_unknown_field() -> None:
    assert LegacyCitiDefinition.model_validate_json(DEFINITION).operation == "layout_date_start_continuation_v1"
    schema = json.loads(Path(__file__).with_name("legacy-citi-declaration-schema-v1.json").read_text())
    assert schema == LegacyCitiDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(LegacyCitiError, match="invalid_definition"):
        parse_legacy_citi(json.dumps(raw).encode(), lines())

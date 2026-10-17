"""OCCU interest remains a located header charge, separate from dated lines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_pdf_lines import page_lines

from devtools.parser_engine_pilot.occu_card_lines import OccuCardDefinition, OccuCardError, parse_occu_card

DEFINITION = Path(__file__).with_name("occu-card-pilot-definition.json").read_bytes()


def lines(changes: dict[int, str] | None = None):
    source = [
        "AccountNumberXXXXXXXXXXXX1234 Page1of3",
        "StatementClosingDate 01/31/26",
        "DaysinBillingCycle 31 Payment notice",
        "PreviousBalance $100.00",
        "InterestCharged + $5.00 Payment example",
        "NewBalance $95.00",
        "RewardsPointsSummary",
        "PreviousBalance 100.00",
        "01/05 01/04 Purchase 10.00",
        "01/10 01/09 Payment -20.00",
        "AccountNumber XXXXXXXXXXXX1234",
        "NewBalance $95.00",
        "InterestCharged",
    ]
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    return page_lines(
        b"%PDF-synthetic",
        ["\n".join(source)],
        extraction_library="pdfplumber-bounded-layout-default-v1",
    )


def parse(changes: dict[int, str] | None = None):
    return parse_occu_card(DEFINITION, lines(changes))


def test_dated_rows_header_charge_and_printed_equation() -> None:
    output = parse()
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    account = output.payload.accounts[0]
    assert account.source_identity == "1234" and account.source_identity_form == "last_four"
    assert (account.opening.minor, account.closing.minor) == (-10000, -9500)
    assert [(r.row_role, r.date_role, r.amount.minor) for r in account.rows] == [
        ("activity", "posting_date", -1000),
        ("activity", "posting_date", 2000),
        ("header_charge", "statement_period_end", -500),
    ]
    assert account.rows[-1].date.iso == "2026-01-31"
    assert account.rows[-1].amount.locations == (account.rows[-1].fragments[0].location,)
    assert {d.code for d in output.payload.dispositions} == {
        "repeated_closing_balance",
        "interest_section_heading",
        "rewards_points_previous_balance",
    }


def test_conflicting_or_missing_header_amount_and_unknown_dated_line_refuse() -> None:
    with pytest.raises(OccuCardError, match="printed_card_balance_equation"):
        parse({4: "InterestCharged + $6.00"})
    with pytest.raises(OccuCardError, match="missing_or_ambiguous_interest"):
        parse({4: "InterestCharged"})
    with pytest.raises(OccuCardError, match="conflicting_printed_closing"):
        parse({11: "NewBalance $96.00"})
    with pytest.raises(OccuCardError, match="unresolved_dated_line"):
        parse({9: "01/10 Payment amount unavailable"})
    with pytest.raises(OccuCardError, match="missing_or_ambiguous_rewards_section"):
        parse({6: "Unidentified section"})


def test_definition_is_strict_and_channel_is_explicit() -> None:
    assert OccuCardDefinition.model_validate_json(DEFINITION).operation == "card_header_charge_v1"
    schema = json.loads(Path(__file__).with_name("occu-card-declaration-schema-v1.json").read_text())
    assert schema == OccuCardDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(OccuCardError, match="invalid_definition"):
        parse_occu_card(json.dumps(raw).encode(), lines())
    other_channel = page_lines(b"%PDF-synthetic", ["StatementClosingDate 01/31/26"], extraction_library="other")
    with pytest.raises(OccuCardError, match="source_channel_mismatch"):
        parse_occu_card(DEFINITION, other_channel)

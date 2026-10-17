"""Printed transaction and posting columns remain distinct source evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_pdf_lines import page_lines

from devtools.parser_engine_pilot.two_date_card_lines import (
    TwoDateCardDefinition,
    TwoDateCardError,
    parse_two_date_card,
)

DEFINITION = Path(__file__).with_name("yamaha-card-pilot-definition.json").read_bytes()


def lines(changes: dict[int, str] | None = None):
    source = [
        "Statement Account Number: 1234 56XX XXXX 7890",
        "Previous Balance $1,000.00 New Balance: $990.00",
        "Statement Closing Date 02/28/26",
        "Days in Billing Cycle 28",
        "ACCOUNT ACTIVITY SINCE YOUR LAST STATEMENT",
        "Transaction Post",
        "Reference Number Transaction Description Amount",
        "Date Date",
        "PURCHASES",
        "02/05 02/07 Purchase $10.00",
        "PAYMENTS",
        "02/09 02/10 Payment $20.00-",
    ]
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    return page_lines(b"%PDF-synthetic", ["\n".join(source)], extraction_library="synthetic-pdf-1")


def test_printed_dates_credit_sign_and_liability_equation() -> None:
    output = parse_two_date_card(DEFINITION, lines())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    account = output.payload.accounts[0]
    assert account.source_identity == "123456XXXXXX7890" and account.source_identity_form == "opaque"
    assert (account.opening.minor, account.closing.minor) == (-100000, -99000)
    assert [(row.transaction_date.iso, row.date.iso, row.amount.minor) for row in account.rows] == [
        ("2026-02-05", "2026-02-07", -1000),
        ("2026-02-09", "2026-02-10", 2000),
    ]
    assert all(row.row_role == "activity" for row in account.rows)


def test_wrong_equation_or_unresolved_dated_line_refuses_statement() -> None:
    with pytest.raises(TwoDateCardError, match="printed_card_balance_equation"):
        parse_two_date_card(DEFINITION, lines({1: "Previous Balance $1,000.00 New Balance: $989.00"}))
    with pytest.raises(TwoDateCardError, match="unresolved_dated_line"):
        parse_two_date_card(DEFINITION, lines({11: "02/09 Mystery"}))
    with pytest.raises(TwoDateCardError, match="posting_outside_period"):
        parse_two_date_card(DEFINITION, lines({11: "02/09 03/03 Payment $20.00-"}))


def test_definition_schema_and_unknown_fields() -> None:
    assert TwoDateCardDefinition.model_validate_json(DEFINITION).operation == "two_date_card_activity_v1"
    saved = json.loads(Path(__file__).with_name("two-date-card-declaration-schema-v1.json").read_text())
    assert saved == TwoDateCardDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(TwoDateCardError, match="invalid_definition"):
        parse_two_date_card(json.dumps(raw).encode(), lines())

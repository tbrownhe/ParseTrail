"""Printed loan components retain source sign and unknown opening principal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence

from devtools.parser_engine_pilot.loan_history_lines import (
    LoanHistoryDefinition,
    LoanHistoryError,
    parse_loan_history,
)
from devtools.parser_engine_pilot.pdf_lines import page_lines

DEFINITION = Path(__file__).with_name("capital-one-loan-pilot-definition.json").read_bytes()


def lines(*, interest: bool = True, changes: dict[int, str] | None = None):
    source = [
        "Account Number: 1234567890123",
        "Current Payment Due: $300.00 Principal Balance: $9,500.00",
        "Transactions between 01/01/2026 - 01/31/2026",
        "Date Description Principal Interest Total" if interest else "Date Description Principal Total",
        (
            "01/15/2026 Payment Received -$200.00 -$20.00 = -$220.00"
            if interest
            else "01/15/2026 Amount Financed $10,000.00 = $10,000.00"
        ),
        "",
        "Please detach and return the portion below with your payment.",
        "Account Number: 1234567890123",
    ]
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    return page_lines(b"%PDF-synthetic", ["\n".join(source)], extraction_library="synthetic-pdf-1")


def test_printed_component_row_and_unknown_opening() -> None:
    output = parse_loan_history(DEFINITION, lines())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is False
    account = output.payload.accounts[0]
    assert account.balance_scope == "principal_component"
    assert account.opening is None and account.closing.minor == 950000
    row = account.rows[0]
    assert row.row_role == "activity" and row.date_role == "activity_date"
    assert row.amount.minor == -22000
    assert [(component.role, component.amount.minor) for component in row.components] == [
        ("principal", -20000),
        ("interest", -2000),
    ]
    assert row.date.provenance == "observed"


def test_no_interest_header_keeps_one_principal_component() -> None:
    output = parse_loan_history(DEFINITION, lines(interest=False))
    row = output.payload.accounts[0].rows[0]
    assert row.amount.minor == 1000000
    assert [(component.role, component.amount.minor) for component in row.components] == [("principal", 1000000)]


def test_component_mismatch_or_unrecognized_history_refuses_source() -> None:
    with pytest.raises(LoanHistoryError, match="printed_component_equation"):
        parse_loan_history(DEFINITION, lines(changes={4: "01/15/2026 Payment Received -$200.00 -$20.00 = -$221.00"}))
    with pytest.raises(LoanHistoryError, match="unresolved_history_row"):
        parse_loan_history(DEFINITION, lines(changes={4: "01/15/2026 Unknown activity"}))
    with pytest.raises(LoanHistoryError, match="missing_history_end"):
        parse_loan_history(DEFINITION, lines(changes={6: "Other text"}))


def test_finite_definition_schema_and_unknown_field() -> None:
    assert LoanHistoryDefinition.model_validate_json(DEFINITION).operation == "printed_loan_history_components_v1"
    saved = json.loads(Path(__file__).with_name("loan-history-declaration-schema-v1.json").read_text())
    assert saved == LoanHistoryDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(LoanHistoryError, match="invalid_definition"):
        parse_loan_history(json.dumps(raw).encode(), lines())

"""Printed loan components retain source sign and unknown opening principal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_loan_history_lines import (
    LoanHistoryDefinition,
    LoanHistoryError,
    parse_loan_history,
)
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_source_pipeline import SourcePipelineError, build_source_evidence

from devtools.parser_engine_pilot.synthetic_family_sources import pdf_document, text_page

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
    assert row.amount.raw == "-$220.00"
    assert [part.amount.raw for part in row.components] == ["-$200.00", "-$20.00"]
    assert all(part.amount.provenance == "observed" for part in row.components)
    assert all(part.amount.locations == row.amount.locations == row.date.locations for part in row.components)
    assert row.fragments[0].location == row.amount.locations[0]
    assert row.fragments[0].raw_values == (lines().lines[4].raw,)
    assert (row.amount.locations[0].page, row.amount.locations[0].line) == (1, 5)


def test_repeated_printed_payments_remain_distinct_located_occurrences() -> None:
    duplicate = lines().lines[4].raw
    source = lines(changes={5: duplicate})
    output = parse_loan_history(DEFINITION, source)
    rows = output.payload.accounts[0].rows
    assert [row.occurrence for row in rows] == [0, 1]
    assert len({row.row_id for row in rows}) == 2
    assert [row.amount.locations[0].line for row in rows] == [5, 6]
    assert all(row.fragments[0].raw_values == (duplicate,) for row in rows)
    assert [row.components for row in rows] != [rows[0].components] * 2
    assert parse_loan_history(DEFINITION, source) == output


def test_bounded_pdf_pipeline_retains_single_line_split_across_two_pages() -> None:
    source = pdf_document(
        (
            text_page("Capital One Auto Finance", *(line.raw for line in lines().lines)),
            text_page("Additional statement information"),
        )
    )
    output = build_source_evidence(source, DEFINITION, suffix=".pdf")
    account = output.payload.accounts[0]
    row = account.rows[0]
    assert (row.amount.minor, tuple(part.amount.minor for part in row.components)) == (-22000, (-20000, -2000))
    assert row.fragments[0].raw_values == (lines().lines[4].raw,)
    assert all(part.amount.locations == row.amount.locations == row.date.locations for part in row.components)
    assert (row.amount.locations[0].page, row.amount.locations[0].line) == (1, 6)
    assert account.opening is None and account.closing.provenance == "observed"
    assert output.payload.capture_verified is False and output.payload.independent_balance_verified is False
    with pytest.raises(SourcePipelineError, match="^cancelled$"):
        build_source_evidence(source, DEFINITION, suffix=".pdf", cancelled=lambda: True)


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


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({4: "01/15/2026 Payment Received -$200.00 = -$220.00"}, "unresolved_history_row"),
        ({4: "01/15/2026 Payment Received -$200.00 -$20.00 ="}, "unresolved_history_row"),
        ({4: "02/01/2026 Payment Received -$200.00 -$20.00 = -$220.00"}, "history_row_outside_period"),
        ({7: "Account Number: 9876543210987"}, "missing_or_ambiguous_account"),
        ({7: "Principal Balance: $9,500.00"}, "missing_or_ambiguous_history_fields"),
    ],
)
def test_incomplete_or_ambiguous_printed_facts_refuse(changes, error) -> None:
    with pytest.raises(LoanHistoryError, match=f"^{error}$"):
        parse_loan_history(DEFINITION, lines(changes=changes))


def test_finite_definition_schema_and_unknown_field() -> None:
    assert LoanHistoryDefinition.model_validate_json(DEFINITION).operation == "printed_loan_history_components_v1"
    saved = json.loads(Path(__file__).with_name("loan-history-declaration-schema-v1.json").read_text())
    assert saved == LoanHistoryDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(LoanHistoryError, match="invalid_definition"):
        parse_loan_history(json.dumps(raw).encode(), lines())

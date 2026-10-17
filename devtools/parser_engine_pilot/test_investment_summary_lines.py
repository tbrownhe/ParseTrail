"""Account-value summaries remain period components rather than dated activity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_pdf_lines import page_lines

from devtools.parser_engine_pilot.investment_summary_lines import (
    InvestmentSummaryDefinition,
    InvestmentSummaryError,
    parse_investment_summary,
)

DEFINITION = Path(__file__).with_name("fidelity-hsa-summary-pilot-definition.json").read_bytes()


def lines(changes: dict[int, str] | None = None):
    source = [
        "INVESTMENT REPORT",
        "January 1, 2026 - January 31, 2026",
        "Fidelity Health Savings Account",
        "Account Number: 123-456789",
        "Your Account Value: $145.00",
        "This Period Year-to-Date",
        "Beginning Account Value $100.00 -",
        "Additions 50.00 50.00",
        "Subtractions -10.00 -10.00",
        "Change in Investment Value * 5.00 5.00",
        "Ending Account Value ** $145.00 $145.00",
        "Accrued Interest (AI) $0.10",
        "Ending Account Value Incl. AI $145.10",
        "Contact Information",
    ]
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    return page_lines(b"%PDF-synthetic", ["\n".join(source)], extraction_library="synthetic-pdf-1")


def test_summary_rows_have_honest_role_date_and_printed_equation() -> None:
    output = parse_investment_summary(DEFINITION, lines())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    account = output.payload.accounts[0]
    assert account.balance_scope == "account_total"
    assert account.source_identity == "123-456789" and account.source_identity_form == "full"
    assert (account.opening.minor, account.closing.minor) == (10000, 14500)
    assert [row.amount.minor for row in account.rows] == [5000, -1000, 500]
    assert all(row.row_role == "period_summary" for row in account.rows)
    assert all(row.date_role == "statement_period_end" and row.date.provenance == "derived" for row in account.rows)
    assert all(row.running_balance is None for row in account.rows)
    assert len([item for item in output.payload.dispositions if item.code == "year_to_date_column"]) == 5
    assert len([item for item in output.payload.dispositions if item.code == "summary_window_tail_unclassified"]) == 3


def test_unknown_component_or_wrong_equation_refuses_entire_statement() -> None:
    with pytest.raises(InvestmentSummaryError, match="unresolved_summary_line"):
        parse_investment_summary(DEFINITION, lines({8: "Secret adjustment -10.00 -10.00"}))
    with pytest.raises(InvestmentSummaryError, match="printed_summary_equation"):
        parse_investment_summary(DEFINITION, lines({10: "Ending Account Value ** $144.00 $144.00"}))
    with pytest.raises(InvestmentSummaryError, match="missing_or_ambiguous_closing"):
        parse_investment_summary(DEFINITION, lines({10: "Ending Account Value Incl. AI $145.00"}))


def test_definition_is_finite_and_rejects_duplicate_or_unknown_fields() -> None:
    assert InvestmentSummaryDefinition.model_validate_json(DEFINITION).operation == "printed_account_value_summary_v1"
    saved = json.loads(Path(__file__).with_name("investment-summary-declaration-schema-v1.json").read_text())
    assert saved == InvestmentSummaryDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(InvestmentSummaryError, match="invalid_definition"):
        parse_investment_summary(json.dumps(raw).encode(), lines())
    raw.pop("python_module")
    raw["row_labels"].append("Additions")
    with pytest.raises(InvestmentSummaryError, match="invalid_definition"):
        parse_investment_summary(json.dumps(raw).encode(), lines())

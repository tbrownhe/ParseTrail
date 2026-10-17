"""Retirement value components remain period summaries with located source text."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_transamerica_summary_lines import (
    RetirementSummaryDefinition,
    RetirementSummaryError,
    parse_retirement_summary,
)

DEFINITION = Path(__file__).with_name("transamerica-summary-pilot-definition.json").read_bytes()


def parse(changes: dict[int, str] | None = None):
    source = [
        "for January 1, 2026 - March 31, 2026 types",
        "123456 12345 Transphorm 401(k) Plan $115.00",
        "Beginning Balance $100.00 rate of return",
        "Money In 3 Mo.",
        "Your Contributions $20.00 forecast",
        "Money Out -$10.00",
        "Credits/Fees $0.00",
        "Gain/Loss $5.00 estimated income",
        "Ending Balance $115.00 all accounts",
    ]
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    return parse_retirement_summary(
        DEFINITION,
        page_lines(
            b"%PDF-synthetic-retirement", ["\n".join(source)], extraction_library="pdfplumber-bounded-simple-v1"
        ),
    )


def test_retirement_components_and_parallel_text() -> None:
    output = parse()
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    account = output.payload.accounts[0]
    assert account.source_identity == "123456" and account.source_identity_form == "opaque"
    assert (account.opening.minor, account.closing.minor) == (10000, 11500)
    assert [(row.description.text, row.amount.minor, row.row_role) for row in account.rows] == [
        ("Your Contributions", 2000, "period_summary"),
        ("Money Out", -1000, "period_summary"),
        ("Credits/Fees", 0, "period_summary"),
        ("Gain/Loss", 500, "period_summary"),
    ]
    assert all(row.date.iso == "2026-03-31" and row.date.provenance == "derived" for row in account.rows)
    assert "summary_heading" in {item.code for item in output.payload.dispositions}
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True


def test_unknown_money_and_wrong_equation_refuse() -> None:
    with pytest.raises(RetirementSummaryError, match="unresolved_summary_money"):
        parse({3: "Mystery $12.00"})
    with pytest.raises(RetirementSummaryError, match="printed_summary_equation"):
        parse({8: "Ending Balance $116.00 all accounts"})


def test_declaration_rejects_executable_extension() -> None:
    schema = json.loads(Path(__file__).with_name("transamerica-summary-declaration-schema-v1.json").read_text())
    assert schema == RetirementSummaryDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(RetirementSummaryError, match="invalid_definition"):
        parse_retirement_summary(
            json.dumps(raw).encode(), page_lines(b"synthetic", ["text"], extraction_library="test")
        )

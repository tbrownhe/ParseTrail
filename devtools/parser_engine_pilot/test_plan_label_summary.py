"""Recognized plan labels and repeated periods retain source value summaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_single_column_summary import (
    PlanLabelSummaryDefinition,
    SingleColumnSummaryError,
    parse_plan_label_summary,
)

DEFINITION = Path(__file__).with_name("fidelity-401k-summary-pilot-definition.json").read_bytes()


def lines(*, variant: str = "printed", changes: dict[int, str] | None = None):
    header = {
        "printed": ["Statement Details", "My Retirement Plan", "Retirement Savings Statement"],
        "headerless": ["My Retirement Plan", "Retirement Savings Statement"],
        "browser": ["Fidelity NetBenefits - SOD detail page", "My Retirement Plan", "Retirement Savings Statement"],
    }[variant]
    source = [
        *header,
        "Your Account Summary Statement Period: 01/01/2026 to 01/31/2026",
        "Beginning Balance $100.00",
        "Your Contributions $50.00",
        "",
        "Change in Market Value -$10.00",
        "Ending Balance $140.00",
        "Your Asset Allocation Statement Period: 01/01/2026 to 01/31/2026",
        "Beginning Balance $80.00",
        "Ending Balance $80.00",
    ]
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    return page_lines(b"%PDF-synthetic", ["\n".join(source)], extraction_library="synthetic-pdf-1")


@pytest.mark.parametrize("variant", ["printed", "headerless", "browser"])
def test_plan_label_variants_and_first_summary(variant: str) -> None:
    output = parse_plan_label_summary(DEFINITION, lines(variant=variant))
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    account = output.payload.accounts[0]
    assert account.source_identity == "My Retirement Plan" and account.source_identity_form == "opaque"
    assert (account.opening.minor, account.closing.minor) == (10000, 14000)
    assert [row.amount.minor for row in account.rows] == [5000, -1000]
    assert all(row.row_role == "period_summary" and row.date_role == "statement_period_end" for row in account.rows)
    assert len(output.payload.dispositions) == 1


def test_conflicting_repeated_period_or_unknown_summary_line_refuses_source() -> None:
    with pytest.raises(SingleColumnSummaryError, match="missing_or_ambiguous_period"):
        parse_plan_label_summary(
            DEFINITION, lines(changes={9: "Your Asset Allocation Statement Period: 02/01/2026 to 02/28/2026"})
        )
    with pytest.raises(SingleColumnSummaryError, match="unresolved_summary_line"):
        parse_plan_label_summary(DEFINITION, lines(changes={5: "Unknown adjustment $50.00"}))


def test_definition_schema_and_unknown_field() -> None:
    assert PlanLabelSummaryDefinition.model_validate_json(DEFINITION).operation == "plan_label_value_summary_v1"
    saved = json.loads(Path(__file__).with_name("plan-label-summary-declaration-schema-v1.json").read_text())
    assert saved == PlanLabelSummaryDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(SingleColumnSummaryError, match="invalid_definition"):
        parse_plan_label_summary(json.dumps(raw).encode(), lines())

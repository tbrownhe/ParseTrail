"""OCCU bank period precedence and two independent running balance chains."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_bounded_pdf_annotations import PDFPeriodAnnotation
from parsetrail.core.v2_occu_bank_lines import OccuBankDefinition, OccuBankError, parse_occu_bank
from parsetrail.core.v2_pdf_lines import page_lines

DEFINITION = Path(__file__).with_name("occu-bank-pilot-definition.json").read_bytes()
ANNOTATIONS = (
    PDFPeriodAnnotation("FROM_DATE", "FROM_DATE", "01/01/26", 2),
    PDFPeriodAnnotation("TO_DATE", "TO_DATE", "01/31/26", 3),
)


def lines(*, annotation: bool = False, changes: dict[int, str] | None = None):
    source = [
        "FROM" if annotation else "FROM 01/01/26",
        "TO" if annotation else "TO 01/31/26",
        "XXXXXX1234 - PRIMARY SAVINGS .",
        "Previous Balance.................... $100.00",
        "Ending Balance...................... $110.00",
        "01/05 Deposit $10.00 $110.00",
        "XXXXXX5678 - REMARKABLE CHECKING .",
        "Previous Balance.................... $200.00",
        "Ending Balance...................... $195.00",
        "01/10 # Payment ($5.00) $195.00",
        "01/12 # Inquiry ATM Balance $195.00",
        "PERSONAL CREDIT LINE-XXXXXX9999 .",
    ]
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    return page_lines(b"%PDF-synthetic", ["\n".join(source)], extraction_library="pdfplumber-bounded-simple-v1")


def test_text_period_and_separate_account_balances() -> None:
    output = parse_occu_bank(DEFINITION, lines())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    assert (output.payload.start.iso, output.payload.end.iso) == ("2026-01-01", "2026-01-31")
    savings, checking = output.payload.accounts
    assert (savings.source_identity, checking.source_identity) == ("1234", "5678")
    assert [(a.opening.minor, a.closing.minor) for a in (savings, checking)] == [(10000, 11000), (20000, 19500)]
    assert [(r.amount.minor, r.running_balance.minor) for a in (savings, checking) for r in a.rows] == [
        (1000, 11000),
        (-500, 19500),
    ]
    assert {d.code for d in output.payload.dispositions} == {"atm_balance_inquiry", "other_account_section"}


def test_annotation_fallback_retains_first_page_ordinals() -> None:
    output = parse_occu_bank(DEFINITION, lines(annotation=True), ANNOTATIONS)
    assert [
        (value.locations[0].kind, value.locations[0].ordinal) for value in (output.payload.start, output.payload.end)
    ] == [
        ("pdf_annotation", 2),
        ("pdf_annotation", 3),
    ]
    with pytest.raises(OccuBankError, match="missing_annotation_period"):
        parse_occu_bank(DEFINITION, lines(annotation=True))
    with pytest.raises(OccuBankError, match="unexpected_annotation_fallback"):
        parse_occu_bank(DEFINITION, lines(), ANNOTATIONS)


def test_unresolved_or_broken_financial_row_refuses() -> None:
    with pytest.raises(OccuBankError, match="printed_running_balance_chain"):
        parse_occu_bank(DEFINITION, lines(changes={9: "01/10 # Payment ($6.00) $195.00"}))
    with pytest.raises(OccuBankError, match="unresolved_dated_line"):
        parse_occu_bank(DEFINITION, lines(changes={9: "01/10 # Payment $5.00"}))
    with pytest.raises(OccuBankError, match="partial_text_period"):
        parse_occu_bank(DEFINITION, lines(changes={1: "TO"}))


def test_definition_is_strict() -> None:
    assert OccuBankDefinition.model_validate_json(DEFINITION).operation == "two_account_running_bank_v1"
    schema = json.loads(Path(__file__).with_name("occu-bank-declaration-schema-v1.json").read_text())
    assert schema == OccuBankDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(OccuBankError, match="invalid_definition"):
        parse_occu_bank(json.dumps(raw).encode(), lines())

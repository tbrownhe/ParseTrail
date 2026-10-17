"""Wells loan allocations retain source rows and an unknown period start."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_wells_loan_lines import WellsLoanDefinition, WellsLoanError, parse_wells_loan

DEFINITION = Path(__file__).with_name("wells-loan-pilot-definition.json").read_bytes()


def lines(changes: dict[int, str] | None = None):
    source = [
        "Account Number 12345678901234",
        "Account Number 12345678901234",
        "Statement Date 01/31/26",
        "Prior Principal Balance $100.00",
        "01/15/26 INTEREST PAYMENT $1.00",
        "01/15/26 PRINCIPAL PAYMENT $20.00",
        "01/31/26 Ending Principal Balance $80.00*",
    ]
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    return page_lines(b"%PDF-synthetic-loan", ["\n".join(source)], extraction_library="pdfplumber-bounded-simple-v1")


def parse(changes: dict[int, str] | None = None):
    return parse_wells_loan(DEFINITION, lines(changes))


def test_printed_principal_chain_preserves_interest_and_unknown_start() -> None:
    output = parse()
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.start.iso is None and output.payload.start.provenance == "unknown"
    assert output.payload.end.iso == "2026-01-31"
    account = output.payload.accounts[0]
    assert account.balance_scope == "principal_component"
    assert (account.opening.minor, account.closing.minor) == (-10000, -8000)
    assert [(row.description.text, row.amount.minor, row.components[0].role) for row in account.rows] == [
        ("INTEREST PAYMENT", 100, "interest"),
        ("PRINCIPAL PAYMENT", 2000, "principal"),
    ]
    assert all(row.date_role == "activity_date" for row in account.rows)
    assert output.payload.independent_balance_verified
    assert output.payload.dispositions[0].code == "repeated_account_identity"


def test_no_payment_does_not_invent_origination() -> None:
    output = parse({4: "", 5: "", 6: "01/31/26 Ending Principal Balance $100.00*"})
    assert output.payload.accounts[0].rows == ()
    assert output.payload.accounts[0].opening.minor == output.payload.accounts[0].closing.minor
    with pytest.raises(WellsLoanError, match="printed_principal_equation"):
        parse({5: "01/15/26 PRINCIPAL PAYMENT $21.00"})
    with pytest.raises(WellsLoanError, match="unresolved_dated_loan_row"):
        parse({4: "01/15/26 UNKNOWN $1.00"})


def test_declaration_rejects_executable_extension() -> None:
    schema = json.loads(Path(__file__).with_name("wells-loan-declaration-schema-v1.json").read_text())
    assert schema == WellsLoanDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(WellsLoanError, match="invalid_definition"):
        parse_wells_loan(json.dumps(raw).encode(), lines())

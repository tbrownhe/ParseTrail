"""Wells loan allocations retain source rows and an unknown period start."""

from __future__ import annotations

import hashlib
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


def empty_register_lines(*, extra=(), change=None):
    raw = [
        "Account Number 12345678901234",
        "Statement Date 01/31/26",
        "Effective Transaction Principal",
        "Date Description Amount Balance",
        "Prior Principal Balance $100.00",
        "Service.",
        "No transactions within this billing cycle.",
        "01/31/26 Ending Principal Balance $100.00*",
        *extra,
    ]
    if change is not None:
        raw = change(raw)
    return page_lines(b"%PDF-synthetic-empty-loan", ["\n".join(raw)], extraction_library="pdfplumber-bounded-simple-v1")


def test_explicit_empty_register_has_located_proof_and_unknown_period_start():
    from parsetrail.core.v2_import_warnings import evidence_import_warnings

    source = empty_register_lines()
    output = parse_wells_loan(DEFINITION, source)
    assert output.engine_version == "wells-loan-lines-pilot-2"
    assert output.payload.accounts[0].rows == ()
    assert output.payload.start.iso is None and output.payload.start.provenance == "unknown"
    assert output.payload.independent_balance_verified and not output.payload.capture_verified
    proof = next(d for d in output.payload.dispositions if d.code == "wells_loan_empty_register")
    assert (proof.location.line, proof.location.end_line) == (3, 8)
    assert proof.raw_values == tuple(line.raw for line in source.lines[2:])
    warnings = evidence_import_warnings(output)
    assert next(w for w in warnings if w.code == "no_activity_captured").classification == "informational"
    assert any(w.code == "source_period_unknown" for w in warnings)
    assert not [w for w in warnings if w.classification == "requires_review"]


@pytest.mark.parametrize(
    "extra",
    [
        "Unknown $2.00",
        "Unknown €2",
        "01/20/26 unknown activity",
        "20 November 2025 unknown activity",
        "20Nov2025 unknown activity",
        "November 20, 2025 unknown activity",
        "2025 November 20 unknown activity",
        "01/20/2026 unknown activity",
        "Total of Payments Received Since the Last Statement: $0.00 Unknown $3.00",
        "On or after 02/30/2026, a late charge of $5.00 may apply.",
    ],
)
def test_explicit_empty_register_does_not_hide_unknown_exterior_money_or_dates(extra):
    from parsetrail.core.v2_import_warnings import evidence_import_warnings

    output = parse_wells_loan(DEFINITION, empty_register_lines(extra=(extra,)))
    assert output.payload.accounts[0].rows == ()
    assert any(w.classification == "requires_review" for w in evidence_import_warnings(output))
    assert output.payload.dispositions[-1].code == "wells_loan_empty_exterior_unclassified"


@pytest.mark.parametrize(
    "change",
    [
        lambda raw: [line for line in raw if line != "No transactions within this billing cycle."],
        lambda raw: [line for line in raw if line != "Effective Transaction Principal"],
        lambda raw: [line for line in raw if line != "Date Description Amount Balance"],
        lambda raw: [line.replace("Service.", "Unknown $2.00") for line in raw],
        lambda raw: [
            line.replace("Prior Principal Balance $100.00", "Prior Principal Balance $100.00 Unknown $2.00")
            for line in raw
        ],
        lambda raw: [line.replace("$100.00*", "$100.00* Unknown $2.00") for line in raw],
    ],
)
def test_zero_capture_and_equal_endpoints_do_not_establish_complete_register(change):
    from parsetrail.core.v2_import_warnings import evidence_import_warnings

    output = parse_wells_loan(DEFINITION, empty_register_lines(change=change))
    assert output.payload.accounts[0].rows == ()
    assert (
        next(w for w in evidence_import_warnings(output) if w.code == "no_activity_captured").classification
        == "requires_review"
    )


def test_complete_coupon_and_quoted_auxiliary_dates_do_not_become_activity():
    from parsetrail.core.v2_import_warnings import evidence_import_warnings

    context = (
        "Total of Payments Received Since the Last Statement: $0.00",
        "For questions *Your account is on automatic payment. Your Payment Due Date 02/15/2026",
        "Bank This automatic payment of $20.00 will be Account Number 12345678901234",
        "withdrawn from your account on 02/15/2026. Total",
        "Amount Due under your agreement Total Amount Due $20.00",
        "On or after 02/20/2026, a late charge of $5.00 may apply.",
    )
    output = parse_wells_loan(DEFINITION, empty_register_lines(extra=context))
    assert not [w for w in evidence_import_warnings(output) if w.classification == "requires_review"]
    assert output.payload.accounts[0].rows == ()
    for malformed in (
        context[:2] + context[3:],
        tuple(line.replace("02/15/2026", "02/30/2026") for line in context),
        tuple(line.replace("will be Account", "will be Unknown $9.00 Account") for line in context),
    ):
        changed = parse_wells_loan(DEFINITION, empty_register_lines(extra=malformed))
        assert any(w.classification == "requires_review" for w in evidence_import_warnings(changed))
    wrong_account = tuple(
        line.replace("Account Number 12345678901234", "Account Number 99999999999999") for line in context
    )
    with pytest.raises(WellsLoanError, match="missing_or_ambiguous_account"):
        parse_wells_loan(DEFINITION, empty_register_lines(extra=wrong_account))


def test_new_source_role_engine_preserves_financial_row_identifiers():
    output, source = parse(), lines()
    assert output.engine_version == "wells-loan-lines-pilot-2"
    for row, line in zip(output.payload.accounts[0].rows, source.lines[4:6], strict=True):
        expected = hashlib.sha256(
            f"{output.definition_sha256}:wells-loan-lines-pilot-1:{line.line_id}".encode()
        ).hexdigest()
        assert row.row_id == expected

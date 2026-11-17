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


def test_exterior_inventory_keeps_known_fields_and_every_extracted_line_without_certifying_capture() -> None:
    source = lines()
    output = parse_loan_history(DEFINITION, source)
    assert output.engine_version == "loan-history-lines-pilot-2"
    assert output.payload.capture_verified is False and output.payload.independent_balance_verified is False
    captured = {
        (fragment.location.page, fragment.location.line): fragment.raw_values
        for row in output.payload.accounts[0].rows
        for fragment in row.fragments
    }
    captured.update({(item.location.page, item.location.line): item.raw_values for item in output.payload.dispositions})
    assert captured == {(line.page, line.line): (line.raw,) for line in source.lines}
    payment = next(item for item in output.payload.dispositions if item.code == "loan_payment_information")
    assert payment.raw_values == ("Current Payment Due: $300.00 Principal Balance: $9,500.00",)
    assert not {item.code for item in output.payload.dispositions} & {"unclassified_monetary_line", "dated_unresolved"}


@pytest.mark.parametrize(
    "index,replacement,code",
    [
        (7, "01/16/2026 Payment Received -$100.00 -$10.00 = -$110.00", "unclassified_monetary_line"),
        (7, "Unclassified $2.00", "unclassified_monetary_line"),
        (7, "Unclassified 2.00", "unclassified_monetary_line"),
        (7, "Unclassified $", "unclassified_monetary_line"),
        (7, "Unclassified \u20ac2.00", "unclassified_monetary_line"),
        (7, "Other activity 01/16/2026", "dated_unresolved"),
        (7, "Other activity 2026-01-16", "dated_unresolved"),
        (0, "Account Number: 1234567890123 Unclassified $2.00", "unclassified_monetary_line"),
        (0, "Unclassified $2.00 Account Number: 1234567890123", "unclassified_monetary_line"),
        (
            1,
            "Current Payment Due: $300.00 Principal Balance: $9,500.00 Unclassified $2.00",
            "unclassified_monetary_line",
        ),
        (1, "Current Payment Due: $300.000 Principal Balance: $9,500.00", "unclassified_monetary_line"),
        (1, "Current Payment Due: $300.00x Principal Balance: $9,500.00", "unclassified_monetary_line"),
        (1, "Current Payment Due: $300.00 Other date 01/16/2026 Principal Balance: $9,500.00", "dated_unresolved"),
    ],
)
def test_exterior_residual_money_and_dates_are_located_unresolved_evidence(index, replacement, code) -> None:
    source = lines(changes={index: replacement})
    output = parse_loan_history(DEFINITION, source)
    unresolved = [item for item in output.payload.dispositions if item.code == code]
    assert len(unresolved) == 1
    assert unresolved[0].raw_values == (replacement,)
    assert (unresolved[0].location.page, unresolved[0].location.line) == (1, index + 1)
    account = output.payload.accounts[0]
    assert account.opening is None and account.closing.minor == 950000
    assert len(account.rows) == 1 and account.rows[0].amount.minor == -22000


@pytest.mark.parametrize(
    "replacement,error",
    [
        ("Account Number: 1234567890123 Account Number: 9876543210987", "missing_or_ambiguous_account"),
        ("Principal Balance: $9,500.00 Principal Balance: $9,000.00", "missing_or_ambiguous_history_fields"),
    ],
)
def test_multiple_fields_on_one_line_cannot_hide_another_identity_or_endpoint(replacement, error) -> None:
    with pytest.raises(LoanHistoryError, match=f"^{error}$"):
        parse_loan_history(DEFINITION, lines(changes={7: replacement}))


@pytest.mark.parametrize("suffix", [".1", ",1", "0", "x"])
def test_malformed_closing_token_is_not_consumed_as_a_printed_prefix(suffix) -> None:
    with pytest.raises(LoanHistoryError, match="^missing_or_ambiguous_history_fields$"):
        parse_loan_history(
            DEFINITION, lines(changes={1: "Current Payment Due: $300.00 Principal Balance: $9,500.00" + suffix})
        )


@pytest.mark.parametrize(
    "source_field,role",
    [
        ("Statement Date: 01/31/2026", "loan_statement_dates"),
        ("Payment Due Date: 02/15/2026", "loan_statement_dates"),
        ("Due Date: 02/15/2026", "loan_statement_dates"),
        ("Payoff Good Through: 02/15/2026", "loan_statement_dates"),
        ("Past Due: $0.00", "loan_payment_information"),
        ("Late Fees: $5.00", "loan_payment_information"),
        ("Total Due: $305.00", "loan_payment_information"),
        ("Payoff Amount: $9,600.00", "loan_account_summary"),
        ("Amount Enclosed: $", "loan_coupon_information"),
        ("Mailing region 12345 Amount Enclosed: $", "loan_coupon_information"),
        ("1. Payoff Amount: The quote may include accrued charges.", "loan_page_text"),
        ("2. Late Fees: Charges may apply to a late payment.", "loan_page_text"),
        ("Telephone payments available 24/7", "loan_page_text"),
    ],
)
def test_finite_exterior_summary_dates_and_blank_coupon_are_nonactivity_source_roles(source_field, role) -> None:
    output = parse_loan_history(DEFINITION, lines(changes={7: source_field}))
    disposition = next(item for item in output.payload.dispositions if item.location.line == 8)
    assert disposition.code == role and disposition.raw_values == (source_field,)
    account = output.payload.accounts[0]
    assert account.opening is None and account.closing.minor == 950000
    assert len(account.rows) == 1 and account.rows[0].amount.minor == -22000
    assert output.payload.capture_verified is False and output.payload.independent_balance_verified is False


@pytest.mark.parametrize(
    "source_field",
    [
        "Statement Date: 01/31/2026",
        "Past Due: $0.00",
        "Late Fees: $5.00",
        "Total Due: $305.00",
        "Payoff Amount: $9,600.00",
        "Payoff Good Through: 02/15/2026",
        "Due Date: 02/15/2026",
        "Amount Enclosed: $",
        "Mailing region 12345 Amount Enclosed: $",
        "1. Payoff Amount: The quote may include accrued charges.",
        "2. Late Fees: Charges may apply to a late payment.",
    ],
)
@pytest.mark.parametrize("suffix", [" Unknown $1.00", " Unknown activity 01/16/2026"])
def test_known_exterior_fields_never_consume_appended_unknown_money_or_dates(source_field, suffix) -> None:
    output = parse_loan_history(DEFINITION, lines(changes={7: source_field + suffix}))
    disposition = next(item for item in output.payload.dispositions if item.location.line == 8)
    assert disposition.code in {"unclassified_monetary_line", "dated_unresolved"}
    assert disposition.raw_values == (source_field + suffix,)


@pytest.mark.parametrize(
    "source_field,code",
    [
        ("Past Due: $300.00.1", "unclassified_monetary_line"),
        ("Past Due: $300.00,1", "unclassified_monetary_line"),
        ("Payoff Amount: $300.000", "unclassified_monetary_line"),
        ("Total Due: 300", "unclassified_monetary_line"),
        ("Amount Enclosed: $300", "unclassified_monetary_line"),
        ("Amount Enclosed: $300.00", "unclassified_monetary_line"),
        ("Amount Enclosed: 300", "unclassified_monetary_line"),
        ("Statement Date: 01/31/2026.1", "dated_unresolved"),
        ("Payment Due Date: 02/30/2026", "dated_unresolved"),
        ("Due Date: 24/77", "dated_unresolved"),
        ("Payoff Good Through:", "dated_unresolved"),
    ],
)
def test_malformed_known_exterior_fields_and_filled_coupon_remain_unresolved(source_field, code) -> None:
    output = parse_loan_history(DEFINITION, lines(changes={7: source_field}))
    disposition = next(item for item in output.payload.dispositions if item.location.line == 8)
    assert disposition.code == code and disposition.raw_values == (source_field,)


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

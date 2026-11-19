"""Wells business table cells become scoped, located statement evidence."""

from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_wells_statement_output import WellsStatementError, from_wells_business
from parsetrail.core.v2_wells_table import extract_table_rows

from devtools.parser_engine_pilot.test_wells_table import FakePage, cells

DEFINITION = Path(__file__).with_name("wells-table-pilot-definition.json").read_bytes()
SOURCE = b"%PDF-synthetic"


def statement_text() -> list[str]:
    return [
        "\n".join(
            (
                "October 31, 2026 Page 1 of 1",
                "Statement period activity summary Account number: 1234567890",
                "Beginning balance on 10/1 $100.00",
                "Ending balance on 10/31 $101.00",
            )
        )
    ]


def table_cells() -> list[list[str | None]]:
    result = cells()
    result[0][0] = "10/1"
    return result


def build(values: list[list[str | None]] | None = None, *, text: list[str] | None = None):
    table = extract_table_rows(
        DEFINITION,
        SOURCE,
        [FakePage(values if values is not None else table_cells())],
        extraction_library="synthetic-pdf-1",
    )
    lines = page_lines(SOURCE, text if text is not None else statement_text(), extraction_library="synthetic-pdf-1")
    return from_wells_business(DEFINITION, table, lines)


def test_printed_balance_and_continuation_round_trip() -> None:
    output = build()
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.start.iso == "2026-10-01" and output.payload.start.provenance == "derived"
    assert output.payload.end.iso == "2026-10-31" and output.payload.end.provenance == "observed"
    account = output.payload.accounts[0]
    assert account.balance_scope == "account_total"
    assert (account.opening.minor, account.closing.minor) == (10000, 10100)
    assert len(account.rows) == 1
    assert account.rows[0].description.text == "Printed description continuation"
    assert len(account.rows[0].fragments) == 2
    assert account.rows[0].running_balance.minor == 10100
    assert len(output.payload.dispositions) == 2
    assert output.payload.independent_balance_verified is True
    assert output.payload.capture_verified is False


def test_wrong_printed_running_balance_refuses_statement() -> None:
    values = table_cells()
    values[0][5] = "$102.00"
    with pytest.raises(WellsStatementError, match="printed_running_mismatch"):
        build(values)


def footer_cells():
    return table_cells()[:3] + [
        ["Endi", "ng balance on 10/31", "", "", "", "101.00"],
        ["Total", "s", "$1.", "00", "$0.00", ""],
        ["hly se", "rvice fee summar", "y", "", "", ""],
        ["Fee p", "eriod 10/01/2026 - 10/31/2026 Standard monthly service fee $0.00 You paid $0.00", "", "", "", ""],
        ["How", "to avoid the monthly service fee Minimum", "require", "d This", "fee period", ""],
        ["Have", "any ONE of the following account requirements", "", "", "", ""],
        ["• A", "verage ledger balan", "ce", "$1,000.0", "0", "$101.00"],
        ["•", "Minimum daily balan", "ce", "$100.0", "0", "$100.00"],
        ["C1/C2", "", "", "", "", ""],
        ["ount", "transaction fees summary", "", "", "", ""],
        ["", "", "Units Excess", "Servic", "e charge per", "Total service"],
        ["Servic", "e charge description", "Units used included units", "ex", "cess units ($)", "charge ($)"],
        ["Cash", "Deposited ($)", "0 1,000 0", "", "0.0000", "0.00"],
        ["Trans", "actions", "1 100 0", "", "0.00", "0.00"],
        ["Total", "service charges", "", "", "", "$0.00"],
    ]


def footer_text():
    return [statement_text()[0] + "\nMonthly service fee summary\nAccount transaction fees summary"]


def test_finite_footer_cells_retain_locations_values_and_activity_count():
    values = footer_cells()
    output = build(values, text=footer_text())
    assert output.engine_version == "wells-table-pilot-2+statement-v3"
    assert len(output.payload.accounts[0].rows) == 1
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    dispositions = output.payload.dispositions
    assert not [d for d in dispositions if d.code == "unresolved_after_stop"]
    assert {d.code for d in dispositions} == {
        "wells_non_activity_blank",
        "wells_statement_summary",
        "wells_service_fee_information",
        "wells_transaction_fee_information",
    }
    for d in dispositions:
        assert d.raw_values == tuple(cell or "" for cell in values[d.location.row - 1])
        assert d.location.region is not None


@pytest.mark.parametrize(
    "index,replacement",
    [
        (3, ["Endi", "ng balance on 10/31", "", "", "", "102.00"]),
        (4, ["Totals", "", "$1.00", "$0.00", "$9", ""]),
        (
            6,
            [
                "Fee p",
                "eriod 10/99/2026 - 10/31/2026 Standard monthly service fee $0.00 You paid $0.00",
                "",
                "",
                "",
                "",
            ],
        ),
        (9, ["• Average ledger balance", "", "", "$1000.00", "$9", "$101.00"]),
        (17, ["Total service charges", "", "", "", "", "$1.00"]),
    ],
)
def test_unknown_truncated_or_mismatched_footer_money_remains_unresolved(index, replacement):
    values = footer_cells()
    values[index] = replacement
    output = build(values, text=footer_text())
    disposition = next(d for d in output.payload.dispositions if d.location.row == index + 1)
    assert disposition.code == "unresolved_after_stop"
    assert disposition.raw_values == tuple(replacement)
    assert len(output.payload.accounts[0].rows) == 1


def test_fee_tables_need_printed_headings_and_extra_occurrences_stay_unknown():
    values = footer_cells()
    output = build(values)
    assert any(d.code == "unresolved_after_stop" for d in output.payload.dispositions)
    values += [["Unknown adjustment", "", "$9.00", "", "", ""]] * 2
    output = build(values, text=footer_text())
    assert [d.code for d in output.payload.dispositions[-2:]] == ["unresolved_after_stop"] * 2
    assert output.payload.dispositions[-2].location != output.payload.dispositions[-1].location


@pytest.mark.parametrize("heading", ["Initiate Business Checking SM ", "Business Market Rate Savings"])
def test_single_finite_product_heading_is_located_source_evidence(heading):
    text = [heading + "\n" + statement_text()[0]]
    output = build(text=text)
    product = next(d for d in output.payload.dispositions if d.code == "wells_account_product")
    assert product.raw_values == (heading,)
    assert (product.location.page, product.location.line) == (1, 1)
    for extra in (heading, "Unsupported Product", "Business Market Rate Savings"):
        altered = [heading + " " + extra + "\n" + statement_text()[0]]
        assert not [d for d in build(text=altered).payload.dispositions if d.code == "wells_account_product"]

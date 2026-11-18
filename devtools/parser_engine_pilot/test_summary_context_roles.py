"""Public synthetic chart and footnote source roles have finite boundaries."""

from __future__ import annotations

import pytest
from parsetrail.core.v2_import_warnings import evidence_import_warnings
from parsetrail.core.v2_investment_summary_lines import parse_investment_summary
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_single_column_summary import parse_single_column_summary

from devtools.parser_engine_pilot.test_investment_summary_lines import DEFINITION as HSA_DEFINITION
from devtools.parser_engine_pilot.test_investment_summary_lines import lines as hsa_lines
from devtools.parser_engine_pilot.test_single_column_summary import DEFINITION as VAN_DEFINITION


def chart_source_lines() -> list[str]:
    """A complete adjacent chart frame; amounts and identity are invented."""
    return [
        "ACCOUNT SUMMARY: 01/01/2026 - 03/31/2026",
        "EMPLOYEES 123456",
        "Your account summary",
        "Account Balance Your account progress",
        "Statement period",
        "$2,000",
        "Beginning balance $100.00",
        "Your contributions $50.00 $1,500",
        "$1,000",
        "Employer contributions $25.00",
        "Market gain/loss -$5.00 $500",
        "Other transactions $0.00",
        "Ending balance $170.00",
        "$0",
    ]


def chart_lines(changes=None, extra=()):
    source = chart_source_lines()
    for index, replacement in (changes or {}).items():
        source[index] = replacement
    source[10:10] = extra
    return page_lines(b"synthetic-chart", ["\n".join(source)], extraction_library="synthetic-pdf-1")


def review_codes(evidence):
    return {item.code for item in evidence_import_warnings(evidence) if item.classification == "requires_review"}


def test_complete_chart_axis_is_retained_without_changing_summary_values():
    output = parse_single_column_summary(VAN_DEFINITION, chart_lines())
    assert not review_codes(output)
    axis = [item for item in output.payload.dispositions if item.code == "summary_chart_axis"]
    assert [(item.location.line, item.raw_values) for item in axis] == [
        (6, ("$2,000",)),
        (14, ("$0",)),
        (8, ("Your contributions $50.00 $1,500",)),
        (9, ("$1,000",)),
        (11, ("Market gain/loss -$5.00 $500",)),
    ]
    account = output.payload.accounts[0]
    assert [row.amount.minor for row in account.rows] == [5000, 2500, -500, 0]
    assert (account.opening.minor, account.closing.minor) == (10000, 17000)
    assert output.payload.independent_balance_verified and not output.payload.capture_verified


@pytest.mark.parametrize("changes", [{3: "Account Balance"}, {5: ""}, {8: "$900"}, {8: "$1,000.00"}, {13: "$500"}])
def test_missing_or_malformed_chart_frame_does_not_rescue_money(changes):
    output = parse_single_column_summary(VAN_DEFINITION, chart_lines(changes))
    assert "summary_window_unclassified" in review_codes(output)


def test_other_money_inside_a_valid_chart_frame_is_not_suppressed():
    output = parse_single_column_summary(VAN_DEFINITION, chart_lines(extra=("Unknown amount $9.00",)))
    assert "summary_window_unclassified" in review_codes(output)
    assert any(item.raw_values == ("Unknown amount $9.00",) for item in output.payload.dispositions)


@pytest.mark.parametrize("tail", ["Unknown amount $9.00 $1,500", "01/20/2026 unexpected activity $1,500"])
def test_other_money_or_date_on_a_chart_tick_tail_remains_reviewable(tail):
    output = parse_single_column_summary(VAN_DEFINITION, chart_lines({7: "Your contributions $50.00 " + tail}))
    assert "summary_extra_column" in review_codes(output)
    assert any(item.raw_values == (tail,) for item in output.payload.dispositions)


@pytest.mark.parametrize(
    "changes",
    [
        {5: "Unknown amount $2,000"},
        {13: "01/20/2026 Unknown $0"},
        {13: "*May include unknown fees $0"},
    ],
)
def test_unproved_outer_tick_labels_cannot_establish_the_chart_frame(changes):
    output = parse_single_column_summary(VAN_DEFINITION, chart_lines(changes))
    assert "summary_window_unclassified" in review_codes(output)


def test_exact_public_chart_footnote_can_share_the_last_axis_tick():
    source = chart_lines({13: "*May include recordkeeping, administrative, or purchase/redemption fees. $0"})
    output = parse_single_column_summary(VAN_DEFINITION, source)
    assert not review_codes(output)


def test_hsa_alternative_valuation_is_retained_separately_from_closing():
    output = parse_investment_summary(HSA_DEFINITION, hsa_lines())
    assert not review_codes(output)
    assert output.payload.accounts[0].closing.minor == 14500
    assert {item.code for item in output.payload.dispositions} >= {
        "summary_accrued_interest",
        "summary_inclusive_value",
        "summary_contact_heading",
    }


@pytest.mark.parametrize(
    "tail",
    [
        {11: "Accrued Interest (AI) $0.11"},
        {11: "Unknown amount $0.10"},
        {11: "Accrued Interest (AI) $0.10 $9.00"},
        {12: "Ending Account Value Incl. AI $145.10 extra"},
        {12: "Accrued Interest (AI) $0.10"},
        {13: "Unknown $7.00"},
    ],
)
def test_hsa_unexplained_or_conflicting_amounts_remain_reviewable(tail):
    assert "summary_window_tail_unclassified" in review_codes(parse_investment_summary(HSA_DEFINITION, hsa_lines(tail)))


def test_anchored_no_money_footnote_and_continuations_are_preserved():
    output = parse_investment_summary(
        HSA_DEFINITION,
        hsa_lines(
            {
                11: "* Reflects changes in your holdings due to price changes.",
                12: "Includes transactions during the statement period.",
                13: "** Additional account value information.",
            }
        ),
    )
    assert not review_codes(output)
    assert len([item for item in output.payload.dispositions if item.code == "summary_explanatory_note"]) == 3
    for replacement in (
        "Unknown text",
        "01/20/2026 unexpected activity",
        "Unknown $7.00",
        "Unknown 7.00",
        "* Unexpected activity January 20, 2026",
        "* Unexpected activity 2026-01-20",
    ):
        changed = parse_investment_summary(HSA_DEFINITION, hsa_lines({11: replacement}))
        assert "summary_window_tail_unclassified" in review_codes(changed)

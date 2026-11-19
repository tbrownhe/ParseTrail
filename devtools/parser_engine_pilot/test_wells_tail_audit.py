"""Public synthetic boundaries for the shared, nonposting Wells footer audit."""

from datetime import date

import pytest
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_wells_dispositions import classify_wells_tail
from parsetrail.core.v2_wells_table import TableRow

PERIOD = "Fee period 11/01/2026 - 11/28/2026 Standard monthly service fee $0.00 You paid $0.00"
HEADER = "How to avoid the monthly service fee Minimum required This fee period"
REQUIREMENTS = "Have any ONE of the following account requirements"
BALANCE = "· Minimum daily balance $100.00 $200.00 3"


def frame(extra=()):
    return ["Monthly service fee summary", PERIOD, HEADER, REQUIREMENTS, BALANCE, *extra]


def audit(printed, cropped=None, *, pages=None, row_pages=None, closing=20000):
    cropped = printed if cropped is None else cropped
    rows = tuple(
        TableRow(
            str(index),
            (row_pages or {}).get(index, 1),
            index + 1,
            (1.0, 2.0, 3.0, 4.0),
            (text, "", "", "", "", ""),
            "unresolved_after_stop",
        )
        for index, text in enumerate(cropped)
    )
    lines = page_lines(b"public-wells-tail", pages or ["\n".join(printed)], extraction_library="synthetic-pdf-1")
    result = classify_wells_tail(
        rows,
        lines,
        closing=closing,
        end=date(2026, 11, 30),
        statement_start=date(2026, 11, 1),
        credits=10000,
        debits=0,
    )
    assert [item.raw_values for item in result] == [row.raw_cells for row in rows]
    assert [item.location.row for item in result] == list(range(1, len(rows) + 1))
    return result


@pytest.mark.parametrize(
    "criterion",
    [
        "· Minimum daily balance $100.00 $50.00 3",
        "· Minimum daily balance $100.00 $50.00 34",
        "· Age of primary account owner 17 - 24 25 3",
        "· Account is linked to a Wells Fargo Campus ATM Card or Campus Debit Card 1 0 3",
        "· Average ledger balance $100.00 $250.00",
        "· Minimum daily balance $100.00 -$5.00",
        "· Total amount of qualifying electronic deposits $500.00 $600.00 3",
        "· Total amount of qualifying direct deposits $500.00 $600.00",
        "· A single automatic transfer from a Wells Fargo checking account $25.00 $50.00 3",
        "· A monthly automatic transfer from a Wells Fargo checking account $25.00 $50.00",
        "· An automatic transfer from a linked Wells Fargo checking account each fee period $1.00 $5.00 3",
        "· Save As You Go® transfer from a Wells Fargo checking account $1.00 $2.00",
        "• Total automatic transfers from an eligible Wells Fargo business checking $100.00 $200.00",
        "· Age of primary account owner 17 - 24 21 3",
        "· Age of account owner 17 - 24",
        # The final raw 3 is ambiguous. It stays uninterpreted auxiliary text; no age
        # or eligibility fact is emitted by the auditor.
        "· Age of account owner 17 - 24 3",
        "· Account is linked to a Wells Fargo Campus ATM Card or Campus Debit Card 1 0",
    ],
)
def test_typed_auxiliary_criteria_require_complete_fee_frame(criterion):
    output = audit(frame((criterion,)))
    assert all(item.code == "wells_service_fee_information" for item in output)


@pytest.mark.parametrize("marker", ["3", "34", "✓", "✔", "√"])
def test_finite_raw_marker_does_not_create_an_eligibility_or_amount_fact(marker):
    text = f"· Minimum daily balance $100.00 $200.00 {marker}"
    output = audit(frame((text,)))
    assert output[-1].code == "wells_service_fee_information"
    assert output[-1].raw_values[0] == text
    assert output[-1].model_dump().keys() == {"code", "location", "raw_values"}


@pytest.mark.parametrize(
    "criterion",
    [
        "· Minimum daily balance $100.00 $200.00 $3",
        "· Minimum daily balance $100.00 $200.00 3.00",
        "· Minimum daily balance $100.00 $200.00 33",
        "· Minimum daily balance $100.00 $200.00 $34",
        "· Minimum daily balance $100.00 $200.00 34.00",
        "· Minimum daily balance $100.00 $200.00 334",
        "· Minimum daily balance $100.00 $200.00 343",
        "· Minimum daily balance $100.00 $200.00 3 4",
        "· Minimum daily balance $100.00 $200.00 4",
        "· Minimum daily balance $100.00 $200.00 3 $9.00",
        "· Minimum daily balance $100.00 $200.00 3 11/29/2026",
        "Unknown adjustment $100.00 $200.00 3",
        "· Minimum daily balance $1000.000 $2,000.00",
        "· Minimum daily balance $90,000,000,000,000.00 $100,000,000,000,000.00",
    ],
)
def test_unknown_extra_malformed_or_unsupported_fields_stay_unresolved(criterion):
    assert audit(frame((criterion,)))[-1].code == "unresolved_after_stop"


@pytest.mark.parametrize("removed", [0, 1, 2, 3])
def test_missing_frame_parts_do_not_authorize_criteria(removed):
    source = frame()
    del source[removed]
    assert audit(source)[-1].code == "unresolved_after_stop"


def test_frame_without_any_supported_criterion_stays_unresolved():
    source = frame()[:-1] + ["Unknown adjustment $1.00"]
    assert all(item.code == "unresolved_after_stop" for item in audit(source))


@pytest.mark.parametrize(
    "period",
    [
        PERIOD.replace("11/28/2026", "12/01/2026"),
        PERIOD.replace("11/28/2026", "11/99/2026"),
        PERIOD.replace("11/01/2026", "01/01/2026"),
        PERIOD.replace("11/28/2026", "10/01/2026"),
        PERIOD + " Unknown $9.00",
        PERIOD.replace("$0.00", "$90,000,000,000,000.01"),
    ],
)
def test_invalid_future_unbounded_or_malformed_auxiliary_period_stays_unresolved(period):
    source = frame()
    source[1] = period
    assert audit(source)[-1].code == "unresolved_after_stop"


def test_auxiliary_fee_period_is_not_required_to_equal_statement_period():
    source = frame()
    assert audit(source)[1].code == "wells_service_fee_information"
    assert "11/28/2026" in audit(source)[1].raw_values[0]


def test_crop_mapping_requires_same_label_full_numeric_inventory_and_semantic_text():
    for replacement in (
        "Unknown adjustment $100.00 $200.00 3",
        "$100.00 $200.00 3",
        BALANCE.replace("$200.00", "$201.00"),
        BALANCE + " Unknown $9.00",
        BALANCE.replace("$200.00", "$200.0"),
    ):
        cropped = frame()
        cropped[-1] = replacement
        assert audit(frame(), cropped)[-1].code == "unresolved_after_stop"
    cropped = frame()
    cropped[0] = "hly service fee summary"
    cropped[-1] = BALANCE[3:]
    assert audit(frame(), cropped)[-1].code == "wells_service_fee_information"


def test_lost_negative_sign_decimal_or_date_punctuation_stays_unknown():
    negative = "· Minimum daily balance $100.00 -$5.00"
    source = frame((negative,))
    cropped = list(source)
    cropped[-1] = negative.replace("-$5.00", "$5.00")
    assert audit(source, cropped)[-1].code == "unresolved_after_stop"
    cropped[-1] = negative.replace("-$5.00", "-$500")
    assert audit(source, cropped)[-1].code == "unresolved_after_stop"
    cropped = frame()
    cropped[1] = PERIOD.replace("11/28/2026", "1128/2026")
    assert audit(frame(), cropped)[1].code == "unresolved_after_stop"


def test_ambiguous_equal_value_source_lines_do_not_authorize_a_crop():
    unbulleted = BALANCE.removeprefix("· ")
    source = frame((unbulleted,))
    cropped = list(source)
    cropped[4] = unbulleted
    assert audit(source, cropped)[4].code == "unresolved_after_stop"


def test_negative_ending_repeat_is_context_only_when_exactly_equal():
    text = "Ending balance on 11/30 -$200.00"
    assert audit([text], closing=-20000)[0].code == "wells_statement_summary"
    assert audit([text], closing=-20001)[0].code == "unresolved_after_stop"
    assert audit([text + " Unknown $9.00"], closing=-20000)[0].code == "unresolved_after_stop"


def test_same_numbers_do_not_cross_section_or_page_boundaries():
    source = frame(("Important account information", BALANCE))
    output = audit(source)
    assert output[-2].code == "wells_statement_context"
    assert output[-1].code == "unresolved_after_stop"
    source = frame()
    output = audit(source, pages=["\n".join(source), "Other content"], row_pages={len(source) - 1: 2})
    assert output[-1].code == "unresolved_after_stop"
    source = frame(("Important account information Unknown $9.00", BALANCE))
    assert audit(source)[-1].code == "unresolved_after_stop"


def test_dated_activity_after_stop_never_inherits_fee_context():
    source = frame()
    source.append("11/12 $100.00 $200.00")
    assert audit(source)[-1].code == "unresolved_after_stop"


def test_control_marker_requires_complete_same_page_fee_frame_and_exact_inventory():
    source = frame(("B1/B2",))
    assert audit(source)[-1].code == "wells_statement_context"
    for changed in ("B1/B2 $9.00", "1/2", "Unknown B1/B2"):
        assert audit(frame((changed,)))[-1].code == "unresolved_after_stop"
    assert audit(["B1/B2"])[-1].code == "unresolved_after_stop"


@pytest.mark.parametrize(
    "paragraph",
    [
        [
            "We waived the fee this fee period to allow you to meet the requirements to avoid the monthly service fee. Your fee waiver is about to expire. You will",
            "need to meet one of the requirements to avoid the monthly service fee.",
        ],
        [
            "The Monthly service fee summary fee period ending date shown above includes a Saturday, Sunday, or holiday which are non-business days.",
            "Transactions occurring after the last business day of the month will be included in your next fee period.",
        ],
    ],
)
def test_complete_fee_prose_needs_its_frame_and_every_sentence(paragraph):
    output = audit(frame(paragraph))
    assert all(item.code == "wells_service_fee_information" for item in output)
    for changed in (paragraph[:1], [paragraph[0], paragraph[1] + " Unknown $9.00"]):
        output = audit(frame(changed))
        assert output[-len(changed)].code == "unresolved_after_stop"
    assert audit(paragraph)[0].code == "unresolved_after_stop"


def test_balance_explanation_needs_complete_public_paragraph_and_no_extra_values():
    paragraph = [
        "The Ending Daily Balance does not reflect any pending withdrawals or holds on deposited funds that may have been outstanding on your account when your",
        "transactions posted. If you had insufficient available funds when a transaction posted, fees may have been assessed.",
    ]
    assert all(item.code == "wells_balance_disclosure" for item in audit(paragraph))
    assert audit(paragraph[:1])[0].code == "unresolved_after_stop"
    altered = [paragraph[0], paragraph[1] + " Unknown $9.00"]
    assert audit(altered)[0].code == "unresolved_after_stop"


def test_contact_notice_needs_complete_public_paragraph_and_typed_phone():
    notice = [
        "NEW YORK CITY CUSTOMERS ONLY -- Pursuant to New York City regulations, we request that you contact us at 1-800-TO WELLS",
        "(1-800-555-0100) to share your language preference.",
    ]
    assert all(item.code == "wells_statement_context" for item in audit(notice))
    for changed in (
        notice[:1],
        [notice[0], notice[1].replace("555-0100", "555-010")],
        [notice[0], notice[1] + " Unknown $9.00"],
        [notice[0], notice[1] + " 11/30/2026"],
    ):
        assert audit(changed)[0].code == "unresolved_after_stop"
    # An isolated phone, even with equal digits, does not gain the paragraph's role.
    assert audit(notice, ["(1-800-555-0100)"])[0].code == "unresolved_after_stop"

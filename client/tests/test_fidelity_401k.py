import pytest
from parsetrail.plugins.pdf_fidelity401k_201810 import Parser


@pytest.mark.parametrize(
    "heading",
    [
        "Statement Details",
        "4/8/2021 Fidelity Netbene\ufb01ts - SOD detail page",
        "Fidelity NetBenefits - SOD detail page",
        "10/9/21, 12:04 PM Fidelity Netbene\ufb01ts - SOD detail page",
    ],
)
def test_recognized_headers_preserve_existing_plan_alias(heading):
    parser = Parser()
    parser.lines = [
        heading,
        "",
        "Example Retirement Savings Plan",
        "Retirement Savings Statement",
        "for Example Employees",
        "SYNTHETIC PERSON Customer Service: 800-000-0000",
    ]
    assert parser.extract_account_number() == "Example Retirement Savings Plan"


def test_plan_lines_above_title_join_without_including_print_header():
    parser = Parser()
    parser.lines = ["Statement Details", "", "Example Company", "Retirement Plan", "Retirement Savings Statement"]
    assert parser.extract_account_number() == "Example Company Retirement Plan"


@pytest.mark.parametrize("heading", [[], ["Statement Details"]])
def test_headerless_or_inline_continuation_preserves_old_account_key(heading):
    parser = Parser()
    parser.lines = [
        *heading,
        "",
        "Example 401(k) and Example",
        "Retirement Contribution Retirement Savings Statement",
        "CUSTOMER NAME AND ADDRESS",
    ]
    assert parser.extract_account_number() == "Example 401(k) and Example"


@pytest.mark.parametrize(
    "lines",
    [
        ["Unrecognized page", "Example Plan", "Retirement Savings Statement"],
        ["Statement Details", "Retirement Savings Statement", "CUSTOMER NAME"],
        ["Statement Details", "Example Plan"],
        ["Statement Details", "Fidelity NetBenefits - SOD detail page", "Plan", "Retirement Savings Statement"],
        ["Statement Details", "Plan", "Retirement Savings Statement", "Retirement Savings Statement"],
    ],
)
def test_uncertain_header_does_not_guess_an_account(lines):
    parser = Parser()
    parser.lines = lines
    with pytest.raises(ValueError):
        parser.extract_account_number()

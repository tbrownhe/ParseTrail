"""Printed Citi account and balance fields from bounded source evidence."""

import pytest

from devtools.parser_engine_pilot.citi_statement_header import CitiHeaderError, parse_header


def test_parses_period_account_and_printed_credit_balance_signs() -> None:
    header = parse_header(
        "Billing Period: 12/04/25-01/05/26 Account number ending in: 1234",
        ("Previous balance $100.00\nNew balance $125.00\nAccount number ending in 1234",),
    )
    assert (header.start_date.isoformat(), header.end_date.isoformat()) == (
        "2025-12-04",
        "2026-01-05",
    )
    assert header.account_suffix == "1234"
    assert header.account_locations == ((1, 3),)
    assert header.previous_balance.ledger_minor == -10000
    assert header.new_balance.ledger_minor == -12500


def test_refuses_conflicting_account_and_duplicate_balance() -> None:
    chars = "Billing Period: 12/04/25-01/05/26"
    with pytest.raises(CitiHeaderError, match="account_suffix"):
        parse_header(
            chars,
            (
                "Account number ending in 1234\nAccount number ending in 5678\nPrevious balance $1.00\nNew balance $2.00",
            ),
        )
    with pytest.raises(CitiHeaderError, match="statement_balances"):
        parse_header(
            chars,
            ("Account number ending in 1234\nPrevious balance $1.00\nPrevious balance $2.00\nNew balance $3.00",),
        )


def test_single_embedded_closing_or_matching_anchored_copy() -> None:
    chars = "Billing Period: 12/04/25-01/05/26"
    base = "Account number ending in 1234\nPrevious balance $1.00\n"
    embedded = parse_header(chars, (base + "Sioux Falls, SD 00000 New balance $3.00",))
    assert embedded.new_balance.ledger_minor == -300
    anchored = parse_header(
        chars,
        (base + "New balance $3.00\nSioux Falls, SD 00000 New balance $3.00",),
    )
    assert anchored.new_balance.line == 3
    with pytest.raises(CitiHeaderError, match="statement_balances"):
        parse_header(chars, (base + "New balance $3.00\nSioux Falls, SD 00000 New balance $4.00",))

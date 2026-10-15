"""The declaration's money operation accepts only its printed syntax."""

import pytest

from devtools.parser_engine_pilot.money_operations import usd_symbol_minor_v1


@pytest.mark.parametrize(
    ("raw", "minor"),
    [("$0.00", 0), ("-$10.25", -1025), ("$1,234.56", 123456), ("$999", 99900)],
)
def test_exact_usd_symbol_amount(raw: str, minor: int) -> None:
    assert usd_symbol_minor_v1(raw) == minor


@pytest.mark.parametrize("raw", ["$1.2", "$1000.00", "$1,23.00", "($1.00)", "$1.00CR", "1.00", "$1.00 "])
def test_undeclared_money_syntax_is_refused(raw: str) -> None:
    with pytest.raises(ValueError, match="invalid_usd_symbol_amount"):
        usd_symbol_minor_v1(raw)

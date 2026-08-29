from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from parsetrail.core import plot
from parsetrail.core.fingerprint import transaction_fingerprint
from parsetrail.core.money import (
    from_minor_units,
    parse_money,
    require_minor_units,
    to_minor_units,
)
from parsetrail.gui.main_window import PandasModel
from PySide6.QtCore import Qt


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$12.34", Decimal("12.34")),
        ("-$12.34", Decimal("-12.34")),
        ("($12.34)", Decimal("-12.34")),
        ("$12.34CR", Decimal("-12.34")),
        ("$12.34-", Decimal("-12.34")),
    ],
)
def test_parse_money_is_exact(raw: str, expected: Decimal) -> None:
    assert parse_money(raw) == expected


def test_money_rejects_binary_float_and_sub_minor_values() -> None:
    with pytest.raises(TypeError, match="binary floats"):
        require_minor_units(0.1)
    with pytest.raises(ValueError, match="more than 2 decimal places"):
        require_minor_units("0.001")


def test_minor_unit_round_trip_is_exact() -> None:
    values = [Decimal("0.00"), Decimal("0.01"), Decimal("-10.99"), Decimal("999999999999.99")]
    assert [from_minor_units(to_minor_units(value)) for value in values] == values


def test_fingerprint_has_explicit_framing_and_occurrence() -> None:
    common = {
        "account_id": 7,
        "posting_date": date(2026, 8, 28),
        "amount": Decimal("12.34"),
        "balance": Decimal("56.78"),
        "currency_code": "USD",
    }
    first = transaction_fingerprint(description="AB", occurrence=0, **common)
    same_normalized = transaction_fingerprint(description="  AB  ", occurrence=0, **common)
    different_boundary = transaction_fingerprint(description="A", occurrence=0, **common)
    second_occurrence = transaction_fingerprint(description="AB", occurrence=1, **common)

    assert first == same_normalized
    assert len(first) == 64
    assert len({first, different_boundary, second_occurrence}) == 3


def test_plotting_converts_exact_values_only_at_presentation_boundary(monkeypatch) -> None:
    columns = ["TransactionID", "AccountName", "AssetType", "Date", "Amount", "Balance", "Description", "Category"]
    data = [
        (
            1,
            "Checking",
            "Asset",
            date(2026, 8, 28),
            Decimal("12.34"),
            Decimal("112.34"),
            "Example",
            "Bills",
        )
    ]
    monkeypatch.setattr(plot.query, "transactions", lambda _session: (data, columns))
    monkeypatch.setattr(plot.query, "asset_types", lambda _session: {"Checking": "Asset"})

    balances, _ = plot.get_balance_data(object())
    categories = plot.get_category_data(object())

    assert balances.loc[pd.Timestamp("2026-08-28"), "Checking"] == pytest.approx(112.34)
    assert categories.loc[pd.Timestamp("2026-08-01"), "Bills"] == pytest.approx(12.34)


def test_pandas_model_does_not_treat_dates_as_numeric() -> None:
    model = PandasModel(pd.DataFrame([[Decimal("12.34"), date(2026, 8, 28)]], columns=["Balance", "Date"]))

    assert model.data(model.index(0, 1), Qt.BackgroundRole) is None

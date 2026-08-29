"""Exact money parsing and integer-minor-unit conversion."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

DEFAULT_CURRENCY = "USD"
SUPPORTED_CURRENCIES = {DEFAULT_CURRENCY: 2}


def currency_minor_unit(currency_code: str) -> int:
    normalized = currency_code.strip().upper()
    try:
        return SUPPORTED_CURRENCIES[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported currency code: {normalized!r}") from exc


def exact_decimal(value: Decimal | int | str) -> Decimal:
    """Return an exact Decimal and deliberately reject binary floats."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("Money values must be Decimal, int, or str; binary floats are not accepted.")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, str)):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid money value: {value!r}") from exc
    else:
        raise TypeError(f"Money values must be Decimal, int, or str, got {type(value).__name__}.")
    if not result.is_finite():
        raise ValueError("Money values must be finite.")
    return result


def require_minor_units(
    value: Decimal | int | str,
    currency_code: str = DEFAULT_CURRENCY,
) -> Decimal:
    amount = exact_decimal(value)
    exponent = currency_minor_unit(currency_code)
    quantum = Decimal(1).scaleb(-exponent)
    quantized = amount.quantize(quantum)
    if amount != quantized:
        raise ValueError(f"{currency_code.upper()} values cannot have more than {exponent} decimal places.")
    return quantized


def to_minor_units(
    value: Decimal | int | str,
    currency_code: str = DEFAULT_CURRENCY,
) -> int:
    amount = require_minor_units(value, currency_code)
    exponent = currency_minor_unit(currency_code)
    return int(amount.scaleb(exponent))


def from_minor_units(value: int, currency_code: str = DEFAULT_CURRENCY) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Minor-unit values must be integers, got {type(value).__name__}.")
    exponent = currency_minor_unit(currency_code)
    return Decimal(value).scaleb(-exponent)


def parse_money(amount_text: str, currency_code: str = DEFAULT_CURRENCY) -> Decimal:
    """Parse common statement money formats without passing through a float."""
    if not isinstance(amount_text, str):
        raise TypeError(f"Money text must be a string, got {type(amount_text).__name__}.")

    normalized = amount_text.replace(",", "").replace("$", "").replace(" ", "").upper()
    negative = (
        normalized.startswith("-")
        or normalized.endswith("-")
        or normalized.endswith("CR")
        or (normalized.startswith("(") and normalized.endswith(")"))
    )
    cleaned = normalized.replace("-", "").replace("CR", "").replace("(", "").replace(")", "")
    if not cleaned:
        raise ValueError("Money text does not contain a value.")
    amount = require_minor_units(cleaned, currency_code)
    return -amount if negative else amount

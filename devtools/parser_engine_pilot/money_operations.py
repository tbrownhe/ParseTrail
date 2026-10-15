"""Finite exact money operations for parser definitions."""

from __future__ import annotations

import re

USD_SYMBOL = re.compile(r"-?\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
USD_OR_DECIMAL_2DP = re.compile(r"-?\$?(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}")
USD_TRAILING_CREDIT_2DP = re.compile(r"\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}-?")
USD_TRAILING_CR_2DP = re.compile(r"\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}(?:CR)?")
MAX_MINOR = 9_000_000_000_000_000


def usd_symbol_minor_v1(raw: str) -> int:
    """Read the printed Citi-style USD token without broad money coercion."""
    if type(raw) is not str or len(raw) > 40 or USD_SYMBOL.fullmatch(raw) is None:
        raise ValueError("invalid_usd_symbol_amount")
    negative = raw.startswith("-")
    digits = raw.removeprefix("-").removeprefix("$").replace(",", "")
    whole, separator, fraction = digits.partition(".")
    amount = int(whole) * 100 + (int(fraction) if separator else 0)
    if amount > MAX_MINOR:
        raise ValueError("usd_symbol_amount_range")
    return -amount if negative else amount


def usd_or_decimal_2dp_minor_v1(raw: str) -> int:
    """Read a printed signed dollar or bare-decimal token in exact cents."""
    if type(raw) is not str or len(raw) > 40 or USD_OR_DECIMAL_2DP.fullmatch(raw) is None:
        raise ValueError("invalid_usd_or_decimal_amount")
    negative = raw.startswith("-")
    major, cents = raw.removeprefix("-").removeprefix("$").replace(",", "").split(".")
    amount = int(major) * 100 + int(cents)
    if amount > MAX_MINOR:
        raise ValueError("usd_or_decimal_amount_range")
    return -amount if negative else amount


def usd_trailing_credit_2dp_minor_v1(raw: str) -> int:
    """Read a printed dollar amount whose trailing minus marks a credit."""
    if type(raw) is not str or len(raw) > 40 or USD_TRAILING_CREDIT_2DP.fullmatch(raw) is None:
        raise ValueError("invalid_usd_trailing_credit_amount")
    negative = raw.endswith("-")
    major, cents = raw.removesuffix("-").removeprefix("$").replace(",", "").split(".")
    amount = int(major) * 100 + int(cents)
    if amount > MAX_MINOR:
        raise ValueError("usd_trailing_credit_amount_range")
    return -amount if negative else amount


def usd_trailing_cr_2dp_minor_v1(raw: str) -> int:
    """Read a printed dollar amount whose CR suffix marks a credit."""
    if type(raw) is not str or len(raw) > 40 or USD_TRAILING_CR_2DP.fullmatch(raw) is None:
        raise ValueError("invalid_usd_trailing_cr_amount")
    negative = raw.endswith("CR")
    major, cents = raw.removesuffix("CR").removeprefix("$").replace(",", "").split(".")
    amount = int(major) * 100 + int(cents)
    if amount > MAX_MINOR:
        raise ValueError("usd_trailing_cr_amount_range")
    return -amount if negative else amount

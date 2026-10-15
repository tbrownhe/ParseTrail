"""Finite exact money operations for parser definitions."""

from __future__ import annotations

import re

USD_SYMBOL = re.compile(r"-?\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
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

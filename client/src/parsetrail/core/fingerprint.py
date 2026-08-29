"""Versioned, unambiguous transaction fingerprints."""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import date
from decimal import Decimal

from parsetrail.core.money import DEFAULT_CURRENCY, to_minor_units

TRANSACTION_FINGERPRINT_VERSION = 1
_DOMAIN = b"parsetrail.transaction\x00"


def _frame(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(8, "big") + encoded


def _normalize_description(description: str) -> str:
    normalized = unicodedata.normalize("NFKC", description)
    return " ".join(normalized.split())


def transaction_fingerprint(
    *,
    account_id: int,
    posting_date: date,
    amount: Decimal,
    balance: Decimal,
    description: str,
    occurrence: int,
    currency_code: str = DEFAULT_CURRENCY,
) -> str:
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise ValueError("account_id must be a positive integer.")
    if not isinstance(posting_date, date):
        raise TypeError("posting_date must be a date.")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-empty string.")
    if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 0:
        raise ValueError("occurrence must be a non-negative integer.")

    currency = currency_code.strip().upper()
    fields = (
        str(TRANSACTION_FINGERPRINT_VERSION),
        str(account_id),
        posting_date.isoformat(),
        str(to_minor_units(amount, currency)),
        str(to_minor_units(balance, currency)),
        currency,
        _normalize_description(description),
        str(occurrence),
    )
    payload = _DOMAIN + b"".join(_frame(field) for field in fields)
    return hashlib.sha256(payload).hexdigest()

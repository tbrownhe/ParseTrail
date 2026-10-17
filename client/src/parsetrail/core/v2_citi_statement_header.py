"""Finite recent-Citi statement fields from bounded first-page and text evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from parsetrail.core.v2_money_operations import USD_SYMBOL, usd_symbol_minor_v1

MONEY = USD_SYMBOL.pattern


class CitiHeaderError(ValueError):
    """Redacted refusal of ambiguous printed statement fields."""


@dataclass(frozen=True, slots=True)
class PrintedBalance:
    page: int
    line: int
    raw: str
    ledger_minor: int


@dataclass(frozen=True, slots=True)
class CitiStatementHeader:
    start_date: date
    end_date: date
    period_char_span: tuple[int, int]
    account_suffix: str
    account_locations: tuple[tuple[int, int], ...]
    previous_balance: PrintedBalance
    new_balance: PrintedBalance


def parse_header(
    first_page_chars: str,
    pages: tuple[str, ...],
    *,
    period_label: str = "Billing Period:",
    account_label: str = "Account number ending in",
    opening_label: str = "Previous balance",
    closing_label: str = "New balance",
) -> CitiStatementHeader:
    """Read only observed fields; reject missing, conflicting or duplicate values."""
    if any(not label or len(label) > 80 for label in (period_label, account_label, opening_label, closing_label)):
        raise CitiHeaderError("invalid_labels")
    period_pattern = re.compile(
        rf"{re.escape(period_label)}\s{{0,4}}(\d{{2}}/\d{{2}}/\d{{2}})-(\d{{2}}/\d{{2}}/\d{{2}})"
    )
    account_pattern = re.compile(rf"{re.escape(account_label)}:?\s*(\d{{4}})")
    opening_pattern = re.compile(rf"\b{re.escape(opening_label)}\s+(?P<amount>{MONEY})(?:\s|$)")
    closing_pattern = re.compile(rf"\b{re.escape(closing_label)}\s+(?P<amount>{MONEY})(?:\s|$)")
    periods = list(period_pattern.finditer(first_page_chars))
    if len(periods) != 1:
        raise CitiHeaderError("statement_period")
    try:
        start = datetime.strptime(periods[0][1], "%m/%d/%y").date()
        end = datetime.strptime(periods[0][2], "%m/%d/%y").date()
    except ValueError:
        raise CitiHeaderError("statement_period") from None
    if not start < end or (end - start).days > 45:
        raise CitiHeaderError("statement_period")

    accounts: list[tuple[str, int, int]] = []
    previous: list[PrintedBalance] = []
    new: list[PrintedBalance] = []
    anchored_new: list[PrintedBalance] = []
    for page_number, page in enumerate(pages, 1):
        for line_number, line in enumerate(page.splitlines(), 1):
            accounts.extend((match[1], page_number, line_number) for match in account_pattern.finditer(line))
            normalized = " ".join(line.split())
            for pattern, found in ((opening_pattern, previous), (closing_pattern, new)):
                if match := pattern.search(normalized):
                    raw = match["amount"]
                    value = PrintedBalance(page_number, line_number, raw, -usd_symbol_minor_v1(raw))
                    found.append(value)
                    if found is new and match.start() == 0:
                        anchored_new.append(value)
    if not accounts or len({account for account, _, _ in accounts}) != 1:
        raise CitiHeaderError("account_suffix")
    if len(previous) != 1 or not new:
        raise CitiHeaderError("statement_balances")
    if len(new) == 1:
        selected_new = new[0]
    elif len(anchored_new) == 1 and all(item.ledger_minor == anchored_new[0].ledger_minor for item in new):
        selected_new = anchored_new[0]
    else:
        raise CitiHeaderError("statement_balances")
    return CitiStatementHeader(
        start,
        end,
        periods[0].span(),
        accounts[0][0],
        tuple((page, line) for _, page, line in accounts),
        previous[0],
        selected_new,
    )

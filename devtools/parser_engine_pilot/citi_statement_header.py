"""Finite recent-Citi statement fields from bounded first-page and text evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from devtools.parser_engine_pilot.money_operations import USD_SYMBOL, usd_symbol_minor_v1

PERIOD = re.compile(r"Billing Period:\s{0,4}(\d{2}/\d{2}/\d{2})-(\d{2}/\d{2}/\d{2})")
ACCOUNT = re.compile(r"Account number ending in:?\s*(\d{4})")
MONEY = USD_SYMBOL.pattern
PREVIOUS = re.compile(rf"\bPrevious balance\s+(?P<amount>{MONEY})")
NEW = re.compile(rf"\bNew balance\s+(?P<amount>{MONEY})")


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


def parse_header(first_page_chars: str, pages: tuple[str, ...]) -> CitiStatementHeader:
    """Read only observed fields; reject missing, conflicting or duplicate values."""
    periods = list(PERIOD.finditer(first_page_chars))
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
    for page_number, page in enumerate(pages, 1):
        for line_number, line in enumerate(page.splitlines(), 1):
            accounts.extend((match[1], page_number, line_number) for match in ACCOUNT.finditer(line))
            for pattern, found in ((PREVIOUS, previous), (NEW, new)):
                for match in pattern.finditer(line):
                    raw = match["amount"]
                    found.append(
                        PrintedBalance(
                            page_number,
                            line_number,
                            raw,
                            -usd_symbol_minor_v1(raw),
                        )
                    )
    if not accounts or len({account for account, _, _ in accounts}) != 1:
        raise CitiHeaderError("account_suffix")
    if len(previous) != 1 or len(new) != 1:
        raise CitiHeaderError("statement_balances")
    return CitiStatementHeader(
        start,
        end,
        periods[0].span(),
        accounts[0][0],
        tuple((page, line) for _, page, line in accounts),
        previous[0],
        new[0],
    )

"""Read-only disposition of Citi dollar lines outside dated transactions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from parsetrail.plugins.pdf_citicc_202511 import Parser as RecentCiti

from devtools.parser_engine_pilot.citi_source_dispositions import DatedLineDisposition

MONEY = RecentCiti.AMOUNT.pattern
NEW_CHARGES = re.compile(rf"New Charges\s+{MONEY}\Z")
ANNUAL_TOTAL = re.compile(rf"Total (?:fees|interest) charged in \d{{4}}\s+{MONEY}\Z")


@dataclass(frozen=True, slots=True)
class MoneyLineDisposition:
    page: int
    line: int
    status: Literal[
        "legal_disclosure",
        "fee_period_total",
        "interest_period_total",
        "annual_summary",
        "cardholder_subtotal",
        "apr_information",
        "membership_notice",
        "unresolved",
    ]


def dispose_unlinked_money_lines(
    pages: tuple[str, ...], dated_lines: tuple[DatedLineDisposition, ...]
) -> tuple[MoneyLineDisposition, ...]:
    """Classify every non-transaction dollar line after the first page."""
    covered = {(item.page, line) for item in dated_lines for line in range(item.line, item.end_line + 1)}
    result = []
    for page_number, page in enumerate(pages, 1):
        if page_number == 1:
            continue
        lines = page.splitlines()
        for index, raw in enumerate(lines):
            line_number = index + 1
            if (page_number, line_number) in covered or RecentCiti.AMOUNT.search(raw) is None:
                continue
            line = " ".join(raw.split())
            # Accessible-PDF decorative digits can precede a printed label.
            label = re.sub(r"^\d+\s+", "", line)
            if label.startswith("and the purchase price must have been more than "):
                status = "legal_disclosure"
            elif "TOTAL FEES FOR THIS PERIOD" in label or (
                RecentCiti.AMOUNT.fullmatch(label)
                and any(
                    "TOTAL FEES FOR THIS PERIOD" in lines[later]
                    for later in range(index + 1, min(len(lines), index + 4))
                )
            ):
                status = "fee_period_total"
            elif "TOTAL INTEREST FOR THIS PERIOD" in label:
                status = "interest_period_total"
            elif ANNUAL_TOTAL.fullmatch(label):
                status = "annual_summary"
            elif NEW_CHARGES.fullmatch(label):
                status = "cardholder_subtotal"
            elif (
                label.startswith(("Standard Purch ", "Standard Adv ", "RtSaleOffer "))
                and "%" in label
                and "(D)" in label
                and len(RecentCiti.AMOUNT.findall(label)) >= 2
            ):
                status = "apr_information"
            elif label.startswith("Your account has an Annual Membership Fee of "):
                status = "membership_notice"
            else:
                status = "unresolved"
            result.append(MoneyLineDisposition(page_number, line_number, status))
    return tuple(result)

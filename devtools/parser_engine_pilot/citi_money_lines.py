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
SUMMARY_AMOUNT = re.compile(
    rf"(?:Previous balance|Payments|Credits|Purchases|Cash advances|Fees|Interest|New balance)\s*\+?\s*{MONEY}"
)
COUPON_AMOUNTS = re.compile(rf"{MONEY}\s+{MONEY}\s+\d{{2}}/\d{{2}}/\d{{2}}\Z")


@dataclass(frozen=True, slots=True)
class MoneyLineDisposition:
    page: int
    line: int
    status: Literal[
        "account_summary",
        "payment_information",
        "credit_terms",
        "repayment_example",
        "summary_extraction_artifact",
        "cardholder_subtotal_extraction_artifact",
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
    """Classify every dollar line outside dated transaction spans."""
    covered = {(item.page, line) for item in dated_lines for line in range(item.line, item.end_line + 1)}
    result = []
    for page_number, page in enumerate(pages, 1):
        lines = page.splitlines()
        for index, raw in enumerate(lines):
            line_number = index + 1
            if (page_number, line_number) in covered or "$" not in raw:
                continue
            line = " ".join(raw.split())
            # Accessible-PDF decorative digits can precede a printed label.
            label = re.sub(r"^\d+\s+", "", line)
            if RecentCiti.AMOUNT.search(raw) is None:
                if page_number == 1 and "Amount enclosed:" in label:
                    status = "payment_information"
                elif page_number == 1 and "INnetewr ebsatlance" in label:
                    status = "summary_extraction_artifact"
                elif page_number > 1 and label.startswith("New Charges Card"):
                    status = "cardholder_subtotal_extraction_artifact"
                else:
                    status = "unresolved"
            elif page_number == 1:
                status = _first_page_status(label, lines, index)
            elif label.startswith("and the purchase price must have been more than "):
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


def _first_page_status(label: str, lines: list[str], index: int) -> str:
    """Keep summary, payment and disclosure amounts separate from activity."""
    if "INnetewr ebsatlance" in label:
        return "summary_extraction_artifact"
    if SUMMARY_AMOUNT.search(label):
        return "account_summary"
    if label.startswith(("Your next AutoPay payment of ", "Minimum payment due", "New balance as of ")):
        return "payment_information"
    if "Minimum payment due" in label or "New balance" in label:
        return "payment_information"
    if COUPON_AMOUNTS.fullmatch(label) and index > 0 and "Payment due date" in lines[index - 1]:
        return "payment_information"
    if "Savings=" in label or ("Only the minimum payment" in label and RecentCiti.AMOUNT.search(label)):
        return "repayment_example"
    if RecentCiti.AMOUNT.fullmatch(label) and any(
        "Savings=" in following for following in lines[index + 1 : index + 3]
    ):
        return "repayment_example"
    if (
        "late fee of up to " in label
        or "Credit Limit" in label
        or "Includes $" in label
        or "available for cash advance" in label
    ):
        return "credit_terms"
    return "unresolved"

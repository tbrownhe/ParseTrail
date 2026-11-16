"""Finite non-activity roles for uncovered older Citi monetary lines.

These labels retain source detail; they neither add activity nor certify capture.
An unfamiliar suffix, parallel amount or dated line remains unresolved.
"""

from __future__ import annotations

import re

from parsetrail.core.source_evidence import SourceDisposition
from parsetrail.core.v2_pdf_lines import PageLine, PDFLineEvidence

_MONEY = r"-?\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
# Whole dollars are printed in credit terms and repayment illustrations. This
# grammar is deliberately separate from financial activity and period totals.
_DISCLOSURE_MONEY = r"\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{2})?"
_SUMMARY = re.compile(rf"(?:Payments|Credits|Purchases|Cash advances|Fees|Interest)\s*:?\s*\+?\s*{_MONEY}", re.I)
_PAYMENT = re.compile(rf"(?:Minimum payment due\s*:?|New balance as of \d{{2}}/\d{{2}}/\d{{2}}:)\s*{_MONEY}", re.I)
_CREDIT = re.compile(rf"(?:Credit limit|Available credit|Cash advance limit)\s*:?\s*{_DISCLOSURE_MONEY}", re.I)
_CASH_LIMIT = re.compile(rf"Includes {_DISCLOSURE_MONEY} cash advance limit", re.I)
_CREDIT_EXAMPLE = re.compile(rf"your balance\. For example: Credit Limit {_DISCLOSURE_MONEY}", re.I)
_AVAILABLE_HEADER = re.compile(
    rf"charges using this card balance shown on the paying an estimated Available credit {_DISCLOSURE_MONEY}", re.I
)
_CASH_AVAILABLE_HEADER = re.compile(
    rf"and each month you pay\.\.\. statement in about\.\.\. total of\.\.\. Includes {_DISCLOSURE_MONEY} available for cash advances",
    re.I,
)
_YEARS = r"[1-9][0-9]? year\(s\)"
_REPAYMENT_MINIMUM = re.compile(rf"Only the minimum payment {_YEARS} {_DISCLOSURE_MONEY}", re.I)
_REPAYMENT_MONTHLY = re.compile(rf"{_DISCLOSURE_MONEY} {_YEARS}", re.I)
_REPAYMENT_SAVINGS = re.compile(rf"\(Savings={_DISCLOSURE_MONEY}\)", re.I)
_APR = re.compile(
    rf"(?:Standard Purch|Standard Adv|BalTrnOffer(?: \d{{1,2}})?|RtSaleOffer(?: \d{{1,2}})?) "
    rf"\d{{1,2}}\.\d{{2}}% (?:\(V\) )?{_MONEY} \(D\) {_MONEY}",
    re.I,
)
_APR_TABLE_ROW = re.compile(
    rf"[A-Za-z][A-Za-z0-9 ]{{0,59}} \d{{1,2}}\.\d{{2}}% (?:\(V\) )?{_MONEY} \(D\) {_MONEY}", re.I
)
_INTEREST_DETAIL = re.compile(rf"Interest:\s*{_MONEY}", re.I)
_INTEREST_TOTAL = re.compile(rf"Total interest charged in this billing period\s+{_MONEY}", re.I)


def classify_legacy_citi_money(
    dispositions: tuple[SourceDisposition, ...], lines: PDFLineEvidence
) -> tuple[SourceDisposition, ...]:
    """Refine only unclassified full lines, preserving locations and raw values."""
    pages: dict[int, list[PageLine]] = {}
    for line in lines.lines:
        if line.normalized:
            pages.setdefault(line.page, []).append(line)
    positions = {(line.page, line.line): (page, index) for page in pages.values() for index, line in enumerate(page)}
    result = []
    for item in dispositions:
        if item.code in {"fee_period_total", "interest_period_total", "annual_fee_total", "annual_interest_total"}:
            if (
                sum(value.count("$") for value in item.raw_values) != 1
                or sum(len(re.findall(_MONEY + r"(?![\d.])", value)) for value in item.raw_values) != 1
            ):
                item = item.model_copy(update={"code": "unclassified_monetary_line"})
        if item.code != "unclassified_monetary_line":
            result.append(item)
            continue
        page, index = positions[(item.location.page, item.location.line)]
        raw = page[index].normalized
        code = None
        if item.location.page == 1:
            if _SUMMARY.fullmatch(raw):
                code = "citi_account_summary"
            elif _PAYMENT.fullmatch(raw):
                code = "citi_payment_information"
            elif (
                _CREDIT.fullmatch(raw)
                or _CASH_LIMIT.fullmatch(raw)
                or (
                    _CREDIT_EXAMPLE.fullmatch(raw)
                    and index + 1 < len(page)
                    and _CASH_LIMIT.fullmatch(page[index + 1].normalized)
                )
                or (
                    _AVAILABLE_HEADER.fullmatch(raw)
                    and index + 1 < len(page)
                    and _CASH_AVAILABLE_HEADER.fullmatch(page[index + 1].normalized)
                )
                or (
                    _CASH_AVAILABLE_HEADER.fullmatch(raw)
                    and index > 0
                    and _AVAILABLE_HEADER.fullmatch(page[index - 1].normalized)
                )
            ):
                code = "citi_credit_terms"
            elif _REPAYMENT_MINIMUM.fullmatch(raw):
                code = "citi_repayment_example"
            elif (
                _REPAYMENT_MONTHLY.fullmatch(raw)
                and any(_REPAYMENT_MINIMUM.fullmatch(line.normalized) for line in page[max(0, index - 2) : index])
                and index + 1 < len(page)
                and _REPAYMENT_SAVINGS.fullmatch(page[index + 1].normalized)
            ) or (
                _REPAYMENT_SAVINGS.fullmatch(raw)
                and index > 0
                and _REPAYMENT_MONTHLY.fullmatch(page[index - 1].normalized)
                and any(_REPAYMENT_MINIMUM.fullmatch(line.normalized) for line in page[max(0, index - 3) : index - 1])
            ):
                code = "citi_repayment_example"
        elif _APR.fullmatch(raw) or (
            _APR_TABLE_ROW.fullmatch(raw)
            and any(
                line.normalized.startswith("Standard Purch ") and _APR.fullmatch(line.normalized)
                for line in page[max(0, index - 3) : index]
            )
            and any(
                line.normalized.startswith("Standard Adv ") and _APR.fullmatch(line.normalized)
                for line in page[index + 1 : index + 7]
            )
        ):
            code = "citi_apr_information"
        elif (
            _INTEREST_DETAIL.fullmatch(raw)
            and (
                (index > 0 and page[index - 1].normalized.casefold() == "interest charged")
                or (index + 1 < len(page) and page[index + 1].normalized.casefold() == "interest charged")
            )
            and any(_INTEREST_TOTAL.fullmatch(line.normalized) for line in page[index + 1 : index + 4])
        ):
            code = "citi_interest_charge_detail"
        result.append(item.model_copy(update={"code": code}) if code is not None else item)
    return tuple(result)

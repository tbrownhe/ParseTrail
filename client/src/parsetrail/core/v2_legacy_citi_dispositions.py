"""Finite non-activity roles for uncovered older Citi monetary lines.

These labels retain source detail; they neither add activity nor certify capture.
An unfamiliar suffix, parallel amount or dated line remains unresolved.
"""

from __future__ import annotations

import re

from parsetrail.core.source_evidence import SourceDisposition
from parsetrail.core.v2_money_operations import usd_symbol_minor_v1
from parsetrail.core.v2_pdf_lines import PageLine, PDFLineEvidence

_MONEY = r"-?\$\s*(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
# Whole dollars are printed in credit terms and repayment illustrations. This
# grammar is deliberately separate from financial activity and period totals.
_DISCLOSURE_MONEY = r"\$\s*(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{2})?"
_SUMMARY = re.compile(rf"(?:Payments|Credits|Purchases|Cash advances|Fees|Interest)\s*:?\s*[+-]?\s*{_MONEY[2:]}", re.I)
_PAYMENT = re.compile(rf"(?:Minimum payment due\s*:?|New balance as of \d{{2}}/\d{{2}}/\d{{2}}:)\s*{_MONEY}", re.I)
_CREDIT = re.compile(
    rf"(?:(?:Revolving )?Credit limit|Available (?:(?:cash|revolving) )?credit|Cash advance limit)\s*:?\s*{_DISCLOSURE_MONEY}",
    re.I,
)
_CASH_LIMIT = re.compile(rf"Includes {_DISCLOSURE_MONEY} (?:cash advance limit|available for cash advances)", re.I)
_CREDIT_EXAMPLE = re.compile(rf"your balance\. For example: Credit Limit {_DISCLOSURE_MONEY}", re.I)
_AVAILABLE_HEADER = re.compile(
    rf"charges using this card balance shown on the paying an estimated Available credit {_DISCLOSURE_MONEY}", re.I
)
_CASH_AVAILABLE_HEADER = re.compile(
    rf"and each month you pay\.\.\. statement in about\.\.\. total of\.\.\. Includes {_DISCLOSURE_MONEY} available for cash advances",
    re.I,
)
_YEARS = r"[1-9][0-9]? year\(s\)"
_REPAYMENT_TERM = r"[1-9][0-9]? (?:year|month)\(s\)"
_REPAYMENT_CREDIT = rf"(?:(?:Revolving )?Credit limit|Available (?:Revolving )?credit) {_DISCLOSURE_MONEY}"
_REPAYMENT_MINIMUM = re.compile(rf"Only the minimum payment {_YEARS} {_DISCLOSURE_MONEY}", re.I)
_REPAYMENT_MINIMUM_WITH_HEADER = re.compile(
    rf"Only the minimum payment {_REPAYMENT_TERM} {_DISCLOSURE_MONEY} Credit Limit", re.I
)
_REPAYMENT_MONTHLY = re.compile(rf"{_DISCLOSURE_MONEY} {_YEARS}", re.I)
_REPAYMENT_SAVINGS = re.compile(rf"\(Savings\s*=\s*{_DISCLOSURE_MONEY}\)", re.I)
_APR = re.compile(
    rf"(?:Standard Purch|Standard Adv|BalTrnOffer(?: \d{{1,2}})?|RtSaleOffer(?: \d{{1,2}})?) "
    rf"\d{{1,2}}\.\d{{2}}% (?:\(\s*V\s*\) )?{_MONEY} \(D\) {_MONEY}",
    re.I,
)
_APR_TABLE_ROW = re.compile(
    rf"[A-Za-z][A-Za-z0-9 ]{{0,59}} \d{{1,2}}\.\d{{2}}% (?:\(\s*V\s*\) )?{_MONEY} \(D\) {_MONEY}", re.I
)
_INTEREST_DETAIL = re.compile(rf"Interest:\s*{_MONEY}", re.I)
_INTEREST_TOTAL = re.compile(rf"Total interest charged in this billing period\s+{_MONEY}", re.I)
_SUMMARY_PREFIX = re.compile(
    r"(?:Minimum Payment Warning: I\s*f you make only the minimum payment each|"
    r"period, you will pay more in interest and it will take you longer to pay off|"
    r"your balance\. For example:|"
    r"If you make no additional You will pay off the And you will end up|"
    r"charges using this card balance shown on the paying an estimated)",
    re.I,
)
_ANNUAL_PURCHASES = re.compile(rf"Minimum annual purchases:\s*{_DISCLOSURE_MONEY}", re.I)
_AUTOPAY = re.compile(
    rf"(?:(?:[A-Za-z]{{1,12}} statement,? your next)|(?:Your next)) AutoPay payment of {_MONEY}(?: will)?", re.I
)
_LATE_WARNING = re.compile(
    rf"listed above, you may have to pay a late fee of up to {_DISCLOSURE_MONEY} and your APRs may be", re.I
)
_COUPON = re.compile(
    rf"(?:Pay your bill from virtually anywhere|Enrolled in AutoPay\.?) Minimum payment due\s*:?\s*{_MONEY}", re.I
)
_COUNSELING_CREDIT = re.compile(
    rf"For information about credit counseling services, call [0-9-]+\. (?:Revolving )?Credit limit {_DISCLOSURE_MONEY}",
    re.I,
)
_MINIMUM_INTEREST = re.compile(
    rf"Minimum interest charge\. If we charge interest, it will be at least {_DISCLOSURE_MONEY}\.", re.I
)
_CONDITIONAL_LATE_FEE = re.compile(
    rf"using a {_DISCLOSURE_MONEY} late fee \(if your minimum payment due was less than {_DISCLOSURE_MONEY}, we used",
    re.I,
)
_REPAYMENT_COMBINED = re.compile(
    rf"{_DISCLOSURE_MONEY} {_REPAYMENT_TERM}(?: (?P<total>{_DISCLOSURE_MONEY}))?"
    rf"(?: \(Savings\s*=\s*{_DISCLOSURE_MONEY}\))?"
    rf"(?: (?:{_REPAYMENT_CREDIT}|Includes {_DISCLOSURE_MONEY} cash advance limit))?",
    re.I,
)
_MINIMUM_WITH_CREDIT = re.compile(
    rf"(?P<minimum>Only the minimum payment {_REPAYMENT_TERM} {_DISCLOSURE_MONEY})"
    rf"(?: {_REPAYMENT_CREDIT})?",
    re.I,
)
_OVERLIMIT = re.compile(rf"(?:includes an overlimit amount of {_MONEY} and a|past due amount of {_MONEY}\.?)", re.I)
_LEGAL_PURCHASE = re.compile(
    rf"day['’\ufffd]s balance and new charges, subtract new credits or payments, and make "
    rf"than {_DISCLOSURE_MONEY}\. \(Note: Neither of these is necessary if your purchase was based on",
    re.I,
)


def _repayment_headings(page: list[PageLine], index: int) -> bool:
    headers = [item.normalized.casefold() for item in page[max(0, index - 8) : index]]
    return any(item.startswith("if you make no additional") for item in headers) and any(
        item.startswith("and each month you pay") for item in headers
    )


def _repayment_positions(page: list[PageLine]) -> set[int]:
    """Prove the detached total from the labelled repayment table and savings.

    A bare amount alone is not a repayment example. Require the printed column
    headings, both labelled alternatives, and exact illustrated savings before
    classifying a detached total. This never checks an account balance.
    """
    result = set()
    for index, line in enumerate(page):
        minimum = _MINIMUM_WITH_CREDIT.fullmatch(line.normalized)
        if minimum is None:
            continue
        if not _repayment_headings(page, index):
            continue
        nearby = range(index + 1, min(index + 9, len(page)))
        monthly = [i for i in nearby if _REPAYMENT_COMBINED.fullmatch(page[i].normalized)]
        savings = [
            (i, match)
            for i in nearby
            if (match := re.search(rf"\(Savings\s*=\s*(?P<amount>{_DISCLOSURE_MONEY})\)", page[i].normalized, re.I))
            and (i in monthly or _REPAYMENT_SAVINGS.fullmatch(page[i].normalized))
        ]
        if len(monthly) != 1 or len(savings) != 1 or abs(monthly[0] - savings[0][0]) > 1:
            continue
        minimum_raw = re.search(_DISCLOSURE_MONEY + r"(?![\d,.])", minimum["minimum"]).group()

        # Complete grammars above have already bounded every monetary token.
        def minor(raw):
            raw = raw.replace(" ", "")
            return usd_symbol_minor_v1(raw if "." in raw else raw + ".00")

        try:
            total = minor(minimum_raw) - minor(savings[0][1]["amount"])
            monthly_match = _REPAYMENT_COMBINED.fullmatch(page[monthly[0]].normalized)
            if monthly_match["total"] is not None:
                if minor(monthly_match["total"]) == total:
                    result.update((index, monthly[0], savings[0][0]))
                continue
            detached = [
                i
                for i in nearby
                if re.fullmatch(_DISCLOSURE_MONEY, page[i].normalized) and minor(page[i].normalized) == total
            ]
        except ValueError:
            # Disclosure recognition never bypasses the exact money operation's
            # syntax/range. Keep incomplete proof as unresolved source content.
            continue
        if len(detached) == 1:
            result.update((index, monthly[0], savings[0][0], detached[0]))
    return result


def _parallel_summary(raw: str) -> bool:
    for match in re.finditer(r"(?:Payments|Credits|Purchases|Cash advances|Fees|Interest)\b", raw, re.I):
        prefix = raw[: match.start()].strip()
        if (
            _SUMMARY_PREFIX.fullmatch(prefix)
            or re.fullmatch(
                r"Late Payment Warning: If we do not receive your minimum payment by the date", prefix, re.I
            )
            or _LATE_WARNING.fullmatch(prefix)
            or re.fullmatch(r"increased up to the Penalty APR of \d{1,2}\.\d{2}%\.?", prefix, re.I)
        ) and _SUMMARY.fullmatch(raw[match.start() :]):
            return True
    return False


def _apr_with_known_parallel_text(raw: str) -> bool:
    match = _APR.match(raw)
    if match is None:
        return False
    tail = raw[match.end() :].strip()
    return bool(_ANNUAL_PURCHASES.fullmatch(tail) or tail.casefold() in {"interest charged", "interest rate"})


def _savings_positions(page: list[PageLine]) -> set[int]:
    """Bind the labeled sidebar components and its explicitly labeled total.

    The final bare amount needs both the printed total heading's column and the
    exact component equation. An equal amount elsewhere does not acquire a role.
    """
    result = set()
    for start, line in enumerate(page):
        if line.normalized != "Citi Simplicity Lifetime Savings":
            continue
        window = range(start + 1, min(start + 22, len(page)))
        interest = [(i, re.fullmatch(rf"Interest: (?P<amount>{_MONEY})", page[i].normalized)) for i in window]
        fee = [
            (i, re.fullmatch(rf"Fees charged No Late Fee: (?P<amount>{_MONEY})", page[i].normalized)) for i in window
        ]
        interest = [(i, m) for i, m in interest if m is not None]
        fee = [(i, m) for i, m in fee if m is not None]
        total_header = [
            i
            for i in window
            if page[i].normalized
            == (
                "Your Annual Percentage Rate (APR) is the annual interest rate on your account. "
                "CITI SIMPLICITY LIFETIME SAVINGS:"
            )
        ]
        if len(interest) != 1 or len(fee) != 1 or len(total_header) != 1:
            continue
        total_index = total_header[0] + 1
        if total_index >= len(page) or re.fullmatch(_MONEY, page[total_index].normalized) is None:
            continue
        header_column = line.raw.find("Citi Simplicity Lifetime Savings")
        total_column = page[total_index].raw.find("$")
        if header_column < 0 or not header_column <= total_column < header_column + len(
            "CITI SIMPLICITY LIFETIME SAVINGS:"
        ):
            continue
        if not start < interest[0][0] < fee[0][0] < total_header[0]:
            continue
        if any(
            page[i].raw.find(label) < header_column
            for i, label in ((interest[0][0], "Interest:"), (fee[0][0], "No Late Fee:"))
        ):
            continue
        try:
            interest_minor, fee_minor, total_minor = (
                usd_symbol_minor_v1(raw.replace(" ", ""))
                for raw in (interest[0][1]["amount"], fee[0][1]["amount"], page[total_index].normalized)
            )
        except ValueError:
            # Shape recognition does not authorize conversion outside the money
            # operation's admitted syntax/range. Retain the unresolved lines.
            continue
        if interest_minor + fee_minor == total_minor:
            result.update((interest[0][0], fee[0][0], total_index))
    return result


def classify_legacy_citi_money(
    dispositions: tuple[SourceDisposition, ...], lines: PDFLineEvidence
) -> tuple[SourceDisposition, ...]:
    """Refine only unclassified full lines, preserving locations and raw values."""
    pages: dict[int, list[PageLine]] = {}
    for line in lines.lines:
        if line.normalized:
            pages.setdefault(line.page, []).append(line)
    positions = {(line.page, line.line): (page, index) for page in pages.values() for index, line in enumerate(page)}
    repayment = _repayment_positions(pages.get(1, []))
    savings = {number: _savings_positions(page) for number, page in pages.items() if number > 1}
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
            if index in repayment:
                code = "citi_repayment_example"
            elif _REPAYMENT_MINIMUM_WITH_HEADER.fullmatch(raw) and _repayment_headings(page, index):
                code = "citi_repayment_example"
            elif _SUMMARY.fullmatch(raw) or _parallel_summary(raw):
                code = "citi_account_summary"
            elif (
                _PAYMENT.fullmatch(raw)
                or _AUTOPAY.fullmatch(raw)
                or _COUPON.fullmatch(raw)
                or _OVERLIMIT.fullmatch(raw)
            ):
                code = "citi_payment_information"
            elif _LATE_WARNING.fullmatch(raw):
                code = "citi_credit_terms"
            elif (
                _CREDIT.fullmatch(raw)
                or _CASH_LIMIT.fullmatch(raw)
                or _COUNSELING_CREDIT.fullmatch(raw)
                or re.fullmatch(
                    rf"For information about credit counseling services, call [0-9-]+\. "
                    rf"Available (?:Revolving )?credit {_DISCLOSURE_MONEY}",
                    raw,
                    re.I,
                )
                or re.fullmatch(
                    rf"charges using this card balance shown on the paying an estimated "
                    rf"(?:Revolving )?Credit limit {_DISCLOSURE_MONEY}",
                    raw,
                    re.I,
                )
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
        elif index in savings.get(item.location.page, set()):
            code = "citi_savings_information"
        elif (
            _MINIMUM_INTEREST.fullmatch(raw)
            or _CONDITIONAL_LATE_FEE.fullmatch(raw)
            or re.fullmatch(_CONDITIONAL_LATE_FEE.pattern + r" Plus Tier", raw, re.I)
            or re.fullmatch(_CONDITIONAL_LATE_FEE.pattern + r" " + _ANNUAL_PURCHASES.pattern, raw, re.I)
            or (
                _LEGAL_PURCHASE.fullmatch(raw)
                and index > 0
                and page[index - 1].normalized
                == (
                    "take the balance at the end of the previous day, add the interest on the previous "
                    "your current mailing address, and the purchase price must have been more"
                )
                and index + 1 < len(page)
                and page[index + 1].normalized
                == (
                    "adjustments. The Balance Subject to Interest Rate is the average of the daily "
                    "an advertisement we mailed to you, or if we own the company that sold you"
                )
            )
        ):
            code = "citi_credit_terms"
        elif (
            _APR.fullmatch(raw)
            or _apr_with_known_parallel_text(raw)
            or _ANNUAL_PURCHASES.fullmatch(raw)
            or re.fullmatch(
                rf"and the estimated interest that would have been assessed against these same "
                rf"Minimum Annual Purchases: {_DISCLOSURE_MONEY}",
                raw,
                re.I,
            )
            or (
                _APR_TABLE_ROW.fullmatch(raw)
                and any(
                    line.normalized.startswith("Standard Purch ") and _APR.fullmatch(line.normalized)
                    for line in page[max(0, index - 3) : index]
                )
                and any(
                    line.normalized.startswith("Standard Adv ") and _APR.fullmatch(line.normalized)
                    for line in page[index + 1 : index + 7]
                )
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

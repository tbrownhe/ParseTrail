"""Printed Wells personal-loan allocations without synthetic periods or payments."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from parsetrail.core.source_evidence import (
    ComponentEvidence,
    DateValue,
    MoneyValue,
    ObservationEvidence,
    PdfLine,
    SourceDisposition,
    SourceEvidence,
    SourceFragment,
    StatementAccount,
    StatementPayload,
    TextValue,
)
from parsetrail.core.v2_money_operations import usd_symbol_minor_v1
from parsetrail.core.v2_pdf_lines import PageLine, PDFLineEvidence
from parsetrail.core.v2_pdf_routing import PDFRouting

ENGINE_VERSION = "wells-loan-lines-pilot-2"
# Additional source-role proof does not change the existing financial rows.
OBSERVATION_ID_VERSION = "wells-loan-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MONEY = r"\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.\d{2}"
DATE = r"\d{2}/\d{2}/\d{2}"
DATE_START = re.compile(rf"^{DATE}\s")
_AUXILIARY_DATE = r"\d{2}/\d{2}/(?:\d{4}|\d{2})"
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
_FINANCIAL_OR_DATE = re.compile(
    r"[$€£¥]|(?<!\d)\d[\d,]*\.\d{2}(?!\d)"
    r"|(?<!\d)\d{1,4}[-/]\d{1,2}(?:[-/]\d{1,4})?(?!\d)"
    rf"|\b{_MONTH}[ .-]*\d{{1,2}}(?:st|nd|rd|th)?(?:[, .-]*\d{{4}})?\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?[ .-]*{_MONTH}(?:[, .-]*\d{{4}})?\b"
    rf"|\b\d{{4}}[ .-]*{_MONTH}[ .-]*\d{{1,2}}\b",
    re.I,
)
_EMPTY_REGISTER_LABEL = "No transactions within this billing cycle."


def _empty_register_dispositions(lines, opening_line, closing_line, account, definition):
    """Prove an explicitly empty register and audit its other financial tokens.

    Equal balances alone never qualify. Printed payment/accrual/coupon context
    remains separate from principal transactions and does not authorize posting.
    """
    positions = {line.line_id: index for index, line in enumerate(lines.lines)}
    opening, closing = positions[opening_line.line_id], positions[closing_line.line_id]
    headings = [
        index
        for index in range(max(0, opening - 5), opening)
        if lines.lines[index].normalized == "Effective Transaction Principal"
    ]
    if len(headings) != 1 or not 3 <= closing - headings[0] <= 10:
        return ()
    first = headings[0]
    block = lines.lines[first : closing + 1]
    if (
        any(line.page != opening_line.page for line in block)
        or re.fullmatch(rf"{re.escape(definition.opening_label)} {MONEY}", opening_line.normalized) is None
        or re.fullmatch(rf"{DATE} {re.escape(definition.closing_label)} {MONEY}\*", closing_line.normalized) is None
        or not any(line.normalized == "Date Description Amount Balance" for line in block[: opening - first])
        or lines.lines[closing - 1].normalized != _EMPTY_REGISTER_LABEL
        or not 1 <= closing - opening <= 3
    ):
        return ()
    protected = {opening_line.line_id, closing_line.line_id}
    if any(_FINANCIAL_OR_DATE.search(line.normalized) for line in block if line.line_id not in protected):
        return ()
    proof = SourceDisposition(
        code="wells_loan_empty_register",
        location=PdfLine(kind="pdf_line", page=block[0].page, line=block[0].line, end_line=block[-1].line),
        raw_values=tuple(line.raw for line in block),
    )
    result = [proof]
    summary_labels = (
        "Per Diem Amount",
        "Total Amount Due",
        "Total Payments Received",
        "Principal Payment",
        "Interest Payment",
        "Interest Accrued",
        "Principal Balance",
        "Principal",
        "Interest",
    )
    summary_money = re.compile(rf"\b(?:{'|'.join(re.escape(label) for label in summary_labels)})\s+{MONEY}(?=\s|$)")
    summary_date = re.compile(
        rf"\b(?:Statement Date|Maturity Date|Payment Due Date)\s+(?P<date>{_AUXILIARY_DATE})(?=\s|$)"
    )
    identity = re.compile(rf"\bAccount Number\s+{re.escape(account)}\b")
    rate = re.compile(r"\bInterest Rate\s+\d{1,2}\.\d{1,4}%(?=\s|$)")
    coupon_starts = [
        index
        for index, line in enumerate(lines.lines)
        if (
            "your account is on autopay." in line.normalized.casefold()
            or "your account is on automatic payment." in line.normalized.casefold()
        )
        and "Payment Due Date" in line.normalized
    ]
    coupon = set()
    if len(coupon_starts) == 1:
        start = coupon_starts[0]
        window = lines.lines[start : start + 4]
        text = " ".join(line.normalized for line in window)
        if (
            len(window) == 4
            and all(line.page == window[0].page for line in window)
            and identity.search(text)
            and re.search(rf"\bautomatic payment of {MONEY}", text)
            and re.search(rf"withdrawn from your account on {_AUXILIARY_DATE}\.", text)
            and re.search(rf"Total Amount Due {MONEY}", text)
            and (
                "your account is on automatic payment." in text.casefold()
                or re.search(rf"automatic payment amount of {MONEY}", text)
            )
        ):
            coupon = {line.line_id for line in window}
    coupon_patterns = (
        identity,
        summary_date,
        re.compile(rf"\bautomatic payment of {MONEY}"),
        re.compile(rf"withdrawn from your account on (?P<date>{_AUXILIARY_DATE})\."),
        re.compile(rf"automatic payment amount of {MONEY}"),
        re.compile(rf"Total Amount Due {MONEY}"),
    )
    late = re.compile(rf"On or after (?P<date>{_AUXILIARY_DATE}), a late charge of {MONEY}(?=\s|$)")
    total = re.compile(rf"Total of Payments Received Since the Last Statement: {MONEY}(?=\s|$)")
    charges_prefixes = (
        "Since the last statement, a late charge, other charges and fees, or some combination of them, were incurred",
        "Since the last statement, a Late Charge and /or Other Charges and Fees were incurred",
    )
    charges = re.compile(
        rf"(?:{'|'.join(re.escape(prefix) for prefix in charges_prefixes)}) in the amount of {MONEY}\Z"
    )
    block_ids = {line.line_id for line in block}
    for index, line in enumerate(lines.lines):
        if line.line_id in block_ids or not _FINANCIAL_OR_DATE.search(line.normalized):
            continue
        raw = line.normalized
        known = False
        try:
            if line.line_id in coupon:
                for pattern in coupon_patterns:
                    for match in pattern.finditer(raw):
                        if "date" in match.groupdict():
                            _auxiliary_date(match["date"])
                    raw = pattern.sub("", raw)
                known = not _FINANCIAL_OR_DATE.search(raw)
            elif total.match(raw):
                known = not _FINANCIAL_OR_DATE.search(raw[total.match(raw).end() :])
            elif any(
                start >= 0
                and all(previous.page == line.page for previous in lines.lines[start:index])
                and charges.fullmatch(" ".join(previous.normalized for previous in lines.lines[start : index + 1]))
                for start in (index - 1, index - 2)
            ):
                known = True
            elif late.match(raw):
                match = late.match(raw)
                _auxiliary_date(match["date"])
                known = not _FINANCIAL_OR_DATE.search(raw[match.end() :])
            elif index < first:
                strong_fields = bool(summary_date.search(raw) or identity.search(raw))
                for match in summary_date.finditer(raw):
                    _auxiliary_date(match["date"])
                raw = identity.sub("", summary_date.sub("", rate.sub("", summary_money.sub("", raw))))
                known = not _FINANCIAL_OR_DATE.search(raw) if strong_fields else not raw.strip(" :*")
        except WellsLoanError:
            known = False
        if known:
            try:
                for match in re.finditer(MONEY, line.normalized):
                    _money(match.group())
            except WellsLoanError:
                known = False
        result.append(
            SourceDisposition(
                code="loan_payment_information" if known else "wells_loan_empty_exterior_unclassified",
                location=_location(line),
                raw_values=(line.raw,),
            )
        )
    return tuple(result)


class WellsLoanError(ValueError):
    """Redacted refusal of incomplete Wells loan source evidence."""


class WellsLoanDefinition(BaseModel):
    routing: PDFRouting
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["printed_principal_allocations_v1"]
    date_format: Literal["MM/DD/YY"]
    money_format: Literal["usd_symbol_2dp"]
    balance_scope: Literal["principal_component"]
    account_label: str = Field(min_length=1, max_length=80)
    statement_date_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    interest_label: str = Field(min_length=1, max_length=80)
    principal_label: str = Field(min_length=1, max_length=80)
    max_activity_rows: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def valid_labels(self) -> WellsLoanDefinition:
        labels = (
            self.account_label,
            self.statement_date_label,
            self.opening_label,
            self.closing_label,
            self.interest_label,
            self.principal_label,
        )
        if len(set(labels)) != len(labels) or any(label != label.strip() or "\n" in label for label in labels):
            raise ValueError("invalid loan labels")
        return self


def load_definition(data: bytes) -> tuple[WellsLoanDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise WellsLoanError("definition_size")
    try:
        definition = WellsLoanDefinition.model_validate_json(data)
    except ValidationError:
        raise WellsLoanError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _money(raw: str) -> int:
    if re.fullmatch(MONEY, raw) is None:
        raise WellsLoanError("invalid_loan_money")
    try:
        return usd_symbol_minor_v1(raw)
    except ValueError:
        raise WellsLoanError("invalid_loan_money") from None


def _date(raw: str):
    try:
        parsed = datetime.strptime(raw, "%m/%d/%y").date()
    except ValueError:
        raise WellsLoanError("invalid_loan_date") from None
    if parsed.strftime("%m/%d/%y") != raw:
        raise WellsLoanError("invalid_loan_date")
    return parsed


def _auxiliary_date(raw: str):
    """Payment/fee metadata may print four-digit years; activity remains MM/DD/YY."""
    format = "%m/%d/%Y" if len(raw) == 10 else "%m/%d/%y"
    try:
        parsed = datetime.strptime(raw, format).date()
    except ValueError:
        raise WellsLoanError("invalid_loan_context_date") from None
    if parsed.strftime(format) != raw:
        raise WellsLoanError("invalid_loan_context_date")
    return parsed


def _one(matches, code: str):
    if len(matches) != 1:
        raise WellsLoanError(code)
    return matches[0]


def parse_wells_loan(definition_bytes: bytes, lines: PDFLineEvidence) -> SourceEvidence:
    """Preserve printed interest/principal lines and verify only principal balance."""
    definition, definition_hash = load_definition(definition_bytes)
    account_pattern = re.compile(rf"\b{re.escape(definition.account_label)}\s+(?P<account>\d{{8,20}})\b")
    date_pattern = re.compile(rf"\b{re.escape(definition.statement_date_label)}\s+(?P<date>{DATE})(?=\s|$)")
    opening_pattern = re.compile(rf"\b{re.escape(definition.opening_label)}\s+(?P<amount>{MONEY})(?=\s|$)")
    closing_pattern = re.compile(
        rf"^(?P<date>{DATE})\s+{re.escape(definition.closing_label)}\s+(?P<amount>{MONEY})\*(?=\s|$)"
    )
    row_pattern = re.compile(
        rf"^(?P<date>{DATE})\s+(?P<label>{re.escape(definition.interest_label)}|"
        rf"{re.escape(definition.principal_label)})\s+(?P<amount>{MONEY})$"
    )
    accounts = [(line, match) for line in lines.lines if (match := account_pattern.search(line.normalized))]
    if not accounts or len({match["account"] for _, match in accounts}) != 1:
        raise WellsLoanError("missing_or_ambiguous_account")
    account_line, account_match = accounts[0]
    statement_line, statement_match = _one(
        [(line, match) for line in lines.lines if (match := date_pattern.search(line.normalized))],
        "missing_or_ambiguous_statement_date",
    )
    opening_line, opening_match = _one(
        [(line, match) for line in lines.lines if (match := opening_pattern.search(line.normalized))],
        "missing_or_ambiguous_opening",
    )
    closings = [
        (index, line, match)
        for index, line in enumerate(lines.lines)
        if (match := closing_pattern.match(line.normalized))
    ]
    closing_index, closing_line, closing_match = _one(closings, "missing_or_ambiguous_closing")
    end = _date(statement_match["date"])
    if _date(closing_match["date"]) != end:
        raise WellsLoanError("closing_date_mismatch")
    opening, closing = -_money(opening_match["amount"]), -_money(closing_match["amount"])
    rows = []
    occurrences: Counter[tuple[str, str, int]] = Counter()
    for line in lines.lines[:closing_index]:
        if not DATE_START.match(line.normalized):
            continue
        match = row_pattern.fullmatch(line.normalized)
        if match is None:
            raise WellsLoanError("unresolved_dated_loan_row")
        if len(rows) >= definition.max_activity_rows:
            raise WellsLoanError("activity_row_limit")
        date = _date(match["date"])
        if date > end:
            raise WellsLoanError("activity_after_statement_date")
        amount = _money(match["amount"])
        label = match["label"]
        role = "principal" if label == definition.principal_label else "interest"
        location = _location(line)
        key = (date.isoformat(), label, amount)
        occurrence = occurrences[key]
        occurrences[key] += 1
        money = MoneyValue(raw=match["amount"], minor=amount, provenance="observed", locations=(location,))
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(
                    f"{definition_hash}:{OBSERVATION_ID_VERSION}:{line.line_id}".encode()
                ).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=account_match["account"],
                source_account_form="full",
                date_role="activity_date",
                date=DateValue(raw=match["date"], iso=date.isoformat(), provenance="observed", locations=(location,)),
                transaction_date=None,
                description=TextValue(raw=label, text=label, provenance="observed", locations=(location,)),
                amount=money,
                running_balance=None,
                components=(ComponentEvidence(role=role, amount=money),),
                fragments=(SourceFragment(channel="loan_allocation_line", location=location, raw_values=(line.raw,)),),
            )
        )
    if opening + sum(row.amount.minor for row in rows if row.components[0].role == "principal") != closing:
        raise WellsLoanError("printed_principal_equation")
    dispositions = tuple(
        SourceDisposition(code="repeated_account_identity", location=_location(line), raw_values=(line.raw,))
        for line, _ in accounts[1:]
    )
    if not rows and opening == closing:
        dispositions += _empty_register_dispositions(
            lines, opening_line, closing_line, account_match["account"], definition
        )
    return SourceEvidence(
        schema_version=2,
        source_sha256=lines.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION,
        extractor_version=lines.extraction_library + "+" + lines.adapter_version,
        payload=StatementPayload(
            kind="statement",
            start=DateValue(raw=None, iso=None, provenance="unknown", locations=()),
            end=DateValue(
                raw=statement_match["date"],
                iso=end.isoformat(),
                provenance="observed",
                locations=(_location(statement_line), _location(closing_line)),
            ),
            accounts=(
                StatementAccount(
                    source_identity=account_match["account"],
                    source_identity_form="full",
                    balance_scope="principal_component",
                    identity_locations=tuple(_location(line) for line, _ in accounts[:16]),
                    opening=MoneyValue(
                        raw=opening_match["amount"],
                        minor=opening,
                        provenance="observed",
                        locations=(_location(opening_line),),
                    ),
                    closing=MoneyValue(
                        raw=closing_match["amount"],
                        minor=closing,
                        provenance="observed",
                        locations=(_location(closing_line),),
                    ),
                    rows=tuple(rows),
                ),
            ),
            dispositions=dispositions,
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )

"""Finite two-date card activity with a printed liability balance equation."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from parsetrail.core.source_evidence import (
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
from parsetrail.core.v2_money_operations import usd_trailing_credit_2dp_minor_v1
from parsetrail.core.v2_partial_dates import PartialDateError, resolve_month_day
from parsetrail.core.v2_pdf_lines import PageLine, PDFLineEvidence
from parsetrail.core.v2_pdf_routing import PDFRouting

ENGINE_VERSION = "two-date-card-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
DATE_PREFIX = re.compile(r"^\d{2}/\d{2}\b")
ROW = re.compile(
    r"^(?P<transaction>\d{2}/\d{2})\s+(?P<posting>\d{2}/\d{2})\s+"
    r"(?P<description>.+?)\s+(?P<amount>\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}-?)$"
)


class TwoDateCardError(ValueError):
    """Redacted refusal of unsupported printed activity."""


class TwoDateCardDefinition(BaseModel):
    routing: PDFRouting
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["two_date_card_activity_v1"]
    date_format: Literal["MM/DD+MM/DD/YY"]
    money_format: Literal["usd_2dp_trailing_credit"]
    amount_direction: Literal["invert_for_liability"]
    account_label: str = Field(min_length=1, max_length=80)
    closing_date_label: str = Field(min_length=1, max_length=80)
    cycle_days_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    section_start: str = Field(min_length=1, max_length=80)
    transaction_post_header: str = Field(min_length=1, max_length=80)
    description_amount_header: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def finite_labels(self) -> TwoDateCardDefinition:
        labels = (
            self.account_label,
            self.closing_date_label,
            self.cycle_days_label,
            self.opening_label,
            self.closing_label,
            self.section_start,
            self.transaction_post_header,
            self.description_amount_header,
        )
        if len(set(labels)) != len(labels) or any(
            label != label.strip() or "\n" in label or "\r" in label for label in labels
        ):
            raise ValueError("invalid labels")
        return self


def load_definition(data: bytes) -> tuple[TwoDateCardDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise TwoDateCardError("definition_size")
    try:
        definition = TwoDateCardDefinition.model_validate_json(data)
    except ValidationError:
        raise TwoDateCardError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _one(matches: list[tuple[PageLine, re.Match[str]]], code: str) -> tuple[PageLine, re.Match[str]]:
    if len(matches) != 1:
        raise TwoDateCardError(code)
    return matches[0]


def _money(raw: str) -> int:
    try:
        return usd_trailing_credit_2dp_minor_v1(raw)
    except ValueError:
        raise TwoDateCardError("invalid_card_money") from None


def parse_two_date_card(definition_bytes: bytes, lines: PDFLineEvidence) -> SourceEvidence:
    """Bind both printed dates, source sign and the independent liability chain."""
    definition, definition_hash = load_definition(definition_bytes)
    account_pattern = re.compile(
        rf"\b{re.escape(definition.account_label)}\s*(?P<account>[0-9X]{{4}}(?:\s+[0-9X]{{4}}){{3}})\b"
    )
    date_pattern = re.compile(rf"\b{re.escape(definition.closing_date_label)}\s+(?P<date>\d{{2}}/\d{{2}}/\d{{2}})\b")
    days_pattern = re.compile(rf"\b{re.escape(definition.cycle_days_label)}\s+(?P<days>\d{{1,2}})\b")
    balance_pattern = re.compile(
        rf"\b{re.escape(definition.opening_label)}\s+(?P<opening>\$[0-9,]+\.[0-9]{{2}})\s+"
        rf"{re.escape(definition.closing_label)}\s+(?P<closing>\$[0-9,]+\.[0-9]{{2}})\b"
    )
    accounts = [(line, match) for line in lines.lines if (match := account_pattern.search(line.normalized))]
    account_values = {"".join(match["account"].split()) for _, match in accounts}
    if not accounts or len(account_values) != 1 or "X" not in next(iter(account_values)):
        raise TwoDateCardError("missing_or_ambiguous_account")
    account = next(iter(account_values))
    date_line, date_match = _one(
        [(line, match) for line in lines.lines if (match := date_pattern.search(line.normalized))],
        "missing_or_ambiguous_closing_date",
    )
    days_line, days_match = _one(
        [(line, match) for line in lines.lines if (match := days_pattern.search(line.normalized))],
        "missing_or_ambiguous_cycle_days",
    )
    balance_line, balance_match = _one(
        [(line, match) for line in lines.lines if (match := balance_pattern.search(line.normalized))],
        "missing_or_ambiguous_balances",
    )
    try:
        month, day, year = map(int, date_match["date"].split("/"))
        end = datetime(2000 + year, month, day).date()
        days = int(days_match["days"])
    except ValueError:
        raise TwoDateCardError("invalid_period") from None
    if not 2 <= days <= 40:
        raise TwoDateCardError("invalid_period")
    start = end - timedelta(days=days - 1)
    opening_raw, closing_raw = balance_match["opening"], balance_match["closing"]
    opening, closing = -_money(opening_raw), -_money(closing_raw)
    section = [index for index, line in enumerate(lines.lines) if line.normalized == definition.section_start]
    if len(section) != 1:
        raise TwoDateCardError("missing_or_ambiguous_activity_section")
    section_index = section[0]
    header_lines = lines.lines[section_index + 1 : section_index + 8]
    if not any(line.normalized == definition.transaction_post_header for line in header_lines) or not any(
        line.normalized == definition.description_amount_header for line in header_lines
    ):
        raise TwoDateCardError("missing_activity_columns")
    candidates = [line for line in lines.lines[section_index + 1 :] if DATE_PREFIX.match(line.normalized)]
    if not candidates:
        raise TwoDateCardError("missing_activity_rows")
    rows = []
    occurrences: Counter[tuple[str, str, int, str]] = Counter()
    for line in candidates:
        if len(line.normalized) > 512 or (match := ROW.fullmatch(line.normalized)) is None:
            raise TwoDateCardError("unresolved_dated_line")
        try:
            transaction = resolve_month_day(match["transaction"], start, end)
            posting = resolve_month_day(match["posting"], start, end)
        except PartialDateError:
            raise TwoDateCardError("invalid_activity_date") from None
        if not start <= posting <= end:
            raise TwoDateCardError("posting_outside_period")
        source_amount = _money(match["amount"])
        amount = -source_amount
        description = match["description"]
        location = _location(line)
        key = (transaction.isoformat(), posting.isoformat(), amount, description)
        occurrence = occurrences[key]
        occurrences[key] += 1
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(f"{definition_hash}:{ENGINE_VERSION}:{line.line_id}".encode()).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=account,
                source_account_form="opaque",
                date_role="posting_date",
                date=DateValue(
                    raw=None, iso=posting.isoformat(), provenance="derived", locations=(location, _location(date_line))
                ),
                transaction_date=DateValue(
                    raw=None,
                    iso=transaction.isoformat(),
                    provenance="derived",
                    locations=(location, _location(date_line)),
                ),
                description=TextValue(raw=description, text=description, provenance="observed", locations=(location,)),
                amount=MoneyValue(raw=match["amount"], minor=amount, provenance="observed", locations=(location,)),
                running_balance=None,
                components=(),
                fragments=(SourceFragment(channel="two_date_card_line", location=location, raw_values=(line.raw,)),),
            )
        )
    if opening + sum(row.amount.minor for row in rows) != closing:
        raise TwoDateCardError("printed_card_balance_equation")
    dispositions = tuple(
        SourceDisposition(code="activity_header", location=_location(line), raw_values=(line.raw,))
        for line in header_lines
        if line.normalized in {definition.transaction_post_header, definition.description_amount_header}
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
            start=DateValue(
                raw=None,
                iso=start.isoformat(),
                provenance="derived",
                locations=(_location(date_line), _location(days_line)),
            ),
            end=DateValue(
                raw=date_match["date"], iso=end.isoformat(), provenance="observed", locations=(_location(date_line),)
            ),
            accounts=(
                StatementAccount(
                    source_identity=account,
                    source_identity_form="opaque",
                    balance_scope="account_total",
                    identity_locations=tuple(_location(line) for line, _ in accounts),
                    opening=MoneyValue(
                        raw=opening_raw, minor=opening, provenance="observed", locations=(_location(balance_line),)
                    ),
                    closing=MoneyValue(
                        raw=closing_raw, minor=closing, provenance="observed", locations=(_location(balance_line),)
                    ),
                    rows=tuple(rows),
                ),
            ),
            dispositions=dispositions,
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )

"""Finite account-value summary operation over bounded PDF page lines."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime
from typing import Literal

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
from parsetrail.core.v2_pdf_lines import PageLine, PDFLineEvidence
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from devtools.parser_engine_pilot.money_operations import usd_or_decimal_2dp_minor_v1

ENGINE_VERSION = "investment-summary-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
PERIOD = re.compile(r"(?P<start>[A-Z][a-z]+ \d{1,2}, \d{4}) - (?P<end>[A-Z][a-z]+ \d{1,2}, \d{4})\Z")


class InvestmentSummaryError(ValueError):
    """Redacted refusal of a summary that cannot be represented exactly."""


class InvestmentSummaryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["printed_account_value_summary_v1"]
    period_format: Literal["Month D, YYYY - Month D, YYYY"]
    money_format: Literal["usd_or_decimal_2dp_or_dash"]
    account_format: Literal["NNN-NNNNNN"]
    account_label: str = Field(min_length=1, max_length=80)
    summary_header: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    row_labels: tuple[str, ...] = Field(min_length=1, max_length=8)
    valuation_label: str = Field(min_length=1, max_length=80)
    summary_window_lines: int = Field(ge=5, le=20)

    @model_validator(mode="after")
    def finite_labels(self) -> InvestmentSummaryDefinition:
        labels = (self.account_label, self.summary_header, self.opening_label, self.closing_label, *self.row_labels)
        if (
            self.valuation_label not in self.row_labels
            or len(set(labels)) != len(labels)
            or any(label != label.strip() or "\n" in label or "\r" in label for label in labels)
        ):
            raise ValueError("invalid labels")
        return self


def load_definition(data: bytes) -> tuple[InvestmentSummaryDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise InvestmentSummaryError("definition_size")
    try:
        definition = InvestmentSummaryDefinition.model_validate_json(data)
    except ValidationError:
        raise InvestmentSummaryError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _money(raw: str) -> int:
    if raw == "-":
        return 0
    try:
        return usd_or_decimal_2dp_minor_v1(raw)
    except ValueError:
        raise InvestmentSummaryError("invalid_summary_money") from None


def _two_columns(line: PageLine, label: str, *, footnote: str = "") -> tuple[str, str]:
    prefix = label + ((" " + footnote) if footnote else "") + " "
    if not line.normalized.startswith(prefix):
        raise InvestmentSummaryError("unexpected_summary_label")
    values = line.normalized[len(prefix) :].split()
    if len(values) != 2:
        raise InvestmentSummaryError("summary_column_count")
    _money(values[0])
    _money(values[1])
    return values[0], values[1]


def parse_investment_summary(definition_bytes: bytes, lines: PDFLineEvidence) -> SourceEvidence:
    """Preserve printed period components as summaries, never as dated activity."""
    definition, definition_hash = load_definition(definition_bytes)
    first_page = tuple(line for line in lines.lines if line.page == 1)
    periods = [(line, match) for line in first_page[:10] if (match := PERIOD.fullmatch(line.normalized))]
    account_pattern = re.compile(rf"\b{re.escape(definition.account_label)}\s*(?P<account>[0-9]{{3}}-[0-9]{{6}})\b")
    accounts = [(line, match) for line in first_page[:10] if (match := account_pattern.search(line.normalized))]
    headers = [line for line in first_page[:25] if line.normalized == definition.summary_header]
    if len(periods) != 1 or len(accounts) != 1 or len(headers) != 1:
        raise InvestmentSummaryError("missing_or_ambiguous_summary_anchor")
    period_line, period_match = periods[0]
    account_line, account_match = accounts[0]
    try:
        start = datetime.strptime(period_match["start"], "%B %d, %Y").date()
        end = datetime.strptime(period_match["end"], "%B %d, %Y").date()
    except ValueError:
        raise InvestmentSummaryError("invalid_period") from None
    if not start < end or (end - start).days > 100:
        raise InvestmentSummaryError("invalid_period")
    header = headers[0]
    header_index = next(index for index, line in enumerate(first_page) if line.line == header.line)
    window = first_page[header_index + 1 : header_index + definition.summary_window_lines + 1]
    if len(window) < 3 or not window[0].normalized.startswith(definition.opening_label + " "):
        raise InvestmentSummaryError("missing_opening")
    closing = [
        index for index, line in enumerate(window) if line.normalized.startswith(definition.closing_label + " ** ")
    ]
    if len(closing) != 1 or closing[0] < 2:
        raise InvestmentSummaryError("missing_or_ambiguous_closing")
    opening_line = window[0]
    closing_line = window[closing[0]]
    raw_opening, opening_ytd = _two_columns(opening_line, definition.opening_label)
    raw_closing, closing_ytd = _two_columns(closing_line, definition.closing_label, footnote="**")
    opening = _money(raw_opening)
    closing_minor = _money(raw_closing)
    account = account_match["account"]
    rows = []
    dispositions = [
        SourceDisposition(code="year_to_date_column", location=_location(opening_line), raw_values=(opening_ytd,)),
        SourceDisposition(code="year_to_date_column", location=_location(closing_line), raw_values=(closing_ytd,)),
    ]
    occurrences: Counter[tuple[str, int]] = Counter()
    seen_labels = set()
    for line in window[1 : closing[0]]:
        parts = line.normalized.rsplit(" ", 2)
        if len(parts) != 3:
            raise InvestmentSummaryError("unresolved_summary_line")
        raw_label, raw_amount, ytd = parts
        label = raw_label.removesuffix(" *")
        if label not in definition.row_labels or label in seen_labels:
            raise InvestmentSummaryError("unresolved_summary_line")
        if label == definition.valuation_label and raw_label != label + " *":
            raise InvestmentSummaryError("missing_valuation_marker")
        if label != definition.valuation_label and raw_label != label:
            raise InvestmentSummaryError("unexpected_summary_marker")
        seen_labels.add(label)
        amount = _money(raw_amount)
        _money(ytd)
        location = _location(line)
        key = (label, amount)
        occurrence = occurrences[key]
        occurrences[key] += 1
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(f"{definition_hash}:{ENGINE_VERSION}:{line.line_id}".encode()).hexdigest(),
                occurrence=occurrence,
                row_role="period_summary",
                source_account=account,
                source_account_form="full",
                date_role="statement_period_end",
                date=DateValue(
                    raw=None, iso=end.isoformat(), provenance="derived", locations=(location, _location(period_line))
                ),
                transaction_date=None,
                description=TextValue(raw=raw_label, text=label, provenance="observed", locations=(location,)),
                amount=MoneyValue(raw=raw_amount, minor=amount, provenance="observed", locations=(location,)),
                running_balance=None,
                components=(),
                fragments=(SourceFragment(channel="account_value_summary", location=location, raw_values=(line.raw,)),),
            )
        )
        dispositions.append(SourceDisposition(code="year_to_date_column", location=location, raw_values=(ytd,)))
    dispositions.extend(
        SourceDisposition(code="summary_window_tail_unclassified", location=_location(line), raw_values=(line.raw,))
        for line in window[closing[0] + 1 :]
    )
    if not rows or opening + sum(row.amount.minor for row in rows) != closing_minor:
        raise InvestmentSummaryError("printed_summary_equation")
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
                raw=period_match["start"],
                iso=start.isoformat(),
                provenance="observed",
                locations=(_location(period_line),),
            ),
            end=DateValue(
                raw=period_match["end"], iso=end.isoformat(), provenance="observed", locations=(_location(period_line),)
            ),
            accounts=(
                StatementAccount(
                    source_identity=account,
                    source_identity_form="full",
                    balance_scope="account_total",
                    identity_locations=(_location(account_line),),
                    opening=MoneyValue(
                        raw=raw_opening, minor=opening, provenance="observed", locations=(_location(opening_line),)
                    ),
                    closing=MoneyValue(
                        raw=raw_closing,
                        minor=closing_minor,
                        provenance="observed",
                        locations=(_location(closing_line),),
                    ),
                    rows=tuple(rows),
                ),
            ),
            dispositions=tuple(dispositions),
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )

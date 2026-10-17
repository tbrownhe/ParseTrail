"""Finite account-value summary with one printed period column and unresolved tails."""

from __future__ import annotations

import hashlib
import re
import unicodedata
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

from devtools.parser_engine_pilot.money_operations import usd_symbol_minor_v1

ENGINE_VERSION = "single-column-summary-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MONEY = re.compile(r"-?\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}")


class SingleColumnSummaryError(ValueError):
    """Redacted refusal of unsupported account-value source evidence."""


class SingleColumnSummaryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["single_column_value_summary_v1"]
    period_format: Literal["MM/DD/YYYY - MM/DD/YYYY"]
    money_format: Literal["signed_usd_2dp"]
    identity_format: Literal["six_digit_plan_id"]
    period_label: str = Field(min_length=1, max_length=80)
    identity_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    row_labels: tuple[str, ...] = Field(min_length=1, max_length=8)
    summary_window_lines: int = Field(ge=4, le=20)

    @model_validator(mode="after")
    def finite_labels(self) -> SingleColumnSummaryDefinition:
        labels = (self.period_label, self.identity_label, self.opening_label, self.closing_label, *self.row_labels)
        if len(set(labels)) != len(labels) or any(
            label != label.strip() or "\n" in label or "\r" in label for label in labels
        ):
            raise ValueError("invalid labels")
        return self


def load_definition(data: bytes) -> tuple[SingleColumnSummaryDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise SingleColumnSummaryError("definition_size")
    try:
        definition = SingleColumnSummaryDefinition.model_validate_json(data)
    except ValidationError:
        raise SingleColumnSummaryError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _date(raw: str):
    try:
        result = datetime.strptime(raw, "%m/%d/%Y").date()
    except ValueError:
        raise SingleColumnSummaryError("invalid_period") from None
    if result.strftime("%m/%d/%Y") != raw:
        raise SingleColumnSummaryError("invalid_period")
    return result


def _first_money(line: PageLine, label: str) -> tuple[str, int, str]:
    if not line.normalized.startswith(label + " "):
        raise SingleColumnSummaryError("missing_summary_label")
    rest = line.normalized[len(label) :].strip()
    match = MONEY.match(rest)
    if match is None:
        raise SingleColumnSummaryError("missing_summary_amount")
    raw = match.group()
    try:
        amount = usd_symbol_minor_v1(raw)
    except ValueError:
        raise SingleColumnSummaryError("invalid_summary_money") from None
    return raw, amount, rest[match.end() :].strip()


def parse_single_column_summary(definition_bytes: bytes, lines: PDFLineEvidence) -> SourceEvidence:
    """Retain printed period components with explicit unknown nonprimary columns."""
    definition, definition_hash = load_definition(definition_bytes)
    first_page = tuple(line for line in lines.lines if line.page == 1)
    period_pattern = re.compile(
        rf"^{re.escape(definition.period_label)}\s*(?P<start>\d{{2}}/\d{{2}}/\d{{4}})\s+-\s+"
        rf"(?P<end>\d{{2}}/\d{{2}}/\d{{4}})$"
    )
    identity_pattern = re.compile(rf"^{re.escape(definition.identity_label)}.*?\s+(?P<identity>\d{{6}})$")
    periods = [(line, match) for line in first_page[:12] if (match := period_pattern.fullmatch(line.normalized))]
    identities = [(line, match) for line in first_page[:15] if (match := identity_pattern.fullmatch(line.normalized))]
    if len(periods) != 1 or len(identities) != 1:
        raise SingleColumnSummaryError("missing_or_ambiguous_summary_anchor")
    period_line, period_match = periods[0]
    identity_line, identity_match = identities[0]
    start, end = _date(period_match["start"]), _date(period_match["end"])
    if not start < end or (end - start).days > 100:
        raise SingleColumnSummaryError("invalid_period")
    opening_lines = [line for line in first_page if line.normalized.startswith(definition.opening_label + " ")]
    closing_lines = [line for line in first_page if line.normalized.startswith(definition.closing_label + " ")]
    if len(opening_lines) != 1 or len(closing_lines) != 1:
        raise SingleColumnSummaryError("missing_or_ambiguous_balances")
    opening_line, closing_line = opening_lines[0], closing_lines[0]
    if (
        not opening_line.line < closing_line.line
        or closing_line.line - opening_line.line > definition.summary_window_lines
    ):
        raise SingleColumnSummaryError("summary_window_limit")
    opening_raw, opening, opening_tail = _first_money(opening_line, definition.opening_label)
    closing_raw, closing, closing_tail = _first_money(closing_line, definition.closing_label)
    account = identity_match["identity"]
    rows = []
    dispositions = []
    occurrences: Counter[tuple[str, int]] = Counter()
    for line in first_page[opening_line.line : closing_line.line - 1]:
        label = next((label for label in definition.row_labels if line.normalized.startswith(label + " ")), None)
        if label is None:
            dispositions.append(
                SourceDisposition(code="summary_window_unclassified", location=_location(line), raw_values=(line.raw,))
            )
            continue
        raw_amount, amount, tail = _first_money(line, label)
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
                source_account_form="opaque",
                date_role="statement_period_end",
                date=DateValue(
                    raw=None, iso=end.isoformat(), provenance="derived", locations=(location, _location(period_line))
                ),
                transaction_date=None,
                description=TextValue(raw=label, text=label, provenance="observed", locations=(location,)),
                amount=MoneyValue(raw=raw_amount, minor=amount, provenance="observed", locations=(location,)),
                running_balance=None,
                components=(),
                fragments=(SourceFragment(channel="account_value_summary", location=location, raw_values=(line.raw,)),),
            )
        )
        if tail:
            dispositions.append(SourceDisposition(code="summary_extra_column", location=location, raw_values=(tail,)))
    for line, tail in ((opening_line, opening_tail), (closing_line, closing_tail)):
        if tail:
            dispositions.append(
                SourceDisposition(code="summary_extra_column", location=_location(line), raw_values=(tail,))
            )
    if not rows or opening + sum(row.amount.minor for row in rows) != closing:
        raise SingleColumnSummaryError("printed_summary_equation")
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
                    source_identity_form="opaque",
                    balance_scope="account_total",
                    identity_locations=(_location(identity_line),),
                    opening=MoneyValue(
                        raw=opening_raw, minor=opening, provenance="observed", locations=(_location(opening_line),)
                    ),
                    closing=MoneyValue(
                        raw=closing_raw, minor=closing, provenance="observed", locations=(_location(closing_line),)
                    ),
                    rows=tuple(rows),
                ),
            ),
            dispositions=tuple(dispositions),
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )


class PlanLabelSummaryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["plan_label_value_summary_v1"]
    period_format: Literal["MM/DD/YYYY to MM/DD/YYYY"]
    money_format: Literal["signed_usd_2dp"]
    title: str = Field(min_length=1, max_length=80)
    printed_header: str = Field(min_length=1, max_length=80)
    browser_header: str = Field(min_length=1, max_length=80)
    summary_section_label: str = Field(min_length=1, max_length=80)
    period_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    row_labels: tuple[str, ...] = Field(min_length=1, max_length=20)
    summary_window_lines: int = Field(ge=3, le=20)

    @model_validator(mode="after")
    def finite_labels(self) -> PlanLabelSummaryDefinition:
        labels = (
            self.title,
            self.printed_header,
            self.browser_header,
            self.summary_section_label,
            self.period_label,
            self.opening_label,
            self.closing_label,
            *self.row_labels,
        )
        if len(set(labels)) != len(labels) or any(
            label != label.strip() or "\n" in label or "\r" in label for label in labels
        ):
            raise ValueError("invalid labels")
        return self


def load_plan_definition(data: bytes) -> tuple[PlanLabelSummaryDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise SingleColumnSummaryError("definition_size")
    try:
        definition = PlanLabelSummaryDefinition.model_validate_json(data)
    except ValidationError:
        raise SingleColumnSummaryError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _plan_identity(definition: PlanLabelSummaryDefinition, lines: PDFLineEvidence) -> tuple[str, tuple[PdfLine, ...]]:
    header_lines = lines.lines[:30]
    normalized = [" ".join(unicodedata.normalize("NFKC", line.raw).split()) for line in header_lines]
    titles = [index for index, text in enumerate(normalized) if definition.title in text]
    if len(titles) != 1:
        raise SingleColumnSummaryError("missing_or_ambiguous_plan_title")
    title_index = titles[0]
    browser_pattern = re.compile(
        r"(?:\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})(?:,\s+\d{1,2}:\d{2}\s+[AP]M)?\s+)?" + re.escape(definition.browser_header),
        re.IGNORECASE,
    )
    starts = [
        index
        for index, text in enumerate(normalized[:title_index])
        if text == definition.printed_header or browser_pattern.fullmatch(text)
    ]
    if len(starts) > 1:
        raise SingleColumnSummaryError("ambiguous_plan_header")
    if starts:
        candidates = [
            (header_lines[index], normalized[index]) for index in range(starts[0] + 1, title_index) if normalized[index]
        ]
        if not 1 <= len(candidates) <= 4:
            raise SingleColumnSummaryError("missing_or_ambiguous_plan_label")
    else:
        candidates = [(header_lines[index], normalized[index]) for index in range(title_index) if normalized[index]]
        if len(candidates) != 1 or re.search(r"\bretirement\b|\b401\(k\)", candidates[0][1], re.IGNORECASE) is None:
            raise SingleColumnSummaryError("missing_or_ambiguous_plan_label")
    return " ".join(text for _, text in candidates), tuple(_location(line) for line, _ in candidates)


def parse_plan_label_summary(definition_bytes: bytes, lines: PDFLineEvidence) -> SourceEvidence:
    """Preserve recognized plan-label variants and printed value components."""
    definition, definition_hash = load_plan_definition(definition_bytes)
    account, identity_locations = _plan_identity(definition, lines)
    period_pattern = re.compile(
        rf"\b{re.escape(definition.period_label)}\s*"
        rf"(?P<start>\d{{2}}/\d{{2}}/\d{{4}})\s+to\s+"
        rf"(?P<end>\d{{2}}/\d{{2}}/\d{{4}})\b"
    )
    periods = [
        (index, line, match)
        for index, line in enumerate(lines.lines)
        if (match := period_pattern.search(line.normalized))
    ]
    if not periods or any(
        (match["start"], match["end"]) != (periods[0][2]["start"], periods[0][2]["end"]) for _, _, match in periods
    ):
        raise SingleColumnSummaryError("missing_or_ambiguous_period")
    period_index, period_line, period_match = periods[0]
    if not period_line.normalized.startswith(
        (definition.summary_section_label + " " + definition.period_label, definition.period_label)
    ):
        raise SingleColumnSummaryError("first_period_not_account_summary")
    start, end = _date(period_match["start"]), _date(period_match["end"])
    if not start < end or (end - start).days > 100:
        raise SingleColumnSummaryError("invalid_period")
    openings = [
        (index, line)
        for index, line in enumerate(lines.lines)
        if index > period_index and line.normalized.startswith(definition.opening_label + " ")
    ]
    closings = [
        (index, line)
        for index, line in enumerate(lines.lines)
        if index > period_index and line.normalized.startswith(definition.closing_label + " ")
    ]
    if not openings or not closings:
        raise SingleColumnSummaryError("missing_or_ambiguous_balances")
    opening_index, opening_line = openings[0]
    closing_index, closing_line = closings[0]
    if not opening_index < closing_index or closing_index - opening_index > definition.summary_window_lines:
        raise SingleColumnSummaryError("summary_window_limit")
    opening_raw, opening, opening_tail = _first_money(opening_line, definition.opening_label)
    closing_raw, closing, closing_tail = _first_money(closing_line, definition.closing_label)
    rows = []
    dispositions = []
    occurrences: Counter[tuple[str, int]] = Counter()
    for line in lines.lines[opening_index + 1 : closing_index]:
        if not line.normalized:
            dispositions.append(
                SourceDisposition(code="summary_blank_line", location=_location(line), raw_values=(line.raw,))
            )
            continue
        label = next((label for label in definition.row_labels if line.normalized.startswith(label + " ")), None)
        if label is None:
            raise SingleColumnSummaryError("unresolved_summary_line")
        raw_amount, amount, tail = _first_money(line, label)
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
                source_account_form="opaque",
                date_role="statement_period_end",
                date=DateValue(
                    raw=None, iso=end.isoformat(), provenance="derived", locations=(location, _location(period_line))
                ),
                transaction_date=None,
                description=TextValue(raw=label, text=label, provenance="observed", locations=(location,)),
                amount=MoneyValue(raw=raw_amount, minor=amount, provenance="observed", locations=(location,)),
                running_balance=None,
                components=(),
                fragments=(SourceFragment(channel="plan_value_summary", location=location, raw_values=(line.raw,)),),
            )
        )
        if tail:
            dispositions.append(SourceDisposition(code="summary_extra_column", location=location, raw_values=(tail,)))
    for line, tail in ((opening_line, opening_tail), (closing_line, closing_tail)):
        if tail:
            dispositions.append(
                SourceDisposition(code="summary_extra_column", location=_location(line), raw_values=(tail,))
            )
    if not rows or opening + sum(row.amount.minor for row in rows) != closing:
        raise SingleColumnSummaryError("printed_summary_equation")
    return SourceEvidence(
        schema_version=2,
        source_sha256=lines.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION + "+plan-label",
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
                    source_identity_form="opaque",
                    balance_scope="account_total",
                    identity_locations=identity_locations,
                    opening=MoneyValue(
                        raw=opening_raw, minor=opening, provenance="observed", locations=(_location(opening_line),)
                    ),
                    closing=MoneyValue(
                        raw=closing_raw, minor=closing, provenance="observed", locations=(_location(closing_line),)
                    ),
                    rows=tuple(rows),
                ),
            ),
            dispositions=tuple(dispositions),
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )

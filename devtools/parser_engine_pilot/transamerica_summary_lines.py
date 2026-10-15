"""Finite retirement account-value summary over bounded PDF page lines."""

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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from devtools.parser_engine_pilot.money_operations import usd_symbol_minor_v1
from devtools.parser_engine_pilot.pdf_lines import PageLine, PDFLineEvidence

ENGINE_VERSION = "retirement-summary-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
PERIOD = re.compile(r"(?P<start>[A-Z][a-z]+ \d{1,2}, \d{4}) - (?P<end>[A-Z][a-z]+ \d{1,2}, \d{4})")
MONEY = re.compile(r"-?\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}")


class RetirementSummaryError(ValueError):
    """Redacted refusal of incomplete retirement summary evidence."""


class RetirementSummaryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["single_column_retirement_summary_v1"]
    period_format: Literal["Month D, YYYY - Month D, YYYY"]
    money_format: Literal["signed_usd_2dp"]
    identity_format: Literal["six_digit_plan_prefix"]
    plan_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    row_labels: tuple[str, ...] = Field(min_length=3, max_length=12)
    income_labels: tuple[str, str]
    required_labels: tuple[str, ...] = Field(min_length=1, max_length=10)
    summary_window_lines: int = Field(ge=5, le=30)

    @model_validator(mode="after")
    def valid_labels(self) -> RetirementSummaryDefinition:
        labels = (self.plan_label, self.opening_label, self.closing_label, *self.row_labels)
        if (
            len(set(labels)) != len(labels)
            or any(label != label.strip() or "\n" in label for label in labels)
            or len(set(self.income_labels)) != 2
            or not set(self.income_labels).issubset(self.row_labels)
            or not set(self.required_labels).issubset(self.row_labels)
            or set(self.income_labels) & set(self.required_labels)
        ):
            raise ValueError("invalid retirement labels")
        return self


def load_definition(data: bytes) -> tuple[RetirementSummaryDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise RetirementSummaryError("definition_size")
    try:
        definition = RetirementSummaryDefinition.model_validate_json(data)
    except ValidationError:
        raise RetirementSummaryError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _money(raw: str) -> int:
    if MONEY.fullmatch(raw) is None:
        raise RetirementSummaryError("invalid_summary_money")
    try:
        return usd_symbol_minor_v1(raw)
    except ValueError:
        raise RetirementSummaryError("invalid_summary_money") from None


def _amount_after_label(line: PageLine, label: str) -> tuple[str, int, str]:
    prefix = label + " "
    if not line.normalized.startswith(prefix):
        raise RetirementSummaryError("missing_summary_label")
    rest = line.normalized[len(prefix) :]
    match = MONEY.match(rest)
    if match is None or (match.end() < len(rest) and not rest[match.end()].isspace()):
        raise RetirementSummaryError("missing_summary_amount")
    raw = match.group()
    return raw, _money(raw), rest[match.end() :].strip()


def parse_retirement_summary(definition_bytes: bytes, lines: PDFLineEvidence) -> SourceEvidence:
    """Retain period components without treating investment gain as cash activity."""
    definition, definition_hash = load_definition(definition_bytes)
    first_page = tuple(line for line in lines.lines if line.page == 1)
    periods = [(line, match) for line in first_page[:25] if (match := PERIOD.search(line.normalized))]
    plan_pattern = re.compile(
        rf"^(?P<identity>\d{{6}})\s+\d{{5}}\b.*?{re.escape(definition.plan_label)}", re.IGNORECASE
    )
    plans = [(line, match) for line in first_page[:30] if (match := plan_pattern.search(line.normalized))]
    if len(periods) != 1 or len(plans) != 1:
        raise RetirementSummaryError("missing_or_ambiguous_anchor")
    period_line, period_match = periods[0]
    plan_line, plan_match = plans[0]
    try:
        start = datetime.strptime(period_match["start"], "%B %d, %Y").date()
        end = datetime.strptime(period_match["end"], "%B %d, %Y").date()
    except ValueError:
        raise RetirementSummaryError("invalid_period") from None
    if not 0 < (end - start).days <= 100:
        raise RetirementSummaryError("invalid_period")
    opening_lines = [line for line in first_page if line.normalized.startswith(definition.opening_label + " ")]
    closing_lines = [
        line
        for line in first_page
        if line.normalized.startswith(definition.closing_label + " ")
        and MONEY.match(line.normalized[len(definition.closing_label) + 1 :])
    ]
    if len(opening_lines) != 1 or len(closing_lines) != 1:
        raise RetirementSummaryError("missing_or_ambiguous_balances")
    opening_line, closing_line = opening_lines[0], closing_lines[0]
    if not opening_line.line < closing_line.line <= opening_line.line + definition.summary_window_lines:
        raise RetirementSummaryError("summary_window_limit")
    opening_raw, opening, opening_tail = _amount_after_label(opening_line, definition.opening_label)
    closing_raw, closing, closing_tail = _amount_after_label(closing_line, definition.closing_label)
    account = plan_match["identity"]
    rows = []
    dispositions = []
    seen_labels = set()
    occurrences: Counter[tuple[str, int]] = Counter()
    for line in first_page[opening_line.line : closing_line.line - 1]:
        label = next((label for label in definition.row_labels if line.normalized.startswith(label + " ")), None)
        if label is None:
            if any("$" in word for word in line.normalized.split()[1:4]):
                raise RetirementSummaryError("unresolved_summary_money")
            dispositions.append(
                SourceDisposition(code="summary_interleaved_text", location=_location(line), raw_values=(line.raw,))
            )
            continue
        try:
            raw_amount, amount, tail = _amount_after_label(line, label)
        except RetirementSummaryError as error:
            if str(error) != "missing_summary_amount":
                raise
            dispositions.append(
                SourceDisposition(code="summary_heading", location=_location(line), raw_values=(line.raw,))
            )
            continue
        if label in seen_labels:
            raise RetirementSummaryError("duplicate_summary_component")
        seen_labels.add(label)
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
                fragments=(SourceFragment(channel="retirement_summary", location=location, raw_values=(line.raw,)),),
            )
        )
        if tail:
            dispositions.append(SourceDisposition(code="summary_parallel_text", location=location, raw_values=(tail,)))
    if len(seen_labels & set(definition.income_labels)) != 1 or not set(definition.required_labels).issubset(
        seen_labels
    ):
        raise RetirementSummaryError("missing_summary_component")
    if opening + sum(row.amount.minor for row in rows) != closing:
        raise RetirementSummaryError("printed_summary_equation")
    for line, tail in ((opening_line, opening_tail), (closing_line, closing_tail)):
        if tail:
            dispositions.append(
                SourceDisposition(code="summary_parallel_text", location=_location(line), raw_values=(tail,))
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
                    identity_locations=(_location(plan_line),),
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

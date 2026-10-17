"""Finite card statement evidence using bounded layout and simple text channels."""

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
from parsetrail.core.v2_money_operations import usd_trailing_cr_2dp_minor_v1
from parsetrail.core.v2_pdf_lines import ADAPTER_VERSION, PageLine, PDFLineEvidence
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from devtools.parser_engine_pilot.partial_dates import PartialDateError, resolve_month_day

ENGINE_VERSION = "dual-text-card-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MONEY = r"\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
CARD_MONEY = MONEY + r"(?:CR)?"
DATE_PREFIX = re.compile(r"^\d{2}/\d{2}\b")
INTEREST_PERIOD = re.compile(r"^\d{2}/\d{2}/\d{2}\s+TO\s+\d{2}/\d{2}/\d{2}$")
ROW = re.compile(
    rf"^(?P<posting>\d{{2}}/\d{{2}})\s+(?:(?P<transaction>\d{{2}}/\d{{2}})\s+)?"
    rf"(?P<description>.+?)\s+(?P<amount>{CARD_MONEY})$"
)


class DualTextCardError(ValueError):
    """Redacted refusal of incomplete or conflicting card source evidence."""


class DualTextCardDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["dual_text_card_activity_v1"]
    metadata_channel: Literal["pdf_layout_fixed_tolerance_v1"]
    activity_channel: Literal["pdf_simple_text_v1"]
    date_format: Literal["MM/DD+MM/DD/YYYY"]
    money_format: Literal["usd_2dp_trailing_cr"]
    amount_direction: Literal["invert_for_liability"]
    period_open_label: str = Field(min_length=1, max_length=80)
    period_close_label: str = Field(min_length=1, max_length=80)
    account_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def finite_labels(self) -> DualTextCardDefinition:
        labels = (
            self.period_open_label,
            self.period_close_label,
            self.account_label,
            self.opening_label,
            self.closing_label,
        )
        if len(set(labels)) != len(labels) or any(
            label != label.strip() or "\n" in label or "\r" in label for label in labels
        ):
            raise ValueError("invalid labels")
        return self


def load_definition(data: bytes) -> tuple[DualTextCardDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise DualTextCardError("definition_size")
    try:
        definition = DualTextCardDefinition.model_validate_json(data)
    except ValidationError:
        raise DualTextCardError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _date(raw: str):
    try:
        result = datetime.strptime(raw, "%m/%d/%Y").date()
    except ValueError:
        raise DualTextCardError("invalid_printed_period") from None
    if result.strftime("%m/%d/%Y") != raw:
        raise DualTextCardError("invalid_printed_period")
    return result


def _money(raw: str) -> int:
    try:
        return usd_trailing_cr_2dp_minor_v1(raw)
    except ValueError:
        raise DualTextCardError("invalid_card_money") from None


def parse_dual_text_card(definition_bytes: bytes, layout: PDFLineEvidence, simple: PDFLineEvidence) -> SourceEvidence:
    """Join two fixed extraction channels and verify the printed card equation."""
    definition, definition_hash = load_definition(definition_bytes)
    if (
        layout.source_sha256 != simple.source_sha256
        or layout.page_count != simple.page_count
        or layout.adapter_version != simple.adapter_version
        or layout.adapter_version != ADAPTER_VERSION
        or layout.extraction_library != "pdfplumber-bounded-layout-fixed-v1"
        or simple.extraction_library != "pdfplumber-bounded-simple-v1"
    ):
        raise DualTextCardError("source_channel_mismatch")
    metadata_pattern = re.compile(
        rf"\b{re.escape(definition.period_open_label)}\s*(?P<start>\d{{2}}/\d{{2}}/\d{{4}})\s+"
        rf"{re.escape(definition.period_close_label)}\s*(?P<end>\d{{2}}/\d{{2}}/\d{{4}})\s+"
        rf"{re.escape(definition.account_label)}\s*(?P<account>\d{{4}}(?:\s+\d{{4}}){{3}})\b"
    )
    metadata = [(line, match) for line in layout.lines if (match := metadata_pattern.search(line.normalized))]
    if len(metadata) != 1:
        raise DualTextCardError("missing_or_ambiguous_metadata")
    metadata_line, metadata_match = metadata[0]
    start, end = _date(metadata_match["start"]), _date(metadata_match["end"])
    if not start < end or (end - start).days > 45:
        raise DualTextCardError("invalid_printed_period")
    account = "".join(metadata_match["account"].split())
    opening_pattern = re.compile(rf"^{re.escape(definition.opening_label)}\s+(?:\+\s+)?(?P<amount>{MONEY})$")
    closing_pattern = re.compile(rf"^{re.escape(definition.closing_label)}\s+(?P<amount>{MONEY})$")
    equation_pattern = re.compile(rf"^{re.escape(definition.closing_label)}\s*=\s+(?P<amount>{MONEY})$")
    openings = [(line, match) for line in layout.lines if (match := opening_pattern.fullmatch(line.normalized))]
    closings = [(line, match) for line in layout.lines if (match := closing_pattern.fullmatch(line.normalized))]
    equations = [(line, match) for line in layout.lines if (match := equation_pattern.fullmatch(line.normalized))]
    if len(openings) != 1 or not closings or len(equations) != 1:
        raise DualTextCardError("missing_or_ambiguous_balances")
    opening_line, opening_match = openings[0]
    closing_line, closing_match = closings[0]
    equation_line, equation_match = equations[0]
    opening_source, closing_source = _money(opening_match["amount"]), _money(closing_match["amount"])
    if (
        any(_money(match["amount"]) != closing_source for _, match in closings)
        or _money(equation_match["amount"]) != closing_source
    ):
        raise DualTextCardError("conflicting_printed_closing")
    if not (metadata_line.page == opening_line.page == closing_line.page == equation_line.page):
        raise DualTextCardError("summary_page_mismatch")
    opening, closing = -opening_source, -closing_source
    rows = []
    dated_dispositions = []
    occurrences: Counter[tuple[str, str | None, int, str]] = Counter()
    for line in simple.lines:
        if DATE_PREFIX.match(line.normalized) is None:
            continue
        if INTEREST_PERIOD.fullmatch(line.normalized):
            dated_dispositions.append(
                SourceDisposition(code="interest_period_header", location=_location(line), raw_values=(line.raw,))
            )
            continue
        if len(line.normalized) > 512 or (match := ROW.fullmatch(line.normalized)) is None:
            raise DualTextCardError("unresolved_dated_line")
        try:
            posting = resolve_month_day(match["posting"], start, end)
            transaction = resolve_month_day(match["transaction"], start, end) if match["transaction"] else None
        except PartialDateError:
            raise DualTextCardError("invalid_activity_date") from None
        if not start <= posting <= end:
            raise DualTextCardError("posting_outside_period")
        amount = -_money(match["amount"])
        description = match["description"]
        location = _location(line)
        key = (posting.isoformat(), transaction.isoformat() if transaction else None, amount, description)
        occurrence = occurrences[key]
        occurrences[key] += 1
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(f"{definition_hash}:{ENGINE_VERSION}:{line.line_id}".encode()).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=account,
                source_account_form="full",
                date_role="posting_date",
                date=DateValue(
                    raw=None,
                    iso=posting.isoformat(),
                    provenance="derived",
                    locations=(location, _location(metadata_line)),
                ),
                transaction_date=(
                    DateValue(
                        raw=None,
                        iso=transaction.isoformat(),
                        provenance="derived",
                        locations=(location, _location(metadata_line)),
                    )
                    if transaction
                    else None
                ),
                description=TextValue(raw=description, text=description, provenance="observed", locations=(location,)),
                amount=MoneyValue(raw=match["amount"], minor=amount, provenance="observed", locations=(location,)),
                running_balance=None,
                components=(),
                fragments=(SourceFragment(channel="card_simple_line", location=location, raw_values=(line.raw,)),),
            )
        )
    if opening + sum(row.amount.minor for row in rows) != closing:
        raise DualTextCardError("printed_card_balance_equation")
    dispositions = (
        tuple(dated_dispositions)
        + tuple(
            SourceDisposition(code="repeated_closing_balance", location=_location(line), raw_values=(line.raw,))
            for line, _ in closings[1:]
        )
        + (
            SourceDisposition(
                code="closing_equation_copy", location=_location(equation_line), raw_values=(equation_line.raw,)
            ),
        )
    )
    return SourceEvidence(
        schema_version=2,
        source_sha256=simple.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION,
        extractor_version="pdfplumber-dual-text-fixed-v1+" + simple.adapter_version,
        payload=StatementPayload(
            kind="statement",
            start=DateValue(
                raw=metadata_match["start"],
                iso=start.isoformat(),
                provenance="observed",
                locations=(_location(metadata_line),),
            ),
            end=DateValue(
                raw=metadata_match["end"],
                iso=end.isoformat(),
                provenance="observed",
                locations=(_location(metadata_line),),
            ),
            accounts=(
                StatementAccount(
                    source_identity=account,
                    source_identity_form="full",
                    balance_scope="account_total",
                    identity_locations=(_location(metadata_line),),
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

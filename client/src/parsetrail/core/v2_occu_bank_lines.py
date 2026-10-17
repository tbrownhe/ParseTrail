"""Finite two-account OCCU bank evidence with explicit date-source precedence."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from parsetrail.core.source_evidence import (
    DateValue,
    MoneyValue,
    ObservationEvidence,
    PdfAnnotation,
    PdfLine,
    SourceDisposition,
    SourceEvidence,
    SourceFragment,
    StatementAccount,
    StatementPayload,
    TextValue,
)
from parsetrail.core.v2_bounded_pdf_annotations import PDFPeriodAnnotation
from parsetrail.core.v2_money_operations import usd_parenthetical_2dp_minor_v1
from parsetrail.core.v2_partial_dates import PartialDateError, resolve_month_day
from parsetrail.core.v2_pdf_lines import ADAPTER_VERSION, PageLine, PDFLineEvidence

ENGINE_VERSION = "occu-bank-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MONEY = r"(?:\(\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}\)|\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2})"
DATED = re.compile(r"^\d{2}/\d{2}\s")
ROW = re.compile(
    rf"^(?P<date>\d{{2}}/\d{{2}})\s+(?:#\s+)?(?P<description>.+?)\s+"
    rf"(?P<amount>{MONEY})\s+(?P<balance>{MONEY})$"
)
INQUIRY = re.compile(rf"^\d{{2}}/\d{{2}}\s+#\s+Inquiry ATM .+\s+{MONEY}$")


class OccuBankError(ValueError):
    """Redacted refusal of incomplete OCCU bank source evidence."""


class OccuBankDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["two_account_running_bank_v1"]
    text_channel: Literal["pdf_simple_text_v1"]
    annotation_fallback: Literal["first_page_from_to_v1"]
    date_format: Literal["MM/DD/YY+MM/DD"]
    money_format: Literal["usd_2dp_parenthetical_debit"]
    account_labels: tuple[str, str]
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    other_account_label: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def finite_labels(self) -> OccuBankDefinition:
        labels = (*self.account_labels, self.opening_label, self.closing_label, self.other_account_label)
        if len(set(labels)) != len(labels) or any(
            not label or len(label) > 80 or label != label.strip() or "\n" in label or "\r" in label for label in labels
        ):
            raise ValueError("invalid labels")
        return self


def load_definition(data: bytes) -> tuple[OccuBankDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise OccuBankError("definition_size")
    try:
        definition = OccuBankDefinition.model_validate_json(data)
    except ValidationError:
        raise OccuBankError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _money(raw: str) -> int:
    try:
        return usd_parenthetical_2dp_minor_v1(raw)
    except ValueError:
        raise OccuBankError("invalid_bank_money") from None


def _date(raw: str):
    try:
        month, day, year = map(int, raw.split("/"))
        return datetime(2000 + year, month, day).date()
    except ValueError:
        raise OccuBankError("invalid_period_date") from None


def _period(
    lines: PDFLineEvidence, annotations: tuple[PDFPeriodAnnotation, PDFPeriodAnnotation] | None
) -> tuple[DateValue, DateValue, list[SourceDisposition]]:
    text_dates = {}
    dispositions = []
    for field in ("FROM", "TO"):
        found = [
            (line, match.group(1))
            for line in lines.lines
            if (match := re.match(rf"^{field}\s+(\d{{2}}/\d{{2}}/\d{{2}})(?:\s|$)", line.normalized))
        ]
        if found:
            if len({raw for _, raw in found}) != 1:
                raise OccuBankError("conflicting_text_period")
            text_dates[field] = found[0]
            dispositions.extend(
                SourceDisposition(code="repeated_period_date", location=_location(line), raw_values=(line.raw,))
                for line, _ in found[1:]
            )
    if len(text_dates) == 1:
        raise OccuBankError("partial_text_period")
    if len(text_dates) == 2:
        if annotations is not None:
            raise OccuBankError("unexpected_annotation_fallback")
        start_line, start_raw = text_dates["FROM"]
        end_line, end_raw = text_dates["TO"]
        start_loc, end_loc = _location(start_line), _location(end_line)
    else:
        if annotations is None or [item.field for item in annotations] != ["FROM_DATE", "TO_DATE"]:
            raise OccuBankError("missing_annotation_period")
        start_raw, end_raw = annotations[0].raw, annotations[1].raw
        start_loc = PdfAnnotation(kind="pdf_annotation", page=1, ordinal=annotations[0].ordinal)
        end_loc = PdfAnnotation(kind="pdf_annotation", page=1, ordinal=annotations[1].ordinal)
    start, end = _date(start_raw), _date(end_raw)
    if not 0 < (end - start).days <= 45:
        raise OccuBankError("invalid_period")
    return (
        DateValue(raw=start_raw, iso=start.isoformat(), provenance="observed", locations=(start_loc,)),
        DateValue(raw=end_raw, iso=end.isoformat(), provenance="observed", locations=(end_loc,)),
        dispositions,
    )


def _account(
    definition: OccuBankDefinition,
    definition_hash: str,
    heading: PageLine,
    suffix: str,
    section: tuple[PageLine, ...],
    start: DateValue,
    end: DateValue,
) -> tuple[StatementAccount, list[SourceDisposition]]:
    balance_patterns = {
        "opening": re.compile(rf"^{re.escape(definition.opening_label)}\.+\s+(?P<amount>{MONEY})$"),
        "closing": re.compile(rf"^{re.escape(definition.closing_label)}\.+\s+(?P<amount>{MONEY})$"),
    }
    balances = {}
    for role, pattern in balance_patterns.items():
        found = [(line, match) for line in section if (match := pattern.fullmatch(line.normalized))]
        if len(found) != 1:
            raise OccuBankError("missing_or_ambiguous_balance")
        balances[role] = found[0]
    opening_line, opening_match = balances["opening"]
    closing_line, closing_match = balances["closing"]
    opening = _money(opening_match["amount"])
    closing = _money(closing_match["amount"])
    rows = []
    dispositions = []
    occurrences: Counter[tuple[str, int, str]] = Counter()
    prior = opening
    for line in section:
        if DATED.match(line.normalized) is None:
            continue
        if len(line.normalized) > 512:
            raise OccuBankError("dated_line_limit")
        if INQUIRY.fullmatch(line.normalized):
            dispositions.append(
                SourceDisposition(code="atm_balance_inquiry", location=_location(line), raw_values=(line.raw,))
            )
            continue
        match = ROW.fullmatch(line.normalized)
        if match is None:
            raise OccuBankError("unresolved_dated_line")
        try:
            posted = resolve_month_day(match["date"], _date(start.raw), _date(end.raw))
        except PartialDateError:
            raise OccuBankError("invalid_activity_date") from None
        if not start.iso <= posted.isoformat() <= end.iso:
            raise OccuBankError("posting_outside_period")
        amount = _money(match["amount"])
        running = _money(match["balance"])
        if prior + amount != running:
            raise OccuBankError("printed_running_balance_chain")
        prior = running
        description = match["description"]
        location = _location(line)
        key = (posted.isoformat(), amount, description)
        occurrence = occurrences[key]
        occurrences[key] += 1
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(f"{definition_hash}:{ENGINE_VERSION}:{line.line_id}".encode()).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=suffix,
                source_account_form="last_four",
                date_role="posting_date",
                date=DateValue(
                    raw=None, iso=posted.isoformat(), provenance="derived", locations=(location, *end.locations)
                ),
                transaction_date=None,
                description=TextValue(raw=description, text=description, provenance="observed", locations=(location,)),
                amount=MoneyValue(raw=match["amount"], minor=amount, provenance="observed", locations=(location,)),
                running_balance=MoneyValue(
                    raw=match["balance"], minor=running, provenance="observed", locations=(location,)
                ),
                components=(),
                fragments=(SourceFragment(channel="bank_simple_line", location=location, raw_values=(line.raw,)),),
            )
        )
    if prior != closing:
        raise OccuBankError("printed_closing_balance_chain")
    return (
        StatementAccount(
            source_identity=suffix,
            source_identity_form="last_four",
            balance_scope="account_total",
            identity_locations=(_location(heading),),
            opening=MoneyValue(
                raw=opening_match["amount"], minor=opening, provenance="observed", locations=(_location(opening_line),)
            ),
            closing=MoneyValue(
                raw=closing_match["amount"], minor=closing, provenance="observed", locations=(_location(closing_line),)
            ),
            rows=tuple(rows),
        ),
        dispositions,
    )


def parse_occu_bank(
    definition_bytes: bytes,
    lines: PDFLineEvidence,
    annotations: tuple[PDFPeriodAnnotation, PDFPeriodAnnotation] | None = None,
) -> SourceEvidence:
    """Read savings and checking sections with source-native running balances."""
    definition, definition_hash = load_definition(definition_bytes)
    if lines.adapter_version != ADAPTER_VERSION or lines.extraction_library != "pdfplumber-bounded-simple-v1":
        raise OccuBankError("source_channel_mismatch")
    start, end, dispositions = _period(lines, annotations)
    headings = []
    for label in definition.account_labels:
        pattern = re.compile(rf"^X{{6}}(?P<suffix>\d{{4}}) - {re.escape(label)} \.?$")
        found = [
            (index, line, match)
            for index, line in enumerate(lines.lines)
            if (match := pattern.fullmatch(line.normalized))
        ]
        if len(found) != 1:
            raise OccuBankError("missing_or_ambiguous_account_section")
        headings.append(found[0])
    (sav_index, sav_line, sav_match), (chk_index, chk_line, chk_match) = headings
    if not sav_index < chk_index or sav_match["suffix"] == chk_match["suffix"]:
        raise OccuBankError("invalid_account_sections")
    trailing = [
        index
        for index in range(chk_index + 1, len(lines.lines))
        if lines.lines[index].normalized.startswith("XXXXX")
        or definition.other_account_label in lines.lines[index].normalized
    ]
    checking_end = min(trailing) if trailing else len(lines.lines)
    sav_account, sav_dispositions = _account(
        definition, definition_hash, sav_line, sav_match["suffix"], lines.lines[sav_index:chk_index], start, end
    )
    chk_account, chk_dispositions = _account(
        definition, definition_hash, chk_line, chk_match["suffix"], lines.lines[chk_index:checking_end], start, end
    )
    dispositions.extend(sav_dispositions)
    dispositions.extend(chk_dispositions)
    if trailing:
        tail_line = lines.lines[checking_end]
        dispositions.append(
            SourceDisposition(code="other_account_section", location=_location(tail_line), raw_values=(tail_line.raw,))
        )
    return SourceEvidence(
        schema_version=2,
        source_sha256=lines.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION,
        extractor_version="pdfplumber-bounded-simple-v1+" + lines.adapter_version,
        payload=StatementPayload(
            kind="statement",
            start=start,
            end=end,
            accounts=(sav_account, chk_account),
            dispositions=tuple(dispositions),
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )

"""Finite savings-statement line operations over bounded PDF page evidence."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Callable
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

from devtools.parser_engine_pilot.partial_dates import PartialDateError, resolve_month_day
from devtools.parser_engine_pilot.pdf_lines import PageLine, PDFLineEvidence

ENGINE_VERSION = "savings-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MAX_DATED_LINE_CHARS = 512
MONEY_TEXT = r"(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)?\.[0-9]{2}-?"
MONEY = re.compile(rf"{MONEY_TEXT}\Z")
PERIOD_DATE = re.compile(r"\d{2}/\d{2}/\d{4}\Z")
DATE_PREFIX = re.compile(r"^\d{2}/\d{2}\b")
ROW = re.compile(
    rf"^(?P<date>\d{{2}}/\d{{2}})\s+(?P<description>.+?)\s+"
    rf"(?P<amount>{MONEY_TEXT})\s+(?P<balance>{MONEY_TEXT})$"
)


class SavingsLineError(ValueError):
    """Redacted refusal with optional page and line."""

    def __init__(self, code: str, line: PageLine | None = None):
        self.code = code
        self.page = line.page if line else None
        self.line = line.line if line else None
        super().__init__(code)


class SavingsDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["dated_running_savings_v1"]
    capabilities: tuple[
        Literal["pdf_lines_v1", "unique_printed_fields_v1", "bounded_activity_v1", "printed_running_chain_v1"], ...
    ]
    period_label: str = Field(min_length=1, max_length=80)
    account_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    opening_row_label: str = Field(min_length=1, max_length=80)
    closing_row_label: str = Field(min_length=1, max_length=80)
    section_start: str = Field(min_length=1, max_length=80)
    section_end: str = Field(min_length=1, max_length=80)
    period_date_format: Literal["MM/DD/YYYY"]
    row_date_format: Literal["MM/DD"]
    money_format: Literal["trailing_minus_2dp"]

    @model_validator(mode="after")
    def finite_labels(self) -> SavingsDefinition:
        required = {"pdf_lines_v1", "unique_printed_fields_v1", "bounded_activity_v1", "printed_running_chain_v1"}
        if set(self.capabilities) != required or len(self.capabilities) != len(required):
            raise ValueError("invalid capabilities")
        labels = (
            self.period_label,
            self.account_label,
            self.opening_label,
            self.closing_label,
            self.opening_row_label,
            self.closing_row_label,
            self.section_start,
            self.section_end,
        )
        if len(set(labels)) != len(labels) or any(label != label.strip() or "\n" in label for label in labels):
            raise ValueError("invalid labels")
        return self


def load_definition(data: bytes) -> tuple[SavingsDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise SavingsLineError("definition_size")
    try:
        definition = SavingsDefinition.model_validate_json(data)
    except ValidationError:
        raise SavingsLineError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _money(raw: str, line: PageLine) -> int:
    if len(raw) > 30 or MONEY.fullmatch(raw) is None:
        raise SavingsLineError("invalid_money", line)
    unsigned = raw.removesuffix("-").replace(",", "")
    major, cents = unsigned.split(".")
    amount = int(major or "0") * 100 + int(cents)
    if amount > 9_000_000_000_000_000:
        raise SavingsLineError("money_range", line)
    return -amount if raw.endswith("-") else amount


def _date(raw: str, line: PageLine):
    if PERIOD_DATE.fullmatch(raw) is None:
        raise SavingsLineError("invalid_period_date", line)
    try:
        value = datetime.strptime(raw, "%m/%d/%Y").date()
    except ValueError:
        raise SavingsLineError("invalid_period_date", line) from None
    if value.strftime("%m/%d/%Y") != raw:
        raise SavingsLineError("invalid_period_date", line)
    return value


def parse_savings_lines(
    definition_bytes: bytes,
    lines: PDFLineEvidence,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> SourceEvidence:
    """Parse printed endpoints and a bounded running-balance section."""
    definition, definition_hash = load_definition(definition_bytes)
    period_pattern = re.compile(
        rf"^{re.escape(definition.period_label)}\s*(?P<start>\d{{2}}/\d{{2}}/\d{{4}})\s*-\s*"
        r"(?P<end>\d{2}/\d{2}/\d{4})$"
    )
    account_pattern = re.compile(rf"^{re.escape(definition.account_label)}\s+X+(?P<number>\d{{4}})$")
    balance_patterns = {
        "opening": re.compile(
            rf"^{re.escape(definition.opening_label)}\d{{2}}/\d{{2}}/\d{{2}}\s+(?P<amount>{MONEY_TEXT})(?=\s|$)"
        ),
        "closing": re.compile(
            rf"^{re.escape(definition.closing_label)}\d{{2}}/\d{{2}}/\d{{2}}\s+(?P<amount>{MONEY_TEXT})(?=\s|$)"
        ),
    }
    marker_pattern = re.compile(
        rf"^(?P<date>\d{{2}}/\d{{2}})\s+(?P<label>{re.escape(definition.opening_row_label)}|"
        rf"{re.escape(definition.closing_row_label)})\s+(?P<balance>{MONEY_TEXT})$"
    )
    found: dict[str, tuple[PageLine, re.Match[str]]] = {}
    sections: dict[str, PageLine] = {}
    printed_dispositions = []
    for line in lines.lines:
        if cancelled is not None and cancelled():
            raise SavingsLineError("cancelled", line)
        for role, pattern in (("period", period_pattern), ("account", account_pattern), *balance_patterns.items()):
            match = pattern.match(line.normalized) if role in balance_patterns else pattern.fullmatch(line.normalized)
            if match is None:
                continue
            if role in found:
                if role == "period" and match.groupdict() == found[role][1].groupdict():
                    printed_dispositions.append(
                        SourceDisposition(
                            code="repeated_period_header", location=_location(line), raw_values=(line.raw,)
                        )
                    )
                    continue
                raise SavingsLineError("duplicate_" + role, line)
            found[role] = (line, match)
            if role in balance_patterns and line.normalized[match.end() :].strip():
                printed_dispositions.append(
                    SourceDisposition(code="balance_line_tail", location=_location(line), raw_values=(line.raw,))
                )
        for role, matches in (
            ("start", line.normalized == definition.section_start),
            ("end", line.normalized.startswith(definition.section_end)),
        ):
            if matches:
                if role in sections:
                    raise SavingsLineError("duplicate_section_" + role, line)
                sections[role] = line
    if set(found) != {"period", "account", "opening", "closing"}:
        raise SavingsLineError("missing_printed_field")
    if set(sections) != {"start", "end"}:
        raise SavingsLineError("missing_activity_boundary")
    positions = {(line.page, line.line): index for index, line in enumerate(lines.lines)}
    first = positions[(sections["start"].page, sections["start"].line)]
    last = positions[(sections["end"].page, sections["end"].line)]
    if first >= last:
        raise SavingsLineError("activity_boundaries_out_of_order")
    period_line, period = found["period"]
    start, end = _date(period["start"], period_line), _date(period["end"], period_line)
    if start >= end or (end - start).days > 366:
        raise SavingsLineError("invalid_period")
    opening_line, opening = found["opening"]
    closing_line, closing = found["closing"]
    opening_minor, closing_minor = _money(opening["amount"], opening_line), _money(closing["amount"], closing_line)
    account_line, account = found["account"]
    account_number = account["number"]
    rows = []
    dispositions = printed_dispositions
    occurrence: Counter[str] = Counter()
    markers: set[str] = set()
    running = opening_minor
    for line in lines.lines[first + 1 : last]:
        if cancelled is not None and cancelled():
            raise SavingsLineError("cancelled", line)
        if len(line.raw) > MAX_DATED_LINE_CHARS:
            raise SavingsLineError("activity_line_limit", line)
        match = ROW.fullmatch(line.normalized)
        if match is None:
            marker = marker_pattern.fullmatch(line.normalized)
            if marker is not None:
                label = marker["label"]
                expected = opening_minor if label == definition.opening_row_label else closing_minor
                if label in markers or _money(marker["balance"], line) != expected:
                    raise SavingsLineError("balance_marker_mismatch", line)
                markers.add(label)
                dispositions.append(
                    SourceDisposition(code="balance_marker", location=_location(line), raw_values=(line.raw,))
                )
                continue
            if DATE_PREFIX.match(line.normalized) or "$" in line.raw or re.search(r"\d+\.\d{2}", line.raw):
                raise SavingsLineError("unresolved_activity_line", line)
            dispositions.append(
                SourceDisposition(code="activity_header", location=_location(line), raw_values=(line.raw,))
            )
            continue
        if match["description"] in {"Beginning Balance", "Ending Balance"}:
            dispositions.append(
                SourceDisposition(code="balance_marker", location=_location(line), raw_values=(line.raw,))
            )
            continue
        try:
            row_date = resolve_month_day(match["date"], start, end)
        except PartialDateError:
            raise SavingsLineError("invalid_row_date", line) from None
        if not start <= row_date <= end:
            raise SavingsLineError("row_date_outside_period", line)
        amount = _money(match["amount"], line)
        printed_running = _money(match["balance"], line)
        running += amount
        if running != printed_running:
            raise SavingsLineError("printed_running_mismatch", line)
        index = occurrence[line.raw]
        occurrence[line.raw] += 1
        row_id = hashlib.sha256(
            f"{lines.source_sha256}:{definition_hash}:{ENGINE_VERSION}:{lines.adapter_version}:{lines.extraction_library}:{line.page}:{line.line}:{index}".encode()
        ).hexdigest()
        location = _location(line)
        rows.append(
            ObservationEvidence(
                row_id=row_id,
                occurrence=index,
                source_account=account_number,
                source_account_form="last_four",
                date_role="posting_date",
                date=DateValue(raw=None, iso=row_date.isoformat(), provenance="derived", locations=(location,)),
                transaction_date=None,
                description=TextValue(
                    raw=match["description"],
                    text=" ".join(match["description"].split()),
                    provenance="observed",
                    locations=(location,),
                ),
                amount=MoneyValue(raw=match["amount"], minor=amount, provenance="observed", locations=(location,)),
                running_balance=MoneyValue(
                    raw=match["balance"], minor=printed_running, provenance="observed", locations=(location,)
                ),
                components=(),
                fragments=(SourceFragment(channel="savings_line", location=location, raw_values=(line.raw,)),),
            )
        )
    if running != closing_minor:
        raise SavingsLineError("printed_closing_mismatch")
    if markers != {definition.opening_row_label, definition.closing_row_label}:
        raise SavingsLineError("missing_balance_marker")
    period_location = _location(period_line)
    payload = StatementPayload(
        kind="statement",
        start=DateValue(
            raw=period["start"], iso=start.isoformat(), provenance="observed", locations=(period_location,)
        ),
        end=DateValue(raw=period["end"], iso=end.isoformat(), provenance="observed", locations=(period_location,)),
        accounts=(
            StatementAccount(
                source_identity=account_number,
                source_identity_form="last_four",
                identity_locations=(_location(account_line),),
                opening=MoneyValue(
                    raw=opening["amount"],
                    minor=opening_minor,
                    provenance="observed",
                    locations=(_location(opening_line),),
                ),
                closing=MoneyValue(
                    raw=closing["amount"],
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
    )
    return SourceEvidence(
        schema_version=2,
        source_sha256=lines.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION,
        extractor_version=lines.extraction_library + "+" + lines.adapter_version,
        payload=payload,
    )

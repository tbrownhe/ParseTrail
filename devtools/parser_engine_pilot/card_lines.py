"""Finite card-statement line pilot over already extracted PDF page evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from devtools.parser_engine_pilot.pdf_lines import PageLine, PDFLineEvidence

ENGINE_VERSION = "card-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MAX_MONEY_MINOR = 9_000_000_000_000_000
MAX_DATED_LINE_CHARS = 512
TRANSACTION = re.compile(
    r"^\s*(?P<date>\d{2}/\d{2})\s{2,}(?P<description>.+?)\s+"
    r"(?P<amount>-?\$?(?:\d{1,3}(?:,\d{3})*)?\.\d{2})\s*$"
)
DATED_PREFIX = re.compile(r"^\s*\d{1,2}/\d{1,2}\b")
DATED_CODE = re.compile(r"^\s*\d{2}/\d{2}\s+(?P<code>[A-Z]{3})\s*$")
SUMMARY_MONEY = re.compile(r"\$(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})*|[1-9][0-9]*)\.[0-9]{2}\Z")
TRANSACTION_MONEY = re.compile(r"-?\$?(?:[0-9]{1,3}(?:,[0-9]{3})*)?\.[0-9]{2}\Z")
Provenance = Literal["printed", "normalized_source_sign", "derived_year", "derived_posting_proxy"]


class CardLineError(ValueError):
    """Redacted card-line failure with optional page and line."""

    def __init__(self, code: str, location: PageLine | None = None):
        self.code = code
        self.page = location.page if location else None
        self.line = location.line if location else None
        super().__init__(code)


class CardDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    capabilities: tuple[
        Literal["pdf_lines_v1", "card_mmdd_amount_v1", "printed_card_boundaries_v1", "clamped_posting_proxy_v1"], ...
    ]
    period_label: str = Field(min_length=1, max_length=80)
    account_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    date_format: Literal["MM/DD/YY"]
    money_format: Literal["card_usd_2dp"]
    amount_direction: Literal["invert_for_liability"]
    dated_auxiliary: Literal["three_uppercase_letters"]

    @model_validator(mode="after")
    def valid_capabilities(self) -> CardDefinition:
        required = {
            "pdf_lines_v1",
            "card_mmdd_amount_v1",
            "printed_card_boundaries_v1",
            "clamped_posting_proxy_v1",
        }
        if set(self.capabilities) != required or len(self.capabilities) != len(required):
            raise ValueError("invalid capabilities")
        labels = (self.period_label, self.account_label, self.opening_label, self.closing_label)
        if len(set(labels)) != len(labels) or any(
            label != label.strip() or "\n" in label or "\r" in label for label in labels
        ):
            raise ValueError("invalid labels")
        return self


@dataclass(frozen=True, slots=True)
class CardField:
    raw: str
    normalized: str | int
    provenance: Provenance
    source_line_id: str
    page: int
    line: int


@dataclass(frozen=True, slots=True)
class CardRow:
    row_id: str
    occurrence: int
    transaction_date: CardField
    posting_date: CardField
    description: CardField
    amount: CardField
    source_sign_minor: int


@dataclass(frozen=True, slots=True)
class AuxiliaryLine:
    source_line_id: str
    page: int
    line: int
    raw: str
    code: str
    disposition: Literal["dated_three_letter_detail_uninterpreted"]


@dataclass(frozen=True, slots=True)
class CardStatementEvidence:
    output_schema_version: int
    source_sha256: str
    definition_sha256: str
    engine_version: str
    extraction_library: str
    line_adapter_version: str
    parser_id: str
    definition_revision: str
    account_identity: CardField
    period_start: CardField
    period_end: CardField
    opening_minor: CardField
    closing_minor: CardField
    rows: tuple[CardRow, ...]
    auxiliary_lines: tuple[AuxiliaryLine, ...]
    coverage_verified: Literal[False]
    balance_reconciled: Literal[False]


def load_definition(data: bytes) -> tuple[CardDefinition, str]:
    if not data or len(data) > MAX_DEFINITION_BYTES:
        raise CardLineError("definition_size")
    try:
        definition = CardDefinition.model_validate_json(data)
    except ValidationError:
        raise CardLineError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _field(raw: str, normalized: str | int, provenance: Provenance, line: PageLine) -> CardField:
    return CardField(raw, normalized, provenance, line.line_id, line.page, line.line)


def _money(raw: str, *, summary: bool, location: PageLine) -> int:
    pattern = SUMMARY_MONEY if summary else TRANSACTION_MONEY
    if len(raw) > 30 or pattern.fullmatch(raw) is None:
        raise CardLineError("invalid_money", location)
    sign = -1 if raw.startswith("-") else 1
    major, cents = raw.removeprefix("-").removeprefix("$").replace(",", "").split(".")
    minor = sign * (int(major or "0") * 100 + int(cents))
    if abs(minor) > MAX_MONEY_MINOR:
        raise CardLineError("money_range", location)
    return minor


def _printed_date(raw: str, location: PageLine) -> date:
    try:
        value = datetime.strptime(raw, "%m/%d/%y").date()
    except ValueError:
        raise CardLineError("invalid_period_date", location) from None
    if value.strftime("%m/%d/%y") != raw:
        raise CardLineError("invalid_period_date", location)
    return value


def _transaction_date(raw: str, start: date, end: date, location: PageLine) -> date:
    month, day = map(int, raw.split("/"))
    years = {start.year, start.year + 1, end.year, end.year - 1}
    candidates = []
    for year in years:
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        distance = min(abs((candidate - start).days), abs((candidate - end).days))
        candidates.append((distance, candidate))
    if not candidates:
        raise CardLineError("invalid_transaction_date", location)
    nearest = min(distance for distance, _candidate in candidates)
    winners = [candidate for distance, candidate in candidates if distance == nearest]
    if len(winners) != 1 or nearest > (end - start).days:
        raise CardLineError("ambiguous_transaction_date", location)
    return winners[0]


def parse_card_lines(
    definition_bytes: bytes,
    lines: PDFLineEvidence,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> CardStatementEvidence:
    """Parse one card layout; the PDF decoder and posting approval stay outside."""
    definition, definition_hash = load_definition(definition_bytes)
    period_pattern = re.compile(
        rf"^{re.escape(definition.period_label)}\s+(?P<start>\d{{2}}/\d{{2}}/\d{{2}})\s+-\s+"
        r"(?P<end>\d{2}/\d{2}/\d{2})$"
    )
    account_pattern = re.compile(rf"^{re.escape(definition.account_label)}\s+(?:X{{4}}\s+){{3}}(?P<number>\d{{4}})$")
    balance_patterns = {
        "opening": re.compile(rf"^{re.escape(definition.opening_label)}\s+(?P<amount>\$[\d,]+\.\d{{2}})$"),
        "closing": re.compile(rf"^{re.escape(definition.closing_label)}\s+(?P<amount>\$[\d,]+\.\d{{2}})$"),
    }
    found: dict[str, tuple[PageLine, re.Match]] = {}
    for line in lines.lines:
        if cancelled is not None and cancelled():
            raise CardLineError("cancelled", line)
        for role, pattern in (("period", period_pattern), ("account", account_pattern), *balance_patterns.items()):
            match = pattern.fullmatch(line.normalized)
            if match is None:
                continue
            if role in found:
                raise CardLineError("duplicate_" + role, line)
            found[role] = (line, match)
    if set(found) != {"period", "account", "opening", "closing"}:
        raise CardLineError("missing_printed_field")
    period_line, period = found["period"]
    start = _printed_date(period["start"], period_line)
    end = _printed_date(period["end"], period_line)
    if end < start or (end - start).days > 370:
        raise CardLineError("invalid_period", period_line)
    account_line, account = found["account"]
    opening_line, opening = found["opening"]
    closing_line, closing = found["closing"]
    seen = Counter()
    rows = []
    auxiliaries = []
    for line in lines.lines:
        if cancelled is not None and cancelled():
            raise CardLineError("cancelled", line)
        if DATED_PREFIX.match(line.raw) is None:
            continue
        if len(line.raw) > MAX_DATED_LINE_CHARS:
            raise CardLineError("dated_line_limit", line)
        match = TRANSACTION.fullmatch(line.raw)
        if match is None:
            auxiliary = DATED_CODE.fullmatch(line.raw)
            if auxiliary is None:
                raise CardLineError("unresolved_dated_line", line)
            auxiliaries.append(
                AuxiliaryLine(
                    line.line_id,
                    line.page,
                    line.line,
                    line.raw,
                    auxiliary["code"],
                    "dated_three_letter_detail_uninterpreted",
                )
            )
            continue
        transaction_date = _transaction_date(match["date"], start, end, line)
        posting_proxy = min(max(transaction_date, start), end)
        source_sign = _money(match["amount"], summary=False, location=line)
        normalized_amount = -source_sign
        description = " ".join(match["description"].split())
        occurrence = seen[line.raw]
        seen[line.raw] += 1
        row_id = hashlib.sha256(
            json.dumps(
                [
                    lines.source_sha256,
                    definition_hash,
                    ENGINE_VERSION,
                    lines.adapter_version,
                    lines.extraction_library,
                    line.page,
                    line.line,
                    occurrence,
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        rows.append(
            CardRow(
                row_id,
                occurrence,
                _field(match["date"], transaction_date.isoformat(), "derived_year", line),
                _field(match["date"], posting_proxy.isoformat(), "derived_posting_proxy", line),
                _field(match["description"], description, "printed", line),
                _field(match["amount"], normalized_amount, "normalized_source_sign", line),
                source_sign,
            )
        )
    return CardStatementEvidence(
        output_schema_version=1,
        source_sha256=lines.source_sha256,
        definition_sha256=definition_hash,
        engine_version=ENGINE_VERSION,
        extraction_library=lines.extraction_library,
        line_adapter_version=lines.adapter_version,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        account_identity=_field(account["number"], account["number"], "printed", account_line),
        period_start=_field(period["start"], start.isoformat(), "printed", period_line),
        period_end=_field(period["end"], end.isoformat(), "printed", period_line),
        opening_minor=_field(
            opening["amount"], -_money(opening["amount"], summary=True, location=opening_line), "printed", opening_line
        ),
        closing_minor=_field(
            closing["amount"], -_money(closing["amount"], summary=True, location=closing_line), "printed", closing_line
        ),
        rows=tuple(rows),
        auxiliary_lines=tuple(auxiliaries),
        coverage_verified=False,
        balance_reconciled=False,
    )

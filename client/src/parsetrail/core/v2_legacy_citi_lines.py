"""Finite older Citi layout evidence with bounded date-start continuation."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
from parsetrail.core.v2_monetary_line_inventory import MonetaryLineRule, inventory_monetary_lines
from parsetrail.core.v2_money_operations import usd_symbol_minor_v1
from parsetrail.core.v2_partial_dates import PartialDateError, resolve_month_day
from parsetrail.core.v2_pdf_lines import ADAPTER_VERSION, PageLine, PDFLineEvidence
from parsetrail.core.v2_pdf_routing import PDFRouting

ENGINE_VERSION = "legacy-citi-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MONEY = r"-?\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
MONEY_TOKEN = re.compile(MONEY)
DATE_START = re.compile(r"^\d{2}/\d{2}\s")
ROW = re.compile(
    rf"^(?P<transaction>\d{{2}}/\d{{2}})\s+(?:(?P<posting>\d{{2}}/\d{{2}})\s+)?"
    rf"(?P<description>.+?)\s+(?P<amount>{MONEY})(?:\s+(?P<trailing>.+))?$"
)


class LegacyCitiError(ValueError):
    """Redacted refusal of incomplete older Citi statement evidence."""


class LegacyCitiDefinition(BaseModel):
    routing: PDFRouting
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[2]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["layout_date_start_continuation_v1"]
    text_channel: Literal["pdf_default_layout_v1"]
    date_format: Literal["MM/DD/YY+MM/DD"]
    money_format: Literal["usd_symbol_2dp"]
    amount_direction: Literal["invert_for_liability"]
    period_label: str = Field(min_length=1, max_length=80)
    account_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    table_header: str = Field(min_length=1, max_length=80)
    max_continuation_lines: Literal[5]
    monetary_line_rules: tuple[MonetaryLineRule, ...] = Field(min_length=1, max_length=16)


def load_definition(data: bytes) -> tuple[LegacyCitiDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise LegacyCitiError("definition_size")
    try:
        definition = LegacyCitiDefinition.model_validate_json(data)
    except ValidationError:
        raise LegacyCitiError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine, end: PageLine | None = None) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line, end_line=end.line if end else None)


def _date(raw: str):
    try:
        month, day, year = map(int, raw.split("/"))
        return datetime(2000 + year, month, day).date()
    except ValueError:
        raise LegacyCitiError("invalid_period_date") from None


def _money(raw: str) -> int:
    if re.fullmatch(MONEY, raw) is None:
        raise LegacyCitiError("invalid_card_money")
    try:
        return usd_symbol_minor_v1(raw)
    except ValueError:
        raise LegacyCitiError("invalid_card_money") from None


def _one(matches: list[tuple[PageLine, re.Match[str]]], code: str) -> tuple[PageLine, re.Match[str]]:
    if len(matches) != 1:
        raise LegacyCitiError(code)
    return matches[0]


def _truncate_words(raw: str, max_index: int) -> str:
    """Stop at the declared Amount column while keeping adjacent wrap text."""
    words = []
    start = 0
    last_end = -1
    for word in raw.split():
        position = raw.find(word, start)
        if position > max_index and (last_end < 0 or position - last_end > 1):
            break
        words.append(word)
        last_end = position + len(word)
        start = last_end
    return " ".join(words)


def _rows(
    definition: LegacyCitiDefinition, lines: PDFLineEvidence
) -> tuple[list[tuple[str, tuple[PageLine, ...]]], list[SourceDisposition]]:
    pages: dict[int, list[PageLine]] = {}
    for line in lines.lines:
        if line.normalized:
            pages.setdefault(line.page, []).append(line)
    found = []
    dispositions = []
    saw_header = False
    for page_lines in pages.values():
        headers = [
            line
            for line in page_lines
            if all(word in line.normalized.lower().split() for word in definition.table_header.lower().split())
        ]
        if not headers:
            continue
        saw_header = True
        header = headers[0]
        dispositions.extend(
            SourceDisposition(code="repeated_table_header", location=_location(line), raw_values=(line.raw,))
            for line in headers[1:]
        )
        max_index = header.raw.lower().index("amount") + len("amount")
        starts = [i for i, line in enumerate(page_lines) if DATE_START.match(line.normalized)]
        for index in starts:
            fragments = [page_lines[index]]
            text = _truncate_words(page_lines[index].raw, max_index)
            for offset in range(1, definition.max_continuation_lines + 1):
                if MONEY_TOKEN.search(text):
                    break
                next_index = index + offset
                if next_index >= len(page_lines) or next_index in starts:
                    break
                fragments.append(page_lines[next_index])
                text += " " + _truncate_words(page_lines[next_index].raw, max_index)
            if not MONEY_TOKEN.search(text):
                raise LegacyCitiError("unresolved_dated_start")
            if len(text) > 1024 or len(MONEY_TOKEN.findall(text)) > 2:
                raise LegacyCitiError("ambiguous_row_amount")
            found.append((text, tuple(fragments)))
    if not found and (not saw_header or any(DATE_START.match(line.normalized) for line in lines.lines)):
        raise LegacyCitiError("missing_activity_rows")
    return found, dispositions


def parse_legacy_citi(definition_bytes: bytes, lines: PDFLineEvidence) -> SourceEvidence:
    """Bind a located Citi layout row to its first dated start and amount."""
    definition, definition_hash = load_definition(definition_bytes)
    if lines.adapter_version != ADAPTER_VERSION or lines.extraction_library != "pdfplumber-bounded-layout-default-v1":
        raise LegacyCitiError("source_channel_mismatch")
    period_pattern = re.compile(
        rf"^{re.escape(definition.period_label)}\s*(?P<start>\d{{2}}/\d{{2}}/\d{{2}})-(?P<end>\d{{2}}/\d{{2}}/\d{{2}})(?:\s|$)"
    )
    account_pattern = re.compile(rf"{re.escape(definition.account_label)}\s+(?P<suffix>\d{{4}})\b")
    opening_pattern = re.compile(rf"^{re.escape(definition.opening_label)}\s+(?P<amount>{MONEY})$")
    closing_pattern = re.compile(rf"\b{re.escape(definition.closing_label)}\s+(?P<amount>{MONEY})(?:\s|$)")
    period_line, period_match = _one(
        [(line, match) for line in lines.lines if (match := period_pattern.match(line.normalized))],
        "missing_or_ambiguous_period",
    )
    start, end = _date(period_match["start"]), _date(period_match["end"])
    if not 0 < (end - start).days <= 45:
        raise LegacyCitiError("invalid_period")
    accounts = [(line, match) for line in lines.lines if (match := account_pattern.search(line.normalized))]
    if not accounts or len({match["suffix"] for _, match in accounts}) != 1:
        raise LegacyCitiError("missing_or_ambiguous_account")
    account_line, account_match = accounts[0]
    suffix = account_match["suffix"]
    opening_line, opening_match = _one(
        [(line, match) for line in lines.lines if (match := opening_pattern.fullmatch(line.normalized))],
        "missing_or_ambiguous_opening",
    )
    closings = [(line, match) for line in lines.lines if (match := closing_pattern.search(line.normalized))]
    if not closings:
        raise LegacyCitiError("missing_or_ambiguous_closing")
    closing_line, closing_match = closings[0]
    if any(_money(match["amount"]) != _money(closing_match["amount"]) for _, match in closings[1:]):
        raise LegacyCitiError("conflicting_printed_closing")
    opening, closing = -_money(opening_match["amount"]), -_money(closing_match["amount"])
    rows = []
    occurrences: Counter[tuple[str, str | None, int, str]] = Counter()
    candidates, table_dispositions = _rows(definition, lines)
    tail_dispositions = []
    for text, fragments in candidates:
        match = ROW.fullmatch(text)
        if match is None:
            raise LegacyCitiError("unresolved_dated_row")
        try:
            transaction = resolve_month_day(match["transaction"], start, end)
            posting = resolve_month_day(match["posting"], start, end) if match["posting"] else transaction
        except PartialDateError:
            raise LegacyCitiError("invalid_activity_date") from None
        if not start <= posting <= end:
            raise LegacyCitiError("posting_outside_period")
        amount = -_money(match["amount"])
        description_raw = match["description"]
        description = " ".join(description_raw.split())
        span = _location(fragments[0], fragments[-1]) if len(fragments) > 1 else _location(fragments[0])
        if match["trailing"]:
            trailing = match["trailing"]
            if MONEY_TOKEN.search(trailing):
                if re.fullmatch(rf"No Late Fee:\s+{MONEY}", trailing) is None:
                    raise LegacyCitiError("ambiguous_parallel_money")
                tail_code = "parallel_no_late_fee"
            else:
                tail_code = "parallel_column_tail"
            tail_dispositions.append(SourceDisposition(code=tail_code, location=span, raw_values=(trailing,)))
        key = (posting.isoformat(), transaction.isoformat() if match["posting"] else None, amount, description)
        occurrence = occurrences[key]
        occurrences[key] += 1
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(
                    f"{definition_hash}:{ENGINE_VERSION}:{fragments[0].line_id}".encode()
                ).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=suffix,
                source_account_form="last_four",
                date_role="posting_date",
                date=DateValue(
                    raw=None,
                    iso=posting.isoformat(),
                    provenance="derived" if match["posting"] else "assumed",
                    locations=(span, _location(period_line)),
                ),
                transaction_date=DateValue(
                    raw=None,
                    iso=transaction.isoformat(),
                    provenance="derived",
                    locations=(span, _location(period_line)),
                ),
                description=TextValue(raw=description_raw, text=description, provenance="observed", locations=(span,)),
                amount=MoneyValue(raw=match["amount"], minor=amount, provenance="observed", locations=(span,)),
                running_balance=None,
                components=(),
                fragments=tuple(
                    SourceFragment(channel="citi_layout_line", location=_location(line), raw_values=(line.raw,))
                    for line in fragments
                ),
            )
        )
    if opening + sum(row.amount.minor for row in rows) != closing:
        raise LegacyCitiError("printed_card_balance_equation")
    repeated_closing_dispositions = tuple(
        SourceDisposition(code="repeated_closing_balance", location=_location(line), raw_values=(line.raw,))
        for line, _ in closings[1:]
    )
    classified_dispositions = tuple(table_dispositions) + tuple(tail_dispositions) + repeated_closing_dispositions
    covered_locations = (
        (_location(opening_line),)
        + tuple(_location(line) for line, _ in closings)
        + tuple(fragment.location for row in rows for fragment in row.fragments)
        + tuple(disposition.location for disposition in classified_dispositions)
    )
    monetary_dispositions = inventory_monetary_lines(
        lines,
        money_token=MONEY_TOKEN,
        covered_locations=covered_locations,
        rules=definition.monetary_line_rules,
    )
    return SourceEvidence(
        schema_version=2,
        source_sha256=lines.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION,
        extractor_version="pdfplumber-bounded-layout-default-v1+" + lines.adapter_version,
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
                    source_identity=suffix,
                    source_identity_form="last_four",
                    balance_scope="account_total",
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
            dispositions=classified_dispositions + monetary_dispositions,
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )

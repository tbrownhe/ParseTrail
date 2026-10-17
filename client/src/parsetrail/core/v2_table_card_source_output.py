"""Finite card observations from declared anchored table cells and text fields."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime

from parsetrail.core.source_evidence import (
    DateValue,
    MoneyValue,
    ObservationEvidence,
    PdfChars,
    PdfLine,
    PdfTableRow,
    SourceDisposition,
    SourceEvidence,
    SourceFragment,
    StatementAccount,
    StatementPayload,
    TextValue,
)
from parsetrail.core.v2_anchored_table import AnchoredRow, AnchoredTableEvidence, load_definition
from parsetrail.core.v2_citi_statement_header import CitiHeaderError, parse_header
from parsetrail.core.v2_money_operations import usd_symbol_minor_v1
from parsetrail.core.v2_partial_dates import PartialDateError, resolve_month_day
from parsetrail.core.v2_pdf_lines import ADAPTER_VERSION, PDFLineEvidence
from parsetrail.core.v2_table_continuations import ContinuationError, RawTableRow, assemble

ENGINE_VERSION = "table-card-source-pilot-1"
MONEY = re.compile(r"-?\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}\Z")
DATE = re.compile(r"\d{2}/\d{2}\Z")
DATE_PREFIX = re.compile(r"\d{2}/\d{2}")


class TableCardError(ValueError):
    """Redacted refusal of incomplete table-card source evidence."""


def _location(row: AnchoredRow) -> PdfTableRow:
    return PdfTableRow(kind="pdf_table_row", page=row.page, row=row.ordinal, region=row.region)


def _line(page: int, line: int) -> PdfLine:
    return PdfLine(kind="pdf_line", page=page, line=line)


def _date(raw: str):
    try:
        return datetime.strptime(raw, "%m/%d/%y").date()
    except ValueError:
        raise TableCardError("invalid_period_date") from None


def from_anchored_card(definition_bytes: bytes, table: AnchoredTableEvidence, text: PDFLineEvidence) -> SourceEvidence:
    """Admit only dated table starts; preserve every other raw table row."""
    definition, definition_hash = load_definition(definition_bytes)
    rule = definition.statement
    if rule is None:
        raise TableCardError("missing_statement_rule")
    if (
        table.definition_sha256 != definition_hash
        or table.source_sha256 != text.source_sha256
        or text.adapter_version != ADAPTER_VERSION
        or text.extraction_library != "pdfplumber-bounded-layout-default-v1"
        or len(table.pages) != text.page_count
    ):
        raise TableCardError("source_channel_mismatch")
    pages = tuple("\n".join(line.raw for line in text.lines if line.page == page.page) for page in table.pages)
    try:
        header = parse_header(
            table.first_page_chars,
            pages,
            period_label=rule.period_label,
            account_label=rule.account_label,
            opening_label=rule.opening_label,
            closing_label=rule.closing_label,
        )
    except CitiHeaderError:
        raise TableCardError("invalid_statement_header") from None
    period_raw = table.first_page_chars[header.period_char_span[0] : header.period_char_span[1]]
    period_match = re.search(r"(\d{2}/\d{2}/\d{2})-(\d{2}/\d{2}/\d{2})", period_raw)
    if period_match is None or _date(period_match[1]) != header.start_date or _date(period_match[2]) != header.end_date:
        raise TableCardError("invalid_statement_period")
    first_page_span = PdfChars(
        kind="pdf_chars", page=1, start=header.period_char_span[0], end=header.period_char_span[1]
    )
    selected: list[tuple[object, tuple[AnchoredRow, ...]]] = []
    dispositions = []
    pending: list[AnchoredRow] = []
    for row in table.rows:
        cells = tuple(cell.strip() for cell in row.raw_cells)
        location = _location(row)
        if not any(cells):
            dispositions.append(SourceDisposition(code="blank_table_row", location=location, raw_values=()))
            continue
        if tuple(cell.casefold() for cell in cells[:2]) == tuple(
            value.casefold() for value in rule.repeated_header_date_cells
        ) and not any(cells[2:]):
            dispositions.append(
                SourceDisposition(code="repeated_table_header", location=location, raw_values=row.raw_cells)
            )
            continue
        start = bool(DATE.fullmatch(cells[0]) or DATE.fullmatch(cells[1]))
        if start:
            if pending:
                raise TableCardError("new_row_before_amount")
            if any(value and DATE.fullmatch(value) is None for value in cells[:2]):
                raise TableCardError("invalid_table_date")
            pending = [row]
        elif pending:
            if any(cells[:2]):
                raise TableCardError("invalid_continuation_date")
            pending.append(row)
        else:
            if any(DATE_PREFIX.search(cell) for cell in cells[:2]):
                raise TableCardError("unresolved_dated_table_row")
            code = "monetary_table_tail" if any(MONEY.search(cell) for cell in cells) else "nonactivity_table_row"
            dispositions.append(SourceDisposition(code=code, location=location, raw_values=row.raw_cells))
            continue
        if len(pending) > rule.continuation.max_group_rows:
            raise TableCardError("continuation_limit")
        if MONEY.fullmatch(cells[3]):
            raw_rows = tuple(
                RawTableRow(item.page, item.ordinal, tuple(cell.strip() for cell in item.raw_cells)) for item in pending
            )
            try:
                joined = assemble(rule.continuation, raw_rows)
            except ContinuationError:
                raise TableCardError("invalid_continuation") from None
            if len(joined) != 1 or joined[0].amount_raw != cells[3]:
                raise TableCardError("invalid_continuation")
            selected.append((joined[0], tuple(pending)))
            pending = []
    if pending:
        raise TableCardError("missing_terminal_amount")
    if not selected:
        raise TableCardError("missing_activity_rows")
    rows = []
    occurrences: Counter[tuple[str, str | None, int, str]] = Counter()
    for joined, sources in selected:
        first = sources[0]
        transaction_raw, posting_raw = first.raw_cells[:2]
        transaction_raw, posting_raw = transaction_raw.strip(), posting_raw.strip()
        try:
            transaction = resolve_month_day(transaction_raw or posting_raw, header.start_date, header.end_date)
            posting = resolve_month_day(posting_raw or transaction_raw, header.start_date, header.end_date)
        except PartialDateError:
            raise TableCardError("invalid_activity_date") from None
        if not header.start_date <= posting <= header.end_date:
            raise TableCardError("posting_outside_period")
        amount_raw = joined.amount_raw
        try:
            amount = -usd_symbol_minor_v1(amount_raw)
        except ValueError:
            raise TableCardError("invalid_card_money") from None
        description = joined.description
        key = (
            posting.isoformat(),
            transaction.isoformat() if transaction_raw and posting_raw else None,
            amount,
            description,
        )
        occurrence = occurrences[key]
        occurrences[key] += 1
        source_locations = tuple(_location(item) for item in sources)
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(
                    f"{table.source_sha256}:{definition_hash}:{ENGINE_VERSION}:{table.extraction_library}:"
                    f"{first.page}:{first.ordinal}".encode()
                ).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=header.account_suffix,
                source_account_form="last_four",
                date_role="posting_date",
                date=DateValue(
                    raw=None,
                    iso=posting.isoformat(),
                    provenance="derived",
                    locations=(_location(first), first_page_span),
                ),
                transaction_date=(
                    DateValue(
                        raw=None,
                        iso=transaction.isoformat(),
                        provenance="derived",
                        locations=(_location(first), first_page_span),
                    )
                    if transaction_raw and posting_raw
                    else None
                ),
                description=TextValue(
                    raw=description, text=description, provenance="observed", locations=source_locations
                ),
                amount=MoneyValue(
                    raw=amount_raw, minor=amount, provenance="observed", locations=(_location(sources[-1]),)
                ),
                running_balance=None,
                components=(),
                fragments=tuple(
                    SourceFragment(channel="anchored_table_row", location=_location(item), raw_values=item.raw_cells)
                    for item in sources
                ),
            )
        )
    if header.previous_balance.ledger_minor + sum(row.amount.minor for row in rows) != header.new_balance.ledger_minor:
        raise TableCardError("printed_card_balance_equation")
    return SourceEvidence(
        schema_version=2,
        source_sha256=table.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION,
        extractor_version=table.extraction_library + "+" + text.adapter_version,
        payload=StatementPayload(
            kind="statement",
            start=DateValue(
                raw=period_match[1],
                iso=header.start_date.isoformat(),
                provenance="observed",
                locations=(first_page_span,),
            ),
            end=DateValue(
                raw=period_match[2],
                iso=header.end_date.isoformat(),
                provenance="observed",
                locations=(first_page_span,),
            ),
            accounts=(
                StatementAccount(
                    source_identity=header.account_suffix,
                    source_identity_form="last_four",
                    balance_scope="account_total",
                    identity_locations=tuple(_line(page, line) for page, line in header.account_locations[:16]),
                    opening=MoneyValue(
                        raw=header.previous_balance.raw,
                        minor=header.previous_balance.ledger_minor,
                        provenance="observed",
                        locations=(_line(header.previous_balance.page, header.previous_balance.line),),
                    ),
                    closing=MoneyValue(
                        raw=header.new_balance.raw,
                        minor=header.new_balance.ledger_minor,
                        provenance="observed",
                        locations=(_line(header.new_balance.page, header.new_balance.line),),
                    ),
                    rows=tuple(rows),
                ),
            ),
            dispositions=tuple(dispositions),
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )

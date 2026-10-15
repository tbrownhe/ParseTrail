"""Finite Wells business statement evidence from bounded lines and table cells."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timedelta

from parsetrail.core.source_evidence import (
    DateValue,
    MoneyValue,
    ObservationEvidence,
    PdfLine,
    PdfTableRow,
    SourceDisposition,
    SourceEvidence,
    SourceFragment,
    StatementAccount,
    StatementPayload,
    TextValue,
)

from devtools.parser_engine_pilot.money_operations import usd_or_decimal_2dp_minor_v1
from devtools.parser_engine_pilot.partial_dates import PartialDateError, resolve_slash_month_day
from devtools.parser_engine_pilot.pdf_lines import PageLine, PDFLineEvidence
from devtools.parser_engine_pilot.table_continuations import RawTableRow, assemble
from devtools.parser_engine_pilot.wells_table import TableRow, WellsTableEvidence, load_definition

END_DATE = re.compile(r"(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})")
PARTIAL = r"\d{1,2}/\d{1,2}"
MONEY = r"-?\$?(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"


class WellsStatementError(ValueError):
    """Redacted statement refusal with no source values."""


def _table_location(row: TableRow) -> PdfTableRow:
    return PdfTableRow(kind="pdf_table_row", page=row.page, row=row.table_row, region=row.region)


def _month_day(raw: str, start, end):
    try:
        return resolve_slash_month_day(raw, start, end)
    except PartialDateError:
        raise WellsStatementError("invalid_partial_date") from None


def _money(raw: str) -> int:
    try:
        return usd_or_decimal_2dp_minor_v1(raw.strip())
    except ValueError:
        raise WellsStatementError("invalid_statement_money") from None


def from_wells_business(
    definition_bytes: bytes,
    table: WellsTableEvidence,
    lines: PDFLineEvidence,
) -> SourceEvidence:
    """Require printed fields, exact row amounts and a source balance equation."""
    definition, definition_hash = load_definition(definition_bytes)
    if (
        table.output_schema_version != 1
        or table.source_sha256 != lines.source_sha256
        or table.definition_sha256 != definition_hash
        or len(table.pages) != lines.page_count
        or not table.rows
    ):
        raise WellsStatementError("bounded_source_mismatch")
    first_page = tuple(line for line in lines.lines if line.page == 1 and line.line <= 10)
    date_matches = [(line, match) for line in first_page if (match := END_DATE.search(line.normalized))]
    if len(date_matches) != 1:
        raise WellsStatementError("missing_or_ambiguous_end_date")
    end_line, end_match = date_matches[0]
    try:
        end = datetime.strptime(end_match["date"], "%B %d, %Y").date()
    except ValueError:
        raise WellsStatementError("invalid_end_date") from None
    summaries = [line for line in lines.lines if definition.summary_label in line.normalized]
    if len(summaries) != 1:
        raise WellsStatementError("missing_or_ambiguous_summary")
    summary = summaries[0]
    positions = {(line.page, line.line): index for index, line in enumerate(lines.lines)}
    start_index = positions[(summary.page, summary.line)]
    window = lines.lines[start_index : start_index + definition.balance_window_lines]
    account_pattern = re.compile(rf"{re.escape(definition.account_label)}\s*(?P<account>\d{{4,}})\b")
    opening_pattern = re.compile(
        rf"{re.escape(definition.opening_label)}\s+(?P<date>{PARTIAL})\s+(?P<amount>{MONEY})(?=\s|$)"
    )
    closing_pattern = re.compile(
        rf"(?:{'|'.join(re.escape(label) for label in definition.closing_labels)})\s+"
        rf"(?P<date>{PARTIAL})\s+(?P<amount>{MONEY})(?=\s|$)"
    )
    found = {}
    for line in window:
        for role, pattern in (("account", account_pattern), ("opening", opening_pattern), ("closing", closing_pattern)):
            match = pattern.search(line.normalized)
            if match is None:
                continue
            if role in found:
                raise WellsStatementError("ambiguous_summary_field")
            found[role] = (line, match)
    if set(found) != {"account", "opening", "closing"}:
        raise WellsStatementError("missing_summary_field")
    account_line, account_match = found["account"]
    opening_line, opening_match = found["opening"]
    closing_line, closing_match = found["closing"]
    if not positions[(opening_line.page, opening_line.line)] < positions[(closing_line.page, closing_line.line)]:
        raise WellsStatementError("summary_field_order")
    start = _month_day(opening_match["date"], end - timedelta(days=120), end)
    if not start < end or (end - start).days > 120 or _month_day(closing_match["date"], start, end) != end:
        raise WellsStatementError("invalid_statement_period")
    opening = _money(opening_match["amount"])
    closing = _money(closing_match["amount"])
    account_number = account_match["account"]
    accepted = tuple(row for row in table.rows if row.disposition in {"dated_candidate", "description_continuation"})
    by_location = {(row.page, row.table_row): row for row in accepted}
    if len(by_location) != len(accepted):
        raise WellsStatementError("duplicate_table_row_location")
    grouped = assemble(
        definition.continuation,
        tuple(RawTableRow(row.page, row.table_row, row.raw_cells) for row in accepted),
    )
    rows = []
    occurrences: Counter[tuple[str, int, str]] = Counter()
    running = opening
    for group in grouped:
        sources = tuple(by_location[(row.page, row.ordinal)] for row in group.sources)
        first = sources[0]
        if first.disposition != "dated_candidate" or any(
            row.disposition != "description_continuation" for row in sources[1:]
        ):
            raise WellsStatementError("invalid_continuation_group")
        if any(row.raw_cells[3].strip() or row.raw_cells[4].strip() or row.raw_cells[5].strip() for row in sources[1:]):
            raise WellsStatementError("money_on_continuation")
        credit, debit = first.raw_cells[3].strip(), first.raw_cells[4].strip()
        if bool(credit) == bool(debit):
            raise WellsStatementError("ambiguous_amount_columns")
        raw_amount = credit or debit
        amount = _money(raw_amount) * (1 if credit else -1)
        if amount == 0:
            raise WellsStatementError("zero_activity_amount")
        posting_date = _month_day(first.raw_cells[0].strip(), start, end)
        if not start <= posting_date <= end:
            raise WellsStatementError("posting_date_outside_period")
        running += amount
        printed_balance = first.raw_cells[5].strip()
        if printed_balance and _money(printed_balance) != running:
            raise WellsStatementError("printed_running_mismatch")
        key = (posting_date.isoformat(), amount, group.description)
        occurrence = occurrences[key]
        occurrences[key] += 1
        location = _table_location(first)
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(": ".join(row.row_id for row in sources).encode()).hexdigest(),
                occurrence=occurrence,
                source_account=account_number,
                source_account_form="full",
                date_role="posting_date",
                date=DateValue(raw=None, iso=posting_date.isoformat(), provenance="derived", locations=(location,)),
                transaction_date=None,
                description=TextValue(
                    raw=None,
                    text=group.description,
                    provenance="derived",
                    locations=tuple(_table_location(row) for row in sources),
                ),
                amount=MoneyValue(raw=raw_amount, minor=amount, provenance="observed", locations=(location,)),
                running_balance=(
                    MoneyValue(raw=printed_balance, minor=running, provenance="observed", locations=(location,))
                    if printed_balance
                    else None
                ),
                components=(),
                fragments=tuple(
                    SourceFragment(channel="wells_table", location=_table_location(row), raw_values=row.raw_cells)
                    for row in sources
                ),
            )
        )
    if running != closing:
        raise WellsStatementError("printed_closing_mismatch")
    dispositions = tuple(
        SourceDisposition(
            code=row.disposition,
            location=_table_location(row),
            raw_values=row.raw_cells,
        )
        for row in table.rows
        if row.disposition in {"terminator", "unresolved_after_stop"}
    )
    payload = StatementPayload(
        kind="statement",
        start=DateValue(
            raw=None,
            iso=start.isoformat(),
            provenance="derived",
            locations=(PdfLine(kind="pdf_line", page=opening_line.page, line=opening_line.line), _location(end_line)),
        ),
        end=DateValue(
            raw=end_match["date"], iso=end.isoformat(), provenance="observed", locations=(_location(end_line),)
        ),
        accounts=(
            StatementAccount(
                source_identity=account_number,
                source_identity_form="full",
                balance_scope="account_total",
                identity_locations=(_location(account_line),),
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
    )
    return SourceEvidence(
        schema_version=2,
        source_sha256=table.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=table.engine_version + "+statement-v1",
        extractor_version=table.extraction_library + "+" + lines.adapter_version,
        payload=payload,
    )


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)

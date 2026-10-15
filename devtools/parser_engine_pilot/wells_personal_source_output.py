"""Finite Wells personal cash evidence from declared table geometry and printed fields."""

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

from devtools.parser_engine_pilot.anchored_table import (
    AnchoredRow,
    AnchoredTableEvidence,
    TableWellsPersonalRule,
    load_definition,
)
from devtools.parser_engine_pilot.money_operations import usd_or_decimal_2dp_minor_v1
from devtools.parser_engine_pilot.partial_dates import PartialDateError, resolve_slash_month_day
from devtools.parser_engine_pilot.pdf_lines import ADAPTER_VERSION, PageLine, PDFLineEvidence
from devtools.parser_engine_pilot.table_continuations import ContinuationError, RawTableRow, assemble

ENGINE_VERSION = "wells-personal-source-pilot-1"
END_DATE = re.compile(r"(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})")
PARTIAL = r"\d{1,2}/\d{1,2}"
MONEY = r"-?\$?(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.\d{2}"
DATE = re.compile(rf"{PARTIAL}\Z")


class WellsPersonalError(ValueError):
    """Redacted refusal of incomplete Wells personal statement evidence."""


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _table_location(row: AnchoredRow) -> PdfTableRow:
    return PdfTableRow(kind="pdf_table_row", page=row.page, row=row.ordinal, region=row.region)


def _money(raw: str) -> int:
    try:
        return usd_or_decimal_2dp_minor_v1(raw)
    except ValueError:
        raise WellsPersonalError("invalid_money") from None


def _date(raw: str, start, end):
    try:
        return resolve_slash_month_day(raw, start, end)
    except PartialDateError:
        raise WellsPersonalError("invalid_partial_date") from None


def _printed_fields(rule: TableWellsPersonalRule, lines: PDFLineEvidence):
    first_page = tuple(line for line in lines.lines if line.page == 1 and line.line <= 10)
    end_matches = [(line, match) for line in first_page if (match := END_DATE.search(line.normalized))]
    if len(end_matches) != 1:
        raise WellsPersonalError("missing_or_ambiguous_end_date")
    end_line, end_match = end_matches[0]
    try:
        end = datetime.strptime(end_match["date"], "%B %d, %Y").date()
    except ValueError:
        raise WellsPersonalError("invalid_end_date") from None
    summaries = [line for line in lines.lines if rule.summary_label in line.normalized]
    if len(summaries) != 1:
        raise WellsPersonalError("missing_or_ambiguous_summary")
    summary = summaries[0]
    positions = {(line.page, line.line): index for index, line in enumerate(lines.lines)}
    window = lines.lines[positions[(summary.page, summary.line)] :][: rule.balance_window_lines]
    account_pattern = re.compile(rf"{re.escape(rule.account_label)}\s*(?P<account>\d{{4,}})\b")
    opening_pattern = re.compile(
        rf"{re.escape(rule.opening_label)}[^0-9]{{0,24}}(?P<date>{PARTIAL})\s+(?P<amount>{MONEY})(?=\s|$)"
    )
    closing_pattern = re.compile(
        rf"(?:{'|'.join(re.escape(label) for label in rule.closing_labels)})"
        rf"[^0-9]{{0,24}}(?P<date>{PARTIAL})\s+(?P<amount>{MONEY})(?=\s|$)"
    )
    found = {}
    for line in window:
        for role, pattern in (("account", account_pattern), ("opening", opening_pattern), ("closing", closing_pattern)):
            match = pattern.search(line.normalized)
            if match is None:
                continue
            if role in found:
                raise WellsPersonalError("ambiguous_summary_field")
            found[role] = (line, match)
    if set(found) != {"account", "opening", "closing"}:
        raise WellsPersonalError("missing_summary_field")
    account_line, account_match = found["account"]
    opening_line, opening_match = found["opening"]
    closing_line, closing_match = found["closing"]
    if not positions[(opening_line.page, opening_line.line)] < positions[(closing_line.page, closing_line.line)]:
        raise WellsPersonalError("summary_field_order")
    start = _date(opening_match["date"], end - timedelta(days=rule.max_period_days), end)
    if not start < end or (end - start).days > rule.max_period_days or _date(closing_match["date"], start, end) != end:
        raise WellsPersonalError("invalid_statement_period")
    return (
        start,
        end,
        end_line,
        end_match,
        account_line,
        account_match,
        opening_line,
        opening_match,
        closing_line,
        closing_match,
    )


def _activity_rows(table: AnchoredTableEvidence) -> tuple[tuple[AnchoredRow, ...], tuple[SourceDisposition, ...]]:
    selected = []
    dispositions = []
    for page in table.pages:
        stopped = False
        for row in (item for item in table.rows if item.page == page.page):
            location = _table_location(row)
            if stopped:
                dispositions.append(
                    SourceDisposition(code="unresolved_after_stop", location=location, raw_values=row.raw_cells)
                )
                continue
            if not any(row.raw_cells) or row.raw_cells[0].startswith("Ending"):
                stopped = True
                dispositions.append(
                    SourceDisposition(code="table_terminator", location=location, raw_values=row.raw_cells)
                )
                continue
            if len(row.raw_cells) != 6:
                raise WellsPersonalError("table_columns")
            date_raw, _, description, credit, debit, balance = (cell.strip() for cell in row.raw_cells)
            if DATE.fullmatch(date_raw):
                if not description or bool(credit) == bool(debit):
                    raise WellsPersonalError("invalid_dated_row")
                selected.append(row)
            elif not date_raw and description and not any((row.raw_cells[1], credit, debit, balance)):
                selected.append(row)
            else:
                raise WellsPersonalError("unresolved_before_stop")
    if not selected:
        raise WellsPersonalError("missing_activity_rows")
    return tuple(selected), tuple(dispositions)


def from_wells_personal(
    definition_bytes: bytes, table: AnchoredTableEvidence, lines: PDFLineEvidence
) -> SourceEvidence:
    """Require exact table/summary balance parity without classifying later page text."""
    definition, definition_hash = load_definition(definition_bytes)
    rule = definition.statement
    if not isinstance(rule, TableWellsPersonalRule):
        raise WellsPersonalError("missing_wells_statement_rule")
    if (
        table.definition_sha256 != definition_hash
        or table.source_sha256 != lines.source_sha256
        or len(table.pages) != lines.page_count
        or lines.adapter_version != ADAPTER_VERSION
        or lines.extraction_library != "pdfplumber-bounded-simple-v1"
    ):
        raise WellsPersonalError("source_channel_mismatch")
    (
        start,
        end,
        end_line,
        end_match,
        account_line,
        account_match,
        opening_line,
        opening_match,
        closing_line,
        closing_match,
    ) = _printed_fields(rule, lines)
    selected, dispositions = _activity_rows(table)
    by_location = {(row.page, row.ordinal): row for row in selected}
    if len(by_location) != len(selected):
        raise WellsPersonalError("duplicate_table_location")
    try:
        joined = assemble(
            rule.continuation,
            tuple(RawTableRow(row.page, row.ordinal, row.raw_cells) for row in selected),
        )
    except ContinuationError:
        raise WellsPersonalError("invalid_continuation") from None
    opening, closing = _money(opening_match["amount"]), _money(closing_match["amount"])
    account = account_match["account"]
    rows = []
    running = opening
    occurrences: Counter[tuple[str, int, str]] = Counter()
    for group in joined:
        sources = tuple(by_location[(item.page, item.ordinal)] for item in group.sources)
        first = sources[0]
        if DATE.fullmatch(first.raw_cells[0].strip()) is None or any(
            any(item.raw_cells[index].strip() for index in (0, 1, 3, 4, 5)) for item in sources[1:]
        ):
            raise WellsPersonalError("invalid_continuation_group")
        credit, debit = first.raw_cells[3].strip(), first.raw_cells[4].strip()
        if bool(credit) == bool(debit):
            raise WellsPersonalError("ambiguous_amount_columns")
        raw_amount = credit or debit
        printed_amount = _money(raw_amount)
        if printed_amount <= 0:
            raise WellsPersonalError("invalid_amount_direction")
        amount = printed_amount if credit else -printed_amount
        date = _date(first.raw_cells[0].strip(), start, end)
        if not start <= date <= end:
            raise WellsPersonalError("posting_outside_period")
        running += amount
        balance_raw = first.raw_cells[5].strip()
        if balance_raw and _money(balance_raw) != running:
            raise WellsPersonalError("printed_running_mismatch")
        key = (date.isoformat(), amount, group.description)
        occurrence = occurrences[key]
        occurrences[key] += 1
        location = _table_location(first)
        locations = tuple(_table_location(item) for item in sources)
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(
                    f"{table.source_sha256}:{definition_hash}:{ENGINE_VERSION}:".encode()
                    + ":".join(f"{item.page}:{item.ordinal}" for item in sources).encode()
                ).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=account,
                source_account_form="full",
                date_role="posting_date",
                date=DateValue(
                    raw=None, iso=date.isoformat(), provenance="derived", locations=(location, _location(opening_line))
                ),
                transaction_date=None,
                description=TextValue(
                    raw=first.raw_cells[2] if len(sources) == 1 else None,
                    text=group.description,
                    provenance="observed" if len(sources) == 1 else "derived",
                    locations=locations,
                ),
                amount=MoneyValue(raw=raw_amount, minor=amount, provenance="observed", locations=(location,)),
                running_balance=(
                    MoneyValue(raw=balance_raw, minor=running, provenance="observed", locations=(location,))
                    if balance_raw
                    else None
                ),
                components=(),
                fragments=tuple(
                    SourceFragment(
                        channel="anchored_table_row", location=_table_location(item), raw_values=item.raw_cells
                    )
                    for item in sources
                ),
            )
        )
    if running != closing:
        raise WellsPersonalError("printed_closing_mismatch")
    return SourceEvidence(
        schema_version=2,
        source_sha256=table.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION,
        extractor_version=table.extraction_library + "+" + lines.adapter_version,
        payload=StatementPayload(
            kind="statement",
            start=DateValue(
                raw=None,
                iso=start.isoformat(),
                provenance="derived",
                locations=(_location(opening_line), _location(end_line)),
            ),
            end=DateValue(
                raw=end_match["date"], iso=end.isoformat(), provenance="observed", locations=(_location(end_line),)
            ),
            accounts=(
                StatementAccount(
                    source_identity=account,
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
        ),
    )

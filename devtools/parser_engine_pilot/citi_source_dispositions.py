"""Read-only source-line capture check for the recent Citi PDF layout.

This checks whether every dated line outside the simple text-row matcher has a
located table occurrence or a located fee. It does not admit financial rows.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from parsetrail.core.money import parse_money, to_minor_units
from parsetrail.plugins.pdf_citicc_202511 import Parser as RecentCiti

from devtools.parser_engine_pilot.channel_occurrences import Candidate, validate_candidates

DATE_ONLY = re.compile(r"^\s*(?:\d+\s+)*(?P<date>\d{2}/\d{2})\s*$")


@dataclass(frozen=True, slots=True)
class DatedLineDisposition:
    page: int
    line: int
    end_line: int
    status: Literal["simple_text", "table_copy", "fee", "unresolved"]
    table_row: int | None = None
    description_evidence: Literal["ordered_words", "first_character_loss"] | None = None


@dataclass(frozen=True, slots=True)
class _Start:
    page: int
    line: int
    end_line: int
    date: str
    amount_minor: int | None
    simple: bool
    context: str


def _description_evidence(description: str, context: str) -> Literal["ordered_words", "first_character_loss"] | None:
    target = description.upper().split()
    words = context.upper().split()
    if not target:
        return None
    for allow_initial_loss in (False, True):
        position = 0
        for word in words:
            if word == target[position] or (
                allow_initial_loss and position == 0 and len(word) == len(target[0]) + 1 and word[1:] == target[0]
            ):
                position += 1
                if position == len(target):
                    return "first_character_loss" if allow_initial_loss else "ordered_words"
    return None


def _starts(parser: RecentCiti, pages: list[str]) -> list[_Start]:
    def dated(raw: str) -> re.Match[str] | None:
        return parser.DATE_PREFIX.match(raw) or DATE_ONLY.match(raw)

    result = []
    for page_number, page in enumerate(pages, 1):
        lines = page.splitlines()
        for index, line in enumerate(lines):
            match = dated(line)
            if match is None:
                continue
            simple = parser.TEXT_TRANSACTION.match(line) is not None
            end = min(index + 4, len(lines))
            if simple:
                end = index + 1
            else:
                end = next(
                    (later for later in range(index + 1, end) if dated(lines[later])),
                    end,
                )
            amounts = {
                -to_minor_units(parse_money(found.group()))
                for raw in lines[index:end]
                for found in parser.AMOUNT.finditer(raw)
            }
            # A description may precede a date-only line in this layout. Do not
            # reach back past another dated start or beyond two nearby lines.
            context_start = index
            for previous in range(index - 1, max(-1, index - 3), -1):
                if dated(lines[previous]):
                    break
                context_start = previous
            result.append(
                _Start(
                    page_number,
                    index + 1,
                    end,
                    match.group("date"),
                    next(iter(amounts)) if len(amounts) == 1 else None,
                    simple,
                    " ".join(lines[context_start:end]),
                )
            )
    return result


def dispose_dated_lines(
    parser: RecentCiti,
    pages: list[str],
    table: list[Candidate],
    fees: list[Candidate],
) -> tuple[DatedLineDisposition, ...]:
    """Pair source starts with table occurrences in page order; refuse gaps."""
    validate_candidates(table, "table")
    validate_candidates(fees, "fee")
    starts = _starts(parser, pages)
    table_groups: dict[tuple[int, str, int], list[Candidate]] = defaultdict(list)
    source_groups: dict[tuple[int, str, int], list[_Start]] = defaultdict(list)
    for row in table:
        assert row.page is not None
        table_groups[(row.page, row.transaction_date.strftime("%m/%d"), row.amount_minor)].append(row)
    for row in starts:
        if row.amount_minor is not None:
            source_groups[(row.page, row.date, row.amount_minor)].append(row)
    for rows in table_groups.values():
        rows.sort(key=lambda row: row.line or 0)

    table_links: dict[tuple[int, int], Candidate] = {}
    for key, source_rows in source_groups.items():
        table_rows = table_groups.get(key, [])
        if len(source_rows) != len(table_rows):
            continue
        for source_row, table_row in zip(source_rows, table_rows, strict=True):
            table_links[(source_row.page, source_row.line)] = table_row

    fee_by_location = {(fee.page, fee.line): fee for fee in fees}
    result = []
    for row in starts:
        if row.simple:
            result.append(DatedLineDisposition(row.page, row.line, row.end_line, "simple_text"))
            continue
        table_row = table_links.get((row.page, row.line))
        evidence = _description_evidence(table_row.description, row.context) if table_row is not None else None
        if table_row is not None and evidence is not None:
            result.append(
                DatedLineDisposition(row.page, row.line, row.end_line, "table_copy", table_row.line, evidence)
            )
            continue
        fee = fee_by_location.get((row.page, row.line))
        if (
            fee is not None
            and fee.amount_minor == row.amount_minor
            and fee.end_line is not None
            and row.line <= fee.end_line <= row.end_line
        ):
            result.append(DatedLineDisposition(row.page, row.line, fee.end_line, "fee"))
            continue
        result.append(DatedLineDisposition(row.page, row.line, row.end_line, "unresolved"))
    return tuple(result)

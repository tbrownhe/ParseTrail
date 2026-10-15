"""Capped raw table-cell evidence for the recent Citi PDF geometry."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Literal

from parsetrail.plugins.pdf_citicc_202511 import Parser as RecentCiti

from devtools.parser_engine_pilot.pdf_lines import MAX_PAGES, MAX_PDF_BYTES

MAX_CHARS_PER_PAGE = 200_000
MAX_TABLE_ROWS = 20_000
MAX_CELL_CHARS = 4096
ENGINE_VERSION = "citi-table-pilot-1"


class CitiTableError(ValueError):
    """Redacted table extraction failure."""


@dataclass(frozen=True, slots=True)
class CitiTablePage:
    page: int
    status: Literal["no_header", "table", "after_stop"]
    crop_region: tuple[float, float, float, float] | None
    vertical_lines: tuple[float, ...]
    stops_transactions: bool


@dataclass(frozen=True, slots=True)
class CitiTableRow:
    page: int
    table_row: int
    region: tuple[float, float, float, float] | None
    source_line: int | None
    raw_cells: tuple[str, str, str, str]
    channel: Literal["table", "interest_text"]


@dataclass(frozen=True, slots=True)
class CitiTableEvidence:
    output_schema_version: int
    source_sha256: str
    engine_version: str
    extraction_library: str
    pages: tuple[CitiTablePage, ...]
    rows: tuple[CitiTableRow, ...]
    coverage_verified: Literal[False]
    account_balance_reconciled: Literal[False]


def _valid_region(region: tuple[float, ...], page) -> bool:
    return (
        len(region) == 4
        and all(isinstance(value, (int, float)) and math.isfinite(value) for value in region)
        and 0 <= region[0] < region[2] <= page.width
        and 0 <= region[1] < region[3] <= page.height
    )


def extract_citi_table(source: bytes, pages, *, extraction_library: str) -> CitiTableEvidence:
    """Retain cells and source regions; do not convert them to transactions."""
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_PDF_BYTES:
        raise CitiTableError("source_size")
    if not extraction_library or len(extraction_library) > 80:
        raise CitiTableError("extraction_library")
    parser = RecentCiti()
    page_evidence = []
    rows = []
    for page_number, page in enumerate(pages, 1):
        if page_number > MAX_PAGES or len(page.chars) > MAX_CHARS_PER_PAGE:
            raise CitiTableError("page_limit")
        if parser.stop:
            page_evidence.append(CitiTablePage(page_number, "after_stop", None, (), True))
            continue
        if not parser.vertical_lines:
            parser.get_vertical_lines(page)
        if not parser.vertical_lines:
            page_evidence.append(CitiTablePage(page_number, "no_header", None, (), False))
            continue
        crop = tuple(parser.crop_settings)
        vertical = tuple(parser.vertical_lines)
        if (
            not _valid_region(crop, page)
            or len(vertical) != 5
            or any(left >= right for left, right in zip(vertical, vertical[1:], strict=False))
        ):
            raise CitiTableError("invalid_geometry")
        table = page.crop(crop).find_table(
            table_settings={
                "vertical_strategy": "explicit",
                "horizontal_strategy": "lines",
                "explicit_vertical_lines": vertical,
            }
        )
        page_row_number = 0
        if table is not None:
            extracted = table.extract()
            if len(extracted) != len(table.rows):
                raise CitiTableError("row_locations")
            for cells, region in zip(extracted, table.rows, strict=True):
                if len(rows) >= MAX_TABLE_ROWS or len(cells) != 4:
                    raise CitiTableError("row_limit_or_width")
                values = tuple(cell or "" for cell in cells)
                if any(len(value) > MAX_CELL_CHARS for value in values):
                    raise CitiTableError("cell_limit")
                if not any(values):
                    continue
                if not all(not value or parser.TRANSACTION_DATE.match(value) for value in values[:2]):
                    continue
                bbox = tuple(region.bbox)
                if not _valid_region(bbox, page):
                    raise CitiTableError("invalid_row_region")
                page_row_number += 1
                rows.append(CitiTableRow(page_number, page_row_number, bbox, None, values, "table"))
        text = page.extract_text_simple() or ""
        stop = "TOTAL INTEREST FOR THIS PERIOD" in text
        if stop:
            parser.stop = True
            interest = re.compile(parser.INTEREST_LINE)
            for line_number, line in enumerate(text.splitlines(), 1):
                if interest.match(line):
                    parts = line.split()
                    values = ("", parts[0], " ".join(parts[1:-1]), parts[-1])
                    if len(rows) >= MAX_TABLE_ROWS or any(len(value) > MAX_CELL_CHARS for value in values):
                        raise CitiTableError("row_or_cell_limit")
                    page_row_number += 1
                    rows.append(CitiTableRow(page_number, page_row_number, None, line_number, values, "interest_text"))
                    break
        page_evidence.append(CitiTablePage(page_number, "table", crop, vertical, stop))
    if not page_evidence or not any(page.status == "table" for page in page_evidence):
        raise CitiTableError("no_table_pages")
    return CitiTableEvidence(
        1,
        hashlib.sha256(source).hexdigest(),
        ENGINE_VERSION,
        extraction_library,
        tuple(page_evidence),
        tuple(rows),
        False,
        False,
    )

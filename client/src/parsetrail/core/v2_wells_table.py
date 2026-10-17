"""Finite Wells Fargo business table geometry pilot over decoded PDF pages."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from parsetrail.core.v2_pdf_lines import MAX_PAGES, MAX_PDF_BYTES
from parsetrail.core.v2_pdf_routing import PDFRouting
from parsetrail.core.v2_table_continuations import ContinuationRule

ENGINE_VERSION = "wells-table-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MAX_WORDS_PER_PAGE = 20_000
MAX_TABLE_ROWS = 20_000
MAX_CELL_CHARS = 4096
HEADERS = ("Date", "Description", "Credits", "Debits", "balance")
DATED = re.compile(r"\d{1,2}/\d{1,2}")


class WellsTableError(ValueError):
    """Redacted extraction failure with optional page and table row."""

    def __init__(self, code: str, page: int | None = None, row: int | None = None):
        self.code = code
        self.page = page
        self.row = row
        super().__init__(code)


class WellsTableDefinition(BaseModel):
    routing: PDFRouting
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    capability: Literal["wells_business_geometry_v1"]
    statement_operation: Literal["bounded_business_table_statement_v1"]
    summary_label: str = Field(min_length=1, max_length=80)
    account_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_labels: tuple[str, ...] = Field(min_length=1, max_length=2)
    balance_window_lines: int = Field(ge=4, le=20)
    date_format: Literal["M/D_or_MM/DD"]
    money_format: Literal["usd_or_decimal_2dp"]
    continuation: ContinuationRule

    @model_validator(mode="after")
    def finite_statement(self) -> WellsTableDefinition:
        labels = (self.summary_label, self.account_label, self.opening_label, *self.closing_labels)
        if (
            len(set(labels)) != len(labels)
            or any(label != label.strip() or "\n" in label or "\r" in label for label in labels)
            or self.continuation.mode != "description_after_start"
            or self.continuation.start_columns != (0,)
            or self.continuation.break_columns != (0,)
            or self.continuation.description_column != 2
            or self.continuation.amount_column is not None
        ):
            raise ValueError("invalid business statement operation")
        return self


@dataclass(frozen=True, slots=True)
class TableRow:
    row_id: str
    page: int
    table_row: int
    region: tuple[float, float, float, float]
    raw_cells: tuple[str, ...]
    disposition: Literal["dated_candidate", "description_continuation", "terminator", "unresolved_after_stop"]


@dataclass(frozen=True, slots=True)
class TablePage:
    page: int
    status: Literal["no_header", "table"]
    header_region: tuple[float, float, float, float] | None
    vertical_lines: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class WellsTableEvidence:
    output_schema_version: int
    source_sha256: str
    definition_sha256: str
    engine_version: str
    extraction_library: str
    parser_id: str
    definition_revision: str
    pages: tuple[TablePage, ...]
    rows: tuple[TableRow, ...]
    coverage_verified: Literal[False]
    account_balance_reconciled: Literal[False]


def load_definition(data: bytes) -> tuple[WellsTableDefinition, str]:
    if not data or len(data) > MAX_DEFINITION_BYTES:
        raise WellsTableError("definition_size")
    try:
        definition = WellsTableDefinition.model_validate_json(data)
    except ValidationError:
        raise WellsTableError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _header_words(page, page_number: int) -> tuple[dict, ...] | None:
    words = page.extract_words()
    if len(words) > MAX_WORDS_PER_PAGE:
        raise WellsTableError("word_limit", page_number)
    candidates = [word for word in words if word.get("text") in HEADERS]
    if any(label not in {word["text"] for word in candidates} for label in HEADERS):
        return None
    bottoms = [word.get("bottom") for word in candidates]
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in bottoms):
        raise WellsTableError("invalid_header_geometry", page_number)
    # Match the accepted reader's modal-line selection, but refuse ambiguity.
    counts = Counter(bottoms)
    maximum = max(counts.values())
    modal = [value for value, count in counts.items() if count == maximum]
    if len(modal) != 1:
        raise WellsTableError("ambiguous_header_line", page_number)
    selected = tuple(word for word in candidates if abs(word["bottom"] - modal[0]) < 2)
    if len(selected) != len(HEADERS) or {word["text"] for word in selected} != set(HEADERS):
        raise WellsTableError("ambiguous_header_words", page_number)
    return selected


def extract_table_rows(
    definition_bytes: bytes,
    source_bytes: bytes,
    pages: Iterable,
    *,
    extraction_library: str,
    cancelled: Callable[[], bool] | None = None,
) -> WellsTableEvidence:
    """Extract raw regions/cells; no dates, money, postings or balances are inferred."""
    if not source_bytes or len(source_bytes) > MAX_PDF_BYTES:
        raise WellsTableError("source_size")
    if not extraction_library or len(extraction_library) > 80:
        raise WellsTableError("extraction_library")
    definition, definition_hash = load_definition(definition_bytes)
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    page_evidence = []
    rows = []
    for page_number, page in enumerate(pages, 1):
        if cancelled is not None and cancelled():
            raise WellsTableError("cancelled", page_number)
        if page_number > MAX_PAGES:
            raise WellsTableError("page_limit", page_number)
        selected = _header_words(page, page_number)
        if selected is None:
            page_evidence.append(TablePage(page_number, "no_header", None, ()))
            continue
        header = {word["text"]: word for word in selected}
        date, description, credits, debits, balance = (header[label] for label in HEADERS)
        vertical = (
            date["x0"] - 3,
            date["x1"] + 2,
            description["x0"] - 2,
            credits["x0"] - 3,
            credits["x1"] + 2,
            debits["x1"] + 2,
            balance["x1"] + 2,
        )
        crop_region = (vertical[0], date["bottom"] + 0.1, vertical[-1], page.height)
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (*vertical, *crop_region)):
            raise WellsTableError("invalid_table_geometry", page_number)
        if any(left >= right for left, right in zip(vertical, vertical[1:], strict=False)) or not (
            0 <= crop_region[0] < crop_region[2] <= page.width and 0 <= crop_region[1] < crop_region[3] <= page.height
        ):
            raise WellsTableError("invalid_table_geometry", page_number)
        table = page.crop(crop_region).find_table(
            table_settings={
                "vertical_strategy": "explicit",
                "horizontal_strategy": "text",
                "explicit_vertical_lines": vertical,
            }
        )
        if table is None:
            raise WellsTableError("missing_table", page_number)
        if len(table.rows) > MAX_TABLE_ROWS - len(rows):
            raise WellsTableError("table_row_limit_or_width", page_number)
        extracted = table.extract()
        if len(extracted) != len(table.rows):
            raise WellsTableError("table_row_locations", page_number)
        page_evidence.append(
            TablePage(page_number, "table", (date["x0"], date["top"], balance["x1"], balance["bottom"]), vertical)
        )
        stopped = False
        last_candidate = False
        for row_number, (cells, region) in enumerate(zip(extracted, table.rows, strict=True), 1):
            if cancelled is not None and cancelled():
                raise WellsTableError("cancelled", page_number, row_number)
            if len(rows) >= MAX_TABLE_ROWS or len(cells) != 6:
                raise WellsTableError("table_row_limit_or_width", page_number, row_number)
            values = tuple(cell or "" for cell in cells)
            if any(len(value) > MAX_CELL_CHARS for value in values):
                raise WellsTableError("cell_limit", page_number, row_number)
            bbox = tuple(region.bbox)
            if (
                len(bbox) != 4
                or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in bbox)
                or not (0 <= bbox[0] < bbox[2] <= page.width and 0 <= bbox[1] < bbox[3] <= page.height)
            ):
                raise WellsTableError("invalid_row_region", page_number, row_number)
            if stopped:
                if DATED.search(values[0]):
                    raise WellsTableError("dated_row_after_stop", page_number, row_number)
                disposition = "unresolved_after_stop"
            elif not any(values) or values[0].startswith("Ending"):
                disposition = "terminator"
                stopped = True
            elif DATED.search(values[0]):
                disposition = "dated_candidate"
                last_candidate = True
            elif not values[0] and values[2] and last_candidate:
                disposition = "description_continuation"
            else:
                raise WellsTableError("unresolved_table_row", page_number, row_number)
            row_id = hashlib.sha256(
                json.dumps(
                    [source_hash, definition_hash, ENGINE_VERSION, extraction_library, page_number, row_number],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            rows.append(TableRow(row_id, page_number, row_number, bbox, values, disposition))
    if not page_evidence or not any(page.status == "table" for page in page_evidence):
        raise WellsTableError("no_table_pages")
    return WellsTableEvidence(
        1,
        source_hash,
        definition_hash,
        ENGINE_VERSION,
        extraction_library,
        definition.parser_id,
        definition.revision,
        tuple(page_evidence),
        tuple(rows),
        False,
        False,
    )

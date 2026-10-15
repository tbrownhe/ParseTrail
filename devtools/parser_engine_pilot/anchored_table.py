"""Finite declared header-anchor geometry for bounded PDF table extraction."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from statistics import median
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from devtools.parser_engine_pilot.pdf_lines import MAX_PAGES, MAX_PDF_BYTES
from devtools.parser_engine_pilot.table_continuations import ContinuationRule

ENGINE_VERSION = "anchored-table-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MAX_WORDS_PER_PAGE = 20_000
MAX_CHARS_PER_PAGE = 200_000
MAX_TABLE_ROWS = 20_000
MAX_CELL_CHARS = 4096


class AnchorEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["anchor_edge"]
    anchor: int = Field(ge=0, le=15)
    edge: Literal["x0", "x1"]
    offset: float = Field(ge=-30, le=30)


class AnchorMidpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["anchor_midpoint"]
    left_anchor: int = Field(ge=0, le=15)
    left_edge: Literal["x0", "x1"]
    right_anchor: int = Field(ge=0, le=15)
    right_edge: Literal["x0", "x1"]
    offset: float = Field(ge=-30, le=30)


Boundary = Annotated[AnchorEdge | AnchorMidpoint, Field(discriminator="kind")]


class TableCardStatementRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operation: Literal["table_card_activity_v1"]
    date_format: Literal["MM/DD+MM/DD/YY"]
    money_format: Literal["usd_symbol_2dp"]
    amount_direction: Literal["invert_for_liability"]
    period_label: str = Field(min_length=1, max_length=80)
    account_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    repeated_header_date_cells: tuple[str, str]
    continuation: ContinuationRule

    @model_validator(mode="after")
    def valid_card_rule(self) -> TableCardStatementRule:
        labels = (self.period_label, self.account_label, self.opening_label, self.closing_label)
        rule = self.continuation
        if (
            len(set(labels)) != len(labels)
            or any(label != label.strip() or "\n" in label for label in labels)
            or any(not value or len(value) > 40 or value != value.strip() for value in self.repeated_header_date_cells)
            or rule.mode != "amount_on_last_row"
            or rule.start_columns != (0, 1)
            or rule.break_columns != (0, 1)
            or rule.description_column != 2
            or rule.amount_column != 3
        ):
            raise ValueError("invalid table card operation")
        return self


class AnchoredTableDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["anchored_columns_table_v1"]
    headers: tuple[str, ...] = Field(min_length=2, max_length=8)
    partial_suffix_min: int = Field(ge=3, le=8)
    header_line_tolerance: float = Field(ge=0, le=20)
    crop_top_anchor: int = Field(ge=0, le=7)
    crop_top_offset: float = Field(ge=0, le=20)
    boundaries: tuple[Boundary, ...] = Field(min_length=3, max_length=9)
    horizontal_strategy: Literal["text", "lines"]
    snap_y_tolerance: float = Field(ge=0, le=3)
    statement: TableCardStatementRule | None = None

    @model_validator(mode="after")
    def valid_geometry(self) -> AnchoredTableDefinition:
        if (
            len(set(self.headers)) != len(self.headers)
            or any(not item or item != item.strip() or len(item) > 40 or "\n" in item for item in self.headers)
            or self.crop_top_anchor >= len(self.headers)
            or len(self.boundaries) != len(self.headers) + 1
        ):
            raise ValueError("invalid header geometry")
        for boundary in self.boundaries:
            if isinstance(boundary, AnchorEdge):
                if boundary.anchor >= len(self.headers):
                    raise ValueError("invalid boundary anchor")
            elif boundary.left_anchor >= len(self.headers) or boundary.right_anchor >= len(self.headers):
                raise ValueError("invalid midpoint anchor")
        return self


class AnchoredTableError(ValueError):
    """Redacted refusal of invalid geometry or table extraction."""


@dataclass(frozen=True, slots=True)
class AnchoredPage:
    page: int
    status: Literal["no_header", "table"]
    header_region: tuple[float, float, float, float] | None
    vertical_lines: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class AnchoredRow:
    page: int
    ordinal: int
    region: tuple[float, float, float, float]
    raw_cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnchoredTableEvidence:
    output_schema_version: int
    source_sha256: str
    definition_sha256: str
    engine_version: str
    extraction_library: str
    first_page_chars: str
    pages: tuple[AnchoredPage, ...]
    rows: tuple[AnchoredRow, ...]
    coverage_verified: Literal[False]


def load_definition(data: bytes) -> tuple[AnchoredTableDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise AnchoredTableError("definition_size")
    try:
        definition = AnchoredTableDefinition.model_validate_json(data)
    except ValidationError:
        raise AnchoredTableError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _selected_header(page, definition: AnchoredTableDefinition):
    words = page.extract_words()
    if len(words) > MAX_WORDS_PER_PAGE:
        raise AnchoredTableError("word_limit")
    word_set = {word.get("text") for word in words}
    resolved = []
    for label in definition.headers:
        if label in word_set:
            resolved.append(label)
            continue
        matches = [
            word
            for word in word_set
            if isinstance(word, str) and label.endswith(word) and len(word) >= definition.partial_suffix_min
        ]
        if not matches:
            return None
        longest = max(len(word) for word in matches)
        best = [word for word in matches if len(word) == longest]
        if len(best) != 1:
            raise AnchoredTableError("ambiguous_header_fragment")
        resolved.append(best[0])
    if len(set(resolved)) != len(resolved):
        raise AnchoredTableError("duplicate_header_fragment")
    candidates = [word for word in words if word.get("text") in resolved]
    bottoms = [word.get("bottom") for word in candidates]
    if not bottoms or any(type(value) not in {int, float} or not math.isfinite(value) for value in bottoms):
        raise AnchoredTableError("invalid_header_geometry")
    center = median(bottoms)
    selected = [word for word in candidates if abs(word["bottom"] - center) < definition.header_line_tolerance]
    if len(selected) != len(resolved) or {word["text"] for word in selected} != set(resolved):
        return None
    return tuple(next(word for word in selected if word["text"] == label) for label in resolved)


def _boundary(boundary: Boundary, selected) -> float:
    if isinstance(boundary, AnchorEdge):
        return selected[boundary.anchor][boundary.edge] + boundary.offset
    return (
        selected[boundary.left_anchor][boundary.left_edge] + selected[boundary.right_anchor][boundary.right_edge]
    ) / 2 + boundary.offset


def _region(region: tuple[float, float, float, float], page) -> bool:
    return all(type(value) in {int, float} and math.isfinite(value) for value in region) and (
        0 <= region[0] < region[2] <= page.width and 0 <= region[1] < region[3] <= page.height
    )


def extract_anchored_table(
    definition_bytes: bytes, source: bytes, pages, *, extraction_library: str
) -> AnchoredTableEvidence:
    """Return raw table cells and locations without interpreting money or dates."""
    if type(source) is not bytes or not 0 < len(source) <= MAX_PDF_BYTES:
        raise AnchoredTableError("source_size")
    definition, definition_hash = load_definition(definition_bytes)
    if not extraction_library or len(extraction_library) > 80:
        raise AnchoredTableError("extraction_library")
    page_evidence = []
    rows = []
    first_page_chars = ""
    for page_number, page in enumerate(pages, 1):
        if page_number > MAX_PAGES or len(page.chars) > MAX_CHARS_PER_PAGE:
            raise AnchoredTableError("page_limit")
        if page_number == 1:
            first_page_chars = "".join(char["text"] for char in page.chars)
            if not first_page_chars or len(first_page_chars) > MAX_CHARS_PER_PAGE:
                raise AnchoredTableError("first_page_chars_limit")
        selected = _selected_header(page, definition)
        if selected is None:
            page_evidence.append(AnchoredPage(page_number, "no_header", None, ()))
            continue
        vertical = tuple(_boundary(item, selected) for item in definition.boundaries)
        crop = (
            vertical[0],
            selected[definition.crop_top_anchor]["bottom"] + definition.crop_top_offset,
            vertical[-1],
            page.height,
        )
        if (
            not all(math.isfinite(value) for value in vertical)
            or any(left >= right for left, right in zip(vertical, vertical[1:], strict=False))
            or not _region(crop, page)
        ):
            raise AnchoredTableError("invalid_table_geometry")
        table = page.crop(crop).find_table(
            table_settings={
                "vertical_strategy": "explicit",
                "horizontal_strategy": definition.horizontal_strategy,
                "snap_y_tolerance": definition.snap_y_tolerance,
                "explicit_vertical_lines": vertical,
            }
        )
        if table is None:
            raise AnchoredTableError("missing_table")
        cells = table.extract()
        if len(cells) != len(table.rows) or len(rows) + len(cells) > MAX_TABLE_ROWS:
            raise AnchoredTableError("row_limit_or_locations")
        header_region = (
            min(word["x0"] for word in selected),
            min(word["top"] for word in selected),
            max(word["x1"] for word in selected),
            max(word["bottom"] for word in selected),
        )
        if not _region(header_region, page):
            raise AnchoredTableError("invalid_header_geometry")
        page_evidence.append(AnchoredPage(page_number, "table", header_region, vertical))
        for ordinal, (row, region) in enumerate(zip(cells, table.rows, strict=True), 1):
            values = tuple(value or "" for value in row)
            bbox = tuple(region.bbox)
            if (
                len(values) != len(definition.headers)
                or any(len(value) > MAX_CELL_CHARS for value in values)
                or not _region(bbox, page)
            ):
                raise AnchoredTableError("invalid_table_row")
            rows.append(AnchoredRow(page_number, ordinal, bbox, values))
    if not page_evidence or not any(page.status == "table" for page in page_evidence):
        raise AnchoredTableError("no_table_pages")
    return AnchoredTableEvidence(
        1,
        hashlib.sha256(source).hexdigest(),
        definition_hash,
        ENGINE_VERSION,
        extraction_library,
        first_page_chars,
        tuple(page_evidence),
        tuple(rows),
        False,
    )

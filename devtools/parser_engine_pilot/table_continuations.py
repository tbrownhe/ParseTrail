"""Finite table-row continuation operation over already decoded PDF cells."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_INPUT_ROWS = 20_000
MAX_COLUMNS = 16
MAX_CELL_CHARS = 4096
MAX_PAGE = 100


class ContinuationError(ValueError):
    """Redacted refusal for an incomplete or ambiguous row group."""


class ContinuationRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["table_continuation_v1"]
    mode: Literal["amount_on_last_row", "description_after_start"]
    start_columns: tuple[int, ...] = Field(min_length=1, max_length=2)
    break_columns: tuple[int, ...] = Field(min_length=1, max_length=2)
    description_column: int = Field(ge=0, lt=MAX_COLUMNS)
    amount_column: int | None = Field(default=None, ge=0, lt=MAX_COLUMNS)
    max_group_rows: int = Field(ge=1, le=8)
    allow_cross_page: bool = False

    @model_validator(mode="after")
    def valid_columns(self) -> ContinuationRule:
        columns = (*self.start_columns, *self.break_columns, self.description_column)
        if (
            len(set(self.start_columns)) != len(self.start_columns)
            or len(set(self.break_columns)) != len(self.break_columns)
            or any(column < 0 or column >= MAX_COLUMNS for column in columns)
            or not set(self.break_columns).issubset(self.start_columns)
            or self.description_column in self.start_columns
            or (self.mode == "amount_on_last_row" and self.amount_column is None)
            or (self.amount_column is not None and self.amount_column in {*self.start_columns, self.description_column})
        ):
            raise ValueError("invalid continuation columns")
        return self


@dataclass(frozen=True, slots=True)
class RawTableRow:
    page: int
    ordinal: int
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JoinedTableRow:
    sources: tuple[RawTableRow, ...]
    description: str
    amount_raw: str | None


def assemble(rule: ContinuationRule, rows: tuple[RawTableRow, ...]) -> tuple[JoinedTableRow, ...]:
    """Join only declared continuation shapes; retain every source row."""
    if len(rows) > MAX_INPUT_ROWS:
        raise ContinuationError("row_limit")
    referenced = (*rule.start_columns, *rule.break_columns, rule.description_column)
    if rule.amount_column is not None:
        referenced += (rule.amount_column,)
    groups = []
    pending: list[RawTableRow] = []
    last_location = (0, 0)

    def finish() -> None:
        if not pending:
            return
        parts = [row.cells[rule.description_column].strip() for row in pending]
        if any(not part for part in parts):
            raise ContinuationError("empty_description")
        amount_row = pending[-1] if rule.mode == "amount_on_last_row" else pending[0]
        amount = amount_row.cells[rule.amount_column].strip() if rule.amount_column is not None else None
        if rule.mode == "amount_on_last_row" and not amount:
            raise ContinuationError("missing_terminal_amount")
        groups.append(JoinedTableRow(tuple(pending), " ".join(parts), amount))
        pending.clear()

    for row in rows:
        if (
            row.page < 1
            or row.page > MAX_PAGE
            or row.ordinal < 1
            or (row.page, row.ordinal) <= last_location
            or len(row.cells) <= max(referenced)
            or len(row.cells) > MAX_COLUMNS
            or any(not isinstance(cell, str) or len(cell) > MAX_CELL_CHARS for cell in row.cells)
        ):
            raise ContinuationError("invalid_table_row")
        last_location = (row.page, row.ordinal)
        starts = any(row.cells[column].strip() for column in rule.start_columns)
        breaks = any(row.cells[column].strip() for column in rule.break_columns)
        if not pending:
            if not starts:
                raise ContinuationError("orphan_continuation")
            pending.append(row)
        elif breaks:
            if rule.mode == "amount_on_last_row":
                raise ContinuationError("new_row_before_amount")
            finish()
            pending.append(row)
        else:
            if row.page != pending[-1].page and not rule.allow_cross_page:
                raise ContinuationError("unexpected_page_break")
            pending.append(row)
        if len(pending) > rule.max_group_rows:
            raise ContinuationError("continuation_limit")
        if rule.mode == "amount_on_last_row" and rule.amount_column is not None:
            if row.cells[rule.amount_column].strip():
                finish()
    finish()
    return tuple(groups)

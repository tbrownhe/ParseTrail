"""Bounded P2-2 table-declaration pilot; not part of runtime imports."""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ENGINE_VERSION = "table-pilot-2"
MAX_DEFINITION_BYTES = 64 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 64
MAX_CELLS = 1_000_000
MAX_CELL_CHARS = 4096
MAX_MONEY_CHARS = 30
MAX_MONEY_MINOR = 9_000_000_000_000_000
MONEY_PATTERN = re.compile(r"-?\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}\Z")
LOAN_ID_PATTERN = re.compile(r"([0-9]+-[0-9]+) .+\Z")


class EngineError(ValueError):
    """Redacted declaration or source failure with an optional source row."""

    def __init__(self, code: str, row: int | None = None):
        self.code = code
        self.row = row
        super().__init__(f"{code} at row {row}" if row is not None else code)


class Columns(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account: str | None = None
    date: str
    description: str
    total: str
    balance: str | None = None
    principal: str | None = None
    interest: str | None = None
    fees: str | None = None


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".csv", ".xlsx"]
    kind: Literal["activity_export"]
    capabilities: tuple[Literal["table_rows_v1", "components_v1"], ...]
    header: tuple[str, ...] = Field(min_length=1, max_length=MAX_COLUMNS)
    columns: Columns
    date_format: Literal["MM/DD/YYYY", "YYYY-MM-DD"]
    date_role: Literal["activity_date", "posting_date"] = "activity_date"
    money_format: Literal["usd_symbol_2dp"]
    unknown_balance_literals: tuple[str, ...] = ()
    first_header_cell: Literal["exact", "after_last_gt"] = "exact"
    empty_trailing_column: bool = False
    account_key: Literal["observed", "loan_id_dash_v1", "unknown"] = "observed"

    @model_validator(mode="after")
    def valid_layout(self) -> Definition:
        if "table_rows_v1" not in self.capabilities or len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("invalid capabilities")
        if not 1 <= len(self.header) <= MAX_COLUMNS or any(
            not value or len(value) > MAX_CELL_CHARS for value in self.header
        ):
            raise ValueError("invalid header")
        if len(set(self.header)) != len(self.header):
            raise ValueError("duplicate header")
        values = [value for value in self.columns.model_dump().values() if value is not None]
        if len(values) != len(set(values)) or any(value not in self.header for value in values):
            raise ValueError("invalid column mapping")
        components = (self.columns.principal, self.columns.interest, self.columns.fees)
        if any(components) != all(components) or (all(components) != ("components_v1" in self.capabilities)):
            raise ValueError("incomplete component operation")
        if self.columns.balance is None and self.unknown_balance_literals:
            raise ValueError("unknown balance literals require a balance column")
        if (self.columns.account is None) != (self.account_key == "unknown"):
            raise ValueError("account identity declaration")
        if len(self.unknown_balance_literals) > 16 or len(set(self.unknown_balance_literals)) != len(
            self.unknown_balance_literals
        ):
            raise ValueError("duplicate unknown balance literal")
        if any(not value or len(value) > 80 for value in self.unknown_balance_literals):
            raise ValueError("invalid unknown balance literal")
        if self.empty_trailing_column and len(self.header) == MAX_COLUMNS:
            raise ValueError("trailing column exceeds limit")
        return self


@dataclass(frozen=True, slots=True)
class CellLocation:
    suffix: Literal[".csv", ".xlsx"]
    row: int
    column: int
    sheet: str | None = None

    @property
    def cell_reference(self) -> str | None:
        if self.suffix != ".xlsx":
            return None
        number = self.column
        letters = ""
        while number:
            number, remainder = divmod(number - 1, 26)
            letters = chr(65 + remainder) + letters
        return f"{letters}{self.row}"


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    raw: str
    normalized: str | int | None
    provenance: Literal["observed", "unknown"]
    location: CellLocation


@dataclass(frozen=True, slots=True)
class ActivityRow:
    row_id: str
    occurrence: int
    account: FieldEvidence | None
    date: FieldEvidence
    description: FieldEvidence
    total: FieldEvidence
    components: tuple[tuple[str, FieldEvidence], ...]
    balance: FieldEvidence | None


@dataclass(frozen=True, slots=True)
class IgnoredRow:
    row: int
    reason: Literal["blank_row"]


@dataclass(frozen=True, slots=True)
class Evidence:
    output_schema_version: int
    source_sha256: str
    definition_sha256: str
    engine_version: str
    extraction_adapter: str
    parser_id: str
    definition_revision: str
    account_key: str
    date_format: str
    date_role: Literal["activity_date", "posting_date"]
    money_format: str
    kind: Literal["activity_export"]
    rows: tuple[ActivityRow, ...]
    ignored_rows: tuple[IgnoredRow, ...]
    account_identities: tuple[str, ...]
    activity_start: str | None
    activity_end: str | None
    statement_opening_minor: None
    statement_closing_minor: None
    coverage_verified: Literal[False]
    balance_reconciled: Literal[False]


def load_definition(data: bytes) -> tuple[Definition, str]:
    if not data or len(data) > MAX_DEFINITION_BYTES:
        raise EngineError("definition_size")
    try:
        definition = Definition.model_validate_json(data)
    except ValidationError:
        raise EngineError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _money(raw: str, row: int) -> int:
    if len(raw) > MAX_MONEY_CHARS or MONEY_PATTERN.fullmatch(raw) is None:
        raise EngineError("invalid_money", row)
    negative = raw.startswith("-")
    major, cents = raw.removeprefix("-").removeprefix("$").replace(",", "").split(".")
    minor = int(major) * 100 + int(cents)
    if negative:
        minor = -minor
    if abs(minor) > MAX_MONEY_MINOR:
        raise EngineError("money_range", row)
    return minor


def _date(raw: str, fmt: str, row: int) -> str:
    pattern = "%m/%d/%Y" if fmt == "MM/DD/YYYY" else "%Y-%m-%d"
    try:
        value = datetime.strptime(raw, pattern).date()
    except ValueError:
        raise EngineError("invalid_date", row) from None
    if value.strftime(pattern) != raw:
        raise EngineError("invalid_date", row)
    return value.isoformat()


def parse_table(
    definition_bytes: bytes,
    source_bytes: bytes,
    rows: Iterable[Sequence[str | None]],
    *,
    suffix: Literal[".csv", ".xlsx"],
    sheet: str | None = None,
    extraction_adapter: str = "predecoded-rows-pilot-1",
    cancelled: Callable[[], bool] | None = None,
) -> Evidence:
    """Parse bounded decoded table rows. XLSX decoding is outside this pilot."""
    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise EngineError("source_size")
    definition, definition_hash = load_definition(definition_bytes)
    if not extraction_adapter or len(extraction_adapter) > 80:
        raise EngineError("extraction_adapter")
    if definition.suffix != suffix or (suffix == ".xlsx" and not sheet) or (suffix == ".csv" and sheet is not None):
        raise EngineError("source_kind")
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    index = {name: position for position, name in enumerate(definition.header)}
    parsed = []
    ignored = []
    seen = Counter()
    account_names = {}
    cell_count = 0
    for row_number, raw_row in enumerate(rows, 1):
        if cancelled is not None and cancelled():
            raise EngineError("cancelled", row_number)
        if row_number > MAX_ROWS:
            raise EngineError("row_limit")
        values = tuple("" if cell is None else cell for cell in itertools.islice(raw_row, MAX_COLUMNS + 1))
        cell_count += len(values)
        if (
            cell_count > MAX_CELLS
            or len(values) > MAX_COLUMNS
            or any(not isinstance(cell, str) or len(cell) > MAX_CELL_CHARS for cell in values)
        ):
            raise EngineError("cell_limit", row_number)
        if row_number == 1:
            if definition.empty_trailing_column:
                if not values or values[-1] != "":
                    raise EngineError("header_mismatch", row_number)
                values = values[:-1]
            if definition.first_header_cell == "after_last_gt" and values:
                values = (values[0].split(">")[-1], *values[1:])
            if values != definition.header:
                raise EngineError("header_mismatch", row_number)
            continue
        if not any(values):
            ignored.append(IgnoredRow(row_number, "blank_row"))
            continue
        if definition.empty_trailing_column:
            if not values or values[-1] != "":
                raise EngineError("trailing_column", row_number)
            values = values[:-1]
        if len(values) != len(definition.header):
            raise EngineError("row_width", row_number)

        def field(
            column: str,
            normalized: str | int | None,
            provenance: Literal["observed", "unknown"] = "observed",
            *,
            values: tuple[str, ...] = values,
            row_number: int = row_number,
        ) -> FieldEvidence:
            column_number = index[column] + 1
            return FieldEvidence(
                raw=values[column_number - 1],
                normalized=normalized,
                provenance=provenance,
                location=CellLocation(suffix, row_number, column_number, sheet),
            )

        account_raw = values[index[definition.columns.account]] if definition.columns.account is not None else None
        description_raw = values[index[definition.columns.description]]
        if (account_raw is not None and not account_raw.strip()) or not description_raw.strip():
            raise EngineError("missing_identity_or_description", row_number)
        account_key = account_raw
        if definition.account_key == "loan_id_dash_v1":
            assert account_raw is not None
            match = LOAN_ID_PATTERN.fullmatch(account_raw)
            if match is None:
                raise EngineError("account_identity", row_number)
            account_key = match[1]
            if account_key in account_names and account_names[account_key] != account_raw:
                raise EngineError("account_name_conflict", row_number)
            account_names[account_key] = account_raw
        account = field(definition.columns.account, account_key) if definition.columns.account is not None else None
        date_column = definition.columns.date
        date = field(date_column, _date(values[index[date_column]], definition.date_format, row_number))
        description = field(definition.columns.description, description_raw)
        total_column = definition.columns.total
        total = field(total_column, _money(values[index[total_column]], row_number))
        components = []
        for role in ("principal", "interest", "fees"):
            column = getattr(definition.columns, role)
            if column is not None:
                components.append((role, field(column, _money(values[index[column]], row_number))))
        if components and sum(item.normalized for _role, item in components) != total.normalized:
            raise EngineError("component_equation", row_number)
        balance = None
        if definition.columns.balance is not None:
            balance_column = definition.columns.balance
            balance_raw = values[index[balance_column]]
            if balance_raw in definition.unknown_balance_literals:
                balance = field(balance_column, None, "unknown")
            else:
                balance = field(balance_column, _money(balance_raw, row_number))
        duplicate_key = values
        occurrence = seen[duplicate_key]
        seen[duplicate_key] += 1
        row_id = hashlib.sha256(
            f"{source_hash}:{definition_hash}:{ENGINE_VERSION}:{extraction_adapter}:{row_number}:{occurrence}".encode()
        ).hexdigest()
        parsed.append(ActivityRow(row_id, occurrence, account, date, description, total, tuple(components), balance))
    if not parsed:
        raise EngineError("no_activity_rows")
    dates = [row.date.normalized for row in parsed]
    return Evidence(
        output_schema_version=1,
        source_sha256=source_hash,
        definition_sha256=definition_hash,
        engine_version=ENGINE_VERSION,
        extraction_adapter=extraction_adapter,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        account_key=definition.account_key,
        date_format=definition.date_format,
        date_role=definition.date_role,
        money_format=definition.money_format,
        kind="activity_export",
        rows=tuple(parsed),
        ignored_rows=tuple(ignored),
        account_identities=tuple(sorted({row.account.normalized for row in parsed if row.account is not None})),
        activity_start=min(dates),
        activity_end=max(dates),
        statement_opening_minor=None,
        statement_closing_minor=None,
        coverage_verified=False,
        balance_reconciled=False,
    )


def parse_csv(definition_bytes: bytes, source_bytes: bytes, *, cancelled: Callable[[], bool] | None = None) -> Evidence:
    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise EngineError("source_size")
    try:
        text = source_bytes.decode("utf-8-sig")
        rows = csv.reader(io.StringIO(text), strict=True)
        return parse_table(
            definition_bytes,
            source_bytes,
            rows,
            suffix=".csv",
            extraction_adapter=f"python-csv-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            cancelled=cancelled,
        )
    except (UnicodeError, csv.Error):
        raise EngineError("csv_structure") from None

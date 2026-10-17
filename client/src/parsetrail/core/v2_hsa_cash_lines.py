"""Finite HealthEquity cash-section pilot over extracted PDF page lines."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from parsetrail.core.v2_pdf_lines import PageLine, PDFLineEvidence

ENGINE_VERSION = "hsa-cash-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MAX_DATED_LINE_CHARS = 512
MAX_MONEY_MINOR = 9_000_000_000_000_000
PERIOD = re.compile(r"(?P<start>\d{2}/\d{2}/\d{2})\s*through\s*(?P<end>\d{2}/\d{2}/\d{2})\Z")
DATED_ROW = re.compile(r"^\d{2}/\d{2}/\d{4}\s")
MONEY_BODY = r"\$?(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
MONEY = re.compile(rf"(?:{MONEY_BODY}|-{MONEY_BODY}|\({MONEY_BODY}\))\Z")
Provenance = Literal["printed", "unknown_description"]


class HsaCashError(ValueError):
    """Redacted cash-section failure with optional page and line."""

    def __init__(self, code: str, location: PageLine | None = None):
        self.code = code
        self.page = location.page if location else None
        self.line = location.line if location else None
        super().__init__(code)


class HsaCashDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["cash_statement_section"]
    capabilities: tuple[
        Literal["pdf_lines_v1", "ordered_cash_boundaries_v1", "dated_cash_rows_v1", "printed_cash_chain_v1"], ...
    ]
    period_label: str = Field(min_length=1, max_length=80)
    account_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    period_date_format: Literal["MM/DD/YY"]
    row_date_format: Literal["MM/DD/YYYY"]
    money_format: Literal["signed_decimal_2dp"]
    line_prefix: Literal["strip_underscore_space"]

    @model_validator(mode="after")
    def valid_layout(self) -> HsaCashDefinition:
        required = {"pdf_lines_v1", "ordered_cash_boundaries_v1", "dated_cash_rows_v1", "printed_cash_chain_v1"}
        if set(self.capabilities) != required or len(self.capabilities) != len(required):
            raise ValueError("invalid capabilities")
        labels = (self.period_label, self.account_label, self.opening_label, self.closing_label)
        if len(set(labels)) != len(labels) or any(
            label != label.strip() or "\r" in label or "\n" in label for label in labels
        ):
            raise ValueError("invalid labels")
        return self


@dataclass(frozen=True, slots=True)
class CashField:
    raw: str
    normalized: str | int | None
    provenance: Provenance
    source_line_id: str
    page: int
    line: int


@dataclass(frozen=True, slots=True)
class CashRow:
    row_id: str
    date: CashField
    description: CashField
    amount_minor: CashField
    printed_running_minor: CashField


@dataclass(frozen=True, slots=True)
class UnresolvedSectionLine:
    source_line_id: str
    page: int
    line: int
    raw: str
    reason: Literal[
        "cash_window_heading",
        "cash_window_rate_table",
        "cash_window_fee_summary",
        "cash_window_interest_disclosure",
        "cash_window_unclassified",
    ]


@dataclass(frozen=True, slots=True)
class HsaCashEvidence:
    output_schema_version: int
    source_sha256: str
    definition_sha256: str
    engine_version: str
    extraction_library: str
    line_adapter_version: str
    parser_id: str
    definition_revision: str
    account_identity: CashField
    period_start: CashField
    period_end: CashField
    printed_opening_minor: CashField
    printed_closing_minor: CashField
    rows: tuple[CashRow, ...]
    unresolved_section_lines: tuple[UnresolvedSectionLine, ...]
    cash_chain_verified: Literal[True]
    coverage_verified: Literal[False]
    account_balance_reconciled: Literal[False]


def load_definition(data: bytes) -> tuple[HsaCashDefinition, str]:
    if not data or len(data) > MAX_DEFINITION_BYTES:
        raise HsaCashError("definition_size")
    try:
        definition = HsaCashDefinition.model_validate_json(data)
    except ValidationError:
        raise HsaCashError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _field(raw: str, normalized: str | int | None, provenance: Provenance, line: PageLine) -> CashField:
    return CashField(raw, normalized, provenance, line.line_id, line.page, line.line)


def _date(raw: str, fmt: str, line: PageLine) -> str:
    pattern = "%m/%d/%y" if fmt == "MM/DD/YY" else "%m/%d/%Y"
    try:
        parsed = datetime.strptime(raw, pattern).date()
    except ValueError:
        raise HsaCashError("invalid_date", line) from None
    if parsed.strftime(pattern) != raw:
        raise HsaCashError("invalid_date", line)
    return parsed.isoformat()


def _money(raw: str, line: PageLine) -> int:
    if len(raw) > 30 or MONEY.fullmatch(raw) is None:
        raise HsaCashError("invalid_money", line)
    negative = raw.startswith("-") or raw.startswith("(")
    body = raw.removeprefix("-").removeprefix("(").removesuffix(")").removeprefix("$").replace(",", "")
    major, cents = body.split(".")
    minor = int(major) * 100 + int(cents)
    if minor > MAX_MONEY_MINOR:
        raise HsaCashError("money_range", line)
    return -minor if negative else minor


def _non_dated_disposition(raw: str) -> str:
    """Classify printed non-activity lines inside the cash balance boundaries."""
    line = raw.lstrip("_ ")
    if line in {
        "",
        "Interest AverageDaily Interest",
        "BalanceTier",
        "Rate Balance Earned YeartoDate",
        "Period",
        "AccountStatement(Continued)",
        ". Depositor Account",
        "Date DescriptionofTransaction (Withdrawal) Balance",
    } or re.fullmatch(r"[1-9][0-9]*of[1-9][0-9]*", line):
        return "cash_window_heading"
    if line.startswith(("TotalNon-SufficientFundsFees ", "TotalReturnDepositItemFees ", "TotalOverdraftFees ")):
        return "cash_window_fee_summary"
    if re.fullmatch(r"\$[0-9][0-9,]*\.[0-9]{2}\)", line):
        return "cash_window_interest_disclosure"
    if line.startswith(("$", "Over$", "Total ", "Fundsarecurrentlyheldat", "InterestRateScheduleEffective:")):
        return "cash_window_rate_table"
    if line.startswith(
        (
            "Interestfor",
            "forperiodis",
            "yieldearnedforperiodis",
            "percentageyieldearnedforperiodis",
            "averagecollectedbalanceof",
            "balanceof",
            "investedbalanceof",
            "of$",
        )
    ):
        return "cash_window_interest_disclosure"
    return "cash_window_unclassified"


def parse_cash_section(
    definition_bytes: bytes,
    lines: PDFLineEvidence,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> HsaCashEvidence:
    """Parse and check printed cash only; retain other section lines unresolved."""
    definition, definition_hash = load_definition(definition_bytes)
    found: dict[str, tuple[PageLine, str]] = {}
    for line in lines.lines:
        if cancelled is not None and cancelled():
            raise HsaCashError("cancelled", line)
        normalized = line.normalized.lstrip("_ ")
        if normalized.startswith(definition.opening_label):
            role, value = "opening", normalized.removeprefix(definition.opening_label).strip()
        elif normalized.startswith(definition.closing_label):
            role, value = "closing", normalized.removeprefix(definition.closing_label).strip()
        elif normalized.startswith(definition.account_label):
            parts = normalized.removeprefix(definition.account_label).split()
            role, value = "account", parts[0] if parts else ""
        elif " " + definition.account_label in normalized:
            parts = normalized.rsplit(" " + definition.account_label, 1)[1].split()
            role, value = "account", parts[0] if parts else ""
        else:
            marker = " " + definition.period_label
            if normalized.startswith(definition.period_label):
                role, value = "period", normalized.removeprefix(definition.period_label)
            elif marker in normalized:
                role, value = "period", normalized.rsplit(marker, 1)[1]
            else:
                continue
        if role in found:
            raise HsaCashError("duplicate_" + role, line)
        if not value:
            raise HsaCashError("empty_" + role, line)
        found[role] = (line, value)
    if set(found) != {"period", "account", "opening", "closing"}:
        raise HsaCashError("missing_printed_field")
    period_line, period_raw = found["period"]
    period = PERIOD.fullmatch(period_raw)
    if period is None:
        raise HsaCashError("invalid_period", period_line)
    start = _date(period["start"], definition.period_date_format, period_line)
    end = _date(period["end"], definition.period_date_format, period_line)
    if end < start:
        raise HsaCashError("invalid_period", period_line)
    opening_line, opening_raw = found["opening"]
    closing_line, closing_raw = found["closing"]
    positions = {line.line_id: index for index, line in enumerate(lines.lines)}
    first, last = positions[opening_line.line_id], positions[closing_line.line_id]
    if first >= last:
        raise HsaCashError("cash_boundaries_out_of_order", closing_line)
    opening_minor = _money(opening_raw, opening_line)
    closing_minor = _money(closing_raw, closing_line)
    running = opening_minor
    rows = []
    unresolved = []
    for line in lines.lines[first + 1 : last]:
        if cancelled is not None and cancelled():
            raise HsaCashError("cancelled", line)
        normalized = line.normalized.lstrip("_ ")
        if DATED_ROW.match(normalized) is None:
            unresolved.append(
                UnresolvedSectionLine(line.line_id, line.page, line.line, line.raw, _non_dated_disposition(line.raw))
            )
            continue
        if len(normalized) > MAX_DATED_LINE_CHARS:
            raise HsaCashError("dated_line_limit", line)
        parts = normalized.split()
        if len(parts) < 3:
            raise HsaCashError("incomplete_cash_row", line)
        date_raw, amount_raw, balance_raw = parts[0], parts[-2], parts[-1]
        date_value = _date(date_raw, definition.row_date_format, line)
        amount = _money(amount_raw, line)
        balance = _money(balance_raw, line)
        running += amount
        if running != balance:
            raise HsaCashError("printed_running_mismatch", line)
        description_raw = " ".join(parts[1:-2])
        row_id = hashlib.sha256(
            json.dumps(
                [
                    lines.source_sha256,
                    definition_hash,
                    ENGINE_VERSION,
                    lines.adapter_version,
                    lines.extraction_library,
                    line.page,
                    line.line,
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        rows.append(
            CashRow(
                row_id,
                _field(date_raw, date_value, "printed", line),
                _field(
                    description_raw,
                    description_raw or None,
                    "printed" if description_raw else "unknown_description",
                    line,
                ),
                _field(amount_raw, amount, "printed", line),
                _field(balance_raw, balance, "printed", line),
            )
        )
    if running != closing_minor:
        raise HsaCashError("printed_closing_mismatch", closing_line)
    account_line, account_raw = found["account"]
    return HsaCashEvidence(
        output_schema_version=1,
        source_sha256=lines.source_sha256,
        definition_sha256=definition_hash,
        engine_version=ENGINE_VERSION,
        extraction_library=lines.extraction_library,
        line_adapter_version=lines.adapter_version,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        account_identity=_field(account_raw, account_raw, "printed", account_line),
        period_start=_field(period["start"], start, "printed", period_line),
        period_end=_field(period["end"], end, "printed", period_line),
        printed_opening_minor=_field(opening_raw, opening_minor, "printed", opening_line),
        printed_closing_minor=_field(closing_raw, closing_minor, "printed", closing_line),
        rows=tuple(rows),
        unresolved_section_lines=tuple(unresolved),
        cash_chain_verified=True,
        coverage_verified=False,
        account_balance_reconciled=False,
    )

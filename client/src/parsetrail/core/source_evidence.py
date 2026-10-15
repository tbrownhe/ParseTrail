"""Strict 2.0 parser output, before any profile or ledger write.

Source evidence contains no account mapping, category, verification or posting.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z][a-z0-9_.-]{0,79}$"
MAX_MINOR = 9_000_000_000_000_000


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PdfLine(EvidenceModel):
    kind: Literal["pdf_line"]
    page: int = Field(ge=1, le=100)
    line: int = Field(ge=1, le=20_000)
    end_line: int | None = Field(default=None, ge=1, le=20_000)

    @model_validator(mode="after")
    def ordered(self) -> PdfLine:
        if self.end_line is not None and self.end_line < self.line:
            raise ValueError("invalid PDF line span")
        return self


class PdfTableRow(EvidenceModel):
    kind: Literal["pdf_table_row"]
    page: int = Field(ge=1, le=100)
    row: int = Field(ge=1, le=20_000)
    region: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def valid_region(self) -> PdfTableRow:
        if self.region is not None:
            import math

            x0, y0, x1, y1 = self.region
            if not all(math.isfinite(value) for value in self.region) or not (0 <= x0 < x1 and 0 <= y0 < y1):
                raise ValueError("invalid PDF region")
        return self


class PdfChars(EvidenceModel):
    kind: Literal["pdf_chars"]
    page: int = Field(ge=1, le=100)
    start: int = Field(ge=0, le=200_000)
    end: int = Field(ge=1, le=200_000)

    @model_validator(mode="after")
    def ordered(self) -> PdfChars:
        if self.end <= self.start:
            raise ValueError("invalid PDF character span")
        return self


class CsvCell(EvidenceModel):
    kind: Literal["csv_cell"]
    row: int = Field(ge=1, le=100_000)
    column: int = Field(ge=1, le=64)


class CsvRow(EvidenceModel):
    kind: Literal["csv_row"]
    row: int = Field(ge=1, le=100_000)


class XlsxCell(EvidenceModel):
    kind: Literal["xlsx_cell"]
    sheet: str = Field(min_length=1, max_length=100)
    row: int = Field(ge=1, le=100_000)
    column: int = Field(ge=1, le=64)


class XlsxRow(EvidenceModel):
    kind: Literal["xlsx_row"]
    sheet: str = Field(min_length=1, max_length=100)
    row: int = Field(ge=1, le=100_000)


SourceLocation = Annotated[
    PdfLine | PdfTableRow | PdfChars | CsvCell | CsvRow | XlsxCell | XlsxRow, Field(discriminator="kind")
]


class MoneyValue(EvidenceModel):
    raw: str | None = Field(max_length=4096)
    minor: int | None
    provenance: Literal["observed", "derived", "unknown"]
    locations: tuple[SourceLocation, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def consistent(self) -> MoneyValue:
        if self.minor is not None and abs(self.minor) > MAX_MINOR:
            raise ValueError("money range")
        if self.provenance == "observed" and (self.raw is None or self.minor is None or not self.locations):
            raise ValueError("observed money needs source and exact value")
        if self.provenance == "derived" and (self.raw is not None or self.minor is None or not self.locations):
            raise ValueError("derived money needs inputs, not a printed value")
        if self.provenance == "unknown" and self.minor is not None:
            raise ValueError("unknown money cannot have a value")
        return self


class DateValue(EvidenceModel):
    raw: str | None = Field(max_length=80)
    iso: str | None = Field(max_length=10)
    provenance: Literal["observed", "derived", "unknown"]
    locations: tuple[SourceLocation, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def consistent(self) -> DateValue:
        if self.iso is not None:
            try:
                if date.fromisoformat(self.iso).isoformat() != self.iso:
                    raise ValueError
            except ValueError:
                raise ValueError("invalid evidence date") from None
        if self.provenance == "observed" and (self.raw is None or self.iso is None or not self.locations):
            raise ValueError("observed date needs source and value")
        if self.provenance == "derived" and (self.raw is not None or self.iso is None or not self.locations):
            raise ValueError("derived date needs inputs")
        if self.provenance == "unknown" and self.iso is not None:
            raise ValueError("unknown date cannot have a value")
        return self


class TextValue(EvidenceModel):
    raw: str | None = Field(max_length=4096)
    text: str | None = Field(max_length=4096)
    provenance: Literal["observed", "derived", "unknown"]
    locations: tuple[SourceLocation, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def consistent(self) -> TextValue:
        if self.provenance == "observed" and (self.raw is None or self.text is None or not self.locations):
            raise ValueError("observed text needs source and value")
        if self.provenance == "derived" and (self.raw is not None or self.text is None or not self.locations):
            raise ValueError("derived text needs inputs")
        if self.provenance == "unknown" and self.text is not None:
            raise ValueError("unknown text cannot have a value")
        return self


class SourceFragment(EvidenceModel):
    channel: str = Field(pattern=IDENTIFIER)
    location: SourceLocation
    raw_values: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def bounded(self) -> SourceFragment:
        if any(len(value) > 4096 for value in self.raw_values):
            raise ValueError("raw source field limit")
        return self


class SourceDisposition(EvidenceModel):
    code: str = Field(pattern=IDENTIFIER)
    location: SourceLocation
    raw_values: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def bounded(self) -> SourceDisposition:
        if any(len(value) > 4096 for value in self.raw_values):
            raise ValueError("raw source field limit")
        return self


class ComponentEvidence(EvidenceModel):
    role: Literal["principal", "interest", "fee"]
    amount: MoneyValue


class ObservationEvidence(EvidenceModel):
    row_id: str = Field(pattern=SHA256)
    occurrence: int = Field(ge=0, le=100_000)
    row_role: Literal["activity", "period_summary"]
    source_account: str = Field(min_length=1, max_length=4096)
    source_account_form: Literal["full", "last_four", "opaque"]
    date_role: Literal["posting_date", "activity_date", "statement_period_end"]
    date: DateValue
    transaction_date: DateValue | None = None
    description: TextValue
    amount: MoneyValue
    running_balance: MoneyValue | None = None
    components: tuple[ComponentEvidence, ...] = Field(max_length=3)
    fragments: tuple[SourceFragment, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def consistent(self) -> ObservationEvidence:
        if (self.row_role == "period_summary") != (self.date_role == "statement_period_end"):
            raise ValueError("summary row date role")
        if self.source_account_form == "last_four" and (
            len(self.source_account) != 4 or not self.source_account.isdigit()
        ):
            raise ValueError("invalid abbreviated account identifier")
        if self.amount.minor is None or self.date.iso is None:
            raise ValueError("observation needs a date and amount")
        roles = [item.role for item in self.components]
        if len(set(roles)) != len(roles):
            raise ValueError("duplicate component role")
        if self.components and any(item.amount.minor is None for item in self.components):
            raise ValueError("component amount unknown")
        if self.components and sum(item.amount.minor for item in self.components) != self.amount.minor:
            raise ValueError("component equation")
        return self


class StatementAccount(EvidenceModel):
    source_identity: str = Field(min_length=1, max_length=4096)
    source_identity_form: Literal["full", "last_four", "opaque"]
    balance_scope: Literal["account_total", "cash_component", "principal_component"]
    identity_locations: tuple[SourceLocation, ...] = Field(min_length=1, max_length=16)
    opening: MoneyValue | None
    closing: MoneyValue | None
    rows: tuple[ObservationEvidence, ...] = Field(max_length=100_000)

    @model_validator(mode="after")
    def rows_belong_to_account(self) -> StatementAccount:
        if any(
            row.source_account != self.source_identity
            or row.source_account_form != self.source_identity_form
            or row.date_role not in {"posting_date", "statement_period_end"}
            for row in self.rows
        ):
            raise ValueError("statement row account or date role")
        if self.source_identity_form == "last_four" and (
            len(self.source_identity) != 4 or not self.source_identity.isdigit()
        ):
            raise ValueError("invalid abbreviated account identifier")
        return self


class StatementPayload(EvidenceModel):
    kind: Literal["statement"]
    start: DateValue
    end: DateValue
    accounts: tuple[StatementAccount, ...] = Field(min_length=1, max_length=100)
    dispositions: tuple[SourceDisposition, ...] = Field(max_length=100_000)
    capture_verified: bool
    independent_balance_verified: bool

    @model_validator(mode="after")
    def consistent(self) -> StatementPayload:
        if self.start.iso is None or self.end.iso is None or self.start.iso >= self.end.iso:
            raise ValueError("statement period")
        if len({account.source_identity for account in self.accounts}) != len(self.accounts):
            raise ValueError("duplicate source account")
        if any(
            row.date.iso < self.start.iso or row.date.iso > self.end.iso
            for account in self.accounts
            for row in account.rows
        ):
            raise ValueError("posting date outside statement")
        if self.independent_balance_verified:
            for account in self.accounts:
                if (
                    account.opening is None
                    or account.closing is None
                    or account.opening.provenance != "observed"
                    or account.closing.provenance != "observed"
                    or any(row.amount.provenance != "observed" for row in account.rows)
                    or account.opening.minor + sum(row.amount.minor for row in account.rows) != account.closing.minor
                ):
                    raise ValueError("independent statement balance equation")
        return self


class ActivityExportPayload(EvidenceModel):
    kind: Literal["activity_export"]
    activity_start: DateValue
    activity_end: DateValue
    rows: tuple[ObservationEvidence, ...] = Field(max_length=100_000)
    dispositions: tuple[SourceDisposition, ...] = Field(max_length=100_000)
    coverage_verified: Literal[False] = False

    @model_validator(mode="after")
    def consistent(self) -> ActivityExportPayload:
        if (
            self.activity_start.iso is None
            or self.activity_end.iso is None
            or self.activity_start.iso > self.activity_end.iso
            or any(row.date.iso < self.activity_start.iso or row.date.iso > self.activity_end.iso for row in self.rows)
        ):
            raise ValueError("activity span")
        return self


SourcePayload = Annotated[StatementPayload | ActivityExportPayload, Field(discriminator="kind")]


class SourceEvidence(EvidenceModel):
    schema_version: Literal[2]
    source_sha256: str = Field(pattern=SHA256)
    definition_sha256: str = Field(pattern=SHA256)
    parser_id: str = Field(pattern=IDENTIFIER)
    definition_revision: str = Field(min_length=1, max_length=80)
    engine_version: str = Field(min_length=1, max_length=80)
    extractor_version: str = Field(min_length=1, max_length=80)
    payload: SourcePayload

    @model_validator(mode="after")
    def unique_rows(self) -> SourceEvidence:
        if isinstance(self.payload, StatementPayload):
            rows = (row for account in self.payload.accounts for row in account.rows)
        else:
            rows = iter(self.payload.rows)
        identifiers = [row.row_id for row in rows]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate source row identity")
        return self

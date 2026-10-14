"""Stable v1 snapshot schema for the disposable fresh-profile service slice."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
HASH = r"^[0-9a-f]{64}$"


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CellLocationV1(SnapshotModel):
    suffix: Literal[".csv"]
    row: int = Field(ge=1, le=100_000)
    column: int = Field(ge=1, le=64)
    sheet: None


class FieldEvidenceV1(SnapshotModel):
    raw: str = Field(max_length=4096)
    normalized: str | int | None
    provenance: Literal["observed", "unknown"]
    location: CellLocationV1


class ActivityRowV1(SnapshotModel):
    row_id: str = Field(pattern=HASH)
    occurrence: int = Field(ge=0, le=100_000)
    account: FieldEvidenceV1
    date: FieldEvidenceV1
    description: FieldEvidenceV1
    total: FieldEvidenceV1
    components: tuple[tuple[str, FieldEvidenceV1], ...] = Field(max_length=3)
    balance: FieldEvidenceV1 | None


class IgnoredRowV1(SnapshotModel):
    row: int = Field(ge=1, le=100_000)
    reason: Literal["blank_row"]


class StoredEvidenceV1(SnapshotModel):
    output_schema_version: Literal[1]
    source_sha256: str = Field(pattern=HASH)
    definition_sha256: str = Field(pattern=HASH)
    engine_version: str = Field(min_length=1, max_length=80)
    extraction_adapter: str = Field(min_length=1, max_length=80)
    parser_id: str = Field(min_length=1, max_length=80)
    definition_revision: str = Field(min_length=1, max_length=80)
    account_key: str = Field(min_length=1, max_length=4096)
    date_format: Literal["MM/DD/YYYY", "YYYY-MM-DD"]
    date_role: Literal["posting_date"]
    money_format: Literal["usd_symbol_2dp"]
    kind: Literal["activity_export"]
    rows: tuple[ActivityRowV1, ...] = Field(max_length=100_000)
    ignored_rows: tuple[IgnoredRowV1, ...] = Field(max_length=100_000)
    account_identities: tuple[str, ...] = Field(min_length=1, max_length=1)
    activity_start: str | None
    activity_end: str | None
    statement_opening_minor: None
    statement_closing_minor: None
    coverage_verified: Literal[False]
    balance_reconciled: Literal[False]

    @model_validator(mode="after")
    def consistent_rows(self) -> StoredEvidenceV1:
        identity = self.account_identities[0]
        if not identity or len(identity) > 4096 or self.account_key != "observed":
            raise ValueError("invalid account identity")
        if len({row.row_id for row in self.rows}) != len(self.rows):
            raise ValueError("duplicate row id")
        for row in self.rows:
            if (
                row.components
                or row.account.normalized != identity
                or not isinstance(row.date.normalized, str)
                or not isinstance(row.total.normalized, int)
                or not isinstance(row.description.normalized, str)
            ):
                raise ValueError("unsupported saved row")
            try:
                parsed = date.fromisoformat(row.date.normalized)
            except ValueError:
                raise ValueError("invalid saved date") from None
            if parsed.isoformat() != row.date.normalized:
                raise ValueError("invalid saved date")
        return self

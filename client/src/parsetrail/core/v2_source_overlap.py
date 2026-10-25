"""Finite cross-source candidate descriptions; matching never decides identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OVERLAP_RULE = "v2-source-overlap-1"


@dataclass(frozen=True)
class SourceOverlapRow:
    row_id: str
    source_sha256: str
    account_id: str
    account_name: str
    source_date: str
    date_role: str
    date_provenance: str
    amount_minor: int
    description: str
    locations: tuple[str, ...]
    active_allocated_minor: int
    has_journal_history: bool


@dataclass(frozen=True)
class SourceOverlapCandidate:
    left: SourceOverlapRow
    right: SourceOverlapRow
    state: Literal["pending", "distinct", "repeat", "supporting", "stale", "posted_conflict"]
    retained_row_id: str | None
    revision_id: int | None
    basis_sha256: str


@dataclass(frozen=True)
class SourceOverlapInventory:
    candidates: tuple[SourceOverlapCandidate, ...]
    truncated: bool
    total_pairs: int
    rule: str = OVERLAP_RULE


def bucket_key(row: SourceOverlapRow) -> tuple[str, int, str, str]:
    return row.account_id, row.amount_minor, row.source_date, row.date_role

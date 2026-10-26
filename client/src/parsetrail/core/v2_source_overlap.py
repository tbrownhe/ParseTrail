"""Finite cross-source candidate descriptions; matching never decides identity."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Literal

OVERLAP_RULE = "v2-source-overlap-1"
SOURCE_DATE_WINDOW_DAYS = 3


@dataclass(frozen=True)
class SourceOverlapRow:
    row_id: str
    source_sha256: str
    account_id: str
    account_name: str
    source_date: str | None
    date_role: str
    date_provenance: str
    amount_minor: int
    description: str
    locations: tuple[str, ...]
    active_allocated_minor: int
    has_journal_history: bool
    repeat_support_history_validated: bool = False


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


def _source_day(row: SourceOverlapRow) -> int:
    if row.source_date is None:
        raise ValueError("source_overlap_date_unknown")
    day = date.fromisoformat(row.source_date)
    if day.isoformat() != row.source_date:
        raise ValueError("source_overlap_date_invalid")
    return day.toordinal()


def _candidate_row(row: SourceOverlapRow) -> bool:
    return (
        row.source_date is not None
        and row.date_provenance != "unknown"
        and row.date_role in {"posting_date", "activity_date"}
        and type(row.amount_minor) is int
        and row.amount_minor != 0
    )


def nearby_source_pair(left: SourceOverlapRow, right: SourceOverlapRow) -> bool:
    """Candidate eligibility only; no identity, group or posting decision."""
    if (
        left.row_id == right.row_id
        or left.source_sha256 == right.source_sha256
        or left.account_id != right.account_id
        or not _candidate_row(left)
        or not _candidate_row(right)
        or left.amount_minor != right.amount_minor
    ):
        return False
    return abs(_source_day(left) - _source_day(right)) <= SOURCE_DATE_WINDOW_DAYS


def nearby_source_reason(left: SourceOverlapRow, right: SourceOverlapRow) -> str | None:
    if not nearby_source_pair(left, right):
        return None
    days = abs(_source_day(left) - _source_day(right))
    role_note = "; source date roles differ" if left.date_role != right.date_role else ""
    return ("Same source date" if days == 0 else f"Source dates {days} day(s) apart") + role_note


def pairwise_source_group(rows: Iterable[SourceOverlapRow]) -> bool:
    """A repeat group cannot extend a date window through a chain."""
    members = tuple(rows)
    return all(nearby_source_pair(left, right) for index, left in enumerate(members) for right in members[index + 1 :])


class NearbySourceIndex:
    """Finite date-window index without a display cap or materialized pair list.

    Keep all rows, including supporting occurrences. A caller must review groups
    and decisions separately; dropping aliases here would hide outsider edges.
    Counting uses date searches and source multiplicities rather than visiting
    every pair, including when many sources share one date and amount.
    """

    def __init__(self, rows: Iterable[SourceOverlapRow]):
        self.rows: dict[str, SourceOverlapRow] = {}
        cohorts: dict[tuple[str, int], list[tuple[int, str]]] = {}
        by_source: dict[tuple[tuple[str, int], str], list[tuple[int, str]]] = {}
        for row in rows:
            if row.row_id in self.rows:
                raise ValueError("source_overlap_duplicate_row")
            self.rows[row.row_id] = row
            if not _candidate_row(row):
                continue
            day = _source_day(row)
            cohort = row.account_id, row.amount_minor
            cohorts.setdefault(cohort, []).append((day, row.row_id))
            by_source.setdefault((cohort, row.source_sha256), []).append((day, row.row_id))
        self._cohorts = {key: tuple(sorted(items)) for key, items in cohorts.items()}
        self._days = {key: tuple(day for day, _row_id in items) for key, items in self._cohorts.items()}
        self._source_items = {key: tuple(sorted(items)) for key, items in by_source.items()}
        self._source_days = {key: tuple(day for day, _row_id in items) for key, items in self._source_items.items()}

    def neighbors(self, row_id: str) -> tuple[str, ...]:
        row = self.rows[row_id]
        if not _candidate_row(row):
            return ()
        key, day = (row.account_id, row.amount_minor), _source_day(row)
        days = self._days[key]
        low = bisect_left(days, day - SOURCE_DATE_WINDOW_DAYS)
        high = bisect_right(days, day + SOURCE_DATE_WINDOW_DAYS)
        return tuple(
            other_id
            for _other_day, other_id in self._cohorts[key][low:high]
            if self.rows[other_id].source_sha256 != row.source_sha256
        )

    def count_pairs(self, *, source_sha256: str | None = None) -> int:
        total = 0
        for key, items in self._cohorts.items():
            days = self._days[key]
            for offset, (day, row_id) in enumerate(items):
                source = self.rows[row_id].source_sha256
                if source_sha256 is not None:
                    if source != source_sha256:
                        continue
                    low = bisect_left(days, day - SOURCE_DATE_WINDOW_DAYS)
                    high = bisect_right(days, day + SOURCE_DATE_WINDOW_DAYS)
                    same = self._source_days[key, source]
                    total += (
                        high
                        - low
                        - (
                            bisect_right(same, day + SOURCE_DATE_WINDOW_DAYS)
                            - bisect_left(same, day - SOURCE_DATE_WINDOW_DAYS)
                        )
                    )
                else:
                    high = bisect_right(days, day + SOURCE_DATE_WINDOW_DAYS)
                    same = self._source_days[key, source]
                    # Same-date ties are ordered by row id; subtract only the
                    # same-source rows on the forward side of this position.
                    same_forward = bisect_right(same, day + SOURCE_DATE_WINDOW_DAYS) - bisect_right(
                        self._source_items[key, source], (day, row_id)
                    )
                    total += high - offset - 1 - same_forward
        return total

    def pairs(self, *, source_sha256: str | None = None) -> Iterator[tuple[str, str]]:
        for key in sorted(self._cohorts):
            items, days = self._cohorts[key], self._days[key]
            for offset, (day, row_id) in enumerate(items):
                row = self.rows[row_id]
                high = bisect_right(days, day + SOURCE_DATE_WINDOW_DAYS)
                for _other_day, other_id in items[offset + 1 : high]:
                    other = self.rows[other_id]
                    if row.source_sha256 == other.source_sha256:
                        continue
                    if source_sha256 is None or source_sha256 in (row.source_sha256, other.source_sha256):
                        yield tuple(sorted((row_id, other_id)))

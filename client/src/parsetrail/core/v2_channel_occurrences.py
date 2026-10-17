"""Bounded, source-preserving occurrence matching over extracted channels.

This operation identifies copies and overlaps. It never admits a transaction.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

MAX_RULE_BYTES = 4096
MAX_CANDIDATES = 10_000
MAX_DESCRIPTION_CHARS = 512
MAX_PAGE = 100
MAX_POSITION = 20_000
MAX_MONEY_MINOR = 9_000_000_000_000_000


class OccurrenceError(ValueError):
    """Redacted refusal of malformed or ambiguous source evidence."""


class OccurrenceRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["channel_occurrences_v1"]
    primary_channel: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    secondary_channel: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    scope: Literal["same_page"]

    @model_validator(mode="after")
    def distinct_channels(self) -> OccurrenceRule:
        if self.primary_channel == self.secondary_channel:
            raise ValueError("channels must differ")
        return self


def load_occurrence_rule(data: bytes) -> OccurrenceRule:
    if not data or len(data) > MAX_RULE_BYTES:
        raise OccurrenceError("rule_size")
    try:
        return OccurrenceRule.model_validate_json(data)
    except ValidationError:
        raise OccurrenceError("invalid_rule") from None


@dataclass(frozen=True, slots=True)
class Candidate:
    transaction_date: date
    posting_date: date
    amount_minor: int
    description: str
    channel: str
    page: int | None = None
    line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True, slots=True)
class OccurrenceMatch:
    secondary: Candidate
    status: Literal["exact_copy", "additional_exact", "coarse_overlap", "secondary_only"]
    primary_index: int | None
    peer_indices: tuple[int, ...]


def validate_candidates(rows: list[Candidate], channel: str) -> None:
    if len(rows) > MAX_CANDIDATES:
        raise OccurrenceError("candidate_limit")
    locations = set()
    for row in rows:
        if (
            row.channel != channel
            or type(row.transaction_date) is not date
            or type(row.posting_date) is not date
            or type(row.amount_minor) is not int
            or type(row.page) is not int
            or row.page < 1
            or row.page > MAX_PAGE
            or type(row.line) is not int
            or row.line < 1
            or row.line > MAX_POSITION
            or (
                row.end_line is not None
                and (type(row.end_line) is not int or row.end_line < row.line or row.end_line > MAX_POSITION)
            )
            or not isinstance(row.description, str)
            or not row.description
            or len(row.description) > MAX_DESCRIPTION_CHARS
            or row.description != " ".join(row.description.split())
            or row.amount_minor == 0
            or abs(row.amount_minor) > MAX_MONEY_MINOR
        ):
            raise OccurrenceError("invalid_candidate")
        location = (row.page, row.line)
        if location in locations:
            raise OccurrenceError("duplicate_source_location")
        locations.add(location)


def _coarse_key(row: Candidate) -> tuple[int, date, date, int]:
    assert row.page is not None
    return (row.page, row.transaction_date, row.posting_date, row.amount_minor)


def match_occurrences(
    rule: OccurrenceRule, primary: list[Candidate], secondary: list[Candidate]
) -> tuple[OccurrenceMatch, ...]:
    """Pair exact copies one to one and label all other occurrences for review."""
    if len(primary) + len(secondary) > MAX_CANDIDATES:
        raise OccurrenceError("candidate_limit")
    validate_candidates(primary, rule.primary_channel)
    validate_candidates(secondary, rule.secondary_channel)
    coarse: dict[tuple[int, date, date, int], list[int]] = defaultdict(list)
    exact: dict[tuple[tuple[int, date, date, int], str], deque[int]] = defaultdict(deque)
    for index, row in enumerate(primary):
        key = _coarse_key(row)
        coarse[key].append(index)
        exact[(key, row.description)].append(index)

    matches = []
    for row in secondary:
        key = _coarse_key(row)
        available = exact[(key, row.description)]
        peers = tuple(coarse[key])
        if available:
            matches.append(OccurrenceMatch(row, "exact_copy", available.popleft(), peers))
        elif any(primary[index].description == row.description for index in peers):
            matches.append(OccurrenceMatch(row, "additional_exact", None, peers))
        elif peers:
            matches.append(OccurrenceMatch(row, "coarse_overlap", None, peers))
        else:
            matches.append(OccurrenceMatch(row, "secondary_only", None, ()))
    return tuple(matches)

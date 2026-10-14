"""Finite, read-only recent-Citi channel reconciliation over extracted candidates.

PDF decoding and channel extraction are separate pilot boundaries. No row is posted.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from typing import Literal

MAX_CANDIDATES = 10_000
MAX_DESCRIPTION_CHARS = 512
MAX_PAGE = 100
MAX_POSITION = 20_000
MAX_MONEY_MINOR = 9_000_000_000_000_000
DATE_ONLY = re.compile(r"\d{2}/\d{2}\Z")
Channel = Literal["table", "text", "fee"]


class CitiChannelError(ValueError):
    """Redacted refusal of ambiguous or inconsistent source evidence."""


@dataclass(frozen=True, slots=True)
class Candidate:
    transaction_date: date
    posting_date: date
    amount_minor: int
    description: str
    channel: Channel
    page: int | None = None
    line: int | None = None  # Text line or parsed table-row ordinal.
    end_line: int | None = None  # End of a multiline fee, when present.


@dataclass(frozen=True, slots=True)
class ResolvedRow:
    representative: Candidate
    sources: tuple[Candidate, ...]
    disposition: Literal["table", "text_only", "additional_text_occurrence", "fee"]


@dataclass(frozen=True, slots=True)
class CitiResolution:
    rows: tuple[ResolvedRow, ...]
    incomplete_text_copies: tuple[Candidate, ...]
    first_character_corrections: int
    balance_reconciled: bool


def _key(row: Candidate) -> tuple[int, date, date, int]:
    assert row.page is not None
    return (row.page, row.transaction_date, row.posting_date, row.amount_minor)


def _validate(rows: list[Candidate], channel: Channel) -> None:
    if len(rows) > MAX_CANDIDATES:
        raise CitiChannelError("candidate_limit")
    locations = set()
    for row in rows:
        if (
            row.channel != channel
            or row.page is None
            or row.page < 1
            or row.page > MAX_PAGE
            or row.line is None
            or row.line < 1
            or row.line > MAX_POSITION
            or (row.end_line is not None and (row.end_line < row.line or row.end_line > MAX_POSITION))
            or not row.description
            or len(row.description) > MAX_DESCRIPTION_CHARS
            or row.description != " ".join(row.description.split())
            or row.amount_minor == 0
            or abs(row.amount_minor) > MAX_MONEY_MINOR
        ):
            raise CitiChannelError("invalid_candidate")
        location = (row.page, row.line)
        if location in locations:
            raise CitiChannelError("duplicate_source_location")
        locations.add(location)


def resolve(
    table: list[Candidate],
    text: list[Candidate],
    fees: list[Candidate],
    *,
    opening_minor: int,
    closing_minor: int,
) -> CitiResolution:
    """Pair unique same-page evidence; retain artifacts; require printed balance."""
    for rows, channel in ((table, "table"), (text, "text"), (fees, "fee")):
        _validate(rows, channel)
    if sum(map(len, (table, text, fees))) > MAX_CANDIDATES:
        raise CitiChannelError("candidate_limit")

    coarse: dict[tuple[int, date, date, int], list[int]] = defaultdict(list)
    exact: dict[tuple[tuple[int, date, date, int], str], deque[int]] = defaultdict(deque)
    sources = [[row] for row in table]
    representatives = list(table)
    for index, row in enumerate(table):
        coarse[_key(row)].append(index)
        exact[(_key(row), row.description)].append(index)

    extras: list[ResolvedRow] = []
    incomplete: list[Candidate] = []
    corrected = 0
    for row in text:
        key = _key(row)
        available = exact[(key, row.description)]
        if available:
            index = available.popleft()
            sources[index].append(row)
            continue
        peers = coarse[key]
        if len(peers) == 1 and DATE_ONLY.fullmatch(row.description):
            incomplete.append(row)
            continue
        if len(peers) == 1:
            index = peers[0]
            table_description = table[index].description
            if row.description[1:] == table_description or table_description[1:] == row.description:
                sources[index].append(row)
                # Prefer the fuller observed description, retaining both raw channels.
                if len(row.description) > len(table_description):
                    representatives[index] = row
                corrected += 1
                continue
        if any(table[index].description == row.description for index in peers):
            extras.append(ResolvedRow(row, (row,), "additional_text_occurrence"))
            continue
        if not peers and DATE_ONLY.fullmatch(row.description) is None:
            extras.append(ResolvedRow(row, (row,), "text_only"))
            continue
        raise CitiChannelError("unresolved_text_overlap")

    rows = [
        ResolvedRow(representative, tuple(evidence), "table")
        for representative, evidence in zip(representatives, sources, strict=True)
    ]
    rows.extend(extras)
    for fee in fees:
        # A fee with the same date and amount as another row needs source review.
        if any(
            existing.representative.page == fee.page
            and existing.representative.posting_date == fee.posting_date
            and existing.representative.amount_minor == fee.amount_minor
            for existing in rows
        ):
            raise CitiChannelError("fee_overlap")
        rows.append(ResolvedRow(fee, (fee,), "fee"))
    if opening_minor + sum(row.representative.amount_minor for row in rows) != closing_minor:
        raise CitiChannelError("balance_mismatch")
    return CitiResolution(tuple(rows), tuple(incomplete), corrected, True)

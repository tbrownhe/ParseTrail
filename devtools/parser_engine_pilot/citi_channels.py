"""Read-only Citi policy over shared channel occurrence matching.

PDF decoding and extraction remain separate pilot boundaries; no row is posted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from devtools.parser_engine_pilot.channel_occurrences import (
    MAX_CANDIDATES,
    Candidate,
    OccurrenceError,
    load_occurrence_rule,
    match_occurrences,
    validate_candidates,
)

DATE_ONLY = re.compile(r"\d{2}/\d{2}\Z")
CITI_OCCURRENCE_RULE = load_occurrence_rule(
    b'{"operation":"channel_occurrences_v1","primary_channel":"table","secondary_channel":"text","scope":"same_page"}'
)


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


def resolve(
    table: list[Candidate],
    text: list[Candidate],
    fees: list[Candidate],
    *,
    opening_minor: int,
    closing_minor: int,
) -> CitiResolution:
    """Apply Citi artifact rules and a printed balance check to matched evidence."""
    if sum(map(len, (table, text, fees))) > MAX_CANDIDATES:
        raise OccurrenceError("candidate_limit")
    matches = match_occurrences(CITI_OCCURRENCE_RULE, table, text)
    validate_candidates(fees, "fee")
    sources = [[row] for row in table]
    representatives = list(table)

    extras: list[ResolvedRow] = []
    incomplete: list[Candidate] = []
    corrected = 0
    for match in matches:
        row = match.secondary
        if match.status == "exact_copy":
            assert match.primary_index is not None
            if len(sources[match.primary_index]) != 1:
                raise OccurrenceError("unresolved_text_overlap")
            sources[match.primary_index].append(row)
            continue
        if match.status == "coarse_overlap" and len(match.peer_indices) == 1 and DATE_ONLY.fullmatch(row.description):
            incomplete.append(row)
            continue
        if match.status == "coarse_overlap" and len(match.peer_indices) == 1:
            index = match.peer_indices[0]
            table_description = table[index].description
            if len(sources[index]) == 1 and (
                row.description[1:] == table_description or table_description[1:] == row.description
            ):
                sources[index].append(row)
                if len(row.description) > len(table_description):
                    representatives[index] = row
                corrected += 1
                continue
        if match.status == "additional_exact":
            extras.append(ResolvedRow(row, (row,), "additional_text_occurrence"))
            continue
        if match.status == "secondary_only" and DATE_ONLY.fullmatch(row.description) is None:
            extras.append(ResolvedRow(row, (row,), "text_only"))
            continue
        raise OccurrenceError("unresolved_text_overlap")

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
            raise OccurrenceError("fee_overlap")
        rows.append(ResolvedRow(fee, (fee,), "fee"))
    if opening_minor + sum(row.representative.amount_minor for row in rows) != closing_minor:
        raise OccurrenceError("balance_mismatch")
    return CitiResolution(tuple(rows), tuple(incomplete), corrected, True)

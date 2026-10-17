"""Recent Citi date/money adapter over the shared table continuation operation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from parsetrail.core.v2_table_continuations import (
    ContinuationRule,
    JoinedTableRow,
    RawTableRow,
    assemble,
)

from devtools.parser_engine_pilot.channel_occurrences import Candidate, validate_candidates
from devtools.parser_engine_pilot.citi_layout import AMOUNT, TRANSACTION_DATE
from devtools.parser_engine_pilot.citi_table import CitiTableEvidence
from devtools.parser_engine_pilot.money_operations import usd_symbol_minor_v1
from devtools.parser_engine_pilot.partial_dates import resolve_month_day


@dataclass(frozen=True, slots=True)
class CitiTableCandidates:
    rows: tuple[Candidate, ...]
    groups: tuple[JoinedTableRow, ...]


def candidates_from_table(
    evidence: CitiTableEvidence,
    start_date: datetime,
    end_date: datetime,
    *,
    continuation: ContinuationRule,
) -> CitiTableCandidates:
    """Convert printed table groups; keep supplemental text as source evidence."""
    groups = assemble(
        continuation,
        tuple(RawTableRow(row.page, row.table_row, row.raw_cells) for row in evidence.rows),
    )
    candidates = []
    for group in groups:
        first = group.sources[0]
        transaction_match = TRANSACTION_DATE.search(first.cells[0])
        posting_match = TRANSACTION_DATE.search(first.cells[1])
        if transaction_match is None and posting_match is None:
            raise ValueError("missing_citi_table_date")
        if group.amount_raw is None or AMOUNT.fullmatch(group.amount_raw) is None:
            raise ValueError("invalid_citi_table_amount")
        transaction_raw = (transaction_match or posting_match).group()
        posting_raw = (posting_match or transaction_match).group()
        candidates.append(
            Candidate(
                resolve_month_day(transaction_raw, start_date, end_date),
                resolve_month_day(posting_raw, start_date, end_date),
                -usd_symbol_minor_v1(group.amount_raw),
                " ".join(group.description.split()),
                "table",
                first.page,
                first.ordinal,
            )
        )
    validate_candidates(candidates, "table")
    return CitiTableCandidates(tuple(candidates), groups)

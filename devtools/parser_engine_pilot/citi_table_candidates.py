"""Recent Citi date/money adapter over the shared table continuation operation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from parsetrail.core.money import parse_money, to_minor_units
from parsetrail.core.utils import get_absolute_date
from parsetrail.plugins.pdf_citicc_202511 import Parser as RecentCiti

from devtools.parser_engine_pilot.channel_occurrences import Candidate, validate_candidates
from devtools.parser_engine_pilot.citi_table import CitiTableEvidence
from devtools.parser_engine_pilot.table_continuations import (
    ContinuationRule,
    JoinedTableRow,
    RawTableRow,
    assemble,
)

CITI_TABLE_RULE = ContinuationRule.model_validate(
    {
        "operation": "table_continuation_v1",
        "mode": "amount_with_details",
        "start_columns": [0, 1],
        "break_columns": [0, 1],
        "description_column": 2,
        "amount_column": 3,
        "max_group_rows": 8,
        "allow_cross_page": False,
    }
)


@dataclass(frozen=True, slots=True)
class CitiTableCandidates:
    rows: tuple[Candidate, ...]
    groups: tuple[JoinedTableRow, ...]


def candidates_from_table(evidence: CitiTableEvidence, start_date: datetime, end_date: datetime) -> CitiTableCandidates:
    """Convert printed table groups; keep supplemental text as source evidence."""
    groups = assemble(
        CITI_TABLE_RULE,
        tuple(RawTableRow(row.page, row.table_row, row.raw_cells) for row in evidence.rows),
    )
    candidates = []
    for group in groups:
        first = group.sources[0]
        transaction_match = RecentCiti.TRANSACTION_DATE.search(first.cells[0])
        posting_match = RecentCiti.TRANSACTION_DATE.search(first.cells[1])
        if transaction_match is None and posting_match is None:
            raise ValueError("missing_citi_table_date")
        if group.amount_raw is None or RecentCiti.AMOUNT.fullmatch(group.amount_raw) is None:
            raise ValueError("invalid_citi_table_amount")
        transaction_raw = (transaction_match or posting_match).group()
        posting_raw = (posting_match or transaction_match).group()
        candidates.append(
            Candidate(
                get_absolute_date(transaction_raw, start_date, end_date).date(),
                get_absolute_date(posting_raw, start_date, end_date).date(),
                -to_minor_units(parse_money(group.amount_raw)),
                " ".join(group.description.split()),
                "table",
                first.page,
                first.ordinal,
            )
        )
    validate_candidates(candidates, "table")
    return CitiTableCandidates(tuple(candidates), groups)

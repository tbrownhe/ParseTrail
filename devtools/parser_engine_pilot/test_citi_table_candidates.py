"""Citi date/money conversion over shared bounded table grouping."""

from datetime import datetime
from functools import partial

import pytest
from parsetrail.core.v2_citi_table import CitiTableEvidence, CitiTablePage, CitiTableRow
from parsetrail.core.v2_table_continuations import ContinuationError

from devtools.parser_engine_pilot.citi_authoring import DEFINITION
from devtools.parser_engine_pilot.citi_table_candidates import candidates_from_table as candidates_from_table_with_rule

candidates_from_table = partial(candidates_from_table_with_rule, continuation=DEFINITION.table_continuation)


def evidence(*cells: tuple[str, str, str, str]) -> CitiTableEvidence:
    rows = tuple(CitiTableRow(1, index, (0, 0, 1, 1), None, raw, "table") for index, raw in enumerate(cells, 1))
    return CitiTableEvidence(
        1,
        "0" * 64,
        "test",
        "test",
        "unused",
        (CitiTablePage(1, "table", (0, 0, 1, 1), (0, 1), False),),
        rows,
        False,
        False,
    )


def test_foreign_amount_and_post_amount_details_keep_source_rows() -> None:
    result = candidates_from_table(
        evidence(
            ("12/31", "01/02", "FOREIGN CAFE", ""),
            ("", "", "100.00 PESO", "$5.00"),
            ("01/03", "01/03", "AIRLINE", "$20.00"),
            ("", "", "DEPART: 01/10", ""),
        ),
        datetime(2025, 12, 1),
        datetime(2026, 1, 5),
    )
    assert [
        (row.transaction_date.isoformat(), row.posting_date.isoformat(), row.amount_minor, row.description)
        for row in result.rows
    ] == [
        ("2025-12-31", "2026-01-02", -500, "FOREIGN CAFE 100.00 PESO"),
        ("2026-01-03", "2026-01-03", -2000, "AIRLINE"),
    ]
    assert [row.line for row in result.rows] == [1, 3]
    assert [row.ordinal for row in result.groups[1].detail_rows] == [4]


def test_incomplete_foreign_row_refuses_candidate() -> None:
    with pytest.raises(ContinuationError, match="missing_or_multiple_amounts"):
        candidates_from_table(
            evidence(("01/02", "01/03", "INCOMPLETE", "")),
            datetime(2026, 1, 1),
            datetime(2026, 1, 31),
        )

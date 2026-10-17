"""Shared continuation shapes used by several existing PDF table parsers."""

from __future__ import annotations

import pytest
from parsetrail.core.v2_table_continuations import (
    ContinuationError,
    ContinuationRule,
    RawTableRow,
    assemble,
)
from pydantic import ValidationError


def test_citi_and_synchrony_amount_on_last_row_shape() -> None:
    rule = ContinuationRule.model_validate_json(
        b'{"operation":"table_continuation_v1","mode":"amount_on_last_row",'
        b'"start_columns":[0,1],"break_columns":[1],"description_column":2,'
        b'"amount_column":3,"max_group_rows":4,"allow_cross_page":true}'
    )
    rows = (
        RawTableRow(1, 1, ("07/29", "07/30", "FOREIGN MERCHANT", "")),
        RawTableRow(2, 1, ("", "", "CURRENCY DETAIL", "$12.34")),
        RawTableRow(2, 2, ("07/31", "08/01", "NEXT PURCHASE", "$2.00")),
    )
    joined = assemble(rule, rows)
    assert [(item.description, item.amount_raw) for item in joined] == [
        ("FOREIGN MERCHANT CURRENCY DETAIL", "$12.34"),
        ("NEXT PURCHASE", "$2.00"),
    ]
    assert [(item.page, item.ordinal) for item in joined[0].sources] == [(1, 1), (2, 1)]


def test_wells_and_lendingclub_description_after_start_shape() -> None:
    rule = ContinuationRule.model_validate(
        {
            "operation": "table_continuation_v1",
            "mode": "description_after_start",
            "start_columns": [0],
            "break_columns": [0],
            "description_column": 1,
            "amount_column": 2,
            "max_group_rows": 3,
        }
    )
    rows = (
        RawTableRow(1, 1, ("08/01", "TRANSFER FROM", "$30.00")),
        RawTableRow(1, 2, ("", "SAVINGS", "")),
        RawTableRow(1, 3, ("08/02", "PURCHASE", "-$5.00")),
    )
    joined = assemble(rule, rows)
    assert [(item.description, item.amount_raw) for item in joined] == [
        ("TRANSFER FROM SAVINGS", "$30.00"),
        ("PURCHASE", "-$5.00"),
    ]
    assert len(joined[0].sources) == 2


def test_amount_with_details_keeps_posted_description_separate_from_supplemental_lines() -> None:
    rule = ContinuationRule.model_validate(
        {
            "operation": "table_continuation_v1",
            "mode": "amount_with_details",
            "start_columns": [0, 1],
            "break_columns": [0, 1],
            "description_column": 2,
            "amount_column": 3,
            "max_group_rows": 5,
        }
    )
    rows = (
        RawTableRow(1, 1, ("08/01", "08/01", "AIRLINE", "$50.00")),
        RawTableRow(1, 2, ("", "", "DEPART: 08/10", "")),
        RawTableRow(1, 3, ("08/02", "08/02", "FOREIGN MERCHANT", "")),
        RawTableRow(1, 4, ("", "", "CURRENCY DETAIL", "$12.34")),
    )
    joined = assemble(rule, rows)
    assert [(row.description, row.amount_raw) for row in joined] == [
        ("AIRLINE", "$50.00"),
        ("FOREIGN MERCHANT CURRENCY DETAIL", "$12.34"),
    ]
    assert [row.cells[2] for row in joined[0].detail_rows] == ["DEPART: 08/10"]
    assert joined[1].detail_rows == ()
    with pytest.raises(ContinuationError, match="missing_or_multiple_amounts"):
        assemble(rule, (RawTableRow(1, 1, ("08/01", "08/01", "INCOMPLETE", "")),))


def test_refuses_incomplete_or_undeclared_continuations() -> None:
    rule = ContinuationRule.model_validate(
        {
            "operation": "table_continuation_v1",
            "mode": "amount_on_last_row",
            "start_columns": [0],
            "break_columns": [0],
            "description_column": 1,
            "amount_column": 2,
            "max_group_rows": 2,
        }
    )
    with pytest.raises(ContinuationError, match="missing_terminal_amount"):
        assemble(rule, (RawTableRow(1, 1, ("08/01", "INCOMPLETE", "")),))
    with pytest.raises(ContinuationError, match="orphan_continuation"):
        assemble(rule, (RawTableRow(1, 1, ("", "ORPHAN", "$1.00")),))
    with pytest.raises(ContinuationError, match="unexpected_page_break"):
        assemble(
            rule,
            (
                RawTableRow(1, 1, ("08/01", "FOREIGN", "")),
                RawTableRow(2, 1, ("", "CONTINUATION", "$1.00")),
            ),
        )
    with pytest.raises(ValidationError):
        ContinuationRule.model_validate({**rule.model_dump(), "python_hook": "run_me"})

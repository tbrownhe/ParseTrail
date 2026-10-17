"""Synthetic workbook parity and refusal through the native worker boundary."""

from __future__ import annotations

from dataclasses import asdict

import pytest
from parsetrail.core.v2_worker_limits import WorkerError, WorkerLimits
from parsetrail.core.v2_xlsx_adapter import parse_xlsx

from devtools.parser_engine_pilot.bounded_xlsx import parse_bounded_xlsx
from devtools.parser_engine_pilot.test_xlsx_adapter import definition, workbook


def test_bounded_workbook_evidence_matches_in_process_pilot() -> None:
    source = workbook()
    declared = definition()
    expected = parse_xlsx(declared, source, sheet="Activity")
    actual = parse_bounded_xlsx(declared, source, sheet="Activity")
    assert asdict(actual) == asdict(expected)


def test_invalid_workbook_and_deadline_fail_without_cell_contents() -> None:
    with pytest.raises(WorkerError, match="worker_failed") as error:
        parse_bounded_xlsx(definition(), workbook(formula=True), sheet="Activity")
    assert "Account A" not in str(error.value)
    with pytest.raises(WorkerError, match="timeout"):
        parse_bounded_xlsx(definition(), workbook(), sheet="Activity", limits=WorkerLimits(wall_seconds=0.01))

"""Shared occurrence matching leaves financial disposition to the caller."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from devtools.parser_engine_pilot.channel_occurrences import (
    Candidate,
    OccurrenceError,
    OccurrenceRule,
    load_occurrence_rule,
    match_occurrences,
)

DAY = date(2026, 8, 2)
RULE = load_occurrence_rule(
    b'{"operation":"channel_occurrences_v1","primary_channel":"table","secondary_channel":"text","scope":"same_page"}'
)


def row(description: str, channel: str, line: int, *, page: int = 1, amount: int = -100) -> Candidate:
    return Candidate(DAY, DAY, amount, description, channel, page, line)


def test_exact_occurrences_are_paired_once_and_others_remain_candidates() -> None:
    primary = [row("SAME", "table", 1), row("SAME", "table", 2), row("OTHER", "table", 3)]
    secondary = [
        row("SAME", "text", 10),
        row("SAME", "text", 11),
        row("SAME", "text", 12),
        row("DIFFERENT", "text", 13),
        row("SAME", "text", 14, page=2),
    ]
    matches = match_occurrences(RULE, primary, secondary)
    assert [(item.status, item.primary_index) for item in matches] == [
        ("exact_copy", 0),
        ("exact_copy", 1),
        ("additional_exact", None),
        ("coarse_overlap", None),
        ("secondary_only", None),
    ]
    assert matches[3].peer_indices == (0, 1, 2)
    assert matches[4].secondary is secondary[4]


def test_strict_rule_and_source_locations_refuse_ambiguous_input() -> None:
    with pytest.raises(OccurrenceError, match="rule_size"):
        load_occurrence_rule(b" " * 4097)
    with pytest.raises(OccurrenceError, match="invalid_rule"):
        load_occurrence_rule(b'{"operation":"channel_occurrences_v1","python_hook":"run_me"}')
    with pytest.raises(ValidationError):
        OccurrenceRule.model_validate({**RULE.model_dump(), "python_hook": "run_me"})
    with pytest.raises(ValidationError):
        OccurrenceRule.model_validate({**RULE.model_dump(), "secondary_channel": "table"})
    with pytest.raises(OccurrenceError, match="duplicate_source_location"):
        match_occurrences(RULE, [row("A", "table", 1), row("B", "table", 1)], [])
    with pytest.raises(OccurrenceError, match="invalid_candidate"):
        match_occurrences(RULE, [], [row(" A", "text", 1)])

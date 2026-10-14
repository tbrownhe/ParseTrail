"""Occurrence and conflicting-channel rules for the recent-Citi audit."""

from __future__ import annotations

from datetime import date

from devtools.parser_engine_pilot.audit_citi_channels import Candidate, dispositions


def candidate(description: str, channel: str, amount: int = -100) -> Candidate:
    return Candidate(date(2026, 8, 1), date(2026, 8, 2), amount, description, channel)


def test_exact_occurrences_match_but_conflicts_remain_unresolved() -> None:
    table = [candidate("Same", "table"), candidate("Same", "table"), candidate("Other", "table")]
    text = [
        candidate("Same", "text"),
        candidate("Same", "text"),
        candidate("Same", "text"),
        candidate("Different", "text"),
        candidate("Only in text", "text", -200),
    ]
    assert [item.status for item in dispositions(table, text)] == [
        "exact_table_occurrence",
        "exact_table_occurrence",
        "unresolved_overlap",
        "unresolved_overlap",
        "text_only_candidate",
    ]
    assert dispositions(table, text)[3].candidate.description == "Different"

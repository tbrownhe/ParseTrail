"""Occurrence and conflicting-channel rules for the recent-Citi audit."""

from __future__ import annotations

from datetime import date

from devtools.parser_engine_pilot.audit_citi_channels import Candidate, dispositions, overlap_shape


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


def test_overlap_shapes_only_describe_same_page_candidates() -> None:
    table = [Candidate(date(2026, 8, 1), date(2026, 8, 2), -100, "MERCHANT", "table", 3)]

    def text(description: str, page: int = 3) -> Candidate:
        return Candidate(date(2026, 8, 1), date(2026, 8, 2), -100, description, "text", page)

    assert overlap_shape(text("08/01"), table) == "date_only_text_copy"
    assert overlap_shape(text("XMERCHANT"), table) == "one_character_description_difference"
    assert overlap_shape(text("MERCHANT"), table) == "additional_exact_occurrence"
    assert overlap_shape(text("UNRELATED"), table) == "unclassified_overlap"
    assert overlap_shape(text("MERCHANT", 4), table) == "unclassified_overlap"

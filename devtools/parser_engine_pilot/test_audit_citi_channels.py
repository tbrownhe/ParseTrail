"""Occurrence and conflicting-channel rules for the recent-Citi audit."""

from __future__ import annotations

from datetime import date, datetime

from parsetrail.plugins.pdf_citicc_202511 import Parser

from devtools.parser_engine_pilot.audit_citi_channels import (
    Candidate,
    dispositions,
    fee_candidates,
    overlap_shape,
    unmatched_dated_line_counts,
)


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


def test_fee_and_unmatched_dated_lines_keep_distinct_source_locations() -> None:
    parser = Parser()
    parser.start_date = datetime(2026, 7, 4)
    parser.end_date = datetime(2026, 8, 5)
    pages = [
        "\n".join(
            (
                "07/20 07/21 MERCHANT $10.00",
                "07/22 FOREIGN MERCHANT",
                "CURRENCY DETAIL $20.00",
                "07/23 07/24 MERCHANT $30.00 legal notice",
                "Fees Charged",
                "08/05 MEMBERSHIP FEE",
                "SEE REVERSE $40.00",
                "TOTAL FEES FOR THIS PERIOD $40.00",
            )
        )
    ]
    fees = fee_candidates(parser, pages)
    assert [(fee.page, fee.line, fee.end_line, fee.description, fee.amount_minor) for fee in fees] == [
        (1, 6, 7, "MEMBERSHIP FEE SEE REVERSE", -4000)
    ]
    assert unmatched_dated_line_counts(parser, pages) == {"without_money": 2, "with_money": 1}

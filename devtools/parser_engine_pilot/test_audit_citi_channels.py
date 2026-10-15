"""Occurrence and conflicting-channel rules for the recent-Citi audit."""

from __future__ import annotations

from datetime import date, datetime

from parsetrail.plugins.pdf_citicc_202511 import Parser

from devtools.parser_engine_pilot.audit_citi_channels import (
    Candidate,
    dispositions,
    fee_candidates,
    overlap_shape,
)
from devtools.parser_engine_pilot.citi_source_dispositions import dispose_dated_lines


def candidate(description: str, channel: str, line: int, amount: int = -100) -> Candidate:
    return Candidate(date(2026, 8, 1), date(2026, 8, 2), amount, description, channel, 3, line)


def test_exact_occurrences_match_but_conflicts_remain_unresolved() -> None:
    table = [candidate("Same", "table", 1), candidate("Same", "table", 2), candidate("Other", "table", 3)]
    text = [
        candidate("Same", "text", 10),
        candidate("Same", "text", 11),
        candidate("Same", "text", 12),
        candidate("Different", "text", 13),
        candidate("Only in text", "text", 14, -200),
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


def test_fee_and_extra_dated_lines_keep_distinct_source_locations() -> None:
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
    table = [
        Candidate(date(2026, 7, 22), date(2026, 7, 22), -2000, "FOREIGN MERCHANT CURRENCY DETAIL", "table", 1, 1),
        Candidate(date(2026, 7, 23), date(2026, 7, 24), -3000, "MERCHANT", "table", 1, 2),
    ]
    ledger = dispose_dated_lines(parser, pages, table, fees)
    assert [(row.line, row.status, row.table_row) for row in ledger] == [
        (1, "simple_text", None),
        (2, "table_copy", 1),
        (4, "table_copy", 2),
        (6, "fee", None),
    ]

"""Source capture checks for difficult recent Citi text/table copies."""

from datetime import date

from parsetrail.plugins.pdf_citicc_202511 import Parser

from devtools.parser_engine_pilot.channel_occurrences import Candidate
from devtools.parser_engine_pilot.citi_source_dispositions import dispose_dated_lines


def table(description: str, amount: int, row: int, *, day: int = 2) -> Candidate:
    return Candidate(date(2026, 1, day), date(2026, 1, day), amount, description, "table", 1, row)


def test_pairs_duplicate_source_occurrences_and_keeps_their_order() -> None:
    page = "\n".join(
        (
            "01/02 SHOP A $10.00 legal copy",
            "01/02 SHOP A $10.00 more legal copy",
            "01/03 IZAKAYA $20.00 legal copy",
        )
    )
    result = dispose_dated_lines(
        Parser(),
        [page],
        [table("SHOP A", -1000, 1), table("SHOP A", -1000, 2), table("ZAKAYA", -2000, 3, day=3)],
        [],
    )
    assert [(row.status, row.table_row, row.description_evidence) for row in result] == [
        ("table_copy", 1, "ordered_words"),
        ("table_copy", 2, "ordered_words"),
        ("table_copy", 3, "first_character_loss"),
    ]


def test_links_foreign_continuation_and_date_only_line_with_prior_description() -> None:
    page = "\n".join(
        (
            "01/02 CAFE A MEX",
            "1,000.00 MEXICAN PESO $50.00",
            "CAFE B MEX",
            "01/03",
            "200.00 MEXICAN PESO $10.00",
        )
    )
    result = dispose_dated_lines(
        Parser(),
        [page],
        [
            table("CAFE A MEX 1,000.00 MEXICAN PESO", -5000, 1),
            table("CAFE B MEX 200.00 MEXICAN PESO", -1000, 2, day=3),
        ],
        [],
    )
    assert [(row.status, row.table_row) for row in result] == [("table_copy", 1), ("table_copy", 2)]


def test_fee_uses_printed_section_span_and_mismatch_stays_unresolved() -> None:
    pages = [
        "01/02 STORE A $10.00 legal copy",
        "\n".join(
            (
                "Fees Charged",
                "01/03 MEMBERSHIP FEE",
                "SEE REVERSE $99.00",
                "$99.00",
                "TOTAL FEES FOR THIS PERIOD",
            )
        ),
    ]
    fee = Candidate(date(2026, 1, 3), date(2026, 1, 3), -9900, "MEMBERSHIP FEE", "fee", 2, 2, 3)
    result = dispose_dated_lines(Parser(), pages, [table("STORE B", -1000, 1)], [fee])
    assert [(row.status, row.end_line) for row in result] == [("unresolved", 1), ("fee", 3)]


def test_refuses_missing_duplicate_table_occurrence() -> None:
    page = "01/02 SHOP A $10.00 legal copy\n01/02 SHOP A $10.00 another copy"
    result = dispose_dated_lines(Parser(), [page], [table("SHOP A", -1000, 1)], [])
    assert [row.status for row in result] == ["unresolved", "unresolved"]

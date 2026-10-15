"""Dollar lines outside Citi transaction spans need explicit dispositions."""

from devtools.parser_engine_pilot.citi_money_lines import dispose_unlinked_money_lines
from devtools.parser_engine_pilot.citi_source_dispositions import DatedLineDisposition


def test_labels_known_summary_lines_without_reinterpreting_a_transaction() -> None:
    pages = (
        "New balance $100.00",
        "\n".join(
            (
                "01/02 SHOP $10.00",
                "Fees Charged",
                "$0.00",
                "TOTAL FEES FOR THIS PERIOD",
                "TOTAL INTEREST FOR THIS PERIOD $1.00",
                "New Charges $10.00",
                "Standard Purch 26.49% (V) $10.00 (D) $1.00",
                "MYSTERY $3.00",
            )
        ),
    )
    dated = (DatedLineDisposition(2, 1, 1, "simple_text"),)
    result = dispose_unlinked_money_lines(pages, dated)
    assert [(row.line, row.status) for row in result] == [
        (3, "fee_period_total"),
        (5, "interest_period_total"),
        (6, "cardholder_subtotal"),
        (7, "apr_information"),
        (8, "unresolved"),
    ]

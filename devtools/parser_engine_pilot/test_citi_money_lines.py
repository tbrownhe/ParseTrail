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
        (1, "account_summary"),
        (3, "fee_period_total"),
        (5, "interest_period_total"),
        (6, "cardholder_subtotal"),
        (7, "apr_information"),
        (8, "unresolved"),
    ]


def test_first_page_money_requires_explicit_disposition() -> None:
    pages = (
        "\n".join(
            (
                "New balance as of 08/05/26: $100.00",
                "Previous balance $90.00",
                "Purchases +$10.00",
                "Credit Limit $5,000.00",
                "Minimum payment due New balance Payment due date",
                "$25.00 $100.00 09/01/26",
                "Amount enclosed: $",
                "Unknown charge $5.00",
                "Unknown marker $",
            )
        ),
    )
    assert [(item.line, item.status) for item in dispose_unlinked_money_lines(pages, ())] == [
        (1, "payment_information"),
        (2, "account_summary"),
        (3, "account_summary"),
        (4, "credit_terms"),
        (6, "payment_information"),
        (7, "payment_information"),
        (8, "unresolved"),
        (9, "unresolved"),
    ]


def test_retains_unreadable_subtotal_as_artifact() -> None:
    pages = ("", "New Charges Card ending i $n 04.00306")
    assert [(item.page, item.status) for item in dispose_unlinked_money_lines(pages, ())] == [
        (2, "cardholder_subtotal_extraction_artifact")
    ]

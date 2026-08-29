from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from parsetrail.core.validation import Transaction
from parsetrail.plugins.pdf_citicc_202511 import Parser


def configured_parser(*pages: str) -> Parser:
    parser = Parser()
    parser.start_date = datetime(2026, 7, 4)
    parser.end_date = datetime(2026, 8, 5)
    parser.reader = SimpleNamespace(pages_simple=list(pages))
    return parser


def test_recovers_only_transactions_missing_from_table_extraction() -> None:
    parser = configured_parser(
        "\n".join(
            (
                "07/03 07/04 ALREADY EXTRACTED CA $10.00",
                "3 1 07/03 07/04 OBSCURED ROW CA $20.00",
                "07/21 AUTOPAY AUTO-PMT -$30.00",
            )
        )
    )
    extracted = [
        Transaction(
            transaction_date=datetime(2026, 7, 3),
            posting_date=datetime(2026, 7, 4),
            amount=Decimal("-10.00"),
            desc="ALREADY EXTRACTED CA",
        )
    ]

    missing = parser.extract_missing_text_transactions(extracted)

    assert [(item.amount, item.desc) for item in missing] == [
        (Decimal("-20.00"), "OBSCURED ROW CA"),
        (Decimal("30.00"), "AUTOPAY AUTO-PMT"),
    ]


def test_recovers_multiline_fee_from_fee_section() -> None:
    parser = configured_parser(
        "\n".join(
            (
                "Fees Charged",
                "08/05 MEMBERSHIP FEE AUG 26-JUL 27",
                "SEE REVERSE FOR RENEWAL INFORMATION $99.00",
                "TOTAL FEES FOR THIS PERIOD $99.00",
            )
        )
    )

    missing = parser.extract_missing_fees([])

    assert len(missing) == 1
    assert missing[0].amount == Decimal("-99.00")
    assert missing[0].posting_date.isoformat() == "2026-08-05"

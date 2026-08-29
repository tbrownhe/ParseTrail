from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from parsetrail.plugins.pdf_chasecc_202602 import Parser


def test_extracts_purchase_fee_and_payment_rows() -> None:
    parser = Parser()
    parser.reader = SimpleNamespace(
        pages_simple=[
            "\n".join(
                (
                    "PAYMENTS AND OTHER CREDITS",
                    "07/12      AUTOMATIC PAYMENT - THANK YOU -4,643.05",
                    "PURCHASE",
                    "06/15      SQ *KTOWN PHO Los Angeles CA 60.58",
                    "06/15      VENDING MACHINE TOKYO  .89",
                    "FEES CHARGED",
                    "06/16      ANNUAL MEMBERSHIP FEE 95.00",
                )
            )
        ]
    )

    transactions = parser.extract_transactions(datetime(2026, 6, 15), datetime(2026, 7, 15))

    assert [transaction.amount for transaction in transactions] == [
        Decimal("4643.05"),
        Decimal("-60.58"),
        Decimal("-0.89"),
        Decimal("-95.00"),
    ]
    assert transactions[0].posting_date.isoformat() == "2026-07-12"


def test_clamps_unknown_posting_date_to_statement_boundary() -> None:
    parser = Parser()
    parser.reader = SimpleNamespace(pages_simple=["03/15      PRIOR-DAY CHARGE 10.00"])

    transactions = parser.extract_transactions(datetime(2026, 3, 16), datetime(2026, 4, 15))

    assert transactions[0].transaction_date.isoformat() == "2026-03-15"
    assert transactions[0].posting_date.isoformat() == "2026-03-16"


def test_summary_extractors_ignore_other_balance_labels() -> None:
    parser = Parser()
    parser.lines = [
        "New Balance",
        "Previous Balance $0.00",
        "New Balance $303.53",
        "Opening/Closing Date 01/24/26 - 02/15/26",
        "Account Number: XXXX XXXX XXXX 7121",
    ]

    start_date, end_date = parser.extract_statement_dates()

    assert (start_date.date().isoformat(), end_date.date().isoformat()) == ("2026-01-24", "2026-02-15")
    assert parser.extract_account_number() == "7121"
    assert parser.extract_balances() == (Decimal("0.00"), Decimal("-303.53"))

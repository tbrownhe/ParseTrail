from decimal import Decimal
from types import SimpleNamespace

import pytest
from parsetrail.plugins.pdf_capitaloneauto_202402 import Parser as AutoParser
from parsetrail.plugins.pdf_lendingclubsavings_202601 import Parser as SavingsParser


def parse(parser, lines):
    reader = SimpleNamespace(
        extract_text_simple=lambda: "\n".join(lines),
        extract_lines_simple=lambda: lines,
        text_simple="\n".join(lines),
        lines_simple=lines,
    )
    return parser().parse(reader).accounts[0]


def savings():
    return [
        "************************* LevelUp Savings 1234567890 ***********************",
        "12/31 Balance Forward -------------------------------------> 1,000.00",
        "01/12 SYNTHETIC DEPOSIT 200.00 1,200.00",
        "SYNTHETIC WITHDRAWAL 100.00- 1,100.00",
        "Interest Paid 2.00 1,102.00",
        "Previous Statement Date: 12/31/25",
        "Beginning Interest Service Ending",
        "Balance + Deposits + Paid - Deductions- Charge = Balance",
        "1,000.00 200.00 2.00 100.00 .00 1,102.00",
        "Statement from 01/01/26 thru 01/30/26 Average Stmt Balance 1,050.00",
    ]


def auto(rows=None, *, interest=True):
    if rows is None:
        rows = ["01/12/2026 Payment Received -$80.00 -$20.00 = -$100.00"]
    return [
        "Account Number: SYNTHETIC-001",
        "Current Payment Due: $100.00 Principal Balance: $920.00",
        "TRANSACTION HISTORY",
        "Transactions between 01/01/2026 - 01/31/2026",
        "Date Description Principal Interest Total" if interest else "Date Description Principal Total",
        *rows,
        "Please detach and return the portion below with your payment.",
        "PAYMENT OPTIONS",
        # Dates/amounts outside the transaction table are not activity.
        "01/31/2026 SYNTHETIC COUPON $500.00 = $500.00",
    ]


def test_savings_reads_independent_summary_and_preserves_activity():
    result = parse(SavingsParser, savings())
    assert (result.start_balance, result.end_balance) == (Decimal("1000"), Decimal("1102"))
    assert [row.amount for row in result.transactions] == [Decimal("200"), Decimal("-100"), Decimal("2")]


def test_savings_rejects_missing_tail_even_with_consistent_remaining_running_balances():
    with pytest.raises(ValueError, match="printed ending balance"):
        parse(SavingsParser, [line for line in savings() if not line.startswith("Interest Paid")])


@pytest.mark.parametrize(
    ("before", "after", "error"),
    [
        ("1,200.00", "1,201.00", "running balance"),
        ("-----> 1,000.00", "-----> 999.00", "Balance Forward"),
        (".00 1,102.00", ".00 1,103.00", "summary does not reconcile"),
        ("1,000.00 200.00", "BAD 200.00", "summary amounts"),
    ],
)
def test_savings_rejects_inconsistent_or_malformed_evidence(before, after, error):
    with pytest.raises(ValueError, match=error):
        parse(SavingsParser, [line.replace(before, after) for line in savings()])


@pytest.mark.parametrize("duplicate", [False, True])
def test_savings_requires_unique_summary(duplicate):
    lines = savings()
    header = lines[7]
    lines = lines + [header] if duplicate else [line for line in lines if line != header]
    with pytest.raises(ValueError, match="exactly one printed balance summary"):
        parse(SavingsParser, lines)


def test_savings_zero_activity_requires_matching_reported_balances():
    lines = [line for line in savings() if not any(x in line for x in ("SYNTHETIC", "Interest Paid"))]
    lines[5] = "1,000.00 .00 .00 .00 .00 1,000.00"
    result = parse(SavingsParser, lines)
    assert result.transactions == []
    assert result.start_balance == result.end_balance == Decimal("1000")


def test_auto_preserves_payment_interest_and_reconstructs_opening_from_principal():
    result = parse(AutoParser, auto())
    assert result.start_balance == Decimal("-1000")
    assert result.end_balance == Decimal("-920")
    assert [(row.amount, row.desc) for row in result.transactions] == [
        (Decimal("100"), "Payment Received"),
        (Decimal("-20"), "Interest Fee"),
    ]


def test_auto_origination_uses_principal_without_interest_column():
    result = parse(AutoParser, auto(["01/12/2026 Amount Financed $920.00 = $920.00"], interest=False))
    assert result.start_balance == Decimal("0")
    assert result.transactions[0].amount == Decimal("-920")


def test_auto_blank_lines_and_repeated_header_do_not_truncate_activity():
    rows = ["01/12/2026 Payment Received -$80.00 -$20.00 = -$100.00"]
    rows += ["", "Date Description Principal Interest Total", "01/25/2026 Payment Received -$90.00 -$10.00 = -$100.00"]
    result = parse(AutoParser, auto(rows))
    assert result.start_balance == Decimal("-1090")
    assert len(result.transactions) == 4


@pytest.mark.parametrize(
    ("before", "after", "error"),
    [
        ("-$80.00", "-$79.99", "principal and interest"),
        ("-$20.00", "-$19.99", "principal and interest"),
        ("-$100.00", "-$99.99", "principal and interest"),
        ("-$80.00", "garbled", "history amounts"),
        (" = ", " ", "history row"),
        ("01/12/2026", "02/12/2026", "outside the printed"),
        ("Principal Interest Total", "Principal Fees Interest Total", "columns"),
    ],
)
def test_auto_rejects_corrupt_or_unsupported_rows(before, after, error):
    with pytest.raises(ValueError, match=error):
        parse(AutoParser, [line.replace(before, after) for line in auto()])


def test_auto_does_not_silently_stop_at_unrecognized_row():
    rows = ["01/12/2026 Payment Received -$80.00 -$20.00 = -$100.00", "Unexpected continued activity"]
    with pytest.raises(ValueError, match="history row"):
        parse(AutoParser, auto(rows))


def test_auto_does_not_assume_no_activity_when_table_is_empty():
    with pytest.raises(ValueError, match="Empty transaction history"):
        parse(AutoParser, auto([]))


def test_auto_requires_end_marker():
    with pytest.raises(ValueError, match="end marker"):
        parse(AutoParser, [line for line in auto() if not line.startswith("Please detach")])


@pytest.mark.parametrize("duplicate", [False, True])
def test_auto_requires_unique_printed_principal_balance(duplicate):
    lines = auto()
    lines = lines + [lines[1]] if duplicate else lines[:1] + lines[2:]
    with pytest.raises(ValueError, match="exactly one printed principal balance"):
        parse(AutoParser, lines)

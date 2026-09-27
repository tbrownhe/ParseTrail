from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from parsetrail.plugins.pdf_hehsa_201810 import Parser


def parse(lines):
    return Parser().parse(SimpleNamespace(extract_lines_simple=lambda: lines)).accounts[0]


def header():
    return ["Period:08/01/26through08/31/26", "AccountNumber:SYNTHETIC-001"]


def continued():
    return header() + [
        "Date DescriptionofTransaction (Withdrawal) Balance",
        "BeginningBalance $1,000.00",
        "08/10/2026 EmployeeContributionfor2026 200.00 1,200.00",
        "InterestRateScheduleEffective:08/01/26",
        "Interest AverageDaily Interest",
        "BalanceTier Rate Balance Earned",
        "$0.00-$2,000.00 0.01% $1,100.00 $0.10",
        "1of3",
        "AccountStatement(Continued)",
        "Date DescriptionofTransaction (Withdrawal) Balance",
        "08/20/2026 Investment:SYNTHETIC (100.00) 1,100.00",
        "_ 08/31/2026 Interestfor8/1/2026-8/31/2026(Annualpercentage 0.10 1,100.10",
        "yieldearnedforperiodis0.01%onaveragecollected",
        "balanceof$1,100.00)",
        "_ EndingBalance $1,100.10",
        "InvestmentPortfolio",
        "08/31/2026 SYNTHETIC unrelated portfolio row 999.00 999.00",
    ]


def test_continuation_after_rate_table_and_underscores_preserve_all_cash_rows():
    result = parse(continued())
    assert result.start_balance == Decimal("1000.00")
    assert result.end_balance == Decimal("1100.10")
    assert [row.amount for row in result.transactions] == [Decimal("200"), Decimal("-100"), Decimal("0.10")]
    assert [row.posting_date for row in result.transactions] == [
        date(2026, 8, 10),
        date(2026, 8, 20),
        date(2026, 8, 31),
    ]
    assert all("unrelated" not in row.desc for row in result.transactions)


def test_printed_closing_balance_rejects_truncated_activity_instead_of_deriving_its_own():
    lines = [line for line in continued() if "Interestfor" not in line]
    with pytest.raises(ValueError, match="printed ending balance"):
        parse(lines)


def test_running_balance_mismatch_fails_even_when_overall_amounts_balance():
    lines = [line.replace("200.00 1,200.00", "200.00 1,201.00") for line in continued()]
    with pytest.raises(ValueError, match="printed running balance"):
        parse(lines)


@pytest.mark.parametrize("boundary", ["BeginningBalance", "EndingBalance"])
@pytest.mark.parametrize("action", ["missing", "duplicate"])
def test_missing_or_ambiguous_printed_boundaries_fail(boundary, action):
    lines = [line.lstrip("_ ") for line in continued()]
    if action == "missing":
        lines = [line for line in lines if not line.startswith(boundary)]
    else:
        lines.append(next(line for line in lines if line.startswith(boundary)))
    with pytest.raises(ValueError, match="exactly one printed"):
        parse(lines)


def test_zero_activity_statement_uses_both_printed_balances():
    result = parse(header() + ["BeginningBalance $10.00", "EndingBalance $10.00"])
    assert result.transactions == []
    assert result.start_balance == result.end_balance == Decimal("10.00")
    with pytest.raises(ValueError, match="printed ending balance"):
        parse(header() + ["BeginningBalance $10.00", "EndingBalance $10.01"])


def test_reversed_balance_boundaries_fail():
    with pytest.raises(ValueError, match="out of order"):
        parse(header() + ["EndingBalance $10.00", "BeginningBalance $10.00"])

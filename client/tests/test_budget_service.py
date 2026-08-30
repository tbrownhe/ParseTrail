from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from parsetrail.core.budgets import BudgetQueryService, InvalidBudgetQueryError
from parsetrail.core.migrate import upgrade_db
from parsetrail.core.orm import Accounts, AccountTypes, Categories, Transactions, create_database


def _transaction(category_id: int | None, seed: str, amount: str, posting_date: date) -> Transactions:
    return Transactions(
        AccountID=1,
        TransactionDate=posting_date,
        PostingDate=posting_date,
        Amount=Decimal(amount),
        Balance=Decimal("100.00"),
        CurrencyCode="USD",
        Description=seed,
        Fingerprint=hashlib.sha256(seed.encode()).hexdigest(),
        FingerprintVersion=1,
        CategoryID=category_id,
        Verified=False,
    )


def _service(tmp_path: Path) -> BudgetQueryService:
    db_path = tmp_path / "budgets.db"
    upgrade_db(db_path)
    Session = create_database(db_path)
    with Session.begin() as session:
        session.add(AccountTypes(AccountTypeID=1, AccountType="Checking", AssetType="Asset"))
        session.add(
            Accounts(
                AccountID=1,
                AccountName="Checking",
                AccountTypeID=1,
                CurrencyCode="USD",
                Company="Example",
                Description="Fixture",
                AppreciationRate=Decimal(0),
            )
        )
        groceries = Categories(CategoryID=1, Name="Groceries", Type="Expense", Active=1)
        groceries.Budget = Decimal("100.00")
        salary = Categories(CategoryID=2, Name="Salary", Type="Income", Active=1)
        salary.Budget = Decimal("200.00")
        unbudgeted = Categories(CategoryID=3, Name="Unbudgeted", Type="Expense", Active=1)
        archived = Categories(CategoryID=4, Name="Archived", Type="Expense", Active=0)
        archived.Budget = Decimal("50.00")
        session.add_all([groceries, salary, unbudgeted, archived])
        session.add_all(
            [
                _transaction(1, "groceries-one", "-30.00", date(2026, 8, 5)),
                _transaction(1, "groceries-two", "-10.00", date(2026, 8, 8)),
                _transaction(2, "paycheck", "500.00", date(2026, 8, 15)),
                _transaction(4, "archived", "-10.00", date(2026, 8, 20)),
                _transaction(None, "uncategorized", "-5.00", date(2026, 8, 22)),
                _transaction(1, "outside", "-999.00", date(2026, 9, 1)),
            ]
        )
    return BudgetQueryService(Session)


def test_budget_service_module_is_headless() -> None:
    code = """
import sys

class DenyUiImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6.") or fullname.startswith("parsetrail.gui"):
            raise AssertionError(f"UI dependency imported by budget service: {fullname}")
        return None

sys.meta_path.insert(0, DenyUiImports())
import parsetrail.core.budgets
print("headless budget service ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "headless budget service ok" in result.stdout


def test_category_report_preserves_signs_ranges_counts_and_inactive_filter(tmp_path: Path) -> None:
    service = _service(tmp_path)

    rows = service.report(start=date(2026, 8, 1), end=date(2026, 9, 1))

    assert [row.label for row in rows] == ["Salary", "Unbudgeted", "Groceries"]
    salary, unbudgeted, groceries = rows
    assert (salary.budget, salary.actual, salary.variance, salary.pct_used) == (
        Decimal("200.00"),
        Decimal("500.00"),
        Decimal("300.00"),
        Decimal("250"),
    )
    assert unbudgeted.budget is None
    assert unbudgeted.actual == 0
    assert groceries.budget == Decimal("-100.00")
    assert groceries.actual == Decimal("-40.00")
    assert groceries.variance == Decimal("60.00")
    assert groceries.pct_used == Decimal("40")
    assert groceries.transaction_count == 2

    with_inactive = service.report(
        start=date(2026, 8, 1),
        end=date(2026, 9, 1),
        include_inactive=True,
    )
    assert next(row for row in with_inactive if row.label == "Archived").actual == Decimal("-10.00")
    assert all(row.label != "uncategorized" for row in with_inactive)


def test_type_report_aggregates_and_prorates_monthly_budgets(tmp_path: Path) -> None:
    service = _service(tmp_path)

    rows = service.report(
        start=date(2026, 8, 1),
        end=date(2026, 8, 16),
        group_by="Type",
        prorate=True,
    )

    assert [row.label for row in rows] == ["Income", "Expense"]
    income, expense = rows
    assert income.budget == Decimal("100.00")
    assert income.actual == Decimal("500.00")
    assert expense.budget == Decimal("-50.00")
    assert expense.actual == Decimal("-40.00")
    assert expense.transaction_count == 2
    assert expense.pct_used == Decimal("80")


def test_budget_report_rejects_invalid_range_and_grouping(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(InvalidBudgetQueryError, match="before"):
        service.report(start=date(2026, 8, 1), end=date(2026, 8, 1))
    with pytest.raises(InvalidBudgetQueryError, match="grouped"):
        service.report(
            start=date(2026, 8, 1),
            end=date(2026, 9, 1),
            group_by="Account",  # type: ignore[arg-type]
        )

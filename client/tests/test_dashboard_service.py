from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from parsetrail.core.dashboard import DashboardQueryService
from parsetrail.core.migrate import upgrade_db
from parsetrail.core.orm import (
    Accounts,
    AccountTypes,
    Categories,
    Plugins,
    Statements,
    Transactions,
    create_database,
)


def _service(tmp_path: Path) -> DashboardQueryService:
    db_path = tmp_path / "dashboard.db"
    upgrade_db(db_path)
    Session = create_database(db_path)
    with Session.begin() as session:
        session.add_all(
            [
                AccountTypes(AccountTypeID=1, AccountType="Checking", AssetType="Asset"),
                AccountTypes(AccountTypeID=2, AccountType="Credit Card", AssetType="Debt"),
            ]
        )
        session.add_all(
            [
                Accounts(
                    AccountID=1,
                    AccountName="Checking",
                    AccountTypeID=1,
                    CurrencyCode="USD",
                    Company="Example",
                    Description="Asset",
                    AppreciationRate=Decimal(0),
                ),
                Accounts(
                    AccountID=2,
                    AccountName="Card",
                    AccountTypeID=2,
                    CurrencyCode="USD",
                    Company="Example",
                    Description="Debt",
                    AppreciationRate=Decimal(0),
                ),
            ]
        )
        session.add_all(
            [
                Categories(CategoryID=1, Name="Groceries", Type="Expense", Active=1),
                Categories(CategoryID=2, Name="Salary", Type="Income", Active=1),
            ]
        )
        session.add(
            Plugins(
                PluginID=1,
                PluginName="fixture",
                Version="1.0",
                Suffix=".csv",
                Company="Example",
                StatementType="Checking",
            )
        )
        session.add(
            Statements(
                StatementID=1,
                PluginID=1,
                AccountID=1,
                ImportedAt=datetime(2026, 8, 31, tzinfo=timezone.utc),
                StartDate=date(2026, 8, 1),
                EndDate=date(2026, 8, 31),
                StartBalance=Decimal("0.00"),
                EndBalance=Decimal("90.00"),
                CurrencyCode="USD",
                TransactionCount=1,
                Filename="fixture.csv",
                ContentHashAlgorithm="sha256",
                ContentHash="a" * 64,
            )
        )
        session.add_all(
            [
                Transactions(
                    TransactionID=1,
                    AccountID=1,
                    TransactionDate=date(2026, 8, 10),
                    PostingDate=date(2026, 8, 10),
                    Amount=Decimal("100.00"),
                    Balance=Decimal("100.00"),
                    CurrencyCode="USD",
                    Description="Paycheck",
                    Fingerprint=hashlib.sha256(b"paycheck").hexdigest(),
                    FingerprintVersion=1,
                    CategoryID=2,
                    Verified=True,
                ),
                Transactions(
                    TransactionID=2,
                    AccountID=1,
                    TransactionDate=date(2026, 8, 20),
                    PostingDate=date(2026, 8, 20),
                    Amount=Decimal("-10.00"),
                    Balance=Decimal("90.00"),
                    CurrencyCode="USD",
                    Description="Food",
                    Fingerprint=hashlib.sha256(b"food").hexdigest(),
                    FingerprintVersion=1,
                    CategoryID=1,
                    Verified=True,
                ),
                Transactions(
                    TransactionID=3,
                    AccountID=2,
                    TransactionDate=date(2026, 8, 22),
                    PostingDate=date(2026, 8, 22),
                    Amount=Decimal("-25.00"),
                    Balance=Decimal("-25.00"),
                    CurrencyCode="USD",
                    Description="Card food",
                    Fingerprint=hashlib.sha256(b"card-food").hexdigest(),
                    FingerprintVersion=1,
                    CategoryID=1,
                    Verified=False,
                ),
            ]
        )
    return DashboardQueryService(Session)


def test_dashboard_service_module_is_headless() -> None:
    code = """
import sys

class DenyUiImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6.") or fullname.startswith("parsetrail.gui"):
            raise AssertionError(f"UI dependency imported by dashboard service: {fullname}")
        return None

sys.meta_path.insert(0, DenyUiImports())
import parsetrail.core.dashboard
print("headless dashboard service ok")
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
    assert "headless dashboard service ok" in result.stdout


def test_dashboard_queries_return_balances_checklists_and_discrepancy_inputs(tmp_path: Path) -> None:
    service = _service(tmp_path)

    balances = service.latest_balances()
    assert [(row.account_name, row.balance, row.date) for row in balances] == [
        ("Checking", Decimal("90.00"), date(2026, 8, 20)),
        ("Card", Decimal("-25.00"), date(2026, 8, 22)),
    ]
    assert service.account_names() == ["Card", "Checking"]
    assert service.category_names() == ["Groceries", "Salary"]
    discrepancy = service.statement_discrepancy_data()
    assert discrepancy.balances == tuple(balances)
    assert discrepancy.latest_statement_date == date(2026, 8, 31)


def test_dashboard_history_and_training_queries_preserve_expected_shapes(tmp_path: Path) -> None:
    service = _service(tmp_path)

    balance_history, debt_columns = service.balance_history()
    assert {"Checking", "Card", "Net Worth", "Total Assets", "Total Debts"}.issubset(balance_history.columns)
    assert debt_columns == ["Card", "Total Debts"]
    category_spending = service.category_spending()
    assert set(category_spending.columns) == {"Groceries", "Salary"}

    rows, columns = service.training_set()
    assert columns == ["TransactionID", "Company", "AccountType", "Description", "Amount", "Category"]
    assert [row.TransactionID for row in rows] == [1, 2]

from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from parsetrail.core.categories import (
    CategoryNotFoundError,
    CategoryService,
    DuplicateCategoryError,
    InvalidCategoryError,
)
from parsetrail.core.migrate import upgrade_db
from parsetrail.core.orm import (
    Accounts,
    AccountTypes,
    Categories,
    Transactions,
    create_database,
)
from sqlalchemy import select


def _transaction(category_id: int, seed: str, *, verified: bool) -> Transactions:
    return Transactions(
        AccountID=1,
        TransactionDate=date(2026, 8, 1),
        PostingDate=date(2026, 8, 2),
        Amount=Decimal("10.00"),
        Balance=Decimal("100.00"),
        CurrencyCode="USD",
        Description=f"Transaction {seed}",
        Fingerprint=hashlib.sha256(seed.encode()).hexdigest(),
        FingerprintVersion=1,
        CategoryID=category_id,
        Verified=verified,
        ConfidenceScore=Decimal("0.75"),
    )


def _service(tmp_path: Path) -> tuple[CategoryService, object]:
    db_path = tmp_path / "categories.db"
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
        groceries.Budget = Decimal("250.00")
        archived = Categories(CategoryID=2, Name="Old category", Type="Expense", Active=0)
        income = Categories(CategoryID=3, Name="Salary", Type="Income", Active=1)
        session.add_all([groceries, archived, income])
        session.add_all(
            [
                _transaction(1, "verified", verified=True),
                _transaction(1, "unverified", verified=False),
                _transaction(2, "archived", verified=True),
            ]
        )
    return CategoryService(Session), Session


def test_category_service_module_is_headless() -> None:
    code = """
import sys

class DenyUiImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6.") or fullname.startswith("parsetrail.gui"):
            raise AssertionError(f"UI dependency imported by category service: {fullname}")
        return None

sys.meta_path.insert(0, DenyUiImports())
import parsetrail.core.categories
print("headless category service ok")
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
    assert "headless category service ok" in result.stdout


def test_list_categories_preserves_filter_order_budget_and_counts(tmp_path: Path) -> None:
    service, _Session = _service(tmp_path)

    active = service.list_categories()
    all_categories = service.list_categories(include_inactive=True)

    assert [(row.name, row.transaction_count) for row in active] == [("Groceries", 2), ("Salary", 0)]
    assert active[0].budget == Decimal("250.00")
    assert [(row.name, row.active) for row in all_categories] == [
        ("Groceries", True),
        ("Old category", False),
        ("Salary", True),
    ]


def test_add_and_inline_updates_are_atomic_and_validated(tmp_path: Path) -> None:
    service, Session = _service(tmp_path)

    added = service.add(" Utilities ", "Expense")
    assert added.name == "Utilities"
    assert added.active is True
    assert service.set_type(added.category_id, "Transfer").category_type == "Transfer"
    assert service.set_budget(added.category_id, "123.45").budget == Decimal("123.45")
    assert service.set_active(added.category_id, False).active is False
    assert service.set_budget(added.category_id, "").budget is None

    with pytest.raises(DuplicateCategoryError, match="Utilities"):
        service.add("Utilities", "Income")
    with pytest.raises(InvalidCategoryError, match="Type must be"):
        service.set_type(added.category_id, "Other")
    with pytest.raises(InvalidCategoryError, match="valid USD amount"):
        service.set_budget(added.category_id, "12.345")
    with pytest.raises(CategoryNotFoundError):
        service.set_active(999, True)

    with Session() as session:
        category = session.get(Categories, added.category_id)
        assert category.Type == "Transfer"
        assert category.Budget is None
        assert category.Active is False


def test_rename_migrates_transactions_and_preserves_verification_by_default(tmp_path: Path) -> None:
    service, Session = _service(tmp_path)

    impact = service.describe(1)
    assert (impact.transaction_count, impact.verified_transaction_count) == (2, 1)
    change = service.rename(1, "Food")

    assert change.source_name == "Groceries"
    assert change.target_name == "Food"
    assert change.affected_transactions == 2
    with Session() as session:
        source = session.get(Categories, 1)
        target = session.scalar(select(Categories).where(Categories.Name == "Food"))
        transactions = session.scalars(
            select(Transactions).where(Transactions.Description.in_(["Transaction verified", "Transaction unverified"]))
        ).all()
        assert source.Active is False
        assert target.Type == "Expense"
        assert target.Budget is None
        assert {transaction.CategoryID for transaction in transactions} == {target.CategoryID}
        assert {transaction.Verified for transaction in transactions} == {True, False}
        assert all(transaction.ConfidenceScore is None for transaction in transactions)


def test_failed_rename_does_not_partially_change_the_source(tmp_path: Path) -> None:
    service, Session = _service(tmp_path)

    with pytest.raises(DuplicateCategoryError, match="Salary"):
        service.rename(1, "Salary", unverify=True)

    with Session() as session:
        source = session.get(Categories, 1)
        transactions = session.scalars(select(Transactions).where(Transactions.CategoryID == 1)).all()
        assert source.Active is True
        assert len(transactions) == 2
        assert all(transaction.ConfidenceScore == Decimal("0.75") for transaction in transactions)


def test_merge_reactivates_target_and_can_unverify_transactions(tmp_path: Path) -> None:
    service, Session = _service(tmp_path)

    change = service.merge(1, 2, unverify=True)

    assert change.source_name == "Groceries"
    assert change.target_name == "Old category"
    assert change.affected_transactions == 2
    with Session() as session:
        source = session.get(Categories, 1)
        target = session.get(Categories, 2)
        moved = session.scalars(
            select(Transactions).where(Transactions.Description.in_(["Transaction verified", "Transaction unverified"]))
        ).all()
        assert source.Active is False
        assert target.Active is True
        assert {transaction.CategoryID for transaction in moved} == {2}
        assert all(transaction.Verified is False for transaction in moved)
        assert all(transaction.ConfidenceScore is None for transaction in moved)

    with pytest.raises(InvalidCategoryError, match="must be different"):
        service.merge(2, 2)

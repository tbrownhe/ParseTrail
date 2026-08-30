from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from parsetrail.core.migrate import upgrade_db
from parsetrail.core.orm import Accounts, AccountTypes, Categories, Transactions, create_database
from parsetrail.core.transactions import TransactionAccountNotFoundError, TransactionService
from parsetrail.core.validation import Transaction


def _stored_transaction(
    transaction_id: int,
    seed: str,
    *,
    posting_date: date,
    amount: str,
    balance: str,
    category_id: int | None = 1,
) -> Transactions:
    return Transactions(
        TransactionID=transaction_id,
        AccountID=1,
        TransactionDate=posting_date,
        PostingDate=posting_date,
        Amount=Decimal(amount),
        Balance=Decimal(balance),
        CurrencyCode="USD",
        Description=seed,
        Fingerprint=hashlib.sha256(seed.encode()).hexdigest(),
        FingerprintVersion=1,
        CategoryID=category_id,
        Verified=False,
    )


def _service(tmp_path: Path) -> tuple[TransactionService, object]:
    db_path = tmp_path / "transactions.db"
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
        session.add(Categories(CategoryID=1, Name="Groceries", Type="Expense", Active=1))
        session.add_all(
            [
                _stored_transaction(
                    1,
                    "older",
                    posting_date=date(2026, 8, 1),
                    amount="-10.00",
                    balance="90.00",
                ),
                _stored_transaction(
                    2,
                    "same-day-later-id",
                    posting_date=date(2026, 8, 1),
                    amount="5.00",
                    balance="95.00",
                    category_id=None,
                ),
                _stored_transaction(
                    3,
                    "newest",
                    posting_date=date(2026, 8, 5),
                    amount="5.00",
                    balance="100.00",
                ),
            ]
        )
    return TransactionService(Session), Session


def test_transaction_service_module_is_headless() -> None:
    code = """
import sys

class DenyUiImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6.") or fullname.startswith("parsetrail.gui"):
            raise AssertionError(f"UI dependency imported by transaction service: {fullname}")
        return None

sys.meta_path.insert(0, DenyUiImports())
import parsetrail.core.transactions
print("headless transaction service ok")
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
    assert "headless transaction service ok" in result.stdout


def test_account_and_transaction_queries_preserve_order_ranges_and_exact_money(tmp_path: Path) -> None:
    service, _Session = _service(tmp_path)

    assert service.accounts() == [(1, "Checking")]
    assert service.latest_balance(1) == (date(2026, 8, 5), Decimal("100.00"))
    assert service.latest_balance(999) is None

    rows = service.in_range(start=date(2026, 8, 1), end=date(2026, 8, 1))
    assert [row.description for row in rows] == ["older", "same-day-later-id"]
    assert rows[0].amount == Decimal("-10.00")
    assert rows[0].category == "Groceries"
    assert rows[1].category is None


def test_manual_insert_hashes_atomically_and_reports_duplicates(tmp_path: Path) -> None:
    service, Session = _service(tmp_path)
    manual = Transaction(
        transaction_date=date(2026, 8, 10),
        posting_date=date(2026, 8, 10),
        amount=Decimal("-25.00"),
        balance=Decimal("75.00"),
        desc="Manual Entry: Repair",
    )

    first = service.insert_manual(1, [manual])
    second = service.insert_manual(1, [manual])

    assert (first.inserted, first.duplicates) == (1, 0)
    assert (second.inserted, second.duplicates) == (0, 1)
    with Session() as session:
        stored = session.query(Transactions).filter(Transactions.Description == "Manual Entry: Repair").one()
        assert stored.Amount == Decimal("-25.00")
        assert stored.Balance == Decimal("75.00")
        assert len(stored.Fingerprint) == 64


def test_manual_insert_rejects_a_missing_account_without_partial_data(tmp_path: Path) -> None:
    service, Session = _service(tmp_path)
    manual = Transaction(
        transaction_date=date(2026, 8, 10),
        posting_date=date(2026, 8, 10),
        amount=Decimal("1.00"),
        balance=Decimal("1.00"),
        desc="Manual Entry: Missing account",
    )

    with pytest.raises(TransactionAccountNotFoundError, match="999"):
        service.insert_manual(999, [manual])

    with Session() as session:
        assert session.query(Transactions).filter(Transactions.Description == manual.desc).count() == 0

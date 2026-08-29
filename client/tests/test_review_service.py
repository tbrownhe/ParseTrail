from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from parsetrail.core import categorize
from parsetrail.core.learn import CategoryCompatibilityError
from parsetrail.core.migrate import upgrade_db
from parsetrail.core.orm import Accounts, AccountTypes, Categories, Transactions, create_database
from parsetrail.core.review import (
    InvalidReviewChangesError,
    ReviewTransactionNotFoundError,
    TransactionRecord,
    TransactionReviewService,
)


def _transaction(
    transaction_id: int,
    category_id: int | None,
    seed: str,
    *,
    posting_date: date,
    verified: bool,
) -> Transactions:
    return Transactions(
        TransactionID=transaction_id,
        AccountID=1,
        TransactionDate=posting_date,
        PostingDate=posting_date,
        Amount=Decimal("-10.00"),
        Balance=Decimal("100.00"),
        CurrencyCode="USD",
        Description=seed,
        Fingerprint=hashlib.sha256(seed.encode()).hexdigest(),
        FingerprintVersion=1,
        CategoryID=category_id,
        Verified=verified,
        ConfidenceScore=Decimal("0.75"),
    )


def _service(tmp_path: Path) -> tuple[TransactionReviewService, object]:
    db_path = tmp_path / "review.db"
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
        session.add_all(
            [
                Categories(CategoryID=1, Name="Groceries", Type="Expense", Active=1),
                Categories(CategoryID=2, Name="Utilities", Type="Expense", Active=1),
                Categories(CategoryID=3, Name="Archived", Type="Expense", Active=0),
            ]
        )
        session.add_all(
            [
                _transaction(1, 1, "active-unverified", posting_date=date(2026, 8, 1), verified=False),
                _transaction(2, 3, "archived-unverified", posting_date=date(2026, 8, 2), verified=False),
                _transaction(3, None, "uncategorized", posting_date=date(2026, 8, 3), verified=False),
                _transaction(4, 1, "verified", posting_date=date(2026, 8, 4), verified=True),
            ]
        )
    return TransactionReviewService(Session), Session


def test_review_service_module_is_headless() -> None:
    code = """
import sys

class DenyUiImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6.") or fullname.startswith("parsetrail.gui"):
            raise AssertionError(f"UI dependency imported by review service: {fullname}")
        return None

sys.meta_path.insert(0, DenyUiImports())
import parsetrail.core.review
print("headless review service ok")
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
    assert "headless review service ok" in result.stdout


def test_review_queries_preserve_filters_order_and_category_state(tmp_path: Path) -> None:
    service, _Session = _service(tmp_path)

    assert service.active_categories() == [(1, "Groceries"), (2, "Utilities")]
    unverified = service.list_transactions()
    assert [record.description for record in unverified] == [
        "active-unverified",
        "archived-unverified",
        "uncategorized",
    ]
    assert unverified[0].account_name == "Checking"
    assert unverified[0].amount == Decimal("-10.00")
    assert unverified[0].confidence == 0.75
    assert unverified[1].category_active is False
    assert unverified[2].category_id is None
    assert unverified[2].category_name == ""
    assert unverified[2].category_active is True

    archived = service.list_transactions(only_unverified=False, only_archived_categories=True)
    assert [record.description for record in archived] == ["archived-unverified"]
    assert len(service.list_transactions(only_unverified=False)) == 4


def test_save_changes_is_atomic_and_clears_model_confidence(tmp_path: Path) -> None:
    service, Session = _service(tmp_path)
    records = service.list_transactions()
    first, second = records[:2]
    first.category_id = 2
    first.category_name = "Utilities"
    first.verified = True
    second.category_id = 999

    with pytest.raises(InvalidReviewChangesError, match="999"):
        service.save_changes(records)
    with Session() as session:
        unchanged = session.get(Transactions, 1)
        assert unchanged.CategoryID == 1
        assert unchanged.Verified is False
        assert unchanged.ConfidenceScore == Decimal("0.75")

    second.category_id = 2
    assert service.save_changes(records) == 2
    with Session() as session:
        saved = session.get(Transactions, 1)
        assert saved.CategoryID == 2
        assert saved.Verified is True
        assert saved.ConfidenceScore is None


def test_save_rejects_uncategorized_or_disappeared_transactions(tmp_path: Path) -> None:
    service, Session = _service(tmp_path)
    uncategorized = next(record for record in service.list_transactions() if record.category_id is None)
    uncategorized.verified = True
    with pytest.raises(InvalidReviewChangesError, match="no category"):
        service.save_changes([uncategorized])

    missing = TransactionRecord(
        transaction_id=999,
        date=date(2026, 8, 1),
        account_name="Checking",
        description="Missing",
        amount=Decimal(0),
        category_id=1,
        category_name="Groceries",
        verified=False,
        category_active=True,
    )
    missing.verified = True
    with pytest.raises(ReviewTransactionNotFoundError, match="999"):
        service.save_changes([missing])

    with Session() as session:
        assert session.get(Transactions, 3).Verified is False


def test_auto_categorize_can_add_missing_categories_and_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _Session = _service(tmp_path)
    categorize_calls = []
    add_calls = []

    def fake_categorize(**kwargs) -> None:
        categorize_calls.append(kwargs)
        if len(categorize_calls) == 1:
            raise CategoryCompatibilityError(["Travel", "Dining", "Travel"])

    monkeypatch.setattr(categorize, "transactions", fake_categorize)
    monkeypatch.setattr(
        categorize,
        "add_missing_categories",
        lambda session, missing: add_calls.append((session, tuple(missing))) or list(missing),
    )
    decisions = []

    result = service.auto_categorize(
        tmp_path / "model.joblib",
        missing_category_decision=lambda missing: decisions.append(tuple(missing)) or True,
    )

    assert result.completed is True
    assert result.added_categories == ("Dining", "Travel")
    assert decisions == [("Dining", "Travel")]
    assert len(categorize_calls) == 2
    assert add_calls[0][1] == ("Dining", "Travel")


def test_auto_categorize_rejection_does_not_add_or_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _Session = _service(tmp_path)
    calls = []

    def incompatible(**kwargs) -> None:
        calls.append(kwargs)
        raise CategoryCompatibilityError(["Travel"])

    monkeypatch.setattr(categorize, "transactions", incompatible)
    monkeypatch.setattr(
        categorize,
        "add_missing_categories",
        lambda *_args: pytest.fail("missing categories must not be added after rejection"),
    )

    result = service.auto_categorize(
        tmp_path / "model.joblib",
        missing_category_decision=lambda _missing: False,
    )

    assert result.completed is False
    assert result.added_categories == ()
    assert len(calls) == 1

from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from parsetrail.core.accounts import (
    AccountInUseError,
    AccountNotFoundError,
    AccountService,
    AccountSummary,
    DuplicateAccountError,
    DuplicateAccountNumberError,
    InvalidAccountError,
)
from parsetrail.core.migrate import upgrade_db
from parsetrail.core.orm import Accounts, AccountTypes, Transactions, create_database


def _service(tmp_path: Path) -> tuple[AccountService, object]:
    db_path = tmp_path / "accounts.db"
    upgrade_db(db_path)
    Session = create_database(db_path)
    with Session.begin() as session:
        session.add_all(
            [
                AccountTypes(AccountTypeID=1, AccountType="Checking", AssetType="Asset"),
                AccountTypes(AccountTypeID=2, AccountType="TangibleAsset", AssetType="TangibleAsset"),
            ]
        )
        session.add(
            Accounts(
                AccountID=1,
                AccountName="Primary checking",
                AccountTypeID=1,
                CurrencyCode="USD",
                Company="Example Bank",
                Description="Daily spending",
                AppreciationRate=Decimal(0),
            )
        )
    return AccountService(Session), Session


def test_account_service_module_is_headless() -> None:
    code = """
import sys

class DenyUiImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6.") or fullname.startswith("parsetrail.gui"):
            raise AssertionError(f"UI dependency imported by account service: {fullname}")
        return None

sys.meta_path.insert(0, DenyUiImports())
import parsetrail.core.accounts
print("headless account service ok")
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
    assert "headless account service ok" in result.stdout


def test_list_accounts_and_types_preserves_details_and_order(tmp_path: Path) -> None:
    service, _Session = _service(tmp_path)

    assert service.account_types() == ["Checking", "TangibleAsset"]
    assert service.list_accounts() == [
        AccountSummary(
            account_id=1,
            name="Primary checking",
            company="Example Bank",
            description="Daily spending",
            account_type="Checking",
            appreciation_rate=Decimal(0),
        )
    ]


def test_add_update_and_validation_are_atomic(tmp_path: Path) -> None:
    service, Session = _service(tmp_path)

    added = service.add(
        name="House",
        account_type="TangibleAsset",
        company="Personal",
        description="Residence",
        appreciation_rate="3.25",
    )
    assert added.appreciation_rate == Decimal("3.25")
    updated = service.update(
        "House",
        account_type="Checking",
        company="New company",
        description="New description",
        appreciation_rate=0,
    )
    assert updated.name == "House"
    assert updated.account_type == "Checking"
    assert updated.company == "New company"

    with pytest.raises(DuplicateAccountError, match="House"):
        service.add(
            name="House",
            account_type="Checking",
            company="Duplicate",
            description="Duplicate",
        )
    with pytest.raises(InvalidAccountError, match="required"):
        service.add(name="", account_type="Checking", company="Bank", description="Missing")
    with pytest.raises(InvalidAccountError, match="appreciation"):
        service.update(
            "House",
            account_type="TangibleAsset",
            company="Personal",
            description="Residence",
            appreciation_rate="not-a-number",
        )
    with pytest.raises(AccountNotFoundError, match="Unknown"):
        service.update(
            "Unknown",
            account_type="Checking",
            company="Bank",
            description="Missing",
        )

    with Session() as session:
        account = session.get(Accounts, added.account_id)
        assert account.AccountTypeID == 1
        assert account.Company == "New company"
        assert account.AppreciationRate == Decimal(0)


def test_assign_account_number_is_unique_and_resolvable(tmp_path: Path) -> None:
    service, _Session = _service(tmp_path)

    assert service.assign_number("Primary checking", "ending-1234") == 1
    assert service.account_id_for_number("ending-1234") == 1
    with pytest.raises(DuplicateAccountNumberError, match="ending-1234"):
        service.assign_number("Primary checking", "ending-1234")
    with pytest.raises(AccountNotFoundError, match="missing"):
        service.account_id_for_number("missing")


def test_delete_removes_unused_account_and_rejects_account_with_history(tmp_path: Path) -> None:
    service, Session = _service(tmp_path)
    unused = service.add(
        name="Unused",
        account_type="Checking",
        company="Example",
        description="No history",
    )
    service.assign_number("Unused", "unused-number")
    service.delete("Unused")

    with Session() as session:
        assert session.get(Accounts, unused.account_id) is None
        session.add(
            Transactions(
                AccountID=1,
                TransactionDate=date(2026, 8, 1),
                PostingDate=date(2026, 8, 2),
                Amount=Decimal("10.00"),
                Balance=Decimal("100.00"),
                CurrencyCode="USD",
                Description="History",
                Fingerprint=hashlib.sha256(b"history").hexdigest(),
                FingerprintVersion=1,
                Verified=False,
            )
        )
        session.commit()

    with pytest.raises(AccountInUseError, match="statements or transactions"):
        service.delete("Primary checking")
    with pytest.raises(AccountNotFoundError, match="Unknown"):
        service.delete("Unknown")

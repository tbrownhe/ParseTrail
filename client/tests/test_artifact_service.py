from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from parsetrail.core import artifacts
from parsetrail.core.artifacts import ArtifactService, ArtifactWriteError
from parsetrail.core.migrate import upgrade_db
from parsetrail.core.orm import (
    AccountNumbers,
    Accounts,
    AccountTypes,
    Categories,
    Transactions,
    create_database,
)


def _service(tmp_path: Path) -> ArtifactService:
    db_path = tmp_path / "artifacts.db"
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
                AppreciationRate=Decimal("1.25"),
            )
        )
        session.add(AccountNumbers(AccountNumberID=1, AccountID=1, AccountNumber="ending-1234"))
        session.add(Categories(CategoryID=1, Name="Groceries", Type="Expense", Active=1))
        session.add(
            Transactions(
                TransactionID=1,
                AccountID=1,
                TransactionDate=date(2026, 8, 10),
                PostingDate=date(2026, 8, 10),
                Amount=Decimal("-10.00"),
                Balance=Decimal("90.00"),
                CurrencyCode="USD",
                Description="Food",
                Fingerprint=hashlib.sha256(b"food").hexdigest(),
                FingerprintVersion=1,
                CategoryID=1,
                Verified=True,
            )
        )
    return ArtifactService(Session)


def test_artifact_service_module_is_headless() -> None:
    code = """
import sys

class DenyUiImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6.") or fullname.startswith("parsetrail.gui"):
            raise AssertionError(f"UI dependency imported by artifact service: {fullname}")
        return None

sys.meta_path.insert(0, DenyUiImports())
import parsetrail.core.artifacts
print("headless artifact service ok")
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
    assert "headless artifact service ok" in result.stdout


def test_account_export_is_complete_and_atomically_replaces_destination(tmp_path: Path) -> None:
    service = _service(tmp_path)
    destination = tmp_path / "exports" / "accounts.json"
    destination.parent.mkdir()
    destination.write_text("stale", encoding="utf-8")

    result = service.export_accounts(destination)
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert (result.account_count, result.account_number_count) == (1, 1)
    assert payload["Accounts"][0]["AccountName"] == "Checking"
    assert payload["Accounts"][0]["AppreciationRate"] == "1.2500000000"
    assert payload["AccountNumbers"][0]["AccountNumber"] == "ending-1234"
    assert list(destination.parent.glob(".*.tmp")) == []


def test_failed_account_export_preserves_existing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    destination = tmp_path / "accounts.json"
    destination.write_text("original", encoding="utf-8")
    monkeypatch.setattr(
        artifacts.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("injected replace failure")),
    )

    with pytest.raises(ArtifactWriteError, match="accounts.json"):
        service.export_accounts(destination)

    assert destination.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_report_generation_writes_expected_workbook_without_launching_it(tmp_path: Path) -> None:
    service = _service(tmp_path)
    destination = tmp_path / "report.xlsx"

    assert service.generate_report(destination) == destination
    assert destination.is_file()
    with pd.ExcelFile(destination) as workbook:
        assert workbook.sheet_names == ["Transactions", "Pivot Category", "Pivot CategoryAsset"]

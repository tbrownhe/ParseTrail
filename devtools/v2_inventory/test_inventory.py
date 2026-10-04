"""Synthetic preservation cases; never touch a real profile."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from parsetrail.core.orm import Base
from sqlalchemy import create_engine

from devtools.v2_inventory.inventory import create_inventory


def _source(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "books.db"
    engine = create_engine(f"sqlite:///{source}")
    Base.metadata.create_all(engine)
    engine.dispose()
    data = b"synthetic statement bytes"
    archive = tmp_path / "books"
    (archive / "SUCCESS").mkdir(parents=True)
    (archive / "SUCCESS" / "sample.pdf").write_bytes(data)
    (archive / "FAIL").mkdir()
    (archive / "FAIL" / "failed.txt").write_text("synthetic", encoding="utf-8")
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.json").write_text(
        json.dumps({"db_path": str(source), "email": "private@example.test"}), encoding="utf-8"
    )
    (profile / "accounts.json").write_text("{}", encoding="utf-8")
    with sqlite3.connect(source) as connection:
        connection.executescript(
            "CREATE TABLE alembic_version(version_num TEXT NOT NULL);"
            "INSERT INTO alembic_version VALUES('0004_statement_accounting');"
            "INSERT INTO Currencies(CurrencyCode,MinorUnit) VALUES('USD',2);"
            "INSERT INTO AccountTypes(AccountTypeID,AccountType,AssetType) VALUES(1,'Checking','Asset');"
            "INSERT INTO Accounts(AccountID,AccountName,AccountTypeID,CurrencyCode,Company,Description,AppreciationRate) "
            "VALUES(1,'Synthetic checking',1,'USD','Synthetic','',0);"
            "INSERT INTO AccountNumbers(AccountNumberID,AccountID,AccountNumber) VALUES(1,1,'synthetic-1');"
            "INSERT INTO Categories(CategoryID,Name,Type,Active,BudgetMinor,BudgetCurrencyCode) "
            "VALUES(1,'Groceries','Expense',1,12500,'USD');"
            "INSERT INTO Plugins(PluginID,PluginName,Version,Suffix,Company,StatementType) "
            "VALUES(1,'synthetic','1','.pdf','Synthetic','Statement');"
        )
        connection.execute(
            "INSERT INTO Statements(StatementID,PluginID,AccountID,ImportedAt,StartDate,EndDate,StartBalanceMinor,"
            "EndBalanceMinor,CurrencyCode,TransactionCount,Filename,ContentHashAlgorithm,ContentHash) "
            "VALUES(1,1,1,'2026-01-02','2026-01-01','2026-01-31',10000,9000,'USD',1,'sample.pdf','sha256',?)",
            (hashlib.sha256(data).hexdigest(),),
        )
        connection.execute(
            "INSERT INTO Transactions(TransactionID,AccountID,PostingDate,AmountMinor,BalanceMinor,CurrencyCode,"
            "Description,Fingerprint,FingerprintVersion,CategoryID,Verified) "
            "VALUES(1,1,'2026-01-05',-1000,9000,'USD','Synthetic purchase',?,1,1,1)",
            ("a" * 64,),
        )
        connection.execute(
            "INSERT INTO Transactions(TransactionID,AccountID,PostingDate,AmountMinor,BalanceMinor,CurrencyCode,"
            "Description,Fingerprint,FingerprintVersion,Verified) "
            "VALUES(2,1,'2026-02-01',0,9000,'USD','Manual Entry: Account Closed Manually',?,1,0)",
            ("b" * 64,),
        )
        connection.execute("INSERT INTO StatementTransactions VALUES(1,1,1)")
    return source, archive, profile


def test_inventory_preserves_all_known_fields_and_source_refs(tmp_path: Path) -> None:
    source, archive, profile = _source(tmp_path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = create_inventory(source, archive, profile)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
    assert result["source"]["state_counts"]["verified_expense"] == 1
    assert result["source"]["state_counts"]["unlinked_transactions"] == 1
    assert result["source"]["state_counts"]["manual_closure_markers"] == 1
    assert result["source"]["state_counts"]["budget_targets"] == 1
    assert result["source"]["plugin_references"] == [
        {"plugin_id": 1, "name": "synthetic", "version": "1", "statement_count": 1}
    ]
    assert len(result["source"]["tables"]["Transactions"]["content_sha256"]) == 64
    assert result["archive"]["references"] == [
        {"statement_id": 1, "status": "matched", "archive_path": "SUCCESS/sample.pdf"}
    ]
    assert not result["issues"]
    assert result["activation_ready"] is False
    assert "private@example.test" not in json.dumps(result)


def test_unknown_user_state_and_missing_source_remain_unresolved(tmp_path: Path) -> None:
    source, archive, profile = _source(tmp_path)
    with sqlite3.connect(source) as connection:
        connection.execute("ALTER TABLE Categories ADD COLUMN OwnerNote TEXT")
        connection.execute("UPDATE Categories SET OwnerNote='synthetic user note'")
    (archive / "SUCCESS" / "sample.pdf").unlink()
    (profile / "config.json").write_text(json.dumps({"owner_preference": "synthetic"}), encoding="utf-8")
    (profile / "custom.dat").write_bytes(b"synthetic")
    result = create_inventory(source, archive, profile)
    kinds = {issue["kind"] for issue in result["issues"]}
    assert {"unknown_field", "source_reference_missing", "unknown_setting", "unknown_profile_file"} <= kinds
    assert result["source"]["tables"]["Categories"]["fields"]["OwnerNote"] == "unresolved"
    assert result["source"]["state_counts"]["verified_expense"] == 1
    assert "synthetic user note" not in json.dumps(result)


def test_live_wal_sidecar_is_refused_without_mutation(tmp_path: Path) -> None:
    source, archive, profile = _source(tmp_path)
    wal = Path(str(source) + "-wal")
    wal.write_bytes(b"synthetic live marker")
    before = source.read_bytes(), wal.read_bytes()
    with pytest.raises(ValueError, match="closed snapshot"):
        create_inventory(source, archive, profile)
    assert (source.read_bytes(), wal.read_bytes()) == before

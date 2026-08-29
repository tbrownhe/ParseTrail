import hashlib
import shutil
import sqlite3
from datetime import date, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from parsetrail.core import migrate, query
from parsetrail.core.migrate import BUDGET_REVISION, upgrade_db
from parsetrail.core.orm import (
    Statements,
    StatementTransactions,
    Transactions,
    create_database,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError


def _legacy_database(path: Path) -> None:
    command.upgrade(migrate._alembic_config(path), BUDGET_REVISION)
    connection = sqlite3.connect(path)
    try:
        connection.execute('INSERT INTO "AccountTypes" VALUES (1, "Checking", "Asset")')
        connection.execute(
            'INSERT INTO "Accounts" '
            "(AccountID, AccountName, AccountTypeID, Company, Description, AppreciationRate) "
            'VALUES (1, "Primary", 1, "Example", "Migration fixture", 0.0125)'
        )
        connection.execute('INSERT INTO "AccountNumbers" VALUES (1, 1, "fixture-account")')
        connection.execute(
            'INSERT INTO "Categories" (CategoryID, Name, Type, Active, ParentID, Budget) '
            'VALUES (1, "Bills", "Expense", 1, NULL, 123.45)'
        )
        connection.execute('INSERT INTO "Plugins" VALUES (1, "fixture", "1.0.0", ".csv", "Example", "Checking")')
        connection.execute(
            'INSERT INTO "Statements" '
            "(StatementID, PluginID, AccountID, ImportDate, StartDate, EndDate, StartBalance, EndBalance, "
            "TransactionCount, Filename, MD5) "
            'VALUES (1, 1, 1, "2026-08-28", "2026-08-01", "2026-08-31", '
            '100.00, 112.34, 1, "fixture.csv", ?)',
            ("a" * 32,),
        )
        connection.execute(
            'INSERT INTO "Transactions" '
            "(TransactionID, StatementID, AccountID, Date, Amount, Balance, Description, MD5, "
            "CategoryID, Verified, ConfidenceScore) "
            'VALUES (1, 1, 1, "2026-08-15", 12.34, 112.34, "Statement row", ?, 1, 1, 0.9)',
            ("b" * 32,),
        )
        connection.execute(
            'INSERT INTO "Transactions" '
            "(TransactionID, StatementID, AccountID, Date, Amount, Balance, Description, MD5, "
            "CategoryID, Verified, ConfidenceScore) "
            'VALUES (2, NULL, 1, "2026-08-20", -2.34, 110.00, "Manual row", ?, NULL, 0, NULL)',
            ("c" * 32,),
        )
        connection.commit()
    finally:
        connection.close()


def test_create_database_never_conceals_missing_migrations(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError, match="upgrade_db"):
        create_database(missing)

    empty = tmp_path / "empty.db"
    empty.touch()
    with pytest.raises(RuntimeError, match="missing tables"):
        create_database(empty)


def test_new_database_is_created_at_head_without_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "new.db"
    upgrade_db(db_path)

    assert db_path.exists()
    assert list(tmp_path.glob("*.dbb")) == []
    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            "0003_precise_financial_schema"
        )
        assert connection.execute("SELECT MinorUnit FROM Currencies WHERE CurrencyCode='USD'").fetchone()[0] == 2
    finally:
        connection.close()


def test_legacy_database_migrates_exact_values_dates_membership_and_constraints(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _legacy_database(db_path)

    upgrade_db(db_path)

    backups = list(tmp_path.glob("legacy_*.dbb"))
    assert len(backups) == 1
    Session = create_database(db_path)
    with Session() as session:
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
        statement = session.get(Statements, 1)
        assert statement.StartDate == date(2026, 8, 1)
        assert statement.StartBalance == Decimal("100.00")
        assert statement.ImportedAt.tzinfo == timezone.utc
        assert statement.ContentHashAlgorithm == "md5"
        assert statement.TransactionCount == 1

        transactions = session.scalars(select(Transactions).order_by(Transactions.TransactionID)).all()
        assert [transaction.Amount for transaction in transactions] == [Decimal("12.34"), Decimal("-2.34")]
        assert [transaction.PostingDate for transaction in transactions] == [
            date(2026, 8, 15),
            date(2026, 8, 20),
        ]
        assert all(len(transaction.Fingerprint) == 64 for transaction in transactions)
        assert session.scalar(select(func.count()).select_from(StatementTransactions)) == 1

        transaction_data, columns = query.transactions(session)
        assert columns[3:6] == ["Date", "Amount", "Balance"]
        assert transaction_data[0].Date == date(2026, 8, 15)
        assert transaction_data[0].Amount == Decimal("12.34")
        assert transaction_data[0].Balance == Decimal("112.34")
        assert query.latest_balance(session, 1) == (date(2026, 8, 20), Decimal("110.00"))
        assert query.statement_max_date(session) == date(2026, 8, 31)

        ranged, _ = query.transactions_in_range(
            session,
            start_date=date(2026, 8, 16),
            end_date=date(2026, 8, 31),
        )
        assert [row.Description for row in ranged] == ["Manual row"]

        session.execute(text('DELETE FROM "Categories" WHERE "CategoryID" = 1'))
        session.commit()
        assert session.get(Transactions, 1).CategoryID is None

        with pytest.raises(IntegrityError):
            session.execute(text('DELETE FROM "Accounts" WHERE "AccountID" = 1'))
            session.commit()
        session.rollback()

    connection = sqlite3.connect(db_path)
    try:
        transaction_columns = {row[1]: row[2] for row in connection.execute('PRAGMA table_info("Transactions")')}
        assert transaction_columns["AmountMinor"] == "INTEGER"
        assert transaction_columns["BalanceMinor"] == "INTEGER"
        assert "StatementID" not in transaction_columns
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()

    shutil.copy2(backups[0], db_path)
    restored = sqlite3.connect(db_path)
    try:
        assert restored.execute("SELECT version_num FROM alembic_version").fetchone()[0] == BUDGET_REVISION
        assert restored.execute('SELECT count(*) FROM "Transactions"').fetchone()[0] == 2
    finally:
        restored.close()


def test_failed_shadow_migration_preserves_original_database(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "failure.db"
    _legacy_database(db_path)
    before = hashlib.sha256(db_path.read_bytes()).digest()

    def fail_upgrade(*_args, **_kwargs) -> None:
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(migrate.command, "upgrade", fail_upgrade)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        upgrade_db(db_path)

    assert hashlib.sha256(db_path.read_bytes()).digest() == before
    assert list(tmp_path.glob(".failure.db.migrating-*")) == []
    assert len(list(tmp_path.glob("failure_*.dbb"))) == 1


def test_unversioned_unknown_schema_is_rejected_without_stamping(tmp_path: Path) -> None:
    db_path = tmp_path / "unknown.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("CREATE TABLE mystery (id INTEGER PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="does not match a supported ParseTrail schema"):
        upgrade_db(db_path)

    connection = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "mystery" in tables
        assert "alembic_version" not in tables
    finally:
        connection.close()
    assert list(tmp_path.glob("*.dbb")) == []

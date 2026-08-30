from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from parsetrail.core.database_backup import DatabaseBackupError, DatabaseBackupService
from parsetrail.core.migrate import upgrade_db


def _database(path: Path) -> Path:
    upgrade_db(path)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO Categories (Name, Type) VALUES ('Housing', 'Expense')")
    return path


def test_creates_consistent_verified_backup_without_changing_source(tmp_path: Path) -> None:
    source = _database(tmp_path / "live.db")
    destination = tmp_path / "backups" / "live.dbb"
    destination.parent.mkdir()
    before = source.read_bytes()

    inspection = DatabaseBackupService(source).create_backup(destination)

    assert inspection.path == destination.resolve()
    assert inspection.revision is not None
    assert inspection.row_counts["Categories"] == 1
    assert destination.is_file()
    assert source.read_bytes() == before
    assert not list(destination.parent.glob("*.partial"))


def test_restore_test_uses_disposable_copy_and_preserves_backup(tmp_path: Path) -> None:
    source = _database(tmp_path / "live.db")
    backup = tmp_path / "live.dbb"
    DatabaseBackupService(source).create_backup(backup)
    before = backup.read_bytes()

    inspection = DatabaseBackupService(source).test_restore(backup)

    assert inspection.path == backup.resolve()
    assert inspection.row_counts["Categories"] == 1
    assert backup.read_bytes() == before


def test_restore_creates_new_database_without_overwriting_live_or_backup(tmp_path: Path) -> None:
    source = _database(tmp_path / "live.db")
    backup = tmp_path / "live.dbb"
    service = DatabaseBackupService(source)
    service.create_backup(backup)
    source_before = source.read_bytes()
    backup_before = backup.read_bytes()
    restored = tmp_path / "restored.db"

    inspection = service.restore_to(backup, restored)

    assert inspection.path == restored.resolve()
    assert inspection.row_counts["Categories"] == 1
    assert source.read_bytes() == source_before
    assert backup.read_bytes() == backup_before
    assert restored.is_file()


def test_restore_refuses_existing_destination(tmp_path: Path) -> None:
    source = _database(tmp_path / "live.db")
    backup = tmp_path / "live.dbb"
    service = DatabaseBackupService(source)
    service.create_backup(backup)
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"do not overwrite")

    with pytest.raises(DatabaseBackupError, match="already exists"):
        service.restore_to(backup, existing)

    assert existing.read_bytes() == b"do not overwrite"


def test_corrupt_backup_fails_restore_test_with_chained_diagnostic(tmp_path: Path) -> None:
    source = _database(tmp_path / "live.db")
    corrupt = tmp_path / "corrupt.dbb"
    corrupt.write_bytes(b"not a sqlite database")

    with pytest.raises(DatabaseBackupError) as exc_info:
        DatabaseBackupService(source).test_restore(corrupt)

    assert exc_info.value.__cause__ is not None
    assert "not a sqlite" not in str(exc_info.value).lower()


def test_invalid_live_schema_does_not_leave_a_backup(tmp_path: Path) -> None:
    source = tmp_path / "invalid.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE Accounts (AccountID INTEGER PRIMARY KEY)")
    destination = tmp_path / "invalid.dbb"

    with pytest.raises(DatabaseBackupError, match="supported ParseTrail"):
        DatabaseBackupService(source).create_backup(destination)

    assert not destination.exists()

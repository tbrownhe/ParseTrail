"""Consistent, testable SQLite backup and restore operations."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from parsetrail.core.orm import Base

SUMMARY_TABLES = ("Accounts", "Statements", "Transactions", "Categories")
MINIMUM_PARSETRAIL_TABLES = frozenset(("Accounts", "Statements", "Transactions"))


class DatabaseBackupError(RuntimeError):
    """Raised when a backup cannot be created, verified, or restored safely."""


@dataclass(frozen=True, slots=True)
class DatabaseInspection:
    path: Path
    revision: str | None
    row_counts: dict[str, int]


class DatabaseBackupService:
    """Use SQLite's online backup API so live-database copies are consistent."""

    def __init__(self, source: Path) -> None:
        self.source = Path(source).resolve()

    def create_backup(self, destination: Path) -> DatabaseInspection:
        destination = self._validate_destination(destination)
        self._copy_database(self.source, destination)
        try:
            return self.inspect(destination, require_current_schema=True)
        except DatabaseBackupError:
            self._remove_failed_copy(destination)
            raise

    def test_restore(self, backup: Path) -> DatabaseInspection:
        """Restore into a disposable database, then verify integrity and relationships."""
        backup = self._validate_source(backup)
        try:
            with tempfile.TemporaryDirectory(prefix="parsetrail-restore-test-") as temp_dir:
                restored = Path(temp_dir) / "restored.db"
                self._copy_database(backup, restored)
                return self.inspect(restored, reported_path=backup)
        except DatabaseBackupError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise DatabaseBackupError("The database restore test could not be completed.") from exc

    def restore_to(self, backup: Path, destination: Path) -> DatabaseInspection:
        """Restore to a new path, preserving both the backup and current database."""
        backup = self._validate_source(backup)
        destination = self._validate_destination(destination)
        if destination == self.source:
            raise DatabaseBackupError("Restore to a new database path; the active database will not be overwritten.")
        self._copy_database(backup, destination)
        try:
            return self.inspect(destination)
        except DatabaseBackupError:
            self._remove_failed_copy(destination)
            raise

    @staticmethod
    def inspect(
        path: Path, *, reported_path: Path | None = None, require_current_schema: bool = False
    ) -> DatabaseInspection:
        path = DatabaseBackupService._validate_source(path)
        try:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            try:
                integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
                if integrity_rows != [("ok",)]:
                    raise DatabaseBackupError("The database failed SQLite's integrity check.")
                violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise DatabaseBackupError(
                        f"The database has {len(violations)} foreign-key relationship violation(s)."
                    )
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                missing_minimum = sorted(MINIMUM_PARSETRAIL_TABLES - tables)
                if missing_minimum:
                    raise DatabaseBackupError("The file is not a supported ParseTrail database.")
                if require_current_schema:
                    missing_current = sorted(set(Base.metadata.tables) - tables)
                    if missing_current:
                        raise DatabaseBackupError("The live database backup is missing current application tables.")

                revision = None
                if "alembic_version" in tables:
                    revision_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
                    revision = str(revision_row[0]) if revision_row else None
                row_counts = {
                    table: int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
                    for table in SUMMARY_TABLES
                    if table in tables
                }
            finally:
                connection.close()
        except DatabaseBackupError:
            raise
        except sqlite3.Error as exc:
            raise DatabaseBackupError("The database could not be read or verified.") from exc
        return DatabaseInspection(
            path=Path(reported_path).resolve() if reported_path is not None else path,
            revision=revision,
            row_counts=row_counts,
        )

    @staticmethod
    def _validate_source(path: Path) -> Path:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise DatabaseBackupError("Select an existing database backup file.")
        return resolved

    @staticmethod
    def _validate_destination(path: Path) -> Path:
        resolved = Path(path).expanduser().resolve()
        if resolved.exists():
            raise DatabaseBackupError("The destination already exists; choose a new filename.")
        if not resolved.parent.is_dir():
            raise DatabaseBackupError("The destination folder does not exist.")
        return resolved

    @staticmethod
    def _copy_database(source: Path, destination: Path) -> None:
        source = DatabaseBackupService._validate_source(source)
        partial = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
        try:
            source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
            try:
                destination_connection = sqlite3.connect(partial)
                try:
                    source_connection.backup(destination_connection)
                finally:
                    destination_connection.close()
            finally:
                source_connection.close()
            os.replace(partial, destination)
        except (OSError, sqlite3.Error) as exc:
            raise DatabaseBackupError("The database could not be copied safely.") from exc
        finally:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _remove_failed_copy(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

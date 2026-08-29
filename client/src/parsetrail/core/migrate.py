from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from loguru import logger
from sqlalchemy import create_engine, inspect

from parsetrail.core.settings import settings
from parsetrail.core.utils import resource_path

BASELINE_REVISION = "0001_initial_schema"
BUDGET_REVISION = "e0ecdd6abcc6"

LEGACY_COLUMNS = {
    "AccountTypes": {"AccountTypeID", "AccountType", "AssetType"},
    "Accounts": {
        "AccountID",
        "AccountName",
        "AccountTypeID",
        "Company",
        "Description",
        "AppreciationRate",
    },
    "AccountNumbers": {"AccountNumberID", "AccountID", "AccountNumber"},
    "Categories": {"CategoryID", "Name", "Type", "Active", "ParentID"},
    "Plugins": {"PluginID", "PluginName", "Version", "Suffix", "Company", "StatementType"},
    "Statements": {
        "StatementID",
        "PluginID",
        "AccountID",
        "ImportDate",
        "StartDate",
        "EndDate",
        "StartBalance",
        "EndBalance",
        "TransactionCount",
        "Filename",
        "MD5",
    },
    "Transactions": {
        "TransactionID",
        "StatementID",
        "AccountID",
        "Date",
        "Amount",
        "Balance",
        "Description",
        "MD5",
        "CategoryID",
        "Verified",
        "ConfidenceScore",
    },
}


def _alembic_config(db_path: Path) -> Config:
    base_dir = resource_path("")
    config_path = base_dir / "alembic.ini"
    migrations_path = base_dir / "migrations"

    alembic_config = Config(str(config_path))
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    alembic_config.set_main_option("script_location", str(migrations_path))
    alembic_config.set_main_option("parsetrail_db_path", str(db_path))
    return alembic_config


def _sqlite_backup(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)
    try:
        destination_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
    finally:
        source_connection.close()
    shutil.copystat(source, destination)


def _backup_database(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_name = f"{db_path.stem}_{timestamp}_{uuid.uuid4().hex[:8]}.dbb"
    backup_path = db_path.with_name(backup_name)
    _sqlite_backup(db_path, backup_path)
    return backup_path


def _has_version_table(db_path: Path) -> bool:
    if not db_path.exists():
        return False

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            return inspect(connection).has_table("alembic_version")
    finally:
        engine.dispose()


def _current_revision(db_path: Path) -> str | None:
    if not db_path.exists():
        return None

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    finally:
        engine.dispose()


def _head_revision(alembic_config: Config) -> str | None:
    script = ScriptDirectory.from_config(alembic_config)
    return script.get_current_head()


def _unversioned_revision(db_path: Path) -> str | None:
    """Validate a known legacy schema before assigning it an Alembic revision."""
    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if not table_names:
            return None
        if table_names != set(LEGACY_COLUMNS):
            missing = sorted(set(LEGACY_COLUMNS) - table_names)
            extra = sorted(table_names - set(LEGACY_COLUMNS))
            raise RuntimeError(
                "Unversioned database does not match a supported ParseTrail schema "
                f"(missing tables: {missing or 'none'}; extra tables: {extra or 'none'})."
            )

        has_budget = False
        for table, expected in LEGACY_COLUMNS.items():
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            allowed = expected | ({"Budget"} if table == "Categories" else set())
            if frozenset(columns) not in {frozenset(expected), frozenset(allowed)}:
                missing = sorted(expected - columns)
                extra = sorted(columns - allowed)
                raise RuntimeError(
                    f"Unversioned table {table} has unsupported columns "
                    f"(missing: {missing or 'none'}; extra: {extra or 'none'})."
                )
            if table == "Categories":
                has_budget = "Budget" in columns

        if has_budget:
            invalid_types = connection.execute(
                "SELECT count(*) FROM \"Categories\" WHERE Type IS NULL OR Type NOT IN ('Expense','Income','Transfer')"
            ).fetchone()[0]
            if invalid_types:
                raise RuntimeError(f"Unversioned budget schema has {invalid_types} invalid category type row(s).")
            return BUDGET_REVISION
        return BASELINE_REVISION
    finally:
        connection.close()


def _validate_migrated_database(db_path: Path, expected_revision: str) -> None:
    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Migrated database failed SQLite integrity check: {integrity}")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Migrated database has {len(violations)} foreign-key violation(s).")
        revision_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        revision = revision_row[0] if revision_row else None
        if revision != expected_revision:
            raise RuntimeError(f"Migrated database revision is {revision!r}; expected {expected_revision!r}.")
    finally:
        connection.close()


def _migrate_shadow(source: Path, head_revision: str, *, backup: bool) -> Path | None:
    source_exists = source.exists()
    unversioned_revision = None
    if source_exists and not _has_version_table(source):
        unversioned_revision = _unversioned_revision(source)

    backup_path = _backup_database(source) if backup and source_exists else None
    shadow = source.with_name(f".{source.name}.migrating-{uuid.uuid4().hex}")
    try:
        if source_exists:
            _sqlite_backup(source, shadow)

        config = _alembic_config(shadow)
        previous_override = os.environ.get("PARSETRAIL_CLIENT_DB")
        os.environ["PARSETRAIL_CLIENT_DB"] = str(shadow)
        try:
            if unversioned_revision is not None:
                logger.info("Validated unversioned database as revision {}", unversioned_revision)
                command.stamp(config, unversioned_revision)
            command.upgrade(config, "head")
        finally:
            if previous_override is not None:
                os.environ["PARSETRAIL_CLIENT_DB"] = previous_override
            else:
                os.environ.pop("PARSETRAIL_CLIENT_DB", None)

        _validate_migrated_database(shadow, head_revision)
        os.replace(shadow, source)
        return backup_path
    except Exception:
        if shadow.exists():
            shadow.unlink()
        raise


def upgrade_db(db_path: Path | None = None, *, backup: bool = True) -> None:
    """Migrate a shadow copy, validate it, then atomically replace the database."""
    target_db = Path(db_path) if db_path is not None else Path(settings.db_path)
    target_db.parent.mkdir(parents=True, exist_ok=True)

    config = _alembic_config(target_db)
    head_revision = _head_revision(config)
    if head_revision is None:
        raise RuntimeError("Client migration history has no head revision.")
    current_revision = _current_revision(target_db)
    if target_db.exists() and _has_version_table(target_db) and current_revision == head_revision:
        logger.info("Database schema version is up to date: {}", current_revision)
        return

    logger.info("Migrating database schema from {} to {}", current_revision, head_revision)
    backup_path = _migrate_shadow(target_db, head_revision, backup=backup)
    if backup_path is not None:
        logger.info("Pre-migration database backup created at {}", backup_path)

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from loguru import logger
from sqlalchemy import create_engine, inspect

from parsetrail.core.settings import settings
from parsetrail.core.utils import resource_path

BASELINE_REVISION = "0001_initial_schema"


def _alembic_config(db_path: Path) -> Config:
    base_dir = resource_path("")
    config_path = base_dir / "alembic.ini"
    migrations_path = base_dir / "migrations"

    alembic_config = Config(str(config_path))
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    alembic_config.set_main_option("script_location", str(migrations_path))
    alembic_config.set_main_option("parsetrail_db_path", str(db_path))
    return alembic_config


def _backup_database(db_path: Path) -> Optional[Path]:
    if not db_path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup_name = f"{db_path.stem}_{timestamp}.dbb"
    backup_path = db_path.with_name(backup_name)
    shutil.copy2(db_path, backup_path)
    return backup_path


def _has_version_table(db_path: Path) -> bool:
    if not db_path.exists():
        return False

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            return inspector.has_table("alembic_version")
    finally:
        engine.dispose()


def _current_revision(db_path: Path) -> Optional[str]:
    if not db_path.exists():
        return None

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    finally:
        engine.dispose()


def _head_revision(alembic_config: Config) -> Optional[str]:
    script = ScriptDirectory.from_config(alembic_config)
    return script.get_current_head()


def upgrade_db(db_path: Optional[Path] = None, *, backup: bool = True) -> None:
    """Run Alembic migrations against the client SQLite database."""
    target_db = Path(db_path) if db_path is not None else Path(settings.db_path)
    target_db.parent.mkdir(parents=True, exist_ok=True)

    alembic_config = _alembic_config(target_db)
    head_rev = _head_revision(alembic_config)
    current_rev = _current_revision(target_db)
    needs_upgrade = current_rev != head_rev

    if target_db.exists() and _has_version_table(target_db) and not needs_upgrade:
        logger.info(f"Database schema version is up to date: {current_rev}")
        return

    previous_override = os.environ.get("PARSETRAIL_CLIENT_DB")
    os.environ["PARSETRAIL_CLIENT_DB"] = str(target_db)
    try:
        if backup and needs_upgrade and target_db.exists():
            backup_path = _backup_database(target_db)
            if backup_path:
                logger.info(f"Database backup created at {backup_path}")

        if target_db.exists() and not _has_version_table(target_db):
            logger.info(f"Stamping existing database to baseline revision {BASELINE_REVISION}")
            command.stamp(alembic_config, BASELINE_REVISION)

        logger.info(f"Migrating {db_path} schema from {current_rev} to {head_rev}")
        command.upgrade(alembic_config, "head")
    finally:
        if previous_override is not None:
            os.environ["PARSETRAIL_CLIENT_DB"] = previous_override
        else:
            os.environ.pop("PARSETRAIL_CLIENT_DB", None)

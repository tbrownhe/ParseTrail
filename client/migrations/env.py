import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the local parsetrail package is importable when running Alembic
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

config = context.config

from parsetrail.core.orm import Base  # noqa: E402
from parsetrail.core.settings import settings  # noqa: E402

target_metadata = Base.metadata


def get_db_path() -> Path:
    """Resolve the target SQLite path (env override wins)."""
    config_db = config.get_main_option("parsetrail_db_path")
    if config_db:
        return Path(config_db)
    override = os.getenv("PARSETRAIL_CLIENT_DB")
    if override:
        return Path(override)
    return Path(settings.db_path)


def get_url(db_path: Path) -> str:
    return f"sqlite:///{db_path}"


def run_migrations_offline() -> None:
    url = get_url(get_db_path())
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url(get_db_path())
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

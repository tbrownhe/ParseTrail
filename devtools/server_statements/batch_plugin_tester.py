"""
Headless batch parser to regression-test ready statements against current plugins.

Runs through statement_uploads rows with plugin_status='ready', decrypts each,
and attempts to parse via the in-memory parse pipeline. Summarizes failures.
"""

import argparse

# Make the client modules importable
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from aes import decrypt_statement
from db import get_sessionmaker
from loguru import logger
from orm import StatementUploads

CLIENT_SRC = Path(__file__).resolve().parents[2] / "client" / "src"
if not CLIENT_SRC.exists():
    raise ImportError("Unable to import ParseTrail client modules")
sys.path.insert(0, str(CLIENT_SRC))

try:
    from parsetrail.build_plugins import main as build_plugins  # noqa: E402
    from parsetrail.core.parse import ParseInput, parse_any  # noqa: E402
    from parsetrail.core.plugin_manager import PluginManager  # noqa: E402
except Exception as e:  # pragma: no cover - optional dependency
    logger.warning(f"Unable to import ParseTrail client modules: {e}")
    raise


def _iter_ready_rows(
    session_maker,
    ids: Sequence[int] | None = None,
    limit: int | None = None,
) -> Iterable[StatementUploads]:
    with session_maker() as session:
        q = session.query(StatementUploads).filter(StatementUploads.plugin_status == "ready")
        if ids:
            q = q.filter(StatementUploads.id.in_(ids))
        if limit:
            q = q.limit(limit)
        yield from q.order_by(StatementUploads.id.asc())


def _parse_row(row: StatementUploads, plugin_manager: PluginManager, *, accept_warnings: bool = False):
    plaintext, metadata = decrypt_statement(row)
    parse_input = ParseInput.from_decrypted(plaintext, row.file_name, metadata)
    result = parse_any(plugin_manager, parse_input)
    return result.require_statement(accept_warnings=accept_warnings)


def run(
    ids: Sequence[int] | None = None,
    limit: int | None = None,
    *,
    accept_warnings: bool = False,
) -> int:
    build_plugins()
    plugin_manager = PluginManager(allow_unsigned=True)
    plugin_manager.load_plugins()

    failures: list[tuple[int, str]] = []
    total = 0

    session_maker = get_sessionmaker()
    for row in _iter_ready_rows(session_maker, ids, limit):
        total += 1
        try:
            _parse_row(row, plugin_manager, accept_warnings=accept_warnings)
            logger.success(f"Parsed statement submission id={row.id}")
        except Exception as e:
            err = str(e)
            failures.append((row.id, err))
            logger.error(f"Failed statement submission id={row.id}: {err}")

    logger.info(f"Processed {total} statements; {len(failures)} failures.")
    if failures:
        for sid, err in failures:
            logger.error(f"[FAIL] id={sid}: {err}")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Batch test parsing for ready statements.")
    parser.add_argument("--ids", nargs="*", type=int, help="Optional specific statement IDs to run.")
    parser.add_argument("--limit", type=int, help="Optional limit on number of statements.")
    parser.add_argument(
        "--accept-warnings",
        action="store_true",
        help="Treat validated parses with warnings as successful.",
    )
    args = parser.parse_args()
    exit_code = run(ids=args.ids, limit=args.limit, accept_warnings=args.accept_warnings)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

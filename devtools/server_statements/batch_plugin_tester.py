"""
Headless batch parser to regression-test ready statements against current plugins.

Runs through statement_uploads rows with plugin_status='ready', decrypts each,
and attempts to parse via the in-memory parse pipeline. Summarizes failures.
"""

import argparse
from pathlib import Path
from typing import Iterable, Sequence

from loguru import logger

from aes import decrypt_statement
from db import SessionLocal
from orm import StatementUploads

# Make the client modules importable
import sys

CLIENT_SRC = Path(__file__).resolve().parents[2] / "client" / "src"
if not CLIENT_SRC.exists():
    raise ImportError("Unable to import ParseTrail client modules")
sys.path.insert(0, str(CLIENT_SRC))

try:
    from parsetrail.build_plugins import main as build_plugins  # noqa: E402
    from parsetrail.core.parse import ParseInput, parse_any  # noqa: E402
    from parsetrail.core.plugins import PluginManager  # noqa: E402
except Exception as e:  # pragma: no cover - optional dependency
    logger.warning(f"Unable to import ParseTrail client modules: {e}")
    raise


def _iter_ready_rows(
    ids: Sequence[int] | None = None, limit: int | None = None
) -> Iterable[StatementUploads]:
    with SessionLocal() as session:
        q = session.query(StatementUploads).filter(
            StatementUploads.plugin_status == "ready"
        )
        if ids:
            q = q.filter(StatementUploads.id.in_(ids))
        if limit:
            q = q.limit(limit)
        for row in q.order_by(StatementUploads.id.asc()):
            yield row


def _parse_row(row: StatementUploads, plugin_manager: PluginManager):
    plaintext, metadata = decrypt_statement(row)
    fname = metadata.get("filename") or metadata.get("file_name") or row.file_name
    suffix = Path(fname).suffix or ".bin"
    parse_input = ParseInput(name=fname, suffix=suffix.lower(), data=plaintext)
    statement = parse_any(SessionLocal, plugin_manager, parse_input, hard_fail=False)
    return statement


def run(ids: Sequence[int] | None = None, limit: int | None = None) -> int:
    build_plugins()
    plugin_manager = PluginManager()
    plugin_manager.load_plugins()

    failures: list[tuple[int, str]] = []
    total = 0

    for row in _iter_ready_rows(ids, limit):
        total += 1
        try:
            _parse_row(row, plugin_manager)
            logger.success(f"Parsed id={row.id} file={row.file_name}")
        except Exception as e:
            err = str(e)
            failures.append((row.id, err))
            logger.error(f"Failed id={row.id} file={row.file_name}: {err}")

    logger.info(f"Processed {total} statements; {len(failures)} failures.")
    if failures:
        for sid, err in failures:
            logger.error(f"[FAIL] id={sid}: {err}")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Batch test parsing for ready statements."
    )
    parser.add_argument(
        "--ids", nargs="*", type=int, help="Optional specific statement IDs to run."
    )
    parser.add_argument(
        "--limit", type=int, help="Optional limit on number of statements."
    )
    args = parser.parse_args()
    exit_code = run(ids=args.ids, limit=args.limit)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

"""Report encrypted statement storage drift and optionally quarantine orphans."""

import argparse
from pathlib import Path

from app.api.routes.statements import STATEMENTS_DIR
from app.core.db import engine
from app.core.statement_reconciliation import compare_statement_storage, quarantine_orphan_files
from sqlalchemy import text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quarantine-orphans",
        type=Path,
        help="recovery directory for encrypted files that have no database row",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the requested quarantine; without this flag the command is read-only",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.apply and args.quarantine_orphans is None:
        raise SystemExit("--apply requires --quarantine-orphans")

    with engine.connect() as connection:
        registered = set(connection.execute(text("SELECT file_name FROM statement_uploads")).scalars())
    report = compare_statement_storage(STATEMENTS_DIR, registered)

    print(f"Encrypted orphan files: {len(report.orphan_files)}")
    for name in report.orphan_files:
        print(f"  orphan file: {name}")
    print(f"Rows with missing encrypted files: {len(report.missing_files)}")
    for name in report.missing_files:
        print(f"  missing file: {name}")

    if args.quarantine_orphans is not None:
        if args.apply:
            quarantine_orphan_files(
                STATEMENTS_DIR,
                args.quarantine_orphans,
                report.orphan_files,
            )
            print(f"Quarantined {len(report.orphan_files)} encrypted orphan file(s)")
        else:
            print("Dry run only; add --apply to quarantine orphan files")
    return 0 if report.consistent else 1


if __name__ == "__main__":
    raise SystemExit(main())

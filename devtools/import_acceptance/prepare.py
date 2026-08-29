"""Prepare a disposable copy of a real client database for import acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MARKER_FILENAME = "acceptance-run.json"


class AcceptancePreparationError(RuntimeError):
    """The requested acceptance run cannot be prepared safely."""


def _digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = ("Statements", "Transactions", "StatementTransactions")
    return {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}


def _backup_database(source: Path, destination: Path) -> None:
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)


def prepare_run(
    *,
    source_database: Path,
    mohela_statement: Path,
    occu_statement: Path,
    output_root: Path,
    run_name: str | None = None,
) -> Path:
    source_database = source_database.expanduser().resolve()
    mohela_statement = mohela_statement.expanduser().resolve()
    occu_statement = occu_statement.expanduser().resolve()
    output_root = output_root.expanduser().resolve()

    for path, label in (
        (source_database, "source database"),
        (mohela_statement, "MOHELA statement"),
        (occu_statement, "OCCU statement"),
    ):
        if not path.is_file():
            raise AcceptancePreparationError(f"{label} does not exist: {path}")

    run_name = run_name or datetime.now(timezone.utc).strftime("import-acceptance-%Y%m%dT%H%M%SZ")
    if Path(run_name).name != run_name or run_name in {"", ".", ".."}:
        raise AcceptancePreparationError("run_name must be one plain directory name")
    run_dir = output_root / run_name
    if run_dir.exists():
        raise AcceptancePreparationError(f"acceptance run already exists: {run_dir}")

    database = run_dir / "acceptance.db"
    import_dir = run_dir / database.stem
    run_dir.mkdir(parents=True)
    import_dir.mkdir()
    for directory_name in ("SUCCESS", "FAIL", "DUPLICATE"):
        (import_dir / directory_name).mkdir()

    _backup_database(source_database, database)
    occu_hashes = {algorithm: _digest(occu_statement, algorithm) for algorithm in ("sha256", "md5")}
    mohela_sha256 = _digest(mohela_statement, "sha256")

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise AcceptancePreparationError(f"database copy failed integrity check: {integrity}")
        counts_before = _database_counts(connection)
        occu_rows = connection.execute(
            """
            SELECT StatementID, AccountID, Filename
            FROM Statements
            WHERE (ContentHashAlgorithm = 'sha256' AND ContentHash = ?)
               OR (ContentHashAlgorithm = 'md5' AND ContentHash = ?)
            ORDER BY StatementID
            """,
            (occu_hashes["sha256"], occu_hashes["md5"]),
        ).fetchall()
        filenames = {row[2] for row in occu_rows}
        account_ids = {row[1] for row in occu_rows}
        if len(occu_rows) != 2 or len(account_ids) != 2 or len(filenames) != 1:
            raise AcceptancePreparationError(
                "the OCCU fixture must resolve to exactly two statement rows, "
                "two accounts, and one canonical archive filename in the database copy"
            )
        connection.executemany(
            "DELETE FROM Statements WHERE StatementID = ?",
            [(row[0],) for row in occu_rows],
        )
        counts_after = _database_counts(connection)
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise AcceptancePreparationError("database copy has foreign-key violations after fixture reset")
        connection.commit()

    staged_mohela = import_dir / mohela_statement.name
    staged_occu = import_dir / occu_statement.name
    shutil.copy2(mohela_statement, staged_mohela)
    shutil.copy2(occu_statement, staged_occu)

    marker = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": str(database),
        "import_dir": str(import_dir),
        "source_database": str(source_database),
        "counts_before_occu_reset": counts_before,
        "counts_after_occu_reset": counts_after,
        "baseline_max_transaction_id": None,
        "mohela": {
            "filename": staged_mohela.name,
            "sha256": mohela_sha256,
        },
        "occu": {
            "filename": staged_occu.name,
            "sha256": occu_hashes["sha256"],
            "legacy_md5": occu_hashes["md5"],
            "canonical_archive_filename": next(iter(filenames)),
            "removed_statement_rows": len(occu_rows),
        },
    }
    with sqlite3.connect(database) as connection:
        marker["baseline_max_transaction_id"] = connection.execute(
            "SELECT COALESCE(MAX(TransactionID), 0) FROM Transactions"
        ).fetchone()[0]
    (run_dir / MARKER_FILENAME).write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_dir


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--mohela-statement", type=Path, required=True)
    parser.add_argument("--occu-statement", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-name")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        run_dir = prepare_run(
            source_database=args.source_database,
            mohela_statement=args.mohela_statement,
            occu_statement=args.occu_statement,
            output_root=args.output_root,
            run_name=args.run_name,
        )
    except (OSError, sqlite3.Error, AcceptancePreparationError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Prepared disposable import acceptance run: {run_dir}")
    print(f"Database: {run_dir / 'acceptance.db'}")
    print(f"Import directory: {run_dir / 'acceptance'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Audit database and file invariants for a disposable import-acceptance run."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

try:
    from .prepare import MARKER_FILENAME
except ImportError:  # Direct script execution adds this directory to sys.path.
    from prepare import MARKER_FILENAME


class AcceptanceAuditError(RuntimeError):
    """An acceptance invariant did not hold."""


@dataclass(frozen=True)
class StatementGroup:
    rows: int
    accounts: int
    filenames: tuple[str, ...]
    declared_transactions: int
    links: int
    baseline_links: int


def _statement_group(
    connection: sqlite3.Connection,
    *,
    sha256: str,
    legacy_md5: str = "",
    baseline_max_transaction_id: int,
) -> StatementGroup:
    rows = connection.execute(
        """
        SELECT StatementID, AccountID, Filename, TransactionCount
        FROM Statements
        WHERE (ContentHashAlgorithm = 'sha256' AND ContentHash = ?)
           OR (ContentHashAlgorithm = 'md5' AND ContentHash = ?)
        ORDER BY StatementID
        """,
        (sha256, legacy_md5),
    ).fetchall()
    statement_ids = [row[0] for row in rows]
    if statement_ids:
        placeholders = ",".join("?" for _ in statement_ids)
        links = connection.execute(
            f"SELECT COUNT(*) FROM StatementTransactions WHERE StatementID IN ({placeholders})",
            statement_ids,
        ).fetchone()[0]
        baseline_links = connection.execute(
            f"SELECT COUNT(*) FROM StatementTransactions WHERE StatementID IN ({placeholders}) AND TransactionID <= ?",
            [*statement_ids, baseline_max_transaction_id],
        ).fetchone()[0]
    else:
        links = 0
        baseline_links = 0
    return StatementGroup(
        rows=len(rows),
        accounts=len({row[1] for row in rows}),
        filenames=tuple(sorted({row[2] for row in rows})),
        declared_transactions=sum(row[3] for row in rows),
        links=links,
        baseline_links=baseline_links,
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceAuditError(message)


def audit_run(run_dir: Path, *, expected_state: str) -> dict[str, object]:
    run_dir = run_dir.expanduser().resolve()
    marker_path = run_dir / MARKER_FILENAME
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceAuditError(f"acceptance marker is missing or invalid: {marker_path}") from exc

    database = run_dir / "acceptance.db"
    _require(Path(marker.get("database", "")).resolve() == database, "marker database path does not match")
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        baseline = int(marker["baseline_max_transaction_id"])
        mohela = _statement_group(
            connection,
            sha256=marker["mohela"]["sha256"],
            baseline_max_transaction_id=baseline,
        )
        occu = _statement_group(
            connection,
            sha256=marker["occu"]["sha256"],
            legacy_md5=marker["occu"]["legacy_md5"],
            baseline_max_transaction_id=baseline,
        )
    finally:
        connection.close()

    _require(integrity == "ok", f"SQLite integrity check failed: {integrity}")
    _require(not foreign_key_violations, "SQLite foreign-key violations were found")
    _require(mohela.rows == 1, f"expected one MOHELA statement row, found {mohela.rows}")
    _require(mohela.accounts == 1, "MOHELA statement did not resolve to exactly one account")
    _require(mohela.links == mohela.declared_transactions, "MOHELA statement/link counts disagree")
    _require(mohela.baseline_links > 0, "MOHELA import did not reuse any baseline overlapping transactions")
    _require(occu.rows == 2, f"expected two OCCU statement rows, found {occu.rows}")
    _require(occu.accounts == 2, "OCCU statement did not resolve to two distinct accounts")
    _require(len(occu.filenames) == 1, "OCCU rows do not share one canonical archive filename")
    _require(occu.links == occu.declared_transactions, "OCCU statement/link counts disagree")

    import_dir = Path(marker["import_dir"])
    mohela_source = import_dir / marker["mohela"]["filename"]
    occu_source = import_dir / marker["occu"]["filename"]
    mohela_archive = import_dir / "SUCCESS" / mohela.filenames[0]
    occu_archive = import_dir / "SUCCESS" / occu.filenames[0]
    _require(not mohela_source.exists(), "MOHELA source still exists in the import root")
    _require(mohela_archive.is_file(), "MOHELA canonical archive is missing")
    if expected_state == "pending":
        _require(occu_source.is_file(), "pending OCCU source is not recoverable in the import root")
        _require(not occu_archive.exists(), "pending OCCU file unexpectedly exists in SUCCESS")
    else:
        _require(not occu_source.exists(), "completed OCCU source still exists in the import root")
        _require(occu_archive.is_file(), "completed OCCU canonical archive is missing")

    return {
        "state": expected_state,
        "integrity": integrity,
        "foreign_key_violations": len(foreign_key_violations),
        "mohela": {
            "statement_rows": mohela.rows,
            "transaction_links": mohela.links,
            "overlapping_baseline_links": mohela.baseline_links,
            "archive": mohela.filenames[0],
        },
        "occu": {
            "statement_rows": occu.rows,
            "distinct_accounts": occu.accounts,
            "transaction_links": occu.links,
            "archive": occu.filenames[0],
            "source_pending": occu_source.exists(),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--expect", choices=("pending", "complete"), required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = audit_run(args.run_dir, expected_state=args.expect)
    except (AcceptanceAuditError, KeyError, OSError, sqlite3.Error) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print("PASS: import acceptance invariants hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

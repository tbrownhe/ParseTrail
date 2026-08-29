from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from devtools.import_acceptance.audit import audit_run  # noqa: E402
from devtools.import_acceptance.prepare import prepare_run  # noqa: E402


def _fixture_database(path: Path, occu_payload: bytes) -> None:
    digest = hashlib.sha256(occu_payload).hexdigest()
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE Statements (
                StatementID INTEGER PRIMARY KEY,
                AccountID INTEGER NOT NULL,
                Filename TEXT NOT NULL,
                TransactionCount INTEGER NOT NULL,
                ContentHashAlgorithm TEXT NOT NULL,
                ContentHash TEXT NOT NULL
            );
            CREATE TABLE Transactions (TransactionID INTEGER PRIMARY KEY);
            CREATE TABLE StatementTransactions (
                StatementID INTEGER NOT NULL REFERENCES Statements(StatementID) ON DELETE CASCADE,
                TransactionID INTEGER NOT NULL REFERENCES Transactions(TransactionID) ON DELETE CASCADE,
                PRIMARY KEY (StatementID, TransactionID)
            );
            INSERT INTO Transactions VALUES (40);
            """
        )
        connection.executemany(
            "INSERT INTO Statements VALUES (?, ?, ?, 1, 'sha256', ?)",
            (
                (10, 1, "canonical.pdf", digest),
                (11, 2, "canonical.pdf", digest),
            ),
        )
        connection.executemany(
            "INSERT INTO StatementTransactions VALUES (?, 40)",
            ((10,), (11,)),
        )


def test_prepares_isolated_copy_and_resets_two_account_fixture(tmp_path: Path) -> None:
    source_database = tmp_path / "source.db"
    occu_statement = tmp_path / "OCCU.pdf"
    mohela_statement = tmp_path / "MOHELA.csv"
    occu_statement.write_bytes(b"two account statement")
    mohela_statement.write_bytes(b"overlapping life of loan statement")
    _fixture_database(source_database, occu_statement.read_bytes())

    run_dir = prepare_run(
        source_database=source_database,
        mohela_statement=mohela_statement,
        occu_statement=occu_statement,
        output_root=tmp_path / "runs",
        run_name="acceptance-test",
    )

    database = run_dir / "acceptance.db"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Statements").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM Transactions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM StatementTransactions").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    assert source_database.is_file()
    assert (run_dir / "acceptance" / occu_statement.name).read_bytes() == occu_statement.read_bytes()
    assert (run_dir / "acceptance" / mohela_statement.name).read_bytes() == mohela_statement.read_bytes()
    marker = json.loads((run_dir / "acceptance-run.json").read_text(encoding="utf-8"))
    assert marker["database"] == str(database.resolve())
    assert marker["occu"]["removed_statement_rows"] == 2
    assert marker["baseline_max_transaction_id"] == 40


def test_audits_pending_and_completed_recovery_states(tmp_path: Path) -> None:
    source_database = tmp_path / "source.db"
    occu_statement = tmp_path / "OCCU.pdf"
    mohela_statement = tmp_path / "MOHELA.csv"
    occu_statement.write_bytes(b"two account statement")
    mohela_statement.write_bytes(b"overlapping life of loan statement")
    _fixture_database(source_database, occu_statement.read_bytes())
    run_dir = prepare_run(
        source_database=source_database,
        mohela_statement=mohela_statement,
        occu_statement=occu_statement,
        output_root=tmp_path / "runs",
        run_name="acceptance-test",
    )
    marker = json.loads((run_dir / "acceptance-run.json").read_text(encoding="utf-8"))
    database = run_dir / "acceptance.db"
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO Statements VALUES (?, ?, ?, ?, ?, ?)",
            (
                (12, 3, "MOHELA-canonical.csv", 1, "sha256", marker["mohela"]["sha256"]),
                (13, 1, "OCCU-canonical.pdf", 1, "sha256", marker["occu"]["sha256"]),
                (14, 2, "OCCU-canonical.pdf", 1, "sha256", marker["occu"]["sha256"]),
            ),
        )
        connection.executemany(
            "INSERT INTO StatementTransactions VALUES (?, 40)",
            ((12,), (13,), (14,)),
        )

    import_dir = run_dir / "acceptance"
    (import_dir / mohela_statement.name).replace(import_dir / "SUCCESS" / "MOHELA-canonical.csv")
    pending = audit_run(run_dir, expected_state="pending")
    assert pending["mohela"]["overlapping_baseline_links"] == 1
    assert pending["occu"]["source_pending"] is True

    (import_dir / occu_statement.name).replace(import_dir / "SUCCESS" / "OCCU-canonical.pdf")
    complete = audit_run(run_dir, expected_state="complete")
    assert complete["occu"]["statement_rows"] == 2
    assert complete["occu"]["distinct_accounts"] == 2
    assert complete["occu"]["source_pending"] is False

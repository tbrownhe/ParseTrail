import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "devtools" / "ledger_audit" / "audit.py"
spec = importlib.util.spec_from_file_location("ledger_audit", TOOL)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source #1.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE alembic_version(version_num TEXT);
            INSERT INTO alembic_version VALUES ('synthetic');
            CREATE TABLE AccountTypes(AccountTypeID INTEGER, AssetType TEXT);
            INSERT INTO AccountTypes VALUES (1, 'Asset'), (2, 'Debt');
            CREATE TABLE Accounts(AccountID INTEGER, CurrencyCode TEXT, AccountTypeID INTEGER);
            INSERT INTO Accounts VALUES (1, 'USD', 1), (2, 'USD', 2), (3, 'USD', 1);
            CREATE TABLE Categories(CategoryID INTEGER, Type TEXT);
            INSERT INTO Categories VALUES (1, 'Transfer'), (2, 'Expense'), (3, 'Income');
            CREATE TABLE Transactions(TransactionID INTEGER, AccountID INTEGER, PostingDate TEXT,
                AmountMinor INTEGER, BalanceMinor INTEGER, CurrencyCode TEXT,
                CategoryID INTEGER, Verified INTEGER, Description TEXT);
            CREATE TABLE Statements(StatementID INTEGER, AccountID INTEGER, StartDate TEXT,
                EndDate TEXT, StartBalanceMinor INTEGER, EndBalanceMinor INTEGER,
                CurrencyCode TEXT, TransactionCount INTEGER);
            CREATE TABLE StatementTransactions(StatementID INTEGER, TransactionID INTEGER, StatementRow INTEGER);
            INSERT INTO Transactions VALUES
                (1,1,'2026-08-31',-1000,0,'USD',1,1,'PRIVATE SENTINEL'),
                (2,2,'2026-09-02',1000,0,'USD',1,1,'PRIVATE SENTINEL'),
                (3,1,'2026-08-02',-2500,0,'USD',1,0,'PRIVATE SENTINEL'),
                (4,2,'2026-08-02',2500,0,'USD',3,0,'PRIVATE SENTINEL'),
                (5,2,'2026-08-03',2500,0,'USD',NULL,0,'PRIVATE SENTINEL'),
                (6,1,'2026-08-02',-9900,0,'USD',1,1,'PRIVATE SENTINEL'),
                (7,1,'2026-08-02',-7000,0,'USD',2,1,'PRIVATE SENTINEL'),
                (8,1,'2026-08-01',5000,0,'USD',3,1,'PRIVATE SENTINEL');
            INSERT INTO Statements VALUES
                (1,1,'2026-08-01','2026-08-31',0,4000,'USD',2),
                (2,2,'2026-09-01','2026-09-30',-1000,0,'USD',1),
                (3,1,'2026-09-01','2026-09-30',4000,4000,'USD',0),
                (4,1,'2026-08-01','2026-08-31',0,4000,'USD',2);
            INSERT INTO StatementTransactions VALUES
                (1,1,1),(1,8,2),(2,2,1),(4,1,1),(4,8,2);
        """)
    return path


def inspect(source, **kwargs):
    connection = audit.read_only(source)
    try:
        return audit.audit_connection(connection, **kwargs)
    finally:
        connection.close()


def test_balanced_statements_overlap_empty_accounts_and_candidate_ambiguity(source):
    report = inspect(source)
    summary = report["summary"]
    assert summary["integrity_ok"] is True
    assert summary["statement_balance_exception_count"] == 0
    assert summary["statement_count_exception_count"] == 0
    assert summary["multiply_observed_transaction_count"] == 2
    assert summary["accounts_without_statements"] == 1
    assert summary["unlinked_transaction_count"] == 5
    assert summary["transfer_reciprocal_unique_candidate_count"] == 2
    assert summary["transfer_multiple_candidates_count"] == 1
    assert summary["transfer_no_candidate_count"] == 1
    assert "PRIVATE SENTINEL" not in json.dumps(report)
    assert "confirmed" in report["limitations"][0]


def test_candidate_window_different_currency_same_account_and_zero_do_not_match(source):
    assert inspect(source, window_days=0)["summary"]["transfer_no_candidate_count"] == 3
    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE Transactions SET CurrencyCode='EUR' WHERE TransactionID=2")
        connection.execute("UPDATE Transactions SET AccountID=1 WHERE TransactionID IN (4,5)")
        connection.execute("UPDATE Transactions SET AmountMinor=0 WHERE TransactionID=6")
    report = inspect(source)
    assert report["summary"]["transfer_no_candidate_count"] == 4
    assert report["summary"]["account_currency_mismatch_count"] == 1
    with pytest.raises(ValueError):
        inspect(source, window_days=32)


def test_source_link_balance_count_and_period_exceptions_remain_distinct(source):
    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE Statements SET EndBalanceMinor=4001 WHERE StatementID=1")
        connection.execute("UPDATE Statements SET TransactionCount=9 WHERE StatementID=2")
        connection.execute("INSERT INTO StatementTransactions VALUES (2,8,2)")
        connection.execute("UPDATE Transactions SET Verified=1 WHERE TransactionID=5")
    report = inspect(source)
    summary = report["summary"]
    assert summary["statement_balance_exception_count"] == 2
    assert summary["statement_count_exception_count"] == 1
    assert summary["invalid_source_link_count"] == 1
    assert summary["statement_out_of_period_count"] == 1
    assert summary["verified_without_category_count"] == 1
    assert report["private_findings"]["statement_balance_exceptions"][0] == {
        "statement_id": 1,
        "difference_minor": 1,
    }


def test_adjacent_balance_breaks_and_coverage_gaps_are_not_silently_repaired(source):
    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE Statements SET StartBalanceMinor=5000 WHERE StatementID=3")
        connection.execute("INSERT INTO Statements VALUES (5,1,'2026-11-01','2026-11-30',4000,4000,'USD',0)")
    summary = inspect(source)["summary"]
    assert summary["adjacent_statement_balance_exception_count"] == 1
    assert summary["accounts_with_internal_gaps"] == 1


def test_snapshot_is_independent_read_only_and_output_cannot_overwrite_source(source, tmp_path):
    original = source.read_bytes()
    output = tmp_path / "private"
    report = audit.create_audit(source, output)
    assert source.read_bytes() == original
    assert report["snapshot"]["source_files_unchanged_during_run"]
    assert report["snapshot"]["audit_snapshot_unchanged"]
    assert json.loads((output / "audit.json").read_text())["summary"] == report["summary"]
    with pytest.raises(FileExistsError):
        audit.create_audit(source, output)
    with pytest.raises(FileExistsError):
        audit.create_audit(source, source)
    connection = audit.read_only(source)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM Transactions")
    finally:
        connection.close()
    with sqlite3.connect(output / "snapshot.db") as connection:
        connection.execute("DELETE FROM Transactions")
    assert source.read_bytes() == original


def test_online_snapshot_includes_committed_wal_rows(source, tmp_path):
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO Accounts VALUES (4,'USD',1)")
        connection.commit()
        report = audit.create_audit(source, tmp_path / "wal-copy")
        assert report["summary"]["account_count"] == 4
        assert report["snapshot"]["source_files_unchanged_during_run"]
    finally:
        connection.close()


def test_empty_history_is_a_valid_audit_not_a_confirmed_ledger(source):
    with sqlite3.connect(source) as connection:
        connection.execute("DELETE FROM StatementTransactions")
        connection.execute("DELETE FROM Statements")
        connection.execute("DELETE FROM Transactions")
    summary = inspect(source)["summary"]
    assert summary["transaction_count"] == 0
    assert summary["statement_count"] == 0
    assert summary["accounts_without_statements"] == 3
    assert summary["transfer_reciprocal_unique_candidate_count"] == 0


def test_manual_closure_marker_is_only_a_hint_and_does_not_expose_descriptions(source):
    with sqlite3.connect(source) as connection:
        connection.execute(
            "UPDATE Transactions SET Description='Manual Entry: Account Closed Manually' WHERE TransactionID=6"
        )
        connection.execute("UPDATE Transactions SET Description='Manual Entry: PRIVATE ASSET' WHERE TransactionID=7")
    report = inspect(source)
    assert report["summary"]["unlinked_origin_markers"] == {
        "manual_account_closure": 1,
        "manual_entry": 1,
        "unknown_origin": 3,
    }
    assert report["summary"]["unlinked_transaction_count"] == 5
    assert "PRIVATE ASSET" not in json.dumps(report)
    assert report["summary"]["transfer_no_candidate_count"] == 1

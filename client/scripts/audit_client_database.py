"""Emit a redacted structural/data-quality audit for a ParseTrail SQLite database."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

MONEY_COLUMNS = {
    "Categories": ("Budget", "BudgetMinor"),
    "Statements": ("StartBalance", "EndBalance", "StartBalanceMinor", "EndBalanceMinor"),
    "Transactions": ("Amount", "Balance", "AmountMinor", "BalanceMinor"),
}
DATE_COLUMNS = {
    "Statements": ("ImportDate", "StartDate", "EndDate"),
    "Transactions": ("Date", "TransactionDate", "PostingDate"),
}


def _database_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]


def _table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def _invalid_dates(connection: sqlite3.Connection, table: str, column: str) -> int:
    invalid = 0
    for (value,) in connection.execute(f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'):
        try:
            date.fromisoformat(str(value))
        except (TypeError, ValueError):
            invalid += 1
    return invalid


def _non_minor_unit_values(connection: sqlite3.Connection, table: str, column: str) -> int:
    invalid = 0
    for (value,) in connection.execute(f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'):
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            invalid += 1
            continue
        if amount != amount.quantize(Decimal("0.01")):
            invalid += 1
    return invalid


def audit_database(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    try:
        tables = _table_names(connection)
        table_set = set(tables)
        columns: dict[str, dict[str, str]] = {}
        row_counts: dict[str, int] = {}
        null_counts: dict[str, dict[str, int]] = {}

        for table in tables:
            table_columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            columns[table] = {row[1]: row[2] for row in table_columns}
            row_counts[table] = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            null_counts[table] = {
                row[1]: connection.execute(f'SELECT count(*) FROM "{table}" WHERE "{row[1]}" IS NULL').fetchone()[0]
                for row in table_columns
            }

        invalid_dates = {
            f"{table}.{column}": _invalid_dates(connection, table, column)
            for table, date_columns in DATE_COLUMNS.items()
            if table in table_set
            for column in date_columns
            if column in columns[table]
        }
        non_minor_unit_values = {
            f"{table}.{column}": _non_minor_unit_values(connection, table, column)
            for table, money_columns in MONEY_COLUMNS.items()
            if table in table_set
            for column in money_columns
            if column in columns[table]
        }

        duplicate_transaction_hashes = 0
        transactions_without_statements = 0
        statement_count_mismatches = 0
        if "Transactions" in table_set:
            transaction_hash_column = "Fingerprint" if "Fingerprint" in columns["Transactions"] else "MD5"
            if transaction_hash_column in columns["Transactions"]:
                duplicate_transaction_hashes = connection.execute(
                    "SELECT count(*) FROM ("
                    f'SELECT "{transaction_hash_column}" FROM "Transactions" '
                    f'WHERE "{transaction_hash_column}" IS NOT NULL '
                    f'GROUP BY "{transaction_hash_column}" HAVING count(*) > 1)'
                ).fetchone()[0]
            if "StatementID" in columns["Transactions"]:
                transactions_without_statements = connection.execute(
                    'SELECT count(*) FROM "Transactions" WHERE "StatementID" IS NULL'
                ).fetchone()[0]
                if "Statements" in table_set and "TransactionCount" in columns["Statements"]:
                    statement_count_mismatches = connection.execute(
                        'SELECT count(*) FROM "Statements" AS s '
                        'LEFT JOIN (SELECT CAST("StatementID" AS INTEGER) AS sid, count(*) AS actual '
                        'FROM "Transactions" WHERE "StatementID" IS NOT NULL GROUP BY CAST("StatementID" AS INTEGER)) '
                        'AS t ON t.sid = s."StatementID" '
                        'WHERE s."TransactionCount" != coalesce(t.actual, 0)'
                    ).fetchone()[0]
            elif "StatementTransactions" in table_set:
                transactions_without_statements = connection.execute(
                    'SELECT count(*) FROM "Transactions" AS t '
                    'LEFT JOIN "StatementTransactions" AS st ON st."TransactionID" = t."TransactionID" '
                    'WHERE st."TransactionID" IS NULL'
                ).fetchone()[0]
                statement_count_mismatches = connection.execute(
                    'SELECT count(*) FROM "Statements" AS s '
                    'LEFT JOIN (SELECT "StatementID", count(*) AS actual FROM "StatementTransactions" '
                    'GROUP BY "StatementID") AS st ON st."StatementID" = s."StatementID" '
                    'WHERE s."TransactionCount" != coalesce(st.actual, 0)'
                ).fetchone()[0]

        duplicate_plugin_versions = 0
        if "Plugins" in table_set:
            duplicate_plugin_versions = connection.execute(
                "SELECT count(*) FROM ("
                'SELECT "PluginName", "Version" FROM "Plugins" '
                'GROUP BY "PluginName", "Version" HAVING count(*) > 1)'
            ).fetchone()[0]

        duplicate_statement_account_hashes = 0
        if "Statements" in table_set:
            statement_hash_column = "ContentHash" if "ContentHash" in columns["Statements"] else "MD5"
            duplicate_statement_account_hashes = connection.execute(
                "SELECT count(*) FROM ("
                f'SELECT "AccountID", "{statement_hash_column}" FROM "Statements" '
                f'GROUP BY "AccountID", "{statement_hash_column}" HAVING count(*) > 1)'
            ).fetchone()[0]

        revision = None
        if "alembic_version" in table_set:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = row[0] if row else None

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())

        return {
            "database_id": _database_id(resolved),
            "size_bytes": resolved.stat().st_size,
            "revision": revision,
            "integrity": integrity,
            "foreign_key_violations": foreign_key_violations,
            "row_counts": row_counts,
            "columns": columns,
            "null_counts": null_counts,
            "invalid_dates": invalid_dates,
            "non_minor_unit_values": non_minor_unit_values,
            "duplicate_transaction_hash_groups": duplicate_transaction_hashes,
            "duplicate_plugin_version_groups": duplicate_plugin_versions,
            "duplicate_statement_account_hash_groups": duplicate_statement_account_hashes,
            "transactions_without_statements": transactions_without_statements,
            "statement_count_mismatches": statement_count_mismatches,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_database(args.database), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

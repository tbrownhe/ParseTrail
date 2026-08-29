"""Store exact money, typed dates, and truthful statement membership.

Revision ID: 0003_precise_financial_schema
Revises: e0ecdd6abcc6
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from parsetrail.core.fingerprint import TRANSACTION_FINGERPRINT_VERSION, transaction_fingerprint
from parsetrail.core.money import DEFAULT_CURRENCY, to_minor_units

revision = "0003_precise_financial_schema"
down_revision = "e0ecdd6abcc6"
branch_labels = None
depends_on = None

LEGACY_TABLES = (
    "AccountTypes",
    "Accounts",
    "AccountNumbers",
    "Categories",
    "Plugins",
    "Statements",
    "Transactions",
)


def _rows(table: str) -> list[dict]:
    bind = op.get_bind()
    result = bind.execute(sa.text(f'SELECT * FROM "{table}"'))
    return [dict(row) for row in result.mappings()]


def _legacy_money(value, label: str) -> Decimal:
    if value is None:
        raise RuntimeError(f"Cannot migrate NULL money value at {label}.")
    amount = Decimal(str(value))
    try:
        to_minor_units(amount)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Cannot migrate non-cent money value at {label}.") from exc
    return amount


def _legacy_date(value, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Cannot migrate invalid date at {label}.") from exc


def _required(row: dict, key: str, label: str):
    value = row.get(key)
    if value is None:
        raise RuntimeError(f"Cannot migrate NULL {key} at {label}.")
    return value


def _validate_unique(rows: list[dict], keys: tuple[str, ...], label: str) -> None:
    values = [tuple(row.get(key) for key in keys) for row in rows]
    duplicates = [value for value, count in Counter(values).items() if count > 1]
    if duplicates:
        raise RuntimeError(f"Cannot migrate duplicate {label}; resolve {len(duplicates)} duplicate group(s) first.")


def _insert(table, rows: list[dict]) -> None:
    if rows:
        op.get_bind().execute(table.insert(), rows)


def _create_tables():
    currencies = op.create_table(
        "Currencies",
        sa.Column("CurrencyCode", sa.String(3), primary_key=True),
        sa.Column("MinorUnit", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(CurrencyCode) = 3 AND CurrencyCode = upper(CurrencyCode)",
            name="ck_currency_code",
        ),
        sa.CheckConstraint("MinorUnit BETWEEN 0 AND 6", name="ck_currency_minor_unit"),
    )
    account_types = op.create_table(
        "AccountTypes",
        sa.Column("AccountTypeID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("AccountType", sa.String(), nullable=False, unique=True),
        sa.Column("AssetType", sa.String(), nullable=False),
        sqlite_autoincrement=True,
    )
    accounts = op.create_table(
        "Accounts",
        sa.Column("AccountID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("AccountName", sa.String(), nullable=False, unique=True),
        sa.Column("AccountTypeID", sa.Integer(), nullable=False),
        sa.Column("CurrencyCode", sa.String(3), nullable=False, server_default=DEFAULT_CURRENCY),
        sa.Column("Company", sa.String(), nullable=False, server_default=""),
        sa.Column("Description", sa.Text(), nullable=False, server_default=""),
        sa.Column("AppreciationRate", sa.Numeric(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(
            ["AccountTypeID"],
            ["AccountTypes.AccountTypeID"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["CurrencyCode"],
            ["Currencies.CurrencyCode"],
            ondelete="RESTRICT",
        ),
        sqlite_autoincrement=True,
    )
    account_numbers = op.create_table(
        "AccountNumbers",
        sa.Column("AccountNumberID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("AccountID", sa.Integer(), nullable=False),
        sa.Column("AccountNumber", sa.String(), nullable=False, unique=True),
        sa.ForeignKeyConstraint(
            ["AccountID"],
            ["Accounts.AccountID"],
            ondelete="CASCADE",
        ),
        sqlite_autoincrement=True,
    )
    categories = op.create_table(
        "Categories",
        sa.Column("CategoryID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("Name", sa.String(), nullable=False, unique=True),
        sa.Column("Type", sa.String(), nullable=False),
        sa.Column("Active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("ParentID", sa.Integer(), nullable=True),
        sa.Column("BudgetMinor", sa.Integer(), nullable=True),
        sa.Column("BudgetCurrencyCode", sa.String(3), nullable=False, server_default=DEFAULT_CURRENCY),
        sa.CheckConstraint("Type IN ('Expense','Income','Transfer')", name="ck_categories_type_valid"),
        sa.ForeignKeyConstraint(
            ["ParentID"],
            ["Categories.CategoryID"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["BudgetCurrencyCode"],
            ["Currencies.CurrencyCode"],
            ondelete="RESTRICT",
        ),
        sqlite_autoincrement=True,
    )
    plugins = op.create_table(
        "Plugins",
        sa.Column("PluginID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("PluginName", sa.String(), nullable=False),
        sa.Column("Version", sa.String(), nullable=False),
        sa.Column("Suffix", sa.String(), nullable=False),
        sa.Column("Company", sa.String(), nullable=False),
        sa.Column("StatementType", sa.String(), nullable=False),
        sa.UniqueConstraint("PluginName", "Version", name="uq_plugins_name_version"),
        sqlite_autoincrement=True,
    )
    statements = op.create_table(
        "Statements",
        sa.Column("StatementID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("PluginID", sa.Integer(), nullable=False),
        sa.Column("AccountID", sa.Integer(), nullable=False),
        sa.Column("ImportedAt", sa.DateTime(), nullable=False),
        sa.Column("StartDate", sa.Date(), nullable=False),
        sa.Column("EndDate", sa.Date(), nullable=False),
        sa.Column("StartBalanceMinor", sa.Integer(), nullable=False),
        sa.Column("EndBalanceMinor", sa.Integer(), nullable=False),
        sa.Column("CurrencyCode", sa.String(3), nullable=False, server_default=DEFAULT_CURRENCY),
        sa.Column("TransactionCount", sa.Integer(), nullable=False),
        sa.Column("Filename", sa.String(), nullable=False),
        sa.Column("ContentHashAlgorithm", sa.String(8), nullable=False),
        sa.Column("ContentHash", sa.String(64), nullable=False),
        sa.CheckConstraint("EndDate >= StartDate", name="ck_statements_date_order"),
        sa.CheckConstraint("TransactionCount >= 0", name="ck_statements_transaction_count"),
        sa.CheckConstraint(
            "(ContentHashAlgorithm = 'md5' AND length(ContentHash) = 32) OR "
            "(ContentHashAlgorithm = 'sha256' AND length(ContentHash) = 64)",
            name="ck_statements_content_hash",
        ),
        sa.ForeignKeyConstraint(["PluginID"], ["Plugins.PluginID"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["AccountID"], ["Accounts.AccountID"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["CurrencyCode"], ["Currencies.CurrencyCode"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "AccountID",
            "ContentHashAlgorithm",
            "ContentHash",
            name="uq_statements_account_content_hash",
        ),
        sqlite_autoincrement=True,
    )
    transactions = op.create_table(
        "Transactions",
        sa.Column("TransactionID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("AccountID", sa.Integer(), nullable=False),
        sa.Column("TransactionDate", sa.Date(), nullable=True),
        sa.Column("PostingDate", sa.Date(), nullable=False),
        sa.Column("AmountMinor", sa.Integer(), nullable=False),
        sa.Column("BalanceMinor", sa.Integer(), nullable=False),
        sa.Column("CurrencyCode", sa.String(3), nullable=False, server_default=DEFAULT_CURRENCY),
        sa.Column("Description", sa.Text(), nullable=False),
        sa.Column("Fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("FingerprintVersion", sa.Integer(), nullable=False),
        sa.Column("CategoryID", sa.Integer(), nullable=True),
        sa.Column("Verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("ConfidenceScore", sa.Numeric(), nullable=True),
        sa.CheckConstraint("length(Fingerprint) = 64", name="ck_transactions_fingerprint_length"),
        sa.CheckConstraint("FingerprintVersion > 0", name="ck_transactions_fingerprint_version"),
        sa.ForeignKeyConstraint(["AccountID"], ["Accounts.AccountID"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["CurrencyCode"], ["Currencies.CurrencyCode"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["CategoryID"], ["Categories.CategoryID"], ondelete="SET NULL"),
        sqlite_autoincrement=True,
    )
    statement_transactions = op.create_table(
        "StatementTransactions",
        sa.Column("StatementID", sa.Integer(), primary_key=True),
        sa.Column("TransactionID", sa.Integer(), primary_key=True),
        sa.Column("StatementRow", sa.Integer(), nullable=False),
        sa.CheckConstraint("StatementRow > 0", name="ck_statement_transactions_row"),
        sa.ForeignKeyConstraint(["StatementID"], ["Statements.StatementID"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["TransactionID"], ["Transactions.TransactionID"], ondelete="CASCADE"),
        sa.UniqueConstraint("StatementID", "StatementRow", name="uq_statement_transactions_row"),
    )
    return {
        "Currencies": currencies,
        "AccountTypes": account_types,
        "Accounts": accounts,
        "AccountNumbers": account_numbers,
        "Categories": categories,
        "Plugins": plugins,
        "Statements": statements,
        "Transactions": transactions,
        "StatementTransactions": statement_transactions,
    }


def upgrade() -> None:
    legacy = {table: _rows(table) for table in LEGACY_TABLES}
    _validate_unique(legacy["Plugins"], ("PluginName", "Version"), "plugin name/version pairs")
    _validate_unique(legacy["Statements"], ("AccountID", "MD5"), "statement account/content hashes")

    account_ids = {row["AccountID"] for row in legacy["Accounts"]}
    statement_ids = {row["StatementID"] for row in legacy["Statements"]}
    for row in legacy["Transactions"]:
        transaction_id = row["TransactionID"]
        if row.get("AccountID") not in account_ids:
            raise RuntimeError(f"Cannot migrate transaction {transaction_id} with an invalid AccountID.")
        statement_id = row.get("StatementID")
        if statement_id is not None and int(statement_id) not in statement_ids:
            raise RuntimeError(f"Cannot migrate transaction {transaction_id} with an invalid StatementID.")

    # The migration connection has no ORM foreign-key hook, but make the rebuild
    # requirement explicit and restore enforcement validation before completion.
    op.execute("PRAGMA foreign_keys=OFF")
    for table in reversed(LEGACY_TABLES):
        op.rename_table(table, f"_legacy_{table}")

    tables = _create_tables()
    bind = op.get_bind()
    bind.execute(tables["Currencies"].insert(), [{"CurrencyCode": DEFAULT_CURRENCY, "MinorUnit": 2}])

    _insert(
        tables["AccountTypes"],
        [
            {
                "AccountTypeID": row["AccountTypeID"],
                "AccountType": _required(row, "AccountType", f"AccountTypes {row['AccountTypeID']}"),
                "AssetType": _required(row, "AssetType", f"AccountTypes {row['AccountTypeID']}"),
            }
            for row in legacy["AccountTypes"]
        ],
    )
    _insert(
        tables["Accounts"],
        [
            {
                "AccountID": row["AccountID"],
                "AccountName": _required(row, "AccountName", f"Accounts {row['AccountID']}"),
                "AccountTypeID": _required(row, "AccountTypeID", f"Accounts {row['AccountID']}"),
                "CurrencyCode": DEFAULT_CURRENCY,
                "Company": row.get("Company") or "",
                "Description": row.get("Description") or "",
                "AppreciationRate": Decimal(str(row.get("AppreciationRate") or 0)),
            }
            for row in legacy["Accounts"]
        ],
    )
    _insert(
        tables["AccountNumbers"],
        [
            {
                "AccountNumberID": row["AccountNumberID"],
                "AccountID": _required(row, "AccountID", f"AccountNumbers {row['AccountNumberID']}"),
                "AccountNumber": _required(row, "AccountNumber", f"AccountNumbers {row['AccountNumberID']}"),
            }
            for row in legacy["AccountNumbers"]
        ],
    )
    _insert(
        tables["Categories"],
        [
            {
                "CategoryID": row["CategoryID"],
                "Name": _required(row, "Name", f"Categories {row['CategoryID']}"),
                "Type": _required(row, "Type", f"Categories {row['CategoryID']}"),
                "Active": bool(row["Active"]),
                "ParentID": row.get("ParentID"),
                "BudgetMinor": (
                    None
                    if row.get("Budget") is None
                    else to_minor_units(_legacy_money(row["Budget"], f"Categories {row['CategoryID']}.Budget"))
                ),
                "BudgetCurrencyCode": DEFAULT_CURRENCY,
            }
            for row in legacy["Categories"]
        ],
    )
    _insert(
        tables["Plugins"],
        [
            {
                key: _required(row, key, f"Plugins {row['PluginID']}")
                for key in ("PluginID", "PluginName", "Version", "Suffix", "Company", "StatementType")
            }
            for row in legacy["Plugins"]
        ],
    )

    direct_counts = Counter(
        int(row["StatementID"]) for row in legacy["Transactions"] if row.get("StatementID") is not None
    )
    statement_rows = []
    for row in legacy["Statements"]:
        statement_id = row["StatementID"]
        imported_date = _legacy_date(row["ImportDate"], f"Statements {statement_id}.ImportDate")
        content_hash = str(_required(row, "MD5", f"Statements {statement_id}"))
        if len(content_hash) != 32:
            raise RuntimeError(f"Cannot migrate invalid legacy content hash at Statements {statement_id}.")
        statement_rows.append(
            {
                "StatementID": statement_id,
                "PluginID": _required(row, "PluginID", f"Statements {statement_id}"),
                "AccountID": _required(row, "AccountID", f"Statements {statement_id}"),
                "ImportedAt": datetime.combine(imported_date, datetime.min.time()),
                "StartDate": _legacy_date(row["StartDate"], f"Statements {statement_id}.StartDate"),
                "EndDate": _legacy_date(row["EndDate"], f"Statements {statement_id}.EndDate"),
                "StartBalanceMinor": to_minor_units(
                    _legacy_money(row["StartBalance"], f"Statements {statement_id}.StartBalance")
                ),
                "EndBalanceMinor": to_minor_units(
                    _legacy_money(row["EndBalance"], f"Statements {statement_id}.EndBalance")
                ),
                "CurrencyCode": DEFAULT_CURRENCY,
                "TransactionCount": direct_counts[statement_id],
                "Filename": _required(row, "Filename", f"Statements {statement_id}"),
                "ContentHashAlgorithm": "md5",
                "ContentHash": content_hash,
            }
        )
    _insert(tables["Statements"], statement_rows)

    fingerprints: set[str] = set()
    transaction_rows = []
    association_rows = []
    statement_row_numbers: defaultdict[int, int] = defaultdict(int)
    for row in sorted(legacy["Transactions"], key=lambda item: item["TransactionID"]):
        transaction_id = row["TransactionID"]
        account_id = int(_required(row, "AccountID", f"Transactions {transaction_id}"))
        posting_date = _legacy_date(row["Date"], f"Transactions {transaction_id}.Date")
        amount = _legacy_money(row["Amount"], f"Transactions {transaction_id}.Amount")
        balance = _legacy_money(row["Balance"], f"Transactions {transaction_id}.Balance")
        description = str(_required(row, "Description", f"Transactions {transaction_id}"))
        occurrence = 0
        while True:
            fingerprint = transaction_fingerprint(
                account_id=account_id,
                posting_date=posting_date,
                amount=amount,
                balance=balance,
                description=description,
                occurrence=occurrence,
            )
            if fingerprint not in fingerprints:
                fingerprints.add(fingerprint)
                break
            occurrence += 1
        transaction_rows.append(
            {
                "TransactionID": transaction_id,
                "AccountID": account_id,
                "TransactionDate": None,
                "PostingDate": posting_date,
                "AmountMinor": to_minor_units(amount),
                "BalanceMinor": to_minor_units(balance),
                "CurrencyCode": DEFAULT_CURRENCY,
                "Description": description,
                "Fingerprint": fingerprint,
                "FingerprintVersion": TRANSACTION_FINGERPRINT_VERSION,
                "CategoryID": row.get("CategoryID"),
                "Verified": bool(row.get("Verified")),
                "ConfidenceScore": row.get("ConfidenceScore"),
            }
        )
        if row.get("StatementID") is not None:
            statement_id = int(row["StatementID"])
            statement_row_numbers[statement_id] += 1
            association_rows.append(
                {
                    "StatementID": statement_id,
                    "TransactionID": transaction_id,
                    "StatementRow": statement_row_numbers[statement_id],
                }
            )

    _insert(tables["Transactions"], transaction_rows)
    _insert(tables["StatementTransactions"], association_rows)

    for table in reversed(LEGACY_TABLES):
        op.drop_table(f"_legacy_{table}")

    violations = bind.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    if violations:
        raise RuntimeError(f"Precise schema migration produced {len(violations)} foreign-key violation(s).")
    integrity = bind.execute(sa.text("PRAGMA integrity_check")).scalar_one()
    if integrity != "ok":
        raise RuntimeError(f"Precise schema migration failed SQLite integrity check: {integrity}")


def downgrade() -> None:
    raise RuntimeError(
        "The precise financial schema is not downgradable in place. Restore the automatic pre-migration backup instead."
    )

"""Fresh 2.0 SQLite profile for source evidence and authored account decisions.

This store has no reader or migration path for 1.x data. Source facts remain
immutable; imported observations start pending and unposted.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from parsetrail.core.ledger import (
    AccountKind,
    Allocation,
    JournalEntry,
    LedgerAccount,
    LedgerError,
    Observation,
    Posting,
    validate_entry,
)
from parsetrail.core.source_evidence import ActivityExportPayload, SourceEvidence, StatementPayload

APPLICATION_ID = 0x50543230  # PT20
SCHEMA_VERSION = 8
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_DEFINITION_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
TABLE_COLUMNS = {
    "Sources": (
        ("sha256", "TEXT", 0, 1),
        ("suffix", "TEXT", 1, 0),
        ("size", "INTEGER", 1, 0),
        ("content", "BLOB", 1, 0),
    ),
    "Definitions": (("sha256", "TEXT", 0, 1), ("size", "INTEGER", 1, 0), ("content", "BLOB", 1, 0)),
    "EvidenceSnapshots": (
        ("source_sha256", "TEXT", 0, 1),
        ("definition_sha256", "TEXT", 1, 0),
        ("size", "INTEGER", 1, 0),
        ("sha256", "TEXT", 1, 0),
        ("content", "BLOB", 1, 0),
    ),
    "SourceObservations": (
        ("row_id", "TEXT", 0, 1),
        ("source_sha256", "TEXT", 1, 0),
        ("source_account", "TEXT", 0, 0),
        ("source_account_form", "TEXT", 0, 0),
        ("row_role", "TEXT", 1, 0),
        ("date_role", "TEXT", 1, 0),
        ("observed_date", "TEXT", 1, 0),
        ("amount_minor", "INTEGER", 1, 0),
    ),
    "Accounts": (
        ("id", "TEXT", 0, 1),
        ("name", "TEXT", 1, 0),
        ("kind", "TEXT", 1, 0),
        ("currency", "TEXT", 1, 0),
        ("role", "TEXT", 1, 0),
        ("purpose", "TEXT", 1, 0),
        ("institution_key", "TEXT", 0, 0),
        ("full_account_number", "TEXT", 0, 0),
    ),
    "CategoryBudgetRates": (
        ("category_id", "TEXT", 1, 1),
        ("effective_month", "TEXT", 1, 2),
        ("amount_minor", "INTEGER", 0, 0),
    ),
    "FileAccountAssertions": (
        ("source_sha256", "TEXT", 0, 1),
        ("ledger_account_id", "TEXT", 1, 0),
    ),
    "RowAccountAssignments": (
        ("row_id", "TEXT", 0, 1),
        ("ledger_account_id", "TEXT", 1, 0),
    ),
    "SourceAccountBindings": (
        ("source_sha256", "TEXT", 1, 1),
        ("source_identity", "TEXT", 1, 2),
        ("source_identity_form", "TEXT", 1, 3),
        ("ledger_account_id", "TEXT", 1, 0),
    ),
    "JournalEntries": (
        ("key", "TEXT", 0, 1),
        ("payload", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "JournalAllocations": (
        ("entry_key", "TEXT", 1, 1),
        ("row_id", "TEXT", 1, 2),
        ("amount_minor", "INTEGER", 1, 0),
    ),
    "JournalCorrections": (
        ("original_key", "TEXT", 0, 1),
        ("reversal_key", "TEXT", 1, 0),
        ("replacement_key", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
}
FOREIGN_KEYS = {
    "Sources": (),
    "Definitions": (),
    "EvidenceSnapshots": (("definition_sha256", "Definitions", "sha256"), ("source_sha256", "Sources", "sha256")),
    "SourceObservations": (("source_sha256", "Sources", "sha256"),),
    "Accounts": (),
    "CategoryBudgetRates": (("category_id", "Accounts", "id"),),
    "FileAccountAssertions": (("ledger_account_id", "Accounts", "id"), ("source_sha256", "Sources", "sha256")),
    "RowAccountAssignments": (
        ("ledger_account_id", "Accounts", "id"),
        ("row_id", "SourceObservations", "row_id"),
    ),
    "SourceAccountBindings": (
        ("ledger_account_id", "Accounts", "id"),
        ("source_sha256", "Sources", "sha256"),
    ),
    "JournalEntries": (),
    "JournalAllocations": (("row_id", "SourceObservations", "row_id"), ("entry_key", "JournalEntries", "key")),
    "JournalCorrections": (
        ("replacement_key", "JournalEntries", "key"),
        ("reversal_key", "JournalEntries", "key"),
        ("original_key", "JournalEntries", "key"),
    ),
}

IMMUTABLE_TABLES = (
    "Sources",
    "Definitions",
    "EvidenceSnapshots",
    "SourceObservations",
    "JournalEntries",
    "JournalAllocations",
    "JournalCorrections",
)


class ProfileFormatError(ValueError):
    """A profile or saved snapshot is unsupported or damaged."""


@dataclass(frozen=True)
class SavedImport:
    source: bytes
    definition: bytes
    evidence: SourceEvidence
    suffix: Literal[".csv", ".pdf"]


@dataclass(frozen=True)
class FinancialAccount:
    id: str
    name: str
    kind: Literal["asset", "liability"]
    institution_key: str
    full_account_number: str | None = None


@dataclass(frozen=True)
class CategoryAccount:
    id: str
    name: str
    kind: Literal["expense", "income"]


@dataclass(frozen=True)
class CategoryBudgetRate:
    category_id: str
    effective_month: date
    amount_minor: int | None


@dataclass(frozen=True)
class CategoryBudgetTarget:
    category_id: str
    name: str
    kind: Literal["expense", "income"]
    effective_month: date | None
    amount_minor: int | None


@dataclass(frozen=True)
class AccountBinding:
    row_id: str
    ledger_account_id: str | None
    basis: Literal["row", "file", "source", "automatic"] | None


@dataclass(frozen=True)
class SourceAccountBinding:
    source_identity: str
    source_identity_form: Literal["full", "last_four", "opaque"]
    ledger_account_id: str | None


@dataclass(frozen=True)
class CashActivityReviewRow:
    row_id: str
    date: str | None
    description: str
    amount_minor: int | None
    financial_account: str | None
    status: str
    entry_key: str | None = None
    category_id: str | None = None


@dataclass(frozen=True)
class ReviewedCategoryTotal:
    category_id: str
    name: str
    amount_minor: int


@dataclass(frozen=True)
class ReviewedCategorySummary:
    start: date
    end: date
    kind: Literal["expense", "income"]
    categories: tuple[ReviewedCategoryTotal, ...]
    total_minor: int
    activity_rows_without_full_allocation: int
    sources_with_incomplete_activity: int
    excluded_unreviewed_entries: int


@dataclass(frozen=True)
class MonthlyBudgetRow:
    category_id: str
    name: str
    target_minor: int | None
    target_effective_month: date | None
    reviewed_spending_minor: int
    remaining_minor: int | None


@dataclass(frozen=True)
class MonthlyBudgetSummary:
    month: date
    categories: tuple[MonthlyBudgetRow, ...]
    total_target_minor: int | None
    total_reviewed_spending_minor: int
    activity_rows_without_full_allocation: int
    sources_with_incomplete_activity: int
    excluded_unreviewed_expense_entries: int


@dataclass(frozen=True)
class FinancialJournalMovement:
    account_id: str
    name: str
    kind: Literal["asset", "liability"]
    nonopening_change_minor: int
    opening_minor: int | None


@dataclass(frozen=True)
class FinancialJournalSummary:
    start: date
    end: date
    accounts: tuple[FinancialJournalMovement, ...]
    activity_rows_without_full_allocation: int
    sources_with_incomplete_activity: int
    excluded_unreviewed_financial_entries: int


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rows(evidence: SourceEvidence):
    payload = evidence.payload
    if isinstance(payload, StatementPayload):
        return tuple(row for account in payload.accounts for row in account.rows)
    return payload.rows


def _journal_payload(entry: JournalEntry) -> str:
    return json.dumps(entry.payload(), sort_keys=True, separators=(",", ":"))


def _decode_journal(payload: str) -> JournalEntry:
    try:
        data = json.loads(payload)
        return JournalEntry(
            key=data["key"],
            event_id=data["event_id"],
            posting_date=date.fromisoformat(data["posting_date"]),
            description=data["description"],
            postings=tuple(
                Posting(
                    posting["account_id"],
                    posting["amount_minor"],
                    tuple(Allocation(**allocation) for allocation in posting["allocations"]),
                )
                for posting in data["postings"]
            ),
            origin=data["origin"],
            reviewed=data["reviewed"],
            reason=data["reason"],
        )
    except (KeyError, TypeError, ValueError):
        raise ProfileFormatError("journal_entry_invalid") from None


def _check_format(connection: sqlite3.Connection) -> None:
    try:
        marker = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if marker != APPLICATION_ID or version != SCHEMA_VERSION:
            raise ProfileFormatError("unsupported_profile_format")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != TABLE_COLUMNS.keys():
            raise ProfileFormatError("profile_schema_missing")
        for table, columns in TABLE_COLUMNS.items():
            actual_columns = tuple(
                (row[1], row[2], row[3], row[5]) for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if actual_columns != columns:
                raise ProfileFormatError("profile_schema_mismatch")
            actual_foreign_keys = tuple(
                (row[3], row[2], row[4]) for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            )
            if actual_foreign_keys != FOREIGN_KEYS[table]:
                raise ProfileFormatError("profile_schema_mismatch")
        expected_triggers = {
            f"immutable_{table}_{action}" for table in IMMUTABLE_TABLES for action in ("update", "delete")
        }
        triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if triggers != expected_triggers:
            raise ProfileFormatError("profile_schema_mismatch")
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ProfileFormatError("profile_integrity")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ProfileFormatError("profile_integrity")
    except sqlite3.DatabaseError:
        raise ProfileFormatError("profile_integrity") from None


class V2ProfileStore:
    """Open only a marked 2.0 profile; use as a context manager."""

    def __init__(self, connection: sqlite3.Connection, *, read_only: bool):
        self.connection = connection
        self.read_only = read_only

    @classmethod
    def create(cls, path: Path) -> V2ProfileStore:
        path = path.resolve()
        with path.open("xb"):
            pass
        connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(f"""
                BEGIN IMMEDIATE;
                PRAGMA application_id={APPLICATION_ID};
                PRAGMA user_version={SCHEMA_VERSION};
                CREATE TABLE Sources (
                    sha256 TEXT PRIMARY KEY, suffix TEXT NOT NULL CHECK(suffix IN ('.csv','.pdf')),
                    size INTEGER NOT NULL, content BLOB NOT NULL
                );
                CREATE TABLE Definitions (
                    sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL, content BLOB NOT NULL
                );
                CREATE TABLE EvidenceSnapshots (
                    source_sha256 TEXT PRIMARY KEY REFERENCES Sources(sha256),
                    definition_sha256 TEXT NOT NULL REFERENCES Definitions(sha256),
                    size INTEGER NOT NULL, sha256 TEXT NOT NULL, content BLOB NOT NULL
                );
                CREATE TABLE SourceObservations (
                    row_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL REFERENCES Sources(sha256),
                    source_account TEXT,
                    source_account_form TEXT CHECK(source_account_form IN ('full','last_four','opaque')),
                    row_role TEXT NOT NULL CHECK(row_role IN ('activity','period_summary','header_charge')),
                    date_role TEXT NOT NULL CHECK(date_role IN ('posting_date','activity_date','statement_period_end')),
                    observed_date TEXT NOT NULL, amount_minor INTEGER NOT NULL,
                    CHECK((source_account IS NULL) = (source_account_form IS NULL))
                );
                CREATE TABLE Accounts (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('asset','liability','equity','income','expense')),
                    currency TEXT NOT NULL CHECK(currency='USD'),
                    role TEXT NOT NULL CHECK(role IN ('financial','category','internal')),
                    purpose TEXT NOT NULL CHECK(purpose IN ('normal','clearing','opening_equity','suspense')),
                    institution_key TEXT, full_account_number TEXT,
                    CHECK(
                        (role='financial' AND kind IN ('asset','liability') AND purpose='normal'
                            AND institution_key IS NOT NULL)
                        OR (role='category' AND kind IN ('income','expense') AND purpose='normal'
                            AND institution_key IS NULL AND full_account_number IS NULL)
                        OR (role='internal' AND institution_key IS NULL AND full_account_number IS NULL)
                    )
                );
                CREATE TABLE CategoryBudgetRates (
                    category_id TEXT NOT NULL REFERENCES Accounts(id),
                    effective_month TEXT NOT NULL,
                    amount_minor INTEGER CHECK(amount_minor>=0),
                    PRIMARY KEY(category_id,effective_month)
                );
                CREATE TABLE FileAccountAssertions (
                    source_sha256 TEXT PRIMARY KEY REFERENCES Sources(sha256),
                    ledger_account_id TEXT NOT NULL REFERENCES Accounts(id)
                );
                CREATE TABLE RowAccountAssignments (
                    row_id TEXT PRIMARY KEY REFERENCES SourceObservations(row_id),
                    ledger_account_id TEXT NOT NULL REFERENCES Accounts(id)
                );
                CREATE TABLE SourceAccountBindings (
                    source_sha256 TEXT NOT NULL REFERENCES Sources(sha256),
                    source_identity TEXT NOT NULL,
                    source_identity_form TEXT NOT NULL CHECK(source_identity_form IN ('full','last_four','opaque')),
                    ledger_account_id TEXT NOT NULL REFERENCES Accounts(id),
                    PRIMARY KEY(source_sha256,source_identity,source_identity_form)
                );
                CREATE TABLE JournalEntries (
                    key TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE JournalAllocations (
                    entry_key TEXT NOT NULL REFERENCES JournalEntries(key),
                    row_id TEXT NOT NULL REFERENCES SourceObservations(row_id),
                    amount_minor INTEGER NOT NULL CHECK(amount_minor<>0),
                    PRIMARY KEY(entry_key,row_id)
                );
                CREATE TABLE JournalCorrections (
                    original_key TEXT PRIMARY KEY REFERENCES JournalEntries(key),
                    reversal_key TEXT NOT NULL UNIQUE REFERENCES JournalEntries(key),
                    replacement_key TEXT NOT NULL UNIQUE REFERENCES JournalEntries(key),
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                COMMIT;
            """)
            for table in IMMUTABLE_TABLES:
                for action in ("UPDATE", "DELETE"):
                    connection.execute(
                        f"CREATE TRIGGER immutable_{table}_{action.lower()} "
                        f"BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable evidence'); END"
                    )
            _check_format(connection)
            return cls(connection, read_only=False)
        except BaseException:
            connection.close()
            path.unlink(missing_ok=True)
            raise

    @classmethod
    def open(cls, path: Path, *, read_only: bool = False) -> V2ProfileStore:
        path = path.resolve()
        if not path.is_file():
            raise ProfileFormatError("profile_missing")
        try:
            checked = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
            try:
                checked.execute("PRAGMA query_only=ON")
                _check_format(checked)
            finally:
                checked.close()
            mode = "ro" if read_only else "rw"
            connection = sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, isolation_level=None)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                if read_only:
                    connection.execute("PRAGMA query_only=ON")
                _check_format(connection)
                return cls(connection, read_only=read_only)
            except BaseException:
                connection.close()
                raise
        except sqlite3.DatabaseError:
            raise ProfileFormatError("profile_integrity") from None

    def __enter__(self) -> V2ProfileStore:
        return self

    def __exit__(self, *_args) -> None:
        self.connection.close()

    def _require_writable(self) -> None:
        if self.read_only:
            raise ProfileFormatError("profile_read_only")

    def add_financial_account(self, account: FinancialAccount) -> None:
        """Create one user-authored financial account before any source binding."""
        self._require_writable()
        name, institution_key, full_number = self._financial_account_values(account)
        self.connection.execute(
            "INSERT INTO Accounts VALUES (?,?,?,'USD','financial','normal',?,?)",
            (account.id, name, account.kind, institution_key, full_number),
        )

    @staticmethod
    def _financial_account_values(account: FinancialAccount) -> tuple[str, str, str | None]:
        if (
            not isinstance(account, FinancialAccount)
            or type(account.id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,79}", account.id) is None
            or type(account.name) is not str
            or not 0 < len(account.name.strip()) <= 200
            or account.kind not in {"asset", "liability"}
            or type(account.institution_key) is not str
            or re.fullmatch(r"[a-z][a-z0-9_-]{2,79}", account.institution_key) is None
            or (
                account.full_account_number is not None
                and (
                    type(account.full_account_number) is not str
                    or not 0 < len(account.full_account_number.strip()) <= 80
                )
            )
        ):
            raise ProfileFormatError("invalid_financial_account")
        return (
            account.name.strip(),
            account.institution_key,
            account.full_account_number.strip() if account.full_account_number is not None else None,
        )

    def update_financial_account(self, account: FinancialAccount) -> None:
        """Edit account identity labels while preserving its ledger class and ID."""
        self._require_writable()
        name, institution_key, full_number = self._financial_account_values(account)
        current = self.connection.execute(
            "SELECT kind FROM Accounts WHERE id=? AND role='financial'", (account.id,)
        ).fetchone()
        if current is None:
            raise ProfileFormatError("financial_account_missing")
        if current[0] != account.kind:
            raise ProfileFormatError("financial_account_kind_immutable")
        self.connection.execute(
            "UPDATE Accounts SET name=?,institution_key=?,full_account_number=? WHERE id=? AND role='financial'",
            (name, institution_key, full_number, account.id),
        )

    def financial_accounts(self) -> tuple[FinancialAccount, ...]:
        return tuple(
            FinancialAccount(*row)
            for row in self.connection.execute(
                "SELECT id,name,kind,institution_key,full_account_number FROM Accounts "
                "WHERE role='financial' ORDER BY name,id"
            )
        )

    def _require_financial_account(self, account_id: str) -> None:
        if (
            self.connection.execute("SELECT 1 FROM Accounts WHERE id=? AND role='financial'", (account_id,)).fetchone()
            is None
        ):
            raise ProfileFormatError("financial_account_missing")

    def add_category_account(self, account_id: str, name: str, kind: Literal["expense", "income"]) -> None:
        """Create a fresh authored ledger category without source interpretation."""
        self._require_writable()
        if (
            type(account_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,79}", account_id) is None
            or type(name) is not str
            or not 0 < len(name.strip()) <= 200
            or kind not in {"expense", "income"}
        ):
            raise ProfileFormatError("invalid_category_account")
        self.connection.execute(
            "INSERT INTO Accounts VALUES (?,?,?,'USD','category','normal',NULL,NULL)",
            (account_id, name, kind),
        )

    def category_accounts(self) -> tuple[CategoryAccount, ...]:
        return tuple(
            CategoryAccount(*row)
            for row in self.connection.execute(
                "SELECT id,name,kind FROM Accounts WHERE role='category' ORDER BY name,id"
            )
        )

    def rename_category_account(self, account_id: str, name: str) -> None:
        """Change only a category's display name; journal references use its ID."""
        self._require_writable()
        if type(name) is not str or not 0 < len(name.strip()) <= 200:
            raise ProfileFormatError("invalid_category_name")
        cursor = self.connection.execute(
            "UPDATE Accounts SET name=? WHERE id=? AND role='category'", (name.strip(), account_id)
        )
        if cursor.rowcount != 1:
            raise ProfileFormatError("category_account_missing")

    @staticmethod
    def _budget_month(month: date) -> str:
        if type(month) is not date or month.day != 1:
            raise ProfileFormatError("budget_effective_month_invalid")
        return month.isoformat()[:7]

    def set_category_budget_rate(self, category_id: str, effective_month: date, amount_minor: int | None) -> None:
        """Set a monthly target from one month until the next authored change."""
        self._require_writable()
        month_key = self._budget_month(effective_month)
        if amount_minor is not None and (
            type(amount_minor) is not int or not 0 <= amount_minor < 9_000_000_000_000_000
        ):
            raise ProfileFormatError("budget_amount_invalid")
        if (
            self.connection.execute("SELECT 1 FROM Accounts WHERE id=? AND role='category'", (category_id,)).fetchone()
            is None
        ):
            raise ProfileFormatError("category_account_missing")
        self.connection.execute(
            "INSERT INTO CategoryBudgetRates(category_id,effective_month,amount_minor) VALUES (?,?,?) "
            "ON CONFLICT(category_id,effective_month) DO UPDATE SET amount_minor=excluded.amount_minor",
            (category_id, month_key, amount_minor),
        )

    def category_budget_history(self, category_id: str) -> tuple[CategoryBudgetRate, ...]:
        if (
            self.connection.execute("SELECT 1 FROM Accounts WHERE id=? AND role='category'", (category_id,)).fetchone()
            is None
        ):
            raise ProfileFormatError("category_account_missing")
        return tuple(
            CategoryBudgetRate(category_id, date.fromisoformat(month_key + "-01"), amount_minor)
            for month_key, amount_minor in self.connection.execute(
                "SELECT effective_month,amount_minor FROM CategoryBudgetRates "
                "WHERE category_id=? ORDER BY effective_month",
                (category_id,),
            )
        )

    def category_budget_targets(self, month: date) -> tuple[CategoryBudgetTarget, ...]:
        month_key = self._budget_month(month)
        active: dict[str, tuple[date, int | None]] = {}
        for category_id, effective_key, amount_minor in self.connection.execute(
            "SELECT category_id,effective_month,amount_minor FROM CategoryBudgetRates "
            "WHERE effective_month<=? ORDER BY category_id,effective_month",
            (month_key,),
        ):
            active[category_id] = (date.fromisoformat(effective_key + "-01"), amount_minor)
        return tuple(
            CategoryBudgetTarget(
                category.id,
                category.name,
                category.kind,
                active[category.id][0] if category.id in active else None,
                active[category.id][1] if category.id in active else None,
            )
            for category in self.category_accounts()
        )

    def _cash_category_source(self, row_id: str, kind: Literal["expense", "income"]):
        source_row = self.connection.execute(
            "SELECT source_sha256,row_role,date_role,observed_date,amount_minor FROM SourceObservations WHERE row_id=?",
            (row_id,),
        ).fetchone()
        if source_row is None:
            raise ProfileFormatError("source_observation_missing")
        saved = self.load_import(source_row[0])
        bindings = {binding.row_id: binding.ledger_account_id for binding in self.account_bindings(source_row[0])}
        row = next((item for item in _rows(saved.evidence) if item.row_id == row_id), None)
        financial_id = bindings.get(row_id)
        if (
            row is None
            or row.row_role != "activity"
            or row.date_role != "posting_date"
            or row.date.iso is None
            or row.amount.minor is None
            or row.amount.minor == 0
            or (row.amount.minor < 0) != (kind == "expense")
            or not row.description.text
            or financial_id is None
        ):
            raise ProfileFormatError("cash_category_requires_bound_posted_movement")
        if source_row[1:] != (row.row_role, row.date_role, row.date.iso, row.amount.minor):
            raise ProfileFormatError("source_observation_index_mismatch")
        financial = self.connection.execute("SELECT kind,role FROM Accounts WHERE id=?", (financial_id,)).fetchone()
        if financial != ("asset", "financial"):
            raise ProfileFormatError("cash_category_requires_asset_account")
        account_rows = self.connection.execute("SELECT id,name,kind,currency,role,purpose FROM Accounts").fetchall()
        accounts = {
            account_id: LedgerAccount(
                account_id,
                name,
                AccountKind(kind),
                currency,
                account_id if role == "financial" else None,
                purpose,
            )
            for account_id, name, kind, currency, role, purpose in account_rows
        }
        return row, financial_id, accounts

    def _active_consumed(self, *, excluding: str | None = None) -> dict[str, int]:
        query = (
            "SELECT row_id,SUM(amount_minor) FROM JournalAllocations "
            "WHERE entry_key NOT IN (SELECT original_key FROM JournalCorrections)"
        )
        parameters: tuple[str, ...] = ()
        if excluding is not None:
            query += " AND entry_key<>?"
            parameters = (excluding,)
        return dict(self.connection.execute(query + " GROUP BY row_id", parameters))

    def _require_unposted_rows(self, row_ids: tuple[str, ...]) -> None:
        for offset in range(0, len(row_ids), 500):
            batch = row_ids[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            if self.connection.execute(
                f"SELECT 1 FROM JournalAllocations WHERE row_id IN ({placeholders}) LIMIT 1", batch
            ).fetchone():
                raise ProfileFormatError("account_binding_has_journal_history")

    def _row_assignments(self, row_ids: tuple[str, ...]) -> dict[str, str]:
        assigned = {}
        for offset in range(0, len(row_ids), 500):
            batch = row_ids[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            assigned.update(
                self.connection.execute(
                    f"SELECT row_id,ledger_account_id FROM RowAccountAssignments WHERE row_id IN ({placeholders})",
                    batch,
                )
            )
        return assigned

    def cash_activity_review_rows(self, source_sha256: str) -> tuple[CashActivityReviewRow, ...]:
        """Describe source rows for explicit asset cash expense or income review."""
        saved = self.load_import(source_sha256)
        bindings = {binding.row_id: binding.ledger_account_id for binding in self.account_bindings(source_sha256)}
        accounts = {
            account_id: (name, kind, role)
            for account_id, name, kind, role in self.connection.execute("SELECT id,name,kind,role FROM Accounts")
        }
        active: dict[str, list[JournalEntry]] = {}
        for row_id, payload in self.connection.execute(
            "SELECT a.row_id,e.payload FROM JournalAllocations a JOIN JournalEntries e ON e.key=a.entry_key "
            "JOIN SourceObservations o ON o.row_id=a.row_id "
            "WHERE o.source_sha256=? AND a.entry_key NOT IN (SELECT original_key FROM JournalCorrections)",
            (source_sha256,),
        ):
            active.setdefault(row_id, []).append(_decode_journal(payload))
        result = []
        for row in _rows(saved.evidence):
            account_id = bindings.get(row.row_id)
            financial = accounts.get(account_id) if account_id is not None else None
            account_name = financial[0] if financial is not None else None
            entries = active.get(row.row_id, [])
            entry_key = None
            category_id = None
            if entries:
                status = "Already posted to the ledger"
                if len(entries) == 1:
                    entry = entries[0]
                    if (
                        entry.origin == "imported"
                        and entry.reviewed
                        and len(entry.postings) == 2
                        and entry.postings[0].account_id == account_id
                        and entry.postings[0].allocations == (Allocation(row.row_id, row.amount.minor),)
                        and accounts.get(entry.postings[1].account_id, (None, None, None))[1:]
                        == ("expense" if row.amount.minor < 0 else "income", "category")
                    ):
                        entry_key = entry.key
                        category_id = entry.postings[1].account_id
                        status = "Posted: " + accounts[category_id][0]
            elif not isinstance(saved.evidence.payload, ActivityExportPayload):
                status = "Statement posting is not available in this review"
            elif row.row_role != "activity" or row.amount.minor is None or row.amount.minor == 0:
                status = "Outside cash activity scope"
            elif row.date_role != "posting_date" or row.date.iso is None:
                status = "Posting date needs review"
            elif account_id is None:
                status = "Assign a financial account first"
            elif financial is None or financial[1:] != ("asset", "financial"):
                status = "Requires a bound asset account"
            elif not row.description.text:
                status = "Description needs review"
            else:
                status = "Ready for expense review" if row.amount.minor < 0 else "Ready for income review"
            result.append(
                CashActivityReviewRow(
                    row.row_id,
                    row.date.iso,
                    row.description.text,
                    row.amount.minor,
                    account_name,
                    status,
                    entry_key,
                    category_id,
                )
            )
        return tuple(result)

    def _journal_entries_in_period(self, start: date, end: date):
        if type(start) is not date or type(end) is not date or start >= end:
            raise ProfileFormatError("report_period_invalid")
        for (payload,) in self.connection.execute("SELECT payload FROM JournalEntries"):
            entry = _decode_journal(payload)
            if start <= entry.posting_date < end:
                yield entry

    def _unallocated_activity_counts(self) -> tuple[int, int]:
        return self.connection.execute(
            "SELECT COUNT(*),COUNT(DISTINCT o.source_sha256) FROM SourceObservations o "
            "LEFT JOIN ("
            "SELECT a.row_id,SUM(a.amount_minor) AS used FROM JournalAllocations a "
            "WHERE a.entry_key NOT IN (SELECT original_key FROM JournalCorrections) GROUP BY a.row_id"
            ") active ON active.row_id=o.row_id "
            "WHERE o.row_role='activity' AND (active.used IS NULL OR active.used<>o.amount_minor)"
        ).fetchone()

    def reviewed_category_summary(
        self, *, kind: Literal["expense", "income"], start: date, end: date
    ) -> ReviewedCategorySummary:
        """Summarize reviewed category postings in the category's natural direction."""
        if kind not in {"expense", "income"}:
            raise ProfileFormatError("report_category_kind_invalid")
        categories = {category.id: category for category in self.category_accounts() if category.kind == kind}
        totals = dict.fromkeys(categories, 0)
        excluded_unreviewed = 0
        direction = 1 if kind == "expense" else -1
        for entry in self._journal_entries_in_period(start, end):
            if not entry.reviewed:
                excluded_unreviewed += any(posting.account_id in totals for posting in entry.postings)
                continue
            for posting in entry.postings:
                if posting.account_id in totals:
                    totals[posting.account_id] += direction * posting.amount_minor
        unresolved_rows, unresolved_sources = self._unallocated_activity_counts()
        return ReviewedCategorySummary(
            start,
            end,
            kind,
            tuple(
                ReviewedCategoryTotal(category_id, category.name, totals[category_id])
                for category_id, category in categories.items()
            ),
            sum(totals.values()),
            unresolved_rows,
            unresolved_sources,
            excluded_unreviewed,
        )

    def monthly_budget_summary(self, month: date) -> MonthlyBudgetSummary:
        """Compare effective expense targets with reviewed spending in a whole month."""
        self._budget_month(month)
        if month.year == 9999 and month.month == 12:
            raise ProfileFormatError("report_period_invalid")
        next_month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        spending = self.reviewed_category_summary(kind="expense", start=month, end=next_month)
        targets = {target.category_id: target for target in self.category_budget_targets(month)}
        rows = tuple(
            MonthlyBudgetRow(
                category.category_id,
                category.name,
                targets[category.category_id].amount_minor,
                targets[category.category_id].effective_month,
                category.amount_minor,
                (
                    targets[category.category_id].amount_minor - category.amount_minor
                    if targets[category.category_id].amount_minor is not None
                    else None
                ),
            )
            for category in spending.categories
        )
        return MonthlyBudgetSummary(
            month,
            rows,
            sum(row.target_minor for row in rows if row.target_minor is not None)
            if all(row.target_minor is not None for row in rows)
            else None,
            spending.total_minor,
            spending.activity_rows_without_full_allocation,
            spending.sources_with_incomplete_activity,
            spending.excluded_unreviewed_entries,
        )

    def financial_journal_summary(self, *, start: date, end: date) -> FinancialJournalSummary:
        """Show reviewed account postings, keeping openings apart from period activity."""
        accounts = {account.id: account for account in self.financial_accounts()}
        nonopening = dict.fromkeys(accounts, 0)
        opening = dict.fromkeys(accounts, 0)
        opening_seen: set[str] = set()
        excluded_unreviewed = 0
        for entry in self._journal_entries_in_period(start, end):
            financial_postings = tuple(posting for posting in entry.postings if posting.account_id in accounts)
            if not entry.reviewed:
                excluded_unreviewed += bool(financial_postings)
                continue
            target = opening if entry.origin == "opening" else nonopening
            for posting in financial_postings:
                target[posting.account_id] += posting.amount_minor
                if entry.origin == "opening":
                    opening_seen.add(posting.account_id)
        unresolved_rows, unresolved_sources = self._unallocated_activity_counts()
        return FinancialJournalSummary(
            start,
            end,
            tuple(
                FinancialJournalMovement(
                    account_id,
                    account.name,
                    account.kind,
                    nonopening[account_id],
                    opening[account_id] if account_id in opening_seen else None,
                )
                for account_id, account in accounts.items()
            ),
            unresolved_rows,
            unresolved_sources,
            excluded_unreviewed,
        )

    def post_reviewed_cash_category(self, row_id: str, category_id: str, *, reason: str) -> str:
        """Post one explicitly classified asset cash movement with source evidence."""
        self._require_writable()
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("cash_review_reason_required")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            category = self.connection.execute("SELECT kind,role FROM Accounts WHERE id=?", (category_id,)).fetchone()
            if category not in {("expense", "category"), ("income", "category")}:
                raise ProfileFormatError("cash_category_invalid")
            kind = category[0]
            row, financial_id, accounts = self._cash_category_source(row_id, kind)
            amount = row.amount.minor
            entry = JournalEntry(
                key=f"review:cash:{kind}:{row_id}",
                event_id=f"source:{row_id}",
                posting_date=date.fromisoformat(row.date.iso),
                description=row.description.text,
                postings=(
                    Posting(financial_id, amount, (Allocation(row_id, amount),)),
                    Posting(category_id, -amount),
                ),
                reviewed=True,
                reason=reason.strip(),
            )
            payload = _journal_payload(entry)
            prior = self.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (entry.key,)).fetchone()
            if prior is not None:
                if self.connection.execute(
                    "SELECT 1 FROM JournalCorrections WHERE original_key=?", (entry.key,)
                ).fetchone():
                    raise ProfileFormatError("cash_review_already_corrected")
                if prior[0] != payload:
                    raise ProfileFormatError("cash_review_conflicts_with_prior_entry")
                self.connection.execute("COMMIT")
                return entry.key
            validate_entry(
                entry,
                accounts,
                {row_id: Observation(row_id, financial_id, amount, entry.posting_date)},
                self._active_consumed(),
            )
            self.connection.execute("INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (entry.key, payload))
            self.connection.execute("INSERT INTO JournalAllocations VALUES (?,?,?)", (entry.key, row_id, amount))
            self.connection.execute("COMMIT")
            return entry.key
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("cash_review_refused") from None
            raise

    def correct_reviewed_cash_category(self, original_key: str, category_id: str, *, reason: str) -> str:
        """Atomically reverse and recategorize an active reviewed cash movement."""
        self._require_writable()
        if type(original_key) is not str or not original_key or type(category_id) is not str or not category_id:
            raise ProfileFormatError("cash_correction_identity_required")
        if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
            raise ProfileFormatError("cash_correction_reason_required")
        reason = reason.strip()
        replacement_key = (
            "review:cash:correction:" + hashlib.sha256(f"{original_key}\0{category_id}\0{reason}".encode()).hexdigest()
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            prior = self.connection.execute(
                "SELECT replacement_key,reason FROM JournalCorrections WHERE original_key=?", (original_key,)
            ).fetchone()
            if prior is not None:
                if prior == (replacement_key, reason):
                    self.connection.execute("COMMIT")
                    return replacement_key
                raise ProfileFormatError("cash_correction_conflicts_with_prior_decision")
            original_row = self.connection.execute(
                "SELECT payload FROM JournalEntries WHERE key=?", (original_key,)
            ).fetchone()
            if original_row is None:
                raise ProfileFormatError("cash_correction_original_missing")
            original = _decode_journal(original_row[0])
            allocations = self.connection.execute(
                "SELECT row_id,amount_minor FROM JournalAllocations WHERE entry_key=?", (original_key,)
            ).fetchall()
            if (
                original.key != original_key
                or original.origin != "imported"
                or not original.reviewed
                or len(original.postings) != 2
                or len(allocations) != 1
                or original.postings[0].amount_minor != allocations[0][1]
                or original.postings[0].amount_minor == 0
                or original.postings[0].allocations != (Allocation(*allocations[0]),)
                or original.postings[1].amount_minor != -allocations[0][1]
            ):
                raise ProfileFormatError("cash_correction_original_invalid")
            row_id, amount = allocations[0]
            old_category_id = original.postings[1].account_id
            old_category = self.connection.execute(
                "SELECT kind,role FROM Accounts WHERE id=?", (old_category_id,)
            ).fetchone()
            new_category = self.connection.execute(
                "SELECT kind,role FROM Accounts WHERE id=?", (category_id,)
            ).fetchone()
            kind = "expense" if amount < 0 else "income"
            row, financial_id, accounts = self._cash_category_source(row_id, kind)
            if (
                original.postings[0].account_id != financial_id
                or original.event_id != f"source:{row_id}"
                or original.posting_date.isoformat() != row.date.iso
                or original.description != row.description.text
                or old_category != (kind, "category")
                or new_category != (kind, "category")
                or category_id == old_category_id
            ):
                raise ProfileFormatError("cash_correction_requires_new_same_kind_category")
            reversal = JournalEntry(
                key="reversal:" + hashlib.sha256(original_key.encode()).hexdigest(),
                event_id=original.event_id,
                posting_date=original.posting_date,
                description="Reversal: " + original.description,
                postings=tuple(Posting(posting.account_id, -posting.amount_minor) for posting in original.postings),
                origin="reversal",
                reviewed=True,
                reason=reason,
            )
            replacement = JournalEntry(
                key=replacement_key,
                event_id=original.event_id,
                posting_date=original.posting_date,
                description=original.description,
                postings=(
                    Posting(financial_id, amount, (Allocation(row_id, amount),)),
                    Posting(category_id, -amount),
                ),
                reviewed=True,
                reason=reason,
            )
            if self.connection.execute(
                "SELECT 1 FROM JournalEntries WHERE key IN (?,?)", (reversal.key, replacement.key)
            ).fetchone():
                raise ProfileFormatError("cash_correction_key_conflict")
            validate_entry(
                replacement,
                accounts,
                {row_id: Observation(row_id, financial_id, amount, replacement.posting_date)},
                self._active_consumed(excluding=original_key),
            )
            self.connection.execute(
                "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (reversal.key, _journal_payload(reversal))
            )
            self.connection.execute(
                "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (replacement.key, _journal_payload(replacement))
            )
            self.connection.execute("INSERT INTO JournalAllocations VALUES (?,?,?)", (replacement.key, row_id, amount))
            self.connection.execute(
                "INSERT INTO JournalCorrections(original_key,reversal_key,replacement_key,reason) VALUES (?,?,?,?)",
                (original_key, reversal.key, replacement.key, reason),
            )
            self.connection.execute("COMMIT")
            return replacement.key
        except BaseException as exc:
            self.connection.execute("ROLLBACK")
            if isinstance(exc, LedgerError):
                raise ProfileFormatError("cash_correction_refused") from None
            raise

    def source_account_bindings(self, source_sha256: str) -> tuple[SourceAccountBinding, ...]:
        """Show each identity printed by a source and its explicit ledger decision."""
        evidence = self.load_import(source_sha256).evidence
        payload = evidence.payload
        if isinstance(payload, StatementPayload):
            identities = tuple((account.source_identity, account.source_identity_form) for account in payload.accounts)
        else:
            identities = tuple(
                dict.fromkeys(
                    (row.source_account, row.source_account_form)
                    for row in payload.rows
                    if row.source_account is not None
                )
            )
        saved = {
            (identity, form): account_id
            for identity, form, account_id in self.connection.execute(
                "SELECT source_identity,source_identity_form,ledger_account_id "
                "FROM SourceAccountBindings WHERE source_sha256=?",
                (source_sha256,),
            )
        }
        return tuple(SourceAccountBinding(identity, form, saved.get((identity, form))) for identity, form in identities)

    def bind_source_account(
        self, source_sha256: str, source_identity: str, source_identity_form: str, account_id: str
    ) -> None:
        """Bind one printed account identity after an explicit user decision."""
        self._require_writable()
        if (source_identity, source_identity_form) not in {
            (binding.source_identity, binding.source_identity_form)
            for binding in self.source_account_bindings(source_sha256)
        }:
            raise ProfileFormatError("source_account_missing")
        self._require_financial_account(account_id)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            prior = self.connection.execute(
                "SELECT ledger_account_id FROM SourceAccountBindings "
                "WHERE source_sha256=? AND source_identity=? AND source_identity_form=?",
                (source_sha256, source_identity, source_identity_form),
            ).fetchone()
            if prior != (account_id,):
                row_ids = tuple(
                    row[0]
                    for row in self.connection.execute(
                        "SELECT row_id FROM SourceObservations WHERE source_sha256=? "
                        "AND source_account=? AND source_account_form=?",
                        (source_sha256, source_identity, source_identity_form),
                    )
                )
                self._require_unposted_rows(row_ids)
                self.connection.execute(
                    "INSERT INTO SourceAccountBindings VALUES (?,?,?,?) "
                    "ON CONFLICT(source_sha256,source_identity,source_identity_form) "
                    "DO UPDATE SET ledger_account_id=excluded.ledger_account_id",
                    (source_sha256, source_identity, source_identity_form, account_id),
                )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def clear_source_account_binding(self, source_sha256: str, source_identity: str, source_identity_form: str) -> None:
        self._require_writable()
        if (source_identity, source_identity_form) not in {
            (binding.source_identity, binding.source_identity_form)
            for binding in self.source_account_bindings(source_sha256)
        }:
            raise ProfileFormatError("source_account_missing")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row_ids = tuple(
                row[0]
                for row in self.connection.execute(
                    "SELECT row_id FROM SourceObservations WHERE source_sha256=? "
                    "AND source_account=? AND source_account_form=?",
                    (source_sha256, source_identity, source_identity_form),
                )
            )
            self._require_unposted_rows(row_ids)
            self.connection.execute(
                "DELETE FROM SourceAccountBindings WHERE source_sha256=? AND source_identity=? AND source_identity_form=?",
                (source_sha256, source_identity, source_identity_form),
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def assert_file_account(self, source_sha256: str, account_id: str) -> None:
        """Assert that every accountless row belongs to one financial account."""
        self._require_writable()
        self._require_financial_account(account_id)
        evidence = self.load_import(source_sha256).evidence
        payload = evidence.payload
        if (
            not isinstance(payload, ActivityExportPayload)
            or not payload.rows
            or any(row.source_account is not None for row in payload.rows)
        ):
            raise ProfileFormatError("file_account_assertion_requires_accountless_export")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.connection.execute(
                "SELECT 1 FROM RowAccountAssignments a JOIN SourceObservations o ON o.row_id=a.row_id "
                "WHERE o.source_sha256=? LIMIT 1",
                (source_sha256,),
            ).fetchone():
                raise ProfileFormatError("file_account_assertion_conflicts_with_row_assignments")
            prior = self.connection.execute(
                "SELECT ledger_account_id FROM FileAccountAssertions WHERE source_sha256=?", (source_sha256,)
            ).fetchone()
            if prior != (account_id,):
                self._require_unposted_rows(tuple(row.row_id for row in payload.rows))
            self.connection.execute(
                "INSERT INTO FileAccountAssertions VALUES (?,?) "
                "ON CONFLICT(source_sha256) DO UPDATE SET ledger_account_id=excluded.ledger_account_id",
                (source_sha256, account_id),
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def clear_file_account_assertion(self, source_sha256: str) -> None:
        self._require_writable()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.connection.execute(
                "SELECT 1 FROM FileAccountAssertions WHERE source_sha256=?", (source_sha256,)
            ).fetchone():
                self._require_unposted_rows(
                    tuple(
                        row[0]
                        for row in self.connection.execute(
                            "SELECT row_id FROM SourceObservations WHERE source_sha256=?", (source_sha256,)
                        )
                    )
                )
            self.connection.execute("DELETE FROM FileAccountAssertions WHERE source_sha256=?", (source_sha256,))
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def assign_row_account(self, row_id: str, account_id: str) -> None:
        """Assign one accountless row in an export reviewed row by row."""
        self._require_writable()
        row = self.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (row_id,)
        ).fetchone()
        if row is None:
            raise ProfileFormatError("observation_missing")
        self.assign_rows_account(row[0], (row_id,), account_id)

    def assign_rows_account(self, source_sha256: str, row_ids: tuple[str, ...], account_id: str) -> None:
        """Atomically assign selected rows in a mixed, accountless export."""
        self._require_writable()
        self._require_financial_account(account_id)
        evidence = self.load_import(source_sha256).evidence
        payload = evidence.payload
        if (
            not isinstance(payload, ActivityExportPayload)
            or not row_ids
            or len(set(row_ids)) != len(row_ids)
            or not set(row_ids) <= {row.row_id for row in payload.rows if row.source_account is None}
        ):
            raise ProfileFormatError("row_account_assignment_requires_accountless_export")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.connection.execute(
                "SELECT 1 FROM FileAccountAssertions WHERE source_sha256=?", (source_sha256,)
            ).fetchone():
                raise ProfileFormatError("row_account_assignment_conflicts_with_file_assertion")
            prior = self._row_assignments(row_ids)
            self._require_unposted_rows(tuple(row_id for row_id in row_ids if prior.get(row_id) != account_id))
            self.connection.executemany(
                "INSERT INTO RowAccountAssignments VALUES (?,?) "
                "ON CONFLICT(row_id) DO UPDATE SET ledger_account_id=excluded.ledger_account_id",
                ((row_id, account_id) for row_id in row_ids),
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def clear_row_account_assignment(self, row_id: str) -> None:
        row = self.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (row_id,)
        ).fetchone()
        if row is None:
            raise ProfileFormatError("observation_missing")
        self.clear_row_account_assignments(row[0], (row_id,))

    def clear_row_account_assignments(self, source_sha256: str, row_ids: tuple[str, ...]) -> None:
        self._require_writable()
        evidence = self.load_import(source_sha256).evidence
        if len(set(row_ids)) != len(row_ids) or not set(row_ids) <= {row.row_id for row in _rows(evidence)}:
            raise ProfileFormatError("invalid_row_assignment_selection")
        if not row_ids:
            return
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            assigned = tuple(self._row_assignments(row_ids))
            self._require_unposted_rows(assigned)
            self.connection.executemany(
                "DELETE FROM RowAccountAssignments WHERE row_id=?", ((row_id,) for row_id in row_ids)
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def account_bindings(self, source_sha256: str) -> tuple[AccountBinding, ...]:
        """Show effective user decisions; unassigned rows remain unresolved."""
        evidence = self.load_import(source_sha256).evidence
        file_row = self.connection.execute(
            "SELECT ledger_account_id FROM FileAccountAssertions WHERE source_sha256=?", (source_sha256,)
        ).fetchone()
        file_account_id = file_row[0] if file_row else None
        row_assignments = dict(
            self.connection.execute(
                "SELECT a.row_id,a.ledger_account_id FROM RowAccountAssignments a "
                "JOIN SourceObservations o ON o.row_id=a.row_id WHERE o.source_sha256=?",
                (source_sha256,),
            )
        )
        source_assignments = {
            (binding.source_identity, binding.source_identity_form): binding.ledger_account_id
            for binding in self.source_account_bindings(source_sha256)
        }
        result = []
        for row in _rows(evidence):
            if row.row_id in row_assignments:
                result.append(AccountBinding(row.row_id, row_assignments[row.row_id], "row"))
            elif row.source_account is not None and source_assignments.get(
                (row.source_account, row.source_account_form)
            ):
                result.append(
                    AccountBinding(
                        row.row_id, source_assignments[(row.source_account, row.source_account_form)], "source"
                    )
                )
            elif row.source_account is None and file_account_id is not None:
                result.append(AccountBinding(row.row_id, file_account_id, "file"))
            else:
                result.append(AccountBinding(row.row_id, None, None))
        return tuple(result)

    def journal_history_row_ids(self, source_sha256: str) -> frozenset[str]:
        """Rows whose account assignment is locked by any posted journal history."""
        self.load_import(source_sha256)
        return frozenset(
            row_id
            for (row_id,) in self.connection.execute(
                "SELECT DISTINCT a.row_id FROM JournalAllocations a "
                "JOIN SourceObservations o ON o.row_id=a.row_id WHERE o.source_sha256=?",
                (source_sha256,),
            )
        )

    def source_imported(self, source: bytes) -> bool:
        """Check an exact-source retry before invoking a parser."""
        if type(source) is not bytes or not 0 < len(source) <= MAX_SOURCE_BYTES:
            raise ProfileFormatError("source_size")
        return (
            self.connection.execute("SELECT 1 FROM Sources WHERE sha256=?", (_digest(source),)).fetchone() is not None
        )

    def source_ids(self) -> tuple[str, ...]:
        """List saved imports in their original insertion order, newest first."""
        return tuple(row[0] for row in self.connection.execute("SELECT sha256 FROM Sources ORDER BY rowid DESC"))

    def overlapping_statement_sources(self, source_sha256: str) -> tuple[str, ...]:
        """Find period overlaps only for explicitly linked ledger accounts."""
        payload = self.load_import(source_sha256).evidence.payload
        if not isinstance(payload, StatementPayload) or payload.start.iso is None:
            return ()
        account_ids = tuple(
            sorted(
                {
                    binding.ledger_account_id
                    for binding in self.source_account_bindings(source_sha256)
                    if binding.ledger_account_id is not None
                }
            )
        )
        if not account_ids:
            return ()
        placeholders = ",".join("?" for _ in account_ids)
        candidates = self.connection.execute(
            "SELECT DISTINCT source_sha256 FROM SourceAccountBindings "
            f"WHERE ledger_account_id IN ({placeholders}) AND source_sha256<>? ORDER BY source_sha256",
            (*account_ids, source_sha256),
        )
        overlaps = []
        for (candidate_id,) in candidates:
            other = self.load_import(candidate_id).evidence.payload
            if (
                isinstance(other, StatementPayload)
                and other.start.iso is not None
                and payload.start.iso <= other.end.iso
                and other.start.iso <= payload.end.iso
            ):
                overlaps.append(candidate_id)
        return tuple(overlaps)

    def import_source(
        self, source: bytes, definition: bytes, evidence: SourceEvidence, *, suffix: Literal[".csv", ".pdf"]
    ) -> bool:
        """Atomically save one admitted snapshot. False means exact-source retry."""
        self._require_writable()
        if (
            type(source) is not bytes
            or not 0 < len(source) <= MAX_SOURCE_BYTES
            or type(definition) is not bytes
            or not 0 < len(definition) <= MAX_DEFINITION_BYTES
            or suffix not in {".csv", ".pdf"}
        ):
            raise ProfileFormatError("source_or_definition_size")
        try:
            saved = evidence.model_dump_json().encode("utf-8")
            if not 0 < len(saved) <= MAX_EVIDENCE_BYTES:
                raise ProfileFormatError("evidence_size")
            evidence = SourceEvidence.model_validate_json(saved)
        except (AttributeError, ValidationError, ValueError):
            raise ProfileFormatError("invalid_evidence") from None
        source_hash, definition_hash = _digest(source), _digest(definition)
        if evidence.source_sha256 != source_hash or evidence.definition_sha256 != definition_hash:
            raise ProfileFormatError("evidence_hash_mismatch")
        c = self.connection
        c.execute("BEGIN IMMEDIATE")
        try:
            if c.execute("SELECT 1 FROM Sources WHERE sha256=?", (source_hash,)).fetchone():
                c.execute("COMMIT")
                return False
            c.execute(
                "INSERT OR IGNORE INTO Definitions VALUES (?,?,?)", (definition_hash, len(definition), definition)
            )
            c.execute("INSERT INTO Sources VALUES (?,?,?,?)", (source_hash, suffix, len(source), source))
            c.execute(
                "INSERT INTO EvidenceSnapshots VALUES (?,?,?,?,?)",
                (source_hash, definition_hash, len(saved), _digest(saved), saved),
            )
            c.executemany(
                "INSERT INTO SourceObservations VALUES (?,?,?,?,?,?,?,?)",
                (
                    (
                        row.row_id,
                        source_hash,
                        row.source_account,
                        row.source_account_form,
                        row.row_role,
                        row.date_role,
                        row.date.iso,
                        row.amount.minor,
                    )
                    for row in _rows(evidence)
                ),
            )
            c.execute("COMMIT")
            return True
        except BaseException:
            c.execute("ROLLBACK")
            raise

    def load_import(self, source_sha256: str) -> SavedImport:
        row = self.connection.execute(
            "SELECT s.content,s.size,s.suffix,d.content,d.size,e.content,e.size,e.sha256 "
            "FROM Sources s JOIN EvidenceSnapshots e ON e.source_sha256=s.sha256 "
            "JOIN Definitions d ON d.sha256=e.definition_sha256 WHERE s.sha256=?",
            (source_sha256,),
        ).fetchone()
        if row is None:
            raise ProfileFormatError("source_missing")
        source, source_size, suffix, definition, definition_size, content, evidence_size, evidence_hash = row
        if (
            len(source) != source_size
            or len(definition) != definition_size
            or len(content) != evidence_size
            or len(source) > MAX_SOURCE_BYTES
            or len(definition) > MAX_DEFINITION_BYTES
            or len(content) > MAX_EVIDENCE_BYTES
            or _digest(source) != source_sha256
            or _digest(content) != evidence_hash
        ):
            raise ProfileFormatError("saved_snapshot_integrity")
        try:
            evidence = SourceEvidence.model_validate_json(content)
        except ValidationError:
            raise ProfileFormatError("invalid_saved_evidence") from None
        if evidence.source_sha256 != source_sha256 or evidence.definition_sha256 != _digest(definition):
            raise ProfileFormatError("saved_evidence_mismatch")
        expected = {
            (
                item.row_id,
                item.source_account,
                item.source_account_form,
                item.row_role,
                item.date_role,
                item.date.iso,
                item.amount.minor,
            )
            for item in _rows(evidence)
        }
        actual = set(
            self.connection.execute(
                "SELECT row_id,source_account,source_account_form,row_role,date_role,observed_date,amount_minor "
                "FROM SourceObservations WHERE source_sha256=?",
                (source_sha256,),
            )
        )
        if expected != actual:
            raise ProfileFormatError("observation_inventory_mismatch")
        return SavedImport(source, definition, evidence, suffix)

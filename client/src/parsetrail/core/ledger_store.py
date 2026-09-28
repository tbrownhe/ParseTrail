"""Opt-in SQLite ledger prototype, isolated from the active application database.

The store accepts reviewed mappings; it never imports or interprets legacy data.
All writes are atomic and posted records are protected by append-only triggers.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path

from parsetrail.core.ledger import (
    AccountKind,
    Allocation,
    JournalEntry,
    LedgerAccount,
    LedgerError,
    Observation,
    Posting,
    identifier,
    validate_entry,
)
from parsetrail.core.ledger_reconciliation import StatementEvidence, evaluate_statement


def encoded(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def decode_entry(payload: str) -> JournalEntry:
    data = json.loads(payload)
    data["posting_date"] = date.fromisoformat(data["posting_date"])
    data["postings"] = tuple(
        Posting(p["account_id"], p["amount_minor"], tuple(Allocation(**a) for a in p["allocations"]))
        for p in data["postings"]
    )
    return JournalEntry(**data)


class LedgerStore:
    """Use as a context manager. Creation refuses to overwrite any existing file."""

    def __init__(self, path: Path, *, create: bool = False):
        path = path.resolve()
        if create:
            with path.open("xb"):
                pass
        elif not path.is_file():
            raise LedgerError("Ledger file does not exist.")
        self.connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None)
        self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            if create:
                self._create_schema()
            if self.connection.execute("SELECT version FROM LedgerMeta").fetchall() != [(1,)]:
                raise LedgerError("Unsupported isolated ledger version.")
        except Exception:
            self.connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.connection.close()

    @contextmanager
    def _transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def _create_schema(self):
        self.connection.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE LedgerMeta(version INTEGER NOT NULL);
            INSERT INTO LedgerMeta VALUES (1);
            CREATE TABLE LedgerAccounts(id TEXT PRIMARY KEY, source_id TEXT UNIQUE, payload TEXT NOT NULL);
            CREATE TABLE LedgerObservations(id TEXT PRIMARY KEY, account_id TEXT NOT NULL
                REFERENCES LedgerAccounts(id), payload TEXT NOT NULL);
            CREATE TABLE LedgerEntries(key TEXT PRIMARY KEY, payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
            CREATE TABLE LedgerAllocations(entry_key TEXT NOT NULL REFERENCES LedgerEntries(key),
                observation_id TEXT NOT NULL REFERENCES LedgerObservations(id), amount INTEGER NOT NULL,
                PRIMARY KEY(entry_key,observation_id));
            CREATE TABLE LedgerCorrections(original_key TEXT PRIMARY KEY REFERENCES LedgerEntries(key),
                reversal_key TEXT NOT NULL UNIQUE REFERENCES LedgerEntries(key),
                replacement_key TEXT NOT NULL UNIQUE REFERENCES LedgerEntries(key), reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
            CREATE TABLE LedgerReviews(sequence INTEGER PRIMARY KEY, entry_key TEXT NOT NULL
                REFERENCES LedgerEntries(key), reviewed INTEGER NOT NULL CHECK(reviewed IN (0,1)), reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
            CREATE TABLE LedgerStatements(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE LedgerReconciliations(sequence INTEGER PRIMARY KEY, statement_id TEXT NOT NULL
                REFERENCES LedgerStatements(id), ledger_version TEXT NOT NULL, result TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        """)
        for table in (
            "LedgerAccounts",
            "LedgerObservations",
            "LedgerEntries",
            "LedgerAllocations",
            "LedgerCorrections",
            "LedgerReviews",
            "LedgerMeta",
            "LedgerStatements",
            "LedgerReconciliations",
        ):
            for action in ("UPDATE", "DELETE"):
                self.connection.execute(
                    f"CREATE TRIGGER {table}_{action} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Posted ledger history is immutable'); END"
                )
        self.connection.execute("COMMIT")

    def accounts(self) -> dict[str, LedgerAccount]:
        result = {}
        for account_id, payload in self.connection.execute("SELECT id,payload FROM LedgerAccounts"):
            data = json.loads(payload)
            data["kind"] = AccountKind(data["kind"])
            result[account_id] = LedgerAccount(**data)
        return result

    def observations(self) -> dict[str, Observation]:
        result = {}
        for observation_id, payload in self.connection.execute("SELECT id,payload FROM LedgerObservations"):
            data = json.loads(payload)
            data["posting_date"] = date.fromisoformat(data["posting_date"])
            result[observation_id] = Observation(**data)
        return result

    def add_account(self, account: LedgerAccount) -> None:
        account.validate()
        payload = encoded(asdict(account))
        with self._transaction():
            existing = self.connection.execute(
                "SELECT payload FROM LedgerAccounts WHERE id=?", (account.id,)
            ).fetchone()
            if existing:
                if existing[0] != payload:
                    raise LedgerError("Account identity already has a different mapping.")
                return
            self.connection.execute(
                "INSERT INTO LedgerAccounts VALUES (?,?,?)", (account.id, account.source_account_id, payload)
            )

    def add_observation(self, observation: Observation) -> None:
        with self._transaction():
            observation.validate(self.accounts())
            data = asdict(observation)
            data["posting_date"] = observation.posting_date.isoformat()
            payload = encoded(data)
            existing = self.connection.execute(
                "SELECT payload FROM LedgerObservations WHERE id=?", (observation.id,)
            ).fetchone()
            if existing:
                if existing[0] != payload:
                    raise LedgerError("Evidence identity already has different source facts.")
                return
            self.connection.execute(
                "INSERT INTO LedgerObservations VALUES (?,?,?)", (observation.id, observation.account_id, payload)
            )

    def consumed(self) -> dict[str, int]:
        return dict(
            self.connection.execute("""
            SELECT observation_id,sum(amount) FROM LedgerAllocations
            WHERE entry_key NOT IN (SELECT original_key FROM LedgerCorrections)
            GROUP BY observation_id
        """)
        )

    def _existing(self, entry: JournalEntry) -> bool:
        row = self.connection.execute("SELECT payload FROM LedgerEntries WHERE key=?", (entry.key,)).fetchone()
        if row is None:
            return False
        if row[0] != encoded(entry.payload()):
            raise LedgerError("Idempotency key already identifies different journal contents.")
        return True

    def _insert(self, entry: JournalEntry, usage: dict[str, int]):
        self.connection.execute(
            "INSERT INTO LedgerEntries(key,payload) VALUES (?,?)", (entry.key, encoded(entry.payload()))
        )
        self.connection.executemany(
            "INSERT INTO LedgerAllocations VALUES (?,?,?)",
            [(entry.key, observation_id, amount) for observation_id, amount in usage.items()],
        )

    def post(self, entry: JournalEntry) -> str:
        with self._transaction():
            if not self._existing(entry):
                usage = validate_entry(entry, self.accounts(), self.observations(), self.consumed())
                self._insert(entry, usage)
        return entry.key

    def load_batch(
        self,
        accounts: list[LedgerAccount],
        observations: list[Observation],
        statements: list[StatementEvidence],
        entries: list[JournalEntry],
    ) -> None:
        """Apply a deterministic shadow plan atomically, including replay checks.

        Load validation context once rather than rereading all observations for
        every entry. A bad item rolls back the entire batch, including mappings.
        """
        with self._transaction():
            known_accounts = self.accounts()
            known_observations = self.observations()
            known_statements = dict(self.connection.execute("SELECT id,payload FROM LedgerStatements"))
            known_entries = dict(self.connection.execute("SELECT key,payload FROM LedgerEntries"))
            used = self.consumed()
            for account in accounts:
                account.validate()
                if account.id in known_accounts:
                    if known_accounts[account.id] != account:
                        raise LedgerError("Account identity already has a different mapping.")
                    continue
                self.connection.execute(
                    "INSERT INTO LedgerAccounts VALUES (?,?,?)",
                    (account.id, account.source_account_id, encoded(asdict(account))),
                )
                known_accounts[account.id] = account
            for observation in observations:
                observation.validate(known_accounts)
                if observation.id in known_observations:
                    if known_observations[observation.id] != observation:
                        raise LedgerError("Evidence identity already has different source facts.")
                    continue
                data = asdict(observation)
                data["posting_date"] = observation.posting_date.isoformat()
                self.connection.execute(
                    "INSERT INTO LedgerObservations VALUES (?,?,?)",
                    (observation.id, observation.account_id, encoded(data)),
                )
                known_observations[observation.id] = observation
            for statement in statements:
                statement.validate(known_accounts, known_observations)
                payload = encoded(statement.payload())
                if statement.id in known_statements:
                    if known_statements[statement.id] != payload:
                        raise LedgerError("Statement identity already has different source facts.")
                    continue
                self.connection.execute("INSERT INTO LedgerStatements VALUES (?,?)", (statement.id, payload))
                known_statements[statement.id] = payload
            for entry in entries:
                payload = encoded(entry.payload())
                if entry.key in known_entries:
                    if known_entries[entry.key] != payload:
                        raise LedgerError("Idempotency key already identifies different journal contents.")
                    continue
                usage = validate_entry(entry, known_accounts, known_observations, used)
                self._insert(entry, usage)
                for key, amount in usage.items():
                    used[key] = used.get(key, 0) + amount
                known_entries[entry.key] = payload

    def correct(self, original_key: str, replacement: JournalEntry, *, reason: str) -> str:
        """Atomically reverse and replace; release evidence only in the same transaction."""
        identifier(reason)
        with self._transaction():
            existing = self.connection.execute(
                "SELECT replacement_key,reason FROM LedgerCorrections WHERE original_key=?", (original_key,)
            ).fetchone()
            if existing:
                if existing == (replacement.key, reason) and self._existing(replacement):
                    return replacement.key
                raise LedgerError("Entry already has a different correction.")
            row = self.connection.execute("SELECT payload FROM LedgerEntries WHERE key=?", (original_key,)).fetchone()
            if row is None:
                raise LedgerError("Original entry does not exist.")
            original = decode_entry(row[0])
            if original.origin == "reversal" or replacement.key == original.key or self._existing(replacement):
                raise LedgerError("Correction requires an active original and a new replacement.")
            if replacement.event_id != original.event_id:
                raise LedgerError("A correction must preserve the economic event identity.")
            consumed = self.consumed()
            for observation_id, amount in self.connection.execute(
                "SELECT observation_id,amount FROM LedgerAllocations WHERE entry_key=?", (original_key,)
            ):
                consumed[observation_id] -= amount
            usage = validate_entry(replacement, self.accounts(), self.observations(), consumed)
            reversal = JournalEntry(
                key="reversal:" + hashlib.sha256(original_key.encode()).hexdigest(),
                event_id=original.event_id,
                posting_date=original.posting_date,
                description="Reversal: " + original.description,
                postings=tuple(Posting(p.account_id, -p.amount_minor) for p in original.postings),
                origin="reversal",
                reviewed=True,
                reason=reason,
            )
            self._insert(reversal, {})
            self._insert(replacement, usage)
            self.connection.execute(
                "INSERT INTO LedgerCorrections(original_key,reversal_key,replacement_key,reason) VALUES (?,?,?,?)",
                (original_key, reversal.key, replacement.key, reason),
            )
        return replacement.key

    def review(self, key: str, *, reviewed: bool, reason: str) -> None:
        identifier(reason)
        if type(reviewed) is not bool:
            raise LedgerError("Review assertion must be explicit.")
        with self._transaction():
            row = self.connection.execute("SELECT payload FROM LedgerEntries WHERE key=?", (key,)).fetchone()
            if row is None:
                raise LedgerError("Entry does not exist.")
            entry = decode_entry(row[0])
            accounts = self.accounts()
            if reviewed and any(accounts[p.account_id].purpose == "suspense" for p in entry.postings):
                raise LedgerError("Suspense must remain unresolved until corrected.")
            self.connection.execute(
                "INSERT INTO LedgerReviews(entry_key,reviewed,reason) VALUES (?,?,?)", (key, int(reviewed), reason)
            )

    def balances(self, cutoff: date) -> dict[str, int]:
        totals = dict.fromkeys(self.accounts(), 0)
        for (payload,) in self.connection.execute("SELECT payload FROM LedgerEntries ORDER BY key"):
            entry = decode_entry(payload)
            if entry.posting_date <= cutoff:
                for posting in entry.postings:
                    totals[posting.account_id] += posting.amount_minor
        return totals

    def evidence_remaining(self) -> dict[str, int]:
        used = self.consumed()
        return {key: observation.amount_minor - used.get(key, 0) for key, observation in self.observations().items()}

    def entry_status(self, key: str) -> dict:
        row = self.connection.execute("SELECT payload FROM LedgerEntries WHERE key=?", (key,)).fetchone()
        if row is None:
            raise LedgerError("Entry does not exist.")
        entry = decode_entry(row[0])
        review = self.connection.execute(
            "SELECT reviewed FROM LedgerReviews WHERE entry_key=? ORDER BY sequence DESC LIMIT 1", (key,)
        ).fetchone()
        corrected = self.connection.execute("SELECT 1 FROM LedgerCorrections WHERE original_key=?", (key,)).fetchone()
        return {
            "posted": True,
            "reviewed": bool(review[0]) if review else entry.reviewed,
            "superseded": bool(corrected),
            # Reconciliation is account/statement scoped, never inferred here.
            "statement_reconciled": None,
        }

    def add_statement(self, statement: StatementEvidence) -> None:
        with self._transaction():
            statement.validate(self.accounts(), self.observations())
            payload = encoded(statement.payload())
            existing = self.connection.execute(
                "SELECT payload FROM LedgerStatements WHERE id=?", (statement.id,)
            ).fetchone()
            if existing:
                if existing[0] != payload:
                    raise LedgerError("Statement identity already has different source facts.")
                return
            self.connection.execute("INSERT INTO LedgerStatements VALUES (?,?)", (statement.id, payload))

    def _ledger_version(self) -> str:
        # Conservative invalidation: any new posted entry reopens prior checks.
        rows = self.connection.execute("SELECT key,payload FROM LedgerEntries ORDER BY key").fetchall()
        return hashlib.sha256(encoded(rows).encode()).hexdigest()

    def reconcile(self, statement_id: str) -> dict:
        with self._transaction():
            row = self.connection.execute("SELECT payload FROM LedgerStatements WHERE id=?", (statement_id,)).fetchone()
            if row is None:
                raise LedgerError("Statement does not exist.")
            data = json.loads(row[0])
            data["start_date"] = date.fromisoformat(data["start_date"])
            data["end_date"] = date.fromisoformat(data["end_date"])
            data["observation_ids"] = tuple(data["observation_ids"])
            statement = StatementEvidence(**data)
            entries = [decode_entry(row[0]) for row in self.connection.execute("SELECT payload FROM LedgerEntries")]
            superseded = {row[0] for row in self.connection.execute("SELECT original_key FROM LedgerCorrections")}
            result = evaluate_statement(
                statement, self.accounts(), self.observations(), entries, superseded, self.evidence_remaining()
            )
            self.connection.execute(
                "INSERT INTO LedgerReconciliations(statement_id,ledger_version,result) VALUES (?,?,?)",
                (statement_id, self._ledger_version(), encoded(result)),
            )
            return result

    def reconciliation_status(self, statement_id: str) -> dict:
        row = self.connection.execute(
            "SELECT ledger_version,result FROM LedgerReconciliations WHERE statement_id=? ORDER BY sequence DESC LIMIT 1",
            (statement_id,),
        ).fetchone()
        if row is None:
            return {"status": "not_checked", "reconciled": False}
        result = json.loads(row[1])
        if row[0] != self._ledger_version():
            return {"status": "stale", "reconciled": False, "previous_result": result}
        return {"status": "current", **result}

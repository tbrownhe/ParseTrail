"""Fresh 2.0 SQLite profile for immutable source and parser evidence snapshots.

This store has no reader or migration path for 1.x data. Accounting review is a
separate stage; every imported observation starts pending and unposted.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from parsetrail.core.source_evidence import SourceEvidence, StatementPayload

APPLICATION_ID = 0x50543230  # PT20
SCHEMA_VERSION = 2
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_DEFINITION_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
TABLE_COLUMNS = {
    "Sources": (("sha256", "TEXT", 1), ("suffix", "TEXT", 0), ("size", "INTEGER", 0), ("content", "BLOB", 0)),
    "Definitions": (("sha256", "TEXT", 1), ("size", "INTEGER", 0), ("content", "BLOB", 0)),
    "EvidenceSnapshots": (
        ("source_sha256", "TEXT", 1),
        ("definition_sha256", "TEXT", 0),
        ("size", "INTEGER", 0),
        ("sha256", "TEXT", 0),
        ("content", "BLOB", 0),
    ),
    "SourceObservations": (
        ("row_id", "TEXT", 1),
        ("source_sha256", "TEXT", 0),
        ("source_account", "TEXT", 0),
        ("source_account_form", "TEXT", 0),
        ("row_role", "TEXT", 0),
        ("date_role", "TEXT", 0),
        ("observed_date", "TEXT", 0),
        ("amount_minor", "INTEGER", 0),
    ),
}
FOREIGN_KEYS = {
    "Sources": (),
    "Definitions": (),
    "EvidenceSnapshots": (("definition_sha256", "Definitions", "sha256"), ("source_sha256", "Sources", "sha256")),
    "SourceObservations": (("source_sha256", "Sources", "sha256"),),
}


class ProfileFormatError(ValueError):
    """A profile or saved snapshot is unsupported or damaged."""


@dataclass(frozen=True)
class SavedImport:
    source: bytes
    definition: bytes
    evidence: SourceEvidence
    suffix: Literal[".csv", ".pdf"]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rows(evidence: SourceEvidence):
    payload = evidence.payload
    if isinstance(payload, StatementPayload):
        return tuple(row for account in payload.accounts for row in account.rows)
    return payload.rows


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
                (row[1], row[2], row[5]) for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if actual_columns != columns:
                raise ProfileFormatError("profile_schema_mismatch")
            actual_foreign_keys = tuple(
                (row[3], row[2], row[4]) for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            )
            if actual_foreign_keys != FOREIGN_KEYS[table]:
                raise ProfileFormatError("profile_schema_mismatch")
        expected_triggers = {
            f"immutable_{table}_{action}" for table in TABLE_COLUMNS for action in ("update", "delete")
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
                    source_account TEXT NOT NULL,
                    source_account_form TEXT NOT NULL CHECK(source_account_form IN ('full','last_four','opaque')),
                    row_role TEXT NOT NULL CHECK(row_role IN ('activity','period_summary')),
                    date_role TEXT NOT NULL CHECK(date_role IN ('posting_date','activity_date','statement_period_end')),
                    observed_date TEXT NOT NULL, amount_minor INTEGER NOT NULL
                );
                COMMIT;
            """)
            for table in ("Sources", "Definitions", "EvidenceSnapshots", "SourceObservations"):
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

    def source_imported(self, source: bytes) -> bool:
        """Check an exact-source retry before invoking a parser."""
        if type(source) is not bytes or not 0 < len(source) <= MAX_SOURCE_BYTES:
            raise ProfileFormatError("source_size")
        return (
            self.connection.execute("SELECT 1 FROM Sources WHERE sha256=?", (_digest(source),)).fetchone() is not None
        )

    def import_source(
        self, source: bytes, definition: bytes, evidence: SourceEvidence, *, suffix: Literal[".csv", ".pdf"]
    ) -> bool:
        """Atomically save one admitted snapshot. False means exact-source retry."""
        if self.read_only:
            raise ProfileFormatError("profile_read_only")
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

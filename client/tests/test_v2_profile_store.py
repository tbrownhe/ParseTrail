"""Fresh profile saves strict source evidence without posting or old-format writes."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from parsetrail.core.v2_citi_source_output import from_citi
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

from devtools.parser_engine_pilot.citi_authoring import DEFINITION_BYTES
from devtools.parser_engine_pilot.test_citi_source_output import sample

CSV_DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()
CSV = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"


def test_one_database_reopens_csv_and_statement_without_reparse(tmp_path: Path) -> None:
    path = tmp_path / "fresh-2.0.db"
    csv_evidence = build_source_evidence(CSV, CSV_DEFINITION, suffix=".csv")
    pdf = b"synthetic statement bytes"
    citi = from_citi(sample(), DEFINITION_BYTES).model_copy(update={"source_sha256": hashlib.sha256(pdf).hexdigest()})
    with V2ProfileStore.create(path) as store:
        assert not store.source_imported(CSV)
        assert store.import_source(CSV, CSV_DEFINITION, csv_evidence, suffix=".csv")
        assert store.source_imported(CSV)
        assert store.import_source(pdf, DEFINITION_BYTES, citi, suffix=".pdf")
        assert not store.import_source(CSV, CSV_DEFINITION, csv_evidence, suffix=".csv")
        assert store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone() == (2,)
        assert store.connection.execute("SELECT DISTINCT row_role FROM SourceObservations").fetchall() == [
            ("activity",)
        ]
        assert store.connection.execute("SELECT count(*) FROM sqlite_master WHERE name='LedgerEntries'").fetchone() == (
            0,
        )
    with V2ProfileStore.open(path, read_only=True) as reopened:
        csv_saved = reopened.load_import(csv_evidence.source_sha256)
        citi_saved = reopened.load_import(citi.source_sha256)
        assert csv_saved.source == CSV and csv_saved.evidence == csv_evidence
        assert citi_saved.source == pdf and citi_saved.evidence == citi
        assert citi_saved.evidence.payload.capture_verified is False
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            reopened.import_source(CSV, CSV_DEFINITION, csv_evidence, suffix=".csv")


@pytest.mark.parametrize("kind", ["legacy", "newer", "unknown", "corrupt"])
def test_unsupported_profile_is_refused_before_write(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "profile.db"
    if kind == "corrupt":
        path.write_bytes(b"not a database")
    else:
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE Sentinel(value TEXT)")
            connection.execute("INSERT INTO Sentinel VALUES ('untouched')")
            if kind == "newer":
                connection.execute("PRAGMA application_id=1347691056")
                connection.execute("PRAGMA user_version=99")
            elif kind == "legacy":
                connection.execute("PRAGMA user_version=1")
    original = path.read_bytes()
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.open(path)
    assert path.read_bytes() == original


def test_failed_import_leaves_no_source_or_observation(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    evidence = build_source_evidence(CSV, CSV_DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        with pytest.raises(ProfileFormatError, match="evidence_hash_mismatch"):
            store.import_source(CSV + b"changed", CSV_DEFINITION, evidence, suffix=".csv")
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone() == (0,)


def test_saved_blob_integrity_is_checked_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    evidence = build_source_evidence(CSV, CSV_DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(CSV, CSV_DEFINITION, evidence, suffix=".csv")
    with sqlite3.connect(path) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_EvidenceSnapshots_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_EvidenceSnapshots_update")
        connection.execute("UPDATE EvidenceSnapshots SET content=?", (b"{}",))
        connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="saved_snapshot_integrity"):
            store.load_import(evidence.source_sha256)


def test_changed_schema_is_refused_before_writable_open(tmp_path: Path) -> None:
    path = tmp_path / "altered.db"
    with V2ProfileStore.create(path):
        pass
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER immutable_Sources_update")
    original = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="profile_schema_mismatch"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == original

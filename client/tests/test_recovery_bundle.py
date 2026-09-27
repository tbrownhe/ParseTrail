import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from parsetrail.core import recovery_bundle as recovery


@pytest.fixture
def sources(tmp_path):
    source = tmp_path / "source #1.db"
    archive = tmp_path / "statements"
    (archive / "SUCCESS").mkdir(parents=True)
    (archive / "FAIL").mkdir()
    (archive / "SUCCESS" / "synthetic.pdf").write_bytes(b"synthetic statement")
    (archive / "FAIL" / "unparsed.csv").write_bytes(b"synthetic pending evidence")
    (archive / "pending.zip").write_bytes(b"opaque nested export; not extracted")
    (archive / "README.txt").write_text("Synthetic export instructions")
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.executescript("""
            CREATE TABLE alembic_version(version_num TEXT);
            INSERT INTO alembic_version VALUES ('synthetic');
            CREATE TABLE Accounts(id INTEGER PRIMARY KEY);
            INSERT INTO Accounts VALUES (1);
            CREATE TABLE Transactions(id INTEGER PRIMARY KEY, amount INTEGER, note TEXT, evidence BLOB);
            INSERT INTO Transactions VALUES (1, -12345, 'synthetic exact money', X'00FF');
            CREATE TABLE Statements(StatementID INTEGER PRIMARY KEY, Filename TEXT,
                ContentHashAlgorithm TEXT, ContentHash TEXT, account INTEGER REFERENCES Accounts(id));
            CREATE TABLE StatementTransactions(statement INTEGER REFERENCES Statements(StatementID),
                tx INTEGER REFERENCES Transactions(id));
        """)
        for i in (1, 2):
            connection.execute(
                "INSERT INTO Statements VALUES (?, ?, ?, ?, 1)",
                (i, "synthetic.pdf", "sha256", hashlib.sha256(b"synthetic statement").hexdigest()),
            )
            connection.execute("INSERT INTO StatementTransactions VALUES (?, 1)", (i,))
    return source, archive


def test_bundle_restores_without_original_database_or_archive(sources, tmp_path):
    source, archive = sources
    before = source.read_bytes()
    report = recovery.create_bundle(source, archive, tmp_path / "backup")
    assert source.read_bytes() == before
    assert report["references"] == {"statement_count": 2, "referenced_file_count": 1, "problems": []}
    source.rename(source.with_suffix(".unavailable"))
    archive.rename(tmp_path / "unavailable")
    restored = tmp_path / "isolated"
    result = recovery.restore_bundle(tmp_path / "backup/recovery.zip", restored)
    assert result["database"] == report["database"]
    assert (restored / "archive/FAIL/unparsed.csv").read_bytes() == b"synthetic pending evidence"
    assert recovery.digest(restored / "database.db") == report["members"]["database.db"]["sha256"]
    with closing(recovery.read_only(restored / "database.db")) as connection:
        assert connection.execute("SELECT amount,evidence FROM Transactions").fetchone() == (-12345, b"\0\xff")


def test_wal_commits_are_included(sources, tmp_path):
    source, archive = sources
    writer = sqlite3.connect(source)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO Transactions VALUES (2, 99, 'committed WAL', NULL)")
        writer.commit()
        report = recovery.create_bundle(source, archive, tmp_path / "backup")
        assert report["database"]["row_counts"]["Transactions"] == 2
    finally:
        writer.close()


@pytest.mark.parametrize("problem", ["missing", "hash_mismatch"])
def test_missing_or_corrupt_archive_never_publishes_bundle(sources, tmp_path, problem):
    source, archive = sources
    path = archive / "SUCCESS/synthetic.pdf"
    if problem == "missing":
        path.unlink()
    else:
        path.write_bytes(b"changed evidence")
    output = tmp_path / "backup"
    with pytest.raises(recovery.RecoveryError, match="Missing or mismatched"):
        recovery.create_bundle(source, archive, output)
    assert not (output / "recovery.zip").exists()
    report = json.loads((output / "source-review.json").read_text())
    assert [p["reason"] for p in report["problems"]] == [problem, problem]


def test_foreign_key_violation_blocks_backup(sources, tmp_path):
    source, archive = sources
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("UPDATE Statements SET account=999")
    with pytest.raises(recovery.RecoveryError, match="foreign-key"):
        recovery.create_bundle(source, archive, tmp_path / "backup")


def test_output_refuses_overwrite_and_source_nesting(sources, tmp_path):
    source, archive = sources
    recovery.create_bundle(source, archive, tmp_path / "backup")
    with pytest.raises(FileExistsError):
        recovery.create_bundle(source, archive, tmp_path / "backup")
    with pytest.raises(recovery.RecoveryError, match="outside"):
        recovery.create_bundle(source, archive, archive / "backup")
    with pytest.raises(FileExistsError):
        recovery.restore_bundle(tmp_path / "backup/recovery.zip", archive)


def test_unexpected_files_are_not_silently_bundled(sources, tmp_path):
    source, archive = sources
    (archive / "config.json").write_text('"synthetic secret"')
    with pytest.raises(recovery.RecoveryError, match="unsupported file"):
        recovery.create_bundle(source, archive, tmp_path / "backup")


@pytest.mark.parametrize(
    "name",
    [
        "../escaped",
        "/absolute",
        "archive/../escaped",
        "archive/C:/x",
        "archive/CON.pdf",
        "archive/back\\slash",
        "archive/trailing.",
    ],
)
def test_restore_rejects_unsafe_paths_before_writing(tmp_path, name):
    bundle = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(bundle, "w") as output:
        output.writestr(name, b"unsafe")
    with pytest.raises(recovery.RecoveryError):
        recovery.restore_bundle(bundle, tmp_path / "restore")
    assert not (tmp_path / "restore").exists()


@pytest.mark.parametrize("corruption", ["bytes", "missing", "extra", "semantic"])
def test_restore_rejects_corrupt_or_inconsistent_bundle(sources, tmp_path, corruption):
    source, archive = sources
    recovery.create_bundle(source, archive, tmp_path / "backup")
    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(tmp_path / "backup/recovery.zip") as original, zipfile.ZipFile(corrupt, "w") as output:
        for name in original.namelist():
            if name == "archive/SUCCESS/synthetic.pdf" and corruption == "missing":
                continue
            data = original.read(name)
            if name == "archive/SUCCESS/synthetic.pdf" and corruption == "bytes":
                data = b"x" * len(data)
            if name == "manifest.json" and corruption == "semantic":
                manifest = json.loads(data)
                manifest["database"]["semantic_sha256"] = "bad"
                data = json.dumps(manifest).encode()
            output.writestr(name, data)
        if corruption == "extra":
            output.writestr("archive/extra.pdf", b"unexpected")
    with pytest.raises(recovery.RecoveryError):
        recovery.restore_bundle(corrupt, tmp_path / "restore")
    assert not (tmp_path / "restore/restore-verification.json").exists()

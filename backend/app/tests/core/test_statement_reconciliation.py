from collections.abc import Generator
from pathlib import Path

import pytest
from app.core.statement_reconciliation import compare_statement_storage, quarantine_orphan_files


@pytest.fixture(scope="module", autouse=True)
def db() -> Generator[None, None, None]:
    """Storage reconciliation unit tests do not use database integration."""
    yield


def test_reports_orphan_files_and_rows_without_reading_contents(tmp_path: Path) -> None:
    (tmp_path / "registered.enc").write_bytes(b"encrypted")
    (tmp_path / "orphan.enc").write_bytes(b"encrypted")
    (tmp_path / "ignored.tmp").write_bytes(b"partial")

    report = compare_statement_storage(
        tmp_path,
        {"registered.enc", "missing.enc"},
    )

    assert report.orphan_files == ("orphan.enc",)
    assert report.missing_files == ("missing.enc",)
    assert report.consistent is False


def test_quarantines_only_explicitly_reported_encrypted_orphans(tmp_path: Path) -> None:
    statement_dir = tmp_path / "statements"
    quarantine_dir = tmp_path / "quarantine"
    statement_dir.mkdir()
    orphan = statement_dir / "orphan.enc"
    retained = statement_dir / "registered.enc"
    orphan.write_bytes(b"orphan ciphertext")
    retained.write_bytes(b"registered ciphertext")

    quarantine_orphan_files(statement_dir, quarantine_dir, (orphan.name,))

    assert not orphan.exists()
    assert (quarantine_dir / orphan.name).read_bytes() == b"orphan ciphertext"
    assert retained.read_bytes() == b"registered ciphertext"


def test_refuses_unsafe_or_overwriting_quarantine_targets(tmp_path: Path) -> None:
    statement_dir = tmp_path / "statements"
    quarantine_dir = tmp_path / "quarantine"
    statement_dir.mkdir()
    quarantine_dir.mkdir()
    (statement_dir / "orphan.enc").write_bytes(b"source")
    (quarantine_dir / "orphan.enc").write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        quarantine_orphan_files(statement_dir, quarantine_dir, ("orphan.enc",))
    with pytest.raises(ValueError):
        quarantine_orphan_files(statement_dir, quarantine_dir, ("../escape.enc",))

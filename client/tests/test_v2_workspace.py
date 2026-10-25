"""A 2.0 workspace imports only local bytes through a verified catalog."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import MAX_CATALOG_BYTES, CatalogError, CatalogRollbackError, key_id_for_public_key
from parsetrail.core.v2_profile_store import MAX_SOURCE_BYTES, ProfileFormatError
from parsetrail.core.v2_source_import import ImportCancelled
from parsetrail.core.v2_workspace import V2Workspace, WorkspaceError, folder_source_files
from scripts.v2_catalog_release import signed_catalog_bytes

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()
SOURCE = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"


def _workspace(tmp_path: Path) -> V2Workspace:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / "synthetic-posted-cash-definition.json").write_bytes(DEFINITION)
    snapshot, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    workspace = V2Workspace.create(
        tmp_path / "fresh.db", tmp_path / "catalog", trusted_keys={key_id_for_public_key(public): public}
    )
    workspace.catalog_cache.activate(snapshot, signature)
    return workspace


def test_verified_file_import_reopens_without_modifying_source(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source_path = tmp_path / "statement.csv"
    source_path.write_bytes(SOURCE)
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    first = workspace.import_file(source_path)
    second = workspace.import_file(source_path)
    assert (first.status, second.status) == ("imported", "already_imported")
    assert workspace.source_ids() == (first.source_sha256,)
    assert workspace.saved_import(first.source_sha256).source == SOURCE
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == before
    reopened = V2Workspace.open(
        workspace.profile_path, workspace.catalog_cache.root, trusted_keys=workspace.catalog_cache.trusted_keys
    )
    assert reopened.source_ids() == (first.source_sha256,)
    assert reopened.saved_import(first.source_sha256).evidence == first.evidence


def test_batch_import_keeps_successes_and_reports_each_selected_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    missing = tmp_path / "missing.pdf"
    first.write_bytes(SOURCE)
    second.write_bytes(SOURCE.replace(b"Coffee", b"Tea"))
    progress = []
    result = workspace.import_files(
        (first, missing, first, second), progress=lambda count, item: progress.append((count, item.status))
    )
    assert [item.status for item in result.files] == ["imported", "failed", "already_imported", "imported"]
    assert result.files[1].error_code == "source_unavailable"
    assert progress == [(1, "imported"), (2, "failed"), (3, "already_imported"), (4, "imported")]
    assert not result.cancelled
    assert len(workspace.source_ids()) == 2
    assert first.read_bytes() == SOURCE


def test_batch_cancellation_keeps_completed_files_and_marks_rest_untouched(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    sources = tuple(tmp_path / f"{index}.csv" for index in range(3))
    for index, source in enumerate(sources):
        source.write_bytes(SOURCE.replace(b"Coffee", f"Coffee {index}".encode()))
    completed = []
    result = workspace.import_files(
        sources,
        cancelled=lambda: bool(completed),
        progress=lambda _count, item: completed.append(item.status),
    )
    assert [item.status for item in result.files] == ["imported", "not_attempted", "not_attempted"]
    assert result.cancelled
    assert len(workspace.source_ids()) == 1


def test_folder_batch_selection_is_shallow_and_supports_only_source_files(tmp_path: Path) -> None:
    folder = tmp_path / "selected"
    folder.mkdir()
    (folder / "b.PDF").write_bytes(b"pdf")
    (folder / "a.csv").write_bytes(SOURCE)
    (folder / "note.txt").write_text("ignored")
    nested = folder / "nested"
    nested.mkdir()
    (nested / "not-selected.csv").write_bytes(SOURCE)
    assert [path.name for path in folder_source_files(folder)] == ["a.csv", "b.PDF"]
    empty = folder / "empty"
    empty.mkdir()
    with pytest.raises(WorkspaceError, match="source_folder_has_no_supported_files"):
        folder_source_files(empty)


def test_missing_catalog_leaves_profile_empty(tmp_path: Path) -> None:
    workspace = V2Workspace.create(tmp_path / "fresh.db", tmp_path / "catalog", trusted_keys={})
    source_path = tmp_path / "statement.csv"
    source_path.write_bytes(SOURCE)
    before = hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest()
    with pytest.raises(WorkspaceError, match="verified_catalog_missing"):
        workspace.import_file(source_path)
    assert workspace.source_ids() == ()
    assert hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest() == before


def test_unsupported_and_oversized_sources_leave_profile_empty(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    allowed = tmp_path / "valid.csv"
    allowed.write_bytes(SOURCE)
    with pytest.raises(ImportCancelled):
        workspace.import_file(allowed, cancelled=lambda: True)
    unsupported = tmp_path / "source.txt"
    unsupported.write_bytes(SOURCE)
    with pytest.raises(WorkspaceError, match="unsupported_source_type"):
        workspace.import_file(unsupported)
    oversized = tmp_path / "source.csv"
    with oversized.open("wb") as stream:
        stream.truncate(MAX_SOURCE_BYTES + 1)
    with pytest.raises(WorkspaceError, match="source_size"):
        workspace.import_file(oversized)
    assert workspace.source_ids() == ()


def test_non_v2_profile_is_rejected_before_import(tmp_path: Path) -> None:
    profile = tmp_path / "old.db"
    with sqlite3.connect(profile) as connection:
        connection.execute("CREATE TABLE LegacySentinel(value TEXT)")
        connection.execute("INSERT INTO LegacySentinel VALUES ('unchanged')")
    before = profile.read_bytes()
    with pytest.raises(ProfileFormatError):
        V2Workspace.open(profile, tmp_path / "catalog", trusted_keys={})
    assert profile.read_bytes() == before


def test_local_signed_catalog_install_is_idempotent_and_refuses_rollback(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / "cash-definition.json").write_bytes(DEFINITION)
    workspace = V2Workspace.create(
        tmp_path / "fresh.db", tmp_path / "cache", trusted_keys={key_id_for_public_key(public): public}
    )

    def release(sequence: int) -> Path:
        snapshot, signature, _verified = signed_catalog_bytes(
            definitions, private, release_sequence=sequence, source_revision="a" * 40
        )
        directory = tmp_path / f"release-{sequence}"
        directory.mkdir()
        (directory / "catalog.json").write_bytes(snapshot)
        (directory / "catalog.sig").write_bytes(signature)
        return directory

    first, second = release(1), release(2)
    assert workspace.install_catalog_release(first).release_sequence == 1
    assert workspace.install_catalog_release(first).release_sequence == 1
    assert workspace.install_catalog_release(second).release_sequence == 2
    with pytest.raises(CatalogRollbackError, match="catalog_rollback"):
        workspace.install_catalog_release(first)
    assert workspace.catalog_cache.load_current().release_sequence == 2
    source = tmp_path / "cash.csv"
    source.write_bytes(SOURCE)
    assert workspace.import_file(source).status == "imported"


def test_local_catalog_refusal_does_not_replace_current_release(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / "cash-definition.json").write_bytes(DEFINITION)
    workspace = V2Workspace.create(
        tmp_path / "fresh.db", tmp_path / "cache", trusted_keys={key_id_for_public_key(public): public}
    )
    release = tmp_path / "release"
    release.mkdir()
    snapshot, signature, _verified = signed_catalog_bytes(
        definitions, private, release_sequence=1, source_revision="a" * 40
    )
    (release / "catalog.json").write_bytes(snapshot)
    (release / "catalog.sig").write_bytes(signature)
    workspace.install_catalog_release(release)
    (release / "catalog.sig").write_bytes(b"\x00" * len(signature))
    with pytest.raises(CatalogError, match="invalid_signature"):
        workspace.install_catalog_release(release)
    (release / "catalog.json").write_bytes(b"x" * (MAX_CATALOG_BYTES + 1))
    with pytest.raises(CatalogError, match="catalog_cache_shape"):
        workspace.install_catalog_release(release)
    with pytest.raises(CatalogError, match="catalog_release_directory"):
        workspace.install_catalog_release(tmp_path / "missing")
    assert workspace.catalog_cache.load_current().snapshot == snapshot

"""A 2.0 workspace imports only local bytes through a verified catalog."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_profile_store import MAX_SOURCE_BYTES, ProfileFormatError
from parsetrail.core.v2_source_import import ImportCancelled
from parsetrail.core.v2_workspace import V2Workspace, WorkspaceError
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

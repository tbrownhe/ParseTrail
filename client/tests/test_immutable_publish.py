from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.immutable_publish import PublishError, publish_release


class FakeTransport:
    def __init__(self, *, pointer: bytes = b'{"release_sequence":1,"schema_version":1}\n') -> None:
        self.files = {"/catalog/current-release.json": pointer}
        self.directories = {"/catalog", "/catalog/releases"}
        self.upload_count = 0
        self.fail_upload_at: int | None = None
        self.corrupt_hash_for: str | None = None
        self.activation_mode = "success"

    def exists(self, remote_path: str) -> bool:
        return remote_path in self.files or remote_path in self.directories

    def create_release(self, releases_root: str, release_dir: str) -> None:
        self.directories.add(releases_root)
        if self.exists(release_dir):
            raise PublishError("release exists")
        self.directories.add(release_dir)

    def upload(self, local_path: Path, remote_path: str) -> None:
        self.upload_count += 1
        if self.upload_count == self.fail_upload_at:
            raise PublishError("injected upload failure")
        self.files[remote_path] = local_path.read_bytes()

    def size(self, remote_path: str) -> int:
        return len(self.files[remote_path])

    def sha256(self, remote_path: str) -> str:
        if remote_path == self.corrupt_hash_for:
            return "0" * 64
        return hashlib.sha256(self.files[remote_path]).hexdigest()

    def replace(self, source_path: str, destination_path: str) -> None:
        if self.activation_mode == "interrupt-before":
            raise PublishError("injected activation interruption")
        self.files[destination_path] = self.files.pop(source_path)
        if self.activation_mode == "interrupt-after":
            raise PublishError("injected post-activation interruption")

    def read(self, remote_path: str, maximum_bytes: int) -> bytes | None:
        value = self.files.get(remote_path)
        if value is not None and len(value) > maximum_bytes:
            raise PublishError("oversized")
        return value


def _release(tmp_path: Path, sequence: int = 2) -> Path:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    artifact = b"compiled plugin"
    (release_dir / "parser.pyc").write_bytes(artifact)
    manifest = {
        "schema_version": 1,
        "release_sequence": sequence,
        "artifacts": [
            {
                "filename": "parser.pyc",
                "size": len(artifact),
                "sha256": hashlib.sha256(artifact).hexdigest(),
            }
        ],
    }
    (release_dir / "plugin-manifest.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    (release_dir / "plugin-manifest.sig").write_bytes(b"s" * 64)
    return release_dir


def _publish(release_dir: Path, transport: FakeTransport) -> int:
    return publish_release(
        release_dir=release_dir,
        manifest_name="plugin-manifest.json",
        signature_name="plugin-manifest.sig",
        remote_root="/catalog",
        transport=transport,
    )


def test_partial_upload_never_changes_visible_pointer(tmp_path: Path) -> None:
    release_dir = _release(tmp_path)
    transport = FakeTransport()
    original_pointer = transport.files["/catalog/current-release.json"]
    transport.fail_upload_at = 2

    with pytest.raises(PublishError, match="upload failure"):
        _publish(release_dir, transport)

    assert transport.files["/catalog/current-release.json"] == original_pointer


def test_remote_hash_mismatch_never_changes_visible_pointer(tmp_path: Path) -> None:
    release_dir = _release(tmp_path)
    transport = FakeTransport()
    original_pointer = transport.files["/catalog/current-release.json"]
    transport.corrupt_hash_for = "/catalog/releases/2/parser.pyc"

    with pytest.raises(PublishError, match="hash mismatch"):
        _publish(release_dir, transport)

    assert transport.files["/catalog/current-release.json"] == original_pointer


def test_interrupted_activation_preserves_old_pointer_when_move_did_not_happen(tmp_path: Path) -> None:
    release_dir = _release(tmp_path)
    transport = FakeTransport()
    original_pointer = transport.files["/catalog/current-release.json"]
    transport.activation_mode = "interrupt-before"

    with pytest.raises(PublishError, match="activation did not complete"):
        _publish(release_dir, transport)

    assert transport.files["/catalog/current-release.json"] == original_pointer


def test_interrupted_connection_after_atomic_activation_is_reconciled(tmp_path: Path) -> None:
    release_dir = _release(tmp_path)
    transport = FakeTransport()
    transport.activation_mode = "interrupt-after"

    assert _publish(release_dir, transport) == 2
    assert json.loads(transport.files["/catalog/current-release.json"])["release_sequence"] == 2


def test_existing_release_sequence_is_never_reused(tmp_path: Path) -> None:
    release_dir = _release(tmp_path)
    transport = FakeTransport()
    transport.directories.add("/catalog/releases/2")

    with pytest.raises(PublishError, match="already exists"):
        _publish(release_dir, transport)

    assert transport.upload_count == 0

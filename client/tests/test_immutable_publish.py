from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from scripts.immutable_publish import PublishError, SshTransport, publish_release


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

    def activate(self, source_path: str, destination_path: str, expected_pointer: bytes | None) -> None:
        if self.files.get(destination_path) != expected_pointer:
            raise PublishError("active pointer changed")
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


def _publish(
    release_dir: Path,
    transport: FakeTransport,
    *,
    inventory_name: str | None = None,
) -> int:
    return publish_release(
        release_dir=release_dir,
        manifest_name="plugin-manifest.json",
        signature_name="plugin-manifest.sig",
        inventory_name=inventory_name,
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


def test_publishes_and_verifies_release_inventory(tmp_path: Path) -> None:
    release_dir = _release(tmp_path)
    inventory_files = []
    for filename in ("parser.pyc", "plugin-manifest.json", "plugin-manifest.sig"):
        payload = (release_dir / filename).read_bytes()
        inventory_files.append(
            {
                "filename": filename,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    inventory = (
        json.dumps(
            {
                "schema_version": 1,
                "release_sequence": 2,
                "files": inventory_files,
            }
        ).encode()
        + b"\n"
    )
    (release_dir / "release-inventory.json").write_bytes(inventory)
    transport = FakeTransport()

    _publish(release_dir, transport, inventory_name="release-inventory.json")

    assert transport.files["/catalog/releases/2/release-inventory.json"] == inventory


@pytest.mark.parametrize(
    "pointer",
    [
        b'{"schema_version":1,"release_sequence":2}',
        b'{"schema_version":1,"release_sequence":9}',
        b"{}",
        b"[]",
        b"not json",
        b'{"schema_version":true,"release_sequence":1}',
        b'{"schema_version":1,"release_sequence":true}',
        b'{"schema_version":1,"release_sequence":0}',
    ],
)
def test_invalid_or_newer_active_pointer_prevents_upload(tmp_path, pointer):
    transport = FakeTransport(pointer=pointer)
    with pytest.raises(PublishError, match="pointer is invalid|must exceed"):
        _publish(_release(tmp_path), transport)
    assert transport.upload_count == 0
    assert "/catalog/releases/2" not in transport.directories
    assert transport.files["/catalog/current-release.json"] == pointer


def test_first_release_can_create_initial_pointer(tmp_path):
    transport = FakeTransport()
    transport.files.clear()
    assert _publish(_release(tmp_path), transport) == 2


def test_concurrent_publication_cannot_be_overwritten(tmp_path, monkeypatch):
    transport = FakeTransport()
    original_activate = transport.activate
    newer = b'{"schema_version":1,"release_sequence":3}'

    def concurrent(source, destination, expected):
        transport.files[destination] = newer
        original_activate(source, destination, expected)

    monkeypatch.setattr(transport, "activate", concurrent)
    with pytest.raises(PublishError, match="activation did not complete"):
        _publish(_release(tmp_path), transport)
    assert transport.files["/catalog/current-release.json"] == newer


def test_unreadable_pointer_after_connection_drop_reports_unknown_outcome(tmp_path, monkeypatch):
    transport = FakeTransport()
    transport.activation_mode = "interrupt-after"
    original_read = transport.read

    def read(path, limit):
        if transport.upload_count:
            raise PublishError("SSH unavailable")
        return original_read(path, limit)

    monkeypatch.setattr(transport, "read", read)
    with pytest.raises(PublishError, match="activation outcome is unknown"):
        _publish(_release(tmp_path), transport)
    assert json.loads(transport.files["/catalog/current-release.json"])["release_sequence"] == 2


@pytest.mark.skipif(not shutil.which("flock") or not shutil.which("sh"), reason="POSIX flock/sh activation integration")
@pytest.mark.parametrize("original", [None, b'{"schema_version":1,"release_sequence":1}\n'])
def test_ssh_activation_command_compares_pointer_under_real_lock(tmp_path, monkeypatch, original):
    import fcntl

    transport = SshTransport("operator@unused.invalid")
    pointer = tmp_path / "current-release.json"
    partial = tmp_path / "next.json"
    if original is not None:
        pointer.write_bytes(original)
    partial.write_bytes(b"new pointer")

    def local_ssh(command):
        result = subprocess.run(["sh", "-c", command], capture_output=True, check=False)
        if result.returncode:
            raise PublishError("activation failed")
        return result.stdout

    monkeypatch.setattr(transport, "_ssh", local_ssh)
    transport.activate(str(partial), str(pointer), original)
    assert pointer.read_bytes() == b"new pointer"
    partial.write_bytes(b"stale writer")
    with pytest.raises(PublishError, match="activation failed"):
        transport.activate(str(partial), str(pointer), original)
    assert pointer.read_bytes() == b"new pointer"
    assert partial.read_bytes() == b"stale writer"
    with (tmp_path / ".publish.lock").open("wb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(PublishError, match="activation failed"):
            transport.activate(str(partial), str(pointer), b"new pointer")
    assert pointer.read_bytes() == b"new pointer"


def test_activation_shell_condition_handles_missing_matching_and_changed_pointer(tmp_path, monkeypatch):
    bash = shutil.which("bash")
    windows_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if windows_bash.is_file():
        bash = str(windows_bash)
    if bash is None:
        pytest.skip("Bash is needed to execute the activation shell condition")
    transport = SshTransport("operator@unused.invalid")
    pointer = tmp_path / "pointer with spaces.json"
    partial = tmp_path / "candidate.json"

    def local_shell(command):
        parts = shlex.split(command)
        assert parts[:2] == ["flock", "-n"]
        assert parts[3:5] == ["sh", "-c"]
        # Exercise the actual compare/move shell code on both native builders;
        # lock contention itself is covered by the POSIX integration above.
        result = subprocess.run([bash, "-c", parts[5]], capture_output=True, check=False)
        if result.returncode:
            raise PublishError("activation failed")
        return result.stdout

    monkeypatch.setattr(transport, "_ssh", local_shell)
    partial.write_bytes(b"first")
    transport.activate(partial.as_posix(), pointer.as_posix(), None)
    assert pointer.read_bytes() == b"first"
    partial.write_bytes(b"second")
    transport.activate(partial.as_posix(), pointer.as_posix(), b"first")
    assert pointer.read_bytes() == b"second"
    partial.write_bytes(b"stale")
    for expected in (None, b"first"):
        with pytest.raises(PublishError, match="activation failed"):
            transport.activate(partial.as_posix(), pointer.as_posix(), expected)
        assert pointer.read_bytes() == b"second"

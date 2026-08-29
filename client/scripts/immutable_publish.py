#!/usr/bin/env python3
"""Publish a signed artifact release without exposing partial remote content."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

MAX_POINTER_BYTES = 1024
REMOTE_SPEC_PATTERN = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._:-]+$")
REMOTE_ROOT_PATTERN = re.compile(r"^/[A-Za-z0-9._/-]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PublishError(RuntimeError):
    """The release could not be safely published or reconciled."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_filename(value: object) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise PublishError("Manifest artifact names must be plain filenames")
    if Path(value).name != value or value in {".", ".."}:
        raise PublishError("Manifest artifact names must be plain filenames")
    return value


def _remote_join(root: str, *parts: str) -> str:
    return str(PurePosixPath(root, *parts))


@dataclass(frozen=True)
class LocalArtifact:
    path: Path
    filename: str
    size: int
    sha256: str


class RemoteTransport(Protocol):
    def exists(self, remote_path: str) -> bool: ...

    def create_release(self, releases_root: str, release_dir: str) -> None: ...

    def upload(self, local_path: Path, remote_path: str) -> None: ...

    def size(self, remote_path: str) -> int: ...

    def sha256(self, remote_path: str) -> str: ...

    def replace(self, source_path: str, destination_path: str) -> None: ...

    def read(self, remote_path: str, maximum_bytes: int) -> bytes | None: ...


class SshTransport:
    def __init__(self, remote_spec: str) -> None:
        if not REMOTE_SPEC_PATTERN.fullmatch(remote_spec):
            raise PublishError("Remote must use the safe user@host form")
        self.remote_spec = remote_spec

    def _ssh(self, command: str, *, allowed_codes: set[int] = frozenset({0})) -> bytes:
        completed = subprocess.run(
            ["ssh", self.remote_spec, command],
            check=False,
            capture_output=True,
        )
        if completed.returncode not in allowed_codes:
            raise PublishError(f"Remote command failed with exit code {completed.returncode}")
        return completed.stdout

    def exists(self, remote_path: str) -> bool:
        command = f"test -e {shlex.quote(remote_path)}"
        completed = subprocess.run(
            ["ssh", self.remote_spec, command],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if completed.returncode not in {0, 1}:
            raise PublishError(f"Remote existence check failed with exit code {completed.returncode}")
        return completed.returncode == 0

    def create_release(self, releases_root: str, release_dir: str) -> None:
        self._ssh(f"mkdir -p {shlex.quote(releases_root)} && mkdir {shlex.quote(release_dir)}")

    def upload(self, local_path: Path, remote_path: str) -> None:
        completed = subprocess.run(
            ["scp", str(local_path), f"{self.remote_spec}:{remote_path}"],
            check=False,
            capture_output=True,
        )
        if completed.returncode:
            raise PublishError(f"Upload failed for {local_path.name}")

    def size(self, remote_path: str) -> int:
        output = self._ssh(f"stat -c %s -- {shlex.quote(remote_path)}")
        try:
            return int(output.strip())
        except ValueError as exc:
            raise PublishError("Remote size response was invalid") from exc

    def sha256(self, remote_path: str) -> str:
        output = self._ssh(f"sha256sum -- {shlex.quote(remote_path)}")
        digest = output.decode("ascii", errors="strict").split(maxsplit=1)[0].lower()
        if not SHA256_PATTERN.fullmatch(digest):
            raise PublishError("Remote hash response was invalid")
        return digest

    def replace(self, source_path: str, destination_path: str) -> None:
        self._ssh(f"mv -- {shlex.quote(source_path)} {shlex.quote(destination_path)}")

    def read(self, remote_path: str, maximum_bytes: int) -> bytes | None:
        if not self.exists(remote_path):
            return None
        output = self._ssh(f"head -c {maximum_bytes + 1} -- {shlex.quote(remote_path)}")
        if len(output) > maximum_bytes:
            raise PublishError("Remote pointer exceeded its read limit")
        return output


def _load_release(
    release_dir: Path,
    manifest_name: str,
    signature_name: str,
) -> tuple[int, tuple[LocalArtifact, ...]]:
    manifest_name = _safe_filename(manifest_name)
    signature_name = _safe_filename(signature_name)
    manifest_path = release_dir / manifest_name
    signature_path = release_dir / signature_name
    try:
        manifest_bytes = manifest_path.read_bytes()
        signature_bytes = signature_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError("Signed release metadata could not be read") from exc
    if len(signature_bytes) != 64:
        raise PublishError("Detached release signature must be exactly 64 bytes")
    sequence = manifest.get("release_sequence")
    artifacts = manifest.get("artifacts")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        raise PublishError("Manifest release sequence must be a positive integer")
    if not isinstance(artifacts, list) or not artifacts:
        raise PublishError("Manifest must contain at least one artifact")

    local_artifacts: list[LocalArtifact] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise PublishError("Manifest artifact must be an object")
        filename = _safe_filename(item.get("filename"))
        expected_size = item.get("size")
        expected_sha = item.get("sha256")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size <= 0:
            raise PublishError(f"Manifest size is invalid for {filename}")
        if not isinstance(expected_sha, str) or not SHA256_PATTERN.fullmatch(expected_sha):
            raise PublishError(f"Manifest digest is invalid for {filename}")
        path = release_dir / filename
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise PublishError(f"Manifest artifact is missing: {filename}") from exc
        if len(data) != expected_size or _sha256(data) != expected_sha:
            raise PublishError(f"Local artifact does not match its signed manifest: {filename}")
        local_artifacts.append(LocalArtifact(path, filename, len(data), expected_sha))

    local_artifacts.extend(
        [
            LocalArtifact(manifest_path, manifest_name, len(manifest_bytes), _sha256(manifest_bytes)),
            LocalArtifact(signature_path, signature_name, len(signature_bytes), _sha256(signature_bytes)),
        ]
    )
    filenames = [artifact.filename for artifact in local_artifacts]
    if len(filenames) != len(set(filenames)):
        raise PublishError("Release filenames must be unique")
    return sequence, tuple(local_artifacts)


def _verify_remote(transport: RemoteTransport, artifact: LocalArtifact, remote_path: str) -> None:
    if transport.size(remote_path) != artifact.size:
        raise PublishError(f"Remote size mismatch for {artifact.filename}")
    if transport.sha256(remote_path) != artifact.sha256:
        raise PublishError(f"Remote hash mismatch for {artifact.filename}")


def publish_release(
    *,
    release_dir: Path,
    manifest_name: str,
    signature_name: str,
    remote_root: str,
    transport: RemoteTransport,
) -> int:
    if not REMOTE_ROOT_PATTERN.fullmatch(remote_root) or ".." in PurePosixPath(remote_root).parts:
        raise PublishError("Remote root must be an absolute safe POSIX path")
    remote_root = remote_root.rstrip("/")
    sequence, artifacts = _load_release(release_dir, manifest_name, signature_name)
    releases_root = _remote_join(remote_root, "releases")
    remote_release = _remote_join(releases_root, str(sequence))
    if transport.exists(remote_release):
        raise PublishError(f"Remote release sequence {sequence} already exists")
    transport.create_release(releases_root, remote_release)

    for artifact in artifacts:
        remote_path = _remote_join(remote_release, artifact.filename)
        transport.upload(artifact.path, remote_path)
        _verify_remote(transport, artifact, remote_path)

    pointer_bytes = (
        json.dumps(
            {"release_sequence": sequence, "schema_version": 1},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    pointer_final = _remote_join(remote_root, "current-release.json")
    pointer_partial = _remote_join(remote_root, f".current-release.{uuid.uuid4().hex}.part")
    with tempfile.NamedTemporaryFile(prefix="parsetrail-release-", suffix=".json", delete=False) as stream:
        stream.write(pointer_bytes)
        pointer_local = Path(stream.name)
    try:
        pointer_artifact = LocalArtifact(
            pointer_local,
            pointer_local.name,
            len(pointer_bytes),
            _sha256(pointer_bytes),
        )
        transport.upload(pointer_local, pointer_partial)
        _verify_remote(transport, pointer_artifact, pointer_partial)
        try:
            transport.replace(pointer_partial, pointer_final)
        except PublishError as exc:
            # The SSH connection can drop after a successful atomic mv. Resolve
            # that uncertain outcome by reading the authoritative pointer.
            if transport.read(pointer_final, MAX_POINTER_BYTES) != pointer_bytes:
                raise PublishError(f"Release {sequence} activation did not complete") from exc
        if transport.read(pointer_final, MAX_POINTER_BYTES) != pointer_bytes:
            raise PublishError(f"Release {sequence} activation could not be verified")
    finally:
        pointer_local.unlink(missing_ok=True)
    return sequence


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--release-dir", type=Path, required=True)
    result.add_argument("--manifest", required=True)
    result.add_argument("--signature", required=True)
    result.add_argument("--remote", required=True)
    result.add_argument("--remote-root", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    sequence = publish_release(
        release_dir=args.release_dir.resolve(),
        manifest_name=args.manifest,
        signature_name=args.signature,
        remote_root=args.remote_root,
        transport=SshTransport(args.remote),
    )
    print(f"Signed immutable release {sequence} uploaded, verified, and activated.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublishError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

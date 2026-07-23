"""Crash-resistant local storage for authenticated plugin releases."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from parsetrail.core.artifacts import resolve_artifact_destination
from parsetrail.core.plugin_manifest import (
    CURRENT_RELEASE_FILENAME,
    MANIFEST_FILENAME,
    RELEASES_DIRECTORY,
    SIGNATURE_FILENAME,
    PluginArtifactError,
    PluginDownloadCancelled,
    PluginManifestError,
    VerifiedPluginRelease,
    require_no_rollback,
    require_runtime_compatibility,
    verify_artifact_file,
    verify_manifest,
)

MAX_POINTER_BYTES = 1024


@dataclass(frozen=True)
class InstalledPluginRelease:
    verified: VerifiedPluginRelease
    release_dir: Path

    @property
    def manifest(self):
        return self.verified.manifest


def _read_limited(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as input_file:
            payload = input_file.read(limit + 1)
    except OSError as exc:
        raise PluginManifestError(f"Could not read {path.name}") from exc
    if len(payload) > limit:
        raise PluginManifestError(f"{path.name} exceeds its size limit")
    return payload


def _release_directory(plugin_root: Path, release_sequence: int) -> Path:
    releases_root = (plugin_root / RELEASES_DIRECTORY).resolve()
    release_dir = (releases_root / str(release_sequence)).resolve()
    try:
        release_dir.relative_to(releases_root)
    except ValueError as exc:
        raise PluginManifestError("Plugin release path escapes its root") from exc
    return release_dir


def read_active_release(
    plugin_root: Path,
    trusted_keys: dict[str, Ed25519PublicKey],
) -> InstalledPluginRelease | None:
    """Load and re-verify the active release and every plugin it contains."""
    pointer_path = plugin_root / CURRENT_RELEASE_FILENAME
    if not pointer_path.exists():
        return None
    try:
        pointer = json.loads(_read_limited(pointer_path, MAX_POINTER_BYTES))
        if set(pointer) != {"schema_version", "release_sequence"}:
            raise ValueError
        if pointer["schema_version"] != 1:
            raise ValueError
        release_sequence = pointer["release_sequence"]
        if not isinstance(release_sequence, int) or release_sequence <= 0:
            raise ValueError
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PluginManifestError("Current plugin release pointer is invalid") from exc

    release_dir = _release_directory(plugin_root, release_sequence)
    manifest_bytes = _read_limited(
        release_dir / MANIFEST_FILENAME,
        1024 * 1024,
    )
    signature = _read_limited(release_dir / SIGNATURE_FILENAME, 64)
    verified = verify_manifest(manifest_bytes, signature, trusted_keys)
    if verified.manifest.release_sequence != release_sequence:
        raise PluginManifestError("Current plugin release pointer does not match its signed manifest")

    for artifact in verified.manifest.artifacts:
        require_runtime_compatibility(artifact)
        plugin_path = resolve_artifact_destination(
            release_dir,
            artifact.filename,
            allowed_suffixes={".pyc"},
        )
        verify_artifact_file(plugin_path, artifact)
    return InstalledPluginRelease(verified=verified, release_dir=release_dir)


def _write_bytes(path: Path, payload: bytes) -> None:
    with path.open("wb") as output_file:
        output_file.write(payload)
        output_file.flush()
        os.fsync(output_file.fileno())


def _activate_pointer(plugin_root: Path, release_sequence: int) -> None:
    pointer_path = plugin_root / CURRENT_RELEASE_FILENAME
    partial_path = pointer_path.with_name(f"{pointer_path.name}.part")
    payload = (
        json.dumps(
            {"schema_version": 1, "release_sequence": release_sequence},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    try:
        _write_bytes(partial_path, payload)
        partial_path.replace(pointer_path)
    finally:
        partial_path.unlink(missing_ok=True)


def install_plugin_release(
    plugin_root: Path,
    release: VerifiedPluginRelease,
    stream_plugin: Callable[[str], Iterable[bytes]],
    *,
    current: InstalledPluginRelease | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> InstalledPluginRelease:
    """Stage every plugin, authenticate it, then atomically activate the catalog."""
    cancellation_requested = cancelled or (lambda: False)
    require_no_rollback(
        release,
        current.verified if current is not None else None,
    )
    for artifact in release.manifest.artifacts:
        require_runtime_compatibility(artifact)

    plugin_root.mkdir(parents=True, exist_ok=True)
    releases_root = plugin_root / RELEASES_DIRECTORY
    releases_root.mkdir(parents=True, exist_ok=True)
    final_dir = _release_directory(
        plugin_root,
        release.manifest.release_sequence,
    )

    if final_dir.exists():
        manifest_bytes = _read_limited(final_dir / MANIFEST_FILENAME, 1024 * 1024)
        signature = _read_limited(final_dir / SIGNATURE_FILENAME, 64)
        if manifest_bytes != release.manifest_bytes or signature != release.signature:
            raise PluginManifestError("A different local release already uses this release sequence")
        for artifact in release.manifest.artifacts:
            verify_artifact_file(final_dir / artifact.filename, artifact)
        _activate_pointer(plugin_root, release.manifest.release_sequence)
        return InstalledPluginRelease(verified=release, release_dir=final_dir)

    staging_dir = releases_root / (f".staging-{release.manifest.release_sequence}-{uuid.uuid4().hex}")
    staging_dir.mkdir()
    activated = False
    try:
        for artifact in release.manifest.artifacts:
            if cancellation_requested():
                raise PluginDownloadCancelled("Plugin update cancelled")
            destination = resolve_artifact_destination(
                staging_dir,
                artifact.filename,
                allowed_suffixes={".pyc"},
            )
            partial_path = destination.with_name(f"{destination.name}.part")
            digest = hashlib.sha256()
            downloaded = 0
            with partial_path.open("wb") as output_file:
                for chunk in stream_plugin(artifact.filename):
                    if cancellation_requested():
                        raise PluginDownloadCancelled("Plugin update cancelled")
                    downloaded += len(chunk)
                    if downloaded > artifact.size:
                        raise PluginArtifactError(f"Plugin download exceeded signed size for {artifact.filename}")
                    digest.update(chunk)
                    output_file.write(chunk)
                output_file.flush()
                os.fsync(output_file.fileno())
            if downloaded != artifact.size:
                raise PluginArtifactError(f"Plugin download was truncated for {artifact.filename}")
            if digest.hexdigest() != artifact.sha256:
                raise PluginArtifactError(f"Plugin digest mismatch for {artifact.filename}")
            partial_path.replace(destination)

        _write_bytes(staging_dir / MANIFEST_FILENAME, release.manifest_bytes)
        _write_bytes(staging_dir / SIGNATURE_FILENAME, release.signature)
        for artifact in release.manifest.artifacts:
            verify_artifact_file(staging_dir / artifact.filename, artifact)

        staging_dir.replace(final_dir)
        activated = True
        _activate_pointer(plugin_root, release.manifest.release_sequence)
        return InstalledPluginRelease(verified=release, release_dir=final_dir)
    finally:
        if not activated and staging_dir.exists():
            shutil.rmtree(staging_dir)

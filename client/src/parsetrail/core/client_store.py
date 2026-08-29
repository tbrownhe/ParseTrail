"""Authenticated, atomic storage for desktop client installers."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from parsetrail.core.artifacts import resolve_artifact_destination
from parsetrail.core.client_manifest import (
    INSTALLER_SUFFIXES,
    ClientArtifactError,
    ClientInstallerArtifact,
    latest_installer,
    verify_client_manifest,
)
from parsetrail.core.plugin_manifest import load_trusted_plugin_keys


class ClientDownloadCancelled(ClientArtifactError):
    """Raised when a user cancels before an installer is authenticated."""


class ClientReleaseSource(Protocol):
    """Network operations required by the trusted update workflow."""

    def fetch_client_release_bytes(self, platform: str) -> tuple[bytes, bytes]: ...

    def stream_installer(self, platform: str, version: str) -> Iterable[tuple[bytes, int, int]]: ...


def fetch_latest_installer(
    source: ClientReleaseSource,
    platform: str,
    trusted_keys: dict[str, Ed25519PublicKey] | None = None,
) -> ClientInstallerArtifact | None:
    """Authenticate the remote catalog before selecting an update."""
    if platform not in INSTALLER_SUFFIXES:
        return None
    manifest_bytes, signature = source.fetch_client_release_bytes(platform)
    release = verify_client_manifest(
        manifest_bytes,
        signature,
        trusted_keys if trusted_keys is not None else load_trusted_plugin_keys(),
    )
    return latest_installer(release, platform)


def download_installer(
    download_root: Path,
    artifact: ClientInstallerArtifact,
    source: ClientReleaseSource,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Stage, authenticate, and atomically publish one installer locally."""
    cancellation_requested = cancelled or (lambda: False)
    report_progress = progress or (lambda _downloaded, _total: None)
    download_root.mkdir(parents=True, exist_ok=True)
    destination = resolve_artifact_destination(
        download_root,
        artifact.filename,
        allowed_suffixes=set(INSTALLER_SUFFIXES.values()),
    )
    partial_path = destination.with_name(f"{destination.name}.part")
    partial_path.unlink(missing_ok=True)
    digest = hashlib.sha256()
    downloaded = 0

    try:
        if cancellation_requested():
            raise ClientDownloadCancelled("Client update cancelled")
        report_progress(0, artifact.size)
        with partial_path.open("wb") as output_file:
            for chunk, _, _ in source.stream_installer(artifact.platform, artifact.version):
                if cancellation_requested():
                    raise ClientDownloadCancelled("Client update cancelled")
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > artifact.size:
                    raise ClientArtifactError(f"Installer download exceeded signed size for {artifact.filename}")
                digest.update(chunk)
                output_file.write(chunk)
                report_progress(downloaded, artifact.size)
            output_file.flush()
            os.fsync(output_file.fileno())

        if cancellation_requested():
            raise ClientDownloadCancelled("Client update cancelled")
        if downloaded != artifact.size:
            raise ClientArtifactError(f"Installer download was truncated for {artifact.filename}")
        if digest.hexdigest() != artifact.sha256:
            raise ClientArtifactError(f"Installer digest mismatch for {artifact.filename}")
        partial_path.replace(destination)
        return destination
    except OSError as exc:
        raise ClientArtifactError(f"Could not store installer {artifact.filename}") from exc
    finally:
        partial_path.unlink(missing_ok=True)

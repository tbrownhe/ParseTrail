import hashlib
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from parsetrail.core.client_manifest import (
    ClientArtifactError,
    ClientInstallerArtifact,
    ClientManifest,
    ClientSignatureError,
    serialize_client_manifest,
)
from parsetrail.core.client_store import (
    ClientDownloadCancelled,
    download_installer,
    fetch_latest_installer,
)
from parsetrail.core.plugin_manifest import key_id_for_public_key


class FakeSource:
    def __init__(self, manifest: bytes, signature: bytes, chunks: list[bytes]) -> None:
        self.manifest = manifest
        self.signature = signature
        self.chunks = chunks
        self.fetch_count = 0
        self.stream_args: tuple[str, str] | None = None

    def fetch_client_release_bytes(self, platform: str) -> tuple[bytes, bytes]:
        self.fetch_count += 1
        return self.manifest, self.signature

    def stream_installer(self, platform: str, version: str) -> Iterable[tuple[bytes, int, int]]:
        self.stream_args = (platform, version)
        downloaded = 0
        total = sum(len(chunk) for chunk in self.chunks)
        for chunk in self.chunks:
            downloaded += len(chunk)
            yield chunk, downloaded, total


def _signed_release(
    payload: bytes,
    *,
    version: str = "1.2.3",
) -> tuple[ClientInstallerArtifact, bytes, bytes, dict[str, Ed25519PublicKey]]:
    signing_key = Ed25519PrivateKey.generate()
    raw_public_key = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = key_id_for_public_key(raw_public_key)
    artifact = ClientInstallerArtifact(
        filename=f"parsetrail_{version}_win64_setup.exe",
        version=version,
        platform="win64",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    manifest = ClientManifest(
        release_sequence=1,
        published_at=datetime.now(timezone.utc),
        key_id=key_id,
        artifacts=(artifact,),
    )
    manifest_bytes = serialize_client_manifest(manifest)
    return artifact, manifest_bytes, signing_key.sign(manifest_bytes), {key_id: signing_key.public_key()}


def test_fetches_and_authenticates_latest_installer() -> None:
    artifact, manifest, signature, trusted_keys = _signed_release(b"installer")
    source = FakeSource(manifest, signature, [])

    latest = fetch_latest_installer(source, "win64", trusted_keys)

    assert latest == artifact
    assert source.fetch_count == 1


def test_rejects_unauthenticated_catalog() -> None:
    _, manifest, _, trusted_keys = _signed_release(b"installer")
    source = FakeSource(manifest, b"x" * 64, [])

    with pytest.raises(ClientSignatureError):
        fetch_latest_installer(source, "win64", trusted_keys)


def test_unsupported_platform_does_not_fetch() -> None:
    _, manifest, signature, trusted_keys = _signed_release(b"installer")
    source = FakeSource(manifest, signature, [])

    assert fetch_latest_installer(source, "linux64", trusted_keys) is None
    assert source.fetch_count == 0


def test_downloads_then_atomically_publishes_authenticated_installer(tmp_path: Path) -> None:
    payload = b"authenticated installer payload"
    artifact, manifest, signature, _ = _signed_release(payload)
    source = FakeSource(manifest, signature, [payload[:8], payload[8:]])
    updates: list[tuple[int, int]] = []

    destination = download_installer(
        tmp_path,
        artifact,
        source,
        progress=lambda downloaded, total: updates.append((downloaded, total)),
    )

    assert destination.read_bytes() == payload
    assert source.stream_args == ("win64", "1.2.3")
    assert updates == [(0, len(payload)), (8, len(payload)), (len(payload), len(payload))]
    assert not destination.with_name(f"{destination.name}.part").exists()


@pytest.mark.parametrize(
    ("chunks", "error"),
    [
        ([b"short"], "truncated"),
        ([b"tampered!"], "digest mismatch"),
        ([b"installer", b"overflow"], "exceeded signed size"),
    ],
)
def test_rejects_bad_download_and_removes_staging(
    tmp_path: Path,
    chunks: list[bytes],
    error: str,
) -> None:
    artifact, manifest, signature, _ = _signed_release(b"installer")
    source = FakeSource(manifest, signature, chunks)
    destination = tmp_path / artifact.filename

    with pytest.raises(ClientArtifactError, match=error):
        download_installer(tmp_path, artifact, source)

    assert not destination.exists()
    assert not destination.with_name(f"{destination.name}.part").exists()


def test_cancellation_preserves_existing_installer_and_removes_staging(tmp_path: Path) -> None:
    payload = b"new installer"
    artifact, manifest, signature, _ = _signed_release(payload)
    source = FakeSource(manifest, signature, [payload[:4], payload[4:]])
    destination = tmp_path / artifact.filename
    destination.write_bytes(b"previous authenticated installer")
    progress_calls = 0

    def cancelled() -> bool:
        return progress_calls >= 2

    def progress(_downloaded: int, _total: int) -> None:
        nonlocal progress_calls
        progress_calls += 1

    with pytest.raises(ClientDownloadCancelled):
        download_installer(
            tmp_path,
            artifact,
            source,
            cancelled=cancelled,
            progress=progress,
        )

    assert destination.read_bytes() == b"previous authenticated installer"
    assert not destination.with_name(f"{destination.name}.part").exists()

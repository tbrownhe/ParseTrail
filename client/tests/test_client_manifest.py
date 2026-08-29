import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.client_manifest import (
    ClientArtifactError,
    ClientInstallerArtifact,
    ClientManifest,
    ClientManifestError,
    ClientSignatureError,
    latest_installer,
    serialize_client_manifest,
    verify_client_manifest,
    verify_installer_file,
)
from parsetrail.core.plugin_manifest import key_id_for_public_key
from pydantic import ValidationError


def _signed_client_release(
    artifacts: tuple[ClientInstallerArtifact, ...],
):
    private_key = Ed25519PrivateKey.generate()
    raw_public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = key_id_for_public_key(raw_public_key)
    manifest = ClientManifest(
        release_sequence=1,
        published_at=datetime.now(timezone.utc),
        key_id=key_id,
        artifacts=artifacts,
    )
    manifest_bytes = serialize_client_manifest(manifest)
    signature = private_key.sign(manifest_bytes)
    return verify_client_manifest(
        manifest_bytes,
        signature,
        {key_id: private_key.public_key()},
    )


def _artifact(
    payload: bytes = b"installer",
    *,
    version: str = "1.2.3",
    platform: str = "win64",
) -> ClientInstallerArtifact:
    suffix = {"macos": ".dmg", "win64": ".exe"}[platform]
    return ClientInstallerArtifact(
        filename=f"parsetrail_{version}_{platform}_setup{suffix}",
        version=version,
        platform=platform,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_verifies_signed_manifest_and_installer(tmp_path: Path) -> None:
    payload = b"authenticated installer bytes"
    release = _signed_client_release((_artifact(payload),))
    artifact = release.manifest.artifacts[0]
    installer_path = tmp_path / artifact.filename
    installer_path.write_bytes(payload)

    verify_installer_file(installer_path, artifact)

    assert latest_installer(release, "win64") == artifact
    assert latest_installer(release, "macos") is None


def test_selects_latest_version_semantically() -> None:
    release = _signed_client_release(
        (
            _artifact(version="1.10.0"),
            _artifact(version="1.9.0"),
        )
    )

    assert latest_installer(release, "win64").version == "1.10.0"


@pytest.mark.parametrize("version", ["1.2", "01.2.3", "v1.2.3"])
def test_rejects_non_semantic_installer_versions(version: str) -> None:
    with pytest.raises(ValidationError, match="semantic version"):
        _artifact(version=version)


def test_rejects_altered_or_unknown_signature() -> None:
    release = _signed_client_release((_artifact(),))
    altered = release.manifest_bytes.replace(b'"version":"1.2.3"', b'"version":"9.0.0"')

    with pytest.raises(ClientSignatureError, match="signature is invalid"):
        verify_client_manifest(
            altered,
            release.signature,
            {release.manifest.key_id: Ed25519PrivateKey.generate().public_key()},
        )

    with pytest.raises(ClientSignatureError, match="unknown signing key"):
        verify_client_manifest(release.manifest_bytes, release.signature, {})


def test_rejects_malformed_and_oversized_manifest() -> None:
    with pytest.raises(ClientManifestError):
        verify_client_manifest(b"{", b"x" * 64, {})

    oversized = b"{}" + b" " * (1024 * 1024)
    with pytest.raises(ClientManifestError, match="size limit"):
        verify_client_manifest(oversized, b"x" * 64, {})


@pytest.mark.parametrize(
    ("filename", "platform", "version"),
    [
        ("../parsetrail_1.2.3_win64_setup.exe", "win64", "1.2.3"),
        ("parsetrail_1.2.3_win64_setup.exe", "macos", "1.2.3"),
        ("parsetrail_1.2.3_win64_setup.exe", "win64", "1.2.4"),
    ],
)
def test_rejects_filename_metadata_mismatch(
    filename: str,
    platform: str,
    version: str,
) -> None:
    with pytest.raises(ValidationError):
        ClientInstallerArtifact(
            filename=filename,
            version=version,
            platform=platform,
            size=1,
            sha256="0" * 64,
        )


def test_rejects_altered_installer(tmp_path: Path) -> None:
    artifact = _artifact(b"expected")
    installer_path = tmp_path / artifact.filename
    installer_path.write_bytes(b"tampered")

    with pytest.raises(ClientArtifactError, match="size mismatch|digest mismatch"):
        verify_installer_file(installer_path, artifact)

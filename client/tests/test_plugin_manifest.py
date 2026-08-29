import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.plugin_manifest import (
    PluginArtifactError,
    PluginManifestError,
    PluginRollbackError,
    PluginSignatureError,
    require_no_rollback,
    verify_artifact_file,
    verify_manifest,
)
from pydantic import ValidationError

from .plugin_release_helpers import signed_release


def test_verifies_signed_manifest_and_artifact(tmp_path: Path) -> None:
    artifact_bytes = b"authenticated plugin bytes"
    release, trusted_keys = signed_release(artifact_bytes)
    artifact_path = tmp_path / release.manifest.artifacts[0].filename
    artifact_path.write_bytes(artifact_bytes)

    verified = verify_manifest(
        release.manifest_bytes,
        release.signature,
        trusted_keys,
    )
    verify_artifact_file(artifact_path, verified.manifest.artifacts[0])

    assert verified.manifest.release_sequence == 1
    assert verified.legacy_metadata()[0]["PLUGIN_NAME"] == "example_plugin"


def test_rejects_altered_manifest_bytes() -> None:
    release, trusted_keys = signed_release(b"plugin")
    altered = release.manifest_bytes.replace(b'"version":"1.0.0"', b'"version":"9.0.0"')

    with pytest.raises(PluginSignatureError, match="signature is invalid"):
        verify_manifest(altered, release.signature, trusted_keys)


def test_rejects_wrong_signing_key() -> None:
    release, trusted_keys = signed_release(b"plugin")
    key_id = release.manifest.key_id
    trusted_keys[key_id] = Ed25519PrivateKey.generate().public_key()

    with pytest.raises(PluginSignatureError, match="signature is invalid"):
        verify_manifest(
            release.manifest_bytes,
            release.signature,
            trusted_keys,
        )


def test_rejects_unknown_signing_key() -> None:
    release, _ = signed_release(b"plugin")

    with pytest.raises(PluginSignatureError, match="unknown signing key"):
        verify_manifest(release.manifest_bytes, release.signature, {})


def test_rejects_malformed_and_oversized_manifest() -> None:
    with pytest.raises(PluginManifestError):
        verify_manifest(b"{", b"x" * 64, {})

    oversized = json.dumps({"key_id": "plugin-ed25519-00000000000000000000000000000000"}).encode()
    oversized += b" " * (1024 * 1024)
    with pytest.raises(PluginManifestError, match="size limit"):
        verify_manifest(oversized, b"x" * 64, {})


def test_rejects_unsafe_artifact_filename() -> None:
    release, _ = signed_release(b"plugin")
    payload = release.manifest.model_dump()
    payload["artifacts"][0]["filename"] = "../plugin.pyc"

    with pytest.raises(ValidationError, match="plain .pyc filename"):
        type(release.manifest).model_validate(payload)


def test_rejects_altered_plugin_bytes(tmp_path: Path) -> None:
    release, _ = signed_release(b"expected")
    artifact = release.manifest.artifacts[0]
    artifact_path = tmp_path / artifact.filename
    artifact_path.write_bytes(b"tampered")

    with pytest.raises(PluginArtifactError, match="size mismatch|digest mismatch"):
        verify_artifact_file(artifact_path, artifact)


def test_rejects_rollback_and_sequence_reuse() -> None:
    current, _ = signed_release(b"current", release_sequence=20)
    older, _ = signed_release(b"older", release_sequence=19)
    reused, _ = signed_release(b"different", release_sequence=20)

    with pytest.raises(PluginRollbackError, match="already installed"):
        require_no_rollback(older, current)
    with pytest.raises(PluginRollbackError, match="reused"):
        require_no_rollback(reused, current)

    require_no_rollback(current, current)

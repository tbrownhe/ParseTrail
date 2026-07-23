import hashlib
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from parsetrail.core.plugin_manifest import (
    PluginArtifact,
    PluginManifest,
    VerifiedPluginRelease,
    current_python_magic,
    current_python_tag,
    key_id_for_public_key,
    serialize_manifest,
    verify_manifest,
)


def signed_release(
    artifact_bytes: bytes,
    *,
    release_sequence: int = 1,
    plugin_name: str = "example_plugin",
    version: str = "1.0.0",
    private_key: Ed25519PrivateKey | None = None,
) -> tuple[VerifiedPluginRelease, dict[str, Ed25519PublicKey]]:
    return signed_catalog(
        {plugin_name: artifact_bytes},
        release_sequence=release_sequence,
        version=version,
        private_key=private_key,
    )


def signed_catalog(
    artifact_payloads: dict[str, bytes],
    *,
    release_sequence: int = 1,
    version: str = "1.0.0",
    private_key: Ed25519PrivateKey | None = None,
) -> tuple[VerifiedPluginRelease, dict[str, Ed25519PublicKey]]:
    signing_key = private_key or Ed25519PrivateKey.generate()
    raw_public_key = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = key_id_for_public_key(raw_public_key)
    artifacts = tuple(
        PluginArtifact(
            filename=f"{plugin_name}.pyc",
            plugin_name=plugin_name,
            version=version,
            minimum_client_version="1.0.0",
            python_tag=current_python_tag(),
            python_magic=current_python_magic(),
            size=len(artifact_bytes),
            sha256=hashlib.sha256(artifact_bytes).hexdigest(),
            company="Example Bank",
            statement_suffix=".pdf",
            statement_type="Example Statement",
        )
        for plugin_name, artifact_bytes in sorted(artifact_payloads.items())
    )
    manifest = PluginManifest(
        release_sequence=release_sequence,
        published_at=datetime.now(timezone.utc),
        key_id=key_id,
        artifacts=artifacts,
    )
    manifest_bytes = serialize_manifest(manifest)
    signature = signing_key.sign(manifest_bytes)
    trusted_keys = {key_id: signing_key.public_key()}
    return (
        verify_manifest(manifest_bytes, signature, trusted_keys),
        trusted_keys,
    )

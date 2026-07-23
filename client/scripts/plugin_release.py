"""Offline key management and signing for ParseTrail plugin releases.

This script is intentionally outside the packaged ``parsetrail`` application.
It never accepts a passphrase through command-line arguments or environment
variables.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from parsetrail.core.plugin_loader import load_plugin
from parsetrail.core.plugin_manifest import (
    MANIFEST_FILENAME,
    SIGNATURE_FILENAME,
    PluginArtifact,
    PluginManifest,
    TrustedPluginKeyStore,
    current_python_magic,
    current_python_tag,
    key_id_for_public_key,
    load_trusted_plugin_keys,
    serialize_manifest,
    verify_artifact_file,
    verify_manifest,
)

CLIENT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = CLIENT_ROOT.parent
DEFAULT_TRUST_STORE = CLIENT_ROOT / "src" / "parsetrail" / "assets" / "plugin-release-keys.json"


def _assert_private_key_outside_repository(private_key_path: Path) -> None:
    resolved_key = private_key_path.expanduser().resolve()
    resolved_repository = REPOSITORY_ROOT.resolve()
    try:
        resolved_key.relative_to(resolved_repository)
    except ValueError:
        return
    raise ValueError("The private signing key must be stored outside the repository")


def _atomic_write(path: Path, payload: bytes, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = path.with_name(f"{path.name}.part")
    try:
        with partial_path.open("xb") as output_file:
            output_file.write(payload)
            output_file.flush()
            os.fsync(output_file.fileno())
        if mode is not None:
            partial_path.chmod(mode)
        partial_path.replace(path)
    finally:
        partial_path.unlink(missing_ok=True)


def _public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def generate_key(
    private_key_path: Path,
    trust_store_path: Path,
    passphrase: bytes,
) -> str:
    """Generate an encrypted offline key and add only its public half to the client."""
    _assert_private_key_outside_repository(private_key_path)
    if private_key_path.exists():
        raise FileExistsError(f"Private key already exists: {private_key_path}")
    if len(passphrase) < 16:
        raise ValueError("The private-key passphrase must be at least 16 characters")

    private_key = Ed25519PrivateKey.generate()
    raw_public_key = _public_key_bytes(private_key)
    key_id = key_id_for_public_key(raw_public_key)
    encrypted_private_key = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase),
    )

    if trust_store_path.exists():
        try:
            trust_store = TrustedPluginKeyStore.model_validate_json(trust_store_path.read_bytes())
        except Exception as exc:
            raise ValueError("Existing plugin trust store is invalid") from exc
        trust_payload = trust_store.model_dump(mode="json")
    else:
        trust_payload = {"schema_version": 1, "keys": []}
    if any(key.get("key_id") == key_id for key in trust_payload["keys"]):
        raise ValueError(f"Public key {key_id} is already trusted")
    trust_payload["keys"].append(
        {
            "key_id": key_id,
            "public_key": base64.b64encode(raw_public_key).decode("ascii"),
        }
    )
    trust_payload["keys"].sort(key=lambda key: key["key_id"])
    encoded_trust_store = json.dumps(trust_payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"

    _atomic_write(private_key_path, encrypted_private_key, mode=0o600)
    try:
        _atomic_write(trust_store_path, encoded_trust_store)
        load_trusted_plugin_keys(trust_store_path)
    except Exception:
        private_key_path.unlink(missing_ok=True)
        raise
    return key_id


def load_private_key(private_key_path: Path, passphrase: bytes) -> Ed25519PrivateKey:
    _assert_private_key_outside_repository(private_key_path)
    payload = private_key_path.read_bytes()
    if b"BEGIN ENCRYPTED PRIVATE KEY" not in payload:
        raise ValueError("Refusing an unencrypted plugin signing key")
    loaded_key = serialization.load_pem_private_key(payload, password=passphrase)
    if not isinstance(loaded_key, Ed25519PrivateKey):
        raise TypeError("Plugin signing key must be Ed25519")
    return loaded_key


def _manifest_artifact(plugin_path: Path) -> PluginArtifact:
    plugin_id, _, metadata = load_plugin(plugin_path)
    if metadata["PLUGIN_NAME"] != plugin_id:
        raise ValueError(f"{plugin_path.name} declares PLUGIN_NAME {metadata['PLUGIN_NAME']!r}, expected {plugin_id!r}")
    digest = hashlib.sha256(plugin_path.read_bytes()).hexdigest()
    return PluginArtifact(
        filename=plugin_path.name,
        plugin_name=plugin_id,
        version=metadata["VERSION"],
        minimum_client_version=metadata["MIN_CLIENT_VERSION"],
        python_tag=current_python_tag(),
        python_magic=current_python_magic(),
        size=plugin_path.stat().st_size,
        sha256=digest,
        company=metadata["COMPANY"],
        statement_suffix=metadata["SUFFIX"],
        statement_type=metadata["STATEMENT_TYPE"],
    )


def _default_release_sequence() -> int:
    return int(datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))


def sign_release(
    plugin_dir: Path,
    private_key_path: Path,
    trust_store_path: Path,
    passphrase: bytes,
    *,
    release_sequence: int | None = None,
) -> PluginManifest:
    """Create and verify a signed catalog for all compiled plugins."""
    plugin_dir = plugin_dir.expanduser().resolve()
    plugin_paths = sorted(plugin_dir.glob("*.pyc"), key=lambda path: path.name)
    if not plugin_paths:
        raise ValueError(f"No compiled plugins found in {plugin_dir}")

    private_key = load_private_key(private_key_path, passphrase)
    raw_public_key = _public_key_bytes(private_key)
    key_id = key_id_for_public_key(raw_public_key)
    trusted_keys = load_trusted_plugin_keys(trust_store_path)
    trusted_key = trusted_keys.get(key_id)
    if trusted_key is None:
        raise ValueError(f"Signing key {key_id} is not present in the client trust store")
    trusted_raw_key = trusted_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    if trusted_raw_key != raw_public_key:
        raise ValueError("Signing key does not match the trusted public key")

    sequence = release_sequence or _default_release_sequence()
    existing_manifest_path = plugin_dir / MANIFEST_FILENAME
    if existing_manifest_path.exists():
        try:
            existing_sequence = json.loads(existing_manifest_path.read_text(encoding="utf-8"))["release_sequence"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Existing plugin manifest is invalid; move it aside rather than silently resetting the release sequence"
            ) from exc
        if sequence <= existing_sequence:
            raise ValueError(f"Release sequence must exceed existing sequence {existing_sequence}")

    manifest = PluginManifest(
        release_sequence=sequence,
        published_at=datetime.now(timezone.utc),
        key_id=key_id,
        artifacts=tuple(_manifest_artifact(path) for path in plugin_paths),
    )
    manifest_bytes = serialize_manifest(manifest)
    signature = private_key.sign(manifest_bytes)
    verify_manifest(manifest_bytes, signature, trusted_keys)
    for artifact in manifest.artifacts:
        verify_artifact_file(plugin_dir / artifact.filename, artifact)

    _atomic_write(plugin_dir / MANIFEST_FILENAME, manifest_bytes)
    _atomic_write(plugin_dir / SIGNATURE_FILENAME, signature)
    return manifest


def verify_release(plugin_dir: Path, trust_store_path: Path) -> PluginManifest:
    trusted_keys = load_trusted_plugin_keys(trust_store_path)
    manifest_bytes = (plugin_dir / MANIFEST_FILENAME).read_bytes()
    signature = (plugin_dir / SIGNATURE_FILENAME).read_bytes()
    release = verify_manifest(manifest_bytes, signature, trusted_keys)
    for artifact in release.manifest.artifacts:
        verify_artifact_file(plugin_dir / artifact.filename, artifact)
    return release.manifest


def _read_passphrase(*, confirm: bool) -> bytes:
    passphrase = getpass.getpass("Plugin signing-key passphrase: ")
    if confirm:
        confirmation = getpass.getpass("Confirm passphrase: ")
        if passphrase != confirmation:
            raise ValueError("Passphrases do not match")
    return passphrase.encode("utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser(
        "generate-key",
        help="create an encrypted private key and embed its public key",
    )
    generate.add_argument("--private-key", type=Path, required=True)
    generate.add_argument("--trust-store", type=Path, default=DEFAULT_TRUST_STORE)

    sign = subparsers.add_parser(
        "sign",
        help="sign a manifest for every .pyc in a plugin directory",
    )
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--plugin-dir", type=Path, required=True)
    sign.add_argument("--trust-store", type=Path, default=DEFAULT_TRUST_STORE)
    sign.add_argument("--sequence", type=int)

    verify = subparsers.add_parser(
        "verify",
        help="verify a release without access to the private key",
    )
    verify.add_argument("--plugin-dir", type=Path, required=True)
    verify.add_argument("--trust-store", type=Path, default=DEFAULT_TRUST_STORE)

    check = subparsers.add_parser(
        "check-trust-store",
        help="fail if the distributed client has no valid public release key",
    )
    check.add_argument("--trust-store", type=Path, default=DEFAULT_TRUST_STORE)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        if args.command == "generate-key":
            key_id = generate_key(
                args.private_key,
                args.trust_store,
                _read_passphrase(confirm=True),
            )
            print(f"Generated offline signing key {key_id}")
            print(f"Private key: {args.private_key.expanduser().resolve()}")
            print(f"Public trust store: {args.trust_store.resolve()}")
        elif args.command == "sign":
            manifest = sign_release(
                args.plugin_dir,
                args.private_key,
                args.trust_store,
                _read_passphrase(confirm=False),
                release_sequence=args.sequence,
            )
            print(f"Signed plugin release {manifest.release_sequence} with {len(manifest.artifacts)} artifacts")
        elif args.command == "verify":
            manifest = verify_release(args.plugin_dir, args.trust_store)
            print(f"Verified plugin release {manifest.release_sequence} with {len(manifest.artifacts)} artifacts")
        else:
            keys = load_trusted_plugin_keys(args.trust_store)
            print(f"Plugin trust store contains {len(keys)} public key(s)")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

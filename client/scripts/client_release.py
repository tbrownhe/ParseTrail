"""Offline signing and verification for ParseTrail desktop installers."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from parsetrail.core.client_manifest import (
    CLIENT_MANIFEST_FILENAME,
    CLIENT_SIGNATURE_FILENAME,
    INSTALLER_SUFFIXES,
    ClientInstallerArtifact,
    ClientManifest,
    serialize_client_manifest,
    verify_client_manifest,
    verify_installer_file,
)
from parsetrail.core.plugin_manifest import (
    key_id_for_public_key,
    load_trusted_plugin_keys,
)

from scripts.plugin_release import (
    DEFAULT_TRUST_STORE,
    _atomic_write,
    _default_release_sequence,
    _public_key_bytes,
    load_private_key,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_for_installer(
    installer_path: Path,
    *,
    platform: str,
    version: str,
) -> ClientInstallerArtifact:
    return ClientInstallerArtifact(
        filename=installer_path.name,
        version=version,
        platform=platform,
        size=installer_path.stat().st_size,
        sha256=_sha256_file(installer_path),
    )


def sign_release(
    installer_path: Path,
    platform: str,
    version: str,
    private_key_path: Path,
    trust_store_path: Path,
    passphrase: bytes,
    *,
    release_sequence: int | None = None,
) -> ClientManifest:
    """Create and independently verify a signed manifest for one installer."""
    installer_path = installer_path.expanduser().resolve()
    if not installer_path.is_file():
        raise FileNotFoundError(f"Installer not found: {installer_path}")
    if platform not in INSTALLER_SUFFIXES:
        raise ValueError(f"Unsupported client platform: {platform}")

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
    release_dir = installer_path.parent
    existing_manifest_path = release_dir / CLIENT_MANIFEST_FILENAME
    if existing_manifest_path.exists():
        try:
            existing_sequence = json.loads(existing_manifest_path.read_text(encoding="utf-8"))["release_sequence"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Existing client manifest is invalid; move it aside rather than silently resetting the release sequence"
            ) from exc
        if not isinstance(existing_sequence, int) or sequence <= existing_sequence:
            raise ValueError(f"Release sequence must exceed existing sequence {existing_sequence}")

    artifact = _artifact_for_installer(
        installer_path,
        platform=platform,
        version=version,
    )
    manifest = ClientManifest(
        release_sequence=sequence,
        published_at=datetime.now(timezone.utc),
        key_id=key_id,
        artifacts=(artifact,),
    )
    manifest_bytes = serialize_client_manifest(manifest)
    signature = private_key.sign(manifest_bytes)
    verified = verify_client_manifest(manifest_bytes, signature, trusted_keys)
    verify_installer_file(installer_path, verified.manifest.artifacts[0])

    _atomic_write(release_dir / CLIENT_MANIFEST_FILENAME, manifest_bytes)
    _atomic_write(release_dir / CLIENT_SIGNATURE_FILENAME, signature)
    return manifest


def verify_release(release_dir: Path, trust_store_path: Path) -> ClientManifest:
    """Verify a local client release without access to the private key."""
    release_dir = release_dir.expanduser().resolve()
    trusted_keys = load_trusted_plugin_keys(trust_store_path)
    manifest_bytes = (release_dir / CLIENT_MANIFEST_FILENAME).read_bytes()
    signature = (release_dir / CLIENT_SIGNATURE_FILENAME).read_bytes()
    release = verify_client_manifest(manifest_bytes, signature, trusted_keys)
    for artifact in release.manifest.artifacts:
        verify_installer_file(release_dir / artifact.filename, artifact)
    return release.manifest


def _read_passphrase() -> bytes:
    return getpass.getpass("Release signing-key passphrase: ").encode("utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sign = subparsers.add_parser("sign", help="sign one platform installer")
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--installer", type=Path, required=True)
    sign.add_argument("--platform", choices=sorted(INSTALLER_SUFFIXES), required=True)
    sign.add_argument("--version", required=True)
    sign.add_argument("--trust-store", type=Path, default=DEFAULT_TRUST_STORE)
    sign.add_argument("--sequence", type=int)

    verify = subparsers.add_parser("verify", help="verify one local client release")
    verify.add_argument("--release-dir", type=Path, required=True)
    verify.add_argument("--trust-store", type=Path, default=DEFAULT_TRUST_STORE)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        if args.command == "sign":
            manifest = sign_release(
                args.installer,
                args.platform,
                args.version,
                args.private_key,
                args.trust_store,
                _read_passphrase(),
                release_sequence=args.sequence,
            )
            print(
                f"Signed client release {manifest.release_sequence} "
                f"for {manifest.artifacts[0].platform} {manifest.artifacts[0].version}"
            )
        else:
            manifest = verify_release(args.release_dir, args.trust_store)
            print(f"Verified client release {manifest.release_sequence} with {len(manifest.artifacts)} artifact(s)")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

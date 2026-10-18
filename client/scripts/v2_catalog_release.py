"""Build an offline signed 2.0 definition catalog without publishing it."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import re
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import (
    MAX_CATALOG_BYTES,
    MAX_DEFINITION_BYTES,
    MAX_DEFINITIONS,
    VerifiedCatalog,
    key_id_for_public_key,
    load_trusted_catalog_keys,
    verify_catalog,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def load_offline_key(path: Path, passphrase: bytes) -> Ed25519PrivateKey:
    """Read only an encrypted Ed25519 key kept outside the repository."""
    path = path.expanduser().resolve()
    if path.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("signing_key_inside_repository")
    with path.open("rb") as stream:
        payload = stream.read(16 * 1024 + 1)
    if not 0 < len(payload) <= 16 * 1024:
        raise ValueError("signing_key_size")
    if b"BEGIN ENCRYPTED PRIVATE KEY" not in payload:
        raise ValueError("unencrypted_signing_key")
    loaded = serialization.load_pem_private_key(payload, password=passphrase)
    if not isinstance(loaded, Ed25519PrivateKey):
        raise ValueError("signing_key_not_ed25519")
    return loaded


def require_shipped_plugin_key(private_key: Ed25519PrivateKey, trust_store_path: Path | None = None) -> None:
    """Refuse a catalog release signed by a key absent from the installed client."""
    public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if load_trusted_catalog_keys(trust_store_path).get(key_id_for_public_key(public)) != public:
        raise ValueError("signing_key_not_shipped_plugin_key")


def signed_catalog_bytes(
    definitions_dir: Path,
    private_key: Ed25519PrivateKey,
    *,
    release_sequence: int,
    source_revision: str,
) -> tuple[bytes, bytes, VerifiedCatalog]:
    """Validate each definition and the signed envelope before returning bytes."""
    if type(release_sequence) is not int or release_sequence <= 0:
        raise ValueError("invalid_release_sequence")
    if type(source_revision) is not str or re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("invalid_source_revision")
    if definitions_dir.is_symlink() or not definitions_dir.is_dir():
        raise ValueError("definitions_directory_unavailable")
    paths = sorted(definitions_dir.glob("*definition.json"))
    if not 1 <= len(paths) <= MAX_DEFINITIONS:
        raise ValueError("definition_count")
    entries = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("definition_file_shape")
        with path.open("rb") as stream:
            content = stream.read(MAX_DEFINITION_BYTES + 1)
        if not 0 < len(content) <= MAX_DEFINITION_BYTES:
            raise ValueError("definition_file_shape")
        identity = admit_pilot_definition(content)
        entries.append(
            {
                "parser_id": identity.parser_id,
                "revision": identity.revision,
                "suffix": identity.suffix,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    entries.sort(key=lambda item: item["parser_id"])
    if len({item["parser_id"] for item in entries}) != len(entries):
        raise ValueError("duplicate_parser_id")
    public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public)
    snapshot = json.dumps(
        {
            "schema_version": 1,
            "engine_contract": 1,
            "release_sequence": release_sequence,
            "source_revision": source_revision,
            "key_id": key_id,
            "definitions": entries,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(snapshot) > MAX_CATALOG_BYTES:
        raise ValueError("catalog_size")
    signature = private_key.sign(snapshot)
    verified = verify_catalog(snapshot, signature, {key_id: public}, admit_pilot_definition)
    return snapshot, signature, verified


def write_release(
    definitions_dir: Path,
    private_key: Ed25519PrivateKey,
    output_dir: Path,
    *,
    release_sequence: int,
    source_revision: str,
) -> VerifiedCatalog:
    """Place the verified pair into a new local directory atomically."""
    snapshot, signature, verified = signed_catalog_bytes(
        definitions_dir,
        private_key,
        release_sequence=release_sequence,
        source_revision=source_revision,
    )
    output_dir = output_dir.expanduser()
    if output_dir.is_symlink():
        raise ValueError("catalog_output_symlink")
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError("catalog_output_exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v2-catalog-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        (staging / "catalog.json").write_bytes(snapshot)
        (staging / "catalog.sig").write_bytes(signature)
        staging.rename(output_dir)
    return verified


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definitions-dir", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-sequence", type=int, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args(argv)
    private_key = load_offline_key(args.private_key, getpass.getpass("Catalog key passphrase: ").encode())
    require_shipped_plugin_key(private_key)
    verified = write_release(
        args.definitions_dir,
        private_key,
        args.output_dir,
        release_sequence=args.release_sequence,
        source_revision=args.source_revision,
    )
    print(
        f"Built local catalog {verified.release_sequence} with {len(verified.definitions)} definitions ({verified.key_id})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

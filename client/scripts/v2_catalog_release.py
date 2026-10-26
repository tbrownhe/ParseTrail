"""Build an offline signed 2.0 definition catalog without publishing it."""

from __future__ import annotations

import argparse
import base64
import binascii
import ctypes
import errno
import getpass
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import (
    MAX_CATALOG_BYTES,
    MAX_DEFINITION_BYTES,
    MAX_DEFINITIONS,
    CatalogAccountContext,
    CatalogEnvelope,
    DefinitionIdentity,
    VerifiedCatalog,
    key_id_for_public_key,
    load_trusted_catalog_keys,
    verify_catalog,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_account_context_key")
        result[key] = value
    return result


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


@dataclass(frozen=True)
class UnsignedCatalog:
    """Offline review input; this type never establishes release authentication."""

    snapshot: bytes
    envelope: CatalogEnvelope

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.snapshot).hexdigest()


def _catalog_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_catalog_key")
        result[key] = value
    return result


def validate_prepared_catalog(snapshot: bytes) -> UnsignedCatalog:
    """Validate unsigned review data without creating a runtime trust route."""
    if type(snapshot) is not bytes or not 0 < len(snapshot) <= MAX_CATALOG_BYTES:
        raise ValueError("catalog_size")
    # The envelope contains base64 declarations, so its JSON nesting is shallow.
    depth, quoted, escaped = 0, False, False
    for value in snapshot:
        if quoted:
            if escaped:
                escaped = False
            elif value == 92:
                escaped = True
            elif value == 34:
                quoted = False
        elif value == 34:
            quoted = True
        elif value in (91, 123):
            depth += 1
            if depth > 16:
                raise ValueError("prepared_catalog_depth")
        elif value in (93, 125):
            depth -= 1
    try:
        data = json.loads(snapshot, object_pairs_hook=_catalog_pairs)
        if type(data) is not dict or any(
            type(data.get(field)) is not int for field in ("schema_version", "engine_contract", "release_sequence")
        ):
            raise ValueError("prepared_catalog_metadata")
        envelope = CatalogEnvelope.model_validate_json(snapshot)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("prepared_catalog_shape") from None
    for entry in envelope.definitions:
        try:
            content = base64.b64decode(entry.content_base64, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("prepared_definition_encoding") from None
        if len(content) != entry.size or hashlib.sha256(content).hexdigest() != entry.sha256:
            raise ValueError("prepared_definition_hash")
        try:
            identity = admit_pilot_definition(content)
        except (ValueError, TypeError, RecursionError):
            raise ValueError("prepared_definition_rejected") from None
        if identity != DefinitionIdentity(entry.parser_id, entry.revision, entry.suffix):
            raise ValueError("prepared_definition_identity")
    return UnsignedCatalog(snapshot, envelope)


def read_prepared_catalog(path: Path) -> UnsignedCatalog:
    """Read one finite regular file; never follow a selected symlink."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("prepared_catalog_file")
    with path.open("rb") as stream:
        snapshot = stream.read(MAX_CATALOG_BYTES + 1)
    return validate_prepared_catalog(snapshot)


def unsigned_catalog_bytes(
    definitions_dir: Path,
    public_key: bytes,
    *,
    release_sequence: int,
    source_revision: str,
) -> bytes:
    """Assemble deterministic, strictly admitted bytes using a public key only."""
    key_id = key_id_for_public_key(public_key)
    if type(release_sequence) is not int or release_sequence <= 0:
        raise ValueError("invalid_release_sequence")
    if type(source_revision) is not str or re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("invalid_source_revision")
    if definitions_dir.is_symlink() or not definitions_dir.is_dir():
        raise ValueError("definitions_directory_unavailable")
    paths = sorted(definitions_dir.glob("*definition.json"))
    if not 1 <= len(paths) <= MAX_DEFINITIONS:
        raise ValueError("definition_count")
    context_path = definitions_dir / "account-contexts.json"
    contexts = {}
    if context_path.exists() or context_path.is_symlink():
        if context_path.is_symlink() or not context_path.is_file() or not 0 < context_path.stat().st_size <= 16 * 1024:
            raise ValueError("account_context_manifest_shape")
        try:
            with context_path.open("rb") as stream:
                context_bytes = stream.read(16 * 1024 + 1)
            if not 0 < len(context_bytes) <= 16 * 1024:
                raise ValueError("account_context_manifest_shape")
            contexts = json.loads(context_bytes, object_pairs_hook=_unique_pairs)
        except (UnicodeError, ValueError, RecursionError):
            raise ValueError("account_context_manifest_shape") from None
        if type(contexts) is not dict:
            raise ValueError("account_context_manifest_shape")
    entries = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("definition_file_shape")
        with path.open("rb") as stream:
            content = stream.read(MAX_DEFINITION_BYTES + 1)
        if not 0 < len(content) <= MAX_DEFINITION_BYTES:
            raise ValueError("definition_file_shape")
        try:
            identity = admit_pilot_definition(content)
        except (RecursionError, TypeError):
            raise ValueError("definition_file_shape") from None
        context = (
            CatalogAccountContext.model_validate(contexts[identity.parser_id]).model_dump()
            if identity.parser_id in contexts
            else None
        )
        entries.append(
            {
                "parser_id": identity.parser_id,
                "revision": identity.revision,
                "suffix": identity.suffix,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_base64": base64.b64encode(content).decode("ascii"),
                "account_context": context,
            }
        )
    entries.sort(key=lambda item: item["parser_id"])
    if len({item["parser_id"] for item in entries}) != len(entries):
        raise ValueError("duplicate_parser_id")
    if set(contexts) - {item["parser_id"] for item in entries}:
        raise ValueError("unknown_account_context_parser")
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
    validate_prepared_catalog(snapshot)
    return snapshot


def signed_catalog_bytes(
    definitions_dir: Path,
    private_key: Ed25519PrivateKey,
    *,
    release_sequence: int,
    source_revision: str,
) -> tuple[bytes, bytes, VerifiedCatalog]:
    """Validate each definition and the signed envelope before returning bytes."""
    public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot = unsigned_catalog_bytes(
        definitions_dir, public, release_sequence=release_sequence, source_revision=source_revision
    )
    signature = private_key.sign(snapshot)
    verified = verify_catalog(snapshot, signature, {key_id_for_public_key(public): public}, admit_pilot_definition)
    return snapshot, signature, verified


def sign_prepared_catalog(
    snapshot: bytes, private_key: Ed25519PrivateKey, *, expected_sha256: str
) -> tuple[bytes, bytes, VerifiedCatalog]:
    """Sign the exact reviewed bytes, never rebuild their declarations."""
    prepared = validate_prepared_catalog(snapshot)
    if type(expected_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("prepared_catalog_digest_required")
    if prepared.sha256 != expected_sha256:
        raise ValueError("prepared_catalog_digest_mismatch")
    public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public)
    if key_id != prepared.envelope.key_id:
        raise ValueError("prepared_catalog_key_mismatch")
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
    _publish_files(output_dir, {"catalog.json": snapshot, "catalog.sig": signature})
    return verified


def _new_output_path(output_dir: Path) -> Path:
    output_dir = output_dir.expanduser()
    if output_dir.is_symlink():
        raise ValueError("catalog_output_symlink")
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError("catalog_output_exists")
    return output_dir


def _publish_files(output_dir: Path, files: dict[str, bytes]) -> None:
    """Publish a complete artifact directory after validation, without overwrites."""
    output_dir = _new_output_path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v2-catalog-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        for name, content in files.items():
            (staging / name).write_bytes(content)
        _rename_directory_no_replace(staging, output_dir)


def _rename_directory_no_replace(source: Path, destination: Path) -> None:
    """Publish once, including against an empty-directory creation race."""
    if sys.platform == "win32":
        # Windows rename does not replace an existing destination.
        os.rename(source, destination)
        return
    if sys.platform not in {"darwin", "linux"}:
        raise OSError(errno.ENOTSUP, "exclusive_directory_publication_unavailable")
    try:
        library = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            # Apple xnu/bsd/sys/stdio.h: renamex_np(..., RENAME_EXCL=0x4).
            rename = library.renamex_np
            rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            arguments = (os.fsencode(source), os.fsencode(destination), 0x4)
        else:
            # Linux renameat2(..., RENAME_NOREPLACE=1); AT_FDCWD is -100.
            rename = library.renameat2
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            arguments = (-100, os.fsencode(source), -100, os.fsencode(destination), 1)
        rename.restype = ctypes.c_int
    except (AttributeError, OSError):
        raise OSError(errno.ENOTSUP, "exclusive_directory_publication_unavailable") from None
    if rename(*arguments) != 0:
        code = ctypes.get_errno() or errno.EIO
        raise OSError(code, os.strerror(code), str(destination))


def write_prepared_release(
    snapshot: bytes, private_key: Ed25519PrivateKey, output_dir: Path, *, expected_sha256: str
) -> VerifiedCatalog:
    snapshot, signature, verified = sign_prepared_catalog(snapshot, private_key, expected_sha256=expected_sha256)
    _publish_files(output_dir, {"catalog.json": snapshot, "catalog.sig": signature})
    return verified


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--definitions-dir", type=Path)
    inputs.add_argument("--prepared-catalog", type=Path)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-sequence", type=int)
    parser.add_argument("--source-revision")
    parser.add_argument("--expected-sha256")
    args = parser.parse_args(argv)
    prepared = None
    if args.prepared_catalog is not None:
        if args.release_sequence is not None or args.source_revision is not None:
            parser.error("prepared input already contains release sequence and source revision")
        prepared = read_prepared_catalog(args.prepared_catalog)
        if args.expected_sha256 != prepared.sha256:
            parser.error("--expected-sha256 must match the reviewed prepared catalog")
        if prepared.envelope.key_id not in load_trusted_catalog_keys():
            raise ValueError("prepared_catalog_key_not_shipped")
    elif args.release_sequence is None or args.source_revision is None or args.expected_sha256 is not None:
        parser.error("definition input requires --release-sequence and --source-revision, without --expected-sha256")
    _new_output_path(args.output_dir)
    private_key = load_offline_key(args.private_key, getpass.getpass("Catalog key passphrase: ").encode())
    require_shipped_plugin_key(private_key)
    verified = (
        write_prepared_release(prepared.snapshot, private_key, args.output_dir, expected_sha256=args.expected_sha256)
        if prepared is not None
        else write_release(
            args.definitions_dir,
            private_key,
            args.output_dir,
            release_sequence=args.release_sequence,
            source_revision=args.source_revision,
        )
    )
    print(
        f"Built local catalog {verified.release_sequence} with {len(verified.definitions)} definitions ({verified.key_id})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline verification of one immutable signed 2.0 parser catalog snapshot."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

MAX_CATALOG_BYTES = 1024 * 1024
MAX_DEFINITION_BYTES = 64 * 1024
MAX_DEFINITIONS = 128
SIGNATURE_BYTES = 64
KEY_ID = re.compile(r"^data-ed25519-[0-9a-f]{32}$")
SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-z][a-z0-9_-]{2,79}$"


class CatalogError(ValueError):
    """A catalog cannot be authenticated or admitted for this engine."""


class CatalogRollbackError(CatalogError):
    """Activation would silently replace a newer verified catalog."""


class CatalogCancelled(CatalogError):
    """Activation stopped before changing the current catalog pointer."""


class CatalogAccountContext(BaseModel):
    """Signed institution and ledger class for an unambiguous parser family."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    institution_key: str = Field(pattern=IDENTIFIER)
    kind: Literal["asset", "liability"]


class CatalogDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    parser_id: str = Field(pattern=IDENTIFIER)
    revision: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    suffix: Literal[".csv", ".pdf", ".xlsx"]
    size: int = Field(gt=0, le=MAX_DEFINITION_BYTES)
    sha256: str = Field(pattern=SHA256)
    content_base64: str = Field(min_length=1, max_length=MAX_DEFINITION_BYTES * 2)
    account_context: CatalogAccountContext | None = None


class CatalogEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    engine_contract: Literal[1]
    release_sequence: int = Field(gt=0)
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    key_id: str = Field(pattern=KEY_ID.pattern)
    definitions: tuple[CatalogDefinition, ...] = Field(min_length=1, max_length=MAX_DEFINITIONS)

    @model_validator(mode="after")
    def unique_sorted_entries(self) -> CatalogEnvelope:
        ids = [item.parser_id for item in self.definitions]
        if ids != sorted(set(ids)):
            raise ValueError("definition identifiers must be unique and sorted")
        return self


@dataclass(frozen=True, slots=True)
class DefinitionIdentity:
    parser_id: str
    revision: str
    suffix: Literal[".csv", ".pdf", ".xlsx"]


@dataclass(frozen=True, slots=True)
class VerifiedDefinition:
    identity: DefinitionIdentity
    content: bytes
    sha256: str
    account_context: CatalogAccountContext | None = None


@dataclass(frozen=True, slots=True)
class VerifiedCatalog:
    release_sequence: int
    source_revision: str
    key_id: str
    snapshot: bytes
    signature: bytes
    definitions: tuple[VerifiedDefinition, ...]


DefinitionAdmission = Callable[[bytes], DefinitionIdentity]


def key_id_for_public_key(public_key: bytes) -> str:
    if type(public_key) is not bytes or len(public_key) != 32:
        raise CatalogError("invalid_public_key")
    return "data-ed25519-" + hashlib.sha256(public_key).hexdigest()[:32]


def load_trusted_catalog_keys(trust_store_path: Path | None = None) -> dict[str, bytes]:
    """Use the shipped plugin release public keys for the data signing domain."""
    from parsetrail.core.release_trust import load_release_public_keys

    return {key_id_for_public_key(raw): raw for raw in load_release_public_keys(trust_store_path).values()}


def verify_catalog(
    snapshot: bytes,
    signature: bytes,
    trusted_keys: Mapping[str, bytes],
    admit_definition: DefinitionAdmission,
) -> VerifiedCatalog:
    """Verify exact bytes, then validate every embedded declaration before use."""
    if type(snapshot) is not bytes or not 0 < len(snapshot) <= MAX_CATALOG_BYTES:
        raise CatalogError("catalog_size")
    if type(signature) is not bytes or len(signature) != SIGNATURE_BYTES:
        raise CatalogError("signature_size")
    try:
        envelope = CatalogEnvelope.model_validate_json(snapshot)
    except ValidationError:
        raise CatalogError("invalid_catalog") from None
    public_key = trusted_keys.get(envelope.key_id)
    if type(public_key) is not bytes or len(public_key) != 32 or key_id_for_public_key(public_key) != envelope.key_id:
        raise CatalogError("untrusted_key")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, snapshot)
    except (InvalidSignature, ValueError):
        raise CatalogError("invalid_signature") from None
    verified = []
    for entry in envelope.definitions:
        try:
            content = base64.b64decode(entry.content_base64, validate=True)
        except (ValueError, binascii.Error):
            raise CatalogError("invalid_definition_encoding") from None
        if len(content) != entry.size or hashlib.sha256(content).hexdigest() != entry.sha256:
            raise CatalogError("definition_hash_mismatch")
        try:
            identity = admit_definition(content)
        except Exception:
            raise CatalogError("definition_rejected") from None
        if not isinstance(identity, DefinitionIdentity) or identity != DefinitionIdentity(
            entry.parser_id, entry.revision, entry.suffix
        ):
            raise CatalogError("definition_identity_mismatch")
        verified.append(VerifiedDefinition(identity, content, entry.sha256, entry.account_context))
    return VerifiedCatalog(
        envelope.release_sequence,
        envelope.source_revision,
        envelope.key_id,
        snapshot,
        signature,
        tuple(verified),
    )


def _read_limited(path: Path, limit: int) -> bytes:
    try:
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise CatalogError("catalog_cache_shape")
        content = path.read_bytes()
    except OSError:
        raise CatalogError("catalog_cache_shape") from None
    if not 0 < len(content) <= limit:
        raise CatalogError("catalog_cache_shape")
    return content


class CatalogCache:
    """Keep immutable verified releases and atomically select one for offline use."""

    def __init__(self, root: Path, trusted_keys: Mapping[str, bytes], admit_definition: DefinitionAdmission):
        self.root = root.resolve()
        self.trusted_keys = trusted_keys
        self.admit_definition = admit_definition

    def _release_dir(self, sequence: int, digest: str) -> Path:
        return self.root / "releases" / f"{sequence}-{digest[:16]}"

    def load_current(self) -> VerifiedCatalog | None:
        pointer = self.root / "current.json"
        if not pointer.exists() and not pointer.is_symlink():
            return None
        try:
            raw = json.loads(_read_limited(pointer, 1024))
        except (ValueError, UnicodeError):
            raise CatalogError("catalog_pointer") from None
        if (
            type(raw) is not dict
            or set(raw) != {"release_sequence", "snapshot_sha256"}
            or type(raw["release_sequence"]) is not int
            or raw["release_sequence"] <= 0
            or type(raw["snapshot_sha256"]) is not str
            or re.fullmatch(SHA256, raw["snapshot_sha256"]) is None
        ):
            raise CatalogError("catalog_pointer")
        release_dir = self._release_dir(raw["release_sequence"], raw["snapshot_sha256"])
        if release_dir.is_symlink():
            raise CatalogError("catalog_cache_shape")
        snapshot = _read_limited(release_dir / "catalog.json", MAX_CATALOG_BYTES)
        signature = _read_limited(release_dir / "catalog.sig", SIGNATURE_BYTES)
        if hashlib.sha256(snapshot).hexdigest() != raw["snapshot_sha256"]:
            raise CatalogError("catalog_cache_hash")
        verified = verify_catalog(snapshot, signature, self.trusted_keys, self.admit_definition)
        if verified.release_sequence != raw["release_sequence"]:
            raise CatalogError("catalog_pointer")
        return verified

    def activate_directory(self, release_dir: Path) -> VerifiedCatalog:
        """Activate a local signed release pair through the normal trust boundary."""
        release_dir = release_dir.expanduser()
        if release_dir.is_symlink() or not release_dir.is_dir():
            raise CatalogError("catalog_release_directory")
        snapshot = _read_limited(release_dir / "catalog.json", MAX_CATALOG_BYTES)
        signature = _read_limited(release_dir / "catalog.sig", SIGNATURE_BYTES)
        return self.activate(snapshot, signature)

    def activate(
        self,
        snapshot: bytes,
        signature: bytes,
        *,
        cancelled: Callable[[], bool] | None = None,
        allow_rollback: bool = False,
    ) -> VerifiedCatalog:
        """Verify first; a pointer swap is the only activation write."""
        release = verify_catalog(snapshot, signature, self.trusted_keys, self.admit_definition)
        current = self.load_current()
        if current is not None:
            if release.release_sequence == current.release_sequence:
                if release.snapshot != current.snapshot or release.signature != current.signature:
                    raise CatalogRollbackError("conflicting_catalog_sequence")
                return current
            if release.release_sequence < current.release_sequence and not allow_rollback:
                raise CatalogRollbackError("catalog_rollback")
        if cancelled is not None and cancelled():
            raise CatalogCancelled("cancelled")
        releases_dir = self.root / "releases"
        releases_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(snapshot).hexdigest()
        release_dir = self._release_dir(release.release_sequence, digest)
        if release_dir.exists():
            if (
                release_dir.is_symlink()
                or _read_limited(release_dir / "catalog.json", MAX_CATALOG_BYTES) != snapshot
                or _read_limited(release_dir / "catalog.sig", SIGNATURE_BYTES) != signature
            ):
                raise CatalogError("conflicting_cached_release")
        else:
            with tempfile.TemporaryDirectory(prefix="catalog-stage-", dir=releases_dir) as staging_name:
                staging = Path(staging_name)
                (staging / "catalog.json").write_bytes(snapshot)
                (staging / "catalog.sig").write_bytes(signature)
                staging.rename(release_dir)
        if cancelled is not None and cancelled():
            raise CatalogCancelled("cancelled")
        pointer = json.dumps(
            {"release_sequence": release.release_sequence, "snapshot_sha256": digest},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        descriptor, temporary = tempfile.mkstemp(prefix="current-", suffix=".tmp", dir=self.root)
        os.close(descriptor)
        temporary_path = Path(temporary)
        try:
            temporary_path.write_bytes(pointer)
            os.replace(temporary_path, self.root / "current.json")
        finally:
            temporary_path.unlink(missing_ok=True)
        return release

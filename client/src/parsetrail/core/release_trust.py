"""Read the installed Ed25519 release public keys without a plugin runtime."""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

TRUST_STORE_FILENAME = "plugin-release-keys.json"
MAX_TRUST_STORE_BYTES = 64 * 1024


class ReleaseTrustError(ValueError):
    """The installed public trust store is unavailable or invalid."""


def key_id_for_public_key(raw_public_key: bytes) -> str:
    if type(raw_public_key) is not bytes or len(raw_public_key) != 32:
        raise ReleaseTrustError("invalid_public_key")
    return f"plugin-ed25519-{hashlib.sha256(raw_public_key).hexdigest()[:32]}"


class TrustedReleaseKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key_id: str
    public_key: str

    @model_validator(mode="after")
    def validate_public_key(self) -> TrustedReleaseKey:
        try:
            raw_key = base64.b64decode(self.public_key, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("public_key must be valid base64") from exc
        if len(raw_key) != 32:
            raise ValueError("public_key must encode a 32-byte Ed25519 public key")
        if self.key_id != key_id_for_public_key(raw_key):
            raise ValueError("key_id does not match public_key")
        return self


class TrustedReleaseKeyStore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    keys: tuple[TrustedReleaseKey, ...]

    @model_validator(mode="after")
    def validate_unique_keys(self) -> TrustedReleaseKeyStore:
        key_ids = [key.key_id for key in self.keys]
        if len(key_ids) != len(set(key_ids)):
            raise ValueError("trusted key identifiers must be unique")
        return self


def default_trust_store_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / TRUST_STORE_FILENAME


def load_release_public_keys(path: Path | None = None) -> dict[str, bytes]:
    source = path or default_trust_store_path()
    try:
        payload = source.read_bytes()
    except OSError as exc:
        raise ReleaseTrustError(f"Plugin trust store is unavailable: {source}") from exc
    if len(payload) > MAX_TRUST_STORE_BYTES:
        raise ReleaseTrustError("Plugin trust store exceeds its size limit")
    try:
        store = TrustedReleaseKeyStore.model_validate_json(payload)
    except Exception as exc:
        raise ReleaseTrustError("Plugin trust store is invalid") from exc
    if not store.keys:
        raise ReleaseTrustError("Plugin trust store contains no public keys")
    return {item.key_id: base64.b64decode(item.public_key, validate=True) for item in store.keys}

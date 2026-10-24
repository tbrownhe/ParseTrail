"""Schema and cryptographic verification for signed plugin releases."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from parsetrail.core.release_trust import (
    ReleaseTrustError,
    load_release_public_keys,
)
from parsetrail.core.release_trust import (
    key_id_for_public_key as key_id_for_public_key,
)
from parsetrail.core.versioning import validate_semver

MANIFEST_FILENAME = "plugin-manifest.json"
SIGNATURE_FILENAME = "plugin-manifest.sig"
CURRENT_RELEASE_FILENAME = "current-release.json"
RELEASES_DIRECTORY = "releases"

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PLUGIN_BYTES = 32 * 1024 * 1024
ED25519_SIGNATURE_BYTES = 64
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
KEY_ID_PATTERN = re.compile(r"^plugin-ed25519-[0-9a-f]{32}$")
PYTHON_TAG_PATTERN = re.compile(r"^cp[0-9]{2,3}$")
PYTHON_MAGIC_PATTERN = re.compile(r"^[0-9a-f]{8}$")
SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class PluginTrustError(RuntimeError):
    """Base error for a plugin release that cannot be trusted."""


class PluginManifestError(PluginTrustError):
    """The signed plugin manifest is missing, malformed, or inconsistent."""


class PluginSignatureError(PluginTrustError):
    """The plugin manifest signature cannot be authenticated."""


class PluginArtifactError(PluginTrustError):
    """A plugin does not match its authenticated manifest entry."""


class PluginRollbackError(PluginTrustError):
    """A remote release attempts to replace a newer installed release."""


class PluginDownloadCancelled(PluginTrustError):
    """The user cancelled a plugin release before activation."""


def _validate_version(value: str) -> str:
    return validate_semver(value)


def _validate_plain_plugin_filename(value: str) -> str:
    supplied_path = Path(value)
    if (
        not value
        or "/" in value
        or "\\" in value
        or supplied_path.name != value
        or value in {".", ".."}
        or supplied_path.is_absolute()
        or supplied_path.suffix.lower() != ".pyc"
    ):
        raise ValueError("must be a plain .pyc filename")
    return value


class PluginArtifact(BaseModel):
    """One exact plugin artifact authenticated by a release manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_type: Literal["plugin"] = "plugin"
    filename: str
    plugin_name: str = Field(min_length=1, max_length=255)
    version: str
    minimum_client_version: str
    python_tag: str
    python_magic: str
    size: int = Field(gt=0, le=MAX_PLUGIN_BYTES)
    sha256: str
    company: str = Field(min_length=1, max_length=255)
    statement_suffix: str = Field(min_length=1, max_length=32)
    statement_type: str = Field(min_length=1, max_length=255)

    _filename = field_validator("filename")(_validate_plain_plugin_filename)
    _version = field_validator("version")(_validate_version)
    _minimum_client_version = field_validator("minimum_client_version")(_validate_version)

    @field_validator("plugin_name")
    @classmethod
    def validate_plugin_name(cls, value: str) -> str:
        normalized = value.strip()
        if Path(normalized).name != normalized or normalized in {".", ".."}:
            raise ValueError("must be a plain plugin identifier")
        return normalized

    @field_validator("python_tag")
    @classmethod
    def validate_python_tag(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not PYTHON_TAG_PATTERN.fullmatch(normalized):
            raise ValueError("must be a CPython tag such as cp310")
        return normalized

    @field_validator("python_magic")
    @classmethod
    def validate_python_magic(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not PYTHON_MAGIC_PATTERN.fullmatch(normalized):
            raise ValueError("must be four bytes encoded as lowercase hexadecimal")
        return normalized

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SHA256_PATTERN.fullmatch(normalized):
            raise ValueError("must be a lowercase SHA-256 digest")
        return normalized

    @model_validator(mode="after")
    def filename_matches_plugin(self) -> PluginArtifact:
        if Path(self.filename).stem != self.plugin_name:
            raise ValueError("filename stem must match plugin_name")
        return self

    def as_legacy_metadata(self) -> dict[str, str]:
        """Return the metadata vocabulary used by the existing Qt tables."""
        return {
            "FILENAME": self.filename,
            "PLUGIN_NAME": self.plugin_name,
            "VERSION": self.version,
            "MIN_CLIENT_VERSION": self.minimum_client_version,
            "COMPANY": self.company,
            "SUFFIX": self.statement_suffix,
            "STATEMENT_TYPE": self.statement_type,
        }


class PluginManifest(BaseModel):
    """Versioned catalog whose exact serialized bytes are signed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    release_sequence: int = Field(gt=0)
    published_at: datetime
    key_id: str
    source_commit: str | None = None
    artifacts: tuple[PluginArtifact, ...] = Field(min_length=1)

    @field_validator("key_id")
    @classmethod
    def validate_key_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not KEY_ID_PATTERN.fullmatch(normalized):
            raise ValueError("has an invalid Ed25519 key identifier")
        return normalized

    @field_validator("published_at")
    @classmethod
    def validate_published_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a timezone")
        return value

    @field_validator("source_commit")
    @classmethod
    def validate_source_commit(cls, value: str | None) -> str | None:
        if value is not None and not SOURCE_COMMIT_PATTERN.fullmatch(value):
            raise ValueError("must be a full lowercase Git commit")
        return value

    @model_validator(mode="after")
    def validate_catalog(self) -> PluginManifest:
        filenames = [artifact.filename for artifact in self.artifacts]
        plugin_names = [artifact.plugin_name for artifact in self.artifacts]
        if len(filenames) != len(set(filenames)):
            raise ValueError("artifact filenames must be unique")
        if len(plugin_names) != len(set(plugin_names)):
            raise ValueError("plugin names must be unique")
        if filenames != sorted(filenames):
            raise ValueError("artifacts must be sorted by filename")
        return self


@dataclass(frozen=True)
class VerifiedPluginRelease:
    """Authenticated manifest bytes and their validated representation."""

    manifest: PluginManifest
    manifest_bytes: bytes
    signature: bytes

    def legacy_metadata(self) -> list[dict[str, str]]:
        return [artifact.as_legacy_metadata() for artifact in self.manifest.artifacts]


def current_python_tag() -> str:
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def current_python_magic() -> str:
    return importlib.util.MAGIC_NUMBER.hex()


def serialize_manifest(manifest: PluginManifest) -> bytes:
    """Serialize deterministically; the resulting exact bytes are signed."""
    payload = manifest.model_dump(mode="json", exclude_none=True)
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def load_trusted_plugin_keys(
    trust_store_path: Path | None = None,
) -> dict[str, Ed25519PublicKey]:
    try:
        raw_keys = load_release_public_keys(trust_store_path)
    except ReleaseTrustError as exc:
        raise PluginSignatureError(str(exc)) from exc
    return {key_id: Ed25519PublicKey.from_public_bytes(raw) for key_id, raw in raw_keys.items()}


def verify_manifest(
    manifest_bytes: bytes,
    signature: bytes,
    trusted_keys: dict[str, Ed25519PublicKey],
) -> VerifiedPluginRelease:
    """Authenticate exact manifest bytes before trusting any catalog fields."""
    if not manifest_bytes or len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise PluginManifestError("Plugin manifest is empty or exceeds its size limit")
    if len(signature) != ED25519_SIGNATURE_BYTES:
        raise PluginSignatureError("Plugin manifest signature has an invalid length")

    try:
        untrusted_payload = json.loads(manifest_bytes)
        key_id = untrusted_payload["key_id"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PluginManifestError("Plugin manifest is not valid JSON") from exc
    if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
        raise PluginManifestError("Plugin manifest has an invalid key identifier")

    public_key = trusted_keys.get(key_id)
    if public_key is None:
        raise PluginSignatureError(f"Plugin manifest uses unknown signing key {key_id}")
    try:
        public_key.verify(signature, manifest_bytes)
    except InvalidSignature as exc:
        raise PluginSignatureError("Plugin manifest signature is invalid") from exc

    try:
        manifest = PluginManifest.model_validate_json(manifest_bytes)
    except Exception as exc:
        raise PluginManifestError("Signed plugin manifest does not match its schema") from exc
    return VerifiedPluginRelease(
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        signature=signature,
    )


def verify_artifact_file(path: Path, artifact: PluginArtifact) -> None:
    """Verify one plugin's length and digest without executing it."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PluginArtifactError(f"Plugin is unavailable: {artifact.filename}") from exc
    if size != artifact.size:
        raise PluginArtifactError(
            f"Plugin size mismatch for {artifact.filename}: expected {artifact.size}, found {size}"
        )

    digest = hashlib.sha256()
    try:
        with path.open("rb") as plugin_file:
            for chunk in iter(lambda: plugin_file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PluginArtifactError(f"Could not read plugin {artifact.filename}") from exc
    if digest.hexdigest() != artifact.sha256:
        raise PluginArtifactError(f"Plugin digest mismatch for {artifact.filename}")


def require_runtime_compatibility(artifact: PluginArtifact) -> None:
    if artifact.python_tag != current_python_tag():
        raise PluginArtifactError(
            f"{artifact.filename} requires {artifact.python_tag}; this client uses {current_python_tag()}"
        )
    if artifact.python_magic != current_python_magic():
        raise PluginArtifactError(f"{artifact.filename} uses incompatible Python bytecode")


def require_no_rollback(
    remote: VerifiedPluginRelease,
    current: VerifiedPluginRelease | None,
) -> None:
    if current is None:
        return
    remote_sequence = remote.manifest.release_sequence
    current_sequence = current.manifest.release_sequence
    if remote_sequence < current_sequence:
        raise PluginRollbackError(
            f"Refusing plugin release {remote_sequence}; release {current_sequence} was already installed"
        )
    if remote_sequence == current_sequence and (
        remote.manifest_bytes != current.manifest_bytes or remote.signature != current.signature
    ):
        raise PluginRollbackError(f"Plugin release sequence {remote_sequence} was reused with different contents")

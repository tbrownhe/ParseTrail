"""Schema and cryptographic verification for signed client installers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from parsetrail.core.plugin_manifest import (
    ED25519_SIGNATURE_BYTES,
    KEY_ID_PATTERN,
    SHA256_PATTERN,
)

CLIENT_MANIFEST_FILENAME = "client-manifest.json"
CLIENT_SIGNATURE_FILENAME = "client-manifest.sig"
CLIENT_CURRENT_RELEASE_FILENAME = "current-release.json"
CLIENT_RELEASES_DIRECTORY = "releases"

MAX_CLIENT_MANIFEST_BYTES = 1024 * 1024
MAX_INSTALLER_BYTES = 1024 * 1024 * 1024
INSTALLER_SUFFIXES = {
    "macos": ".dmg",
    "win64": ".exe",
}


class ClientTrustError(RuntimeError):
    """Base error for a client release that cannot be trusted."""


class ClientManifestError(ClientTrustError):
    """The signed client manifest is missing, malformed, or inconsistent."""


class ClientSignatureError(ClientTrustError):
    """The client manifest signature cannot be authenticated."""


class ClientArtifactError(ClientTrustError):
    """An installer does not match its authenticated manifest entry."""


def _validate_version(value: str) -> str:
    normalized = value.strip()
    try:
        Version(normalized)
    except InvalidVersion as exc:
        raise ValueError("must be a valid version") from exc
    return normalized


def _validate_plain_installer_filename(value: str) -> str:
    supplied_path = Path(value)
    if (
        not value
        or "/" in value
        or "\\" in value
        or supplied_path.name != value
        or value in {".", ".."}
        or supplied_path.is_absolute()
    ):
        raise ValueError("must be a plain installer filename")
    return value


class ClientInstallerArtifact(BaseModel):
    """One exact desktop installer authenticated by a release manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_type: Literal["client_installer"] = "client_installer"
    filename: str
    version: str
    platform: Literal["macos", "win64"]
    size: int = Field(gt=0, le=MAX_INSTALLER_BYTES)
    sha256: str

    _filename = field_validator("filename")(_validate_plain_installer_filename)
    _version = field_validator("version")(_validate_version)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SHA256_PATTERN.fullmatch(normalized):
            raise ValueError("must be a lowercase SHA-256 digest")
        return normalized

    @model_validator(mode="after")
    def filename_matches_metadata(self) -> ClientInstallerArtifact:
        suffix = INSTALLER_SUFFIXES[self.platform]
        expected = f"parsetrail_{self.version}_{self.platform}_setup{suffix}"
        if self.filename != expected:
            raise ValueError(f"filename must be {expected}")
        return self


class ClientManifest(BaseModel):
    """Versioned installer catalog whose exact serialized bytes are signed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    release_sequence: int = Field(gt=0)
    published_at: datetime
    key_id: str
    artifacts: tuple[ClientInstallerArtifact, ...] = Field(min_length=1)

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

    @model_validator(mode="after")
    def validate_catalog(self) -> ClientManifest:
        identities = [(artifact.platform, artifact.version) for artifact in self.artifacts]
        filenames = [artifact.filename for artifact in self.artifacts]
        if len(identities) != len(set(identities)):
            raise ValueError("platform/version pairs must be unique")
        if len(filenames) != len(set(filenames)):
            raise ValueError("artifact filenames must be unique")
        if filenames != sorted(filenames):
            raise ValueError("artifacts must be sorted by filename")
        return self


class VerifiedClientRelease(BaseModel):
    """Authenticated installer manifest bytes and validated representation."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    manifest: ClientManifest
    manifest_bytes: bytes
    signature: bytes


def serialize_client_manifest(manifest: ClientManifest) -> bytes:
    """Serialize deterministically; the resulting exact bytes are signed."""
    return (
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def verify_client_manifest(
    manifest_bytes: bytes,
    signature: bytes,
    trusted_keys: dict[str, Ed25519PublicKey],
) -> VerifiedClientRelease:
    """Authenticate exact manifest bytes before trusting any catalog fields."""
    if not manifest_bytes or len(manifest_bytes) > MAX_CLIENT_MANIFEST_BYTES:
        raise ClientManifestError("Client manifest is empty or exceeds its size limit")
    if len(signature) != ED25519_SIGNATURE_BYTES:
        raise ClientSignatureError("Client manifest signature has an invalid length")

    try:
        untrusted_payload = json.loads(manifest_bytes)
        key_id = untrusted_payload["key_id"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ClientManifestError("Client manifest is not valid JSON") from exc
    if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
        raise ClientManifestError("Client manifest has an invalid key identifier")

    public_key = trusted_keys.get(key_id)
    if public_key is None:
        raise ClientSignatureError(f"Client manifest uses unknown signing key {key_id}")
    try:
        public_key.verify(signature, manifest_bytes)
    except InvalidSignature as exc:
        raise ClientSignatureError("Client manifest signature is invalid") from exc

    try:
        manifest = ClientManifest.model_validate_json(manifest_bytes)
    except Exception as exc:
        raise ClientManifestError("Signed client manifest does not match its schema") from exc
    return VerifiedClientRelease(
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        signature=signature,
    )


def verify_installer_file(path: Path, artifact: ClientInstallerArtifact) -> None:
    """Verify one installer's exact length and digest."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ClientArtifactError(f"Installer is unavailable: {artifact.filename}") from exc
    if size != artifact.size:
        raise ClientArtifactError(
            f"Installer size mismatch for {artifact.filename}: expected {artifact.size}, found {size}"
        )

    digest = hashlib.sha256()
    try:
        with path.open("rb") as installer_file:
            for chunk in iter(lambda: installer_file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ClientArtifactError(f"Could not read installer {artifact.filename}") from exc
    if digest.hexdigest() != artifact.sha256:
        raise ClientArtifactError(f"Installer digest mismatch for {artifact.filename}")


def latest_installer(
    release: VerifiedClientRelease,
    platform: str,
) -> ClientInstallerArtifact | None:
    """Return the newest authenticated installer for one supported platform."""
    candidates = [artifact for artifact in release.manifest.artifacts if artifact.platform == platform]
    if not candidates:
        return None
    return max(candidates, key=lambda artifact: Version(artifact.version))

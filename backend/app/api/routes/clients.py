import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import text

from app.api.request_utils import get_client_host, get_user_agent
from app.core.artifacts import InvalidArtifactName, resolve_artifact_path
from app.core.db import engine

router = APIRouter()

CLIENTS_DIR = Path("data/clients")
CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
CLIENT_MANIFEST = "client-manifest.json"
CLIENT_SIGNATURE = "client-manifest.sig"
CURRENT_RELEASE = "current-release.json"
CLIENT_RELEASES_DIR = "releases"
MAX_CLIENT_MANIFEST_BYTES = 1024 * 1024
MAX_RELEASE_POINTER_BYTES = 1024
SUPPORTED_PLATFORMS = {"macos": ".dmg", "win64": ".exe"}
SEMVER_PATTERN = (
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
ClientVersion = Annotated[str, ApiPath(pattern=rf"^(?:latest|{SEMVER_PATTERN})$")]

logging.basicConfig(
    filename="client_downloads.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
)


class ClientInstallerArtifact(BaseModel):
    """Server-side validation for metadata copied from a signed manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_type: Literal["client_installer"]
    filename: str
    version: str = Field(pattern=rf"^{SEMVER_PATTERN}$", max_length=64)
    platform: Literal["macos", "win64"]
    size: int = Field(gt=0, le=1024 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        supplied_path = Path(value)
        if not value or "/" in value or "\\" in value or supplied_path.name != value or supplied_path.is_absolute():
            raise ValueError("must be a plain filename")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if value != value.strip() or "/" in value or "\\" in value:
            raise ValueError("must be a plain version identifier")
        return value

    @model_validator(mode="after")
    def validate_filename_metadata(self) -> "ClientInstallerArtifact":
        expected = f"parsetrail_{self.version}_{self.platform}_setup{SUPPORTED_PLATFORMS[self.platform]}"
        if self.filename != expected:
            raise ValueError(f"filename must be {expected}")
        return self


class ClientManifest(BaseModel):
    """Strict representation used only after selecting an immutable release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    release_sequence: int = Field(gt=0)
    published_at: datetime
    key_id: str = Field(pattern=r"^plugin-ed25519-[0-9a-f]{32}$")
    artifacts: tuple[ClientInstallerArtifact, ...] = Field(min_length=1)

    @field_validator("published_at")
    @classmethod
    def validate_published_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_artifacts(self) -> "ClientManifest":
        filenames = [artifact.filename for artifact in self.artifacts]
        identities = [(artifact.platform, artifact.version) for artifact in self.artifacts]
        if filenames != sorted(filenames):
            raise ValueError("artifacts must be sorted")
        if len(filenames) != len(set(filenames)) or len(identities) != len(set(identities)):
            raise ValueError("artifacts must be unique")
        return self


def _platform_root(platform: str) -> Path:
    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=404, detail="Platform not found")
    return CLIENTS_DIR / platform


def _active_release_dir(platform: str) -> tuple[Path, int]:
    """Resolve the platform release selected by its atomic pointer."""
    platform_root = _platform_root(platform)
    pointer_path = platform_root / CURRENT_RELEASE
    if not pointer_path.is_file():
        raise HTTPException(status_code=404, detail="Client release not found")
    try:
        if pointer_path.stat().st_size > MAX_RELEASE_POINTER_BYTES:
            raise ValueError
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if set(pointer) != {"schema_version", "release_sequence"}:
            raise ValueError
        if pointer["schema_version"] != 1:
            raise ValueError
        release_sequence = pointer["release_sequence"]
        if not isinstance(release_sequence, int) or isinstance(release_sequence, bool) or release_sequence <= 0:
            raise ValueError
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="Client catalog unavailable")

    releases_root = (platform_root / CLIENT_RELEASES_DIR).resolve()
    release_dir = (releases_root / str(release_sequence)).resolve()
    try:
        release_dir.relative_to(releases_root)
    except ValueError:
        raise HTTPException(status_code=503, detail="Client catalog unavailable")
    if not release_dir.is_dir():
        raise HTTPException(status_code=503, detail="Client catalog unavailable")
    return release_dir, release_sequence


def _active_manifest(platform: str) -> tuple[Path, ClientManifest]:
    release_dir, release_sequence = _active_release_dir(platform)
    manifest_path = release_dir / CLIENT_MANIFEST
    try:
        if not manifest_path.is_file() or manifest_path.stat().st_size > MAX_CLIENT_MANIFEST_BYTES:
            raise ValueError
        manifest = ClientManifest.model_validate_json(manifest_path.read_bytes())
        if manifest.release_sequence != release_sequence:
            raise ValueError
        if any(artifact.platform != platform for artifact in manifest.artifacts):
            raise ValueError
    except (OSError, ValueError, ValidationError):
        raise HTTPException(status_code=503, detail="Client catalog unavailable")
    return release_dir, manifest


def _no_cache_response(content: list[dict[str, str | int]]) -> JSONResponse:
    response = JSONResponse(content=content)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.get("/", summary="Get list of available client installers")
async def get_clients() -> JSONResponse:
    """Return compatibility metadata derived from active release manifests."""
    client_metadata: list[dict[str, str | int]] = []
    for platform in sorted(SUPPORTED_PLATFORMS):
        if not (CLIENTS_DIR / platform / CURRENT_RELEASE).exists():
            continue
        _, manifest = _active_manifest(platform)
        client_metadata.extend(
            {
                "file_name": artifact.filename,
                "version": artifact.version,
                "platform": artifact.platform,
                "file_path": artifact.platform,
                "size": artifact.size,
                "sha256": artifact.sha256,
            }
            for artifact in manifest.artifacts
        )
    return _no_cache_response(client_metadata)


@router.get("/{platform}/manifest", summary="Download the exact signed client manifest")
async def download_client_manifest(platform: str) -> FileResponse:
    release_dir, _ = _active_manifest(platform)
    return FileResponse(
        release_dir / CLIENT_MANIFEST,
        media_type="application/json",
        filename=CLIENT_MANIFEST,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get(
    "/{platform}/manifest-signature",
    summary="Download the detached Ed25519 client-manifest signature",
)
async def download_client_manifest_signature(platform: str) -> FileResponse:
    release_dir, _ = _active_manifest(platform)
    signature_path = release_dir / CLIENT_SIGNATURE
    if not signature_path.is_file() or signature_path.stat().st_size != 64:
        raise HTTPException(status_code=404, detail="Client signature not found")
    return FileResponse(
        signature_path,
        media_type="application/octet-stream",
        filename=CLIENT_SIGNATURE,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/{platform}/{version}", summary="Download a client installer")
async def download_client(platform: str, version: ClientVersion, request: Request) -> FileResponse:
    """Serve only an installer named in the platform's active manifest."""
    release_dir, manifest = _active_manifest(platform)
    artifacts = list(manifest.artifacts)
    artifact: ClientInstallerArtifact | None
    if version == "latest":
        if len(artifacts) != 1:
            raise HTTPException(status_code=503, detail="Client catalog has no unambiguous latest release")
        artifact = artifacts[0]
    else:
        artifact = next((candidate for candidate in artifacts if candidate.version == version), None)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Client installer not found")

    try:
        client_path = resolve_artifact_path(
            release_dir,
            artifact.filename,
            allowed_suffixes=set(SUPPORTED_PLATFORMS.values()),
        )
    except InvalidArtifactName:
        raise HTTPException(status_code=503, detail="Client catalog unavailable")
    if not client_path.is_file() or client_path.stat().st_size != artifact.size:
        raise HTTPException(status_code=404, detail="Client installer not found")

    client_ip = get_client_host(request)
    user_agent = get_user_agent(request)
    logging.info(
        "Download: %s (platform: %s) | IP: %s | User-Agent: %s",
        client_path.stem,
        platform,
        client_ip,
        user_agent,
    )

    query = text(
        """
        INSERT INTO client_downloads (platform, version, client_ip, user_agent)
        VALUES (:platform, :version, :client_ip, :user_agent)
        """
    )
    with engine.begin() as conn:
        conn.execute(
            query,
            {
                "platform": platform,
                "version": artifact.version,
                "client_ip": client_ip,
                "user_agent": user_agent,
            },
        )

    return FileResponse(
        client_path,
        media_type="application/octet-stream",
        filename=client_path.name,
    )

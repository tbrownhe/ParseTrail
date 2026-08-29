import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.api.deps import get_current_user
from app.api.request_utils import get_client_host, get_user_agent
from app.core.artifacts import InvalidArtifactName, resolve_artifact_path
from app.core.db import engine
from app.models import User

router = APIRouter()

# Base directory for plugins
PLUGINS_DIR = Path("data/plugins")
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
PLUGIN_MANIFEST = "plugin-manifest.json"
PLUGIN_SIGNATURE = "plugin-manifest.sig"
CURRENT_RELEASE = "current-release.json"
PLUGIN_RELEASES_DIR = "releases"
MAX_PLUGIN_MANIFEST_BYTES = 1024 * 1024
MAX_RELEASE_POINTER_BYTES = 1024

# Configure logging
logging.basicConfig(
    filename="plugin_downloads.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
)


def _active_release_dir() -> Path:
    """Resolve the atomically selected server release directory."""
    pointer_path = PLUGINS_DIR / CURRENT_RELEASE
    if not pointer_path.exists():
        # Transitional support for a signed release deployed in the old flat
        # directory. New deployments always use the release pointer.
        return PLUGINS_DIR
    if pointer_path.stat().st_size > MAX_RELEASE_POINTER_BYTES:
        raise HTTPException(status_code=503, detail="Plugin catalog unavailable")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if set(pointer) != {"schema_version", "release_sequence"}:
            raise ValueError
        if pointer["schema_version"] != 1:
            raise ValueError
        release_sequence = pointer["release_sequence"]
        if not isinstance(release_sequence, int) or release_sequence <= 0:
            raise ValueError
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="Plugin catalog unavailable")

    releases_root = (PLUGINS_DIR / PLUGIN_RELEASES_DIR).resolve()
    release_dir = (releases_root / str(release_sequence)).resolve()
    try:
        release_dir.relative_to(releases_root)
    except ValueError:
        raise HTTPException(status_code=503, detail="Plugin catalog unavailable")
    if not release_dir.is_dir():
        raise HTTPException(status_code=503, detail="Plugin catalog unavailable")
    return release_dir


@router.get("/", summary="Get list of available plugins")
async def get_plugins() -> JSONResponse:
    """
    Return display metadata derived from the signed release manifest.

    This compatibility endpoint is used by the public website. Desktop clients
    fetch and authenticate the exact manifest bytes from ``/manifest`` instead.
    """
    manifest_file = _active_release_dir() / PLUGIN_MANIFEST
    if not manifest_file.is_file():
        raise HTTPException(status_code=503, detail="Plugin catalog unavailable")
    if manifest_file.stat().st_size > MAX_PLUGIN_MANIFEST_BYTES:
        raise HTTPException(status_code=503, detail="Plugin catalog unavailable")
    try:
        with manifest_file.open(encoding="utf-8") as manifest_stream:
            manifest = json.load(manifest_stream)
        plugin_metadata = [
            {
                "FILENAME": artifact["filename"],
                "PLUGIN_NAME": artifact["plugin_name"],
                "VERSION": artifact["version"],
                "MIN_CLIENT_VERSION": artifact["minimum_client_version"],
                "COMPANY": artifact["company"],
                "SUFFIX": artifact["statement_suffix"],
                "STATEMENT_TYPE": artifact["statement_type"],
            }
            for artifact in manifest["artifacts"]
        ]
    except (KeyError, OSError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="Plugin catalog unavailable")

    response = JSONResponse(content=plugin_metadata)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response


@router.get("/manifest", summary="Download the exact signed plugin manifest")
async def download_plugin_manifest() -> FileResponse:
    manifest_path = _active_release_dir() / PLUGIN_MANIFEST
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="Plugin manifest not found")
    if manifest_path.stat().st_size > MAX_PLUGIN_MANIFEST_BYTES:
        raise HTTPException(status_code=503, detail="Plugin manifest is invalid")
    return FileResponse(
        manifest_path,
        media_type="application/json",
        filename=PLUGIN_MANIFEST,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get(
    "/manifest-signature",
    summary="Download the detached Ed25519 plugin-manifest signature",
)
async def download_plugin_manifest_signature() -> FileResponse:
    signature_path = _active_release_dir() / PLUGIN_SIGNATURE
    if not signature_path.is_file() or signature_path.stat().st_size != 64:
        raise HTTPException(status_code=404, detail="Plugin signature not found")
    return FileResponse(
        signature_path,
        media_type="application/octet-stream",
        filename=PLUGIN_SIGNATURE,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/{plugin_file}", summary="Download a specific plugin")
async def download_plugin(
    plugin_file: str, request: Request, current_user: User = Depends(get_current_user)
) -> FileResponse:
    """
    Serves the requested plugin file if the current user is active.
    plugin_file like 'pdf_citicc_201505.pyc'
    """

    try:
        plugin_path = resolve_artifact_path(
            _active_release_dir(),
            plugin_file,
            allowed_suffixes={".pyc"},
        )
    except InvalidArtifactName:
        raise HTTPException(status_code=400, detail="Invalid plugin filename")
    if not plugin_path.is_file():
        raise HTTPException(status_code=404, detail="Plugin not found")

    # Log the download to file
    client_ip = get_client_host(request)
    user_agent = get_user_agent(request)
    logging.info(
        "Download: %s | IP: %s | User-Agent: %s | User: %s (%s)",
        plugin_file,
        client_ip,
        user_agent,
        getattr(current_user, "email", "unknown"),
        getattr(current_user, "id", "unknown"),
    )

    # Log the download to the database
    query = text(
        """
        INSERT INTO plugin_downloads (plugin_file, client_ip, user_agent, downloaded_at, user_id)
        VALUES (:plugin_file, :client_ip, :user_agent, NOW(), :user_id)
        """
    )
    with engine.begin() as conn:
        conn.execute(
            query,
            {
                "plugin_file": plugin_file,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "user_id": str(current_user.id),
            },
        )

    return FileResponse(
        plugin_path,
        media_type="application/octet-stream",
        filename=plugin_file,
    )

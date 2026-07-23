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

# Configure logging
logging.basicConfig(
    filename="plugin_downloads.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
)


@router.get("/", summary="Get list of available plugins")
async def get_plugins() -> JSONResponse:
    """
    Returns a list of available plugins and their metadata, grouped by file type.
    """
    metadata_file = PLUGINS_DIR / "plugin_metadata.json"

    with metadata_file.open() as f:
        plugin_metadata = json.load(f)

    response = JSONResponse(content=plugin_metadata)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response


@router.get("/{plugin_file}", summary="Download a specific plugin")
async def download_plugin(
    plugin_file: str, request: Request, current_user: User = Depends(get_current_user)
) -> FileResponse:
    """
    Serves the requested plugin file if the current user is active.
    plugin_file like 'pdf_citicc_201505.pyc'
    """

    try:
        plugin_path = resolve_artifact_path(PLUGINS_DIR, plugin_file, allowed_suffixes={".pyc"})
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

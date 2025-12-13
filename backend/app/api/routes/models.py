import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.api.deps import get_current_user
from app.core.db import engine
from app.models import User

router = APIRouter()

# Base directory for plugins
MODELS_DIR = Path("data/models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(
    filename="model_downloads.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
)


@router.get("/", summary="Get list of available models")
async def get_models():
    """
    Returns a list of available models.
    """
    metadata_list = []

    for fpath in MODELS_DIR.glob("*.*"):
        try:
            metadata = {}
            metadata["file_name"] = fpath.name
            metadata["version"] = fpath.stem.split("_")[1]
            metadata_list.append(metadata)
        except IndexError:
            logging.info(f"Skipping malformed filename: {fpath.name}")

    response = JSONResponse(content=metadata_list)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response


@router.get("/{model_file}", summary="Download a specific model")
async def download_plugin(
    model_file: str, request: Request, current_user: User = Depends(get_current_user)
):
    """
    Serves the requested plugin file if the correct token was passed.
    model_file like 'default_0.1.0.mdl'
    """

    model_path = MODELS_DIR / model_file
    if not model_path.exists():
        raise HTTPException(status_code=404, detail="Plugin not found")

    # Log the download to file
    client_ip = request.client.host
    user_agent = request.headers.get("User-Agent", "Unknown")
    logging.info(
        "Download: %s | IP: %s | User-Agent: %s | User: %s (%s)",
        model_path,
        client_ip,
        user_agent,
        getattr(current_user, "email", "unknown"),
        getattr(current_user, "id", "unknown"),
    )

    # Log the download to the database
    query = text(
        """
        INSERT INTO model_downloads (model_file, client_ip, user_agent, downloaded_at, user_id)
        VALUES (:model_file, :client_ip, :user_agent, NOW(), :user_id)
        """
    )
    with engine.begin() as conn:
        conn.execute(
            query,
            {
                "model_file": model_file,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "user_id": str(current_user.id),
            },
        )

    return FileResponse(
        model_path,
        media_type="application/octet-stream",
        filename=model_file,
    )

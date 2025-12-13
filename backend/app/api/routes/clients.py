import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.core.db import engine

router = APIRouter()

# Base directory for plugins
CLIENTS_DIR = Path("data/clients")
CLIENTS_DIR.mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(
    filename="client_downloads.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
)

# Setup file suffix by platform
SUFFIX = {"win64": "exe", "macos": "dmg", "linux": ""}


@router.get("/", summary="Get list of available client installers")
async def get_plugins():
    """
    Returns a list of available client installers and their metadata, grouped by file type.
    """
    client_metadata = []

    # Recursively traverse plugin subdirectories
    for client_file in CLIENTS_DIR.glob("**/*.*"):
        try:
            metadata = {}
            metadata["file_name"] = client_file.name
            metadata["version"] = client_file.stem.split("_")[1]
            metadata["platform"] = client_file.stem.split("_")[2]
            metadata["file_path"] = str(client_file.parent.relative_to(CLIENTS_DIR))
            client_metadata.append(metadata)
        except IndexError:
            logging.info(f"Skipping malformed filename: {client_file.name}")

    response = JSONResponse(content=client_metadata)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response


@router.get("/{platform}/{version}", summary="Download a client setup.exe")
async def download_client(platform: str, version: str, request: Request):
    """
    Serves the requested client install file.
    """
    suffix = SUFFIX[platform]
    if version == "latest":
        # Serve the latest version
        platform_dir = CLIENTS_DIR / platform
        if not platform_dir.exists() or not platform_dir.is_dir():
            raise HTTPException(status_code=404, detail="Platform not found")

        # Find the latest version by sorting the filenames
        client_files = list(
            platform_dir.glob(f"parsetrail_*_{platform}_setup.{suffix}")
        )
        if not client_files:
            raise HTTPException(
                status_code=404,
                detail=f"No client installers available for {platform}",
            )

        # Extract version numbers and sort
        try:
            client_files.sort(key=lambda f: f.stem.split("_")[1], reverse=True)
        except IndexError:
            raise HTTPException(
                status_code=500, detail="Invalid file naming convention"
            )

        client_path = client_files[0]
        version = client_path.stem.split("_")[1]  # Update version to the latest
    else:
        # Download specific version
        client_path = (
            CLIENTS_DIR / platform / f"parsetrail_{version}_{platform}_setup.{suffix}"
        )

    if not client_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"'parsetrail_{version}_{platform}_setup.{suffix}' not found",
        )

    # Log the download to file
    client_ip = request.client.host
    user_agent = request.headers.get("User-Agent", "Unknown")
    logging.info(
        f"Download: {client_path.stem} (type: {platform}) | IP: {client_ip} | User-Agent: {user_agent}"
    )

    # Log the download to the database
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
                "version": version,
                "client_ip": client_ip,
                "user_agent": user_agent,
            },
        )

    return FileResponse(
        client_path,
        media_type="application/octet-stream",
        filename=client_path.name,
    )

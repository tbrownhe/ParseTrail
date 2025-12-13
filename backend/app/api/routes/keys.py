import hashlib
import logging
import subprocess
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text

from app.core.db import engine

router = APIRouter()


# Path to keys
KEYS_DIR = Path("keys")
PRIVATE_KEY_PATH = KEYS_DIR / "private_key.pem"
PUBLIC_KEY_PATH = KEYS_DIR / "public_key.pem"


# Ensure the key directory exists
KEYS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_permissions():
    """
    Ensure the correct permissions are set for the keys directory and its contents.
    """
    try:
        if KEYS_DIR.exists():
            subprocess.run(["chmod", "700", str(KEYS_DIR)], check=True)

        for key_file in KEYS_DIR.glob("*"):
            subprocess.run(["chmod", "600", str(key_file)], check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Permission change failed: {e}")
        raise RuntimeError("Failed to set key permissions")


def generate_new_rsa_keys():
    """Generate new RSA keys and save them to Docker volume"""
    try:
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        ...
    except Exception as e:
        logging.error(f"Failed to generate RSA keys: {e}")
        raise

    # Save the private key to a file
    with PRIVATE_KEY_PATH.open("wb") as private_key_file:
        private_key_file.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    # Generate the public key from the private key
    public_key = private_key.public_key()

    # Save the public key to a file
    with PUBLIC_KEY_PATH.open("wb") as public_key_file:
        public_key_file.write(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    # Restrict key permissions immediately
    ensure_permissions()


def is_key_expired(key_path: Path, max_age_days: int = 365):
    if not key_path.exists():
        return True
    file_age = (time.time() - key_path.stat().st_mtime) / (24 * 3600)
    return file_age > max_age_days


# Create new keys if none exist
if not PRIVATE_KEY_PATH.exists() or not PUBLIC_KEY_PATH.exists():
    generate_new_rsa_keys()

# Create new keys if they are expired
if is_key_expired(PRIVATE_KEY_PATH):
    logging.info("RSA key expired. Generating new keys.")
    generate_new_rsa_keys()


# Configure logging
logging.basicConfig(
    filename="public_key_requests.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
)


@router.get("/public-key", summary="Get the server's public RSA key")
async def get_public_key(request: Request):
    """
    Returns the server's public RSA key.
    """
    try:
        with PUBLIC_KEY_PATH.open("rb") as key_file:
            public_key = key_file.read()
    except FileNotFoundError:
        logging.error("Public key file not found.")
        raise HTTPException(status_code=500, detail="Public key file not found")
    except Exception as e:
        logging.error(f"Error reading public key file: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving public key")

    try:
        client_ip = request.client.host or "unknown"
        user_agent = request.headers.get("User-Agent", "Unknown")
        user_agent = user_agent[:255]
        key_type = "public_key"

        logging.info(
            f"Key request received from {client_ip} with user agent {user_agent}"
        )

        query = text(
            """
            INSERT INTO key_requests (key_type, client_ip, user_agent)
            VALUES (:key_type, :client_ip, :user_agent)
            """
        )
        with engine.begin() as conn:
            conn.execute(
                query,
                {
                    "key_type": key_type,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                },
            )
    except Exception as e:
        logging.error(f"Error logging key request: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving public key")

    # Return public key file to client
    return Response(content=public_key, media_type="application/x-pem-file")


@router.get("/public-key-hash", summary="Get the hash of the server's public RSA key")
async def get_public_key_hash():
    """
    Returns the SHA-256 hash of the server's public RSA key.
    """
    try:
        with open(PUBLIC_KEY_PATH, "rb") as key_file:
            public_key = key_file.read()
    except FileNotFoundError:
        logging.error("Public key file not found.")
        raise HTTPException(status_code=500, detail="Public key file not found")
    except Exception as e:
        logging.error(f"Error reading public key file: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving public key")

    # Compute the SHA-256 hash of the public key
    public_key_hash = hashlib.sha256(public_key).hexdigest()
    logging.info("Public key hash served successfully.")

    return {
        "hash": public_key_hash,
        "key_last_updated": PRIVATE_KEY_PATH.stat().st_mtime,
    }

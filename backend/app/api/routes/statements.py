import base64
import logging
import os
import stat
import uuid
from os import urandom
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from sqlalchemy import text

from app.api.deps import get_current_user
from app.api.routes.keys import PRIVATE_KEY_PATH
from app.core.config import settings
from app.core.db import engine
from app.models import User

router = APIRouter()

# Base directory for uploaded statements
STATEMENTS_DIR = Path("secure/statements")
STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)

# Ensure only the service account can access the directory (no group/world perms).
STATEMENTS_DIR.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def _resolve_owner_from_settings() -> tuple[int, int] | None:
    """
    Resolve STATEMENTS_FILE_OWNER/GROUP from settings to numeric (uid, gid).
    Returns None when no override is configured.
    """
    owner = settings.STATEMENTS_FILE_OWNER
    group = settings.STATEMENTS_FILE_GROUP

    # Skip when not explicitly configured
    if not owner and not group:
        return None

    def _uid(value: str | None) -> int:
        if not value:
            return -1  # -1 leaves uid unchanged
        try:
            return int(value)
        except ValueError as exc:
            raise RuntimeError(
                "STATEMENTS_FILE_OWNER must be a numeric uid (or unset)."
            ) from exc

    def _gid(value: str | None) -> int:
        if not value:
            return -1  # -1 leaves gid unchanged
        try:
            return int(value)
        except ValueError as exc:
            raise RuntimeError(
                "STATEMENTS_FILE_GROUP must be a numeric gid (or unset)."
            ) from exc

    return _uid(owner), _gid(group)


STATEMENTS_OWNER_IDS = _resolve_owner_from_settings()


def _apply_owner(path: Path, *, fatal: bool = False) -> None:
    """
    Apply configured owner/group to a path when STATEMENTS_FILE_OWNER/GROUP are set.
    If fatal is True, raise RuntimeError on failure (used during startup).
    """
    if STATEMENTS_OWNER_IDS is None:
        return

    uid, gid = STATEMENTS_OWNER_IDS
    try:
        os.chown(path, uid, gid)
    except PermissionError as exc:
        message = (
            f"Failed to set ownership on {path} to STATEMENTS_FILE_OWNER/STATEMENTS_FILE_GROUP "
            "because the process lacks permission. Run the service with the ability to chown or "
            "remove the ownership override."
        )
        if fatal:
            raise RuntimeError(message) from exc
        raise HTTPException(status_code=500, detail=message) from exc
    except OSError as exc:
        message = f"Failed to set ownership on {path}: {exc}"
        if fatal:
            raise RuntimeError(message) from exc
        raise HTTPException(status_code=500, detail=message) from exc


# Load server's private key.
with PRIVATE_KEY_PATH.open("rb") as key_file:
    PRIVATE_KEY = serialization.load_pem_private_key(key_file.read(), password=None)


def load_master_key():
    """Load MASTER_KEY from env vars and ensure it's 32 bytes for AES"""
    master_key_b64 = os.getenv("MASTER_KEY")
    if not master_key_b64:
        raise RuntimeError("MASTER_KEY not set in environment")
    master_key = base64.b64decode(master_key_b64)
    if len(master_key) != 32:
        raise ValueError(f"Master key must be 32 bytes, got {len(master_key)}")
    return master_key


def load_master_key_from_docker_secrets():
    """
    Note: This is not currently used.
    For when I decide to use Docker Swarm with Docker Secrets.
    Reads the master key from Docker Secrets.
    Returns the master key as a bytes object.
    """
    secret_path = Path("/run/secrets/master_key")
    if secret_path.exists():
        with secret_path.open("r") as secret_file:
            return secret_file.read().strip().encode("utf-8")
    else:
        raise HTTPException(status_code=500, detail="Master key not found in secrets")


def decrypt_client_key(encrypted_key_b64: str) -> bytes:
    """Uses server's private key to decrypt the client's symmetric key
    that was encrypted using the server's public key.
    Encrypted key is encoded as Base64.

    Args:
        encrypted_key (bytes): Encrypted symmetric key from client

    Returns:
        bytes: Decrypted symmetric key for decrypting the incoming file
    """
    encrypted_key = base64.b64decode(encrypted_key_b64)
    return PRIVATE_KEY.decrypt(
        encrypted_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def decrypt_client_data(symmetric_key: bytes, encrypted_data: bytes) -> bytes:
    """Decrypts data using client-generated symmetric key.

    Args:
        symmetric_key (bytes): Client-generated symmetric key
        encrypted_data (bytes): File data encrypted with symmetric key

    Returns:
        bytes: Decrypted data
    """
    return Fernet(symmetric_key).decrypt(encrypted_data)


def aes_encrypt_data(data: bytes) -> tuple[bytes, bytes, bytes]:
    """Uses AES-GCM to encrypt data.

    Args:
        data (bytes): Data to encrypt

    Returns:
        tuple[bytes, bytes, bytes]: Init Vector, Encrypted Data, Auth Tag
    """
    master_key = load_master_key()
    iv = urandom(16)  # 16-byte IV for AES-GCM
    cipher = Cipher(algorithms.AES(master_key), modes.GCM(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(data) + encryptor.finalize()
    return iv, ciphertext, encryptor.tag


# Configure logging
logging.basicConfig(
    filename="statement_uploads.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
)


@router.post(
    "/submit-statement", summary="Upload and store an encrypted bank statement"
)
async def upload_statement(
    file: UploadFile,
    request: Request,
    metadata: str = Form(...),
    encrypted_key: bytes = Form(...),
    current_user: User = Depends(get_current_user),
):
    """
    Handles encrypted bank statement uploads.
    1. Decrypt the client's symmetric key.
    2. Decrypt the file using the symmetric key.
    3. Encrypt the file with AES-GCM using the master key.
    4. Save the AES-encrypted file to disk.
    5. Log upload details to logfile and the database.
    """

    # Prevent abuse
    if not metadata or len(metadata) > 256:
        raise HTTPException(status_code=400, detail="Invalid metadata")
    metadata = metadata[:256].strip()

    # Step 1: Decrypt the client's symmetric key using the server's private RSA key
    try:
        symmetric_key = decrypt_client_key(encrypted_key)
    except Exception as e:
        logging.error(f"Failed to decrypt symmetric key: {e}")
        raise HTTPException(
            status_code=400, detail=f"Failed to decrypt symmetric key: {e}"
        )

    # Step 2: Decrypt the file using the client's symmetric key
    try:
        encrypted_data = await file.read()
        decrypted_data = decrypt_client_data(symmetric_key, encrypted_data)
    except Exception as e:
        logging.error(f"Failed to decrypt file: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to decrypt file: {e}")

    # Step 3: Encrypt the file using AES-GCM with the master key
    try:
        iv, reencrypted_data, auth_tag = aes_encrypt_data(decrypted_data)
    except Exception as e:
        logging.error(f"Failed to encrypt file for storage: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to encrypt file for storage, aborting: {e}"
        )

    # Step 4: Save the AES-encrypted file to disk
    guid_filename = f"{uuid.uuid4()}.enc"
    file_path = STATEMENTS_DIR / guid_filename
    temp_path = file_path.with_suffix(".tmp")
    try:
        with temp_path.open("wb") as f:
            f.write(reencrypted_data)
        temp_path.replace(file_path)

        # Lock down permissions as soon as the file is saved: user RW only
        os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)
        _apply_owner(file_path)

    except Exception as e:
        logging.error(f"Failed to save file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # Step 5: Log upload details to logfile and the database
    try:
        client_ip = request.client.host
        user_agent = request.headers.get("User-Agent", "Unknown")
        sanitized_metadata = (
            metadata[:256].replace("\n", " ").replace("\r", " ").strip()
        )

        logging.info(
            "Upload received: %s from IP: %s (%s) with sanitized metadata",
            file.filename,
            client_ip,
            getattr(current_user, "id", "unknown"),
        )

        query = text(
            """
            INSERT INTO statement_uploads (file_name, metadata, init_vector, auth_tag, client_ip, user_agent, user_id)
            VALUES (:file_name, :metadata, :init_vector, :auth_tag, :client_ip, :user_agent, :user_id)
            """
        )

        with engine.begin() as conn:
            conn.execute(
                query,
                {
                    "file_name": guid_filename,
                    "metadata": sanitized_metadata,
                    "init_vector": iv,
                    "auth_tag": auth_tag,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                    "user_id": str(current_user.id),
                },
            )
    except Exception as e:
        logging.error(f"Error logging upload to database: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to log upload: {e}")

    # Return a success message to client
    return {"message": "SUCCESS"}

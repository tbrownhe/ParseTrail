import hashlib
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text

from app.api.request_utils import get_client_host, get_user_agent
from app.core.db import engine
from app.core.statement_submission import MAX_CLIENT_IP_CHARS, MAX_USER_AGENT_CHARS, bounded_log_value
from app.core.submission_keys import SubmissionKeyError, load_active_public_key

router = APIRouter()

logging.basicConfig(
    filename="public_key_requests.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
)


@router.get("/public-key", summary="Get the active statement-submission RSA key")
async def get_public_key(request: Request) -> Response:
    """Return the active public key; provisioning is owned by prestart."""
    try:
        key_id, public_key, _ = load_active_public_key()
    except SubmissionKeyError as exc:
        logging.error("Submission public key unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Submission public key unavailable")

    try:
        client_ip = bounded_log_value(get_client_host(request), MAX_CLIENT_IP_CHARS)
        user_agent = bounded_log_value(get_user_agent(request), MAX_USER_AGENT_CHARS)
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
                    "key_type": key_id,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                },
            )
    except Exception as exc:
        logging.error("Submission key request registration failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Submission public key unavailable")

    return Response(
        content=public_key,
        media_type="application/x-pem-file",
        headers={"X-ParseTrail-Key-Id": key_id},
    )


@router.get("/public-key-hash", summary="Get the active submission-key fingerprint")
async def get_public_key_hash() -> dict[str, str | float]:
    try:
        key_id, public_key, modified_at = load_active_public_key()
    except SubmissionKeyError as exc:
        logging.error("Submission public key unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Submission public key unavailable")
    return {
        "hash": hashlib.sha256(public_key).hexdigest(),
        "key_id": key_id,
        "key_last_updated": modified_at,
    }

"""Small helpers for request metadata that may be absent or unbounded."""

import ipaddress

from fastapi import Request

from app.core.config import settings


def get_client_host(request: Request) -> str:
    if settings.ENVIRONMENT == "production":
        cloudflare_host = request.headers.get("CF-Connecting-IP", "").strip()
        try:
            return str(ipaddress.ip_address(cloudflare_host))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request, *, max_length: int = 255) -> str:
    return request.headers.get("User-Agent", "Unknown")[:max_length]

"""Small helpers for request metadata that may be absent or unbounded."""

from fastapi import Request


def get_client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request, *, max_length: int = 255) -> str:
    return request.headers.get("User-Agent", "Unknown")[:max_length]

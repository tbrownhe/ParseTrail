from fastapi import HTTPException, Request, Response, status

from app.core.config import settings

BROWSER_SESSION_COOKIE = "__Host-parsetrail_session" if settings.ENVIRONMENT != "local" else "parsetrail_session"
COOKIE_MAX_AGE_SECONDS = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def require_frontend_origin(request: Request) -> None:
    """Accept browser mutations only from the configured dashboard origin."""
    if request.headers.get("origin") != settings.FRONTEND_HOST:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-site request rejected",
        )


def protect_cookie_authenticated_request(request: Request) -> None:
    if request.method.upper() not in SAFE_METHODS:
        require_frontend_origin(request)


def set_browser_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=BROWSER_SESSION_COOKIE,
        value=token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        path="/",
        secure=settings.ENVIRONMENT != "local",
        httponly=True,
        samesite="strict",
    )


def clear_browser_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=BROWSER_SESSION_COOKIE,
        path="/",
        secure=settings.ENVIRONMENT != "local",
        httponly=True,
        samesite="strict",
    )

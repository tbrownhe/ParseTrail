from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import requests
from loguru import logger

from parsetrail.core.network import HttpTransport, NetworkError, raise_for_response
from parsetrail.core.settings import AppSettings, save_settings, settings

# Keep this in sync with backend/app/core/config.py
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 2
LOGIN_PATH = "/login/access-token"


class AuthError(Exception):
    """Raised when authentication is required or fails."""

    pass


# Type for the UI-provided credential prompt
PromptFunc = Callable[[], tuple[str, str] | None]


def _default_prompt_for_credentials() -> tuple[str, str] | None:
    """
    Default implementation. The core layer does not know how to get credentials.
    Your UI code should patch `prompt_for_credentials` at app startup.
    """
    raise RuntimeError("prompt_for_credentials() is not configured")


# This gets patched by the UI layer (e.g. Qt dialog)
prompt_for_credentials: PromptFunc = _default_prompt_for_credentials


class AuthManager:
    """
    Handles login, token storage, and providing Authorization headers.
    Totally UI-agnostic: it just calls `prompt_for_credentials()` when needed.
    """

    def __init__(
        self,
        app_settings: AppSettings,
        *,
        transport: HttpTransport | None = None,
    ):
        self.settings = app_settings
        self.base_url = str(app_settings.server_url).rstrip("/")
        self.transport = transport or HttpTransport()
        self._token: str = app_settings.access_token or ""

        expires_ts = app_settings.token_expires_at
        if expires_ts:
            try:
                self._token_expires_at: datetime | None = datetime.fromtimestamp(expires_ts, tz=timezone.utc)
            except (OSError, OverflowError, ValueError) as e:
                logger.warning(f"Ignoring invalid token_expires_at in settings: {e}")
                self._token_expires_at = None
        else:
            self._token_expires_at = None

    def _is_token_valid(self) -> bool:
        """
        Local check for token validity. If we don't know expiry, we assume valid
        until the server returns 401.
        """
        if not self._token:
            return False
        if self._token_expires_at is None:
            return True
        return datetime.now(timezone.utc) < self._token_expires_at.astimezone(timezone.utc)

    def _login(self) -> bool:
        """
        Prompt the user for email/password (via the patched UI callback)
        and call the backend /login/access-token endpoint.

        Returns True on success, False on cancel or login failure.
        """
        creds = prompt_for_credentials()
        if creds is None:
            return False

        email, password = creds

        try:
            resp = self.transport.request(
                "POST",
                f"{self.base_url}{LOGIN_PATH}",
                action="signing in",
                data={"username": email, "password": password},
            )
            raise_for_response(resp, "signing in")
        except NetworkError as e:
            logger.error("{}", e)
            return False

        try:
            payload = resp.json()
            token = payload["access_token"]
            if not isinstance(token, str) or not token:
                raise ValueError
        except (KeyError, requests.JSONDecodeError, TypeError, ValueError):
            logger.error("Sign-in response did not match the expected schema")
            return False

        self._token = token
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

        # Persist token
        self.settings.email = email
        self.settings.access_token = token
        self.settings.token_expires_at = self._token_expires_at.timestamp()
        save_settings(self.settings)
        return True

    def clear_token(self) -> None:
        """Clear token from memory and settings."""
        self._token = ""
        self._token_expires_at = None
        self.settings.access_token = ""
        self.settings.token_expires_at = 0.0
        save_settings(self.settings)

    def get_auth_headers(self) -> dict:
        """
        Return Authorization headers, prompting for login if needed.

        Raises AuthError if the user cancels or login fails.
        """
        if not self._is_token_valid():
            if not self._login():
                raise AuthError("User cancelled login or login failed")
        return {"Authorization": f"Bearer {self._token}"}


# Singleton instance, mirroring core.settings.settings
auth_manager = AuthManager(settings)

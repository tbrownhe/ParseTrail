from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Tuple

import requests
from loguru import logger
from parsetrail.core.settings import AppSettings, save_settings, settings

# Keep this in sync with backend/app/core/config.py
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 2
LOGIN_PATH = "/login/access-token"


class AuthError(Exception):
    """Raised when authentication is required or fails."""

    pass


# Type for the UI-provided credential prompt
PromptFunc = Callable[[], Optional[Tuple[str, str]]]


def _default_prompt_for_credentials() -> Optional[Tuple[str, str]]:
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

    def __init__(self, app_settings: AppSettings):
        self.settings = app_settings
        self.base_url = str(settings.server_url).rstrip("/")
        self._token: str = app_settings.access_token or ""

        expires_ts = app_settings.token_expires_at
        if expires_ts:
            try:
                self._token_expires_at: Optional[datetime] = datetime.fromtimestamp(expires_ts, tz=timezone.utc)
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
            resp = requests.post(
                f"{self.base_url}{LOGIN_PATH}",
                data={"username": email, "password": password},
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("{}", e)
            return False

        payload = resp.json()
        token = payload["access_token"]

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

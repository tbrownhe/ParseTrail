from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import requests
from loguru import logger

from parsetrail.core.credentials import TokenStore, credential_store
from parsetrail.core.network import HttpTransport, NetworkError, raise_for_response
from parsetrail.core.settings import (
    AppSettings,
    retire_legacy_credential_key,
    save_settings,
    settings,
)

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
        token_store: TokenStore = credential_store,
    ):
        self.settings = app_settings
        self.base_url = str(app_settings.server_url).rstrip("/")
        self.transport = transport or HttpTransport()
        self.token_store = token_store
        stored_token = token_store.get_token()
        legacy_token = app_settings.access_token or ""
        self._token: str = stored_token or legacy_token
        if legacy_token:
            if stored_token is None:
                token_store.set_token(legacy_token)
            app_settings.access_token = ""
            save_settings(app_settings)
        retire_legacy_credential_key()

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

    def credentials_if_needed(self) -> tuple[str, str] | None:
        """Prompt on the caller's thread, returning credentials for worker login."""
        if self._is_token_valid():
            return None
        credentials = prompt_for_credentials()
        if credentials is None:
            raise AuthError("Sign-in was cancelled.")
        return credentials

    def login(self, email: str, password: str) -> None:
        """Authenticate over the network without invoking any UI callback."""
        try:
            resp = self.transport.request(
                "POST",
                f"{self.base_url}{LOGIN_PATH}",
                action="signing in",
                data={"username": email, "password": password},
            )
            raise_for_response(resp, "signing in")
        except NetworkError as exc:
            raise AuthError(str(exc)) from exc

        try:
            payload = resp.json()
            token = payload["access_token"]
            if not isinstance(token, str) or not token:
                raise ValueError
        except (KeyError, requests.JSONDecodeError, TypeError, ValueError) as exc:
            raise AuthError("The sign-in response was invalid.") from exc

        self._token = token
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        self.settings.email = email
        self.settings.token_expires_at = self._token_expires_at.timestamp()
        self.token_store.set_token(token)
        save_settings(self.settings)

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
            self.login(email, password)
        except AuthError as exc:
            logger.error("{}", exc)
            return False
        return True

    def clear_token(self) -> None:
        """Clear token from memory and settings."""
        self._token = ""
        self._token_expires_at = None
        self.settings.access_token = ""
        self.settings.token_expires_at = 0.0
        self.token_store.delete_token()
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

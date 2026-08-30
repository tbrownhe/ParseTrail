"""OS credential-store boundary for the desktop access token."""

from __future__ import annotations

from typing import Protocol

import keyring
from keyring.backend import KeyringBackend
from loguru import logger

from parsetrail.core.profile import credential_service_name

SERVICE_NAME = credential_service_name()
ACCESS_TOKEN_ACCOUNT = "api-access-token"
_SECURE_BACKEND_MODULES = (
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
    "keyring.backends.libsecret",
)


class TokenStore(Protocol):
    def get_token(self) -> str | None: ...

    def set_token(self, token: str) -> bool: ...

    def delete_token(self) -> None: ...


def _is_secure_backend(backend: KeyringBackend) -> bool:
    module = type(backend).__module__
    if module.startswith(_SECURE_BACKEND_MODULES):
        return True
    if module == "keyring.backends.chainer":
        candidates = tuple(getattr(backend, "backends", ()))
        return bool(candidates) and all(_is_secure_backend(candidate) for candidate in candidates)
    return False


class CredentialStore:
    """Persist tokens only when keyring selected a known OS-backed provider."""

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        self.backend = backend or keyring.get_keyring()
        self.available = _is_secure_backend(self.backend)
        if not self.available:
            logger.warning("No supported OS credential store is available; server login will be kept in memory only")

    def get_token(self) -> str | None:
        if not self.available:
            return None
        try:
            token = self.backend.get_password(SERVICE_NAME, ACCESS_TOKEN_ACCOUNT)
        except Exception as exc:
            logger.warning(
                "Could not read the OS credential store ({})",
                type(exc).__name__,
            )
            return None
        return token if isinstance(token, str) and token else None

    def set_token(self, token: str) -> bool:
        if not token or not self.available:
            return False
        try:
            self.backend.set_password(SERVICE_NAME, ACCESS_TOKEN_ACCOUNT, token)
        except Exception as exc:
            logger.warning(
                "Could not write the OS credential store ({}); login remains in memory only",
                type(exc).__name__,
            )
            return False
        return True

    def delete_token(self) -> None:
        if not self.available:
            return
        try:
            self.backend.delete_password(SERVICE_NAME, ACCESS_TOKEN_ACCOUNT)
        except Exception as exc:
            logger.debug(
                "OS credential was already absent or could not be deleted ({})",
                type(exc).__name__,
            )


credential_store = CredentialStore()

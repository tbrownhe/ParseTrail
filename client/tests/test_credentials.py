from __future__ import annotations

from types import SimpleNamespace

from cryptography.fernet import Fernet
from parsetrail.core import auth, credentials
from parsetrail.core import settings as settings_module
from parsetrail.core.auth import AuthManager
from parsetrail.core.credentials import CredentialStore
from parsetrail.core.settings import AppSettings


class _MemoryBackend:
    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.passwords.get((service, account))

    def set_password(self, service: str, account: str, password: str) -> None:
        self.passwords[(service, account)] = password

    def delete_password(self, service: str, account: str) -> None:
        self.passwords.pop((service, account), None)


class _TokenStore:
    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self.set_calls: list[str] = []
        self.delete_calls = 0

    def get_token(self) -> str | None:
        return self.token

    def set_token(self, token: str) -> bool:
        self.token = token
        self.set_calls.append(token)
        return True

    def delete_token(self) -> None:
        self.token = None
        self.delete_calls += 1


def test_secure_store_round_trip_uses_backend_without_logging_token(monkeypatch) -> None:
    backend = _MemoryBackend()
    monkeypatch.setattr(credentials, "_is_secure_backend", lambda _backend: True)
    store = CredentialStore(backend)

    assert store.get_token() is None
    assert store.set_token("secret-token")
    assert store.get_token() == "secret-token"
    store.delete_token()
    assert store.get_token() is None


def test_insecure_or_null_backend_never_persists() -> None:
    backend = _MemoryBackend()
    store = CredentialStore(backend)

    assert not store.available
    assert not store.set_token("must-remain-in-memory")
    assert backend.passwords == {}


def test_settings_never_serialize_plain_or_file_encrypted_token() -> None:
    saved = AppSettings(access_token="secret-token").prepare_for_save()

    assert "access_token" not in saved
    assert "encrypted_access_token" not in saved
    assert saved["config_version"] == "1.1.0"


def test_legacy_token_is_decrypted_only_for_os_store_migration(monkeypatch, tmp_path) -> None:
    key = Fernet.generate_key()
    key_path = tmp_path / ".parsetrail.key"
    key_path.write_bytes(key)
    encrypted = Fernet(key).encrypt(b"legacy-token").decode()
    monkeypatch.setattr(settings_module, "LEGACY_CREDENTIAL_KEY", key_path)

    loaded = AppSettings.from_saved(
        {
            "email": "user@example.com",
            "encrypted_access_token": encrypted,
        }
    )

    assert loaded.access_token == "legacy-token"
    assert loaded.config_version == "1.1.0"
    assert "encrypted_access_token" not in loaded.prepare_for_save()


def test_auth_manager_moves_legacy_token_then_retires_file_key(monkeypatch) -> None:
    token_store = _TokenStore()
    saves: list[object] = []
    retired: list[bool] = []
    app_settings = SimpleNamespace(
        server_url="https://api.example.test",
        access_token="legacy-token",
        token_expires_at=0,
        email="user@example.com",
    )
    monkeypatch.setattr(auth, "save_settings", saves.append)
    monkeypatch.setattr(auth, "retire_legacy_credential_key", lambda: retired.append(True))

    manager = AuthManager(app_settings, token_store=token_store)

    assert manager._token == "legacy-token"
    assert token_store.set_calls == ["legacy-token"]
    assert app_settings.access_token == ""
    assert saves == [app_settings]
    assert retired == [True]


def test_clear_token_removes_os_credential(monkeypatch) -> None:
    token_store = _TokenStore("stored-token")
    app_settings = SimpleNamespace(
        server_url="https://api.example.test",
        access_token="",
        token_expires_at=0,
        email="user@example.com",
    )
    monkeypatch.setattr(auth, "save_settings", lambda _settings: None)
    monkeypatch.setattr(auth, "retire_legacy_credential_key", lambda: None)
    manager = AuthManager(app_settings, token_store=token_store)

    manager.clear_token()

    assert token_store.delete_calls == 1
    assert manager._token == ""
    assert app_settings.email == "user@example.com"


def test_explicit_sign_out_forgets_prefilled_email(monkeypatch) -> None:
    token_store = _TokenStore("stored-token")
    app_settings = SimpleNamespace(
        server_url="https://api.example.test",
        access_token="",
        token_expires_at=0,
        email="user@example.com",
    )
    saves = []
    monkeypatch.setattr(auth, "save_settings", saves.append)
    monkeypatch.setattr(auth, "retire_legacy_credential_key", lambda: None)
    manager = AuthManager(app_settings, token_store=token_store)

    manager.clear_token(clear_email=True)

    assert token_store.delete_calls == 1
    assert manager._token == ""
    assert app_settings.email == ""
    assert saves == [app_settings]

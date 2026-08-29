import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _settings_env_file() -> str | None:
    """Select an explicit dotenv, the project default when present, or none."""
    configured = os.getenv("PARSETRAIL_ENV_FILE")
    if configured is not None:
        if not configured.strip():
            return None
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Configured environment file does not exist: {path}")
        return str(path)
    return str(DEFAULT_ENV_FILE) if DEFAULT_ENV_FILE.is_file() else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_ignore_empty=True,
        extra="ignore",
    )

    # Where is this being run
    ENVIRONMENT: str = "local"

    # Crypto
    MASTER_KEY: str | None = None  # base64 encoded

    # Database
    POSTGRES_SERVER: str = ""
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    # Local resources
    STATEMENTS_DIR: str = ""
    PLUGINS_DIR: str = ""

    # Remote resources
    SSH_KEY_PATH: str = ""
    REMOTE_HOST: str = ""
    REMOTE_USER: str = ""
    REMOTE_ENV_PATH: str = ""
    REMOTE_STATEMENTS_DIR: str = ""

    # DB tunneling (via ssh -L)
    SSH_TUNNEL_ENABLE: bool = False
    SSH_TUNNEL_LOCAL_PORT: int = 55432
    DB_CONTAINER_NAME: str = "parsetrail-db-1"
    DB_CONTAINER_PORT: int = 5432

    def _check_environment(self, value: str | None) -> None:
        if value not in ["local", "staging", "production"]:
            raise ValueError(f"Unrecognized environment: {value}")

    def _check_remote_creds(self, env: str, host: str, user: str) -> None:
        if env != "local":
            return
        if self.SSH_TUNNEL_ENABLE and not host:
            raise ValueError("REMOTE_HOST is required when SSH_TUNNEL_ENABLE is True")
        if self.SSH_TUNNEL_ENABLE and not user:
            raise ValueError("REMOTE_USER is required when SSH_TUNNEL_ENABLE is True")

    @model_validator(mode="after")
    def _enforce_settings(self) -> Self:
        self._check_environment(self.ENVIRONMENT)
        self._check_remote_creds(self.ENVIRONMENT, self.REMOTE_HOST, self.REMOTE_USER)
        return self


settings = Settings(_env_file=_settings_env_file())  # type: ignore


def require_runtime_settings(current: Settings | None = None) -> Settings:
    """Reject incomplete configuration only when a devtool operation starts."""
    current = current or settings
    if not current.PLUGINS_DIR:
        raise ValueError("PLUGINS_DIR is required for statement parser development")
    return current

from pathlib import Path
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self

# Use project-level .env
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
if not ENV_FILE.exists():
    raise FileNotFoundError(f"Project-level .env not fount at {ENV_FILE}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_ignore_empty=True,
        extra="ignore",
    )

    # Where is this being run
    ENVIRONMENT: str = "local"

    # Crypto
    MASTER_KEY: Optional[str] = None  # base64 encoded

    # Database
    POSTGRES_SERVER: str = ""
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    # Local resources
    STATEMENTS_DIR: str = ""

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
        if value not in ["local", "production"]:
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


settings = Settings()  # type: ignore

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from platform import architecture, system

from cryptography.fernet import Fernet
from loguru import logger
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from parsetrail.version import __version__


class SettingsSaveError(RuntimeError):
    """Raised when validated application settings cannot be persisted."""


def get_platform() -> str:
    """Define platform naming conventions.
    win32, win64, macos32, macos64, linux32, linux64

    Returns:
        str: Platform and architecture
    """
    sys_name = system()
    arch = [bits for bits in ["32", "64"] if bits in architecture()[0]][0]
    if sys_name == "Windows":
        return "win" + arch
    elif sys_name == "Darwin":
        return "macos"
    elif sys_name == "Linux":
        return "linux" + arch


def get_download_dir() -> Path:
    """Platform-dependent downloads directory.

    Raises:
        ValueError: Unsupported platform

    Returns:
        Path: Downloads directory
    """
    os_name = os.name
    if os_name == "nt":
        # Windows
        return Path(os.getenv("USERPROFILE")).resolve() / "Downloads"
    elif os_name == "posix":
        if "XDG_DOWNLOAD_DIR" in os.environ:
            # Linux with XDG spec
            return Path(os.getenv("XDG_DOWNLOAD_DIR")).resolve()
        # Default for Linux/macOS
        return Path.home().resolve() / "Downloads"
    else:
        raise ValueError("Unsupported operating system")


# Constants for platform-dependent paths
APPDATA_DIR = (
    Path.home() / "AppData/Roaming/ParseTrail"  # Windows
    if system() == "Windows"
    else (
        Path.home() / "Library/Application Support/ParseTrail"  # macOS
        if system() == "Darwin"
        else Path.home() / ".config/ParseTrail"  # Linux
    )
)

APPDATA_DIR.mkdir(parents=True, exist_ok=True)
LEGACY_CREDENTIAL_KEY = Path.home() / ".parsetrail.key"


def _decrypt_legacy_token(encrypted_token: str) -> str | None:
    """Read the old file-encrypted token once without ever creating a new key."""
    try:
        key = LEGACY_CREDENTIAL_KEY.read_bytes()
        return Fernet(key).decrypt(encrypted_token.encode()).decode()
    except Exception as exc:
        logger.warning(
            "Could not migrate the legacy server login ({})",
            type(exc).__name__,
        )
        return None


def retire_legacy_credential_key() -> None:
    """Remove the obsolete same-profile decrypting key after token migration."""
    try:
        LEGACY_CREDENTIAL_KEY.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            "Could not remove obsolete credential key ({})",
            type(exc).__name__,
        )


class AppSettings(BaseSettings):
    """
    Application settings.

    Data lakes are derived from the database path:
      db_path = /path/to/primary.db
      import_dir = data_lake_root
      success_dir = data_lake_root/SUCCESS
      fail_dir = data_lake_root/FAIL
      duplicate_dir = data_lake_root/DUPLICATE
    """

    # Ignore any extra fields in the JSON
    model_config = SettingsConfigDict(extra="ignore")

    # Internal settings hidden from dialogs and config.py
    _platform: str = get_platform()
    _version: str = __version__
    _config_path: Path = APPDATA_DIR / "config.json"
    _accounts_json: Path = APPDATA_DIR / "accounts.json"
    _server_public_key: Path = APPDATA_DIR / "server_public_key.pem"
    _download_dir: Path = get_download_dir()

    @property
    def platform(self) -> str:
        """Getter for the hidden value"""
        return self._platform

    @property
    def version(self) -> str:
        """Getter for the hidden value"""
        return self._version

    @property
    def config_path(self) -> Path:
        """Getter for the hidden value"""
        return self._config_path

    @property
    def accounts_json(self) -> Path:
        """Getter for the hidden value"""
        return self._accounts_json

    @property
    def download_dir(self) -> Path:
        """Getter for the hidden value"""
        return self._download_dir

    @property
    def server_public_key(self) -> Path:
        """Getter for the hidden value"""
        return self._server_public_key

    # Internal settings written to config.json but not editable in PreferencesDialog
    config_version: str = Field("1.1.0", description="NO EDIT")
    server_url: AnyHttpUrl = Field(
        "https://api.parsetrail.com/api/v1",
        description="NO EDIT",
    )
    access_token: str = Field(
        "",
        description="NO EDIT",
        exclude=True,
        json_schema_extra={"sensitive": True},
    )
    token_expires_at: float = Field(0, description="NO EDIT")

    # Server login settings
    email: str = Field("", description="Email address for server login")
    # password: str = Field("", description="Password for server login", json_schema_extra={"sensitive": True})

    # Basic settings
    db_path: Path = Field(
        Path.home() / "Documents/ParseTrail/parsetrail.db",
        description="Database Path",
        json_schema_extra={"file_type": "Database Files (*.db)"},
    )
    model_dir: Path = Field(APPDATA_DIR / "models", description="Models Directory")
    model_path: Path = Field(
        Path(APPDATA_DIR / "models" / "default_0.1.0.mdl").resolve(),
        description="Transaction Classifier Model Path",
        json_schema_extra={"file_type": "Model Files (*.mdl)"},
    )
    plugin_dir: Path = Field(APPDATA_DIR / "plugins", description="Plugins Directory")
    log_file: Path = Field(APPDATA_DIR / "logs" / "parsetrail.log", description="Logs Directory")
    automatic_update_checks: bool = Field(
        True,
        description="Check for Client and Plugin Updates After Startup",
    )

    # Reports
    report_dir: Path = Field(
        Path.home() / "Documents" / "ParseTrail" / "Reports",
        description="Reports Export Directory",
    )

    @property
    def import_dir(self) -> Path:
        """Folder that corresponds to the current db stem.
        Drop-zone for new statements; matches the data lake root."""
        db_path = Path(self.db_path).expanduser().resolve()
        return db_path.parent / db_path.stem

    @property
    def success_dir(self) -> Path:
        return self.import_dir / "SUCCESS"

    @property
    def fail_dir(self) -> Path:
        return self.import_dir / "FAIL"

    @property
    def duplicate_dir(self) -> Path:
        return self.import_dir / "DUPLICATE"

    # config.json handling
    def prepare_for_save(self) -> dict:
        """Serialize non-secret settings; access tokens belong in the OS store."""
        return self.model_dump(mode="json", exclude={"access_token"})

    @classmethod
    def from_saved(cls, data: dict) -> "AppSettings":
        """
        Load settings and recover a legacy file-encrypted token for migration.
        Args:
            data (dict): The data loaded from the config file.
        Returns:
            AppSettings: The initialized settings object.
        """
        data = dict(data)
        data.pop("config_version", None)
        data.pop("access_token", None)
        encrypted_token = data.pop("encrypted_access_token", None)
        legacy_token = _decrypt_legacy_token(encrypted_token) if isinstance(encrypted_token, str) else None

        # Validate with defaults to ensure missing fields are populated
        # Ensure any missing fields from config.json are filled with defaults.
        instance = cls(**{**cls().model_dump(mode="python"), **data})
        if legacy_token:
            instance.access_token = legacy_token
        return instance


def backup_config(current: AppSettings) -> None:
    """Copy the existing configuration into its local backup history."""
    if not current.config_path.exists():
        return

    now = datetime.strftime(datetime.now(), r"%Y%m%d%H%M%S%f")
    backup_path = (
        current.config_path.parent / "backup" / f"{current.config_path.stem}_{now}_{uuid.uuid4().hex[:8]}.json"
    )
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current.config_path, backup_path)
    logger.info(f"Backup created: {backup_path}")


def save_settings(current: AppSettings) -> None:
    """
    Save the current settings to a JSON file.
    Args:
        settings (AppSettings): The settings object to save.
    """
    partial = current.config_path.with_name(f".{current.config_path.name}.{uuid.uuid4().hex}.partial")
    try:
        serialized = json.dumps(current.prepare_for_save(), indent=4)
        current.config_path.parent.mkdir(parents=True, exist_ok=True)
        backup_config(current)
        partial.write_text(serialized, encoding="utf-8")
        os.replace(partial, current.config_path)
    except (OSError, TypeError, ValueError) as exc:
        logger.exception("Failed to save settings")
        raise SettingsSaveError("Application settings could not be saved.") from exc
    finally:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
    logger.info("Settings saved successfully.")


def load_settings() -> AppSettings:
    """
    Load settings from a JSON file, decrypting sensitive fields.
    Returns:
        AppSettings: The loaded settings object.
    """
    try:
        with open(AppSettings().config_path) as f:
            data = json.load(f)
        settings = AppSettings.from_saved(data)
        logger.info("Settings loaded successfully.")
        return settings
    except FileNotFoundError:
        logger.warning("Settings file not found. Using default settings.")
        return AppSettings()
    except json.JSONDecodeError as e:
        logger.error(f"Config file is corrupted or invalid: {e}")
        logger.warning("Loading default settings.")
        return AppSettings()
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        return AppSettings()


def restore_defaults(save: bool = True) -> AppSettings:
    """
    Reset settings to default values.
    Args:
        save (bool): Whether to save the default settings to file.
    Returns:
        AppSettings: A new settings object with default values.
    """
    defaults = AppSettings()
    if save:
        save_settings(defaults)
    return defaults


def load_or_create_settings() -> AppSettings:
    loaded = load_settings()
    if not loaded.config_path.exists():
        save_settings(loaded)
    return loaded


# Instantiate the settings object so it's available to codebase
settings = load_or_create_settings()

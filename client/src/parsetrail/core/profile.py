"""Process-local desktop profile selection before settings are imported."""

from __future__ import annotations

import os
from pathlib import Path
from platform import system
from urllib.parse import urlsplit, urlunsplit

PROFILE_ENV = "PARSETRAIL_PROFILE"
STAGING_SERVER_URL_ENV = "PARSETRAIL_STAGING_SERVER_URL"
DEFAULT_PROFILE = "default"
STAGING_PROFILE = "staging"
STAGING_ARGUMENT = "--staging"


class ProfileError(ValueError):
    """A requested runtime profile is unsafe or incomplete."""


def active_profile() -> str:
    profile = os.getenv(PROFILE_ENV, DEFAULT_PROFILE).strip().lower() or DEFAULT_PROFILE
    if profile not in {DEFAULT_PROFILE, STAGING_PROFILE}:
        raise ProfileError(f"Unsupported ParseTrail profile: {profile}")
    return profile


def is_staging_profile() -> bool:
    return active_profile() == STAGING_PROFILE


def normalize_staging_server_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise ProfileError("The staging API URL is invalid") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise ProfileError("The staging API URL must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProfileError("The staging API URL must not contain credentials, a query, or a fragment")
    if parsed.path.rstrip("/") != "/api/v1":
        raise ProfileError("The staging API URL must end in /api/v1")
    return urlunsplit((parsed.scheme, parsed.netloc, "/api/v1", "", ""))


def staging_server_url() -> str:
    value = os.getenv(STAGING_SERVER_URL_ENV, "")
    if not value:
        raise ProfileError(f"{STAGING_SERVER_URL_ENV} is required for the staging profile")
    return normalize_staging_server_url(value)


def configure_runtime_profile(argv: list[str]) -> list[str]:
    """Consume ``--staging URL`` before any profile-aware module is imported."""
    occurrences = [index for index, value in enumerate(argv) if value == STAGING_ARGUMENT]
    if not occurrences:
        return argv
    if len(occurrences) != 1:
        raise ProfileError("--staging may be specified only once")
    index = occurrences[0]
    if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
        raise ProfileError("--staging requires the staging API URL")
    server_url = normalize_staging_server_url(argv[index + 1])
    os.environ[PROFILE_ENV] = STAGING_PROFILE
    os.environ[STAGING_SERVER_URL_ENV] = server_url
    return argv[:index] + argv[index + 2 :]


def application_data_dir(
    profile: str | None = None,
    *,
    system_name: str | None = None,
    home: Path | None = None,
) -> Path:
    selected = profile or active_profile()
    if selected not in {DEFAULT_PROFILE, STAGING_PROFILE}:
        raise ProfileError(f"Unsupported ParseTrail profile: {selected}")
    platform_name = system_name or system()
    home_dir = home or Path.home()
    application_name = "ParseTrail-Staging" if selected == STAGING_PROFILE else "ParseTrail"
    if platform_name == "Windows":
        return home_dir / "AppData" / "Roaming" / application_name
    if platform_name == "Darwin":
        return home_dir / "Library" / "Application Support" / application_name
    return home_dir / ".config" / application_name


def credential_service_name() -> str:
    return "ParseTrail-Staging" if is_staging_profile() else "ParseTrail"


def profile_display_name() -> str:
    return "STAGING" if is_staging_profile() else ""


def require_profile_owned_path(path: Path, *, label: str) -> Path:
    """Prevent staging-managed output from escaping its isolated profile."""
    candidate = path.expanduser().resolve()
    if not is_staging_profile():
        return candidate
    root = application_data_dir(STAGING_PROFILE).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProfileError(f"Staging {label} must remain inside {root}") from exc
    return candidate

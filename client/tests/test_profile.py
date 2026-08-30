from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from parsetrail.core.profile import (
    PROFILE_ENV,
    STAGING_SERVER_URL_ENV,
    ProfileError,
    application_data_dir,
    configure_runtime_profile,
    normalize_staging_server_url,
    require_profile_owned_path,
)


def test_staging_argument_is_consumed_before_qt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    monkeypatch.delenv(STAGING_SERVER_URL_ENV, raising=False)

    try:
        remaining = configure_runtime_profile(
            ["parsetrail", "--staging", "https://api.staging.example/api/v1/", "--runtime-smoke-test"]
        )

        assert remaining == ["parsetrail", "--runtime-smoke-test"]
        assert os.environ[PROFILE_ENV] == "staging"
        assert os.environ[STAGING_SERVER_URL_ENV] == "https://api.staging.example/api/v1"
    finally:
        os.environ.pop(PROFILE_ENV, None)
        os.environ.pop(STAGING_SERVER_URL_ENV, None)


@pytest.mark.parametrize(
    "value",
    [
        "http://api.staging.example/api/v1",
        "https://user@api.staging.example/api/v1",
        "https://api.staging.example/",
        "https://api.staging.example/api/v1?target=production",
    ],
)
def test_staging_server_url_fails_closed(value: str) -> None:
    with pytest.raises(ProfileError):
        normalize_staging_server_url(value)


def test_platform_profile_directories_never_overlap(tmp_path: Path) -> None:
    for platform_name in ("Windows", "Darwin", "Linux"):
        production = application_data_dir("default", system_name=platform_name, home=tmp_path)
        staging = application_data_dir("staging", system_name=platform_name, home=tmp_path)
        assert production != staging
        assert staging.name == "ParseTrail-Staging"


def test_staging_managed_output_cannot_escape_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROFILE_ENV, "staging")
    profile_root = application_data_dir("staging")
    assert require_profile_owned_path(profile_root / "downloads" / "backup.dbb", label="backup")
    with pytest.raises(ProfileError, match="backup"):
        require_profile_owned_path(tmp_path / "production" / "backup.dbb", label="backup")


def test_staging_subprocess_isolates_files_settings_and_credentials(tmp_path: Path) -> None:
    script = """
import json
from pathlib import Path
from pydantic import ValidationError
from parsetrail.core.credentials import SERVICE_NAME
from parsetrail.core.settings import APPDATA_DIR, AppSettings

current = AppSettings()
outside = Path.home() / 'Documents' / 'ParseTrail' / 'parsetrail.db'
try:
    current.db_path = outside
except ValidationError:
    assignment_blocked = True
else:
    assignment_blocked = False
print(json.dumps({
    'appdata': str(APPDATA_DIR),
    'config': str(current.config_path),
    'database': str(current.db_path),
    'import_dir': str(current.import_dir),
    'plugins': str(current.plugin_dir),
    'logs': str(current.log_file),
    'reports': str(current.report_dir),
    'downloads': str(current.download_dir),
    'server_url': str(current.server_url).rstrip('/'),
    'credential_service': SERVICE_NAME,
    'assignment_blocked': assignment_blocked,
}))
"""
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path),
            "USERPROFILE": str(tmp_path),
            PROFILE_ENV: "staging",
            STAGING_SERVER_URL_ENV: "https://api.staging.example/api/v1",
            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    staging_root = str(Path(result["appdata"]).resolve())

    assert Path(staging_root).name == "ParseTrail-Staging"
    for name in ("config", "database", "import_dir", "plugins", "logs", "reports", "downloads"):
        assert str(Path(result[name]).resolve()).startswith(staging_root)
    assert result["server_url"] == "https://api.staging.example/api/v1"
    assert result["credential_service"] == "ParseTrail-Staging"
    assert result["assignment_blocked"] is True
    assert not (tmp_path / "AppData" / "Roaming" / "ParseTrail").exists()

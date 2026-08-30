from __future__ import annotations

import json

import pytest
from parsetrail.core import settings as settings_module
from parsetrail.core.settings import AppSettings, SettingsSaveError, save_settings


def test_save_settings_writes_serialized_configuration(tmp_path) -> None:
    current = AppSettings(email="user@example.test")
    current._config_path = tmp_path / "config.json"

    save_settings(current)

    saved = json.loads(current.config_path.read_text())
    assert saved["email"] == "user@example.test"
    assert "access_token" not in saved


def test_save_settings_preserves_io_error_as_cause(monkeypatch, tmp_path) -> None:
    current = AppSettings()
    current._config_path = tmp_path / "config.json"
    original = OSError("disk unavailable")

    def fail_backup(_current: AppSettings) -> None:
        raise original

    monkeypatch.setattr(settings_module, "backup_config", fail_backup)

    with pytest.raises(SettingsSaveError) as exc_info:
        save_settings(current)

    assert exc_info.value.__cause__ is original
    assert "disk unavailable" not in str(exc_info.value)

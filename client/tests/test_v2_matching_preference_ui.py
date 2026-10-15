"""The global account matching preference is visible and saved safely."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from parsetrail.core.settings import AppSettings, SettingsSaveError  # noqa: E402
from parsetrail.gui import preferences as preferences_module  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox  # noqa: E402


def test_preferences_checkbox_persists_when_saved(monkeypatch, tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    current = AppSettings()
    current._config_path = tmp_path / "config.json"
    monkeypatch.setattr(preferences_module, "settings", current)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    dialog = preferences_module.PreferencesDialog()
    checkbox = dialog.fields["allow_abbreviated_account_matching"]
    assert isinstance(checkbox, QCheckBox) and not checkbox.isChecked()
    assert "same institution" in checkbox.toolTip()
    checkbox.setChecked(True)
    dialog.save_preferences()
    assert current.allow_abbreviated_account_matching
    assert json.loads(current.config_path.read_text(encoding="utf-8"))["allow_abbreviated_account_matching"]
    assert app is not None


def test_failed_save_does_not_enable_automatic_matching(monkeypatch, tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    current = AppSettings()
    current._config_path = tmp_path / "config.json"
    monkeypatch.setattr(preferences_module, "settings", current)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args: None)

    def fail_save(_settings):
        raise SettingsSaveError("injected failure")

    monkeypatch.setattr(preferences_module, "save_settings", fail_save)
    dialog = preferences_module.PreferencesDialog()
    dialog.fields["allow_abbreviated_account_matching"].setChecked(True)
    dialog.save_preferences()
    assert not current.allow_abbreviated_account_matching
    assert not current.config_path.exists()
    assert app is not None

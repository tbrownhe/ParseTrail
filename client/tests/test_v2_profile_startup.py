"""Startup selects only explicit fresh profiles and preserves failed choices."""

from __future__ import annotations

import sqlite3

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_profile_startup import (
    V2ProfileStartupDialog,
    choose_new_workspace,
    choose_open_workspace,
    choose_restored_workspace,
)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def warnings(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: messages.append(message))
    return messages


@pytest.mark.usefixtures("app")
def test_new_profile_cancel_and_existing_destination_leave_files_unchanged(tmp_path, warnings, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    catalog, prefs = tmp_path / "catalog", tmp_path / "prefs.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: ("", ""))
    assert choose_new_workspace(None, tmp_path, catalog, trusted_keys={}, preferences_path=prefs) is None
    assert not catalog.exists() and not prefs.exists()
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"Keep existing bytes")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(existing), ""))
    assert choose_new_workspace(None, tmp_path, catalog, trusted_keys={}, preferences_path=prefs) is None
    assert existing.read_bytes() == b"Keep existing bytes"
    assert "never overwritten" in warnings[-1]


def test_startup_create_and_open_are_explicit_without_catalog_or_preferences_writes(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QDialog, QFileDialog

    selected = tmp_path / "new-profile"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(selected), ""))
    catalog, prefs = tmp_path / "catalog", tmp_path / "prefs.json"
    dialog = V2ProfileStartupDialog(catalog, trusted_keys={}, preferences_path=prefs)
    try:
        assert dialog.workspace is None
        dialog.create_button.click()
        assert dialog.result() == QDialog.Accepted
        profile = selected.with_suffix(".db")
        assert dialog.workspace.profile_path == profile.resolve()
    finally:
        dialog.close()
        app.processEvents()
    before = profile.read_bytes()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(profile), ""))
    opened = choose_open_workspace(None, tmp_path, catalog, trusted_keys={}, preferences_path=prefs)
    assert opened.profile_path == profile.resolve()
    assert profile.read_bytes() == before
    assert not catalog.exists() and not prefs.exists()


def test_legacy_choice_is_refused_read_only_and_dialog_can_retry(tmp_path, app, warnings, monkeypatch):
    from PySide6.QtWidgets import QDialog, QFileDialog

    legacy, fresh = tmp_path / "legacy.db", tmp_path / "fresh.db"
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE Sentinel(value TEXT)")
        connection.execute("INSERT INTO Sentinel VALUES ('untouched')")
    before = legacy.read_bytes()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(legacy), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(fresh), ""))
    dialog = V2ProfileStartupDialog(tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    try:
        dialog.open_button.click()
        assert dialog.workspace is None and dialog.result() != QDialog.Accepted
        assert "1.x files are kept unchanged" in warnings[-1]
        assert legacy.read_bytes() == before
        dialog.create_button.click()
        assert dialog.workspace.profile_path == fresh.resolve()
        assert legacy.read_bytes() == before
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.usefixtures("app")
def test_restore_startup_preserves_backup_and_authored_data(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    source, backup, restored = (tmp_path / name for name in ("source.db", "backup.dbb", "restored.db"))
    with V2ProfileStore.create(source) as store:
        store.add_category_account("expense:food", "Food", "expense")
    V2ProfileStore.snapshot_to(source, backup)
    source_before, backup_before = source.read_bytes(), backup.read_bytes()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(backup), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(restored), ""))
    selected = choose_restored_workspace(
        None, tmp_path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json"
    )
    assert selected.profile_path == restored.resolve()
    with V2ProfileStore.open(restored, read_only=True) as store:
        assert store.category_accounts()[0].name == "Food"
    assert source.read_bytes() == source_before and backup.read_bytes() == backup_before


def test_restore_destination_cancel_or_conflict_never_switches(tmp_path, app, warnings, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    backup = tmp_path / "backup.dbb"
    with V2ProfileStore.create(backup):
        pass
    before = backup.read_bytes()
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"Do not replace")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(backup), ""))
    for destination in ("", str(existing)):
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *_args, _target=destination, **_kwargs: (_target, "")
        )
        dialog = V2ProfileStartupDialog(tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
        try:
            dialog.restore_button.click()
            assert dialog.workspace is None
        finally:
            dialog.close()
            app.processEvents()
    assert existing.read_bytes() == b"Do not replace" and backup.read_bytes() == before
    assert "never overwritten" in warnings[-1]


@pytest.mark.usefixtures("app")
def test_explicit_entry_cancel_does_not_create_profile_catalog_or_preferences(tmp_path, monkeypatch):
    from parsetrail.main import run_v2_workspace
    from PySide6.QtWidgets import QDialog

    catalog, prefs = tmp_path / "catalog", tmp_path / "prefs.json"
    monkeypatch.setattr(V2ProfileStartupDialog, "exec", lambda _self: QDialog.Rejected)
    assert run_v2_workspace(["--v2", "--catalog-cache", str(catalog), "--preferences", str(prefs)]) == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.usefixtures("app")
def test_explicit_entry_chooser_creates_selected_profile_then_opens_window(tmp_path, monkeypatch):
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from parsetrail.main import run_v2_workspace
    from PySide6.QtWidgets import QApplication, QFileDialog

    profile = tmp_path / "selected.db"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(profile), ""))

    def choose(dialog):
        dialog.create_button.click()
        return dialog.result()

    monkeypatch.setattr(V2ProfileStartupDialog, "exec", choose)
    monkeypatch.setattr(QApplication, "exec", lambda *_args: 37)
    shown = []
    monkeypatch.setattr(V2WorkspaceWindow, "show", lambda window: shown.append(window.workspace.profile_path))
    assert (
        run_v2_workspace(
            ["--v2", "--catalog-cache", str(tmp_path / "catalog"), "--preferences", str(tmp_path / "prefs.json")]
        )
        == 37
    )
    assert shown == [profile.resolve()]


@pytest.mark.usefixtures("app")
@pytest.mark.parametrize("create", [False, True])
def test_existing_explicit_cli_profile_paths_do_not_show_startup(tmp_path, monkeypatch, create):
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from parsetrail.main import run_v2_workspace
    from PySide6.QtWidgets import QApplication

    profile = tmp_path / "explicit.db"
    if not create:
        with V2ProfileStore.create(profile):
            pass

    def unexpected_startup(_self):
        raise AssertionError("Explicit profile automation must not open the startup chooser")

    monkeypatch.setattr(V2ProfileStartupDialog, "exec", unexpected_startup)
    monkeypatch.setattr(QApplication, "exec", lambda *_args: 19)
    shown = []
    monkeypatch.setattr(V2WorkspaceWindow, "show", lambda window: shown.append(window.workspace.profile_path))
    args = [
        "--v2",
        "--profile",
        str(profile),
        "--catalog-cache",
        str(tmp_path / "catalog"),
        "--preferences",
        str(tmp_path / "prefs.json"),
    ]
    if create:
        args.append("--create-profile")
    assert run_v2_workspace(args) == 19
    assert shown == [profile.resolve()]


def test_new_profile_menu_preserves_old_profile_and_is_disabled_during_import(tmp_path, app, monkeypatch):
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QFileDialog

    current, new = tmp_path / "current.db", tmp_path / "new.db"
    workspace = V2Workspace.create(
        current, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json"
    )
    with V2ProfileStore.open(current) as store:
        store.add_category_account("expense:food", "Food", "expense")
    before = current.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(new), ""))
    window = V2WorkspaceWindow(workspace)
    try:
        window.import_worker = object()
        window.refresh()
        assert not window.new_profile_action.isEnabled()
        window.import_worker = None
        window.refresh()
        window.new_profile_action.trigger()
        assert window.workspace.profile_path == new.resolve()
        assert str(new.resolve()) == window.profile_label.text()
        with V2ProfileStore.open(new, read_only=True) as store:
            assert store.category_accounts() == ()
        assert current.read_bytes() == before
    finally:
        window.import_worker = None
        window.close()
        app.processEvents()


@pytest.mark.usefixtures("app")
@pytest.mark.parametrize("mode", ["new", "open", "restore"])
def test_invalid_preferences_refuse_before_creating_or_switching_profiles(tmp_path, warnings, monkeypatch, mode):
    from PySide6.QtWidgets import QFileDialog

    profile, output, prefs = (tmp_path / name for name in ("profile.db", "new.db", "prefs.json"))
    with V2ProfileStore.create(profile):
        pass
    prefs.write_bytes(b"invalid preferences; preserve these bytes")
    before = profile.read_bytes()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(profile), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(output), ""))
    chooser = {"new": choose_new_workspace, "open": choose_open_workspace, "restore": choose_restored_workspace}[mode]
    assert chooser(None, tmp_path, tmp_path / "catalog", trusted_keys={}, preferences_path=prefs) is None
    assert not output.exists()
    assert profile.read_bytes() == before
    assert prefs.read_bytes() == b"invalid preferences; preserve these bytes"
    assert "preferences file could not be read" in warnings[-1]


@pytest.mark.usefixtures("app")
def test_invalid_catalog_new_choice_keeps_current_workspace_and_does_not_create_target(tmp_path, warnings, monkeypatch):
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QFileDialog

    current, target, catalog = tmp_path / "current.db", tmp_path / "new.db", tmp_path / "catalog"
    workspace = V2Workspace.create(current, catalog, trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    window = V2WorkspaceWindow(workspace)
    before = current.read_bytes()
    try:
        catalog.mkdir()
        (catalog / "current.json").write_bytes(b"invalid catalog pointer")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(target), ""))
        window.new_profile_action.trigger()
        assert window.workspace is workspace
        assert window.profile_label.text() == str(current.resolve())
        assert not target.exists() and current.read_bytes() == before
        assert "catalog_pointer" in warnings[-1]
    finally:
        window.close()


def test_failed_refresh_after_staging_selection_rolls_back_workspace_and_visible_source(
    tmp_path, app, warnings, monkeypatch
):
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    from .test_v2_workspace_window import SOURCE, _workspace

    workspace = _workspace(tmp_path)
    original = tmp_path / "source.csv"
    original.write_bytes(SOURCE)
    source_id = workspace.import_file(original).source_sha256
    target = V2Workspace.create(
        tmp_path / "new.db",
        workspace.catalog_cache.root,
        trusted_keys=workspace.catalog_cache.trusted_keys,
        preferences_path=workspace.preferences_path,
    )
    before = workspace.profile_path.read_bytes()
    window = V2WorkspaceWindow(workspace)
    original_refresh = window.refresh

    def fail_selected_refresh(*args, **kwargs):
        original_refresh(*args, **kwargs)
        if window.workspace is target:
            raise ValueError("Synthetic concurrent refresh failure")

    monkeypatch.setattr(window, "refresh", fail_selected_refresh)
    try:
        window._select_workspace(target)
        assert window.workspace is workspace
        assert window.profile_label.text() == str(workspace.profile_path)
        assert window._selected_source() == source_id
        assert window.sources.count() == 1
        assert workspace.profile_path.read_bytes() == before
        assert "Synthetic concurrent refresh failure" in warnings[-1]
    finally:
        window.close()
        app.processEvents()

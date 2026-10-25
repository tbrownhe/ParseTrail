"""Embedded originals remain recoverable without import files or a catalog."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_recovery import recover_source_original
from parsetrail.core.v2_workspace import V2Workspace

from .test_v2_workspace import SOURCE, _workspace


def _import_then_remove(tmp_path: Path):
    workspace = _workspace(tmp_path)
    original = tmp_path / "original.csv"
    original.write_bytes(SOURCE)
    imported = workspace.import_file(original)
    original.unlink()
    return workspace, imported.source_sha256


def test_recovery_after_original_disappears_is_exact_and_reimport_is_idempotent(tmp_path: Path):
    workspace, source_id = _import_then_remove(tmp_path)
    before = workspace.profile_path.read_bytes()
    recovered = tmp_path / "recovered.csv"
    assert workspace.recover_source_original(source_id, recovered) == recovered.resolve()
    assert recovered.read_bytes() == SOURCE
    assert hashlib.sha256(recovered.read_bytes()).hexdigest() == source_id
    assert workspace.profile_path.read_bytes() == before
    assert workspace.import_file(recovered).status == "already_imported"
    assert workspace.source_ids() == (source_id,)


def test_restored_profile_recovers_without_catalog_or_original(tmp_path: Path):
    workspace, source_id = _import_then_remove(tmp_path)
    backup, restored = tmp_path / "backup.dbb", tmp_path / "restored.db"
    V2ProfileStore.snapshot_to(workspace.profile_path, backup)
    V2ProfileStore.snapshot_to(backup, restored)
    selected = V2Workspace.open(
        restored, tmp_path / "empty-catalog", trusted_keys={}, preferences_path=tmp_path / "new-preferences.json"
    )
    original_before, restored_before = workspace.profile_path.read_bytes(), restored.read_bytes()
    assert selected.catalog_cache.load_current() is None
    recovered = selected.recover_source_original(source_id, tmp_path / "from-backup.csv")
    assert recovered.read_bytes() == SOURCE
    assert workspace.profile_path.read_bytes() == original_before
    assert restored.read_bytes() == restored_before


def test_destination_refusal_and_publication_failure_preserve_profile_and_existing_files(tmp_path: Path, monkeypatch):
    workspace, source_id = _import_then_remove(tmp_path)
    before = workspace.profile_path.read_bytes()
    existing = tmp_path / "existing.csv"
    existing.write_bytes(b"Keep this original")
    with pytest.raises(ProfileFormatError, match="source_destination_exists"):
        workspace.recover_source_original(source_id, existing)
    with pytest.raises(ProfileFormatError, match="source_destination_parent_missing"):
        workspace.recover_source_original(source_id, tmp_path / "missing" / "new.csv")
    destination = tmp_path / "failed.csv"

    def fail_link(_source, _destination):
        raise OSError("Synthetic publication failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="Synthetic publication failure"):
        workspace.recover_source_original(source_id, destination)
    assert existing.read_bytes() == b"Keep this original"
    assert not destination.exists() and not tuple(tmp_path.glob(".*.partial"))
    assert workspace.profile_path.read_bytes() == before


def test_racing_destination_is_never_overwritten(tmp_path: Path, monkeypatch):
    workspace, source_id = _import_then_remove(tmp_path)
    destination = tmp_path / "race.csv"
    before = workspace.profile_path.read_bytes()
    original_link = os.link

    def competing_link(source, target):
        Path(target).write_bytes(b"Another writer's file")
        return original_link(source, target)

    monkeypatch.setattr(os, "link", competing_link)
    with pytest.raises(ProfileFormatError, match="source_destination_exists"):
        workspace.recover_source_original(source_id, destination)
    assert destination.read_bytes() == b"Another writer's file"
    assert not tuple(tmp_path.glob(".*.partial"))
    assert workspace.profile_path.read_bytes() == before


def test_invalid_saved_source_never_publishes_output(tmp_path: Path):
    workspace, _source_id = _import_then_remove(tmp_path)
    destination = tmp_path / "missing.csv"
    before = workspace.profile_path.read_bytes()
    with pytest.raises(ProfileFormatError):
        recover_source_original(workspace.profile_path, "0" * 64, destination)
    assert not destination.exists() and not tuple(tmp_path.glob(".*.partial"))
    assert workspace.profile_path.read_bytes() == before


def test_pdf_original_is_recovered_verbatim(tmp_path: Path):
    from parsetrail.core.v2_table_bank_source_output import from_anchored_bank

    from devtools.parser_engine_pilot.test_table_bank_source_output import DEFINITION
    from devtools.parser_engine_pilot.test_table_bank_source_output import SOURCE as PDF_SOURCE
    from devtools.parser_engine_pilot.test_table_bank_source_output import evidence as channels

    profile = tmp_path / "pdf.db"
    evidence = from_anchored_bank(DEFINITION, *channels())
    with V2ProfileStore.create(profile) as store:
        store.import_source(PDF_SOURCE, DEFINITION, evidence, suffix=".pdf")
    before = profile.read_bytes()
    recovered = recover_source_original(profile, evidence.source_sha256, tmp_path / "original.pdf")
    assert recovered.read_bytes() == PDF_SOURCE
    assert profile.read_bytes() == before


def test_corrupt_retained_bytes_refuse_export_without_creating_partial(tmp_path: Path):
    workspace, source_id = _import_then_remove(tmp_path)
    with sqlite3.connect(workspace.profile_path) as connection:
        trigger = connection.execute("SELECT sql FROM sqlite_master WHERE name='immutable_Sources_update'").fetchone()[
            0
        ]
        connection.execute("DROP TRIGGER immutable_Sources_update")
        connection.execute("UPDATE Sources SET content=? WHERE sha256=?", (b"corrupt", source_id))
        connection.execute(trigger)
    before = workspace.profile_path.read_bytes()
    destination = tmp_path / "refused.csv"
    with pytest.raises(ProfileFormatError, match="saved_snapshot_integrity"):
        workspace.recover_source_original(source_id, destination)
    assert not destination.exists() and not tuple(tmp_path.glob(".*.partial"))
    assert workspace.profile_path.read_bytes() == before


def test_failed_durable_write_cleans_up_without_publishing(tmp_path: Path, monkeypatch):
    workspace, source_id = _import_then_remove(tmp_path)
    before = workspace.profile_path.read_bytes()
    destination = tmp_path / "refused.csv"

    def fail_sync(_descriptor):
        raise OSError("Synthetic flush failure")

    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(OSError, match="Synthetic flush failure"):
        workspace.recover_source_original(source_id, destination)
    assert not destination.exists() and not tuple(tmp_path.glob(".*.partial"))
    assert workspace.profile_path.read_bytes() == before


def test_workspace_recovery_action_cancel_save_and_failure(tmp_path: Path, monkeypatch):
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    workspace, source_id = _import_then_remove(tmp_path)
    before = workspace.profile_path.read_bytes()
    destination = tmp_path / "selected.csv"
    notices, warnings = [], []
    monkeypatch.setattr(
        "parsetrail.gui.v2_workspace_window.show_path_notice",
        lambda _parent, title, summary, path, detail: notices.append((title, summary, path, detail)),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args[1:]))
    dialog = V2WorkspaceWindow(workspace)
    try:
        assert dialog.recover_source_action.isEnabled()
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: ("", ""))
        dialog.recover_source_action.trigger()
        assert notices == [] and warnings == [] and not destination.exists()
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(destination), ""))
        dialog.recover_source_action.trigger()
        assert destination.read_bytes() == SOURCE
        assert notices[0][2] == destination.resolve()
        assert "not encrypted" in notices[0][3]
        dialog.recover_source_action.trigger()
        assert len(notices) == 1 and len(warnings) == 1
        assert "source_destination_exists" in warnings[0][1]
        assert dialog._selected_source() == source_id
    finally:
        dialog.close()
        app.processEvents()
    assert workspace.profile_path.read_bytes() == before


def test_empty_workspace_has_no_source_to_recover(tmp_path: Path, monkeypatch):
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    workspace = _workspace(tmp_path)
    dialog = V2WorkspaceWindow(workspace)
    try:
        assert not dialog.recover_source_action.isEnabled()
    finally:
        dialog.close()
        app.processEvents()

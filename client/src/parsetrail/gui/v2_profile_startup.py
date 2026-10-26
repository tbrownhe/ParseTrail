"""Explicit profile selection without opening or migrating a 1.x database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace


def _failure(parent, error: Exception) -> None:
    messages = {
        "unsupported_profile_format": "Choose a current 2.0 profile. Earlier pilot and 1.x files are kept unchanged.",
        "profile_destination_exists": "Choose a new file name. Existing profiles are never overwritten.",
        "profile_destination_parent_missing": "Choose an existing folder for the new profile.",
        "v2_preferences_shape": "The separate preferences file could not be read. Repair it before opening a workspace; your profiles have not changed.",
    }
    message = (
        "Choose a new file name. Existing profiles are never overwritten."
        if isinstance(error, FileExistsError)
        else messages.get(str(error), str(error))
    )
    QMessageBox.warning(parent, "Profile was not selected", message)


def _profile_destination(parent, title: str, proposed: Path) -> Path | None:
    selected, _filter = QFileDialog.getSaveFileName(
        parent,
        title,
        str(proposed),
        "ParseTrail profiles (*.db);;All files (*)",
        options=QFileDialog.DontConfirmOverwrite,
    )
    if not selected:
        return None
    destination = Path(selected)
    if not destination.suffix:
        destination = destination.with_suffix(".db")
    if destination.suffix.lower() != ".db":
        QMessageBox.warning(parent, "Profile was not selected", "Choose a .db name for the new profile.")
        return None
    return destination


def _verify_configuration(profile, catalog, trusted_keys, preferences_path) -> None:
    V2Workspace(
        profile, catalog, trusted_keys=trusted_keys, preferences_path=preferences_path
    ).verify_local_configuration()


def choose_new_workspace(parent, directory: Path, catalog: Path, *, trusted_keys=None, preferences_path=None):
    destination = _profile_destination(parent, "Create a fresh 2.0 profile", directory / "ParseTrail-2.0.db")
    if destination is None:
        return None
    try:
        _verify_configuration(destination, catalog, trusted_keys, preferences_path)
        return V2Workspace.create(destination, catalog, trusted_keys=trusted_keys, preferences_path=preferences_path)
    except (ProfileFormatError, sqlite3.Error, OSError, ValueError) as exc:
        _failure(parent, exc)
        return None


def choose_open_workspace(parent, directory: Path, catalog: Path, *, trusted_keys=None, preferences_path=None):
    selected, _filter = QFileDialog.getOpenFileName(
        parent,
        "Open a 2.0 profile",
        str(directory),
        "ParseTrail profiles (*.db);;All files (*)",
        options=QFileDialog.ReadOnly,
    )
    if not selected:
        return None
    profile = Path(selected)
    if profile.suffix.lower() != ".db":
        QMessageBox.warning(parent, "Profile was not selected", "Choose a .db profile, or use Restore backup.")
        return None
    try:
        _verify_configuration(profile, catalog, trusted_keys, preferences_path)
        return V2Workspace.open(profile, catalog, trusted_keys=trusted_keys, preferences_path=preferences_path)
    except (ProfileFormatError, sqlite3.Error, OSError, ValueError) as exc:
        _failure(parent, exc)
        return None


def choose_restored_workspace(parent, directory: Path, catalog: Path, *, trusted_keys=None, preferences_path=None):
    selected, _filter = QFileDialog.getOpenFileName(
        parent,
        "Restore a 2.0 backup",
        str(directory),
        "ParseTrail backups (*.dbb *.db);;All files (*)",
        options=QFileDialog.ReadOnly,
    )
    if not selected:
        return None
    backup = Path(selected)
    destination = _profile_destination(
        parent, "Restore backup as a new profile", backup.with_name(backup.stem + "-restored.db")
    )
    if destination is None:
        return None
    try:
        _verify_configuration(destination, catalog, trusted_keys, preferences_path)
        restored = V2ProfileStore.snapshot_to(backup, destination)
        return V2Workspace.open(restored, catalog, trusted_keys=trusted_keys, preferences_path=preferences_path)
    except (ProfileFormatError, sqlite3.Error, OSError, ValueError) as exc:
        _failure(parent, exc)
        return None


class V2ProfileStartupDialog(QDialog):
    def __init__(self, catalog: Path, *, trusted_keys=None, preferences_path=None, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.trusted_keys = trusted_keys
        self.preferences_path = preferences_path
        self.workspace: V2Workspace | None = None
        self.setWindowTitle("Choose your 2.0 workspace")
        self.resize(590, 340)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Create a fresh local profile, open an existing 2.0 profile, or restore a verified backup to a new file. "
            "Your 1.x application and history remain independent; no migration is performed. "
            "Nothing opens automatically. Cancelling leaves your files unchanged."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        for attribute, text, chooser in (
            ("create_button", "Create a fresh profile…", choose_new_workspace),
            ("open_button", "Open a 2.0 profile…", choose_open_workspace),
            ("restore_button", "Restore backup as a new profile…", choose_restored_workspace),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, choose=chooser: self._choose(choose))
            setattr(self, attribute, button)
            layout.addWidget(button)
        privacy = QLabel(
            "Profiles and backups contain financial data and are not encrypted by ParseTrail. "
            "The signed parser catalog and global preferences are stored separately. "
            "After opening a profile, install a signed catalog to enable imports."
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose(self, chooser) -> None:
        selected = chooser(
            self,
            Path.home() / "Documents",
            self.catalog,
            trusted_keys=self.trusted_keys,
            preferences_path=self.preferences_path,
        )
        if selected is not None:
            self.workspace = selected
            self.accept()

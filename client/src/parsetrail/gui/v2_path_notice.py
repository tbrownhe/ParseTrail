"""Show a copyable filesystem path without wrapping it inside prose."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout


def show_data_locations(parent, profile: Path, catalog: Path, preferences: Path) -> None:
    """Show the three separate local stores with copyable, unwrapped paths."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("2.0 data locations and privacy")
    layout = QVBoxLayout(dialog)
    locations = QFormLayout()
    for label, path in (
        ("Active financial profile", profile),
        ("Signed catalog cache", catalog),
        ("Global preferences", preferences),
    ):
        field = QLineEdit(str(path))
        field.setReadOnly(True)
        field.setCursorPosition(0)
        field.setMinimumWidth(480)
        locations.addRow(label, field)
    layout.addLayout(locations)
    details = QLabel(
        "The profile contains copies of imported source bytes, extracted evidence, accounts, categories, "
        "budgets and reviewed journal entries. ParseTrail does not encrypt the profile or its backups. "
        "A profile backup includes those stored source bytes, but not the separate signed catalog cache "
        "or global preferences. Original files remain at their chosen locations."
    )
    details.setWordWrap(True)
    layout.addWidget(details)
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    buttons.rejected.connect(dialog.accept)
    layout.addWidget(buttons)
    dialog.exec()


def show_path_notice(parent, title: str, summary: str, path: Path, detail: str) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    summary_label = QLabel(summary)
    summary_label.setWordWrap(True)
    layout.addWidget(summary_label)
    path_field = QLineEdit(str(path))
    path_field.setReadOnly(True)
    path_field.setCursorPosition(0)
    path_field.setMinimumWidth(480)
    layout.addWidget(path_field)
    detail_label = QLabel(detail)
    detail_label.setWordWrap(True)
    layout.addWidget(detail_label)
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    buttons.rejected.connect(dialog.accept)
    layout.addWidget(buttons)
    dialog.exec()

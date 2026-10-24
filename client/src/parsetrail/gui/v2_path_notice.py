"""Show a copyable filesystem path without wrapping it inside prose."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout


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

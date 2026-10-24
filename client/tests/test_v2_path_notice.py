"""Filesystem paths remain intact and selectable in 2.0 notices."""

from __future__ import annotations

import os
from pathlib import Path

from parsetrail.gui.v2_path_notice import show_path_notice
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit


def test_saved_path_is_in_single_line_read_only_field(monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    fields = []

    def inspect(dialog):
        fields.extend((field.text(), field.isReadOnly()) for field in dialog.findChildren(QLineEdit))
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", inspect)
    path = Path(r"C:\asdffsd\reviewed.xlsx")
    show_path_notice(None, "Saved", "Workbook saved", path, "Financial data")
    assert len(fields) == 1
    assert fields == [(str(path), True)]
    app.processEvents()

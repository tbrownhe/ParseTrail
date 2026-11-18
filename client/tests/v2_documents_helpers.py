"""Assertions against the Documents table's public Qt model and source identity."""

from PySide6.QtCore import Qt


def document_text(window, row=0):
    model = window.sources.model()
    return " ".join(str(model.index(row, column).data() or "") for column in range(model.columnCount()))


def document_details(window, row=0):
    return window.sources.model().index(row, 0).data(Qt.ToolTipRole)

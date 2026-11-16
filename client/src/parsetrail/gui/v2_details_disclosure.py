"""Compact, keyboard-accessible disclosure for supporting review details."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class DetailsDisclosure(QWidget):
    toggled = Signal(bool)

    def __init__(self, content, parent=None, *, subject="details"):
        super().__init__(parent)
        self.subject = subject
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.button = QToolButton(self)
        self.button.setAutoRaise(True)
        self.button.setCheckable(True)
        self.button.setAccessibleName(f"Show {subject}")
        self.content = content
        content.setParent(self)
        layout.addWidget(self.button)
        layout.addWidget(content)
        self.button.toggled.connect(self._expanded)
        self._expanded(False)

    def _expanded(self, expanded):
        text = "Hide details" if expanded else "Show details"
        self.button.setText(text)
        self.button.setAccessibleName(f"{'Hide' if expanded else 'Show'} {self.subject}")
        self.button.setAccessibleDescription("Expanded" if expanded else "Collapsed")
        self.content.setVisible(expanded)
        self.toggled.emit(expanded)

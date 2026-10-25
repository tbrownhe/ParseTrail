"""Background batch import with a per-file, copyable result review."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from parsetrail.core.v2_workspace import BatchImportResult, V2Workspace


class V2BatchImportWorker(QThread):
    progressed = Signal(int, str)

    def __init__(self, workspace: V2Workspace, paths: tuple[Path, ...], parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.paths = paths
        self.cancel_event = Event()
        self.result: BatchImportResult | None = None
        self.error: Exception | None = None

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            self.result = self.workspace.import_files(
                self.paths,
                cancelled=self.cancel_event.is_set,
                progress=lambda count, item: self.progressed.emit(count, item.path.name),
            )
        except Exception as exc:
            self.error = exc


class V2BatchImportReport(QDialog):
    """Review which selected files were saved, reused, refused or untouched."""

    def __init__(self, result: BatchImportResult, parent=None):
        super().__init__(parent)
        self.setWindowTitle("2.0 batch import results")
        self.resize(780, 480)
        layout = QVBoxLayout(self)
        counts = {
            status: sum(item.status == status for item in result.files)
            for status in ("imported", "already_imported", "failed", "cancelled", "not_attempted")
        }
        summary = QLabel(
            f"{counts['imported']} imported · {counts['already_imported']} already saved · "
            f"{counts['failed']} failed · {counts['cancelled']} cancelled · "
            f"{counts['not_attempted']} not attempted. "
            "Completed files remain pending review; cancellation keeps those imports."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.files = QListWidget()
        for item in result.files:
            label = f"{item.path.name} — {item.status.replace('_', ' ')}"
            if item.error_code:
                label += f": {item.error_code}"
            row = QListWidgetItem(label)
            row.setData(Qt.UserRole, str(item.path))
            row.setToolTip(str(item.path))
            self.files.addItem(row)
        layout.addWidget(self.files)
        layout.addWidget(QLabel("Selected file:"))
        self.selected_path = QLineEdit()
        self.selected_path.setReadOnly(True)
        layout.addWidget(self.selected_path)
        self.files.currentItemChanged.connect(self._selected)
        if self.files.count():
            self.files.setCurrentRow(0)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _selected(self, current: QListWidgetItem | None) -> None:
        self.selected_path.setText(current.data(Qt.UserRole) if current is not None else "")
        self.selected_path.setCursorPosition(0)

"""Open a verified local original asynchronously in the desktop's default app."""

from __future__ import annotations

import atexit
import threading
import time
import weakref
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QMessageBox

from parsetrail.core.v2_original_document import OriginalDocumentError, OriginalDocumentSession, read_saved_original
from parsetrail.core.v2_profile_store import SavedImport

_ORIGINAL_READERS: set[QThread] = set()
_ORIGINAL_OPENERS: set[OriginalDocumentOpen] = set()
_SESSION: OriginalDocumentSession | None = None
_SESSION_LOCK = threading.Lock()
_EXITING = False


def _session() -> OriginalDocumentSession:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            _SESSION = OriginalDocumentSession()
        return _SESSION


def _finish_original_readers() -> None:
    global _EXITING
    _EXITING = True
    for opener in tuple(_ORIGINAL_OPENERS):
        opener.cancel()
    for reader in tuple(_ORIGINAL_READERS):
        reader.requestInterruption()
        while reader.isRunning():
            reader.wait(10)
            time.sleep(0.001)
        reader.wait()
        _ORIGINAL_READERS.discard(reader)
    if _SESSION is not None:
        _SESSION.close()


atexit.register(_finish_original_readers)


class _OriginalReader(QThread):
    def __init__(self, *, profile: Path | None, source_sha256: str, saved: SavedImport | None):
        super().__init__()
        self.profile, self.source_sha256, self.saved = profile, source_sha256, saved
        self.path: Path | None = None
        self.session: OriginalDocumentSession | None = None
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            saved = self.saved or read_saved_original(
                self.profile, self.source_sha256, cancelled=self.isInterruptionRequested
            )
            if self.isInterruptionRequested():
                return
            self.session = _session()
            self.path = self.session.materialize(saved)
            if self.isInterruptionRequested():
                self.session.discard(self.path)
                self.path = None
        except Exception as exc:
            self.error = exc


class OriginalDocumentOpen(QObject):
    """Retained operation for one captured source, cancelled when its parent dies."""

    finished = Signal(bool)
    status_changed = Signal(str)

    def __init__(self, *, profile=None, source_sha256: str, saved=None, parent=None):
        # No QObject parent: cancellation must not destroy a running native worker.
        super().__init__()
        self._parent = weakref.ref(parent) if parent is not None else lambda: None
        self.pending = True
        self.status = "Preparing original document…"
        self.path: Path | None = None
        self.error: Exception | None = None
        self._cancelled = False
        self._reader = _OriginalReader(profile=profile, source_sha256=source_sha256, saved=saved)
        if parent is not None:
            parent.destroyed.connect(self.cancel)
            parent.installEventFilter(self)
            if isinstance(parent, QDialog):
                parent.finished.connect(self.cancel)
        app = QCoreApplication.instance()
        if app is not None and not app.property("parsetrailOriginalExitHook"):
            app.setProperty("parsetrailOriginalExitHook", True)
            app.aboutToQuit.connect(_finish_original_readers)
        _ORIGINAL_OPENERS.add(self)
        _ORIGINAL_READERS.add(self._reader)
        self._reader.finished.connect(self._complete)
        self._reader.finished.connect(lambda: _ORIGINAL_READERS.discard(self._reader))
        self._reader.finished.connect(self._reader.deleteLater)
        self._reader.start()

    def cancel(self, *_args) -> None:
        self._cancelled = True
        if self.pending:
            self._reader.requestInterruption()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Close:
            self.cancel()
        return super().eventFilter(watched, event)

    def _complete(self) -> None:
        reader = self._reader
        self.path, self.error = reader.path, reader.error
        success = False
        if self._cancelled or _EXITING:
            self.status = "Opening original cancelled."
        elif self.error is None and self.path is not None:
            try:
                success = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))
                if not success:
                    self.error = OriginalDocumentError("default_application_did_not_accept_document")
            except Exception as exc:
                self.error = exc
        if not success and self.path is not None:
            try:
                reader.session.discard(self.path)
                self.path = None
            except (OSError, OriginalDocumentError):
                # A locked file remains private and is retried during session cleanup.
                pass
        if success:
            self.status = "Sent to the default application."
        elif self.error is not None and not self._cancelled and not _EXITING:
            self.status = "Original document could not be opened. Try again."
            QMessageBox.warning(
                self._parent(),
                "Original document was not opened",
                "The saved original could not be prepared or sent to its default application. "
                "Check that a default application is installed, then retry.\n\n"
                f"Details: {self.error}",
            )
        self.pending = False
        parent = self._parent()
        if parent is not None:
            try:
                parent.removeEventFilter(self)
            except RuntimeError:
                pass  # QObject destruction already cancelled this request.
        self.status_changed.emit(self.status)
        self.finished.emit(success)
        _ORIGINAL_OPENERS.discard(self)


def open_original_document(profile: Path, source_sha256: str, parent=None) -> OriginalDocumentOpen:
    """Read the captured saved source, never its former input/archive pathname."""
    return OriginalDocumentOpen(profile=Path(profile), source_sha256=source_sha256, parent=parent)


def open_saved_original(saved: SavedImport, parent=None) -> OriginalDocumentOpen:
    """Use already-verified preview bytes without reopening its profile."""
    return OriginalDocumentOpen(saved=saved, source_sha256=saved.evidence.source_sha256, parent=parent)

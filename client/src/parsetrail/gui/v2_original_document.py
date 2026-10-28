"""Read verified retained originals asynchronously into a memory-only viewer."""

from __future__ import annotations

import atexit
import time
import weakref
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Signal
from PySide6.QtWidgets import QDialog, QMessageBox

from parsetrail.core.v2_original_document import read_saved_original
from parsetrail.gui.v2_document_viewer import show_saved_document

_ORIGINAL_READERS: set[QThread] = set()
_ORIGINAL_OPENERS: set[OriginalDocumentOpen] = set()
_EXITING = False


def _finish_original_readers() -> None:
    global _EXITING
    _EXITING = True
    for operation in tuple(_ORIGINAL_OPENERS):
        operation.cancel()
    for reader in tuple(_ORIGINAL_READERS):
        reader.requestInterruption()
        while reader.isRunning():
            reader.wait(10)
            time.sleep(0.001)
        reader.wait()
        _ORIGINAL_READERS.discard(reader)


atexit.register(_finish_original_readers)


class _OriginalReader(QThread):
    def __init__(self, *, profile, source_sha256, saved):
        super().__init__()
        self.profile, self.source_sha256, self.saved = profile, source_sha256, saved
        self.result, self.error = None, None

    def run(self):
        try:
            if not self.isInterruptionRequested():
                self.result = self.saved or read_saved_original(
                    self.profile, self.source_sha256, cancelled=self.isInterruptionRequested
                )
        except Exception as exc:
            self.error = exc


class OriginalDocumentOpen(QObject):
    """Retain a captured read until completion; close the viewer with its host."""

    finished = Signal(bool)
    status_changed = Signal(str)

    def __init__(self, *, profile=None, source_sha256, saved=None, parent=None, initial_page=None, context=""):
        super().__init__()
        self._parent = weakref.ref(parent) if parent is not None else lambda: None
        self.pending, self._cancelled, self._finished, self._read_pending = True, False, False, True
        self.status = "Loading saved original…"
        self.error, self.viewer = None, None
        self.initial_page, self.context = initial_page, context
        self._reader = _OriginalReader(profile=profile, source_sha256=source_sha256, saved=saved)
        if parent is not None:
            parent.destroyed.connect(self.cancel)
            parent.installEventFilter(self)
            if isinstance(parent, QDialog):
                parent.finished.connect(self.cancel)
        app = QCoreApplication.instance()
        if app is not None and not app.property("parsetrailEmbeddedOriginalExitHook"):
            app.setProperty("parsetrailEmbeddedOriginalExitHook", True)
            app.aboutToQuit.connect(_finish_original_readers)
        _ORIGINAL_OPENERS.add(self)
        _ORIGINAL_READERS.add(self._reader)
        self._reader.finished.connect(self._complete_read)
        self._reader.finished.connect(lambda: _ORIGINAL_READERS.discard(self._reader))
        self._reader.finished.connect(self._reader.deleteLater)
        self._reader.start()

    def cancel(self, *_args):
        self._cancelled = True
        if self._read_pending:
            self._reader.requestInterruption()
        if self.viewer is not None:
            try:
                self.viewer.reject()
            except RuntimeError:
                pass

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Close:
            self.cancel()
        return super().eventFilter(watched, event)

    def _remove_filter(self):
        parent = self._parent()
        if parent is not None:
            try:
                parent.removeEventFilter(self)
            except RuntimeError:
                pass

    def _finish(self, success):
        if self._finished:
            return
        self._finished, self.pending = True, False
        if self.viewer is None:
            self._remove_filter()
        self.status_changed.emit(self.status)
        self.finished.emit(success)
        if self.viewer is None:
            _ORIGINAL_OPENERS.discard(self)

    def _complete_read(self):
        self._read_pending = False
        saved = self._reader.result
        self._reader.result = self._reader.saved = None
        if self._cancelled or _EXITING:
            self.status = "Opening original cancelled."
            self._finish(False)
            return
        self.error = self._reader.error
        if self.error is not None or saved is None:
            self.status = "Saved original could not be read. Retry or save a recovery copy from Profile."
            self._finish(False)
            QMessageBox.warning(
                self._parent(), "Saved original could not be read", f"{self.status}\n\nDetails: {self.error}"
            )
            return
        try:
            self.viewer = show_saved_document(
                saved, self._parent(), initial_page=self.initial_page, context=self.context
            )
            self.viewer.load_finished.connect(self._loaded)
            self.viewer.finished.connect(self._viewer_closed)
        except Exception as exc:
            self.error = exc
            self.status = "Original preview is unavailable. Retry or save a recovery copy from Profile."
            self._finish(False)

    def _loaded(self, success):
        if self._cancelled or _EXITING:
            self.status = "Opening original cancelled."
            self._finish(False)
            return
        if not success and self.viewer.needs_password:
            self.status = "This original needs a password. Enter it in the viewer for this session."
            self.status_changed.emit(self.status)
            return
        self.error = self.viewer.error
        self.status = (
            "Original document opened in ParseTrail."
            if success
            else "Original preview could not be displayed. Retry or save a recovery copy from Profile."
        )
        self._finish(success)

    def _viewer_closed(self, *_args):
        self._remove_filter()
        if self.pending:
            self.status = "Opening original cancelled."
            self._finish(False)
        _ORIGINAL_OPENERS.discard(self)


def open_original_document(profile: Path, source_sha256: str, parent=None, *, initial_page=None, context=""):
    return OriginalDocumentOpen(
        profile=Path(profile), source_sha256=source_sha256, parent=parent, initial_page=initial_page, context=context
    )


def open_saved_original(saved, parent=None, *, initial_page=None, context=""):
    return OriginalDocumentOpen(
        saved=saved,
        source_sha256=saved.evidence.source_sha256,
        parent=parent,
        initial_page=initial_page,
        context=context,
    )

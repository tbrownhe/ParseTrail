"""Read verified retained originals asynchronously into a memory-only viewer."""

from __future__ import annotations

import atexit
import time
import weakref
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Signal
from PySide6.QtWidgets import QDialog, QMessageBox
from shiboken6 import isValid

from parsetrail.core.v2_original_document import read_saved_original, read_selected_original
from parsetrail.gui.v2_document_viewer import show_saved_document
from parsetrail.gui.v2_gui_lifetime import clear_exception_tracebacks

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
    # aboutToQuit does not deliver ordinary queued completion callbacks again.
    # Every reader has stopped, so release its data and traceback on this thread.
    for operation in tuple(_ORIGINAL_OPENERS):
        if operation._read_pending:
            operation._complete_read()


atexit.register(_finish_original_readers)


class _OriginalReader(QThread):
    def __init__(self, *, profile, source_sha256, saved, selected_path=None):
        super().__init__()
        self.profile, self.source_sha256, self.saved = profile, source_sha256, saved
        self.selected_path = selected_path
        self.result, self.error = None, None

    def run(self):
        try:
            if not self.isInterruptionRequested():
                self.result = (
                    read_selected_original(
                        self.selected_path, self.source_sha256, cancelled=self.isInterruptionRequested
                    )
                    if self.selected_path is not None
                    else self.saved
                    or read_saved_original(self.profile, self.source_sha256, cancelled=self.isInterruptionRequested)
                )
        except Exception as exc:
            self.error = exc


class OriginalDocumentOpen(QObject):
    """Retain a captured read until completion; close the viewer with its host."""

    finished = Signal(bool)
    status_changed = Signal(str)

    def __init__(
        self, *, profile=None, source_sha256, saved=None, selected_path=None, parent=None, initial_page=None, context=""
    ):
        super().__init__()
        self._parent = weakref.ref(parent) if parent is not None else lambda: None
        self.pending, self._cancelled, self._finished, self._read_pending = True, False, False, True
        self._selected = selected_path is not None
        self.status = "Loading selected original…" if self._selected else "Loading saved original…"
        self.error, self.viewer = None, None
        self._host_connections = []
        self._delete_pending = False
        self.initial_page, self.context = initial_page, context
        self._reader = _OriginalReader(
            profile=profile, source_sha256=source_sha256, saved=saved, selected_path=selected_path
        )
        if parent is not None:
            operation_ref = weakref.ref(self)

            def host_closed(*_args):
                operation = operation_ref()
                if operation is not None and isValid(operation):
                    operation.cancel()

            self._host_connections.append(parent.destroyed.connect(host_closed))
            parent.installEventFilter(self)
            if isinstance(parent, QDialog):
                self._host_connections.append(parent.finished.connect(host_closed))
        app = QCoreApplication.instance()
        if app is not None and not app.property("parsetrailEmbeddedOriginalExitHook"):
            app.setProperty("parsetrailEmbeddedOriginalExitHook", True)
            app.aboutToQuit.connect(_finish_original_readers)
        _ORIGINAL_OPENERS.add(self)
        _ORIGINAL_READERS.add(self._reader)
        reader = self._reader
        reader.finished.connect(self._complete_read)
        reader.finished.connect(lambda: _ORIGINAL_READERS.discard(reader))
        reader.finished.connect(reader.deleteLater)
        reader.start()

    def cancel(self, *_args):
        self._cancelled = True
        if self._read_pending and self._reader is not None and isValid(self._reader):
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

    def _parent_widget(self):
        parent = self._parent()
        return parent if parent is not None and isValid(parent) else None

    def _release_host(self):
        parent = self._parent_widget()
        if parent is not None and isValid(self):
            parent.removeEventFilter(self)
        for connection in self._host_connections:
            QObject.disconnect(connection)
        self._host_connections.clear()

    def _release_operation(self):
        if self._read_pending or self.viewer is not None:
            return
        self._release_host()
        if isinstance(self.error, BaseException):
            clear_exception_tracebacks(self.error)
        _ORIGINAL_OPENERS.discard(self)
        if not self._delete_pending and isValid(self):
            self._delete_pending = True
            self.deleteLater()

    def _finish(self, success):
        if self._finished:
            return
        self._finished, self.pending = True, False
        self.status_changed.emit(self.status)
        self.finished.emit(success)
        self._release_operation()

    def _complete_read(self):
        reader, self._reader = self._reader, None
        if reader is None:
            return
        self._read_pending = False
        saved, error = reader.result, reader.error
        reader.result = reader.saved = reader.error = None
        clear_exception_tracebacks(error)
        if self._cancelled or _EXITING:
            self.status = "Opening original cancelled."
            self._finish(False)
            return
        self.error = error
        if self.error is not None or saved is None:
            self.status = (
                "The selected original changed or could not be read. Select it again to refresh the import."
                if self._selected
                else "Saved original could not be read. Retry or save a recovery copy from Profile."
            )
            self._finish(False)
            QMessageBox.warning(
                self._parent_widget(), "Original could not be read", f"{self.status}\n\nDetails: {self.error}"
            )
            return
        try:
            self.viewer = show_saved_document(
                saved, self._parent_widget(), initial_page=self.initial_page, context=self.context
            )
            self.viewer.load_finished.connect(self._loaded)
            self.viewer.finished.connect(self._viewer_closed)
            self.viewer.destroyed.connect(self._viewer_closed)
        except Exception as exc:
            clear_exception_tracebacks(exc)
            self.error = exc
            self.status = "Original preview is unavailable. Retry or save a recovery copy from Profile."
            self._finish(False)

    def _loaded(self, success):
        if self.viewer is None:
            return
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
        viewer, self.viewer = self.viewer, None
        if viewer is not None and isValid(viewer):
            viewer.load_finished.disconnect(self._loaded)
            viewer.finished.disconnect(self._viewer_closed)
            viewer.destroyed.disconnect(self._viewer_closed)
        if self.pending:
            self.status = "Opening original cancelled."
            self._finish(False)
        else:
            self._release_operation()


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


def open_selected_original(path: Path, expected_sha256: str, parent=None):
    """Open verified pre-import bytes without creating any saved-import claim."""
    return OriginalDocumentOpen(
        selected_path=Path(path),
        source_sha256=expected_sha256,
        parent=parent,
        context=f"Selected original: {Path(path).name} · Not imported yet. Viewing changes no accounts or assignments.",
    )

"""PDF UI callbacks run after native loading and ignore obsolete notifications."""

import threading

from parsetrail.gui import v2_document_viewer as gui
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from shiboken6 import isValid

from .test_v2_document_viewer import saved_original, synthetic_pdf


def test_password_ui_waits_for_native_load_and_retains_device(qtbot, monkeypatch):
    saved = saved_original(synthetic_pdf(password="synthetic-password"))
    native_load = gui.QPdfDocument.load
    password_ui = gui.V2DocumentViewer._password_required
    in_load = []
    events = []
    callbacks = []
    completed = []
    gui_thread = threading.get_ident()

    def _password_required(viewer):
        callbacks.append((bool(in_load), threading.get_ident()))
        return password_ui(viewer)

    def load(document, device):
        document.statusChanged.connect(lambda status: events.append((status, bool(in_load))), Qt.DirectConnection)
        in_load.append(True)
        try:
            assert isValid(document) and isValid(device) and device.isOpen()
            assert bytes(device.data()) == saved.source
            value = native_load(document, device)
            assert isValid(document) and isValid(device) and device.isOpen()
            assert bytes(device.data()) == saved.source
            assert not callbacks and not completed
            return value
        finally:
            in_load.pop()

    monkeypatch.setattr(gui.QPdfDocument, "load", load)
    monkeypatch.setattr(gui.V2DocumentViewer, "_password_required", _password_required)
    viewer = gui.show_saved_document(saved)
    viewer.load_finished.connect(completed.append)
    try:
        qtbot.waitUntil(lambda: viewer.needs_password)
        assert (gui.QPdfDocument.Status.Error, True) in events
        assert callbacks and all(callback == (False, gui_thread) for callback in callbacks)
        assert completed == [False]
        assert viewer._saved is saved and viewer.pdf_buffer.isOpen()
    finally:
        viewer.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(viewer)


def test_ready_view_ignores_obsolete_error_and_password_notifications(qtbot):
    viewer = gui.show_saved_document(saved_original())
    completed = []
    viewer.load_finished.connect(completed.append)
    try:
        qtbot.waitUntil(lambda: viewer.ready)
        assert completed == [True]
        viewer._pdf_status(gui.QPdfDocument.Status.Error)
        viewer._password_required()
        assert viewer.ready and not viewer.pending and not viewer.needs_password
        assert not viewer.password_controls.isVisible()
        assert completed == [True]
    finally:
        viewer.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

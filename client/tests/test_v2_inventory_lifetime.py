"""Inventory delivery precedes GUI-thread cleanup, including failure paths."""

from parsetrail.gui.v2_document_browser import _INVENTORY_READERS, DocumentInventoryWorker
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QThread, Slot
from shiboken6 import isValid


def test_inventory_error_delivered_then_traceback_and_native_worker_released(qapp, qtbot, tmp_path):
    worker = DocumentInventoryWorker(tmp_path / "missing-synthetic-profile.db", 1)
    errors = []
    destroyed_on = []

    class Receiver(QObject):
        @Slot()
        def completed(self):
            errors.append(worker.error)
            assert QThread.currentThread() == qapp.thread()

    receiver = Receiver()
    worker.finished.connect(receiver.completed, Qt.QueuedConnection)
    worker.destroyed.connect(lambda: destroyed_on.append(QThread.currentThread()), Qt.DirectConnection)
    worker.start()
    qtbot.waitUntil(lambda: bool(errors) and worker not in _INVENTORY_READERS)
    assert errors[0] is not None and errors[0].__traceback__ is None
    assert worker.error is None and worker.result == () and worker.accounts == ()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(worker)
    assert destroyed_on == [qapp.thread()]


def test_inventory_cleanup_does_not_depend_on_a_live_receiver(qtbot, tmp_path):
    worker = DocumentInventoryWorker(tmp_path / "missing-synthetic-profile.db", 1)
    receiver = QObject()
    worker.finished.connect(receiver.deleteLater)
    receiver.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    worker.start()
    qtbot.waitUntil(lambda: worker not in _INVENTORY_READERS)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(worker)

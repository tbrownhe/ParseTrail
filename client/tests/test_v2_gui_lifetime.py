"""Modal native disposal and error handoff without cyclic-GC manipulation."""

from builtins import ExceptionGroup

import pytest
from parsetrail.gui.v2_gui_lifetime import clear_exception_tracebacks, exec_disposable
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThread, QTimer
from PySide6.QtWidgets import QDialog, QTableView, QTabWidget, QVBoxLayout
from shiboken6 import isValid


def test_closed_tabbed_modal_is_deleted_on_gui_thread_while_parent_survives(qapp):
    parent = QDialog()
    dialog = QDialog(parent)
    tabs = QTabWidget(dialog)
    table = QTableView()
    tabs.addTab(table, "Synthetic source")
    QVBoxLayout(dialog).addWidget(tabs)
    destroyed_on = []
    dialog.destroyed.connect(lambda: destroyed_on.append(QThread.currentThread()), Qt.DirectConnection)
    QTimer.singleShot(0, dialog, dialog.accept)
    try:
        assert exec_disposable(dialog) == QDialog.Accepted
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert destroyed_on == [qapp.thread()]
        assert not isValid(dialog) and not isValid(table)
        assert isValid(parent)
        assert not parent.findChildren(QDialog)
    finally:
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.usefixtures("qapp")
def test_modal_exception_still_schedules_disposal():
    class FailedDialog(QDialog):
        def exec(self):
            raise ValueError("Synthetic modal failure")

    dialog = FailedDialog()
    with pytest.raises(ValueError, match="Synthetic modal failure"):
        exec_disposable(dialog)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(dialog)


def test_error_handoff_removes_nested_tracebacks_preserving_error_meaning():
    try:
        raise ValueError("Synthetic cause")
    except ValueError as error:
        cause = error
        try:
            raise RuntimeError("Synthetic outer") from cause
        except RuntimeError as error:
            outer = error
    try:
        raise ExceptionGroup("Synthetic group", [outer, cause])
    except ExceptionGroup as error:
        group = error
    assert all(error.__traceback__ is not None for error in (group, outer, cause))
    clear_exception_tracebacks(group)
    assert all(error.__traceback__ is None for error in (group, outer, cause))
    assert group.exceptions == (outer, cause)
    assert outer.__cause__ is cause and outer.__context__ is cause
    assert outer.args == ("Synthetic outer",) and cause.args == ("Synthetic cause",)

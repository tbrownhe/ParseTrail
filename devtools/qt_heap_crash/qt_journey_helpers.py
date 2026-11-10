"""Qt widget-event helpers; these never drive Windows or replace application slots."""

from __future__ import annotations

import json
import time
import warnings
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFileDialog, QLineEdit


def activate(qtbot, widget):
    # Keep Qt's test focus deterministic without depending on Windows foreground
    # activation policy. Inputs below still go through QTest mouse/key events.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*setActiveWindow.*")
        QApplication.setActiveWindow(widget.window())
    qtbot.waitUntil(widget.window().isActiveWindow, timeout=5000)


def enter_text(qtbot, widget, text):
    activate(qtbot, widget)
    qtbot.waitUntil(lambda: widget.isVisible() and widget.isEnabled(), timeout=10000)
    qtbot.mouseClick(widget, Qt.LeftButton)
    assert widget.hasFocus(), (widget.objectName(), QApplication.focusWidget())
    qtbot.keyClick(widget, Qt.Key_A, Qt.ControlModifier)
    qtbot.keyClicks(widget, str(text))


def choose_combo(qtbot, widget, value):
    activate(qtbot, widget)
    qtbot.waitUntil(lambda: widget.isVisible() and widget.isEnabled(), timeout=10000)
    index = widget.findData(value)
    assert index >= 0, (value, [widget.itemText(i) for i in range(widget.count())])
    for _ in range(80):
        if widget.hasFocus():
            break
        focused = QApplication.focusWidget()
        assert focused is not None
        qtbot.keyClick(focused, Qt.Key_Tab)
    assert widget.hasFocus(), "Combo box is not reachable by keyboard focus"
    if widget.isEditable():
        qtbot.keyClick(widget, Qt.Key_Down, Qt.AltModifier)
        view = widget.view()
        qtbot.waitUntil(view.isVisible, timeout=5000)
        qtbot.keyClick(view, Qt.Key_Home)
        for _ in range(index):
            qtbot.keyClick(view, Qt.Key_Down)
        qtbot.keyClick(view, Qt.Key_Return)
        assert widget.currentData() == value
        return
    qtbot.keyClick(widget, Qt.Key_Home)
    for _ in range(index):
        qtbot.keyClick(widget, Qt.Key_Down)
    assert widget.currentData() == value


def click_list_row(qtbot, widget, row):
    activate(qtbot, widget)
    qtbot.mouseClick(widget.viewport(), Qt.LeftButton, pos=widget.visualItemRect(widget.item(row)).center())


def click_table_text(qtbot, table, text):
    activate(qtbot, table)
    qtbot.waitUntil(table.isEnabled, timeout=10000)
    model = table.model()
    for row in range(model.rowCount()):
        for column in range(model.columnCount()):
            index = model.index(row, column)
            if text in str(model.data(index) or ""):
                table.scrollTo(index)
                qtbot.mouseClick(table.viewport(), Qt.LeftButton, pos=table.visualRect(index).center())
                return
    raise AssertionError(f"No visible table row containing {text!r}")


def close_dialog(qtbot, dialog):
    buttons = dialog.findChild(QDialogButtonBox)
    button = buttons.button(QDialogButtonBox.Close)
    assert button is not None
    qtbot.mouseClick(button, Qt.LeftButton)


def select_file(qtbot, dialog, path):
    """Use Qt's real, non-native file picker through its filename editor."""
    field = dialog.findChild(QLineEdit, "fileNameEdit")
    assert field is not None
    enter_text(qtbot, field, Path(path).resolve().as_posix())
    assert Path(dialog.selectedFiles()[0]).resolve() == Path(path).resolve(), dialog.selectedFiles()
    buttons = dialog.findChild(QDialogButtonBox)
    button = buttons.button(
        QDialogButtonBox.Save if dialog.acceptMode() == QFileDialog.AcceptSave else QDialogButtonBox.Open
    )
    assert button is not None
    qtbot.mouseClick(button, Qt.LeftButton)


def click_menu(qtbot, window, menu_text, action_text):
    activate(qtbot, window)
    action = next(action for action in window.menuBar().actions() if action.text() == menu_text)
    qtbot.mouseClick(window.menuBar(), Qt.LeftButton, pos=window.menuBar().actionGeometry(action).center())
    menu = action.menu()
    target = next(action for action in menu.actions() if action.text().startswith(action_text))
    assert target.isEnabled()
    qtbot.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(target).center())


class ModalSteps:
    """Schedule real dialog events while synchronous exec() runs nested Qt loops."""

    def __init__(self, qtbot):
        self.qtbot = qtbot
        self.steps = deque()
        self.error = None
        self.deadline = 0
        self._candidate = None
        self._last_modal = None

    def arm(self, *steps):
        assert not self.steps
        self.error = None
        self._candidate = None
        self._last_modal = None
        self.steps.extend(steps)
        self.deadline = time.monotonic() + 20
        QTimer.singleShot(0, self._poll)

    def _poll(self):
        modal = QApplication.activeModalWidget()
        if self.error is not None:
            if modal is not None:
                modal.reject()
                QTimer.singleShot(0, self._poll)
            return
        if not self.steps:
            return
        if time.monotonic() > self.deadline:
            self.error = AssertionError(f"Modal step timed out; active dialog: {modal!r}")
            self.steps.clear()
            QTimer.singleShot(0, self._poll)
            return
        kind, action = self.steps[0]
        matches = type(modal) is QDialog if kind is QDialog else isinstance(modal, kind)
        if not matches or not modal.isVisible() or modal is self._last_modal:
            QTimer.singleShot(10, self._poll)
            return
        if self._candidate is not modal:
            self._candidate = modal
            modal.activateWindow()
            QTimer.singleShot(10, self._poll)
            return
        self.steps.popleft()
        self._candidate = None
        self._last_modal = modal
        QTimer.singleShot(10, self._poll)
        try:
            action(modal)
        except Exception as exc:
            self.error = exc
            self.steps.clear()
            QTimer.singleShot(0, self._poll)

    def finish(self):
        self.qtbot.waitUntil(lambda: self.error is not None or not self.steps, timeout=25000)
        if self.error is not None:
            raise self.error


class JourneyArtifacts:
    def __init__(self, directory, qapp, size):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest = {
            "platform": qapp.platformName(),
            "requested_window_size": size,
            "interaction": "pytest-qt mouse/keyboard widget events; non-native Qt file dialogs",
            "focus_setup": "QApplication.setActiveWindow before direct Qt test events; no OS activation claim",
            "acceptance": "Scripted software verification; not uncoached or human acceptance",
            "screenshots": [],
        }

    def capture(self, name, widget, *, settle=True):
        if settle:
            QApplication.processEvents()
        destination = self.directory / f"{name}.png"
        assert widget.grab().save(str(destination))
        self.manifest["screenshots"].append(
            {"state": name, "file": destination.name, "width": widget.width(), "height": widget.height()}
        )
        (self.directory / "manifest.json").write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")

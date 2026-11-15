"""Functional checks use the real staging/preview path, stubbing only its modal."""

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPlainTextEdit

from .v2_job_wait import wait_for_jobs


def review_reason(view):
    """The visible reason editor for this selected decision's scope."""
    if not hasattr(view, "batch"):
        return view.reason
    row = view._current() if hasattr(view, "_current") else None
    single_saved = (
        row is not None
        and (row.entry_key is not None or row.status == "Already posted to the ledger")
        and len(view.navigation.selected()) == 1
    )
    if hasattr(view, "batch") and not single_saved:
        return view.batch.reason
    return view.reason


def choose_review_menu(qtbot, button, menu, action):
    """Open the actual menu button and activate its visible action with Qt input."""
    errors = []
    timer = QTimer(menu)
    timer.setSingleShot(True)

    def choose():
        try:
            assert menu.isVisible() and action.isEnabled()
            qtbot.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center())
        except BaseException as error:
            errors.append(error)
            menu.close()

    timer.timeout.connect(choose)
    timer.start(0)
    qtbot.mouseClick(button, Qt.LeftButton)
    timer.deleteLater()
    if errors:
        raise errors[0]
    qtbot.waitUntil(lambda: not menu.isVisible())


def review_action(view):
    """The applicable visible action: stage new rows, correct or inspect saved ones."""
    row = view._current()
    if row is not None and (
        row.entry_key is not None
        or row.status == "Already posted to the ledger"
        or view.purpose.currentData() in {"repayment", "external_history"}
    ):
        return view.action_button
    return view.batch.stage_button


def stage_and_confirm(view, monkeypatch=None, *, before_confirm=None):
    """Stage explicit form choices and run exact preview through existing question spies.

    Only modal interaction is replaced. The real preview worker, source/profile
    guards and batch journal write remain in use. Native journey tests interact
    with this confirmation directly instead of using this functional helper.
    """
    selected = {row.row_id for row in view.navigation.selected()}
    assert selected
    if view.batch.stage_button.isEnabled():
        view.batch.stage_button.click()
    assert selected <= set(view.batch.staged), view.status.text()
    assert view.batch.preview_button.isEnabled(), view.batch.summary.text()

    def confirm(dialog):
        assert dialog.windowTitle().startswith("Confirm staged")
        text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
        text += "\n" + dialog.findChild(QPlainTextEdit).toPlainText()
        if before_confirm is not None:
            before_confirm(dialog)
        response = QMessageBox.question(view, dialog.windowTitle(), text)
        return QDialog.Accepted if response == QMessageBox.Yes else QDialog.Rejected

    context = monkeypatch.context() if monkeypatch is not None else pytest.MonkeyPatch.context()
    with context as patch:
        patch.setattr(QDialog, "exec", confirm)
        view.batch.preview_button.click()
        wait_for_jobs(view)

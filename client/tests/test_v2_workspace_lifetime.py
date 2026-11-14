"""Queued workspace actions cannot outlive their native receiving window."""

from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import QCoreApplication, QEvent
from shiboken6 import isValid


def test_destroyed_workspace_cancels_queued_close_and_initial_inventory(qtbot, tmp_path):
    workspace = V2Workspace.create(
        tmp_path / "synthetic.db",
        tmp_path / "catalog",
        trusted_keys={},
        preferences_path=tmp_path / "preferences.json",
    )
    window = V2WorkspaceWindow(workspace)
    window._close_after_job = True
    window._embedded_busy(False)
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(window)
    # Exercise the pending metacalls/timers; pytest-qt reports any late slot error.
    qtbot.wait(1)
    assert window._inventory_worker is None

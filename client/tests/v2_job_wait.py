"""Wait for GUI worker outcomes while keeping the Qt event loop responsive."""

import time


def wait_for_jobs(view, timeout=15):
    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout
    while view.jobs.pending and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    assert not view.jobs.pending, "Profile operation did not finish"

"""Document discovery stays readable and responsive across refresh/close."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from threading import Event
from time import sleep

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QElapsedTimer, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def wait_for_inventory(window, timeout=10000):
    app = QApplication.instance()
    timer = QElapsedTimer()
    timer.start()
    while window.inventory_pending and timer.elapsed() < timeout:
        app.processEvents()
        sleep(0.005)
    app.processEvents()
    assert not window.inventory_pending, "Document inventory did not settle"


def _populated_workspace(tmp_path):
    from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
    from parsetrail.core.v2_source_pipeline import build_source_evidence

    from .test_v2_workspace_window import DEFINITION, SOURCE, _workspace

    workspace = _workspace(tmp_path)
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Everyday checking", "asset", "synthetic"))
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
    return workspace


def test_documents_are_recognizable_searchable_and_preserve_context(tmp_path: Path, monkeypatch):
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    app = QApplication.instance() or QApplication([])
    window = V2WorkspaceWindow(_populated_workspace(tmp_path))
    reviews = []
    monkeypatch.setattr(
        "parsetrail.gui.v2_workspace_window.V2CashActivityReview.exec",
        lambda dialog: reviews.append(dialog.model.rowCount()),
    )
    try:
        wait_for_inventory(window)
        assert window.sources.count() == 1
        label = window.sources.item(0).text()
        assert "Everyday checking" in label and "2026-10-01" in label
        assert "Activity dates" in label and "unallocated" in label and "may include repeats" in label
        selected = window._selected_source()
        window.document_search.setText("no such account")
        assert window.sources.item(0).isHidden()
        assert not window.review_document_button.isEnabled()
        window.document_search.clear()
        assert window._selected_source() == selected
        window.document_search.setText("Everyday 2026-10")
        assert not window.sources.item(0).isHidden()
        window.review_document_button.click()
        wait_for_inventory(window)
        assert window.navigation.currentRow() == 1
        assert reviews == [1]
        assert "Everyday checking" in window.review_context.text()
        assert window.cash_review_button.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_inventory_loading_yields_to_events_and_close_waits_for_worker(tmp_path: Path, monkeypatch):
    from parsetrail.core.v2_profile_store import V2ProfileStore
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    app = QApplication.instance() or QApplication([])
    workspace = _populated_workspace(tmp_path)
    original = V2ProfileStore.document_summaries
    started, release = Event(), Event()

    def delayed(store):
        started.set()
        assert release.wait(10)
        return original(store)

    monkeypatch.setattr(V2ProfileStore, "document_summaries", delayed)
    window = V2WorkspaceWindow(workspace)
    pulse = []
    try:
        window.show()
        QTimer.singleShot(0, lambda: pulse.append(True))
        timer = QElapsedTimer()
        timer.start()
        while not started.is_set() and timer.elapsed() < 5000:
            app.processEvents()
            sleep(0.005)
        assert started.is_set() and pulse
        assert window.inventory_pending
        assert "Loading" in window.inventory_status.text()
        assert not window.review_document_button.isEnabled()
        window.close()
        assert window.isVisible()
    finally:
        release.set()
        wait_for_inventory(window)
        app.processEvents()
        window.close()
    assert not window.isVisible()


def test_failed_inventory_clears_actions_and_can_retry(tmp_path: Path, monkeypatch):
    from parsetrail.core.v2_profile_store import V2ProfileStore
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    app = QApplication.instance() or QApplication([])
    workspace = _populated_workspace(tmp_path)
    window = V2WorkspaceWindow(workspace)
    original = V2ProfileStore.document_summaries
    try:
        wait_for_inventory(window)

        def refuse(_store):
            raise ValueError("synthetic read failure")

        monkeypatch.setattr(V2ProfileStore, "document_summaries", refuse)
        window.refresh()
        wait_for_inventory(window)
        assert window.sources.count() == 0
        assert not window.review_document_button.isEnabled()
        assert "unavailable" in window.inventory_status.text()
        monkeypatch.setattr(V2ProfileStore, "document_summaries", original)
        window.retry_inventory.click()
        wait_for_inventory(window)
        assert window.sources.count() == 1
        assert window.review_document_button.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_late_inventory_from_previous_profile_cannot_replace_current_accounts(tmp_path: Path, monkeypatch):
    from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    app = QApplication.instance() or QApplication([])
    first_root, second_root = tmp_path / "first", tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first, second = _populated_workspace(first_root), _populated_workspace(second_root)
    with V2ProfileStore.open(second.profile_path) as store:
        store.update_financial_account(FinancialAccount("cash", "New profile checking", "asset", "synthetic"))
    original = V2ProfileStore.document_summaries
    started, release = Event(), Event()
    calls = []

    def delayed(store):
        calls.append(True)
        if len(calls) == 1:
            started.set()
            assert release.wait(10)
        return original(store)

    monkeypatch.setattr(V2ProfileStore, "document_summaries", delayed)
    window = V2WorkspaceWindow(first)
    try:
        timer = QElapsedTimer()
        timer.start()
        while not started.is_set() and timer.elapsed() < 5000:
            app.processEvents()
            sleep(0.005)
        assert started.is_set()
        window._select_workspace(second)
        assert window.accounts_list.count() == 0
        release.set()
        wait_for_inventory(window)
        assert "New profile checking" in window.sources.item(0).text()
        assert "Everyday checking" not in window.sources.item(0).text()
        assert "New profile checking" in window.accounts_list.item(0).text()
    finally:
        release.set()
        wait_for_inventory(window)
        window.close()
        app.processEvents()


@pytest.mark.parametrize("event_loop", [False, True])
def test_inventory_connection_finishes_before_process_teardown(tmp_path: Path, event_loop):
    code = """
import hashlib,json,sys,time
from pathlib import Path
from threading import Event
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_document_browser import _INVENTORY_READERS
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
root=Path(sys.argv[1]);use_loop=sys.argv[2]=='True'
app=QApplication([])
workspace=V2Workspace.create(root/'profile.db',root/'catalog',trusted_keys={},preferences_path=root/'prefs.json')
before=hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest()
original=V2ProfileStore.document_summaries
started=Event()
def delayed(store):
 started.set();time.sleep(.3)
 try:return original(store)
 finally:(root/'finished.txt').write_text('finished')
V2ProfileStore.document_summaries=delayed
window=V2WorkspaceWindow(workspace)
deadline=time.monotonic()+5
while not started.is_set() and time.monotonic()<deadline:
 app.processEvents();time.sleep(.005)
assert started.is_set()
window.close()
if use_loop:
 QTimer.singleShot(0,app.quit);app.exec()
 assert not any(reader.isRunning() for reader in _INVENTORY_READERS)
assert hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest()==before
print(json.dumps({'closed':True}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), str(event_loop)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "finished.txt").read_text() == "finished"

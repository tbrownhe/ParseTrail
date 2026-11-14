"""Original-viewer disposal uses the GUI event loop without waiting for Python GC."""

from __future__ import annotations

import threading
import weakref

import pytest
from parsetrail.core.v2_profile_store import SavedImport, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui import v2_document_viewer as viewer_gui
from parsetrail.gui import v2_original_document as gui
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QDialog, QMessageBox
from shiboken6 import delete, isValid

from .test_v2_document_viewer import saved_original, synthetic_pdf
from .test_v2_profile_store import CSV, CSV_DEFINITION


def flush_deletions():
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def saved():
    evidence = build_source_evidence(CSV, CSV_DEFINITION, suffix=".csv")
    return SavedImport(CSV, CSV_DEFINITION, evidence, ".csv")


@pytest.fixture(autouse=True)
def isolated_gui(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    monkeypatch.setattr(gui, "_EXITING", False)
    yield
    for operation in tuple(gui._ORIGINAL_OPENERS):
        operation.cancel()
    for reader in tuple(gui._ORIGINAL_READERS):
        assert reader.wait(5000)
    qapp.processEvents()
    for viewer in tuple(viewer_gui._VIEWERS):
        viewer.close()
    for reader in tuple(viewer_gui._CSV_READERS):
        assert reader.wait(5000)
    qapp.processEvents()
    flush_deletions()


@pytest.mark.parametrize("finish", ["close", "reject", "accept"])
def test_viewer_releases_data_then_deletes_native_children_on_gui_thread(qtbot, saved, finish):
    parent = QDialog()
    viewer = viewer_gui.show_saved_document(saved, parent)
    qtbot.waitUntil(lambda: not viewer.pending)
    assert viewer.ready
    children = (viewer.csv_model, viewer.pdf_panel, viewer.page_text)
    destroyed_threads = []
    viewer.destroyed.connect(lambda: destroyed_threads.append(threading.get_ident()), Qt.DirectConnection)

    getattr(viewer, finish)()
    assert viewer._saved is None and viewer.csv_model.rowCount() == 0
    assert not viewer._host_connections and viewer not in viewer_gui._VIEWERS
    flush_deletions()

    assert not isValid(viewer) and all(not isValid(child) for child in children)
    assert destroyed_threads == [threading.get_ident()]
    assert not parent.findChildren(viewer_gui.V2DocumentViewer)
    parent.deleteLater()


def test_repeated_profile_original_opens_release_reader_viewer_and_host_callbacks(qtbot, tmp_path, saved):
    profile = tmp_path / "disposable.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(saved.source, saved.definition, saved.evidence, suffix=saved.suffix)
    parent = QDialog()
    for _ in range(3):
        action = gui.open_original_document(profile, saved.evidence.source_sha256, parent)
        qtbot.waitUntil(lambda action=action: not action.pending)
        viewer = action.viewer
        assert viewer.ready and action._reader is None
        assert action in gui._ORIGINAL_OPENERS
        action_ref = weakref.ref(action)
        destroyed_threads = []
        action.destroyed.connect(
            lambda _object=None, threads=destroyed_threads: threads.append(threading.get_ident()), Qt.DirectConnection
        )
        viewer.close()
        assert action.viewer is None and not action._host_connections
        assert action not in gui._ORIGINAL_OPENERS
        flush_deletions()
        assert not isValid(viewer) and not isValid(action)
        assert destroyed_threads == [threading.get_ident()]
        assert not parent.findChildren(viewer_gui.V2DocumentViewer)
        del action
        assert action_ref() is None
    parent.deleteLater()


def test_read_failure_releases_traceback_chain_and_reader_without_losing_diagnostic(qtbot, monkeypatch, tmp_path):
    def failed_read(*_args, **_kwargs):
        try:
            raise RuntimeError("synthetic cause")
        except RuntimeError as cause:
            raise ValueError("synthetic read failure") from cause

    monkeypatch.setattr(gui, "read_saved_original", failed_read)
    action = gui.open_original_document(tmp_path / "unused-disposable.db", "synthetic-source")
    reader = action._reader
    qtbot.waitUntil(lambda: not action.pending)

    assert type(action.error) is ValueError and action.error.args == ("synthetic read failure",)
    assert action.error.__traceback__ is None
    assert action.error.__cause__.args == ("synthetic cause",)
    assert action.error.__cause__.__traceback__ is None
    assert action._reader is None and action.viewer is None
    assert reader.error is reader.result is reader.saved is None
    assert action not in gui._ORIGINAL_OPENERS
    flush_deletions()
    assert not isValid(action) and not isValid(reader)


def test_viewer_construction_failure_releases_gui_traceback(qtbot, monkeypatch, saved):
    def failed_viewer(*_args, **_kwargs):
        raise RuntimeError("synthetic viewer unavailable")

    monkeypatch.setattr(gui, "show_saved_document", failed_viewer)
    action = gui.open_saved_original(saved)
    qtbot.waitUntil(lambda: not action.pending)
    assert action.error.args == ("synthetic viewer unavailable",)
    assert action.error.__traceback__ is None
    assert action._reader is None and action.viewer is None
    flush_deletions()
    assert not isValid(action)


@pytest.mark.parametrize("host_finish", ["reject", "close", "destroy"])
def test_host_close_retains_running_reader_until_actual_finish(qtbot, monkeypatch, tmp_path, saved, host_finish):
    started, release = threading.Event(), threading.Event()

    def delayed_read(*_args, **_kwargs):
        started.set()
        assert release.wait(5)
        return saved

    monkeypatch.setattr(gui, "read_saved_original", delayed_read)
    monkeypatch.setattr(gui, "show_saved_document", lambda *_args, **_kwargs: pytest.fail("Cancelled read opened"))
    parent = QDialog()
    action = gui.open_original_document(tmp_path / "unused-disposable.db", "synthetic-source", parent)
    reader = action._reader
    try:
        qtbot.waitUntil(started.is_set)
        if host_finish == "destroy":
            delete(parent)
        else:
            getattr(parent, host_finish)()
        flush_deletions()
        assert action.pending and isValid(reader) and reader.isRunning()
        assert action in gui._ORIGINAL_OPENERS and reader in gui._ORIGINAL_READERS
        release.set()
        qtbot.waitUntil(lambda: not action.pending)
        assert action.viewer is None and action._reader is None
        assert "cancelled" in action.status
        assert reader.result is reader.saved is None
        flush_deletions()
        assert not isValid(action) and not isValid(reader)
    finally:
        release.set()
        if isValid(reader):
            assert reader.wait(5000)
        if isValid(parent):
            parent.deleteLater()


def test_parent_destruction_closes_loaded_original_and_releases_opener(qtbot, saved):
    parent = QDialog()
    action = gui.open_saved_original(saved, parent)
    qtbot.waitUntil(lambda: not action.pending)
    viewer = action.viewer
    delete(parent)
    assert action.viewer is None and viewer._saved is None
    assert action not in gui._ORIGINAL_OPENERS
    flush_deletions()
    assert not isValid(viewer) and not isValid(action)


@pytest.mark.parametrize("unlock", [False, True])
def test_password_wait_keeps_operation_until_unlock_or_explicit_close(qtbot, unlock):
    action = gui.open_saved_original(saved_original(synthetic_pdf(password="synthetic-password")))
    qtbot.waitUntil(lambda: action.viewer is not None and action.viewer.needs_password)
    viewer = action.viewer
    completed = []
    action.finished.connect(completed.append)
    assert action.pending and action._reader is None
    assert action in gui._ORIGINAL_OPENERS
    if unlock:
        viewer.password.setText("wrong")
        viewer.unlock.click()
        qtbot.waitUntil(lambda: not viewer.pending)
        assert action.pending and completed == []
        viewer.password.setText("synthetic-password")
        viewer.unlock.click()
        qtbot.waitUntil(lambda: not action.pending)
        assert viewer.ready and completed == [True]
    viewer.reject()
    assert completed == [unlock]
    assert action.viewer is None and viewer._saved is None
    flush_deletions()
    assert not isValid(viewer) and not isValid(action)


def test_display_failure_stays_readable_until_closed_then_releases_operation(qtbot):
    action = gui.open_saved_original(saved_original(b"%PDF-broken"))
    qtbot.waitUntil(lambda: not action.pending)
    viewer = action.viewer
    assert isinstance(action.error, str) and viewer.error == action.error
    assert viewer.isVisible() and action in gui._ORIGINAL_OPENERS
    viewer.close()
    assert action.viewer is None and action not in gui._ORIGINAL_OPENERS
    flush_deletions()
    assert not isValid(viewer) and not isValid(action)


def test_shutdown_releases_finished_read_without_delivering_a_queued_viewer(monkeypatch, saved):
    monkeypatch.setattr(gui, "show_saved_document", lambda *_args, **_kwargs: pytest.fail("Shutdown opened viewer"))
    action = gui.open_saved_original(saved)
    reader = action._reader
    assert reader.wait(5000)
    gui._finish_original_readers()
    assert not action.pending and action._reader is None and action.viewer is None
    assert reader.saved is reader.result is reader.error is None
    assert not gui._ORIGINAL_OPENERS and not gui._ORIGINAL_READERS
    flush_deletions()
    assert not isValid(action)

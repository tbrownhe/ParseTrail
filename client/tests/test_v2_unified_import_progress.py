"""One compact, cancellation-safe surface across real batch review handoffs."""

import gc
from threading import Event

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_import import ImportCancelled
from parsetrail.core.v2_workspace import BatchFileResult, BatchImportResult
from parsetrail.gui.v2_batch_import import V2BatchImportReport
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import QEvent, Qt, QThread
from PySide6.QtWidgets import QApplication, QMessageBox
from shiboken6 import isValid

from .qt_journey_helpers import JourneyArtifacts, activate, choose_combo
from .test_v2_import_account_review import group
from .test_v2_import_account_review_queue_states import requests
from .test_v2_occu_batch_import import occu_workspace
from .test_v2_occu_batch_import_dialog import create


def wait_gate(gate, cancelled):
    while not gate.wait(0.01):
        if cancelled():
            return


def start_window(qtbot, workspace, monkeypatch, size=(1050, 700)):
    reports = []
    monkeypatch.setattr(
        V2BatchImportReport,
        "exec",
        lambda dialog: reports.append(tuple(dialog.files.item(i).text() for i in range(dialog.files.count()))),
    )
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    qtbot.waitUntil(lambda: not window.inventory_pending and not window.profile_jobs.pending, timeout=15000)
    return window, reports


def finish_window(qtbot, window, gates=()):
    for gate in gates:
        gate.set()
    if window.import_worker is not None:
        window._cancel_import()
        qtbot.waitUntil(lambda: window.import_worker is None, timeout=20000)
    qtbot.waitUntil(lambda: not window.inventory_pending and not window.profile_jobs.pending, timeout=15000)
    window.close()


@pytest.mark.parametrize("size", [(1050, 700), (1100, 650)])
def test_input_automatic_input_uses_one_compact_surface_and_preserves_decisions(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts, size
):
    workspace, paths = occu_workspace(tmp_path, count=3)
    # A long selected filename exercises wrapping and the copyable full path.
    renamed = paths[1].with_name(
        "Public synthetic statement with a long recognizable savings and checking filename.pdf"
    )
    paths[1].rename(renamed)
    paths = (paths[0], renamed, paths[2])
    entered = [Event() for _ in paths]
    release = [Event() for _ in paths]
    skip_returned, finish_skip = Event(), Event()
    original = workspace.import_file

    def import_file(path, **kwargs):
        index = paths.index(path)
        entered[index].set()
        wait_gate(release[index], kwargs["cancelled"])
        try:
            return original(path, **kwargs)
        finally:
            if index == 2:
                skip_returned.set()
                wait_gate(finish_skip, kwargs["cancelled"])

    monkeypatch.setattr(workspace, "import_file", import_file)
    window, reports = start_window(qtbot, workspace, monkeypatch, size)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    destroyed = []
    try:
        window.start_batch_import(paths)
        worker, progress = window.import_worker, window.progress
        worker.destroyed.connect(lambda: destroyed.append(("worker", QThread.currentThread() is qapp.thread())))
        progress.destroyed.connect(lambda: destroyed.append(("progress", QThread.currentThread() is qapp.thread())))
        qtbot.waitUntil(lambda: entered[0].is_set() and progress.isVisible())
        assert progress.completed.value() == 0 and "File 1 of 3" in progress.file_context.text()
        assert progress.body.hasFocus()
        artifacts.capture("01-first-read-compact", progress)
        release[0].set()
        qtbot.waitUntil(lambda: window.import_preview is not None and window.import_preview.isVisible(), timeout=15000)
        view = window.import_preview
        view.resize(*size)
        view.destroyed.connect(lambda: destroyed.append(("review", QThread.currentThread() is qapp.thread())))
        assert not progress.isVisible()
        create(qtbot, view, "Public primary savings", "savings")
        group(qtbot, view, 1)
        create(qtbot, view, "Public remarkable checking", "checking")
        qtbot.mouseClick(view.abbreviated_matching, Qt.LeftButton)
        choose_combo(qtbot, view.preview_mode, "when_needed")
        qtbot.mouseClick(view.next_button, Qt.LeftButton)
        old_buttons = tuple(
            button.rect().translated(button.mapToGlobal(button.rect().topLeft()))
            for button in (view.import_button, view.skip_button)
        )
        artifacts.capture("02-required-confirmation", view)
        qtbot.mouseClick(view.import_button, Qt.LeftButton)
        qtbot.waitUntil(lambda: entered[1].is_set() and progress.isVisible(), timeout=20000)
        activate(qtbot, progress)
        assert not view.isVisible() and window.progress is progress
        assert progress.completed.value() == 1
        assert "File 2 of 3" in progress.file_context.text()
        assert progress.selected_path.text() == str(paths[1])
        cancel_rect = progress.cancel_button.rect().translated(
            progress.cancel_button.mapToGlobal(progress.cancel_button.rect().topLeft())
        )
        assert not any(cancel_rect.intersects(rect) for rect in old_buttons)
        assert progress.body.hasFocus()
        for _ in range(4):
            qtbot.keyClick(QApplication.focusWidget(), Qt.Key_Return)
        assert not worker.cancel_event.is_set()
        qtbot.keyClick(progress.body, Qt.Key_Tab)
        assert progress.cancel_button.hasFocus()
        qtbot.keyClick(progress.cancel_button, Qt.Key_Tab, Qt.ShiftModifier)
        assert progress.body.hasFocus()
        artifacts.capture("03-automatic-next-file-compact", progress)
        release[1].set()
        qtbot.waitUntil(lambda: entered[2].is_set() and progress.completed.value() == 2, timeout=20000)
        # File 2 ran automatically. File 3 now needs explicit review again.
        workspace.set_import_preview_mode("always")
        release[2].set()
        qtbot.waitUntil(lambda: view.isVisible() and view.request.path == paths[2], timeout=15000)
        assert not progress.isVisible() and window.import_preview is view
        assert view.pages.currentWidget() is view.preview
        assert "File 3 of 3" in view.file_context.text()
        artifacts.capture("04-next-input-no-stale-progress", view)
        qtbot.mouseClick(view.skip_button, Qt.LeftButton)
        qtbot.waitUntil(lambda: skip_returned.is_set() and progress.isVisible(), timeout=10000)
        assert not view.isVisible() and "Skipping" in progress.phase.text()
        artifacts.capture("05-skip-compact", progress)
        finish_skip.set()
        qtbot.waitUntil(lambda: window.import_worker is None and bool(reports), timeout=20000)
        assert [row.split(" — ")[1] for row in reports[0]] == [
            "imported",
            "imported",
            "skipped",
        ]
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not isValid(worker) and not isValid(progress) and not isValid(view)
        assert sorted(destroyed) == [("progress", True), ("review", True), ("worker", True)]
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert len(store.source_ids()) == 2 and len(store.financial_accounts()) == 2
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        qtbot.waitUntil(lambda: not window.inventory_pending, timeout=15000)
        artifacts.capture("06-finished-workspace", window)
        assert gc.isenabled()
        gc.collect()
    finally:
        finish_window(qtbot, window, (*release, finish_skip))


@pytest.mark.parametrize("close", [False, True])
def test_cancel_or_close_after_confirmed_save_waits_for_worker_and_keeps_import(qtbot, tmp_path, monkeypatch, close):
    workspace, paths = occu_workspace(tmp_path)
    saved, release = Event(), Event()
    original = workspace.import_file

    def import_file(path, **kwargs):
        result = original(path, **kwargs)
        if path == paths[0]:
            saved.set()
            # Model a confirmed write completing before GUI outcome delivery.
            release.wait(10)
        return result

    monkeypatch.setattr(workspace, "import_file", import_file)
    window, reports = start_window(qtbot, workspace, monkeypatch)
    try:
        window.start_batch_import(paths)
        qtbot.waitUntil(lambda: window.import_preview is not None and window.import_preview.isVisible(), timeout=15000)
        view = window.import_preview
        create(qtbot, view, "Public savings", "savings")
        group(qtbot, view, 1)
        create(qtbot, view, "Public checking", "checking")
        qtbot.mouseClick(view.next_button, Qt.LeftButton)
        qtbot.mouseClick(view.import_button, Qt.LeftButton)
        qtbot.waitUntil(lambda: saved.is_set() and window.progress.isVisible(), timeout=15000)
        worker, progress = window.import_worker, window.progress
        if close:
            window.close()
        else:
            qtbot.mouseClick(progress.cancel_button, Qt.LeftButton)
        assert window.import_worker is worker and worker.isRunning()
        assert progress.isVisible() and not progress.cancel_button.isEnabled()
        assert "Cancelling" in progress.phase.text()
        assert not view.isVisible()
        release.set()
        qtbot.waitUntil(lambda: window.import_worker is None, timeout=15000)
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert len(store.source_ids()) == 1 and len(store.financial_accounts()) == 2
        if close:
            qtbot.waitUntil(lambda: not window.isVisible(), timeout=15000)
            assert not reports
        else:
            assert len(reports) == 1
            assert "imported" in reports[0][0]
            assert "not attempted" in reports[0][1]
    finally:
        finish_window(qtbot, window, (release,))


def test_fast_automatic_finish_and_failure_never_leave_a_stale_progress_dialog(qtbot, qapp, tmp_path, monkeypatch):
    workspace, paths = occu_workspace(tmp_path)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    window, reports = start_window(qtbot, workspace, monkeypatch)
    try:
        # Repeated completion/failure in one GUI process exercises queued cleanup
        # and reopening without depending on a slow decoder to expose races.
        for failure in (False, True, False):

            def import_files(selected, *, failure=failure, **kwargs):
                if failure:
                    raise RuntimeError("synthetic_start_failure")
                items = tuple(BatchFileResult(path, "already_imported") for path in selected)
                for index, item in enumerate(items, 1):
                    kwargs["progress"](index, item)
                return BatchImportResult(items, cancelled=False)

            monkeypatch.setattr(workspace, "import_files", import_files)
            window.start_batch_import(paths)
            worker, progress = window.import_worker, window.progress
            assert worker.wait(5000)  # Finish before any queued GUI handoff runs.
            qtbot.waitUntil(lambda: window.import_worker is None, timeout=15000)
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            assert not isValid(worker) and not isValid(progress)
            assert window._import_presentation is None and not window._import_presentation_timer.isActive()
            qtbot.waitUntil(lambda: not window.inventory_pending, timeout=15000)
            qapp.processEvents()
        assert len(reports) == 2 and len(warnings) == 1
        assert "synthetic_start_failure" in warnings[0]
        assert gc.isenabled()
        gc.collect()
    finally:
        finish_window(qtbot, window)


@pytest.mark.parametrize("next_review", [False, True])
def test_worker_can_finish_or_request_next_input_before_decision_handoff(
    qtbot, qapp, tmp_path, monkeypatch, next_review
):
    source = tmp_path / "source"
    source.mkdir()
    first, second = requests(source)
    profile = tmp_path / "workspace"
    profile.mkdir()
    workspace, _paths = occu_workspace(profile)
    second_requested = Event()

    def import_files(selected, **kwargs):
        kwargs["review_import"](selected[0], first.review)
        if next_review:
            second_requested.set()
            try:
                kwargs["review_import"](selected[1], second.review)
            except ImportCancelled:
                return BatchImportResult(
                    (BatchFileResult(selected[0], "skipped"), BatchFileResult(selected[1], "cancelled")),
                    cancelled=True,
                )
        return BatchImportResult(tuple(BatchFileResult(path, "skipped") for path in selected), cancelled=False)

    monkeypatch.setattr(workspace, "import_files", import_files)
    window, reports = start_window(qtbot, workspace, monkeypatch)
    try:
        window.start_batch_import((first.path, second.path))
        qtbot.waitUntil(lambda: window.import_preview is not None and window.import_preview.isVisible())
        view, worker, progress = window.import_preview, window.import_worker, window.progress
        qtbot.mouseClick(view.skip_button, Qt.LeftButton)
        # Leave the GUI timer pending while the worker either fully terminates
        # or emits the successor request; the stale Skip handoff must lose.
        if next_review:
            assert second_requested.wait(5)
            qtbot.waitUntil(lambda: view.isVisible() and view.request.path == second.path)
            qapp.processEvents()
            assert view.isVisible() and not progress.isVisible()
            assert view.request is window._import_review_request and not view.request.decided.is_set()
            qtbot.mouseClick(view.cancel_button, Qt.LeftButton)
        else:
            assert worker.wait(5000)
        qtbot.waitUntil(lambda: window.import_worker is None and bool(reports), timeout=15000)
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not isValid(worker) and not isValid(progress) and not isValid(view)
        assert window._import_presentation is None
    finally:
        finish_window(qtbot, window)

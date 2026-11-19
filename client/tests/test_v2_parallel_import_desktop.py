"""Parallel preparation preserves one native decision and ordered saved outcomes."""

import gc
import hashlib
from threading import Event, Lock

import pytest
from parsetrail.core.v2_prepared_import import PreparedImportSession
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_import import ImportCancelled
from PySide6.QtCore import QEvent, Qt, QThread, QTimer
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from .qt_journey_helpers import JourneyArtifacts, choose_combo
from .test_v2_import_account_review import group
from .test_v2_occu_batch_import import occu_workspace
from .test_v2_occu_batch_import_dialog import create
from .test_v2_unified_import_progress import finish_window, start_window


class PreparationGates:
    """Delay public sources without replacing actual decoding or prepared authority."""

    def __init__(self, monkeypatch, paths):
        self.entered = [Event() for _ in paths]
        self.release = [Event() for _ in paths]
        self.finished = [Event() for _ in paths]
        self.active = self.peak = 0
        lock = Lock()
        indexes = {hashlib.sha256(path.read_bytes()).digest(): index for index, path in enumerate(paths)}
        original = PreparedImportSession.__init__

        def prepare(session, source, **kwargs):
            index = indexes[hashlib.sha256(source).digest()]
            with lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            self.entered[index].set()
            try:
                while not self.release[index].wait(0.01):
                    if kwargs["cancelled"]():
                        raise ImportCancelled("cancelled")
                original(session, source, **kwargs)
            finally:
                with lock:
                    self.active -= 1
                self.finished[index].set()

        monkeypatch.setattr(PreparedImportSession, "__init__", prepare)

    def release_all(self):
        for gate in self.release:
            gate.set()


def four_workers(monkeypatch, workspace):
    original = workspace.import_files

    def run(paths, **kwargs):
        return original(paths, preparation_workers=4, **kwargs)

    monkeypatch.setattr(workspace, "import_files", run)


def setup_first_accounts(qtbot, view, *, automatic=True):
    create(qtbot, view, "Public primary savings", "savings")
    group(qtbot, view, 1)
    create(qtbot, view, "Public remarkable checking", "checking")
    if automatic:
        qtbot.mouseClick(view.abbreviated_matching, Qt.LeftButton)
        choose_combo(qtbot, view.preview_mode, "when_needed")
    qtbot.mouseClick(view.next_button, Qt.LeftButton)


@pytest.mark.parametrize("size", [(1050, 700), (1100, 650)])
def test_four_preparations_keep_one_first_use_review_and_learn_both_accounts(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts, size
):
    workspace, paths = occu_workspace(tmp_path, count=4, inactive_savings=True, active_savings_indexes=(2,))
    four_workers(monkeypatch, workspace)
    gates = PreparationGates(monkeypatch, paths)
    window, reports = start_window(qtbot, workspace, monkeypatch, size)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    ticks, destroyed = [], []
    heartbeat = QTimer(window)
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: ticks.append(True))
    heartbeat.start()
    try:
        window.start_batch_import(paths)
        worker, progress = window.import_worker, window.progress
        worker.destroyed.connect(lambda: destroyed.append(("worker", QThread.currentThread() is qapp.thread())))
        progress.destroyed.connect(lambda: destroyed.append(("progress", QThread.currentThread() is qapp.thread())))
        qtbot.waitUntil(lambda: all(gate.is_set() for gate in gates.entered), timeout=15000)
        qtbot.waitUntil(lambda: progress.isVisible() and len(ticks) >= 3)
        assert gates.peak == 4 and progress.completed.value() == 0
        assert "File 1 of 4" in progress.file_context.text()
        assert progress.selected_path.text() == str(paths[0])
        artifacts.capture("01-four-preparations-one-current-file", progress)
        gates.release[0].set()
        qtbot.waitUntil(lambda: window.import_preview is not None and window.import_preview.isVisible(), timeout=20000)
        view = window.import_preview
        view.destroyed.connect(lambda: destroyed.append(("review", QThread.currentThread() is qapp.thread())))
        assert view.request.path == paths[0] and len(view.review.accounts) == 0
        assert [item.row_count for item in view.review.groups] == [0, 1]
        assert not progress.isVisible()
        setup_first_accounts(qtbot, view)
        artifacts.capture("02-first-file-explicit-account-confirmation", view)
        gates.release_all()
        qtbot.mouseClick(view.import_button, Qt.LeftButton)
        qtbot.waitUntil(lambda: window.import_worker is None and bool(reports), timeout=30000)
        assert all("imported" in row for row in reports[0]) and len(reports[0]) == 4
        assert [row.split(" — ")[0] for row in reports[0]] == [path.name for path in paths]
        # All later files were prepared before either account existed, yet use
        # the newest saved identities/preferences without another setup request.
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            accounts = {account.product_type: account.id for account in store.financial_accounts()}
            assert set(accounts) == {"savings", "checking"} and len(store.source_ids()) == 4
            for outcome in reports[0]:
                assert "failed" not in outcome
            for path in paths:
                source = hashlib.sha256(path.read_bytes()).hexdigest()
                assert {
                    binding.source_identity: binding.ledger_account_id
                    for binding in store.source_account_bindings(source)
                } == {"1234": accounts["savings"], "5678": accounts["checking"]}
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not isValid(worker) and not isValid(progress) and not isValid(view)
        assert sorted(destroyed) == [("progress", True), ("review", True), ("worker", True)]
        assert all(gate.is_set() for gate in gates.finished) and gates.active == 0
        qtbot.waitUntil(lambda: not window.inventory_pending, timeout=20000)
        artifacts.capture("03-four-files-complete-no-extra-account-drafts", window)
        assert gc.isenabled()
        gc.collect()
    finally:
        heartbeat.stop()
        gates.release_all()
        finish_window(qtbot, window)


@pytest.mark.parametrize("close", [False, True])
@pytest.mark.parametrize("confirmed", [False, True])
def test_cancel_or_close_joins_ahead_preparation_and_preserves_only_confirmed_import(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts, close, confirmed
):
    from parsetrail.core import v2_workspace

    workspace, paths = occu_workspace(tmp_path, count=4)
    four_workers(monkeypatch, workspace)
    gates = PreparationGates(monkeypatch, paths)
    saved, deliver = Event(), Event()
    original = v2_workspace.commit_import_accounts

    def commit(*args, **kwargs):
        result = original(*args, **kwargs)
        saved.set()
        assert deliver.wait(15), "Timed out delivering a confirmed write"
        return result

    monkeypatch.setattr(v2_workspace, "commit_import_accounts", commit)
    window, reports = start_window(qtbot, workspace, monkeypatch)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    try:
        window.start_batch_import(paths)
        worker, progress = window.import_worker, window.progress
        qtbot.waitUntil(lambda: all(gate.is_set() for gate in gates.entered), timeout=15000)
        if confirmed:
            gates.release[0].set()
            qtbot.waitUntil(
                lambda: window.import_preview is not None and window.import_preview.isVisible(), timeout=20000
            )
            view = window.import_preview
            setup_first_accounts(qtbot, view)
            qtbot.mouseClick(view.import_button, Qt.LeftButton)
            qtbot.waitUntil(lambda: saved.is_set() and progress.isVisible(), timeout=20000)
        else:
            qtbot.waitUntil(progress.isVisible)
        assert worker.isRunning() and gates.active >= 3
        artifacts.capture("01-cancel-with-ahead-work-active", progress)
        if close:
            window.close()
        else:
            qtbot.mouseClick(progress.cancel_button, Qt.LeftButton)
        assert window.import_worker is worker and not progress.cancel_button.isEnabled()
        assert "Cancelling" in progress.phase.text()
        artifacts.capture("02-cancellation-waits-for-confirmed-outcome", progress)
        deliver.set()
        qtbot.waitUntil(lambda: window.import_worker is None, timeout=25000)
        assert gates.active == 0 and all(gate.is_set() for gate in gates.finished)
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert len(store.source_ids()) == int(confirmed)
            assert len(store.financial_accounts()) == 2 * int(confirmed)
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        if close:
            qtbot.waitUntil(lambda: not window.isVisible(), timeout=15000)
            assert not reports
        else:
            assert len(reports) == 1
            assert ("imported" if confirmed else "cancelled") in reports[0][0]
            assert all("not attempted" in row for row in reports[0][1:])
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not isValid(worker) and not isValid(progress)
        assert gc.isenabled()
        gc.collect()
    finally:
        deliver.set()
        gates.release_all()
        finish_window(qtbot, window)

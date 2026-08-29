from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from parsetrail.core import client, plugins
from parsetrail.core.client_manifest import ClientInstallerArtifact
from parsetrail.gui import send
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication


def _assert_event_loop_runs_while_worker_is_blocked(
    thread: QThread,
    worker_started: threading.Event,
    release_worker: threading.Event,
) -> None:
    app = QApplication.instance() or QApplication([])
    main_thread = threading.get_ident()
    callback_threads: list[int] = []
    timer = QTimer()
    timer.setSingleShot(True)
    timer.setInterval(0)

    def record_event_loop_callback() -> None:
        callback_threads.append(threading.get_ident())

    timer.timeout.connect(record_event_loop_callback)
    thread.start()
    finished = False
    try:
        assert worker_started.wait(timeout=2), "worker did not reach the synchronization barrier"
        assert thread.isRunning()
        timer.start()
        deadline = time.monotonic() + 2
        while not callback_threads and time.monotonic() < deadline:
            app.processEvents()
        assert callback_threads == [main_thread]
    finally:
        release_worker.set()
        finished = thread.wait(2000)
        timer.stop()
    app.processEvents()
    assert finished
    assert not thread.isRunning()


def test_installer_download_runs_off_qt_thread(monkeypatch, tmp_path: Path) -> None:
    main_thread = threading.get_ident()
    worker_threads: list[int] = []
    worker_started = threading.Event()
    release_worker = threading.Event()

    def download(_installer, **_kwargs):
        worker_threads.append(threading.get_ident())
        worker_started.set()
        assert release_worker.wait(timeout=2), "test did not release installer worker"
        return tmp_path / "installer.exe"

    monkeypatch.setattr(client, "download_client_installer", download)
    artifact = ClientInstallerArtifact(
        filename="parsetrail_9.0.0_win64_setup.exe",
        version="9.0.0",
        platform="win64",
        size=1,
        sha256="0" * 64,
    )
    thread = client.InstallerDownloadThread(artifact)

    _assert_event_loop_runs_while_worker_is_blocked(thread, worker_started, release_worker)
    assert worker_threads and worker_threads[0] != main_thread


def test_plugin_sync_runs_off_qt_thread(monkeypatch) -> None:
    main_thread = threading.get_ident()
    worker_threads: list[int] = []
    worker_started = threading.Event()
    release_worker = threading.Event()

    def sync(*_args, **_kwargs):
        worker_threads.append(threading.get_ident())
        worker_started.set()
        assert release_worker.wait(timeout=2), "test did not release plugin worker"
        return object()

    monkeypatch.setattr(plugins, "sync_plugins", sync)
    thread = plugins.PluginSyncThread(
        [],
        SimpleNamespace(),
        plugin_manager=SimpleNamespace(),
    )

    _assert_event_loop_runs_while_worker_is_blocked(thread, worker_started, release_worker)
    assert worker_threads and worker_threads[0] != main_thread


def test_statement_encryption_and_upload_run_off_qt_thread(monkeypatch, tmp_path: Path) -> None:
    main_thread = threading.get_ident()
    worker_threads: list[int] = []
    worker_started = threading.Event()
    release_worker = threading.Event()

    def encrypt(_path):
        worker_threads.append(threading.get_ident())
        worker_started.set()
        assert release_worker.wait(timeout=2), "test did not release statement worker"
        return b"encrypted", "key"

    class Response:
        def json(self):
            return {"message": "SUCCESS"}

        def close(self) -> None:
            pass

    def submit(*_args, **_kwargs):
        worker_threads.append(threading.get_ident())
        return Response()

    monkeypatch.setattr(send, "encrypt_file", encrypt)
    monkeypatch.setattr(send.api_client, "submit_statement", submit)
    thread = send.StatementSubmissionThread(
        tmp_path / "statement.pdf",
        {"institution": "Example Bank"},
        credentials=None,
    )

    _assert_event_loop_runs_while_worker_is_blocked(thread, worker_started, release_worker)
    assert worker_threads and all(worker != main_thread for worker in worker_threads)

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


def _run_with_event_loop(thread: QThread) -> int:
    app = QApplication.instance() or QApplication([])
    ticks = 0
    timer = QTimer()
    timer.setInterval(5)

    def tick() -> None:
        nonlocal ticks
        ticks += 1

    timer.timeout.connect(tick)
    timer.start()
    thread.start()
    deadline = time.monotonic() + 2
    while thread.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    thread.wait(1000)
    app.processEvents()
    timer.stop()
    assert not thread.isRunning()
    return ticks


def test_installer_download_runs_off_qt_thread(monkeypatch, tmp_path: Path) -> None:
    main_thread = threading.get_ident()
    worker_threads: list[int] = []

    def download(_installer, **_kwargs):
        worker_threads.append(threading.get_ident())
        time.sleep(0.08)
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

    assert _run_with_event_loop(thread) > 2
    assert worker_threads and worker_threads[0] != main_thread


def test_plugin_sync_runs_off_qt_thread(monkeypatch) -> None:
    main_thread = threading.get_ident()
    worker_threads: list[int] = []

    def sync(*_args, **_kwargs):
        worker_threads.append(threading.get_ident())
        time.sleep(0.08)
        return object()

    monkeypatch.setattr(plugins, "sync_plugins", sync)
    thread = plugins.PluginSyncThread(
        [],
        SimpleNamespace(),
        plugin_manager=SimpleNamespace(),
    )

    assert _run_with_event_loop(thread) > 2
    assert worker_threads and worker_threads[0] != main_thread


def test_statement_encryption_and_upload_run_off_qt_thread(monkeypatch, tmp_path: Path) -> None:
    main_thread = threading.get_ident()
    worker_threads: list[int] = []

    def encrypt(_path):
        worker_threads.append(threading.get_ident())
        time.sleep(0.04)
        return b"encrypted", "key"

    class Response:
        def json(self):
            return {"message": "SUCCESS"}

        def close(self) -> None:
            pass

    def submit(*_args, **_kwargs):
        worker_threads.append(threading.get_ident())
        time.sleep(0.04)
        return Response()

    monkeypatch.setattr(send, "encrypt_file", encrypt)
    monkeypatch.setattr(send.api_client, "submit_statement", submit)
    thread = send.StatementSubmissionThread(
        tmp_path / "statement.pdf",
        {"institution": "Example Bank"},
        credentials=None,
    )

    assert _run_with_event_loop(thread) > 2
    assert worker_threads and all(worker != main_thread for worker in worker_threads)

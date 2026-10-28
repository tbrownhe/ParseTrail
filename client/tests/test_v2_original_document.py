"""Exact ordinary originals, bounded private temporary files and safe default-app handoff."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from parsetrail.core import v2_original_document as storage
from parsetrail.core.v2_profile_store import SavedImport, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_two_date_card_lines import parse_two_date_card
from parsetrail.gui import v2_external_document as gui
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
from PySide6.QtCore import QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from devtools.parser_engine_pilot import test_two_date_card_lines as yamaha

from .test_v2_profile_store import CSV, CSV_DEFINITION


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # No automated test launches an external app or opens a modal warning.
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda _url: False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def saved():
    evidence = build_source_evidence(CSV, CSV_DEFINITION, suffix=".csv")
    return SavedImport(CSV, CSV_DEFINITION, evidence, ".csv")


@pytest.fixture
def profile(tmp_path, saved):
    path = tmp_path / "profile.db"
    with V2ProfileStore.create(path) as store:
        store.import_source(saved.source, saved.definition, saved.evidence, suffix=saved.suffix)
    return path


@pytest.fixture
def session(tmp_path, monkeypatch):
    session = storage.OriginalDocumentSession(tmp_path / "managed")
    monkeypatch.setattr(gui, "_session", lambda: session)
    yield session
    session.close()


def _wait(predicate, timeout=5000):
    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert predicate(), "Original-document operation did not finish"


@pytest.mark.parametrize("suffix", [".csv", ".pdf"])
def test_verified_bytes_and_suffix_are_published_privately_without_input_path(profile, saved, session, suffix):
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    source = storage.read_saved_original(profile, saved.evidence.source_sha256)
    if suffix == ".pdf":
        source = SavedImport(
            b"%PDF-synthetic", yamaha.DEFINITION, parse_two_date_card(yamaha.DEFINITION, yamaha.lines()), ".pdf"
        )
    path = session.materialize(source)
    assert path.read_bytes() == source.source
    assert path.suffix == suffix and path.name.startswith("original-")
    assert source.evidence.source_sha256 not in path.name
    assert path.parent == session.directory
    assert sorted(item.name for item in session.directory.iterdir()) == sorted((".lease", path.name))
    storage._private_directory(session.root)
    storage._private_directory(session.directory)
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("change", ["extension", "bytes", "empty", "oversized", "definition"])
def test_invalid_sources_never_publish(saved, session, change):
    updates = {
        "extension": {"suffix": ".exe"},
        "bytes": {"source": b"different bytes"},
        "empty": {"source": b""},
        "oversized": {"source": b"x" * (storage.MAX_SOURCE_BYTES + 1)},
        "definition": {"definition": b"different declaration"},
    }
    with pytest.raises(storage.OriginalDocumentError):
        session.materialize(replace(saved, **updates[change]))
    assert [path.name for path in session.directory.iterdir()] == [".lease"]


def test_atomic_publication_failure_and_session_limits_preserve_existing_files(saved, session, monkeypatch):
    first = session.materialize(saved)
    original_link = storage.os.link
    monkeypatch.setattr(
        storage.os, "link", lambda *_args: (_ for _ in ()).throw(OSError("synthetic publication failure"))
    )
    with pytest.raises(OSError, match="synthetic publication failure"):
        session.materialize(saved)
    assert first.read_bytes() == saved.source
    assert {path.name for path in session.directory.iterdir()} == {".lease", first.name}
    monkeypatch.setattr(storage.os, "link", original_link)
    monkeypatch.setattr(storage, "MAX_SESSION_FILES", 1)
    with pytest.raises(storage.OriginalDocumentError, match="limit"):
        session.materialize(saved)
    with pytest.raises(storage.OriginalDocumentError, match="session_owned"):
        session.discard(session.root / "unowned.csv")
    assert first.exists()


def test_age_and_exclusive_lease_protect_live_and_recent_sessions(saved, tmp_path):
    root = tmp_path / "managed"
    live = storage.OriginalDocumentSession(root)
    path = live.materialize(saved)
    old = time.time() - storage.STALE_AFTER_SECONDS - 60
    for item in live.directory.iterdir():
        os.utime(item, (old, old))
    os.utime(live.directory, (old, old))
    assert storage.collect_stale_originals(root) == 0
    assert path.read_bytes() == saved.source
    os.close(live._lease)  # Simulate a crashed process releasing its kernel lease.
    live._closed = True
    os.utime(path, None)
    assert storage.collect_stale_originals(root) == 0
    os.utime(path, (old, old))
    assert storage.collect_stale_originals(root) == 1
    assert not live.directory.exists()


def test_locked_cleanup_is_retained_and_retried_only_in_our_owned_session(saved, tmp_path, monkeypatch):
    session = storage.OriginalDocumentSession(tmp_path / "managed")
    path = session.materialize(saved)
    original_unlink = Path.unlink

    def locked(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError("synthetic external viewer lock")
        return original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    assert session.close() is False
    assert path.read_bytes() == saved.source
    monkeypatch.setattr(Path, "unlink", original_unlink)
    unknown = session.root / "unrelated-directory"
    unknown.mkdir()
    sentinel = unknown / "keep.txt"
    sentinel.write_text("unrelated")
    old = time.time() - storage.STALE_AFTER_SECONDS - 60
    for item in session.directory.iterdir():
        os.utime(item, (old, old))
    os.utime(session.directory, (old, old))
    assert storage.collect_stale_originals(session.root) == 1
    assert sentinel.read_text() == "unrelated"


def test_unfamiliar_session_contents_and_symlinks_are_never_swept(saved, tmp_path):
    session = storage.OriginalDocumentSession(tmp_path / "managed")
    path = session.materialize(saved)
    sentinel = session.directory / "not-created-by-this-feature.txt"
    sentinel.write_text("keep")
    assert session.close() is False
    assert sentinel.read_text() == "keep" and path.exists()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "linked-root"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return  # Native symlink creation is not available to every Windows test user.
    with pytest.raises(storage.OriginalDocumentError):
        storage.OriginalDocumentSession(link)
    assert not tuple(outside.iterdir())


def test_preexisting_nonprivate_root_is_refused_without_deleting_contents(tmp_path):
    root = tmp_path / "nonprivate"
    root.mkdir(mode=0o700)
    sentinel = root / "keep.txt"
    sentinel.write_text("unrelated")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        api = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        descriptor = ctypes.c_void_p()
        api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        api.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        assert api.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "D:P(A;OICI;FA;;;WD)", 1, ctypes.byref(descriptor), None
        )
        try:
            assert api.SetFileSecurityW(str(root), 4 | 0x80000000, descriptor)
        finally:
            kernel.LocalFree(descriptor)
    else:
        root.chmod(0o777)
    with pytest.raises(storage.OriginalDocumentError, match="not_private"):
        storage.OriginalDocumentSession(root)
    assert sentinel.read_text() == "unrelated"


@pytest.mark.skipif(os.name != "nt", reason="Native Windows sharing semantics")
def test_actual_windows_viewer_sharing_lock_defers_cleanup(saved, session):
    import ctypes
    from ctypes import wintypes

    path = session.materialize(saved)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        assert session.close() is False
        assert path.exists()
    finally:
        kernel.CloseHandle(handle)
    old = time.time() - storage.STALE_AFTER_SECONDS - 60
    for item in session.directory.iterdir():
        os.utime(item, (old, old))
    os.utime(session.directory, (old, old))
    assert storage.collect_stale_originals(session.root) == 1


def test_corrupted_profile_source_is_refused_before_materialization(profile, saved, session):
    with sqlite3.connect(profile) as connection:
        trigger = connection.execute("SELECT sql FROM sqlite_master WHERE name='immutable_Sources_update'").fetchone()[
            0
        ]
        connection.execute("DROP TRIGGER immutable_Sources_update")
        connection.execute("UPDATE Sources SET content=?", (b"corrupt",))
        connection.execute(trigger)
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="integrity"):
        storage.read_saved_original(profile, saved.evidence.source_sha256)
    assert [path.name for path in session.directory.iterdir()] == [".lease"]
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_default_app_handoff_is_gui_thread_exact_and_retained_for_session(profile, saved, session, monkeypatch):
    main_thread = threading.get_ident()
    launched = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda url: launched.append((threading.get_ident(), Path(url.toLocalFile()))) or True,
    )
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    action = gui.open_original_document(profile, saved.evidence.source_sha256)
    assert action.pending
    _wait(lambda: not action.pending)
    assert launched == [(main_thread, action.path)]
    assert action.path.read_bytes() == saved.source
    assert action.path.parent == session.directory
    assert action.status == "Sent to the default application."
    first = action.path
    second = gui.open_saved_original(saved)
    _wait(lambda: not second.pending)
    assert first.exists() and second.path.exists() and first != second.path
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_failed_launch_removes_copy_and_preview_offers_retry(saved, session, monkeypatch):
    monkeypatch.setattr("parsetrail.gui.v2_evidence_preview.open_saved_original", gui.open_saved_original)
    preview = V2EvidencePreview(saved)
    try:
        preview.original_button.click()
        _wait(lambda: not preview.original_open.pending)
        assert preview.original_open.error is not None
        assert preview.original_button.isEnabled()
        assert "Try again" in preview.original_status.text()
        assert [path.name for path in session.directory.iterdir()] == [".lease"]
        monkeypatch.setattr(QDesktopServices, "openUrl", lambda _url: True)
        preview.original_button.click()
        _wait(lambda: not preview.original_open.pending)
        assert preview.original_open.path.read_bytes() == saved.source
        assert "Sent to" in preview.original_status.text()
    finally:
        preview.close()


def test_cancelled_read_keeps_ui_responsive_and_never_launches(profile, saved, session, monkeypatch):
    original = gui.read_saved_original
    started, release = threading.Event(), threading.Event()
    launched = []

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(gui, "read_saved_original", delayed)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda _url: launched.append(True) or True)
    action = gui.open_original_document(profile, saved.evidence.source_sha256)
    try:
        _wait(started.is_set)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        _wait(lambda: bool(heartbeat))
        action.cancel()
        release.set()
        _wait(lambda: not action.pending)
        assert not launched and action.path is None
        assert [path.name for path in session.directory.iterdir()] == [".lease"]
    finally:
        release.set()
        _wait(lambda: not gui._ORIGINAL_READERS)


@pytest.mark.parametrize("finish", ["reject", "accept", "close", "hide"])
def test_dialog_finished_or_closed_cancels_original_but_temporary_hide_does_not(
    profile, saved, session, monkeypatch, finish
):
    original = gui.read_saved_original
    started, release = threading.Event(), threading.Event()
    launched = []

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(gui, "read_saved_original", delayed)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda _url: launched.append(True) or True)
    parent = QDialog()
    parent.show()
    action = gui.open_original_document(profile, saved.evidence.source_sha256, parent)
    try:
        _wait(started.is_set)
        getattr(parent, finish)()
        assert action.pending  # Closing a host never waits for the native reader.
        assert gui._ORIGINAL_READERS
        release.set()
        _wait(lambda: not action.pending)
        assert bool(launched) == (finish == "hide")
        if finish == "hide":
            assert action.path.read_bytes() == saved.source
        else:
            assert action.path is None
            assert [path.name for path in session.directory.iterdir()] == [".lease"]
    finally:
        release.set()
        parent.reject()
        _wait(lambda: not gui._ORIGINAL_READERS)


@pytest.mark.parametrize("phase", ["materializing", "queued_completion"])
def test_dialog_rejection_after_publication_prevents_dispatch_and_cleans_deferred_copy(
    saved, session, monkeypatch, phase
):
    original = session.materialize
    published, release = threading.Event(), threading.Event()
    paths, launched = [], []

    def delayed(snapshot):
        path = original(snapshot)
        paths.append(path)
        published.set()
        if phase == "materializing":
            assert release.wait(5)
        return path

    monkeypatch.setattr(session, "materialize", delayed)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda _url: launched.append(True) or True)
    parent = QDialog()
    action = gui.open_saved_original(saved, parent)
    try:
        # Avoid delivering the worker's GUI completion until after rejection.
        assert published.wait(5)
        if phase == "queued_completion":
            assert action._reader.wait(5000)
        assert paths[0].exists()
        parent.reject()
        assert paths[0].exists() and action.pending
        release.set()
        _wait(lambda: not action.pending)
        assert not launched and action.path is None
        assert not paths[0].exists()
    finally:
        release.set()
        parent.reject()
        _wait(lambda: not gui._ORIGINAL_READERS)


@pytest.mark.parametrize("event_loop", [False, True])
def test_process_shutdown_drains_original_read_without_launch(profile, saved, tmp_path, event_loop):
    script = textwrap.dedent(
        """
        import json,sys,time,threading
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QDesktopServices
        from parsetrail.gui import v2_external_document as gui
        from parsetrail.core.v2_original_document import OriginalDocumentSession
        app=QApplication([])
        profile,root,marker=map(Path,sys.argv[1:4]);source=sys.argv[4];use_loop=sys.argv[5]=='True'
        gui._SESSION=OriginalDocumentSession(root)
        original=gui.read_saved_original;started=threading.Event()
        def delayed(*args,**kwargs):
            started.set();time.sleep(.4)
            return original(*args,**kwargs)
        gui.read_saved_original=delayed
        def launch(_url):
            marker.write_text('unexpected launch');return True
        QDesktopServices.openUrl=launch
        action=gui.open_original_document(profile,source)
        if use_loop:
            def quit_when_started():
                if started.is_set():app.quit()
                else:QTimer.singleShot(5,quit_when_started)
            QTimer.singleShot(0,quit_when_started);app.exec()
        else:
            deadline=time.monotonic()+5
            while not started.is_set() and time.monotonic()<deadline:
                app.processEvents();time.sleep(.005)
            assert started.is_set()
        print(json.dumps({'started':started.is_set()}),flush=True)
        """
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "client/src"), str(root / "client")))
    environment["QT_QPA_PLATFORM"] = "offscreen"
    temporary_root, marker = tmp_path / "child-managed", tmp_path / "launched.txt"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(profile),
            str(temporary_root),
            str(marker),
            saved.evidence.source_sha256,
            str(event_loop),
        ],
        capture_output=True,
        text=True,
        env=environment,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"started": True}
    assert not marker.exists() and not tuple(temporary_root.iterdir())

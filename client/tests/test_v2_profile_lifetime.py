"""Profile-job captures are released by the GUI after delivery or detachment."""

from __future__ import annotations

import threading

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_profile_jobs import _JOBS, ProfileJobs, finish_profile_jobs
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget
from shiboken6 import delete, isValid


class _Probe:
    def __init__(self, label, released):
        self.label, self.released = label, released

    def __del__(self):
        self.released.append((self.label, threading.get_ident()))


class _Operation(_Probe):
    def __init__(self, released, started, release, *, failure=False):
        super().__init__("operation", released)
        self.started, self.release, self.failure = started, release, failure

    def __call__(self, _store, _cancelled):
        self.started.set()
        assert self.release.wait(5), "Synthetic job was not released"
        if self.failure:
            retained_in_frame = _Probe("error-frame", self.released)
            try:
                raise ValueError("synthetic cause")
            except ValueError as cause:
                assert retained_in_frame.label == "error-frame"
                raise RuntimeError("synthetic failure") from cause
        return _Probe("result", self.released)


@pytest.fixture(autouse=True)
def no_pending_jobs(qapp):
    assert qapp.thread() is not None
    yield
    finish_profile_jobs()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _submit(jobs, released, started, release, **kwargs):
    assert jobs.submit(
        _Probe("key", released),
        _Operation(released, started, release, failure=kwargs.pop("failure", False)),
        connection=False,
        **kwargs,
    )


def test_success_releases_captures_on_gui_after_delivery(qtbot, tmp_path):
    released, delivered = [], []
    started, release = threading.Event(), threading.Event()
    jobs = ProfileJobs(None, tmp_path / "synthetic.db")
    gui_thread = threading.get_ident()

    def completed(key, result):
        assert not released
        delivered.append((key.label, result.label, threading.get_ident()))

    jobs.completed.connect(completed)
    try:
        _submit(jobs, released, started, release)
        qtbot.waitUntil(started.is_set)
        release.set()
        qtbot.waitUntil(lambda: not _JOBS)
        assert delivered == [("key", "result", gui_thread)]
        assert sorted(released) == sorted((label, gui_thread) for label in ("operation", "key", "result"))
    finally:
        release.set()
        jobs.close()
        jobs.deleteLater()


def test_error_delivery_clears_chained_tracebacks_and_releases_frames_on_gui(qtbot, tmp_path):
    released, delivered = [], []
    started, release = threading.Event(), threading.Event()
    jobs = ProfileJobs(None, tmp_path / "synthetic.db")
    gui_thread = threading.get_ident()

    def failed(key, error):
        assert key.label == "key"
        assert type(error) is RuntimeError and error.args == ("synthetic failure",)
        assert type(error.__cause__) is ValueError
        assert error.__context__ is error.__cause__
        assert error.__cause__.args == ("synthetic cause",)
        assert error.__traceback__ is error.__cause__.__traceback__ is None
        delivered.append(threading.get_ident())

    jobs.failed.connect(failed)
    try:
        _submit(jobs, released, started, release, failure=True)
        qtbot.waitUntil(started.is_set)
        release.set()
        qtbot.waitUntil(lambda: not _JOBS)
        assert delivered == [gui_thread]
        assert sorted(released) == sorted((label, gui_thread) for label in ("operation", "key", "error-frame"))
    finally:
        release.set()
        jobs.close()
        jobs.deleteLater()


@pytest.mark.parametrize("write", [False, True])
def test_destroyed_controller_still_releases_outcome_on_gui(qtbot, tmp_path, write):
    released, delivered = [], []
    started, release = threading.Event(), threading.Event()
    jobs = ProfileJobs(None, tmp_path / "synthetic.db")
    jobs.completed.connect(lambda *_args: delivered.append(True))
    gui_thread = threading.get_ident()
    try:
        _submit(jobs, released, started, release, write=write)
        qtbot.waitUntil(started.is_set)
        job = jobs._job
        delete(jobs)
        assert job.isInterruptionRequested() is (not write)
        release.set()
        qtbot.waitUntil(lambda: not _JOBS)
        assert not delivered
        assert sorted(released) == sorted((label, gui_thread) for label in ("operation", "key", "result"))
    finally:
        release.set()


def test_completion_callback_can_destroy_host(qtbot, tmp_path):
    released, delivered = [], []
    started, release = threading.Event(), threading.Event()
    host = QWidget()
    jobs = ProfileJobs(host, tmp_path / "synthetic.db")

    def completed(_key, _result):
        delivered.append(True)
        delete(host)

    jobs.completed.connect(completed)
    try:
        _submit(jobs, released, started, release)
        qtbot.waitUntil(started.is_set)
        release.set()
        qtbot.waitUntil(lambda: not _JOBS)
        assert delivered == [True]
        assert not isValid(jobs)
        assert len(released) == 3
    finally:
        release.set()
        if isValid(host):
            host.deleteLater()


def test_shutdown_delivers_confirmed_write_before_releasing_captures(qtbot, tmp_path):
    released, delivered = [], []
    started, release = threading.Event(), threading.Event()
    jobs = ProfileJobs(None, tmp_path / "synthetic.db")
    gui_thread = threading.get_ident()

    def completed(key, result):
        assert not released
        delivered.append((key.label, result.label))

    jobs.completed.connect(completed)
    try:
        _submit(jobs, released, started, release, write=True)
        qtbot.waitUntil(started.is_set)
        release.set()
        finish_profile_jobs()
        assert delivered == [("key", "result")]
        assert not jobs.pending and not _JOBS
        assert sorted(released) == sorted((label, gui_thread) for label in ("operation", "key", "result"))
        # The already queued finished event must not deliver the outcome twice.
        QCoreApplication.processEvents()
        assert delivered == [("key", "result")]
    finally:
        release.set()
        jobs.close()
        jobs.deleteLater()


def test_shutdown_during_delivery_does_not_release_a_live_callback(qtbot, tmp_path):
    released, delivered = [], []
    started, release = threading.Event(), threading.Event()
    jobs = ProfileJobs(None, tmp_path / "synthetic.db")

    def completed(key, result):
        delivered.append((key.label, result.label))
        finish_profile_jobs()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not released

    jobs.completed.connect(completed)
    try:
        _submit(jobs, released, started, release, write=True)
        qtbot.waitUntil(started.is_set)
        release.set()
        qtbot.waitUntil(lambda: not _JOBS)
        assert delivered == [("key", "result")]
        assert len(released) == 3
    finally:
        release.set()
        jobs.close()
        jobs.deleteLater()


def test_coalescing_cancellation_and_confirmed_write_guards(qtbot, tmp_path):
    path = tmp_path / "synthetic.db"
    with V2ProfileStore.create(path):
        pass
    jobs = ProfileJobs(None, path)
    started, release = threading.Event(), threading.Event()
    delivered = []
    jobs.completed.connect(lambda key, result: delivered.append((key, result)))

    def operation(_store, _cancelled):
        started.set()
        assert release.wait(5)
        return "finished"

    try:
        assert jobs.submit("old", operation)
        qtbot.waitUntil(started.is_set)
        assert jobs.submit("superseded", lambda *_args: "wrong")
        assert jobs.submit("latest", lambda *_args: "current")
        release.set()
        qtbot.waitUntil(lambda: not jobs.pending and not _JOBS)
        assert delivered == [("latest", "current")]
        started.clear()
        release.clear()
        assert jobs.submit("cancelled", operation)
        qtbot.waitUntil(started.is_set)
        assert jobs.cancel_reads()
        release.set()
        qtbot.waitUntil(lambda: not jobs.pending and not _JOBS)
        assert delivered == [("latest", "current")]
        started.clear()
        release.clear()
        assert jobs.submit("confirmed", operation, write=True)
        qtbot.waitUntil(started.is_set)
        assert not jobs.cancel_reads()
        assert not jobs.close()
        assert not jobs.submit("replacement", lambda *_args: "wrong")
        release.set()
        qtbot.waitUntil(lambda: not jobs.pending and not _JOBS)
        assert delivered[-1] == ("confirmed", "finished")
        assert jobs.close()
    finally:
        release.set()
        jobs.close()
        jobs.deleteLater()

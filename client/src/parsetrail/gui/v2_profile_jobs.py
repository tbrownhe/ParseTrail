"""Coalesced profile jobs with connection ownership and safe Qt lifetimes."""

from __future__ import annotations

import atexit
import time
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal

from parsetrail.core.v2_profile_store import V2ProfileStore

_JOBS: set[QThread] = set()
_WRITE_LOCKS: dict[Path, Lock] = {}


def finish_profile_jobs():
    """Interrupt reads and join workers before Qt/interpreter teardown."""
    jobs = tuple(_JOBS)
    for job in jobs:
        if not job.write:
            job.requestInterruption()
    for job in jobs:
        while job.isRunning():
            job.wait(10)
            time.sleep(0.001)
        job.wait()
        _JOBS.discard(job)


atexit.register(finish_profile_jobs)


class _ProfileJob(QThread):
    def __init__(self, profile, generation, key, operation, write, connection=True):
        super().__init__()
        self.profile = profile
        self.generation, self.key = generation, key
        self.operation, self.write = operation, write
        self.connection = connection
        self.result = self.error = None
        self.completed = False

    def run(self):
        lock = _WRITE_LOCKS.setdefault(self.profile, Lock()) if self.write else None
        acquired = False
        try:
            if self.isInterruptionRequested():
                return
            if lock is not None:
                lock.acquire()
                acquired = True
            if self.connection:
                with V2ProfileStore.open(self.profile, read_only=not self.write) as store:
                    if not self.write:
                        store.connection.set_progress_handler(lambda: int(self.isInterruptionRequested()), 1000)
                    self.result = self.operation(store, self.isInterruptionRequested)
            else:
                # Restore, package activation and enumeration have their own
                # verified inputs. A damaged active profile must not prevent
                # recovery from an independent healthy backup.
                self.result = self.operation(None, self.isInterruptionRequested)
            self.completed = True
        except Exception as exc:
            self.error = exc
        finally:
            self.operation = None
            if acquired:
                lock.release()


class ProfileJobs(QObject):
    """One view's latest read or confirmed write; operations capture no widgets.

    ``completed(key, result)`` and ``failed(key, exception)`` run on the GUI thread.
    Callers capture immutable scope in ``key`` and primitive operation arguments.
    Writes cannot be superseded or cancelled after confirmation; close returns
    false until their actual outcome has been delivered. Separate controllers'
    writes are serialized per resolved profile path.
    """

    completed = Signal(object, object)
    failed = Signal(object, object)
    busy_changed = Signal(bool)

    def __init__(self, parent, profile: Path):
        super().__init__(parent)
        self.profile = Path(profile).resolve()
        self._generation = 0
        self._job = None
        self._requested = None
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start)
        self.destroyed.connect(self._detach)
        if parent is not None:
            parent.destroyed.connect(lambda: self._detach())
        app = QCoreApplication.instance()
        if app is not None and not app.property("parsetrail_profile_jobs_exit_hook"):
            app.setProperty("parsetrail_profile_jobs_exit_hook", True)
            app.aboutToQuit.connect(finish_profile_jobs)

    @property
    def pending(self):
        return self._job is not None or self._requested is not None or self._timer.isActive()

    @property
    def writing(self):
        return bool((self._job is not None and self._job.write) or (self._requested and self._requested[-1]))

    def submit(self, key, operation, *, write=False, delay=0, connection=True):
        if self._closed or self.writing:
            return False
        self._generation += 1
        self._requested = (self._generation, key, operation, connection, write)
        if self._job is not None:
            self._job.requestInterruption()
        self.busy_changed.emit(True)
        self._timer.start(delay)
        return True

    def _start(self):
        if self._closed or self._job is not None or self._requested is None:
            return
        generation, key, operation, connection, write = self._requested
        self._requested = None
        job = _ProfileJob(self.profile, generation, key, operation, write, connection)
        self._job = job
        _JOBS.add(job)
        # Capture the job independently: its controller can disappear while a
        # cooperative read is unwinding. The global set owns the worker lifetime.
        job.finished.connect(lambda: _JOBS.discard(job))
        job.finished.connect(self._finished)
        job.finished.connect(job.deleteLater)
        job.start()

    def _finished(self):
        job, self._job = self._job, None
        if job is None or self._closed:
            return
        if job.generation == self._generation:
            if job.error is not None:
                self.failed.emit(job.key, job.error)
            elif job.completed:
                self.completed.emit(job.key, job.result)
        if self._requested is not None:
            self._timer.start(0)
        self.busy_changed.emit(self.pending)

    def cancel_reads(self):
        if self.writing:
            return False
        self._generation += 1
        self._requested = None
        self._timer.stop()
        if self._job is not None:
            self._job.requestInterruption()
        return True

    def _detach(self, *_args):
        self._closed = True
        if self._job is not None and not self._job.write:
            self._job.requestInterruption()

    def close(self):
        if self.writing:
            return False
        self.cancel_reads()
        self._closed = True
        return True

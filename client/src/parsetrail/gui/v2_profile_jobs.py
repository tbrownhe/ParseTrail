"""Coalesced profile jobs with connection ownership and safe Qt lifetimes."""

from __future__ import annotations

import atexit
import time
import weakref
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, QTimer, Signal, Slot
from shiboken6 import isValid

from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_gui_lifetime import clear_exception_tracebacks

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
        job._finish()


atexit.register(finish_profile_jobs)


class _ProfileJob(QThread):
    def __init__(self, profile, generation, key, operation, write, connection=True, controller=None):
        super().__init__()
        self.profile = profile
        self.generation, self.key = generation, key
        self.operation, self.write = operation, write
        self.connection = connection
        self.result = self.error = None
        self.completed = False
        self._released = False
        self._controller_ref = weakref.ref(controller) if controller is not None else None

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
            if acquired:
                lock.release()

    @Slot()
    def _controller_destroyed(self):
        if not self.write:
            self.requestInterruption()

    @Slot()
    def _finish(self):
        """Deliver, then drop captures on the GUI thread, even without a view."""
        if self._released:
            return
        # finished can arrive before native thread-local teardown has completed.
        # Wait for run's stack to exit before releasing its captured objects.
        self.wait()
        # Delivery can enter a modal loop or request application shutdown. Claim
        # finalization first so a reentrant drain cannot release these objects
        # or delete this worker underneath its still-running delivery callback.
        self._released = True
        try:
            controller = self._controller_ref() if self._controller_ref is not None else None
            if controller is not None and isValid(controller):
                controller._finished(self)
        finally:
            if self.error is not None:
                clear_exception_tracebacks(self.error)
            self.operation = self.result = self.key = self.error = None
            self._controller_ref = None
            _JOBS.discard(self)
            self.deleteLater()


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
            parent.destroyed.connect(self._detach)
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
        job = _ProfileJob(self.profile, generation, key, operation, write, connection, self)
        self._job = job
        _JOBS.add(job)
        # The registry owns the worker until independent GUI-thread cleanup.
        # The weak controller reference allows delivery before cleanup without
        # retaining a destroyed view or depending on its signal connections.
        self.destroyed.connect(job._controller_destroyed)
        job.finished.connect(job._finish, Qt.QueuedConnection)
        job.start()

    def _finished(self, job):
        if not isValid(self) or self._job is not job:
            return
        self._job = None
        if self._closed:
            return
        if job.generation == self._generation:
            if job.error is not None:
                clear_exception_tracebacks(job.error)
                self.failed.emit(job.key, job.error)
            elif job.completed:
                self.completed.emit(job.key, job.result)
        # A completion callback may have destroyed the view and this controller.
        if not isValid(self) or self._closed:
            return
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

    @Slot()
    def _detach(self, *_args):
        self._closed = True
        self._requested = None
        if isValid(self._timer):
            self._timer.stop()
        if self._job is not None and not self._job.write:
            self._job.requestInterruption()

    def close(self):
        if self.writing:
            return False
        self.cancel_reads()
        self._closed = True
        return True

"""Run one local calculation at a time without transferring Qt or DB sessions."""

from collections.abc import Callable
from threading import Event

from loguru import logger
from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal, Slot

from parsetrail.core.analysis import AnalysisCancelled, check_cancelled

AnalysisWork = Callable[[Callable[[], bool]], object]


class _AnalysisThread(QThread):
    def __init__(self, work: AnalysisWork, parent: QObject):
        super().__init__(parent)
        self.work = work
        self.cancel_event = Event()
        self.value = None
        self.failed = False

    def run(self) -> None:
        try:
            check_cancelled(self.cancel_event.is_set)
            self.value = self.work(self.cancel_event.is_set)
            check_cancelled(self.cancel_event.is_set)
        except AnalysisCancelled:
            self.cancel_event.set()
            self.value = None
        except Exception:
            logger.exception("Local analysis failed")
            self.failed = True
            self.value = None


class LocalAnalysisJob(QObject):
    """Own thread lifetime and publish outcomes only after the worker has exited.

    Work captures immutable input and session factories, never widgets or open
    sessions. Cancellation also discards a result already awaiting GUI delivery.
    Normal window closing is deferred by the window until ``finished``; the quit
    hook is a final lifetime guard for programmatic application shutdown.
    """

    completed = Signal(object)
    failed = Signal()
    cancelled = Signal()
    finished = Signal()

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self._thread: _AnalysisThread | None = None
        QCoreApplication.instance().aboutToQuit.connect(self._shutdown)

    @property
    def busy(self) -> bool:
        # Remain busy until GUI delivery, even if native computation has ended.
        return self._thread is not None

    def start(self, work: AnalysisWork) -> None:
        if self.busy:
            raise RuntimeError("An analysis is already running.")
        self._thread = _AnalysisThread(work, self)
        self._thread.finished.connect(self._finish)
        self._thread.start()

    @Slot()
    def cancel(self) -> None:
        if self._thread is not None:
            self._thread.cancel_event.set()

    @Slot()
    def _finish(self) -> None:
        thread = self._thread
        if thread is None:
            return
        thread.wait()  # finished was emitted; wait for final native cleanup.
        self._thread = None
        was_cancelled = thread.cancel_event.is_set()
        value, failed = thread.value, thread.failed
        thread.value = None
        thread.deleteLater()
        if was_cancelled:
            self.cancelled.emit()
        elif failed:
            self.failed.emit()
        else:
            self.completed.emit(value)
        self.finished.emit()

    @Slot()
    def _shutdown(self) -> None:
        self.cancel()
        if self._thread is not None:
            # Never destroy a running QThread or terminate a scientific library
            # midway through native work. Normal GUI close remains asynchronous.
            self._thread.wait()

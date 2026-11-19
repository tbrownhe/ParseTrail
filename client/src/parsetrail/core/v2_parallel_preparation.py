"""Bounded, ordered ownership of independent source preparation operations.

Coordinator threads invoke the existing isolated decoder processes. A slot is
held until the ordered consumer releases its result; completed lookahead never
grows with the number of selected files. No GUI or database objects belong here.
"""

from __future__ import annotations

import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event

MAX_PREPARATION_WORKERS = 4
DEFAULT_PREPARATION_WORKERS = min(MAX_PREPARATION_WORKERS, os.cpu_count() or 1)


class PreparationCancelled(ValueError):
    """An ordered preparation operation was cancelled without a write."""


def preparation_workers(value):
    if type(value) is not int or not 1 <= value <= MAX_PREPARATION_WORKERS:
        raise ValueError("import_preparation_workers_invalid")
    return value


def detached_error(error):
    """Drop frames/chains that could otherwise retain source bytes or workers."""
    error.__traceback__ = None
    error.__context__ = None
    error.__cause__ = None
    return error


@dataclass(slots=True)
class _Outcome:
    value: object = None
    error: BaseException | None = None


class OrderedPreparation:
    """Deliver preparations in input order with at most ``workers`` live slots.

    ``prepare(item, *, cancelled)`` runs outside the consumer thread. ``dispose``
    owns every successful result, including unconsumed results after cancellation.
    One consumer uses ``with queue.take_next() as result`` for each input. No
    replacement slot is submitted until that context disposes its current result.
    """

    def __init__(self, items, prepare, *, dispose=None, workers=DEFAULT_PREPARATION_WORKERS, cancelled=None):
        self.workers = preparation_workers(workers)
        self._items = iter(items)
        self._prepare = prepare
        self._dispose = dispose or (lambda _value: None)
        self._external_cancelled = cancelled or (lambda: False)
        self._stopped = Event()
        self._pending = deque()
        self._executor = None
        self._taking = False
        self._closed = False

    def cancelled(self):
        return self._stopped.is_set() or self._external_cancelled()

    def _run(self, item):
        try:
            if self.cancelled():
                raise PreparationCancelled("cancelled")
            return _Outcome(value=self._prepare(item, cancelled=self.cancelled))
        except BaseException as error:
            return _Outcome(error=detached_error(error))

    def _submit(self):
        if self.cancelled():
            return
        try:
            item = next(self._items)
        except StopIteration:
            return
        self._pending.append(self._executor.submit(self._run, item))

    def __enter__(self):
        if self._executor is not None or self._closed:
            raise RuntimeError("preparation_queue_unavailable")
        self._executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="ParseTrailPrepare")
        try:
            for _ in range(self.workers):
                self._submit()
        except BaseException:
            self.close()
            raise
        return self

    @contextmanager
    def take_next(self):
        if self._executor is None or self._closed or self._taking:
            raise RuntimeError("preparation_queue_unavailable")
        if self.cancelled():
            raise PreparationCancelled("cancelled")
        if not self._pending:
            raise RuntimeError("preparation_queue_exhausted")
        self._taking = True
        future = self._pending[0]
        outcome = None
        try:
            while outcome is None:
                if self.cancelled():
                    raise PreparationCancelled("cancelled")
                try:
                    outcome = future.result(timeout=0.05)
                except TimeoutError:
                    continue
            if self.cancelled():
                raise PreparationCancelled("cancelled")
            if outcome.error is not None:
                raise outcome.error
            yield outcome.value
        finally:
            self._taking = False
            # A cancelled wait leaves ownership with close(), which joins and
            # disposes it only after its producer has actually terminated.
            if outcome is not None:
                self._pending.popleft()
                try:
                    if outcome.error is not None:
                        detached_error(outcome.error)
                        outcome.error = None
                    else:
                        self._dispose(outcome.value)
                finally:
                    outcome.value = None
                    self._submit()

    def close(self):
        if self._closed:
            return
        if self._taking:
            raise RuntimeError("preparation_consumer_active")
        self._closed = True
        self._stopped.set()
        executor, self._executor = self._executor, None
        if executor is None:
            return
        for future in self._pending:
            future.cancel()
        # Existing decoder cancellation joins/kills its actual subprocess before
        # prepare returns. Do not dispose a result concurrently with its producer.
        executor.shutdown(wait=True, cancel_futures=True)
        cleanup_error = None
        while self._pending:
            future = self._pending.popleft()
            if future.cancelled():
                continue
            outcome = future.result()
            try:
                if outcome.error is not None:
                    detached_error(outcome.error)
                    outcome.error = None
                else:
                    self._dispose(outcome.value)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = detached_error(error)
            finally:
                outcome.value = None
        self._prepare = self._dispose = self._external_cancelled = self._items = None
        if cleanup_error is not None:
            raise cleanup_error

    def __exit__(self, exception_type, _exception, _traceback):
        try:
            self.close()
        except BaseException:
            if exception_type is None:
                raise

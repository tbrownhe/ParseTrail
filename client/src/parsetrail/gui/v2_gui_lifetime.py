"""Explicit GUI-event-loop disposal and traceback-free error handoff."""

from __future__ import annotations

from builtins import BaseExceptionGroup

from PySide6.QtWidgets import QDialog
from shiboken6 import isValid


def exec_disposable(dialog: QDialog) -> int:
    """Run a one-shot modal, then dispose it in its owning Qt event loop.

    Use only where the caller needs the result code, not live dialog controls
    after completion. Reusable import queues and embedded views own a different
    lifecycle and must not use this helper.
    """
    try:
        return dialog.exec()
    finally:
        if isValid(dialog):
            dialog.deleteLater()


def clear_exception_tracebacks(error: BaseException | None) -> None:
    """Release retained frames on the GUI thread without changing error meaning.

    Call after a worker has finished, or in GUI error delivery. Cause/context
    links and exception-group contents stay intact; only traceback references
    are removed, including those in chained/grouped errors.
    """
    pending = [error] if error is not None else []
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        current.__traceback__ = None
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)

"""Cooperative cancellation shared by local analysis services and adapters."""

from collections.abc import Callable

CancellationCheck = Callable[[], bool] | None


class AnalysisCancelled(Exception):
    """The caller no longer needs this calculation's result."""


def check_cancelled(cancelled: CancellationCheck) -> None:
    if cancelled is not None and cancelled():
        raise AnalysisCancelled

"""Cooperative cancellation shared by local analysis services and adapters."""

from collections.abc import Callable

CancellationCheck = Callable[[], bool] | None


class AnalysisCancelled(Exception):
    """The caller no longer needs this calculation's result."""


class AnalysisInputError(ValueError):
    """An actionable, safe-to-display problem with local analysis inputs."""


def check_cancelled(cancelled: CancellationCheck) -> None:
    if cancelled is not None and cancelled():
        raise AnalysisCancelled

"""Format-independent parser candidate execution."""

from collections.abc import Callable, Sequence
from typing import TypeVar

ResultT = TypeVar("ResultT")


def first_successful_candidate(
    candidates: Sequence[str], operation: Callable[[str], ResultT], *, source: str
) -> ResultT:
    """Run matching parsers in order and return the first successful result."""
    if not candidates:
        raise ValueError(f"No parser candidates were provided for {source}")

    failures: list[str] = []
    for candidate in candidates:
        try:
            return operation(candidate)
        except Exception as exc:
            failures.append(f"{candidate}: {exc}")

    raise ValueError(f"Failed to parse {source}: {'; '.join(failures)}")

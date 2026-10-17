"""Finite year resolution for statement dates printed without a year."""

from __future__ import annotations

import re
from datetime import date, datetime

MONTH_DAY = re.compile(r"(?P<month>0[1-9]|1[0-2])/(?P<day>0[1-9]|[12][0-9]|3[01])\Z")
SLASH_MONTH_DAY = re.compile(r"(?P<month>0?[1-9]|1[0-2])/(?P<day>0?[1-9]|[12][0-9]|3[01])\Z")
MAX_PERIOD_DAYS = 366


class PartialDateError(ValueError):
    """The printed month/day cannot be resolved uniquely."""


def resolve_month_day(raw: str, start: date, end: date) -> date:
    """Choose the unique nearest calendar date within one period's width.

    A transaction date can precede its statement period. The caller separately
    checks a posting date's role and any stricter institution-specific window.
    """
    match = MONTH_DAY.fullmatch(raw) if isinstance(raw, str) else None
    if match is None:
        raise PartialDateError("invalid_month_day")
    start = start.date() if isinstance(start, datetime) else start
    end = end.date() if isinstance(end, datetime) else end
    if type(start) is not date or type(end) is not date or not start <= end:
        raise PartialDateError("invalid_period")
    width = (end - start).days
    if width > MAX_PERIOD_DAYS:
        raise PartialDateError("period_limit")
    month, day = int(match["month"]), int(match["day"])
    candidates = []
    for year in range(start.year - 1, end.year + 2):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        distance = max((start - candidate).days, (candidate - end).days, 0)
        if distance <= width:
            candidates.append((distance, candidate))
    if not candidates:
        raise PartialDateError("outside_period_window")
    best_distance = min(distance for distance, _ in candidates)
    best = [candidate for distance, candidate in candidates if distance == best_distance]
    if len(best) != 1:
        raise PartialDateError("ambiguous_year")
    return best[0]


def resolve_slash_month_day(raw: str, start: date, end: date) -> date:
    """Resolve a printed M/D or MM/DD token using the same finite year rule."""
    match = SLASH_MONTH_DAY.fullmatch(raw) if isinstance(raw, str) else None
    if match is None:
        raise PartialDateError("invalid_slash_month_day")
    normalized = f"{int(match['month']):02d}/{int(match['day']):02d}"
    return resolve_month_day(normalized, start, end)

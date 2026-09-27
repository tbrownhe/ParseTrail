"""Statement coverage and calendar freshness, independent of transactions and Qt."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from parsetrail.core import query
from parsetrail.core.orm import Accounts, Statements


class CoverageServiceError(RuntimeError):
    """The coverage snapshot could not be read or contains invalid ranges."""


@dataclass(frozen=True, order=True)
class DateInterval:
    """Inclusive calendar dates, matching imported statement boundaries."""

    start: date
    end: date

    def __post_init__(self):
        if self.end < self.start:
            raise ValueError("Coverage end must not precede its start.")


def merge_intervals(intervals: Iterable[DateInterval]) -> tuple[DateInterval, ...]:
    merged = []
    for interval in sorted(intervals):
        if merged and (interval.start - merged[-1].end).days <= 1:
            merged[-1] = DateInterval(merged[-1].start, max(merged[-1].end, interval.end))
        else:
            merged.append(interval)
    return tuple(merged)


def missing_intervals(intervals: Iterable[DateInterval], period: DateInterval) -> tuple[DateInterval, ...]:
    """Return every uncovered day range; no coverage is never zero spending."""
    cursor, last = period.start.toordinal(), period.end.toordinal()
    missing = []
    for interval in merge_intervals(intervals):
        start, end = interval.start.toordinal(), interval.end.toordinal()
        if end < cursor:
            continue
        if start > last:
            break
        if start > cursor:
            missing.append(DateInterval(date.fromordinal(cursor), date.fromordinal(start - 1)))
        cursor = max(cursor, end + 1)
        if cursor > last:
            break
    if cursor <= last:
        missing.append(DateInterval(date.fromordinal(cursor), period.end))
    return tuple(missing)


def _intersect(left: tuple[DateInterval, ...], right: tuple[DateInterval, ...]) -> tuple[DateInterval, ...]:
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        start, end = max(left[i].start, right[j].start), min(left[i].end, right[j].end)
        if start <= end:
            result.append(DateInterval(start, end))
        if left[i].end < right[j].end:
            i += 1
        else:
            j += 1
    return tuple(result)


@dataclass(frozen=True)
class StatementPeriod:
    statement_id: int
    interval: DateInterval
    imported_at: datetime


@dataclass(frozen=True)
class AccountFreshness:
    covered_through: date | None
    days_since_coverage: int | None
    latest_imported_at: datetime | None


@dataclass(frozen=True)
class AccountCoverage:
    account_id: int
    name: str
    currency: str
    statements: tuple[StatementPeriod, ...]
    intervals: tuple[DateInterval, ...] = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "intervals", merge_intervals(item.interval for item in self.statements))

    def missing(self, period: DateInterval) -> tuple[DateInterval, ...]:
        return missing_intervals(self.intervals, period)

    def freshness(self, as_of: date) -> AccountFreshness:
        # A future-dated statement cannot advance coverage beyond the reference
        # date. Import time is evidence of ingestion, not recent financial data.
        through = max((min(item.end, as_of) for item in self.intervals if item.start <= as_of), default=None)
        imported = max((item.imported_at for item in self.statements), default=None)
        return AccountFreshness(through, (as_of - through).days if through else None, imported)


@dataclass(frozen=True)
class MonthlyComparison:
    current: DateInterval
    previous: DateInterval


@dataclass(frozen=True)
class CoverageSnapshot:
    accounts: tuple[AccountCoverage, ...]

    def select(self, account_ids: Iterable[int]) -> tuple[AccountCoverage, ...]:
        selected = frozenset(account_ids)
        if not selected:
            raise ValueError("Select at least one account for coverage analysis.")
        if selected - {account.account_id for account in self.accounts}:
            raise ValueError("Selected accounts are missing from the coverage snapshot.")
        return tuple(account for account in self.accounts if account.account_id in selected)

    def common_intervals(self, account_ids: Iterable[int]) -> tuple[DateInterval, ...]:
        accounts = self.select(account_ids)
        common = accounts[0].intervals
        for account in accounts[1:]:
            common = _intersect(common, account.intervals)
        return common

    def latest_monthly_comparison(
        self, account_ids: Iterable[int], *, as_of: date, year_over_year: bool = False
    ) -> MonthlyComparison | None:
        """Latest two comparable closed calendar months fully covered on all accounts.

        Missing/empty selected accounts block comparison. The reference date
        excludes the current calendar month; it is not a historical import-time
        replay. Month-over-month requires adjacent months, never skips a gap.
        """
        common = self.common_intervals(account_ids)
        if not common:
            return None
        # Month numbers avoid day arithmetic at leap years and date boundaries.
        latest = min(as_of.year * 12 + as_of.month - 2, common[-1].end.year * 12 + common[-1].end.month - 1)
        earliest = common[0].start.year * 12 + common[0].start.month - 1
        offset = 12 if year_over_year else 1
        for number in range(latest, earliest + offset - 1, -1):
            current, previous = _month(number), _month(number - offset)
            if not missing_intervals(common, current) and not missing_intervals(common, previous):
                return MonthlyComparison(current, previous)
        return None


def _month(number: int) -> DateInterval:
    year, month = divmod(number, 12)
    month += 1
    return DateInterval(date(year, month, 1), date(year, month, monthrange(year, month)[1]))


class CoverageService:
    """Own read sessions and return immutable scalar evidence, including empty accounts."""

    def __init__(self, SessionFactory):
        self.SessionFactory = SessionFactory

    def snapshot(self) -> CoverageSnapshot:
        statement = (
            select(
                Accounts.AccountID,
                Accounts.AccountName,
                Accounts.CurrencyCode,
                Statements.StatementID,
                Statements.StartDate,
                Statements.EndDate,
                Statements.ImportedAt,
            )
            .outerjoin(Statements, Accounts.AccountID == Statements.AccountID)
            .order_by(Accounts.AccountName, Accounts.AccountID, Statements.StartDate, Statements.StatementID)
        )
        try:
            with self.SessionFactory() as session:
                rows = session.execute(statement).all()
            grouped = {}
            for account_id, name, currency, statement_id, start, end, imported in rows:
                if account_id not in grouped:
                    grouped[account_id] = (name, currency, [])
                if statement_id is not None:
                    grouped[account_id][2].append(StatementPeriod(statement_id, DateInterval(start, end), imported))
            return CoverageSnapshot(
                tuple(
                    AccountCoverage(account_id, name, currency, tuple(periods))
                    for account_id, (name, currency, periods) in grouped.items()
                )
            )
        except (SQLAlchemyError, ValueError) as exc:
            raise CoverageServiceError("Could not read statement coverage.") from exc

    def grid_ranges(self, months: int = 60) -> tuple[tuple[str, tuple[DateInterval, ...]], ...]:
        """Preserve the existing grid's start-date filter and three-month padding.

        Analytics must use the full snapshot: a display window is not a complete
        history and the legacy grid omits accounts without matching statements.
        """
        if months < 1:
            raise ValueError("Months must be positive.")
        try:
            with self.SessionFactory() as session:
                rows, _ = query.statement_date_ranges(session, months=months + 3)
            grouped = {}
            for name, start, end in rows:
                grouped.setdefault(name, []).append(DateInterval(start, end))
            return tuple((name, merge_intervals(intervals)) for name, intervals in sorted(grouped.items()))
        except (SQLAlchemyError, ValueError) as exc:
            raise CoverageServiceError("Could not read statement coverage for the grid.") from exc

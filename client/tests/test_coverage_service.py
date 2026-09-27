import subprocess
import sys
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta, timezone
from random import Random

import pytest
from parsetrail.core.coverage import (
    AccountCoverage,
    CoverageService,
    CoverageServiceError,
    CoverageSnapshot,
    DateInterval,
    StatementPeriod,
    merge_intervals,
    missing_intervals,
)
from sqlalchemy.exc import OperationalError


def span(start, end):
    return DateInterval(date.fromisoformat(start), date.fromisoformat(end))


IMPORTED = datetime(2026, 9, 26, tzinfo=timezone.utc)


def account(account_id, *intervals):
    return AccountCoverage(
        account_id,
        f"Synthetic {account_id}",
        "USD",
        tuple(StatementPeriod(i, interval, IMPORTED) for i, interval in enumerate(intervals)),
    )


def test_merge_overlaps_duplicates_nested_and_adjacent_ranges_without_filling_gaps():
    ranges = [
        span("2026-08-05", "2026-08-20"),
        span("2026-08-01", "2026-08-10"),
        span("2026-08-21", "2026-08-25"),
        span("2026-08-05", "2026-08-20"),
        span("2026-08-27", "2026-08-31"),
    ]
    assert merge_intervals(reversed(ranges)) == (
        span("2026-08-01", "2026-08-25"),
        span("2026-08-27", "2026-08-31"),
    )
    assert missing_intervals(ranges, span("2026-07-31", "2026-09-01")) == (
        span("2026-07-31", "2026-07-31"),
        span("2026-08-26", "2026-08-26"),
        span("2026-09-01", "2026-09-01"),
    )


def test_interval_algebra_agrees_with_day_sets_on_random_small_calendars():
    random = Random(428)
    start = date(2024, 2, 1)
    period = DateInterval(start, start + timedelta(days=59))
    for _ in range(100):
        ranges, days = [], set()
        for _ in range(random.randrange(15)):
            left, right = sorted([random.randrange(-10, 70), random.randrange(-10, 70)])
            ranges.append(DateInterval(start + timedelta(days=left), start + timedelta(days=right)))
            days.update(range(left, right + 1))
        missing = missing_intervals(ranges, period)
        missing_days = {
            day for interval in missing for day in range((interval.start - start).days, (interval.end - start).days + 1)
        }
        assert missing_days == set(range(60)) - days
        merged = merge_intervals(ranges)
        assert all((right.start - left.end).days > 1 for left, right in zip(merged, merged[1:], strict=False))


def test_empty_invalid_and_date_extremes():
    entire = DateInterval(date.min, date.max)
    assert missing_intervals([], entire) == (entire,)
    assert missing_intervals([entire], entire) == ()
    assert merge_intervals([entire, entire]) == (entire,)
    with pytest.raises(ValueError, match="precede"):
        DateInterval(date(2026, 8, 2), date(2026, 8, 1))


def test_fresh_import_does_not_make_old_history_current_or_fill_holes():
    item = account(1, span("2026-07-01", "2026-07-31"), span("2026-08-02", "2026-08-31"))
    freshness = item.freshness(date(2026, 9, 26))
    assert freshness.covered_through == date(2026, 8, 31)
    assert freshness.days_since_coverage == 26
    assert freshness.latest_imported_at == IMPORTED
    assert item.missing(span("2026-07-01", "2026-08-31")) == (span("2026-08-01", "2026-08-01"),)
    empty = account(2).freshness(date(2026, 9, 26))
    assert empty.covered_through is empty.days_since_coverage is empty.latest_imported_at is None


def test_future_dates_do_not_produce_negative_age_or_assert_current_coverage():
    future = account(1, span("2026-10-01", "2026-10-31"))
    assert future.freshness(date(2026, 9, 26)).covered_through is None
    crossing = account(1, span("2026-09-01", "2026-09-30"))
    assert crossing.freshness(date(2026, 9, 26)).days_since_coverage == 0


def test_comparison_uses_all_selected_accounts_and_reports_different_cutoffs():
    checking = account(1, span("2026-01-01", "2026-08-31"))
    card = account(2, span("2026-01-01", "2026-07-31"))
    snapshot = CoverageSnapshot((checking, card, account(3)))
    pair = snapshot.latest_monthly_comparison([1, 2], as_of=date(2026, 9, 26))
    assert pair.current == span("2026-07-01", "2026-07-31")
    assert pair.previous == span("2026-06-01", "2026-06-30")
    assert snapshot.latest_monthly_comparison([1], as_of=date(2026, 9, 26)).current.end == date(2026, 8, 31)
    assert snapshot.latest_monthly_comparison([1, 3], as_of=date(2026, 9, 26)) is None
    assert checking.freshness(date(2026, 9, 26)).days_since_coverage == 26
    assert card.freshness(date(2026, 9, 26)).days_since_coverage == 57


@pytest.mark.parametrize("ids", [[], [99], [1, 99]])
def test_empty_or_unknown_selection_never_claims_complete_coverage(ids):
    with pytest.raises(ValueError, match="Select|missing"):
        CoverageSnapshot((account(1),)).latest_monthly_comparison(ids, as_of=date(2026, 9, 26))


def test_latest_pair_never_skips_a_gap_and_partial_month_does_not_qualify():
    snapshot = CoverageSnapshot(
        (
            account(
                1,
                span("2026-01-01", "2026-02-28"),
                span("2026-03-02", "2026-04-30"),
            ),
        )
    )
    pair = snapshot.latest_monthly_comparison([1], as_of=date(2026, 5, 1))
    assert pair.current == span("2026-02-01", "2026-02-28")
    assert pair.previous == span("2026-01-01", "2026-01-31")
    assert snapshot.latest_monthly_comparison([1], as_of=date(2026, 2, 28)) is None


def test_closed_months_leap_year_year_boundary_and_year_over_year():
    snapshot = CoverageSnapshot((account(1, span("2023-01-01", "2024-03-31")),))
    pair = snapshot.latest_monthly_comparison([1], as_of=date(2024, 3, 31), year_over_year=True)
    assert pair.current == span("2024-02-01", "2024-02-29")
    assert pair.previous == span("2023-02-01", "2023-02-28")
    pair = snapshot.latest_monthly_comparison([1], as_of=date(2024, 2, 1))
    assert pair.current == span("2024-01-01", "2024-01-31")
    assert pair.previous == span("2023-12-01", "2023-12-31")
    short = CoverageSnapshot((account(1, span("2026-01-01", "2026-08-31")),))
    assert short.latest_monthly_comparison([1], as_of=date(2026, 9, 26), year_over_year=True) is None


def test_intersection_preserves_single_day_and_disjoint_ranges():
    snapshot = CoverageSnapshot(
        (
            account(1, span("2026-01-01", "2026-01-10"), span("2026-01-20", "2026-01-30")),
            account(2, span("2026-01-10", "2026-01-20")),
        )
    )
    assert snapshot.common_intervals([2, 1, 1]) == (
        span("2026-01-10", "2026-01-10"),
        span("2026-01-20", "2026-01-20"),
    )


def test_service_reads_statement_evidence_in_its_own_session_and_includes_empty_accounts(tmp_path):
    from parsetrail.core import orm
    from parsetrail.core.migrate import upgrade_db

    database = tmp_path / "coverage.db"
    upgrade_db(database)
    Session = orm.create_database(database)
    with Session.begin() as session:
        session.add(orm.AccountTypes(AccountTypeID=1, AccountType="Checking", AssetType="Asset"))
        session.add_all(
            [
                orm.Accounts(AccountID=1, AccountName="Covered", AccountTypeID=1),
                orm.Accounts(AccountID=2, AccountName="Empty", AccountTypeID=1),
            ]
        )
        session.add(
            orm.Plugins(
                PluginID=1,
                PluginName="fixture",
                Version="1",
                Suffix=".csv",
                Company="Example",
                StatementType="Checking",
            )
        )
        for i, (start, end) in enumerate([("2020-01-01", "2020-01-31"), ("2026-07-01", "2026-08-31")], 1):
            session.add(
                orm.Statements(
                    StatementID=i,
                    PluginID=1,
                    AccountID=1,
                    ImportedAt=IMPORTED,
                    StartDate=date.fromisoformat(start),
                    EndDate=date.fromisoformat(end),
                    StartBalanceMinor=0,
                    EndBalanceMinor=0,
                    TransactionCount=0,
                    Filename=f"synthetic-{i}.csv",
                    ContentHashAlgorithm="sha256",
                    ContentHash=str(i) * 64,
                )
            )
        # A transaction outside the imported statement dates does not fill coverage.
        session.add(
            orm.Transactions(
                AccountID=1,
                PostingDate=date(2026, 9, 26),
                AmountMinor=-1000,
                BalanceMinor=0,
                Description="Synthetic manual entry",
                Fingerprint="a" * 64,
                FingerprintVersion=1,
            )
        )
    lifecycle = []

    @contextmanager
    def tracked():
        with Session() as session:
            lifecycle.append("open")
            yield session
        lifecycle.append("closed")

    try:
        snapshot = CoverageService(tracked).snapshot()
        assert lifecycle == ["open", "closed"]
        assert [item.account_id for item in snapshot.accounts] == [1, 2]
        covered, empty = snapshot.accounts
        assert covered.intervals[0] == span("2020-01-01", "2020-01-31")
        assert [item.statement_id for item in covered.statements] == [1, 2]
        assert covered.freshness(date(2026, 9, 26)).covered_through == date(2026, 8, 31)
        assert empty.intervals == ()
        with Session() as session:
            assert session.query(orm.Statements).count() == 2
            assert session.query(orm.Transactions).count() == 1
    finally:
        Session.kw["bind"].dispose()


def test_service_query_failure_is_distinct_from_empty_coverage():
    @contextmanager
    def broken():
        raise OperationalError("synthetic", {}, Exception("unavailable"))
        yield

    with pytest.raises(CoverageServiceError):
        CoverageService(broken).snapshot()
    with pytest.raises(CoverageServiceError):
        CoverageService(broken).grid_ranges()


def test_existing_grid_adapter_preserves_padding_sorting_merging_and_datetime_bounds(monkeypatch):
    from parsetrail.core import query
    from parsetrail.gui.statements import get_account_coverage

    months_used = []
    rows = [
        ("Second", date(2026, 8, 1), date(2026, 8, 31)),
        ("First", date(2026, 7, 1), date(2026, 7, 31)),
        ("First", date(2026, 8, 1), date(2026, 8, 10)),
    ]

    def ranges(_session, months):
        months_used.append(months)
        return rows, ["AccountName", "StartDate", "EndDate"]

    monkeypatch.setattr(query, "statement_date_ranges", ranges)
    accounts, start, end = get_account_coverage(nullcontext, months=12)
    assert months_used == [15]
    assert accounts == [
        {"name": "First", "intervals": [(datetime(2026, 7, 1), datetime(2026, 8, 10))]},
        {"name": "Second", "intervals": [(datetime(2026, 8, 1), datetime(2026, 8, 31))]},
    ]
    assert (start, end) == (datetime(2026, 7, 1), datetime(2026, 8, 31))
    rows.clear()
    assert get_account_coverage(nullcontext) == ([], None, None)


def test_service_imports_without_qt():
    script = """
import sys
import parsetrail.core.coverage
assert not any(name.startswith('PySide6') or name.startswith('parsetrail.gui') for name in sys.modules)
print('headless coverage ok')
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr

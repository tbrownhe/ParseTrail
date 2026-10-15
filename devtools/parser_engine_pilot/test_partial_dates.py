"""Partial dates must resolve predictably or refuse the source."""

from datetime import date

import pytest

from devtools.parser_engine_pilot.partial_dates import PartialDateError, resolve_month_day


def test_rollover_and_just_before_period() -> None:
    assert resolve_month_day("12/31", date(2026, 1, 1), date(2026, 1, 31)) == date(2025, 12, 31)
    assert resolve_month_day("01/03", date(2025, 12, 4), date(2026, 1, 5)) == date(2026, 1, 3)


@pytest.mark.parametrize("raw", ["1/03", "01/03 junk", "02/30", "00/12", "12/00", "not-a-date"])
def test_refuses_invalid_date(raw: str) -> None:
    with pytest.raises(PartialDateError):
        resolve_month_day(raw, date(2025, 12, 1), date(2026, 1, 5))


def test_refuses_unrelated_or_ambiguous_date() -> None:
    with pytest.raises(PartialDateError, match="outside_period_window"):
        resolve_month_day("08/01", date(2026, 1, 1), date(2026, 1, 31))
    with pytest.raises(PartialDateError, match="ambiguous_year"):
        resolve_month_day("01/01", date(2026, 1, 1), date(2027, 1, 1))

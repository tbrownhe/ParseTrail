"""Finite nearby-date candidates preserve every source occurrence and edge."""

from dataclasses import replace
from itertools import combinations, islice
from random import Random

import pytest
from parsetrail.core.v2_source_overlap import (
    NearbySourceIndex,
    SourceOverlapRow,
    nearby_source_pair,
    nearby_source_reason,
    pairwise_source_group,
)


def _row(key, source, day="2026-01-01", **changes):
    return replace(
        SourceOverlapRow(
            key, source, "cash", "Checking", day, "posting_date", "observed", -400, "Coffee", (), 0, False
        ),
        **changes,
    )


def test_three_calendar_days_across_years_and_roles_never_assert_identity():
    first = _row("a", "one", "2025-12-30")
    revised = _row("b", "two", "2026-01-02", date_role="activity_date", description="Revised merchant text")
    assert nearby_source_pair(first, revised)
    assert nearby_source_reason(first, revised) == "Source dates 3 day(s) apart; source date roles differ"
    assert not nearby_source_pair(first, replace(revised, source_date="2026-01-03"))
    assert nearby_source_reason(first, replace(revised, source_date="2026-01-03")) is None
    assert nearby_source_reason(first, _row("c", "three", "2025-12-30")) == "Same source date"
    for changed in (
        replace(revised, source_sha256="one"),
        replace(revised, account_id="other"),
        replace(revised, amount_minor=-401),
        replace(revised, amount_minor=400),
        replace(revised, amount_minor=-400.0),
        replace(revised, date_role="statement_period_end"),
    ):
        assert not nearby_source_pair(first, changed)
    assert not nearby_source_pair(replace(first, amount_minor=0), replace(revised, amount_minor=0))


def test_nontransitive_groups_and_alias_only_outsider_neighbors_remain_visible():
    first = _row("a", "one", "2026-01-01")
    root = _row("b", "two", "2026-01-03")
    later = _row("c", "three", "2026-01-05")
    outsider = _row("d", "four", "2025-12-30")
    assert pairwise_source_group((first, root))
    assert nearby_source_pair(root, later) and not pairwise_source_group((first, root, later))
    assert not pairwise_source_group((first, replace(root, source_sha256="one")))
    index = NearbySourceIndex((first, root, later, outsider))
    assert set(index.pairs()) == {("a", "b"), ("b", "c"), ("a", "d")}
    # A may support B, but its edge to D must still reach the posting guard.
    assert index.neighbors("d") == ("a",) and "d" not in index.neighbors("b")
    assert index.count_pairs() == 3


def test_index_counts_and_full_neighbors_match_independent_pair_oracle():
    random = Random(814)
    rows = tuple(
        _row(
            f"row-{number:03}",
            f"source-{random.randrange(5)}",
            f"2026-01-{random.randrange(1, 13):02}",
            account_id=f"account-{random.randrange(2)}",
            amount_minor=random.choice((-400, -500, 400)),
            date_role=random.choice(("posting_date", "activity_date")),
        )
        for number in range(90)
    )
    expected = {
        tuple(sorted((left.row_id, right.row_id)))
        for left, right in combinations(rows, 2)
        if left.source_sha256 != right.source_sha256
        and left.account_id == right.account_id
        and left.amount_minor == right.amount_minor
        and abs(int(left.source_date[-2:]) - int(right.source_date[-2:])) <= 3
    }
    index = NearbySourceIndex(reversed(rows))
    assert set(index.pairs()) == expected
    assert index.count_pairs() == len(expected)
    assert tuple(index.pairs()) == tuple(NearbySourceIndex(rows).pairs())
    for row in rows:
        expected_neighbors = {other for pair in expected if row.row_id in pair for other in pair if other != row.row_id}
        assert set(index.neighbors(row.row_id)) == expected_neighbors
    for source in {row.source_sha256 for row in rows} | {"missing"}:
        selected = {row.row_id for row in rows if row.source_sha256 == source}
        expected_selected = {pair for pair in expected if set(pair) & selected}
        assert set(index.pairs(source_sha256=source)) == expected_selected
        assert index.count_pairs(source_sha256=source) == len(expected_selected)


def test_large_equal_cohort_counts_without_materializing_pair_list_or_display_cap():
    rows = tuple(_row(f"row-{number:05}", f"source-{number}") for number in range(3000))
    index = NearbySourceIndex(rows)
    assert index.count_pairs() == 4_498_500
    assert index.count_pairs(source_sha256="source-2999") == 2999
    assert len(index.neighbors("row-02999")) == 2999
    assert len(tuple(islice(index.pairs(), 2000))) == 2000


def test_equal_occurrences_within_one_source_are_not_collapsed():
    rows = (_row("a", "one"), _row("b", "one"), _row("c", "two"), _row("d", "two", "2026-01-04"))
    index = NearbySourceIndex(rows)
    assert set(index.pairs()) == {("a", "c"), ("a", "d"), ("b", "c"), ("b", "d")}
    assert index.count_pairs() == index.count_pairs(source_sha256="one") == 4
    assert not pairwise_source_group(rows)


def test_invalid_dates_and_duplicate_ids_refuse_while_nonactivity_date_roles_stay_out():
    with pytest.raises(ValueError):
        NearbySourceIndex((_row("bad", "one", "2026-02-30"),))
    with pytest.raises(ValueError, match="date_invalid"):
        NearbySourceIndex((_row("bad", "one", "20260101"),))
    with pytest.raises(ValueError, match="duplicate_row"):
        NearbySourceIndex((_row("a", "one"), _row("a", "two")))
    index = NearbySourceIndex((_row("a", "one"), _row("b", "two", date_role="statement_period_end")))
    assert index.count_pairs() == 0 and index.neighbors("b") == ()
    unknown = _row("unknown", "three", None, date_provenance="unknown")
    assert not nearby_source_pair(_row("a", "one"), unknown)
    index = NearbySourceIndex((_row("a", "one"), unknown))
    assert index.count_pairs() == 0 and index.neighbors("unknown") == ()

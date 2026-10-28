"""Neighbor traversal excludes same-source cohorts before inspecting their rows."""

from dataclasses import replace
from datetime import date, timedelta

import pytest
from parsetrail.core.v2_source_overlap import NearbySourceIndex, SourceOverlapRow, nearby_source_pair


def _row(number, *, source="a", day=0, amount=-100, account="cash"):
    return SourceOverlapRow(
        f"row-{number:05}",
        source,
        account,
        account,
        (date(2026, 1, 10) + timedelta(days=day)).isoformat(),
        "posting_date",
        "observed",
        amount,
        "Synthetic movement",
        (),
        0,
        False,
    )


def test_neighbors_match_direct_policy_and_exact_order_with_ties_and_date_boundaries():
    rows = tuple(_row(index, source="abc"[index % 3], day=index % 11 - 5) for index in range(80))
    rows += (
        _row(100, account="other"),
        _row(101, amount=100),
        replace(_row(102), source_date=None, date_provenance="unknown"),
    )
    index = NearbySourceIndex(reversed(rows))
    for row in rows:
        expected = sorted(
            (other for other in rows if nearby_source_pair(row, other)),
            key=lambda other: (other.source_date, other.row_id),
        )
        assert index.neighbors(row.row_id) == tuple(other.row_id for other in expected)
    assert set(index.pairs()) == {
        tuple(sorted((row.row_id, other.row_id))) for row in rows for other in rows if nearby_source_pair(row, other)
    }
    assert index.count_pairs() == len(set(index.pairs()))


class _CountingCohort:
    def __init__(self, items):
        self.items = items
        self.visits = 0

    def __getitem__(self, position):
        assert type(position) is int, "Date windows must not be copied eagerly"
        self.visits += 1
        return self.items[position]


def test_large_own_source_run_is_skipped_without_visiting_each_row():
    rows = tuple(_row(index) for index in range(10_000)) + (_row(10_001, source="b"),)
    index = NearbySourceIndex(rows)

    cohort = _CountingCohort(index._cohorts["cash", -100])
    index._cohorts["cash", -100] = cohort
    for row in rows[:100]:
        assert index.neighbors(row.row_id) == ("row-10001",)
    assert cohort.visits <= 200


def test_duplicate_ids_are_still_refused_and_same_source_only_has_no_neighbors():
    row = _row(1)
    with pytest.raises(ValueError, match="source_overlap_duplicate_row"):
        NearbySourceIndex((row, row))
    index = NearbySourceIndex(tuple(_row(number) for number in range(100)))
    assert all(index.neighbors(row_id) == () for row_id in index.rows)
    assert index.count_pairs() == 0 and tuple(index.pairs()) == ()


def test_dense_cross_source_boolean_query_does_not_materialize_all_real_neighbors():
    rows = tuple(_row(number, source=str(number // 250)) for number in range(10_000))
    index = NearbySourceIndex(rows)
    cohort = _CountingCohort(index._cohorts["cash", -100])
    index._cohorts["cash", -100] = cohort
    assert next(index.iter_neighbors(rows[0].row_id)) == rows[250].row_id
    assert cohort.visits <= 2


def test_sparse_many_source_history_does_not_visit_every_source_for_each_row():
    rows = tuple(_row(number, source=str(number), day=number * 8) for number in range(3000))
    index = NearbySourceIndex(rows)

    cohort = _CountingCohort(index._cohorts["cash", -100])
    index._cohorts["cash", -100] = cohort
    assert all(index.neighbors(row.row_id) == () for row in rows)
    assert cohort.visits == len(rows)


def test_date_window_can_start_and_end_inside_same_source_runs():
    rows = (
        _row(0, day=-6),
        _row(1, day=-2),
        _row(2),
        _row(3, day=2),
        _row(4, day=6),
        _row(5, source="b", day=3),
        _row(6, source="b", day=4),
        _row(7, day=3),
        _row(8, day=4),
    )
    index = NearbySourceIndex(rows)
    assert index.neighbors(rows[2].row_id) == (rows[5].row_id,)
    for row in rows:
        expected = tuple(
            other.row_id
            for other in sorted(rows, key=lambda value: (value.source_date, value.row_id))
            if nearby_source_pair(row, other)
        )
        assert tuple(index.iter_neighbors(row.row_id)) == expected

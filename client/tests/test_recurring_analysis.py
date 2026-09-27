from decimal import Decimal

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from parsetrail.core.cluster import cluster_transactions, filter_by_amount_variance, recurring_transactions


def transactions(amounts, description="Synthetic subscription"):
    return pd.DataFrame(
        {
            "Date": pd.date_range("2026-01-01", periods=len(amounts), freq="MS"),
            "Amount": [Decimal(str(amount)) for amount in amounts],
            "Description": [description] * len(amounts),
        }
    )


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("include_amount", [False, True])
def test_recurring_amount_filter_rejects_variable_debits_and_credits(sign, include_amount):
    frame = transactions([sign * amount for amount in [10, 100, 1000]])
    original = frame.copy(deep=True)
    result = recurring_transactions(frame, max_variance=0.1, max_interval=35, include_amount=include_amount)
    assert result.empty
    assert_frame_equal(frame, original)


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("include_amount", [False, True])
def test_recurring_keeps_stable_series_and_exact_input_money(sign, include_amount):
    frame = transactions([Decimal("19.99") * sign] * 3)
    original = frame.copy(deep=True)
    result = recurring_transactions(frame, max_variance=0, max_interval=35, include_amount=include_amount)
    assert len(result) == 3
    assert result["Amount"].tolist() == original["Amount"].tolist()
    assert all(isinstance(value, Decimal) for value in result["Amount"])
    assert_frame_equal(frame, original)


@pytest.mark.parametrize("sign", [1, -1])
def test_dispersion_threshold_is_an_inclusive_exact_ratio(sign):
    frame = transactions([sign * amount for amount in [9, 10, 11]])
    frame["Cluster"] = 0
    # Sample standard deviation is exactly 1 and the absolute mean exactly 10.
    assert len(filter_by_amount_variance(frame, Decimal("0.1"))) == 3
    assert filter_by_amount_variance(frame, Decimal("0.0999999999999999999999999999")).empty


@pytest.mark.parametrize("amounts", [[0, 0, 0], [-10, 0, -10], [-10, 10, 10], [-10, 10], [10], []])
def test_amount_filter_abstains_on_uninformative_or_mixed_sign_groups(amounts):
    frame = transactions(amounts)
    frame["Cluster"] = 0
    assert filter_by_amount_variance(frame, float("inf")).empty


@pytest.mark.parametrize("amounts", [["NaN", 10, 10], ["Infinity", 10, 10]])
def test_nonfinite_amounts_cannot_become_recurring_matches(amounts):
    frame = transactions(amounts)
    frame["Cluster"] = 0
    assert filter_by_amount_variance(frame, 0.1).empty


@pytest.mark.parametrize("threshold", [-1, float("nan"), float("-inf")])
def test_invalid_dispersion_threshold_is_rejected(threshold):
    frame = transactions([10, 10, 10])
    frame["Cluster"] = 0
    with pytest.raises(ValueError, match="nonnegative"):
        filter_by_amount_variance(frame, threshold)


@pytest.mark.parametrize("description", ["the and or", "!!!", "a b c", ""])
@pytest.mark.parametrize("include_amount", [False, True])
def test_empty_vocabulary_returns_normal_empty_result(description, include_amount):
    frame = transactions([-10, -10, -10], description)
    original = frame.copy(deep=True)
    result = recurring_transactions(frame, include_amount=include_amount, max_variance=0.1)
    assert result.empty
    assert {"Cluster", "Date", "Amount", "Description"} <= set(result.columns)
    assert_frame_equal(frame, original)


def test_empty_input_and_extra_stopwords_return_empty_results():
    assert recurring_transactions(transactions([])).empty
    assert recurring_transactions(transactions([-10, -10, -10]), extra_stopwords=["Synthetic", "subscription"]).empty


def test_uninformative_rows_do_not_form_clusters_when_other_rows_have_words():
    frame = pd.concat([transactions([-10, -10, -10]), transactions([-10, -10, -10], "!!!")], ignore_index=True)
    result = cluster_transactions(frame, min_samples=1, include_amount=True)
    assert result["Description"].tolist() == ["Synthetic subscription"] * 3


def test_optional_amount_features_are_sign_symmetric():
    frame = transactions([10, 100, 1000])
    opposite = frame.copy(deep=True)
    opposite["Amount"] = -opposite["Amount"]
    positive = cluster_transactions(frame, include_amount=True, eps=0.05)
    negative = cluster_transactions(opposite, include_amount=True, eps=0.05)
    assert positive["Cluster"].tolist() == negative["Cluster"].tolist()


def test_minimum_interval_excludes_frequent_purchases():
    frame = transactions([-10, -10, -10])
    frame["Date"] = pd.date_range("2026-01-01", periods=3, freq="D")
    assert recurring_transactions(frame, min_interval=3, max_interval=35).empty


def test_noise_does_not_pass_amount_filter():
    frame = transactions([-10, -10, -10])
    frame["Cluster"] = -1
    assert filter_by_amount_variance(frame, float("inf")).empty


def test_noise_only_analysis_returns_no_match_without_optional_filters():
    assert recurring_transactions(transactions([-10])).empty

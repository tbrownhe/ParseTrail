import re
from decimal import Decimal
from fractions import Fraction

import pandas as pd
from scipy.sparse import hstack
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import MinMaxScaler

from parsetrail.core.english_stopwords import ENGLISH_STOP_WORDS, normalize_words


def preprocess_text(description: str, stopwords: set[str] | frozenset[str] | None = None) -> str:
    """
    Normalize and preprocess the transaction description.
    """
    if stopwords is None:
        stopwords = ENGLISH_STOP_WORDS

    # Normalize text and remove special characters
    description = description.lower()
    description = re.sub(r"[^a-z0-9\s]", "", description)
    tokens = [word for word in description.split() if word not in stopwords]
    return " ".join(tokens)


def cluster_transactions(
    transactions: pd.DataFrame,
    eps=0.5,
    min_samples=2,
    include_amount=False,
    extra_stopwords: list[str] | None = None,
):
    """
    Cluster similar transaction descriptions using TF-IDF and DBSCAN.

    Args:
        transactions (pd.DataFrame): DataFrame with 'Description' and 'Date'.
        eps (float): DBSCAN epsilon (distance threshold).
        min_samples (int): Minimum samples per cluster.

    Returns:
        pd.DataFrame: Transactions with an additional 'Cluster' column.
    """
    transactions = transactions.copy(deep=True)
    if extra_stopwords:
        local_stopwords = ENGLISH_STOP_WORDS.union(word for extra in extra_stopwords for word in normalize_words(extra))
    else:
        local_stopwords = ENGLISH_STOP_WORDS

    # Preprocess text
    transactions["Normalized"] = transactions["Description"].apply(
        lambda d: preprocess_text(d, stopwords=local_stopwords)
    )

    # Convert to numerical vectors using TF-IDF
    tfidf = TfidfVectorizer()
    # Use the vectorizer's own token rules (including its minimum token length).
    # Empty descriptions are not evidence for a recurring series, even when
    # amount features are enabled or min_samples is one.
    analyzer = tfidf.build_analyzer()
    informative = transactions["Normalized"].map(lambda text: bool(analyzer(text))).astype(bool)
    transactions = transactions.loc[informative].copy()
    index = transactions.columns.to_list().index("Description")
    if transactions.empty:
        transactions.insert(loc=index, column="Cluster", value=pd.Series(index=transactions.index, dtype="int64"))
        return transactions
    features = tfidf.fit_transform(transactions["Normalized"])

    # Construct the DBSCAN clusterer
    dbscan = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine")

    if include_amount:
        # Normalize the 'Amount' column to 0-1 range
        scaler = MinMaxScaler()
        # Floating-point vectors are only ML features; retain original exact
        # money values and use magnitudes so debit/credit mirrors cluster alike.
        amount_scaled = scaler.fit_transform(transactions[["Amount"]].abs())

        # Combine TF-IDF and Amount features
        features = hstack([features, amount_scaled])

    # Run the clustering for description only
    clusters = dbscan.fit_predict(features)

    # Add cluster labels to the DataFrame
    transactions.insert(loc=index, column="Cluster", value=clusters)

    return transactions


def identify_recurring_clusters(transactions: pd.DataFrame, min_size=3, min_interval=0, max_interval=35):
    """
    Identify recurring clusters based on transaction dates and frequency.

    Args:
        transactions (pd.DataFrame): DataFrame with 'Cluster' and 'Date'.
        date_col (str): Name of the date column.
        min_size (int): Minimum number of occurrences for a cluster to be considered recurring.
        min_interval (int): Minimum interval (in days) for a cluster to be considered recurring.
        max_interval (int): Maximum interval (in days) for a cluster to be considered recurring.

    Returns:
        pd.DataFrame: Filtered DataFrame with recurring clusters.
    """
    recurring = []
    for cluster_id, group in transactions.groupby("Cluster"):
        # Skip noise
        if cluster_id == -1:
            continue

        # Ignore clusters that are too small
        if len(group) < min_size:
            continue

        # Check regularity of dates
        group = group.sort_values("Date")
        intervals = group["Date"].diff().dt.days.dropna()
        if min_interval <= intervals.mean() <= max_interval:
            recurring.append(cluster_id)

    return transactions[transactions["Cluster"].isin(recurring)]


def filter_by_amount_variance(transactions: pd.DataFrame, max_variance: float) -> pd.DataFrame:
    """Filter by sample standard deviation / absolute mean (0.1 means 10%).

    Retain the historical argument name, but this is relative dispersion, not
    variance. Require at least two finite, nonzero amounts with the same sign;
    mixed purchases/refunds are not one reliable payment amount. Reject these
    uninformative groups even with an infinite threshold. Compare squared
    ratios exactly so Decimal money needs no float conversion or rounded sqrt.
    """
    threshold = Decimal(str(max_variance))
    if threshold.is_nan() or threshold < 0:
        raise ValueError("Amount dispersion threshold must be nonnegative.")
    limit = Fraction(threshold) ** 2 if threshold.is_finite() else None
    recurring = []
    for cluster_id, group in transactions.groupby("Cluster"):
        # Skip noise
        if cluster_id == -1:
            continue

        amounts = [Decimal(str(value)) for value in group["Amount"]]
        if len(amounts) < 2 or any(not value.is_finite() or value == 0 for value in amounts):
            continue
        if not (all(value > 0 for value in amounts) or all(value < 0 for value in amounts)):
            continue
        if limit is None:
            recurring.append(cluster_id)
            continue
        exact_amounts = [Fraction(value) for value in amounts]
        mean = sum(exact_amounts) / len(exact_amounts)
        variance = sum((value - mean) ** 2 for value in exact_amounts) / (len(exact_amounts) - 1)
        if variance <= limit * mean**2:
            recurring.append(cluster_id)

    return transactions[transactions["Cluster"].isin(recurring)]


def recurring_transactions(transactions: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Performs a TF-IDF clustering analysis to find recurring transactions

    Args:
        transactions (pd.DataFrame): Transactions table

    Returns:
        pd.DataFrame: Clustered Transactions
    """
    columns = transactions.columns.to_list()
    required_cols = ["Date", "Amount", "Description"]
    if any(rcol not in columns for rcol in required_cols):
        raise KeyError(f"Dataframe must contain columns {required_cols}")

    # Leave the caller's dates, money, and columns unchanged.
    transactions = transactions.copy(deep=True)
    # Convert db date to datetime
    transactions["Date"] = pd.to_datetime(transactions["Date"])

    # Extract relevant arguments for each function
    cluster_kwargs = {
        key: kwargs[key] for key in ["eps", "min_samples", "include_amount", "extra_stopwords"] if key in kwargs
    }
    recurring_kwargs = {key: kwargs[key] for key in ["min_size", "min_interval", "max_interval"] if key in kwargs}
    amount_kwargs = {key: kwargs[key] for key in ["max_variance"] if key in kwargs}

    # Analyze
    transactions = cluster_transactions(transactions, **cluster_kwargs)
    if recurring_kwargs:
        transactions = identify_recurring_clusters(transactions, **recurring_kwargs)
    if amount_kwargs:
        transactions = filter_by_amount_variance(transactions, **amount_kwargs)

    return transactions[transactions["Cluster"] != -1].sort_values(by=["Cluster", "Date"])

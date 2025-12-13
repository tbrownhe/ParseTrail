import re

import nltk
import pandas as pd
from loguru import logger
from scipy.sparse import hstack
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import MinMaxScaler

# Download stopwords if necessary
for attempt in range(1, 4):
    try:
        from nltk.corpus import stopwords

        STOP_WORDS = set(stopwords.words("english"))

    except Exception:
        logger.debug("Downloading Stopwords for 'nltk' corpus... Attempt {attempt} of 3")
        nltk.download("stopwords")
        continue
    break


def preprocess_text(description: str, stopwords: set | None = None) -> str:
    """
    Normalize and preprocess the transaction description.
    """
    if not stopwords:
        stopwords = STOP_WORDS  # default global set

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
    if extra_stopwords:
        local_stopwords = STOP_WORDS.union(w.lower() for w in extra_stopwords)
    else:
        local_stopwords = STOP_WORDS

    # Preprocess text
    transactions["Normalized"] = transactions["Description"].apply(
        lambda d: preprocess_text(d, stopwords=local_stopwords)
    )

    # Convert to numerical vectors using TF-IDF
    tfidf = TfidfVectorizer()
    features = tfidf.fit_transform(transactions["Normalized"])

    # Construct the DBSCAN clusterer
    dbscan = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine")

    if include_amount:
        # Normalize the 'Amount' column to 0-1 range
        scaler = MinMaxScaler()
        amount_scaled = scaler.fit_transform(transactions[["Amount"]])

        # Combine TF-IDF and Amount features
        features = hstack([features, amount_scaled])

    # Run the clustering for description only
    clusters = dbscan.fit_predict(features)

    # Add cluster labels to the DataFrame
    index = transactions.columns.to_list().index("Description")
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
    """
    Filter clusters to include only those with similar amounts.

    Args:
        transactions (pd.DataFrame): Transactions with 'Cluster' and 'Amount'.
        max_variance (float): Maximum allowable relative variance in amounts within a cluster.

    Returns:
        pd.DataFrame: Filtered transactions.
    """
    recurring = []
    for cluster_id, group in transactions.groupby("Cluster"):
        # Skip noise
        if cluster_id == -1:
            continue

        # Compute variance and apply filter
        variance = group["Amount"].std() / group["Amount"].mean() if group["Amount"].mean() != 0 else 0
        if variance <= max_variance:
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

    return transactions.sort_values(by=["Cluster", "Date"])

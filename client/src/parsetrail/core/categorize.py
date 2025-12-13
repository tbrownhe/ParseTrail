from pathlib import Path

import pandas as pd
from loguru import logger
from sqlalchemy.orm import Session

from parsetrail.core.learn import predict
from parsetrail.core.orm import Transactions, Categories
from parsetrail.core.query import training_set


def update_db_categories(session: Session, df: pd.DataFrame) -> None:
    """
    Updates the database's Transactions table with new CategoryID and ConfidenceScore.

    Args:
        session (Session): SQLAlchemy session object.
        df (pd.DataFrame): DataFrame containing at least:
            - TransactionID
            - Category  (predicted category name)
            - ConfidenceScore
    """
    logger.info("Updating Transactions.CategoryID and Transactions.ConfidenceScore")

    required_cols = {"TransactionID", "Category", "ConfidenceScore"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    # Normalize category names from the model
    df["Category"] = df["Category"].astype(str).str.strip()

    # Unique category names predicted by the model
    category_names = sorted(df["Category"].unique())

    if not category_names:
        logger.info("No categories to update.")
        return

    # Look up CategoryID for all predicted names
    existing = session.query(Categories.Name, Categories.CategoryID).filter(Categories.Name.in_(category_names)).all()
    category_map = {name: cat_id for name, cat_id in existing}

    # Sanity check: all predicted categories should exist in Categories
    missing_cats = [name for name in category_names if name not in category_map]
    if missing_cats:
        raise RuntimeError(
            "The model predicted categories that do not exist in the Categories table: "
            + ", ".join(sorted(missing_cats))
        )

    # Apply updates per transaction
    for row in df.itertuples(index=False):
        tx_id = row.TransactionID
        cat_name = row.Category
        conf = float(row.ConfidenceScore) if row.ConfidenceScore is not None else None
        cat_id = category_map[cat_name]

        session.query(Transactions).filter(Transactions.TransactionID == tx_id).update(
            {
                Transactions.CategoryID: cat_id,
                Transactions.ConfidenceScore: conf,
            },
            synchronize_session=False,
        )

    session.commit()
    logger.success("Updated categories and confidence scores for {} transactions", len(df))


def transactions(
    session: Session,
    model_path: Path,
    unverified: bool = True,
    uncategorized: bool = False,
) -> None:
    """
    Categorize transactions based on specified flags and update the database.

    Args:
        session (Session): SQLAlchemy session object.
        model_path (Path): Path to the trained classification model.
        unverified (bool, optional): Categorize only unverified transactions if True.
        uncategorized (bool, optional): Categorize only uncategorized transactions if True.
    """
    # Fetch the transactions based on the flags
    data, columns = training_set(session, unverified=unverified, uncategorized=uncategorized)

    # Fetch the current set of categories
    result = session.query(Categories.Name).all()
    categories = [category for (category,) in result]

    if len(data) == 0:
        logger.debug("No transactions to categorize!")
        return

    # Convert to DataFrame for processing
    df = pd.DataFrame(data, columns=columns)

    # Categorize the transactions using the model
    df = predict(model_path, df, current_categories=categories)

    # Update the categorized transactions in the database
    update_db_categories(session, df)

    logger.success("Transactions auto-categorized using model at {}", model_path)

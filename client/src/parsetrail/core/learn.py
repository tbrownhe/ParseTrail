from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from loguru import logger
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

MODEL_VERSION = "1.0-category-bundle"

ModelBundle = Dict[str, Any]


def save_model(model_path: Path, bundle: ModelBundle) -> None:
    """
    Persist a complete model bundle (pipeline + metadata) to disk.
    """
    logger.info("Saving machine learning model bundle to {}", model_path)
    joblib.dump(bundle, model_path)


def load_model(model_path: Path) -> ModelBundle:
    """
    Load a model bundle from disk and validate its structure/version.
    """
    logger.info("Loading machine learning model bundle from {}", model_path)
    bundle = joblib.load(model_path)

    # Old format support intentionally removed: force retrain.
    if not isinstance(bundle, dict) or "version" not in bundle:
        raise RuntimeError(
            "Incompatible model file (legacy format). "
            "Please retrain a new model with the current version of ParseTrail."
        )

    if bundle["version"] != MODEL_VERSION:
        raise RuntimeError(
            f"Incompatible model version '{bundle['version']}' "
            f"(expected '{MODEL_VERSION}'). Please retrain the model."
        )

    required_keys = {"pipeline", "amount", "categories", "features", "meta"}
    missing = required_keys - set(bundle.keys())
    if missing:
        raise RuntimeError(f"Model bundle is missing required keys: {sorted(missing)}. " "Please retrain the model.")

    return bundle


def prepare_data(
    df: pd.DataFrame,
    amount: bool,
    features: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Optional[pd.Series], Dict[str, Any]]:
    """
    Prepare input features X and labels y (if present) from a DataFrame.

    Expected columns in df:
        - "Company"
        - "AccountType"
        - "Description"
        - "Category" (for labeled training data; may be absent at prediction time)
        - "Amount" (if amount=True)

    Args:
        df: Input DataFrame.
        amount: Whether to include the "Amount" column as a numeric feature.
        features: Optional feature spec dict from a previously saved model.
                  If provided, it controls text column name and numeric feature names.

    Returns:
        X: Feature DataFrame.
        y: Label Series ("Category") or None if no label column present.
        features_out: Dict describing feature config, saved with the model.
    """
    # Work on a copy to avoid side effects on caller df
    df = df.copy()

    base_required = ["Company", "AccountType", "Description"]
    has_category = "Category" in df.columns
    required = base_required + (["Category"] if has_category else [])
    if amount:
        required.append("Amount")

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {missing}")

    # Use provided feature spec if available, else derive standard config
    if features is None:
        text_column = "TextFeatures"
        text_source_columns = ["Company", "AccountType", "Description"]
        numeric_features = ["Amount"] if amount else []
    else:
        text_column = features.get("text_column", "TextFeatures")
        text_source_columns = features.get("text_source_columns", ["Company", "AccountType", "Description"])
        numeric_features = features.get("numeric_features", ["Amount"] if amount else [])

    # Create combined text feature
    df[text_column] = df[text_source_columns].astype(str).agg(" ".join, axis=1)

    # Build X and y
    x_cols = [text_column] + numeric_features
    X = df[x_cols]
    y = df["Category"] if has_category else None

    features_out = {
        "text_column": text_column,
        "text_source_columns": text_source_columns,
        "numeric_features": numeric_features,
    }

    return X, y, features_out


def prepare_pipeline(features: Dict[str, Any]) -> Pipeline:
    """
    Construct the sklearn Pipeline given a feature configuration dict.
    """
    text_column = features["text_column"]
    numeric_features: List[str] = features.get("numeric_features", [])

    transformers = [("text", TfidfVectorizer(), text_column)]
    if numeric_features:
        transformers.append(("num", StandardScaler(), numeric_features))

    preprocessor = ColumnTransformer(transformers=transformers)

    classifier = LinearSVC()
    pipeline = Pipeline(
        [
            ("preprocessor", preprocessor),
            ("classifier", classifier),
        ]
    )

    return pipeline


def plot_confusion_matrix(
    y_test: pd.Series,
    y_pred: np.ndarray,
    categories: List[str],
    normalized: bool = True,
) -> None:
    """
    Generate and display a confusion matrix heatmap.
    """
    conf_mat = confusion_matrix(y_test, y_pred, labels=categories)
    if normalized:
        conf_mat = conf_mat.astype("float")
        row_sums = conf_mat.sum(axis=1, keepdims=True)
        # Avoid division by zero if a label is absent in y_test
        row_sums[row_sums == 0] = 1.0
        conf_mat_normalized = 100 * conf_mat / row_sums
        sns.heatmap(
            conf_mat_normalized,
            annot=True,
            fmt=".0f",
            xticklabels=categories,
            yticklabels=categories,
            cmap="Blues",
        )
        for text in plt.gca().texts:
            text.set_text(f"{text.get_text()}%")
    else:
        sns.heatmap(
            conf_mat,
            annot=True,
            fmt="d",
            xticklabels=categories,
            yticklabels=categories,
        )
    plt.ylabel("Actual")
    plt.xlabel("Predicted")
    plt.tight_layout()
    plt.show()


def train_pipeline_test(df: pd.DataFrame, amount: bool = False) -> None:
    """
    Train a classification model and report accuracy + confusion matrix.
    This is for experimentation / evaluation only; it does not save the model.

    Several models were tested with and without a numeric Amount column.
    The Amount column typically degraded performance slightly. With text input only,
    accuracy was approximately:
        - LogisticRegression: 94.0%
        - LinearSVC: 97.2%
        - RandomForest: 93.1%
    """
    logger.info("Training classification model to test accuracy")

    # Prepare the training set and preprocessor
    X, y, features = prepare_data(df, amount=amount)
    if y is None:
        raise ValueError("Training data must include a 'Category' column.")

    pipeline = prepare_pipeline(features)

    # Train-Test split
    x_train, x_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=0)

    # Train pipeline
    pipeline.fit(x_train, y_train)

    # Report accuracy and display confusion matrix
    y_pred = pipeline.predict(x_test)
    acc = accuracy_score(y_test, y_pred)
    logger.info("Validation accuracy: {0:.1%}".format(acc))

    categories = sorted(y.unique())
    plot_confusion_matrix(y_test, y_pred, categories=categories)


def train_pipeline_save(df: pd.DataFrame, model_path: Path, amount: bool = False) -> None:
    """
    Train a classification model on the provided data and save it for future use.

    The saved model bundle includes:
        - sklearn Pipeline
        - whether Amount was used as a numeric feature
        - list of category names seen during training
        - feature configuration
        - basic metadata (timestamp, counts)
    """
    logger.info("Training classification pipeline for later use.")

    # Prepare the training set and preprocessor
    X, y, features = prepare_data(df, amount=amount)
    if y is None:
        raise ValueError("Training data must include a 'Category' column.")

    pipeline = prepare_pipeline(features)

    # Train on all provided data
    pipeline.fit(X, y)

    categories = sorted(y.unique())
    bundle: ModelBundle = {
        "version": MODEL_VERSION,
        "pipeline": pipeline,
        "amount": amount,
        "categories": categories,
        "features": features,
        "meta": {
            "trained_at": datetime.utcnow().isoformat() + "Z",
            "n_samples": int(len(df)),
            "n_categories": len(categories),
        },
    }

    save_model(model_path, bundle)
    logger.success("Pipeline saved to {}", model_path)


def confidence_score(pipeline: Pipeline, X: pd.DataFrame) -> np.ndarray:
    """
    Estimate a confidence score based on a numerically stable pseudo-probability.

    For each sample, we:
        - Take the decision_function scores
        - Apply a softmax-like transformation
        - Return the maximum "probability" as a confidence scalar

    Note: This is not a calibrated probability; it is only a relative confidence indicator.
    """
    decision_scores = pipeline.decision_function(X)
    scores = np.asarray(decision_scores)

    if scores.ndim == 1:
        # Binary classification: decision_function returns shape (n_samples,)
        scores = scores.reshape(-1, 1)

    # Softmax with max subtraction for numerical stability
    scores = scores - scores.max(axis=1, keepdims=True)
    exp_scores = np.exp(scores)
    sum_exp = exp_scores.sum(axis=1, keepdims=True)
    # Avoid division by zero (shouldn't happen, but just in case)
    sum_exp[sum_exp == 0] = 1.0
    pseudo_probabilities = exp_scores / sum_exp

    confidence = pseudo_probabilities.max(axis=1)
    return confidence


def _check_category_compatibility(
    model_categories: Iterable[str],
    current_categories: Optional[Iterable[str]],
) -> None:
    """
    Optional compatibility check between the model's training categories and the
    current category set (e.g., from the database).

    - If current_categories is None: no check is performed.
    - If the model was trained on categories that no longer exist: raise an error.
    - If new categories exist that the model has never seen: log a warning.
    """
    if current_categories is None:
        return

    model_set = set(model_categories)
    current_set = set(current_categories)

    missing_in_current = sorted(model_set - current_set)
    if missing_in_current:
        # Model can predict labels that the current system does not support
        raise RuntimeError(
            "The trained model uses categories that no longer exist in the current category set: "
            + ", ".join(missing_in_current)
            + ". Please either restore these categories or retrain the model."
        )

    extra_in_current = sorted(current_set - model_set)
    if extra_in_current:
        # Not fatal: the model just can't predict these new categories
        logger.warning(
            "The current category set contains categories the model has never seen: {}. "
            "Auto-categorization will never assign these categories. "
            "Consider retraining the model.",
            extra_in_current,
        )


def predict(
    model_path: Path,
    df: pd.DataFrame,
    current_categories: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """
    Predict categories and confidence scores for new transactions.

    Args:
        model_path: Path to the saved model bundle.
        df: DataFrame of transactions to classify. Must contain the same
            feature columns used for training (Company, AccountType, Description,
            and optionally Amount). A 'Category' column may be present or not;
            if present, it will be overwritten.
        current_categories: Optional iterable of category names representing the
            *current* valid category set (e.g., from the Categories table). If provided,
            the model's training categories are checked for compatibility against it.

    Returns:
        df with two additional columns:
            - "Category": predicted category names
            - "ConfidenceScore": confidence scalar per row
    """
    logger.info("Classifying transactions using model at {}", model_path)
    bundle = load_model(model_path)

    pipeline: Pipeline = bundle["pipeline"]
    amount: bool = bundle["amount"]
    model_categories: List[str] = bundle["categories"]
    features: Dict[str, Any] = bundle["features"]

    # Optional compatibility check
    _check_category_compatibility(model_categories, current_categories)

    # Prepare features using the same config as training
    X, _, _ = prepare_data(df, amount=amount, features=features)

    # Work on a copy so we don't surprise the caller
    result_df = df.copy()

    # Predict categories and confidence scores
    result_df["Category"] = pipeline.predict(X)
    result_df["ConfidenceScore"] = confidence_score(pipeline, X)

    return result_df

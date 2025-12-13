from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from loguru import logger
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import (
    CountVectorizer,
    TfidfTransformer,
    TfidfVectorizer,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import LinearSVC
from tqdm import tqdm

"""
Most of this was lifted from these:
https://towardsdatascience.com/multi-class-text-classification-with-scikit-learn-12f1e60e0a9f
https://github.com/drojasug/ClassifyingExpensesSciKitLearn/blob/master/MyBudget.ipynb
"""


def load_data() -> pd.DataFrame:
    logger.info("Loading data")
    csv_path = Path("CategorizedExpenses.csv").resolve()
    df = pd.read_csv(csv_path)
    return df


def save_models(vectorizer: CountVectorizer, classifier: LinearSVC) -> None:
    logger.info("Saving models to disk")
    joblib.dump(vectorizer, "vectorizer.mdl")
    joblib.dump(classifier, "classifier.mdl")


def load_models() -> tuple[CountVectorizer, LinearSVC]:
    logger.info("Loading models from disk")
    vectorizer = joblib.load("vectorizer.mdl")
    classifier = joblib.load("classifier.mdl")
    return vectorizer, classifier


def factorize_categories(df):
    """
    Factorize the categories
    """
    logger.info("Factorizing categories")

    # Factorize the categories
    df = df.dropna(axis=0, subset=["Description", "Category"])
    df["category_id"] = df["Category"].factorize()[0]

    # Generate the factorization key
    category_id_df = df[["Category", "category_id"]].drop_duplicates().sort_values("category_id")

    return df, category_id_df


def vectorize_labeled_data(df: pd.DataFrame):
    """
    Vectorizing the description of each transaction.
    Result is uniform 2D array with length of transactions and width of N unique words
    """
    logger.info("Vectorizing transaction descriptions")

    # Vectorize descriptions
    tfidf = TfidfVectorizer(
        sublinear_tf=True,
        min_df=5,
        norm="l2",
        encoding="latin-1",
        ngram_range=(1, 2),
        stop_words="english",
    )
    features = tfidf.fit_transform(df.Description).toarray()

    return features


def train(df: pd.DataFrame, model=LinearSVC()):
    """
    Uses the categorized transactions in the DataFrame to train the chosen ML model.
    The commented out options don't seem to have much effect.
    """
    logger.info("Training {m} model", m=str(model))

    # Train the model on a large fraction of the transactions
    x_train, x_test, y_train, y_test = train_test_split(
        df["Description"], df["Category"], test_size=0.1, random_state=0
    )

    vectorizer = CountVectorizer(
        # min_df=5,
        # ngram_range=(1, 2),
        # stop_words="english",
    )
    X_train_counts = vectorizer.fit_transform(x_train)

    tfidf = TfidfTransformer(
        # sublinear_tf=True,
        # norm="l2",
    )
    X_train_tfidf = tfidf.fit_transform(X_train_counts)
    classifier = model.fit(X_train_tfidf, y_train)

    # Test the accuracy of the model
    score = classifier.score(vectorizer.transform(x_test), y_test)
    logger.info("Classifier is {a} accurate", a="{0:.1%}".format(score))

    # Save the trained model to disk
    save_models(vectorizer, classifier)

    return vectorizer, classifier


def compare_models(features, labels):
    """
    Compares the cross value score for a list of ML models
    to find which one is most accurate.
    """
    logger.info("Comparing machine learning models")
    models = [
        RandomForestClassifier(n_estimators=200, max_depth=3, random_state=0),
        LinearSVC(),
        MultinomialNB(),
        LogisticRegression(random_state=0),
    ]
    CV = 5
    cv_df = pd.DataFrame(index=range(CV * len(models)))
    entries = []

    for model in tqdm(models, total=len(models)):
        model_name = model.__class__.__name__
        accuracies = cross_val_score(model, features, labels, scoring="accuracy", cv=CV)

        for fold_idx, accuracy in enumerate(accuracies):
            entries.append((model_name, fold_idx, accuracy))

    cv_df = pd.DataFrame(entries, columns=["model_name", "fold_idx", "accuracy"])
    sns.boxplot(x="model_name", y="accuracy", data=cv_df)
    sns.stripplot(
        x="model_name",
        y="accuracy",
        data=cv_df,
        size=8,
        jitter=True,
        edgecolor="gray",
        linewidth=2,
    )
    plt.show()


def plot_confusion_matrix(df, category_id_df, features, labels):
    """
    Generate a confusion matrix
    """
    logger.info("Generating Confusion Matrix")
    model = LinearSVC()
    X_train, X_test, y_train, y_test, indices_train, indices_test = train_test_split(
        features, labels, df.index, test_size=0.33, random_state=0
    )
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    conf_mat = confusion_matrix(y_test, y_pred)
    fig, ax = plt.subplots(figsize=(10, 10))
    sns.heatmap(
        conf_mat,
        annot=True,
        fmt="d",
        xticklabels=category_id_df.Category.values,
        yticklabels=category_id_df.Category.values,
    )
    plt.ylabel("Actual")
    plt.xlabel("Predicted")
    plt.show()


def learn():
    """
    Stuff here
    """
    df = load_data()

    df, category_id_df = factorize_categories(df)
    labels = df.category_id

    train(df)

    # Convert the categorized transactions into normalized features and labels
    features = vectorize_labeled_data(df)

    # See which ML model gives highest accuracy
    if False:
        compare_models(features, labels)

    # Plot the confusion matrix
    plot_confusion_matrix(df, category_id_df, features, labels)


if __name__ == "__main__":
    learn()

"""Headless model training with worker-owned reads and uncommitted output."""

from pathlib import Path

import pandas as pd

from parsetrail.core import learn
from parsetrail.core.analysis import AnalysisInputError, CancellationCheck, check_cancelled
from parsetrail.core.dashboard import DashboardQueryService


def train_from_database(
    service: DashboardQueryService, model_path: Path | None, cancelled: CancellationCheck
) -> learn.TrainingEvaluation | learn.PreparedModel:
    check_cancelled(cancelled)
    # training_set owns its session in this caller's thread and returns only
    # scalar data. Never transfer a GUI session or ORM entity into training.
    data, columns = service.training_set()
    check_cancelled(cancelled)
    if not data:
        raise AnalysisInputError("There are no verified, categorized transactions to train a model.")
    frame = pd.DataFrame(data, columns=columns)
    if model_path is None:
        return learn.evaluate_pipeline(frame, amount=False, cancelled=cancelled)
    bundle = learn.fit_model_bundle(frame, amount=False, cancelled=cancelled)
    return learn.prepare_model_save(model_path, bundle, cancelled=cancelled)

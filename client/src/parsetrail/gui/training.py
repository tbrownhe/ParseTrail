"""Cancellable model-training progress; model commit and widgets stay on Qt."""

from functools import partial
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from parsetrail.core import learn
from parsetrail.core.dashboard import DashboardQueryService
from parsetrail.core.training import train_from_database
from parsetrail.gui.analysis_worker import LocalAnalysisJob


class ModelTrainingDialog(QDialog):
    def __init__(self, service: DashboardQueryService, model_path: Path | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Train Model for Testing" if model_path is None else "Train Model for Deployment")
        self.setMinimumWidth(440)
        self.service = service
        self.model_path = model_path
        self.evaluation = None
        self.saved_path = None
        self._started = False
        self._closed = False
        self._pending_done = None
        self.analysis_job = LocalAnalysisJob(self)
        self.analysis_job.completed.connect(self._complete)
        self.analysis_job.failed.connect(self._failed)
        self.analysis_job.cancelled.connect(self._cancelled)
        self.analysis_job.finished.connect(self._finished)

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Preparing local training...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel Training")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_training)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        QTimer.singleShot(0, self.start_training)

    def start_training(self):
        if self._started or self._closed:
            return
        self._started = True
        self.status_label.setText("Reading verified transactions and training locally...")
        self.cancel_button.setEnabled(True)
        self.analysis_job.start(
            partial(train_from_database, self.service, self.model_path),
            discard=learn.discard_prepared_model,
        )

    def _complete(self, result):
        if isinstance(result, learn.PreparedModel):
            try:
                # The queued result has survived cancellation. This single Qt
                # callback is the commit boundary; no training or serialization
                # runs here, and Cancel cannot interleave with the atomic rename.
                learn.publish_prepared_model(result)
                self.saved_path = result.model_path
            except OSError:
                logger.exception("Could not publish the trained model")
                self.status_label.setText("Could not save the trained model. The previous model is unchanged.")
                return
            finally:
                learn.discard_prepared_model(result)
        else:
            self.evaluation = result
        self.accept()

    def cancel_training(self):
        if self.analysis_job.busy:
            self.analysis_job.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Canceling training; waiting for the current calculation step to finish...")

    def _failed(self):
        self.status_label.setText(
            self.analysis_job.error_message
            or "Training failed. The previous model is unchanged. See the application log for details."
        )

    def _cancelled(self):
        self.status_label.setText("Training canceled. No model was saved or replaced.")

    def _finished(self):
        self.progress.setRange(0, 1)
        self.cancel_button.setEnabled(False)
        if self._pending_done is not None:
            result, self._pending_done = self._pending_done, None
            self.done(result)

    def done(self, result):
        if self.analysis_job.busy:
            self._pending_done = result
            self.cancel_training()
            return
        self._closed = True
        super().done(result)

    def closeEvent(self, event):
        if self.analysis_job.busy:
            self.done(QDialog.Rejected)
            event.ignore()
            return
        super().closeEvent(event)

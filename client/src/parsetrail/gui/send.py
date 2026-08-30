from pathlib import Path
from threading import Event

from loguru import logger
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from parsetrail.core.api import (
    StatementSubmissionCancelled,
    api_client,
)
from parsetrail.core.auth import AuthError
from parsetrail.core.crypto import encrypt_file
from parsetrail.core.settings import settings
from parsetrail.core.submission import (
    PreparedStatementSubmission,
    StatementSubmissionError,
    StatementSubmissionService,
    StatementSubmissionValidationError,
)


class StatementSubmissionThread(QThread):
    """Encrypt and upload a statement without blocking the Qt event loop."""

    stage_changed = Signal(str)
    progress_changed = Signal(int, int)
    submitted = Signal()
    submission_failed = Signal(str)
    submission_cancelled = Signal()

    def __init__(
        self,
        submission: PreparedStatementSubmission | Path,
        metadata: dict[str, object] | None = None,
        *,
        credentials: tuple[str, str] | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if isinstance(submission, PreparedStatementSubmission):
            self.submission = submission
        else:
            self.submission = PreparedStatementSubmission(Path(submission), dict(metadata or {}))
        self.credentials = credentials
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            credentials = self.credentials
            self.credentials = None
            StatementSubmissionService(client=api_client, encryptor=encrypt_file).submit(
                self.submission,
                credentials=credentials,
                cancelled=self._cancel_event.is_set,
                progress=self.progress_changed.emit,
                stage_changed=self.stage_changed.emit,
            )
        except StatementSubmissionCancelled:
            self.submission_cancelled.emit()
        except StatementSubmissionError as exc:
            self.submission_failed.emit(str(exc))
        except Exception:
            logger.exception("Unexpected failure in statement submission worker")
            self.submission_failed.emit("The encrypted statement could not be submitted. See the application log.")
        else:
            self.submitted.emit()


class StatementSubmissionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Secure Statement Submission Form")
        self.setMinimumWidth(600)

        # Layout
        layout = QVBoxLayout(self)

        # Instructions
        instructions = QLabel(
            "Please select a bank statement file you need a plugin for"
            " and provide all required details.\n\n"
            "All data is sent using end-to-end encryption over https,"
            " and your file is stored using AES encryption at rest."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Form layout
        form_layout = QFormLayout()

        # File Picker
        self.file_path_input = QLineEdit()
        self.file_path_input.setPlaceholderText("No file selected")
        self.file_path_input.setReadOnly(True)
        self.file_picker_button = QPushButton("Select File")
        self.file_picker_button.clicked.connect(self.pick_file)
        form_layout.addRow("Statement File:", self.file_picker_button)
        form_layout.addRow("Selected File:", self.file_path_input)

        # Institution Name
        self.institution_input = QLineEdit()
        self.institution_input.setPlaceholderText("e.g., Bank of America")
        form_layout.addRow("Institution Name:", self.institution_input)

        # Statement Frequency Dropdown
        self.frequency_input = QComboBox()
        self.frequency_input.addItems(["Daily", "Weekly", "Monthly", "Quarterly", "Annually", "Other"])
        self.frequency_input.setCurrentIndex(2)
        form_layout.addRow("Statement Frequency:", self.frequency_input)

        # Comments (Limited to 256 characters)
        self.comments_input = QTextEdit()
        self.comments_input.setPlaceholderText("Add any notes, clarifications, or bugs (max 256 characters)...")
        self.comments_input.setMaximumHeight(80)
        form_layout.addRow("Additional Comments:", self.comments_input)

        layout.addLayout(form_layout)

        # Submit & Cancel Buttons
        self.submit_button = QPushButton("Submit")
        self.submit_button.clicked.connect(self.submit_data)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        # Add buttons to layout
        layout.addWidget(self.submit_button)
        layout.addWidget(self.cancel_button)

    def clear_fields(self):
        self.file_path_input.setText("")
        self.institution_input.setText("")
        self.comments_input.setText("")

    def pick_file(self):
        """
        Opens a file picker dialog and sets the selected file path.
        """
        default_dir = str(settings.fail_dir)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Bank Statement",
            default_dir,
            "All Files (*.*);;PDF Files (*.pdf)",
        )
        if file_path:
            self.file_path_input.setText(file_path)

    def submit_data(self):
        """
        Collect user input, validate it, and return the metadata.
        """
        if not self.validate():
            return
        if not self.confirm():
            return
        self.send_statement()

    def validate(self) -> bool:
        try:
            self.submission = StatementSubmissionService().prepare(
                Path(self.file_path_input.text().strip()),
                institution=self.institution_input.text(),
                frequency=self.frequency_input.currentText(),
                comments=self.comments_input.toPlainText(),
            )
        except StatementSubmissionValidationError as exc:
            QMessageBox.warning(self, "Input Error", str(exc))
            return False

        return True

    def confirm(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Confirm Submission",
            (
                "Are you sure you want to submit this statement?\n\n"
                "Once submitted, this file will be encrypted and sent"
                " to ParseTrail developers for plugin development."
            ),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            return True
        logger.info("User cancelled statement submission.")
        return False

    def send_statement(self):
        """Encrypts and sends validated data to the server API."""
        submission = getattr(self, "submission", None)
        if submission is None:
            raise ValueError("No validated statement submission is available")
        fpath = submission.source

        try:
            credentials = api_client.auth.credentials_if_needed()
        except AuthError:
            QMessageBox.information(self, "Submission Canceled", "Sign-in was canceled.")
            return

        logger.info(f"Sending {fpath} to server")
        progress = QProgressDialog("Preparing encrypted statement...", "Cancel", 0, 0, self)
        progress.setMinimumWidth(400)
        progress.setWindowTitle("Sending Encrypted Statement")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        thread = StatementSubmissionThread(
            submission,
            credentials=credentials,
            parent=progress,
        )
        self._submission_thread = thread
        progress._submission_thread = thread
        progress.canceled.connect(thread.cancel)
        thread.stage_changed.connect(progress.setLabelText)

        def update_progress(sent: int, total: int) -> None:
            progress.setRange(0, total)
            progress.setValue(sent)

        def submitted() -> None:
            progress.setValue(progress.maximum())
            progress.close()
            self.submit_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            self.clear_fields()
            logger.success(f"Sent {fpath.name} to server")
            QMessageBox.information(
                self,
                "Statement Sent",
                "Server confirmed the end-to-end encrypted file transfer.",
            )

        def failed(message: str) -> None:
            progress.close()
            self.submit_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            logger.error(f"Failed to send statement to server: {message}")
            QMessageBox.critical(self, "Statement Not Sent", f"Failed to send statement:\n{message}")

        def cancelled() -> None:
            progress.close()
            self.submit_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            QMessageBox.information(self, "Submission Canceled", "The statement was not confirmed as received.")

        thread.progress_changed.connect(update_progress)
        thread.submitted.connect(submitted)
        thread.submission_failed.connect(failed)
        thread.submission_cancelled.connect(cancelled)
        thread.finished.connect(lambda: setattr(self, "_submission_thread", None))
        thread.finished.connect(thread.deleteLater)
        self.submit_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        thread.start()
        progress.show()

    def reject(self) -> None:
        thread = getattr(self, "_submission_thread", None)
        if thread is not None and thread.isRunning():
            thread.cancel()
            return
        super().reject()

    def closeEvent(self, event) -> None:
        thread = getattr(self, "_submission_thread", None)
        if thread is not None and thread.isRunning():
            thread.cancel()
            event.ignore()
            return
        super().closeEvent(event)

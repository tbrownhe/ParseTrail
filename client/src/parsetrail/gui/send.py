import os
import time
from pathlib import Path

from loguru import logger
from parsetrail.core.settings import settings
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
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
from parsetrail.core.crypto import encrypt_file
from parsetrail.core.api import api_client
from parsetrail.core.auth import AuthError


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
        self.clear_fields()

    def validate(self) -> bool:
        file_path = self.file_path_input.text().strip()
        institution = self.institution_input.text().strip()
        frequency = self.frequency_input.currentText()
        comments = self.comments_input.toPlainText().strip()

        # Validate inputs
        if not file_path:
            QMessageBox.warning(self, "Input Error", "Please select a file.")
            return False

        if os.path.getsize(file_path) > 26214400:
            QMessageBox.warning(self, "Input Error", "Attachments cannot exceed 25MB")
            return False

        if not institution:
            QMessageBox.warning(self, "Input Error", "Institution name is required.")
            return False

        if len(comments) > 256:
            QMessageBox.warning(self, "Input Error", "Comments must be 256 characters or less.")
            return False

        # Store validated result
        self.metadata = {
            "file_path": file_path,
            "file_name": os.path.basename(file_path),
            "institution": institution,
            "frequency": frequency,
            "comments": comments,
        }

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
        fpath = self.metadata.get("file_path")
        if not fpath:
            raise ValueError("No file_path found in metadata")

        fpath = Path(fpath).resolve()

        # Logging to user
        logger.info(f"Sending {fpath} to server")
        progress = QProgressDialog("Sending statement for plugin development...", "Cancel", 0, 4, self)
        progress.setMinimumWidth(400)
        progress.setWindowTitle("Sending Encrypted Statement")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.setMaximum(4)
        progress.show()
        QApplication.processEvents()

        # Last chance to abort
        for t in range(1, 4):
            time.sleep(1)
            progress.setValue(t)
            QApplication.processEvents()
            if progress.wasCanceled():
                QMessageBox.information(
                    self,
                    "Aborted",
                    "Aborted statement submission.",
                )
                return

        try:
            metadata = {k: v for k, v in self.metadata.items() if k != "file_path"}
            encrypted_file, encrypted_key = encrypt_file(fpath)
            resp = api_client.submit_statement(encrypted_file, encrypted_key, metadata)
            message = resp.json().get("message")

            progress.setValue(progress.maximum())

            # Confirm server received and stored the file
            if message == "SUCCESS":
                logger.success(f"Sent {fpath.name} to server")
                QMessageBox.information(
                    self,
                    "Statement Sent",
                    "Server confirmed End-to-End encrypted file transfer.",
                )
            else:
                logger.error(f"Server responded with error: {message}")
                QMessageBox.critical(
                    self,
                    "Statement Not Sent",
                    f"Server responded with error: {message}",
                )
        except AuthError as e:
            logger.error(f"Authentication error during statement send: {e}")
            QMessageBox.warning(
                self,
                "Authentication Required",
                "Could not authenticate with the server. Please log in and try again.",
            )
        except Exception as e:
            logger.error(f"Failed to send statement to server: {e}")
            QMessageBox.critical(
                self,
                "Statement Not Sent",
                f"Failed to send statement:\n{e}",
            )
        finally:
            progress.close()

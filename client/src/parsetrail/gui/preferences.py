from pathlib import Path

from loguru import logger
from pydantic import ValidationError
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from parsetrail.core.settings import (
    AppSettings,
    restore_defaults,
    save_settings,
    settings,
)


class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setWindowModality(Qt.ApplicationModal)

        # Main layout
        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)

        # Create grid layout for form fields
        self.grid_layout = QGridLayout()
        main_layout.addLayout(self.grid_layout)

        # Initialize row counter
        self.row = 0

        # Add pydantic settings fields objects dynamically
        self.fields = {}
        self.add_fields()

        # Buttons
        button_layout = QHBoxLayout()
        main_layout.addLayout(button_layout)

        reset_button = QPushButton("Restore Defaults")
        reset_button.clicked.connect(self.reset_preferences)
        button_layout.addWidget(reset_button)

        save_button = QPushButton("Save")
        save_button.clicked.connect(self.save_preferences)
        button_layout.addWidget(save_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        # Set fixed window size
        hint = main_layout.sizeHint()
        self.setFixedSize(int(1.6 * hint.width()), int(hint.height() + 100))

    def add_fields(self):
        """Dynamically generate input fields for AppSettings attributes."""
        for field_name, field_info in settings.model_fields.items():
            # field_type = field_info.annotation
            description = field_info.description or field_name
            current_value = getattr(settings, field_name)

            if description == "NO EDIT":
                continue

            # Add Label
            label = QLabel(description + ":")
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.grid_layout.addWidget(label, self.row, 0)
            if isinstance(current_value, bool):
                # Add a checkbox for boolean fields
                checkbox = QCheckBox()
                checkbox.setChecked(current_value)
                self.grid_layout.addWidget(checkbox, self.row, 1)
                self.fields[field_name] = checkbox
            elif isinstance(current_value, Path):
                # Add a path selector for Path fields
                line_edit = QLineEdit(str(current_value))
                self.grid_layout.addWidget(line_edit, self.row, 1)
                select_button = QPushButton("Select...")
                field_metadata = AppSettings.model_fields[field_name].json_schema_extra or {}
                file_type = field_metadata.get("file_type", None)
                if file_type:
                    select_button.clicked.connect(lambda _, le=line_edit, ft=file_type: self.select_file(le, ft))
                else:
                    select_button.clicked.connect(lambda _, le=line_edit: self.select_directory(le))
                self.grid_layout.addWidget(select_button, self.row, 2)
                self.fields[field_name] = line_edit
            else:
                # Add a line edit for other types
                line_edit = QLineEdit(str(current_value))
                self.grid_layout.addWidget(line_edit, self.row, 1)
                self.fields[field_name] = line_edit

            self.row += 1

    def select_file(self, line_edit, file_type: str):
        """Open a file dialog to select a file path."""
        try:
            default_path = str(Path(line_edit.text()).resolve())
        except Exception:
            default_path = ""
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Select File",
            default_path,
            f"{file_type};;All Files (*)",
        )
        if fpath:
            fpath = Path(fpath).resolve()
            line_edit.setText(str(fpath))

    def select_directory(self, line_edit):
        """Open a file dialog to select a path."""
        try:
            default_path = str(Path(line_edit.text()).resolve())
        except Exception:
            default_path = ""
        selected_path = QFileDialog.getExistingDirectory(self, "Select Directory", default_path)
        if selected_path:
            line_edit.setText(selected_path)

    def save_preferences(self):
        """Validate and save preferences to the settings object."""
        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            "Confirm Save",
            "Are you sure you want to save the setup?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return

        # Get the values from the dialog
        updated_settings = {}
        for field_name, widget in self.fields.items():
            try:
                if isinstance(widget, QCheckBox):
                    updated_settings[field_name] = widget.isChecked()
                elif isinstance(widget, QLineEdit):
                    updated_settings[field_name] = widget.text()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Invalid Input",
                    f"Error processing field '{field_name}': {e}",
                )
                return

        try:
            # Validate new settings against type model
            validated_settings = AppSettings(**updated_settings)

            # Update the global settings object in place using validated and typed data
            # Note this leaves _hidden_fields completely untouched
            for field in validated_settings.model_fields.keys():
                setattr(settings, field, getattr(validated_settings, field))

            # Save the config.json
            save_settings(settings)

            QMessageBox.information(self, "Preferences Saved", "Preferences saved successfully.")
            self.accept()
        except ValidationError as e:
            # Display validation errors to the user
            error_message = "\n".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors())
            QMessageBox.critical(
                self,
                "Validation Error",
                f"The following errors occurred while saving preferences:\n{error_message}",
            )
        except Exception as e:
            logger.error(f"Failed to save preferences: {e}")
            QMessageBox.critical(
                self,
                "Save Failed",
                f"Failed to save preferences: {e}",
            )

    def reset_preferences(self):
        """Reset preferences to default values."""
        reply = QMessageBox.question(
            self,
            "Reset Preferences",
            "Are you sure you want to restore default preferences?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            defaults = restore_defaults(save=False)
            for field_name, widget in self.fields.items():
                value = getattr(defaults, field_name)
                if isinstance(widget, QCheckBox):
                    widget.setChecked(value)
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(value))
            QMessageBox.information(
                self,
                "Preferences Reset",
                "Preferences have been restored to defaults.",
            )

    def reject(self):
        reply = QMessageBox.question(
            self,
            "Confirm Exit",
            "Are you sure you want to cancel setup?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            super().reject()

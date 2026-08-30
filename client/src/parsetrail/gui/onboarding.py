"""Local-first onboarding wizard."""

from __future__ import annotations

from collections.abc import Mapping

from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout, QWizard, QWizardPage

from parsetrail.core.onboarding import installed_support_summary, mark_onboarding_complete, onboarding_needed
from parsetrail.core.settings import SettingsSaveError, settings


class FirstRunGuide(QWizard):
    def __init__(self, plugin_metadata: Mapping[str, Mapping[str, object]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Getting Started with ParseTrail")
        self.setMinimumSize(700, 520)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.HaveCustomButton1, True)
        self.setButtonText(QWizard.CustomButton1, "Skip Guide")
        self.setButtonText(QWizard.FinishButton, "Finish")
        self.customButtonClicked.connect(self._skip_guide)

        self.addPage(
            self._text_page(
                "Your financial data stays local",
                (
                    "Normal statement imports are parsed on this device. Transactions and account data are stored in "
                    f"a local SQLite database:\n\n{settings.db_path}\n\n"
                    f"Managed statement files are stored under:\n\n{settings.import_dir}\n\n"
                    "ParseTrail does not encrypt these local files. Device encryption, login security, and your backup "
                    "system protect them. Ordinary imports are not sent to the ParseTrail server."
                ),
            )
        )
        self.addPage(self._plugins_page(plugin_metadata))
        self.addPage(
            self._text_page(
                "Statement contribution is explicit",
                (
                    "Statements are sent only when you choose Statements > Send for Plugin Development and confirm. "
                    "The client encrypts the statement in memory before upload. The server temporarily decrypts it in "
                    "memory, re-encrypts it for storage, and never writes the plaintext statement to disk.\n\n"
                    "The server can associate the contribution with your account and can observe your IP address, user "
                    "agent, transfer size/timing, and the submitted filename, institution, frequency, and comments. "
                    "Those form fields are stored as plaintext metadata."
                ),
            )
        )
        self.addPage(
            self._text_page(
                "Back up both kinds of local data",
                (
                    "Use File > Back Up Database to create a consistent SQLite backup, then File > Test Database Backup "
                    "to rehearse a restore without changing your live database. File > Restore Database restores to a "
                    "new path and preserves the active database.\n\n"
                    "Database backups are plaintext and contain financial data. They do not include the managed "
                    "statement folders, so back up that folder separately if you want to retain source statements. "
                    "File > Database Location and Privacy shows both locations at any time."
                ),
            )
        )
        self.addPage(
            self._text_page(
                "Ready to import",
                (
                    "A useful first session is:\n\n"
                    "1. Check Plugins > Plugin Manager.\n"
                    "2. Add or review account names under Accounts > Edit Accounts.\n"
                    "3. Import one statement from the Statements menu.\n"
                    "4. Review imported transactions and categories.\n"
                    "5. Create and test a database backup.\n\n"
                    "Open Help > Getting Started whenever you want to see this guide again."
                ),
            )
        )

    @staticmethod
    def _text_page(title: str, text: str) -> QWizardPage:
        page = QWizardPage()
        page.setTitle(title)
        layout = QVBoxLayout(page)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(label)
        layout.addStretch()
        return page

    def _plugins_page(self, metadata: Mapping[str, Mapping[str, object]]) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Plugins define statement support")
        layout = QVBoxLayout(page)
        explanation = QLabel(
            "Parser plugins recognize specific institution and statement formats. Check Plugins > Plugin Manager to "
            "see versions or download updates. Downloaded plugin packages are signed; the client verifies them using "
            "its bundled public key before activation. If a current plugin no longer recognizes a statement, use "
            "Plugins > Troubleshoot Parsing or explicitly submit an example for development.\n\nInstalled support:"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        supported = QPlainTextEdit(installed_support_summary(metadata))
        supported.setReadOnly(True)
        layout.addWidget(supported)
        return page

    def accept(self) -> None:
        if self._record_completion():
            super().accept()

    def _skip_guide(self, _button: int) -> None:
        reply = QMessageBox.question(
            self,
            "Skip Getting Started?",
            "Mark the guide complete? You can reopen it later from Help > Getting Started.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes and self._record_completion():
            self.reject()

    def _record_completion(self) -> bool:
        try:
            mark_onboarding_complete(settings)
        except SettingsSaveError:
            logger.exception("Failed to record onboarding completion")
            QMessageBox.warning(
                self,
                "Guide Status Not Saved",
                "ParseTrail could not save this choice. The guide may appear again next time.",
            )
            return False
        return True


def show_first_run_guide(
    plugin_metadata: Mapping[str, Mapping[str, object]], parent=None, *, force: bool = False
) -> None:
    if force or onboarding_needed(settings):
        FirstRunGuide(plugin_metadata, parent=parent).exec()

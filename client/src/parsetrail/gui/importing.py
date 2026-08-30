"""Qt adapter for the headless statement import application service."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox, QProgressDialog

from parsetrail.core.diagnostics import Diagnostic
from parsetrail.core.parser_routing import ParseError, ParseWarningsRejectedError, present_parse_error
from parsetrail.core.settings import settings
from parsetrail.core.statements import SourceFileAction, StatementImportService
from parsetrail.gui.accounts import AssignAccountNumber


class StatementImportController(StatementImportService):
    """Present import decisions and progress while the service owns state changes."""

    def __init__(self, Session, plugin_manager, *, parent=None) -> None:
        self.parent = parent
        super().__init__(
            Session,
            plugin_manager,
            warning_decision=self._accept_warnings,
            account_resolver=self._resolve_account,
            move_retry_decision=self._retry_locked_move,
        )

    def _accept_warnings(self, warnings: Sequence[Diagnostic]) -> bool:
        warning_text = "\n".join(f"- {warning.message}" for warning in warnings)
        return (
            QMessageBox.question(
                self.parent,
                "Statement Validation Warnings",
                f"The parser reported:\n\n{warning_text}\n\nImport this statement anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    def _resolve_account(
        self,
        fpath: Path,
        account_num: str,
        plugin_metadata: Mapping[str, str] | None,
    ) -> int:
        dialog = AssignAccountNumber(
            self.Session,
            fpath,
            dict(plugin_metadata or {}),
            account_num,
            parent=self.parent,
        )
        if dialog.exec() == QDialog.Accepted:
            return dialog.get_account_id()
        raise RuntimeError("Account assignment was canceled.")

    def _retry_locked_move(self, fpath: Path, _dpath: Path, _error: PermissionError) -> bool:
        dialog = QMessageBox(self.parent)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("Unable to Archive File")
        dialog.setText(
            f"The file {fpath.name} could not be copied or moved into the archive. "
            "It might be open in another program. Please close it and try again.",
        )
        dialog.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        return dialog.exec() == QMessageBox.Ok

    def import_all(self) -> None:
        """Import every supported statement from the configured import directory."""
        suffixes = {plugin.get("SUFFIX", ".*") for plugin in self.plugin_manager.metadata.values()}
        fpaths = sorted({fpath for suffix in suffixes for fpath in settings.import_dir.glob(f"*{suffix}")})
        if not fpaths:
            QMessageBox.information(self.parent, "No Files", "No files found in the import directory.")
            return

        success, duplicate, recovered, fail = 0, 0, 0, 0
        failure_details: list[str] = []
        progress = QProgressDialog("Processing statements...", "Cancel", 0, len(fpaths), self.parent)
        progress.setWindowTitle("Import Progress")
        progress.setWindowModality(Qt.WindowModal)
        progress.setValue(0)

        for idx, fpath in enumerate(fpaths):
            progress.setLabelText(f"Processing {fpath.name}...")
            if progress.wasCanceled():
                QMessageBox.information(self.parent, "Import Canceled", "The import was canceled.")
                break

            try:
                result = self.import_one(fpath)
                if result == "success":
                    success += 1
                elif result == "duplicate":
                    duplicate += 1
                elif result == "recovered":
                    recovered += 1
            except ParseWarningsRejectedError as exc:
                progress.close()
                QMessageBox.information(self.parent, "Import Canceled", str(exc))
                break
            except ParseError as exc:
                fail += 1
                presentation = present_parse_error(exc)
                failure_details.append(f"{fpath.name}: {presentation.title}\n{presentation.message}")
                self.handle_failure(fpath, exc)
            except RuntimeError as exc:
                progress.close()
                dialog = QMessageBox(self.parent)
                dialog.setIcon(QMessageBox.Critical)
                dialog.setWindowTitle("Import Canceled")
                dialog.setText(str(exc))
                dialog.setStandardButtons(QMessageBox.Ok)
                dialog.setWindowModality(Qt.ApplicationModal)
                dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
                dialog.exec()
                break
            except Exception as exc:
                fail += 1
                self.handle_failure(fpath, exc)

            progress.setValue(idx + 1)

        progress.close()
        total = len(fpaths)
        remain = total - success - duplicate - recovered - fail
        summary = QMessageBox(self.parent)
        summary.setIcon(QMessageBox.Information if not failure_details else QMessageBox.Warning)
        summary.setWindowTitle("Import Summary")
        summary.setText(
            f"Successfully imported: {success} of {total} files\n"
            f"Duplicates: {duplicate}\n"
            f"Recovered archives: {recovered}\n"
            f"Failures: {fail}\n"
            f"Remaining: {remain}"
        )
        if failure_details:
            summary.setInformativeText(
                "Failed source files were moved to the FAIL folder. Expand details for next steps."
            )
            summary.setDetailedText("\n\n".join(failure_details))
        summary.exec()


def choose_source_file_action(parent, source: Path) -> SourceFileAction | None:
    """Explain one-off file ownership and return the user's explicit choice."""
    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Question)
    dialog.setWindowTitle("Keep or Move the Original Statement?")
    dialog.setText("Choose what ParseTrail should do after the statement data is committed.")
    dialog.setInformativeText(
        "Copy to Archive keeps the selected original and saves a managed copy (recommended).\n\n"
        "Move to Archive places the selected original in ParseTrail's SUCCESS folder.\n\n"
        "Leave in Place stores only the parsed data; ParseTrail will not keep a managed statement copy."
    )
    copy_button = dialog.addButton("Copy to Archive", QMessageBox.AcceptRole)
    move_button = dialog.addButton("Move to Archive", QMessageBox.ActionRole)
    leave_button = dialog.addButton("Leave in Place", QMessageBox.ActionRole)
    dialog.addButton(QMessageBox.Cancel)
    dialog.setDefaultButton(copy_button)

    if source.parent == settings.import_dir:
        copy_button.setEnabled(False)
        leave_button.setEnabled(False)
        dialog.setInformativeText(
            "This file is already in ParseTrail's managed import folder, so it will be moved to the SUCCESS archive "
            "after a successful import. Choose Cancel if you want to move it elsewhere first."
        )
        dialog.setDefaultButton(move_button)

    dialog.exec()
    clicked = dialog.clickedButton()
    if clicked is copy_button:
        return SourceFileAction.COPY
    if clicked is move_button:
        return SourceFileAction.ARCHIVE
    if clicked is leave_button:
        return SourceFileAction.LEAVE_IN_PLACE
    return None

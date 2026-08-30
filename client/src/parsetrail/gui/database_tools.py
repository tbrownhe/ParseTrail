"""Qt adapter for local database backup, verification, and restore."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from parsetrail.core.database_backup import DatabaseBackupError, DatabaseBackupService, DatabaseInspection
from parsetrail.core.settings import SettingsSaveError, save_settings, settings


class DatabaseToolsController:
    def __init__(self, parent) -> None:
        self.parent = parent

    def show_location(self) -> None:
        dialog = QMessageBox(self.parent)
        dialog.setIcon(QMessageBox.Information)
        dialog.setWindowTitle("Local Data and Database Location")
        dialog.setTextFormat(Qt.PlainText)
        dialog.setText(
            f"Financial database:\n{settings.db_path}\n\n"
            f"Managed statement folders:\n{settings.import_dir}\n\n"
            "The SQLite database, managed statement archive, and backups are stored locally and are not encrypted "
            "by ParseTrail. A database backup does not include statement files. Protect both locations with your "
            "device security and backup system."
        )
        dialog.exec()

    def create_backup(self) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        default = settings.download_dir / f"{settings.db_path.stem}-backup-{timestamp}.dbb"
        destination, _ = QFileDialog.getSaveFileName(
            self.parent,
            "Create Database Backup",
            str(default),
            "ParseTrail Database Backups (*.dbb);;SQLite Databases (*.db);;All Files (*)",
        )
        if not destination:
            return
        destination_path = Path(destination)
        if destination_path.suffix.lower() not in {".db", ".dbb"}:
            destination_path = destination_path.with_suffix(".dbb")
        try:
            inspection = DatabaseBackupService(settings.db_path).create_backup(destination_path)
        except DatabaseBackupError:
            logger.exception("Failed to create database backup")
            QMessageBox.critical(
                self.parent,
                "Backup Failed",
                "The database backup could not be created. See the application log for details.",
            )
            return
        QMessageBox.information(
            self.parent,
            "Backup Verified",
            (
                f"A consistent database backup was created and verified at:\n{inspection.path}\n\n"
                "This backup is not encrypted and does not include managed statement files."
            ),
        )

    def test_restore(self) -> None:
        backup = self._choose_backup("Select a Database Backup to Test")
        if backup is None:
            return
        try:
            inspection = DatabaseBackupService(settings.db_path).test_restore(backup)
        except DatabaseBackupError:
            logger.exception("Database restore test failed")
            QMessageBox.critical(
                self.parent,
                "Restore Test Failed",
                "The selected backup could not be restored and verified. See the application log for details.",
            )
            return
        QMessageBox.information(
            self.parent,
            "Restore Test Passed",
            self._inspection_text(inspection),
        )

    def restore(self) -> None:
        backup = self._choose_backup("Select a Database Backup to Restore")
        if backup is None:
            return
        service = DatabaseBackupService(settings.db_path)
        try:
            inspection = service.test_restore(backup)
        except DatabaseBackupError:
            logger.exception("Pre-restore database verification failed")
            QMessageBox.critical(
                self.parent,
                "Restore Blocked",
                "The selected backup failed its restore test. The active database was not changed.",
            )
            return

        default = settings.db_path.with_name(f"{settings.db_path.stem}-restored.db")
        destination, _ = QFileDialog.getSaveFileName(
            self.parent,
            "Restore as a New Database",
            str(default),
            "SQLite Databases (*.db);;All Files (*)",
        )
        if not destination:
            return
        destination_path = Path(destination)
        if destination_path.suffix.lower() != ".db":
            destination_path = destination_path.with_suffix(".db")

        reply = QMessageBox.question(
            self.parent,
            "Confirm Database Restore",
            (
                f"Restore the verified backup to a new database?\n\n"
                f"Backup: {inspection.path}\n"
                f"New database: {destination_path}\n\n"
                "The active database will not be overwritten. ParseTrail will switch to the restored copy and close; "
                "reopen it to migrate and use the restored database. Statement files are not restored."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        original_path = settings.db_path
        try:
            restored = service.restore_to(backup, destination_path)
            settings.db_path = restored.path
            save_settings(settings)
        except (DatabaseBackupError, SettingsSaveError):
            settings.db_path = original_path
            logger.exception("Failed to restore or select database backup")
            QMessageBox.critical(
                self.parent,
                "Restore Failed",
                "The active database was not changed. See the application log for details.",
            )
            return

        QMessageBox.information(
            self.parent,
            "Restore Ready",
            f"ParseTrail will now close. Reopen it to use the restored database at:\n{restored.path}",
        )
        QApplication.quit()

    def _choose_backup(self, title: str) -> Path | None:
        selected, _ = QFileDialog.getOpenFileName(
            self.parent,
            title,
            str(settings.download_dir),
            "ParseTrail Databases (*.dbb *.db);;All Files (*)",
        )
        return Path(selected).resolve() if selected else None

    @staticmethod
    def _inspection_text(inspection: DatabaseInspection) -> str:
        counts = "\n".join(f"{table}: {count} rows" for table, count in inspection.row_counts.items())
        revision = inspection.revision or "unversioned (migration will run when opened)"
        return (
            f"The backup restored successfully to a disposable test database.\n\n"
            f"Backup: {inspection.path}\n"
            f"Schema revision: {revision}\n{counts}\n\n"
            "The disposable test copy was removed; the selected backup and active database were not changed."
        )

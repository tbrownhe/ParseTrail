import os
import shutil
from pathlib import Path

from loguru import logger
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QMessageBox, QProgressDialog
from sqlalchemy.orm import Session, sessionmaker

from parsetrail.core import query
from parsetrail.core.orm import Plugins, Statements, Transactions
from parsetrail.core.parse import parse_any
from parsetrail.core.plugins import PluginManager
from parsetrail.core.settings import settings
from parsetrail.core.utils import hash_file
from parsetrail.core.validation import Statement, Transaction
from parsetrail.gui.accounts import AssignAccountNumber


class StatementProcessor:
    def __init__(self, Session: sessionmaker, plugin_manager: PluginManager) -> None:
        """Initialize the statement processor

        Args:
            plugin_manager: (PluginManager)
        """
        self.Session = Session
        self.plugin_manager = plugin_manager

    def import_all(self, parent=None) -> None:
        """
        Find all statements in the import directory and process them.

        Args:
            parent: Parent class for UI dialogs.
        """
        # Gather files to process
        suffixes = set([plugin.get("SUFFIX", ".*") for plugin in self.plugin_manager.metadata.values()])
        fpaths = [fpath for suffix in suffixes for fpath in settings.import_dir.glob(f"*{suffix}")]
        if not fpaths:
            QMessageBox.information(parent, "No Files", "No files found in the import directory.")
            return

        # Initialize counters
        success, duplicate, fail = 0, 0, 0

        # Progress dialog
        progress = QProgressDialog("Processing statements...", "Cancel", 0, len(fpaths), parent)
        progress.setWindowTitle("Import Progress")
        progress.setWindowModality(Qt.WindowModal)
        progress.setValue(0)

        for idx, fpath in enumerate(sorted(fpaths)):
            progress.setLabelText(f"Processing {fpath.name}...")
            if progress.wasCanceled():
                QMessageBox.information(parent, "Import Canceled", "The import was canceled.")
                break

            try:
                result = self.import_one(fpath)
                if result == "success":
                    success += 1
                elif result == "duplicate":
                    duplicate += 1
            except RuntimeError as e:
                # Stop the import loop immediately if a critical failure occurs
                progress.close()
                dialog = QMessageBox(parent)
                dialog.setIcon(QMessageBox.Critical)
                dialog.setWindowTitle("Import Canceled")
                dialog.setText(str(e))
                dialog.setStandardButtons(QMessageBox.Ok)
                dialog.setWindowModality(Qt.ApplicationModal)  # Ensure it's on top
                dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
                dialog.exec_()
                break
            except Exception as e:
                fail += 1
                self.handle_failure(fpath, e)

            progress.setValue(idx + 1)

        progress.close()

        # Summary dialog
        total = len(fpaths)
        remain = total - success - duplicate - fail
        QMessageBox.information(
            parent,
            "Import Summary",
            (
                f"Successfully imported: {success} of {total} files\n"
                f"Duplicates: {duplicate}\n"
                f"Failures: {fail}\n"
                f"Remaining: {remain}"
            ),
        )

    def import_one(self, fpath: Path) -> str:
        """
        Process a single statement file and import its data.

        Args:
            fpath (Path): Path to the statement file.

        Returns:
            str: "success" if successfully imported, "duplicate" if already imported.
        """
        try:
            md5hash = hash_file(fpath)

            # Check for duplicates by MD5 hash
            filename = self.file_already_imported(md5hash)
            if filename:
                self.handle_duplicate(fpath, filename)
                return "duplicate"

            # Parse the statement and validate its structure
            statement = parse_any(self.Session, self.plugin_manager, fpath)
            if not isinstance(statement, Statement):
                raise TypeError("Parsing module must return a Statement dataclass.")

            # Attach metadata
            statement.add_md5hash(md5hash)
            self.attach_account_info(statement)  # Modifies in place
            for account in statement.accounts:
                account.hash_transactions()
            statement.set_standard_dpath(settings.success_dir)

            # Check for duplicates by filename
            if self.statement_already_imported(statement.dpath.name):
                self.handle_duplicate(fpath, statement.dpath.name)
                return "duplicate"

            # Insert data into the database and move the file to the success directory
            with self.Session() as session:
                self.complete_data_transaction(session, statement)

            logger.success(f"Imported {fpath}")
            return "success"
        except Exception as e:
            logger.error(f"Failed to import {fpath.name}: {e}")
            raise

    def file_already_imported(self, md5hash: str) -> str:
        """Check if the file has already been saved to the db

        Args:
            md5hash (str): Byte hash of passed file

        Returns:
            bool: Whether md5hash exists in the db already
        """
        with self.Session() as session:
            data = query.statements_with_hash(session, md5hash)
        if len(data) == 0:
            return ""
        if len(data) > 1:
            raise KeyError(f"Multiple files found with MD5={md5hash}")
        statement_id, filename = data[0]
        logger.debug(f"Previously imported {filename} (StatementID: {statement_id}) has identical hash {md5hash}")
        return filename

    def statement_already_imported(self, filename: Path) -> bool:
        """Check if the file has already been saved to the db

        Args:
            filename (str): Name of statement file after standardization

        Returns:
            bool: Whether md56hash exists in the db already
        """
        with self.Session() as session:
            data = query.statements_with_filename(session, filename)
        if len(data) == 0:
            return False

        for statement_id, filename in data:
            logger.debug(f"Previously imported {filename} (StatementID: {statement_id})")
        return True

    def handle_failure(self, fpath: Path, error: Exception):
        """
        Handle failed statement imports by moving the file to the fail directory.

        Args:
            fpath (Path): Path to the failed statement file.
            error (Exception): The exception that occurred.
        """
        dpath = settings.fail_dir / fpath.name
        self.move_file_safely(fpath, dpath)
        logger.error(f"Failed to process {fpath.name}: {error}")

    def handle_duplicate(self, fpath: Path, filename: str):
        """
        Handle duplicate statement imports by moving the file to the duplicate directory.

        Args:
            fpath (Path): Path to the failed statement file.
            filename (str): Database filename of duplicate statement.
        """
        if (settings.success_dir / filename).exists():
            # Move to duplicate dir
            dpath = settings.duplicate_dir / filename
        else:
            # Restore missing file in success dir
            dpath = settings.success_dir / filename
        self.move_file_safely(fpath, dpath)
        logger.debug("Duplicate statement moved to {d}", d=dpath)

    def move_file_safely(self, fpath: Path, dpath: Path):
        """
        Move a file to the destination path safely. Ensure the destination directory exists.

        Args:
            fpath (Path): Source file path.
            dpath (Path): Destination file path.

        Raises:
            RuntimeError: If the move operation is cancelled or fails.
        """
        dpath.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                # Check for write lock, then move
                os.rename(fpath, fpath)
                shutil.move(fpath, dpath)
                return
            except PermissionError as e:
                # File is likely open in another program
                dialog = QMessageBox(None)
                dialog.setIcon(QMessageBox.Warning)
                dialog.setWindowTitle("Unable to Move File")
                dialog.setText(
                    f"The file {fpath.name} could not be moved. "
                    "It might be open in another program. Please close it and try again.",
                )
                dialog.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
                dialog.setWindowModality(Qt.ApplicationModal)  # Ensure it's on top
                dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
                if dialog.exec_() == QMessageBox.Cancel:
                    raise RuntimeError(f"File move operation for <pre>{fpath}</pre> was cancelled by the user.") from e
            except Exception as e:
                raise RuntimeError(f"An unexpected error occurred while moving <pre>{fpath}</pre>: {e}") from e

    def attach_account_info(self, statement: Statement) -> Statement:
        """
        Makes sure all accounts in the statement have an entry in the lookup table.
        Return the nicknames of all accounts
        """
        # Ensure an account-to-account_num association is set up for each account_num
        for account in statement.accounts:
            try:
                # Lookup existing account
                with self.Session() as session:
                    account_id = query.account_id_of_account_number(session, account.account_num)
            except KeyError:
                # Prompt user to select account to associate with this account_num
                plugin_metadata = self.plugin_manager.metadata.get(statement.plugin_name)
                try:
                    account_id = self.prompt_account_num(statement.fpath, account.account_num, plugin_metadata)
                except RuntimeError as e:
                    logger.error(f"Account assignment canceled: {e}")
                    raise

            # Get the account_name for this account_id
            with self.Session() as session:
                account_name = query.account_name_of_account_id(session, account_id)

            # Add the new data to the account
            account.add_account_info(account_id, account_name)

    def prompt_account_num(self, fpath: Path, account_num: str, plugin_metadata: dict, parent=None) -> int:
        """
        Ask user to associate this unknown account_num with an Accounts.AccountID
        """
        dialog = AssignAccountNumber(self.Session, fpath, plugin_metadata, account_num)
        if dialog.exec_() == QDialog.Accepted:
            return dialog.get_account_id()
        raise RuntimeError("Account assignment dialog was closed without selection.")

    def complete_data_transaction(self, session: Session, statement: Statement) -> None:
        """
        Inserts statement metadata and associated transactions into the database.
        Rolls back the entire operation if any error occurs.

        Args:
            session (Session): session instance
        """
        with session.begin():
            # Validate the plugin_name exists in the statement metadata
            if not statement.plugin_name:
                raise ValueError("Statement must include a valid plugin_name.")

            plugin_name = statement.plugin_name

            # Retrieve plugin metadata from PluginManager
            plugin_metadata = self.plugin_manager.metadata.get(plugin_name)
            if not plugin_metadata:
                raise ValueError(f"No metadata found for plugin: {plugin_name}")

            # Check if the plugin is already in the Plugins table
            plugin_entry = (
                session.query(Plugins)
                .filter_by(
                    PluginName=plugin_metadata["PLUGIN_NAME"],
                    Version=plugin_metadata["VERSION"],
                )
                .first()
            )

            if not plugin_entry:
                # Plugin does not exist in the table; insert it
                plugin_entry = Plugins(
                    PluginName=plugin_metadata["PLUGIN_NAME"],
                    Version=plugin_metadata["VERSION"],
                    Suffix=plugin_metadata["SUFFIX"],
                    Company=plugin_metadata["COMPANY"],
                    StatementType=plugin_metadata["STATEMENT_TYPE"],
                )
                session.add(plugin_entry)
                session.flush()  # Ensure PluginID is generated

            plugin_id = plugin_entry.PluginID

            for account in statement.accounts:
                # Validate account information
                if not account.account_id or not account.account_name:
                    raise ValueError(f"Account {account.account_num} must have account_id and account_name set.")

                # Prepare and insert statement metadata
                metadata = statement.to_db_row(account)
                statements_table = Statements(
                    **metadata,
                    PluginID=plugin_id,  # Associate with the plugin
                )
                session.add(statements_table)

                # Flush to get autogenerated StatementID
                session.flush()
                statement_id = statements_table.StatementID

                # Prepare transactions for insertion
                transactions_table = Transaction.to_db_rows(statement_id, account.account_id, account.transactions)

                # Insert transactions using insert_rows_carefully
                query.insert_rows_carefully(session, Transactions, transactions_table, skip_duplicates=True)

            # Attempt to move file to destination.
            # If it fails in this context, the whole transaction is rolled back.
            self.move_file_safely(statement.fpath, statement.dpath)

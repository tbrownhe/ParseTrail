import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Literal

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from parsetrail.core import query
from parsetrail.core.diagnostics import Diagnostic
from parsetrail.core.orm import Plugins, Statements, StatementTransactions, Transactions
from parsetrail.core.parse import parse_any
from parsetrail.core.parser_routing import ParseResult
from parsetrail.core.plugin_manager import PluginManager
from parsetrail.core.settings import settings
from parsetrail.core.utils import hash_file
from parsetrail.core.validation import Statement, Transaction


class ArchivePendingError(RuntimeError):
    """Database commit succeeded but the source statement still needs archiving."""


class AccountAssignmentRequiredError(RuntimeError):
    """An imported account number needs an adapter-provided account assignment."""

    def __init__(self, account_num: str) -> None:
        self.account_num = account_num
        super().__init__(f"Account {account_num} must be assigned before the statement can be imported.")


class SourceArchiveError(RuntimeError):
    """The source statement could not be copied or moved to its archive."""


class SourceFileAction(StrEnum):
    """What to do with a selected statement after its data is committed."""

    COPY = "copy"
    ARCHIVE = "archive"
    LEAVE_IN_PLACE = "leave_in_place"


ImportOutcome = Literal["success", "duplicate", "recovered"]


WarningDecision = Callable[[Sequence[Diagnostic]], bool]
AccountResolver = Callable[[Path, str, Mapping[str, str] | None], int]
MoveRetryDecision = Callable[[Path, Path, PermissionError], bool]


class StatementImportService:
    """Headless statement import, persistence, deduplication, and archive service."""

    def __init__(
        self,
        Session: sessionmaker,
        plugin_manager: PluginManager,
        *,
        warning_decision: WarningDecision | None = None,
        account_resolver: AccountResolver | None = None,
        move_retry_decision: MoveRetryDecision | None = None,
    ) -> None:
        """Initialize the statement import service.

        Args:
            plugin_manager: (PluginManager)
        """
        self.Session = Session
        self.plugin_manager = plugin_manager
        self.warning_decision = warning_decision
        self.account_resolver = account_resolver
        self.move_retry_decision = move_retry_decision

    def find_pending_archives(self) -> list[tuple[Path, Path]]:
        """Report committed imports whose original file still awaits archiving."""
        suffixes = {plugin.get("SUFFIX", ".*") for plugin in self.plugin_manager.metadata.values()}
        pending: list[tuple[Path, Path]] = []
        for source in sorted({path for suffix in suffixes for path in settings.import_dir.glob(f"*{suffix}")}):
            try:
                archive_name = self.file_already_imported(self._content_hashes(source))
            except Exception as exc:
                logger.warning(
                    "Could not inspect {} for archive recovery ({})",
                    source.name,
                    type(exc).__name__,
                )
                continue
            if not archive_name:
                continue
            destination = settings.success_dir / archive_name
            if not destination.exists():
                pending.append((source, destination))
        return pending

    def import_one(
        self,
        fpath: Path,
        *,
        source_action: SourceFileAction = SourceFileAction.ARCHIVE,
    ) -> ImportOutcome:
        """
        Process a single statement file and import its data.

        Args:
            fpath (Path): Path to the statement file.

        Returns:
            The import outcome, distinguishing recovered archives from duplicates.
        """
        try:
            source_action = SourceFileAction(source_action)
            content_hashes = self._content_hashes(fpath)

            # Check both the current digest and legacy MD5 rows during migration.
            filename = self.file_already_imported(content_hashes)
            if filename:
                return self.handle_duplicate(fpath, filename, source_action=source_action)

            # Parse the statement and validate its structure
            parse_result = parse_any(self.plugin_manager, fpath)
            statement = self._statement_from_result(parse_result)
            if not isinstance(statement, Statement):
                raise TypeError("Parsing module must return a Statement dataclass.")

            # Attach metadata
            statement.add_content_hash(content_hashes["sha256"])
            self.attach_account_info(statement)  # Modifies in place
            for account in statement.accounts:
                account.hash_transactions()
            statement.set_standard_dpath(settings.success_dir)

            # Check for duplicates by filename
            if self.statement_already_imported(statement.dpath.name):
                return self.handle_duplicate(fpath, statement.dpath.name, source_action=source_action)

            # Commit before moving the only source file. If archiving fails, the
            # committed hash lets the next import recover it deterministically.
            with self.Session() as session:
                self.complete_data_transaction(session, statement)
            try:
                self._apply_source_action(statement.fpath, statement.dpath, source_action)
            except Exception as exc:
                action = "archived" if source_action == SourceFileAction.ARCHIVE else "copied to the archive"
                raise ArchivePendingError(
                    f"The statement data was committed, but its source file could not be {action}. "
                    "The source remains recoverable; keep it in place and retry the import."
                ) from exc

            logger.success(f"Imported {fpath}")
            return "success"
        except Exception as e:
            logger.error(f"Failed to import {fpath.name}: {e}")
            raise

    def _apply_source_action(self, fpath: Path, dpath: Path, source_action: SourceFileAction) -> None:
        if source_action == SourceFileAction.ARCHIVE:
            self.move_file_safely(fpath, dpath)
        elif source_action == SourceFileAction.COPY:
            self.copy_file_safely(fpath, dpath)
        elif source_action != SourceFileAction.LEAVE_IN_PLACE:
            raise ValueError(f"Unsupported source file action: {source_action}")

    def _statement_from_result(self, result: ParseResult) -> Statement:
        if not result.warnings:
            return result.statement
        accepted = self.warning_decision(result.warnings) if self.warning_decision is not None else False
        return result.require_statement(accept_warnings=accepted)

    @staticmethod
    def _content_hashes(fpath: Path) -> dict[str, str]:
        return {
            "sha256": hash_file(fpath, "sha256"),
            "md5": hash_file(fpath, "md5"),
        }

    def file_already_imported(self, content_hashes: dict[str, str]) -> str:
        """Check if the file has already been saved to the db

        Args:
            content_hashes: Byte hashes keyed by algorithm.

        Returns:
            bool: Whether any supplied content hash exists in the database.
        """
        with self.Session() as session:
            data = query.statements_with_hashes(session, content_hashes)
        if len(data) == 0:
            return ""
        filenames = {filename for _, filename in data}
        if len(filenames) > 1:
            raise KeyError(f"Identical file hash is associated with multiple filenames: {sorted(filenames)}")
        filename = filenames.pop()
        statement_ids = [statement_id for statement_id, _ in data]
        logger.debug("Previously imported {} (StatementIDs: {}) has identical content", filename, statement_ids)
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

    def handle_duplicate(
        self,
        fpath: Path,
        filename: str,
        *,
        source_action: SourceFileAction = SourceFileAction.ARCHIVE,
    ) -> Literal["duplicate", "recovered"]:
        """
        Handle duplicate statement imports by moving the file to the duplicate directory.

        Args:
            fpath (Path): Path to the failed statement file.
            filename (str): Database filename of duplicate statement.
        """
        archive_path = settings.success_dir / filename
        if not archive_path.exists() and source_action != SourceFileAction.LEAVE_IN_PLACE:
            # Recover a prior database commit whose archive move did not finish.
            self._apply_source_action(fpath, archive_path, source_action)
            logger.info("Recovered committed statement archive at {}", archive_path)
            return "recovered"

        if source_action == SourceFileAction.ARCHIVE:
            duplicate_path = settings.duplicate_dir / filename
            self.move_file_safely(fpath, duplicate_path)
            logger.info("Duplicate statement moved to {}", duplicate_path)
        else:
            logger.info("Duplicate statement retained at {}", fpath)
        return "duplicate"

    def copy_file_safely(self, fpath: Path, dpath: Path) -> None:
        """Copy a source into the managed archive while retaining the original."""
        dpath.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                shutil.copy2(fpath, dpath)
                return
            except PermissionError as exc:
                if self.move_retry_decision is not None and self.move_retry_decision(fpath, dpath, exc):
                    continue
                raise SourceArchiveError(f"The file {fpath.name} could not be copied to the archive.") from exc
            except (OSError, shutil.Error) as exc:
                raise SourceArchiveError(f"The file {fpath.name} could not be copied to the archive.") from exc

    def move_file_safely(self, fpath: Path, dpath: Path):
        """Move a file, delegating only the locked-file retry decision.

        Args:
            fpath (Path): Source file path.
            dpath (Path): Destination file path.

        Raises:
            SourceArchiveError: If the move operation is cancelled or fails.
        """
        dpath.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                # Check for write lock, then move
                os.rename(fpath, fpath)
                shutil.move(fpath, dpath)
                return
            except PermissionError as e:
                if self.move_retry_decision is not None and self.move_retry_decision(fpath, dpath, e):
                    continue
                raise SourceArchiveError(f"The file {fpath.name} could not be moved.") from e
            except (OSError, shutil.Error) as e:
                raise SourceArchiveError(f"The file {fpath.name} could not be moved to the archive.") from e

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
                plugin_metadata = self.plugin_manager.metadata.get(statement.plugin_name)
                if self.account_resolver is None:
                    raise AccountAssignmentRequiredError(account.account_num)
                account_id = self.account_resolver(statement.fpath, account.account_num, plugin_metadata)

            # Get the account_name for this account_id
            with self.Session() as session:
                account_name = query.account_name_of_account_id(session, account_id)

            # Add the new data to the account
            account.add_account_info(account_id, account_name)

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

                transaction_rows = Transaction.to_db_rows(
                    account.account_id,
                    account.transactions,
                    account.currency_code,
                )
                for row_number, row in enumerate(transaction_rows, start=1):
                    transaction = session.scalar(
                        select(Transactions).where(Transactions.Fingerprint == row["Fingerprint"])
                    )
                    if transaction is None:
                        transaction = Transactions(**row)
                        session.add(transaction)
                        session.flush()
                    elif any(
                        (
                            transaction.AccountID != account.account_id,
                            transaction.PostingDate != row["PostingDate"],
                            transaction.AmountMinor != row["AmountMinor"],
                            transaction.BalanceMinor != row["BalanceMinor"],
                            transaction.CurrencyCode != row["CurrencyCode"],
                            transaction.Description != row["Description"],
                        )
                    ):
                        raise RuntimeError("A transaction fingerprint resolved to different canonical fields.")

                    session.add(
                        StatementTransactions(
                            StatementID=statement_id,
                            TransactionID=transaction.TransactionID,
                            StatementRow=row_number,
                        )
                    )


# Retain the established import name while callers migrate to the service name.
StatementProcessor = StatementImportService

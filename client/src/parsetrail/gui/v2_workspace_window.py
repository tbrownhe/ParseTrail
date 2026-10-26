"""Separate 2.0 desktop shell for verified, unposted source imports."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.source_evidence import ActivityExportPayload, StatementPayload
from parsetrail.core.v2_cash_movement import cash_account_labels
from parsetrail.core.v2_profile_store import (
    CARD_STATEMENT_PARSERS,
    FinancialAccount,
    ProfileFormatError,
    V2ProfileStore,
)
from parsetrail.core.v2_source_import import ImportCancelled, SourceImportResult
from parsetrail.core.v2_workspace import V2Workspace, WorkspaceError, folder_source_files
from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview
from parsetrail.gui.v2_batch_import import V2BatchImportReport, V2BatchImportWorker
from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
from parsetrail.gui.v2_cash_movement import V2CashMovementDialog
from parsetrail.gui.v2_categories import V2CategoryDialog
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
from parsetrail.gui.v2_opening_review import V2OpeningReview
from parsetrail.gui.v2_path_notice import show_data_locations, show_path_notice
from parsetrail.gui.v2_profile_startup import choose_new_workspace
from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
from parsetrail.gui.v2_source_account_review import V2SourceAccountReview
from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog
from parsetrail.gui.v2_transfer_review import V2TransferReview
from parsetrail.gui.v2_workspace_help import show_workspace_about, show_workspace_help


class V2ImportWorker(QThread):
    """Keep bounded parsing off the GUI thread and expose a cancellation flag."""

    def __init__(self, workspace: V2Workspace, source_path: Path, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.source_path = source_path
        self.cancel_event = Event()
        self.result: SourceImportResult | None = None
        self.error: Exception | None = None

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            self.result = self.workspace.import_file(self.source_path, cancelled=self.cancel_event.is_set)
        except Exception as exc:
            self.error = exc


class V2FinancialAccountDialog(QDialog):
    """Record an account exactly as the owner describes it."""

    def __init__(self, parent=None, *, existing: FinancialAccount | None = None, scope_locked: bool = False):
        super().__init__(parent)
        self.existing = existing
        self.setWindowTitle("Edit financial account" if existing is not None else "Add financial account")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setMaxLength(200)
        if existing is not None:
            self.name.setText(existing.name)
        form.addRow("Account name", self.name)
        self.kind = QComboBox()
        self.kind.addItem("Asset (cash or investment)", "asset")
        self.kind.addItem("Liability (card or loan)", "liability")
        if existing is not None:
            self.kind.setCurrentIndex(self.kind.findData(existing.kind))
            self.kind.setEnabled(False)
        form.addRow("Account kind", self.kind)
        self.scope = QComboBox()
        self._populate_scopes(existing.tracking_scope if existing is not None else "account_total")
        self.kind.currentIndexChanged.connect(lambda: self._populate_scopes(self.scope.currentData()))
        self.scope.setEnabled(not scope_locked)
        form.addRow("Tracking scope", self.scope)
        scope_note = QLabel(
            "Scope specifies the amount represented by this account. Account totals, loan principal and cash "
            "components are different values. Scope becomes fixed when reviewed history is saved."
            + (" This account's scope is fixed by its history." if scope_locked else "")
        )
        scope_note.setWordWrap(True)
        form.addRow(scope_note)
        self.institution = QLineEdit()
        self.institution.setPlaceholderText("e.g. mohela")
        self.institution.setMaxLength(80)
        if existing is not None:
            self.institution.setText(existing.institution_key)
        form.addRow("Institution key", self.institution)
        self.number = QLineEdit()
        self.number.setPlaceholderText("Optional; full number only")
        self.number.setMaxLength(80)
        if existing is not None:
            self.number.setText(existing.full_account_number or "")
        form.addRow("Full account number", self.number)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _populate_scopes(self, selected: str) -> None:
        self.scope.clear()
        self.scope.addItem("Whole account", "account_total")
        if self.kind.currentData() == "asset":
            self.scope.addItem("Cash component only", "cash_component")
        else:
            self.scope.addItem("Loan principal only", "principal_component")
        self.scope.setCurrentIndex(max(0, self.scope.findData(selected)))

    def account(self) -> FinancialAccount:
        return FinancialAccount(
            id=self.existing.id if self.existing is not None else uuid4().hex,
            name=self.name.text().strip(),
            kind=self.kind.currentData(),
            institution_key=self.institution.text().strip(),
            full_account_number=self.number.text().strip() or None,
            tracking_scope=self.scope.currentData(),
        )


class V2WorkspaceWindow(QMainWindow):
    """Open only an explicitly selected fresh profile and verified catalog cache."""

    def __init__(self, workspace: V2Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.import_worker: V2ImportWorker | V2BatchImportWorker | None = None
        self.progress: QProgressDialog | None = None
        self._close_after_import = False
        self.setWindowTitle("ParseTrail 2.0 workspace")
        self.resize(1050, 560)
        profile_menu = self.menuBar().addMenu("Profile")
        self.new_profile_action = profile_menu.addAction("New 2.0 profile…")
        self.new_profile_action.triggered.connect(self._new_profile)
        self.open_profile_action = profile_menu.addAction("Open 2.0 profile…")
        self.open_profile_action.triggered.connect(self._choose_profile)
        self.data_locations_action = profile_menu.addAction("Data locations and privacy…")
        self.data_locations_action.triggered.connect(self._show_data_locations)
        self.backup_profile_action = profile_menu.addAction("Back up current profile…")
        self.backup_profile_action.triggered.connect(self._backup_profile)
        self.restore_profile_action = profile_menu.addAction("Restore backup as new profile…")
        self.restore_profile_action.triggered.connect(self._restore_profile)
        self.recover_source_action = profile_menu.addAction("Save selected source original…")
        self.recover_source_action.triggered.connect(self._recover_source_original)
        settings_menu = self.menuBar().addMenu("Settings")
        self.abbreviated_matching_action = QAction(
            "Allow abbreviated account numbers to automatically match to ledger", self
        )
        self.abbreviated_matching_action.setCheckable(True)
        self.abbreviated_matching_action.setChecked(workspace.preferences().allow_abbreviated_account_matching)
        self.abbreviated_matching_action.toggled.connect(self._set_abbreviated_matching)
        settings_menu.addAction(self.abbreviated_matching_action)
        self.assumed_posting_action = QAction(
            "Allow best guess posting dates when a statement does not print one", self
        )
        self.assumed_posting_action.setCheckable(True)
        self.assumed_posting_action.setChecked(workspace.preferences().allow_assumed_posting_dates)
        self.assumed_posting_action.setToolTip(
            "This applies to reviewed accounting entries. Saved source evidence does not change."
        )
        self.assumed_posting_action.toggled.connect(self._set_assumed_posting_dates)
        settings_menu.addAction(self.assumed_posting_action)
        accounts_menu = self.menuBar().addMenu("Accounts")
        self.add_financial_account_action = accounts_menu.addAction("Add financial account…")
        self.add_financial_account_action.triggered.connect(self._add_account)
        self.edit_financial_account_action = accounts_menu.addAction("Edit financial account…")
        self.edit_financial_account_action.triggered.connect(self._edit_account)
        self.account_anchors_action = accounts_menu.addAction("Reviewed openings, dated values and closure…")
        self.account_anchors_action.triggered.connect(self._review_account_anchors)
        self.source_opening_action = accounts_menu.addAction("Review source-backed opening…")
        self.source_opening_action.triggered.connect(self._review_openings)
        review_menu = self.menuBar().addMenu("Review")
        self.transfer_review_action = review_menu.addAction("Owned transfers and card payments…")
        self.transfer_review_action.triggered.connect(self._review_transfers)
        self.settlement_review_action = review_menu.addAction("Transfer fees and partial settlements…")
        self.settlement_review_action.triggered.connect(self._review_settlements)
        reports_menu = self.menuBar().addMenu("Reports")
        self.reviewed_reports_action = reports_menu.addAction("Reviewed reports…")
        self.reviewed_reports_action.triggered.connect(self._open_reviewed_reports)
        self.cash_movement_action = reports_menu.addAction("Cash movement by reviewed purpose…")
        self.cash_movement_action.triggered.connect(
            lambda: V2CashMovementDialog(self.workspace.profile_path, self).exec()
        )
        help_menu = self.menuBar().addMenu("Help")
        self.getting_started_action = help_menu.addAction("Getting started…")
        self.getting_started_action.triggered.connect(lambda: show_workspace_help(self))
        self.about_action = help_menu.addAction("About this workspace…")
        self.about_action.triggered.connect(lambda: show_workspace_about(self))
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self.profile_label = QLineEdit(str(workspace.profile_path))
        self.profile_label.setReadOnly(True)
        self.profile_label.setCursorPosition(0)
        profile_row.addWidget(self.profile_label)
        layout.addLayout(profile_row)
        catalog_controls = QHBoxLayout()
        self.catalog_label = QLabel()
        catalog_controls.addWidget(self.catalog_label)
        self.install_catalog_button = QPushButton("Install signed catalog…")
        self.install_catalog_button.setToolTip("Choose a folder containing catalog.json and catalog.sig")
        self.install_catalog_button.clicked.connect(self._choose_catalog_release)
        catalog_controls.addWidget(self.install_catalog_button)
        catalog_controls.addStretch()
        layout.addLayout(catalog_controls)
        layout.addWidget(QLabel("Saved source evidence (review status depends on each row)"))
        self.sources = QListWidget()
        self.sources.currentItemChanged.connect(self._update_controls)
        self.sources.itemDoubleClicked.connect(self._preview)
        layout.addWidget(self.sources)
        self.selected_details = QLabel()
        self.selected_details.setWordWrap(True)
        layout.addWidget(self.selected_details)
        controls = QHBoxLayout()
        self.import_button = QPushButton("Import source…")
        self.import_button.clicked.connect(self._choose_import)
        controls.addWidget(self.import_button)
        self.import_folder_button = QPushButton("Import folder…")
        self.import_folder_button.clicked.connect(self._choose_import_folder)
        controls.addWidget(self.import_folder_button)
        self.preview_button = QPushButton("Preview evidence")
        self.preview_button.clicked.connect(self._preview)
        controls.addWidget(self.preview_button)
        self.cash_review_button = QPushButton("Review cash activity")
        self.cash_review_button.clicked.connect(self._review_cash_activity)
        controls.addWidget(self.cash_review_button)
        self.card_review_button = QPushButton("Review card purchases")
        self.card_review_button.clicked.connect(self._review_card_purchases)
        controls.addWidget(self.card_review_button)
        self.transfer_review_button = QPushButton("Review transfers")
        self.transfer_review_button.clicked.connect(self._review_transfers)
        controls.addWidget(self.transfer_review_button)
        self.reports_button = QPushButton("Reviewed reports")
        self.reports_button.clicked.connect(self._open_reviewed_reports)
        controls.addWidget(self.reports_button)
        self.coverage_button = QPushButton("Statement coverage")
        self.coverage_button.clicked.connect(self._open_statement_coverage)
        controls.addWidget(self.coverage_button)
        controls.addStretch()
        layout.addLayout(controls)
        account_controls = QHBoxLayout()
        self.source_review_button = QPushButton("Review source accounts")
        self.source_review_button.clicked.connect(self._review_source_account)
        account_controls.addWidget(self.source_review_button)
        self.overlap_review_button = QPushButton("Review repeated rows")
        self.overlap_review_button.clicked.connect(self._review_source_overlap)
        account_controls.addWidget(self.overlap_review_button)
        self.review_button = QPushButton("Review unidentified rows")
        self.review_button.clicked.connect(self._review_account)
        account_controls.addWidget(self.review_button)
        self.account_button = QPushButton("Add financial account")
        self.account_button.clicked.connect(self._add_account)
        account_controls.addWidget(self.account_button)
        self.edit_account_button = QPushButton("Edit financial account")
        self.edit_account_button.clicked.connect(self._edit_account)
        account_controls.addWidget(self.edit_account_button)
        self.categories_button = QPushButton("Categories")
        self.categories_button.clicked.connect(self._edit_categories)
        account_controls.addWidget(self.categories_button)
        self.openings_button = QPushButton("Review openings")
        self.openings_button.clicked.connect(self._review_openings)
        account_controls.addWidget(self.openings_button)
        account_controls.addStretch()
        layout.addLayout(account_controls)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self, select_source: str | None = None) -> None:
        catalog = self.workspace.catalog_cache.load_current()
        self.catalog_label.setText(
            f"Verified catalog release {catalog.release_sequence}"
            if catalog is not None
            else "No verified catalog installed. Choose Install signed catalog to enable import."
        )
        self.import_button.setEnabled(catalog is not None and self.import_worker is None)
        self.import_folder_button.setEnabled(catalog is not None and self.import_worker is None)
        for action in (
            self.new_profile_action,
            self.open_profile_action,
            self.backup_profile_action,
            self.restore_profile_action,
            self.transfer_review_action,
            self.settlement_review_action,
        ):
            action.setEnabled(self.import_worker is None)
        self.transfer_review_button.setEnabled(self.import_worker is None)
        prior = select_source or self._selected_source()
        self.sources.clear()
        for source_id in self.workspace.source_ids():
            item = QListWidgetItem(f"Source {source_id[:16]}…")
            item.setData(Qt.UserRole, source_id)
            item.setToolTip(source_id)
            self.sources.addItem(item)
            if source_id == prior:
                self.sources.setCurrentItem(item)
        if self.sources.currentItem() is None and self.sources.count():
            self.sources.setCurrentRow(0)
        self.status.setText(f"{self.sources.count()} saved source(s). Imported rows start pending review.")
        self._update_controls()

    def _selected_source(self) -> str | None:
        item = self.sources.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _update_controls(self, *_args) -> None:
        source_id = self._selected_source()
        self.recover_source_action.setEnabled(source_id is not None and self.import_worker is None)
        self.preview_button.setEnabled(source_id is not None)
        self.cash_review_button.setEnabled(source_id is not None)
        self.card_review_button.setEnabled(False)
        unidentified_rows = False
        identified_accounts = False
        if source_id is not None:
            evidence = self.workspace.saved_import(source_id).evidence
            self.card_review_button.setEnabled(evidence.parser_id in CARD_STATEMENT_PARSERS)
            payload = evidence.payload
            rows = (
                sum(len(account.rows) for account in payload.accounts)
                if isinstance(payload, StatementPayload)
                else len(payload.rows)
            )
            kind = "Statement" if isinstance(payload, StatementPayload) else "Activity export"
            details = f"{kind} · {evidence.parser_id} · {rows} row(s) · review rows for posting status"
            if isinstance(payload, StatementPayload):
                overlaps = self.workspace.overlapping_statement_sources(source_id)
                if overlaps:
                    other_sources = ", ".join(source[:16] for source in overlaps[:3])
                    if len(overlaps) > 3:
                        other_sources += f", and {len(overlaps) - 3} more"
                    details += f"\nPossible period overlap on an explicitly linked account: {other_sources}. Review before posting."
            self.selected_details.setText(details)
            unidentified_rows = isinstance(payload, ActivityExportPayload) and any(
                row.source_account is None for row in payload.rows
            )
            identified_accounts = isinstance(payload, StatementPayload) or any(
                row.source_account is not None for row in payload.rows
            )
        else:
            self.selected_details.clear()
        self.review_button.setEnabled(unidentified_rows)
        self.source_review_button.setEnabled(identified_accounts)

    def _choose_import(self) -> None:
        sources, _filter = QFileDialog.getOpenFileNames(
            self,
            "Select statements or exports",
            "",
            "Supported sources (*.csv *.pdf);;CSV exports (*.csv);;PDF statements (*.pdf)",
            options=QFileDialog.ReadOnly,
        )
        if len(sources) == 1:
            self.start_import(Path(sources[0]))
        elif sources:
            self.start_batch_import(tuple(Path(source) for source in sources))

    def _choose_import_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select a folder of statements or exports")
        if not directory:
            return
        try:
            paths = folder_source_files(Path(directory))
        except WorkspaceError as exc:
            QMessageBox.warning(self, "Folder was not imported", str(exc))
            return
        self.start_batch_import(paths)

    def _choose_catalog_release(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select a signed catalog release folder")
        if not directory:
            return
        try:
            release = self.workspace.install_catalog_release(Path(directory))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Catalog was not installed", str(exc))
            return
        self.refresh()
        self.status.setText(f"Verified catalog release {release.release_sequence} installed.")

    def _new_profile(self) -> None:
        if self.import_worker is not None:
            return
        selected = choose_new_workspace(
            self,
            self.workspace.profile_path.parent,
            self.workspace.catalog_cache.root,
            trusted_keys=self.workspace.catalog_cache.trusted_keys,
            preferences_path=self.workspace.preferences_path,
        )
        if selected is not None:
            self._select_workspace(selected)

    def _select_workspace(self, selected: V2Workspace) -> None:
        previous = self.workspace
        previous_source = self._selected_source()
        try:
            selected.verify_local_configuration()
            source_ids = selected.source_ids()
            candidate_source = previous_source if previous_source in source_ids else next(iter(source_ids), None)
            if candidate_source is not None:
                selected.saved_import(candidate_source)
                selected.overlapping_statement_sources(candidate_source)
            self.workspace = selected
            self.refresh()
        except (ProfileFormatError, sqlite3.Error, OSError, ValueError) as exc:
            self.workspace = previous
            try:
                self.refresh(select_source=previous_source)
            except (ProfileFormatError, sqlite3.Error, OSError, ValueError):
                self.sources.clear()
                self.import_button.setEnabled(False)
                self.import_folder_button.setEnabled(False)
                self._update_controls()
                self.status.setText(
                    "The current profile is retained, but its view could not refresh. Reopen it to retry."
                )
            QMessageBox.warning(self, "Profile was not opened", str(exc))
            return
        self.profile_label.setText(str(selected.profile_path))
        self.profile_label.setCursorPosition(0)
        self.status.setText("Opened 2.0 profile. Its path is shown above.")

    def _switch_profile(self, path: Path) -> None:
        if self.import_worker is not None:
            return
        try:
            selected = V2Workspace.open(
                path,
                self.workspace.catalog_cache.root,
                trusted_keys=self.workspace.catalog_cache.trusted_keys,
                preferences_path=self.workspace.preferences_path,
            )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Profile was not opened", str(exc))
            return
        self._select_workspace(selected)

    def _choose_profile(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Open a 2.0 profile",
            str(self.workspace.profile_path.parent),
            "ParseTrail profiles (*.db);;All files (*)",
            options=QFileDialog.ReadOnly,
        )
        if selected:
            if Path(selected).suffix.lower() != ".db":
                QMessageBox.warning(self, "Profile was not opened", "Choose a .db profile. Restore .dbb backups first.")
                return
            self._switch_profile(Path(selected))

    def _show_data_locations(self) -> None:
        show_data_locations(
            self,
            self.workspace.profile_path,
            self.workspace.catalog_cache.root,
            self.workspace.preferences_path,
        )

    def _recover_source_original(self) -> None:
        source_id = self._selected_source()
        if source_id is None or self.import_worker is not None:
            return
        try:
            saved_import = self.workspace.saved_import(source_id)
            proposed = self.workspace.profile_path.with_name(f"source-{source_id[:16]}{saved_import.suffix}")
            selected, _filter = QFileDialog.getSaveFileName(
                self, "Save selected source original", str(proposed), "All files (*)"
            )
            if not selected:
                return
            saved = self.workspace.recover_source_original(source_id, Path(selected))
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Source original was not saved", str(exc))
            return
        show_path_notice(
            self,
            "Source original saved",
            "Saved the exact original document retained in this profile:",
            saved,
            "This file contains financial data and is not encrypted by ParseTrail. "
            "The profile and its saved evidence were not changed.",
        )

    def _backup_profile(self) -> None:
        if self.import_worker is not None:
            return
        proposed = self.workspace.profile_path.with_name(f"{self.workspace.profile_path.stem}-backup.dbb")
        selected, _filter = QFileDialog.getSaveFileName(
            self, "Back up current 2.0 profile", str(proposed), "ParseTrail backups (*.dbb);;All files (*)"
        )
        if not selected:
            return
        destination = Path(selected)
        if not destination.suffix:
            destination = destination.with_suffix(".dbb")
        try:
            saved = V2ProfileStore.snapshot_to(self.workspace.profile_path, destination)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Backup was not created", str(exc))
            return
        show_path_notice(
            self,
            "Backup verified",
            "Verified 2.0 profile backup:",
            saved,
            "This file contains financial source evidence and is not encrypted by ParseTrail.",
        )

    def _restore_profile(self) -> None:
        if self.import_worker is not None:
            return
        backup, _filter = QFileDialog.getOpenFileName(
            self,
            "Select a 2.0 profile backup",
            str(self.workspace.profile_path.parent),
            "ParseTrail backups (*.dbb *.db);;All files (*)",
            options=QFileDialog.ReadOnly,
        )
        if not backup:
            return
        proposed = self.workspace.profile_path.with_name(f"{self.workspace.profile_path.stem}-restored.db")
        selected, _filter = QFileDialog.getSaveFileName(
            self, "Restore to a new 2.0 profile", str(proposed), "ParseTrail profiles (*.db);;All files (*)"
        )
        if not selected:
            return
        destination = Path(selected)
        if not destination.suffix:
            destination = destination.with_suffix(".db")
        try:
            restored = V2ProfileStore.snapshot_to(Path(backup), destination)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Restore was not created", str(exc))
            return
        self._switch_profile(restored)

    def start_import(self, source_path: Path) -> None:
        if self.import_worker is not None:
            return
        self.import_worker = V2ImportWorker(self.workspace, source_path, self)
        self.import_worker.finished.connect(self._import_finished)
        self.progress = QProgressDialog("Importing source evidence…", "Cancel import", 0, 0, self)
        self.progress.setWindowTitle("ParseTrail 2.0 import")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.canceled.connect(self.import_worker.cancel)
        self.import_button.setEnabled(False)
        self.import_folder_button.setEnabled(False)
        self.recover_source_action.setEnabled(False)
        for action in (
            self.new_profile_action,
            self.open_profile_action,
            self.backup_profile_action,
            self.restore_profile_action,
        ):
            action.setEnabled(False)
        self.progress.show()
        self.import_worker.start()

    def start_batch_import(self, paths: tuple[Path, ...]) -> None:
        if self.import_worker is not None or not paths:
            return
        self.import_worker = V2BatchImportWorker(self.workspace, paths, self)
        self.import_worker.progressed.connect(self._batch_progress)
        self.import_worker.finished.connect(self._import_finished)
        self.progress = QProgressDialog("Importing source evidence…", "Cancel remaining imports", 0, len(paths), self)
        self.progress.setWindowTitle("ParseTrail 2.0 batch import")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.canceled.connect(self.import_worker.cancel)
        self.import_button.setEnabled(False)
        self.import_folder_button.setEnabled(False)
        self.recover_source_action.setEnabled(False)
        for action in (
            self.new_profile_action,
            self.open_profile_action,
            self.backup_profile_action,
            self.restore_profile_action,
        ):
            action.setEnabled(False)
        self.progress.show()
        self.import_worker.start()

    def _batch_progress(self, count: int, filename: str) -> None:
        if self.progress is not None:
            self.progress.setLabelText(f"Processed {count} source(s); last: {filename}")
            self.progress.setValue(count)

    def _import_finished(self) -> None:
        worker = self.import_worker
        if worker is None:
            return
        result, error = worker.result, worker.error
        if self.progress is not None:
            self.progress.close()
            self.progress.deleteLater()
            self.progress = None
        self.import_worker = None
        worker.deleteLater()
        self.recover_source_action.setEnabled(self._selected_source() is not None)
        for action in (
            self.new_profile_action,
            self.open_profile_action,
            self.backup_profile_action,
            self.restore_profile_action,
        ):
            action.setEnabled(True)
        if self._close_after_import:
            QTimer.singleShot(0, self.close)
            return
        if isinstance(worker, V2BatchImportWorker):
            if result is None:
                self.refresh()
                self.status.setText("Batch import could not start.")
                QMessageBox.warning(self, "Batch import failed", str(error or "Unknown import error"))
                return
            imported = [item for item in result.files if item.status == "imported"]
            self.refresh(select_source=imported[-1].source_sha256 if imported else None)
            failures = sum(item.status == "failed" for item in result.files)
            self.status.setText(
                f"Batch finished: {len(imported)} imported, {failures} failed; saved evidence is pending review."
            )
            V2BatchImportReport(result, self).exec()
            return
        if result is not None:
            self.refresh(select_source=result.source_sha256)
            self.status.setText(
                "Source imported; evidence is pending review."
                if result.status == "imported"
                else "This exact source was already imported."
            )
        elif isinstance(error, ImportCancelled):
            self.status.setText("Import cancelled; no new source saved.")
            self.import_button.setEnabled(self.workspace.catalog_cache.load_current() is not None)
            self.import_folder_button.setEnabled(self.import_button.isEnabled())
        else:
            self.status.setText("Import failed; no new source saved.")
            self.import_button.setEnabled(self.workspace.catalog_cache.load_current() is not None)
            self.import_folder_button.setEnabled(self.import_button.isEnabled())
            QMessageBox.warning(self, "Import failed", str(error or "Unknown import error"))

    def _preview(self, *_args) -> None:
        source_id = self._selected_source()
        if source_id is not None:
            V2EvidencePreview(self.workspace.saved_import(source_id), self).exec()

    def _review_cash_activity(self) -> None:
        source_id = self._selected_source()
        if source_id is not None:
            V2CashActivityReview(self.workspace.profile_path, source_id, self).exec()
            self.refresh(select_source=source_id)

    def _review_card_purchases(self) -> None:
        source_id = self._selected_source()
        if source_id is not None:
            V2CardPurchaseReview(self.workspace, source_id, self).exec()
            self.assumed_posting_action.blockSignals(True)
            self.assumed_posting_action.setChecked(self.workspace.preferences().allow_assumed_posting_dates)
            self.assumed_posting_action.blockSignals(False)
            self.refresh(select_source=source_id)

    def _review_transfers(self) -> None:
        if self.import_worker is not None:
            return
        V2TransferReview(self.workspace, self).exec()
        self.assumed_posting_action.blockSignals(True)
        self.assumed_posting_action.setChecked(self.workspace.preferences().allow_assumed_posting_dates)
        self.assumed_posting_action.blockSignals(False)
        self.refresh()

    def _review_settlements(self) -> None:
        if self.import_worker is not None:
            return
        from parsetrail.gui.v2_settlement_review import V2SettlementReview

        V2SettlementReview(self.workspace, parent=self).exec()
        self.assumed_posting_action.blockSignals(True)
        self.assumed_posting_action.setChecked(self.workspace.preferences().allow_assumed_posting_dates)
        self.assumed_posting_action.blockSignals(False)
        self.refresh()

    def _open_reviewed_reports(self) -> None:
        V2ReviewedReportsDialog(self.workspace.profile_path, self).exec()

    def _open_statement_coverage(self) -> None:
        V2StatementCoverageDialog(self.workspace.profile_path, self).exec()

    def _review_account(self) -> None:
        source_id = self._selected_source()
        if source_id is not None:
            V2AccountBindingReview(self.workspace.profile_path, source_id, self).exec()
            self.refresh(select_source=source_id)

    def _review_source_account(self) -> None:
        source_id = self._selected_source()
        if source_id is not None:
            V2SourceAccountReview(self.workspace, source_id, self).exec()
            self.refresh(select_source=source_id)

    def _review_source_overlap(self) -> None:
        V2SourceOverlapReview(self.workspace.profile_path, self).exec()
        self.refresh()

    def _set_abbreviated_matching(self, enabled: bool) -> None:
        try:
            self.workspace.set_allow_abbreviated_account_matching(enabled)
        except (OSError, ValueError) as exc:
            self.abbreviated_matching_action.blockSignals(True)
            self.abbreviated_matching_action.setChecked(not enabled)
            self.abbreviated_matching_action.blockSignals(False)
            QMessageBox.warning(self, "Preference was not saved", str(exc))

    def _set_assumed_posting_dates(self, enabled: bool) -> None:
        try:
            self.workspace.set_allow_assumed_posting_dates(enabled)
        except (OSError, ValueError) as exc:
            self.assumed_posting_action.blockSignals(True)
            self.assumed_posting_action.setChecked(not enabled)
            self.assumed_posting_action.blockSignals(False)
            QMessageBox.warning(self, "Preference was not saved", str(exc))

    def _add_account(self) -> None:
        dialog = V2FinancialAccountDialog(self)
        while dialog.exec() == QDialog.Accepted:
            try:
                with V2ProfileStore.open(self.workspace.profile_path) as store:
                    store.add_financial_account(dialog.account())
            except (ProfileFormatError, sqlite3.Error, OSError) as exc:
                QMessageBox.warning(self, "Account was not saved", str(exc))
                continue
            self.status.setText(
                "Financial account and tracking scope saved. Bind sources or review its opening and values."
            )
            break

    def _edit_account(self) -> None:
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                accounts = store.financial_accounts()
            identities = cash_account_labels(accounts)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Account details are unavailable", str(exc))
            return
        if not accounts:
            QMessageBox.information(self, "No financial accounts", "Add a financial account before editing one.")
            return
        labels = [f"{identities[account.id]} · ID {account.id}" for account in accounts]
        selected, accepted = QInputDialog.getItem(self, "Edit financial account", "Account", labels, 0, False)
        if not accepted:
            return
        account = accounts[labels.index(selected)]
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                scope_locked = store.financial_account_scope_locked(account.id)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Account details are unavailable", str(exc))
            return
        dialog = V2FinancialAccountDialog(self, existing=account, scope_locked=scope_locked)
        while dialog.exec() == QDialog.Accepted:
            try:
                with V2ProfileStore.open(self.workspace.profile_path) as store:
                    store.update_financial_account(dialog.account())
            except (ProfileFormatError, sqlite3.Error, OSError) as exc:
                QMessageBox.warning(self, "Account was not saved", str(exc))
                continue
            self.status.setText("Financial account details saved. Existing source bindings and postings keep this ID.")
            self._update_controls()
            break

    def _edit_categories(self) -> None:
        V2CategoryDialog(self.workspace.profile_path, self).exec()

    def _review_openings(self) -> None:
        V2OpeningReview(self.workspace, self).exec()

    def _review_account_anchors(self) -> None:
        if self.import_worker is not None:
            return
        from parsetrail.gui.v2_account_anchors import V2AccountAnchors

        V2AccountAnchors(self.workspace.profile_path, parent=self).exec()
        self.refresh()

    def closeEvent(self, event) -> None:
        if self.import_worker is not None:
            self._close_after_import = True
            self.import_worker.cancel()
            self.status.setText("Cancelling import before closing…")
            event.ignore()
            return
        super().closeEvent(event)

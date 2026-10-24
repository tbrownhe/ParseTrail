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
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_import import ImportCancelled, SourceImportResult
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview
from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
from parsetrail.gui.v2_categories import V2CategoryDialog
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
from parsetrail.gui.v2_source_account_review import V2SourceAccountReview


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

    def __init__(self, parent=None, *, existing: FinancialAccount | None = None):
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

    def account(self) -> FinancialAccount:
        return FinancialAccount(
            id=self.existing.id if self.existing is not None else uuid4().hex,
            name=self.name.text().strip(),
            kind=self.kind.currentData(),
            institution_key=self.institution.text().strip(),
            full_account_number=self.number.text().strip() or None,
        )


class V2WorkspaceWindow(QMainWindow):
    """Open only an explicitly selected fresh profile and verified catalog cache."""

    def __init__(self, workspace: V2Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.import_worker: V2ImportWorker | None = None
        self.progress: QProgressDialog | None = None
        self._close_after_import = False
        self.setWindowTitle("ParseTrail 2.0 workspace")
        self.resize(1050, 560)
        settings_menu = self.menuBar().addMenu("Settings")
        self.abbreviated_matching_action = QAction(
            "Allow abbreviated account numbers to automatically match to ledger", self
        )
        self.abbreviated_matching_action.setCheckable(True)
        self.abbreviated_matching_action.setChecked(workspace.preferences().allow_abbreviated_account_matching)
        self.abbreviated_matching_action.toggled.connect(self._set_abbreviated_matching)
        settings_menu.addAction(self.abbreviated_matching_action)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        self.profile_label = QLabel(f"Profile: {workspace.profile_path}")
        self.profile_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.profile_label)
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
        self.preview_button = QPushButton("Preview evidence")
        self.preview_button.clicked.connect(self._preview)
        controls.addWidget(self.preview_button)
        self.cash_review_button = QPushButton("Review cash activity")
        self.cash_review_button.clicked.connect(self._review_cash_activity)
        controls.addWidget(self.cash_review_button)
        self.reports_button = QPushButton("Reviewed reports")
        self.reports_button.clicked.connect(self._open_reviewed_reports)
        controls.addWidget(self.reports_button)
        controls.addStretch()
        layout.addLayout(controls)
        account_controls = QHBoxLayout()
        self.source_review_button = QPushButton("Review source accounts")
        self.source_review_button.clicked.connect(self._review_source_account)
        account_controls.addWidget(self.source_review_button)
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
        self.preview_button.setEnabled(source_id is not None)
        self.cash_review_button.setEnabled(source_id is not None)
        unidentified_rows = False
        identified_accounts = False
        if source_id is not None:
            evidence = self.workspace.saved_import(source_id).evidence
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
        source, _filter = QFileDialog.getOpenFileName(
            self,
            "Select a statement or export",
            "",
            "Supported sources (*.csv *.pdf);;CSV exports (*.csv);;PDF statements (*.pdf)",
            options=QFileDialog.ReadOnly,
        )
        if source:
            self.start_import(Path(source))

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
        self.progress.show()
        self.import_worker.start()

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
        if self._close_after_import:
            QTimer.singleShot(0, self.close)
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
        else:
            self.status.setText("Import failed; no new source saved.")
            self.import_button.setEnabled(self.workspace.catalog_cache.load_current() is not None)
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

    def _open_reviewed_reports(self) -> None:
        V2ReviewedReportsDialog(self.workspace.profile_path, self).exec()

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

    def _set_abbreviated_matching(self, enabled: bool) -> None:
        try:
            self.workspace.set_allow_abbreviated_account_matching(enabled)
        except (OSError, ValueError) as exc:
            self.abbreviated_matching_action.blockSignals(True)
            self.abbreviated_matching_action.setChecked(not enabled)
            self.abbreviated_matching_action.blockSignals(False)
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
            self.status.setText("Financial account saved. Select an accountless export to assign it.")
            break

    def _edit_account(self) -> None:
        with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
            accounts = store.financial_accounts()
        if not accounts:
            QMessageBox.information(self, "No financial accounts", "Add a financial account before editing one.")
            return
        labels = [f"{account.name} ({account.kind}, {account.id})" for account in accounts]
        selected, accepted = QInputDialog.getItem(self, "Edit financial account", "Account", labels, 0, False)
        if not accepted:
            return
        account = accounts[labels.index(selected)]
        dialog = V2FinancialAccountDialog(self, existing=account)
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

    def closeEvent(self, event) -> None:
        if self.import_worker is not None:
            self._close_after_import = True
            self.import_worker.cancel()
            self.status.setText("Cancelling import before closing…")
            event.ignore()
            return
        super().closeEvent(event)

"""Separate 2.0 desktop shell for verified, unposted source imports."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_cash_movement import cash_account_labels
from parsetrail.core.v2_liability_register import REGISTER_PARSER
from parsetrail.core.v2_profile_store import (
    CARD_STATEMENT_PARSERS,
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
from parsetrail.gui.v2_document_browser import (
    DocumentInventoryWorker,
    document_period,
    document_status,
    document_title,
)
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
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


class V2WorkspaceWindow(QMainWindow):
    """Open only an explicitly selected fresh profile and verified catalog cache."""

    def __init__(self, workspace: V2Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.import_worker: V2ImportWorker | V2BatchImportWorker | None = None
        self.progress: QProgressDialog | None = None
        self._close_after_import = False
        self._inventory_worker = None
        self._inventory_generation = 0
        self._inventory_requested = False
        self._inventory_selection = None
        self._inventory_account_selection = None
        self._inventory_profile = None
        self._document_summaries = {}
        self._closing = False
        self._search_prior_source = None
        self.setWindowTitle("ParseTrail 2.0 workspace")
        self.resize(1050, 700)
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
        self.abbreviated_matching_action = QAction("Suggest accounts using abbreviated account numbers", self)
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
        self.source_values_action = accounts_menu.addAction("Review statement closing values…")
        self.source_values_action.triggered.connect(self._review_source_values)
        self.source_opening_action = accounts_menu.addAction("Review source-backed opening…")
        self.source_opening_action.triggered.connect(self._review_openings)
        review_menu = self.menuBar().addMenu("Review")
        self.transfer_review_action = review_menu.addAction("Owned transfers and liability repayments…")
        self.transfer_review_action.triggered.connect(self._review_transfers)
        self.settlement_review_action = review_menu.addAction("Transfer fees and partial settlements…")
        self.settlement_review_action.triggered.connect(self._review_settlements)
        self.loan_payment_action = review_menu.addAction("Evidenced loan principal and interest…")
        self.loan_payment_action.triggered.connect(self._review_loan_payments)
        self.register_review_action = review_menu.addAction("Review selected liability register…")
        self.register_review_action.triggered.connect(self._review_register_activity)
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
        body = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setAccessibleName("Workspace navigation")
        self.navigation.addItems(("Documents", "Review", "Accounts", "Reports"))
        self.navigation.setFixedWidth(142)
        body.addWidget(self.navigation)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        documents = QWidget()
        document_layout = QVBoxLayout(documents)
        self.pages.addWidget(documents)
        imports = QHBoxLayout()
        self.import_button = QPushButton("Import documents…")
        self.import_button.clicked.connect(self._choose_import)
        imports.addWidget(self.import_button)
        self.import_folder_button = QPushButton("Import folder…")
        self.import_folder_button.clicked.connect(self._choose_import_folder)
        imports.addWidget(self.import_folder_button)
        imports.addStretch()
        document_layout.addLayout(imports)
        self.document_search = QLineEdit()
        self.document_search.setPlaceholderText("Find an account, statement period or document type")
        self.document_search.setAccessibleName("Find documents")
        self.document_search.setClearButtonEnabled(True)
        self.document_search.textChanged.connect(self._filter_documents)
        document_layout.addWidget(self.document_search)
        inventory_row = QHBoxLayout()
        self.inventory_status = QLabel("Loading saved documents…")
        self.inventory_status.setWordWrap(True)
        inventory_row.addWidget(self.inventory_status, 1)
        self.retry_inventory = QPushButton("Reload documents")
        self.retry_inventory.clicked.connect(lambda: self.refresh())
        inventory_row.addWidget(self.retry_inventory)
        document_layout.addLayout(inventory_row)
        self.sources = QListWidget()
        self.sources.setAccessibleName("Saved documents")
        self.sources.setWordWrap(True)
        self.sources.currentItemChanged.connect(self._update_controls)
        self.sources.itemDoubleClicked.connect(self._review_document)
        document_layout.addWidget(self.sources, 1)
        self.selected_details = QLabel()
        self.selected_details.setWordWrap(True)
        self.selected_details.setTextFormat(Qt.PlainText)
        self.selected_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        document_layout.addWidget(self.selected_details)
        document_actions = QHBoxLayout()
        self.review_document_button = QPushButton("Review document")
        self.review_document_button.clicked.connect(self._review_document)
        document_actions.addWidget(self.review_document_button)
        self.preview_button = QPushButton("Preview evidence")
        self.preview_button.clicked.connect(self._preview)
        document_actions.addWidget(self.preview_button)
        self.document_details_button = QPushButton("Show details")
        self.document_details_button.setCheckable(True)
        document_actions.addWidget(self.document_details_button)
        document_actions.addStretch()
        document_layout.addLayout(document_actions)
        self.document_technical_details = QPlainTextEdit()
        self.document_technical_details.setReadOnly(True)
        self.document_technical_details.setAccessibleName("Document evidence details")
        self.document_technical_details.setMaximumHeight(140)
        self.document_technical_details.setVisible(False)
        self.document_details_button.toggled.connect(self.document_technical_details.setVisible)
        document_layout.addWidget(self.document_technical_details)

        review = QWidget()
        review_layout = QVBoxLayout(review)
        self.pages.addWidget(review)
        self.review_context = QLabel("Choose a document to review.")
        self.review_context.setWordWrap(True)
        self.review_context.setTextFormat(Qt.PlainText)
        review_layout.addWidget(self.review_context)
        choose_document = QPushButton("Choose a document")
        choose_document.clicked.connect(lambda: self.navigation.setCurrentRow(0))
        review_layout.addWidget(choose_document, alignment=Qt.AlignLeft)
        account_group = QGroupBox("1. Confirm the account")
        account_controls = QHBoxLayout(account_group)
        self.source_review_button = QPushButton("Confirm document accounts")
        self.source_review_button.clicked.connect(self._review_source_account)
        account_controls.addWidget(self.source_review_button)
        self.review_button = QPushButton("Assign rows without an account")
        self.review_button.clicked.connect(self._review_account)
        account_controls.addWidget(self.review_button)
        review_layout.addWidget(account_group)
        self.account_assignment_status = QLabel()
        self.account_assignment_status.setWordWrap(True)
        review_layout.addWidget(self.account_assignment_status)
        activity_group = QGroupBox("2. Review activity")
        activity_layout = QVBoxLayout(activity_group)
        controls = QHBoxLayout()
        self.cash_review_button = QPushButton("Review cash activity")
        self.cash_review_button.clicked.connect(self._review_cash_activity)
        controls.addWidget(self.cash_review_button)
        self.card_review_button = QPushButton("Review card purchases")
        self.card_review_button.clicked.connect(self._review_card_purchases)
        controls.addWidget(self.card_review_button)
        self.transfer_review_button = QPushButton("Review transfers")
        self.transfer_review_button.clicked.connect(self._review_transfers)
        controls.addWidget(self.transfer_review_button)
        activity_layout.addLayout(controls)
        specialized = QHBoxLayout()
        self.register_button = QPushButton("Review loan register")
        self.register_button.clicked.connect(self._review_register_activity)
        specialized.addWidget(self.register_button)
        settlement_button = QPushButton("Fees and partial transfers…")
        settlement_button.clicked.connect(self._review_settlements)
        specialized.addWidget(settlement_button)
        loan_button = QPushButton("Loan principal and interest…")
        loan_button.clicked.connect(self._review_loan_payments)
        specialized.addWidget(loan_button)
        activity_layout.addLayout(specialized)
        specialized.setContentsMargins(12, 0, 12, 0)
        self.review_guidance = QLabel()
        self.review_guidance.setWordWrap(True)
        activity_layout.addWidget(self.review_guidance)
        review_layout.addWidget(activity_group)
        checks = QGroupBox("3. Check supporting evidence")
        checks_layout = QHBoxLayout(checks)
        self.overlap_review_button = QPushButton("Check possible repeated rows")
        self.overlap_review_button.clicked.connect(self._review_source_overlap)
        checks_layout.addWidget(self.overlap_review_button)
        check_statement = QPushButton("Statement checks…")
        check_statement.clicked.connect(self._open_statement_coverage)
        checks_layout.addWidget(check_statement)
        review_layout.addWidget(checks)
        review_note = QLabel(
            "Importing does not add transactions to reports. Review supported activity explicitly. "
            "You can review spending while an opening balance is still unknown."
        )
        review_note.setWordWrap(True)
        review_layout.addWidget(review_note)
        review_layout.addStretch()

        accounts = QWidget()
        accounts_layout = QVBoxLayout(accounts)
        self.pages.addWidget(accounts)
        accounts_note = QLabel(
            "Set up your accounts, then review opening balances or dated values when you have supporting information. "
            "An unknown opening is not zero."
        )
        accounts_note.setWordWrap(True)
        accounts_layout.addWidget(accounts_note)
        self.accounts_list = QListWidget()
        self.accounts_list.setAccessibleName("Your financial accounts")
        self.accounts_list.setWordWrap(True)
        accounts_layout.addWidget(self.accounts_list, 1)
        self.accounts_list.itemDoubleClicked.connect(self._edit_account)
        self.accounts_status = QLabel("Loading accounts…")
        self.accounts_status.setWordWrap(True)
        accounts_layout.addWidget(self.accounts_status)
        self.account_button = QPushButton("Add account…")
        self.account_button.clicked.connect(self._add_account)
        accounts_layout.addWidget(self.account_button, alignment=Qt.AlignLeft)
        self.edit_account_button = QPushButton("Edit account…")
        self.edit_account_button.clicked.connect(self._edit_account)
        accounts_layout.addWidget(self.edit_account_button, alignment=Qt.AlignLeft)
        self.openings_button = QPushButton("Review source-backed openings…")
        self.openings_button.clicked.connect(self._review_openings)
        accounts_layout.addWidget(self.openings_button, alignment=Qt.AlignLeft)
        anchors_button = QPushButton("Openings, dated values and account closure…")
        anchors_button.clicked.connect(self._review_account_anchors)
        accounts_layout.addWidget(anchors_button, alignment=Qt.AlignLeft)
        self.categories_button = QPushButton("Categories and budgets…")
        self.categories_button.clicked.connect(self._edit_categories)
        accounts_layout.addWidget(self.categories_button, alignment=Qt.AlignLeft)
        positions_button = QPushButton("View account positions…")
        positions_button.clicked.connect(self._open_account_positions)
        accounts_layout.addWidget(positions_button, alignment=Qt.AlignLeft)

        reports = QWidget()
        report_layout = QVBoxLayout(reports)
        self.pages.addWidget(reports)
        reports_note = QLabel(
            "Reports use reviewed entries. Pending activity and missing history can limit what the totals tell you. "
            "Each report shows its dates and account scope."
        )
        reports_note.setWordWrap(True)
        report_layout.addWidget(reports_note)
        self.reports_button = QPushButton("Reviewed reports")
        self.reports_button.clicked.connect(self._open_reviewed_reports)
        report_layout.addWidget(self.reports_button, alignment=Qt.AlignLeft)
        report_layout.addWidget(QLabel("Spending, income, budgets, account movement and positions"))
        movement_button = QPushButton("Cash movement…")
        movement_button.clicked.connect(lambda: V2CashMovementDialog(self.workspace.profile_path, self).exec())
        report_layout.addWidget(movement_button, alignment=Qt.AlignLeft)
        movement_note = QLabel(
            "Choose the cash accounts to include; transfers and repayments remain separate from spending."
        )
        movement_note.setWordWrap(True)
        report_layout.addWidget(movement_note)
        self.coverage_button = QPushButton("Statement coverage and checks…")
        self.coverage_button.clicked.connect(self._open_statement_coverage)
        report_layout.addWidget(self.coverage_button, alignment=Qt.AlignLeft)
        coverage_note = QLabel(
            "Inspect saved periods, source arithmetic and separate live or saved reconciliation decisions."
        )
        coverage_note.setWordWrap(True)
        report_layout.addWidget(coverage_note)
        report_layout.addStretch()
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self.status = QLabel()
        self.status.setWordWrap(True)
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
            self.loan_payment_action,
            self.register_review_action,
            self.account_anchors_action,
            self.source_values_action,
        ):
            action.setEnabled(self.import_worker is None)
        self.transfer_review_button.setEnabled(self.import_worker is None)
        self._inventory_selection = select_source or self._selected_source()
        current_account = self.accounts_list.currentItem()
        if current_account is not None:
            self._inventory_account_selection = current_account.data(Qt.UserRole)
        self.accounts_list.clear()
        self.accounts_status.setText("Loading accounts…")
        if self._inventory_profile != self.workspace.profile_path:
            self.sources.clear()
            self._inventory_profile = self.workspace.profile_path
        self._inventory_generation += 1
        self._inventory_requested = True
        self._document_summaries = {}
        self.inventory_status.setText("Loading saved documents…")
        self.status.setText("Imported documents stay pending review until you confirm their activity.")
        self._update_controls()
        QTimer.singleShot(0, self._start_inventory)

    @property
    def inventory_pending(self) -> bool:
        return self._inventory_requested or self._inventory_worker is not None

    def _start_inventory(self) -> None:
        if self._closing or self._inventory_worker is not None or not self._inventory_requested:
            return
        self._inventory_requested = False
        worker = DocumentInventoryWorker(self.workspace.profile_path, self._inventory_generation, self)
        self._inventory_worker = worker
        worker.finished.connect(self._inventory_finished)
        worker.start()

    def _inventory_finished(self) -> None:
        worker = self._inventory_worker
        if worker is None:
            return
        self._inventory_worker = None
        if self._closing:
            worker.deleteLater()
            QTimer.singleShot(0, self.close)
            return
        if worker.generation == self._inventory_generation:
            if worker.error is not None:
                self.sources.clear()
                self._document_summaries = {}
                self.inventory_status.setText("Documents are unavailable. Reload to retry; saved data has not changed.")
                self.inventory_status.setToolTip(str(worker.error))
                self.accounts_list.clear()
                self.accounts_status.setText("Account choices unavailable. Reload documents to retry.")
            else:
                self.inventory_status.setToolTip("")
                self._apply_inventory(worker.result)
                selected_id = self._inventory_account_selection
                labels = cash_account_labels(worker.accounts)
                self.accounts_list.clear()
                for account in worker.accounts:
                    item = QListWidgetItem(labels[account.id])
                    item.setData(Qt.UserRole, account.id)
                    item.setToolTip(item.text())
                    self.accounts_list.addItem(item)
                    if account.id == selected_id:
                        self.accounts_list.setCurrentItem(item)
                self.accounts_status.setText(
                    f"{len(worker.accounts)} accounts · view positions for supported balances and history"
                    if worker.accounts
                    else "No accounts yet. Add an account to connect your documents."
                )
            self._update_controls()
        worker.deleteLater()
        if self._inventory_requested:
            QTimer.singleShot(0, self._start_inventory)

    def _apply_inventory(self, summaries) -> None:
        self._document_summaries = {summary.source_sha256: summary for summary in summaries}
        prior = self._inventory_selection
        scroll = self.sources.verticalScrollBar().value()
        self.sources.blockSignals(True)
        existing = {self.sources.item(i).data(Qt.UserRole): self.sources.item(i) for i in range(self.sources.count())}
        for source_id, item in existing.items():
            if source_id not in self._document_summaries:
                self.sources.takeItem(self.sources.row(item))
        for position, summary in enumerate(summaries):
            item = existing.get(summary.source_sha256)
            if item is None:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, summary.source_sha256)
                self.sources.insertItem(position, item)
            elif self.sources.row(item) != position:
                self.sources.takeItem(self.sources.row(item))
                self.sources.insertItem(position, item)
            item.setText(f"{document_title(summary)}\n{document_period(summary)} · {document_status(summary)}")
            item.setToolTip(f"{item.text()}\nParser: {summary.parser_id}\nSource: {summary.source_sha256}")
            if summary.source_sha256 == prior:
                self.sources.setCurrentItem(item)
        self.sources.blockSignals(False)
        if self.sources.currentItem() is None and self.sources.count():
            self.sources.setCurrentRow(0)
        self.sources.verticalScrollBar().setValue(scroll)
        self._filter_documents(self.document_search.text())

    def _filter_documents(self, query: str) -> None:
        words = query.casefold().split()
        if words and self._search_prior_source is None:
            self._search_prior_source = self._selected_source()
        visible = []
        for i in range(self.sources.count()):
            item = self.sources.item(i)
            summary = self._document_summaries.get(item.data(Qt.UserRole))
            searchable = item.text() + (f" {summary.parser_id}" if summary else "")
            item.setHidden(not all(word in searchable.casefold() for word in words))
            if not item.isHidden():
                visible.append(item)
        if not words and self._search_prior_source:
            for item in visible:
                if item.data(Qt.UserRole) == self._search_prior_source:
                    self.sources.setCurrentItem(item)
                    break
            self._search_prior_source = None
        current = self.sources.currentItem()
        if current is None or current.isHidden():
            self.sources.setCurrentItem(visible[0] if visible else None)
        if not self.inventory_pending:
            self.inventory_status.setText(
                f"{len(visible)} of {self.sources.count()} documents"
                if words
                else f"{self.sources.count()} saved documents · select one to continue"
                if self.sources.count()
                else "No documents yet. Import a bank statement PDF or a supported CSV export to begin."
            )
        self._update_controls()

    def _selected_source(self) -> str | None:
        item = self.sources.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _update_controls(self, *_args) -> None:
        source_id = self._selected_source()
        summary = self._document_summaries.get(source_id)
        available = summary is not None and self.import_worker is None and not self._closing
        self.recover_source_action.setEnabled(available)
        self.preview_button.setEnabled(available)
        self.review_document_button.setEnabled(available)
        self.document_details_button.setEnabled(available)
        is_card = summary is not None and summary.parser_id in CARD_STATEMENT_PARSERS
        is_register = summary is not None and summary.parser_id == REGISTER_PARSER
        self.cash_review_button.setEnabled(available and not is_card and not is_register)
        self.cash_review_button.setVisible(not is_card and not is_register)
        self.card_review_button.setEnabled(available and is_card)
        self.card_review_button.setVisible(is_card)
        self.register_review_action.setEnabled(available and is_register)
        self.register_button.setEnabled(available and is_register)
        self.register_button.setVisible(is_register)
        self.source_review_button.setEnabled(available and summary.has_identified_accounts)
        self.review_button.setEnabled(available and summary.has_unidentified_rows)
        if summary is not None:
            details = f"{document_title(summary)}\n{document_period(summary)} · {summary.row_count} source row(s)"
            if summary.overlapping_source_ids:
                details += (
                    f"\nPossible period overlap with {len(summary.overlapping_source_ids)} other document(s) "
                    "on a confirmed account. Check possible repeated rows before posting."
                )
            self.selected_details.setText(details)
            related = []
            for other_id in summary.overlapping_source_ids:
                other = self._document_summaries.get(other_id)
                related.append(f"{document_title(other)} · {document_period(other)}\n{other_id}" if other else other_id)
            self.document_technical_details.setPlainText(
                f"Parser: {summary.parser_id}\nSource SHA-256: {summary.source_sha256}\n"
                f"Date origins: start {summary.start_provenance}; end {summary.end_provenance}. "
                "Activity counts are conservative and can include supporting repeats. "
                "Full allocation does not establish complete source capture or reconciliation."
                + ("\nPossibly overlapping documents:\n" + "\n".join(related) if summary.overlapping_source_ids else "")
            )
            self.review_context.setText(f"{details}\n{document_status(summary)}")
            self.account_assignment_status.setText(
                f"{summary.unassigned_source_accounts} document account(s) need confirmation."
                if summary.unassigned_source_accounts
                else f"{summary.unassigned_activity_rows} activity row(s) still need a confirmed account."
                if summary.unassigned_activity_rows
                else "No account assignments outstanding for this document."
            )
            self.review_document_button.setText(
                "Confirm account"
                if summary.unassigned_activity_rows or summary.unassigned_source_accounts
                else "Review activity"
                if summary.pending_activity_rows
                else "Review document"
            )
            self.review_guidance.setText(
                "Confirm the document account first. Suggestions need your confirmation."
                if summary.unassigned_activity_rows or summary.unassigned_source_accounts
                else "Review supported activity or check repeated evidence. Unallocated counts can include supporting copies; "
                "do not post them twice. Transfers, repayments and loan splits have separate review."
                if summary.pending_activity_rows
                else "Activity has full allocation. Statement checks, source completeness and corrections remain separate tasks."
            )
        else:
            self.selected_details.setText("Select a document to see its account, dates and next action.")
            self.document_technical_details.clear()
            self.review_context.setText("Choose a document in Documents to start or resume its review.")
            self.account_assignment_status.setText("Account status will appear when a document is selected.")
            self.review_guidance.setText(
                "Document details are loading." if self.inventory_pending else "Choose a document first."
            )

    def _review_document(self, *_args) -> None:
        summary = self._document_summaries.get(self._selected_source())
        if summary is None or self.import_worker is not None:
            return
        self.navigation.setCurrentRow(1)
        if summary.unassigned_source_accounts:
            self._review_source_account()
        elif summary.unassigned_activity_rows:
            self._review_account()
        elif summary.pending_activity_rows:
            if summary.parser_id == REGISTER_PARSER:
                self._review_register_activity()
            elif summary.parser_id in CARD_STATEMENT_PARSERS:
                self._review_card_purchases()
            else:
                self._review_cash_activity()
        else:
            if summary.parser_id == REGISTER_PARSER:
                self.register_button.setFocus()
            elif summary.parser_id in CARD_STATEMENT_PARSERS:
                self.card_review_button.setFocus()
            else:
                self.cash_review_button.setFocus()

    def _open_account_positions(self) -> None:
        dialog = V2ReviewedReportsDialog(self.workspace.profile_path, self)
        dialog.tabs.setCurrentIndex(4)
        dialog.exec()

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
        self._update_controls()
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
        self._update_controls()
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

    def _review_loan_payments(self) -> None:
        if self.import_worker is not None:
            return
        from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview

        V2LoanPaymentReview(self.workspace, parent=self).exec()
        self.assumed_posting_action.blockSignals(True)
        self.assumed_posting_action.setChecked(self.workspace.preferences().allow_assumed_posting_dates)
        self.assumed_posting_action.blockSignals(False)
        self.refresh()

    def _review_register_activity(self) -> None:
        if self.import_worker is not None:
            return
        source_id = self._selected_source()
        if source_id is None or self.workspace.saved_import(source_id).evidence.parser_id != REGISTER_PARSER:
            return
        from parsetrail.gui.v2_liability_register_review import V2LiabilityRegisterReview

        V2LiabilityRegisterReview(self.workspace, source_id, self).exec()
        self.refresh(select_source=source_id)

    def _open_reviewed_reports(self) -> None:
        V2ReviewedReportsDialog(self.workspace.profile_path, self).exec()

    def _open_statement_coverage(self) -> None:
        V2StatementCoverageDialog(self.workspace.profile_path, self).exec()

    def _review_account(self) -> None:
        source_id = self._selected_source()
        if source_id is not None:
            V2AccountBindingReview(self.workspace.profile_path, source_id, self, workspace=self.workspace).exec()
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

    def _edit_account(self, *_args) -> None:
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
        current = self.accounts_list.currentItem()
        selected_id = current.data(Qt.UserRole) if current else None
        account = next((account for account in accounts if account.id == selected_id), None)
        if account is None:
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
            self.refresh()
            self.status.setText("Financial account details saved. Existing source bindings and postings keep this ID.")
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

    def _review_source_values(self) -> None:
        if self.import_worker is not None:
            return
        from parsetrail.gui.v2_account_anchors import V2AccountAnchors

        V2AccountAnchors(self.workspace.profile_path, parent=self, initial_tab="source_values").exec()
        self.refresh()

    def close(self) -> bool:
        if not self.isVisible() and self.import_worker is None:
            # Qt may skip closeEvent for an unseen window. Do not let its
            # queued initial read start after this explicit close request.
            self._closing = True
            self._inventory_requested = False
            if self._inventory_worker is not None:
                self._inventory_worker.requestInterruption()
        return super().close()

    def closeEvent(self, event) -> None:
        if self.import_worker is not None:
            self._close_after_import = True
            self.import_worker.cancel()
            self.status.setText("Cancelling import before closing…")
            event.ignore()
            return
        self._closing = True
        self._inventory_requested = False
        if self._inventory_worker is not None:
            self._inventory_worker.requestInterruption()
            event.ignore()
            return
        super().closeEvent(event)

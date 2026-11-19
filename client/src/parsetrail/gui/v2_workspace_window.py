"""Separate 2.0 desktop shell for verified, unposted source imports."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from threading import Event

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QComboBox,
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
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_cash_movement import cash_account_labels
from parsetrail.core.v2_liability_register import REGISTER_PARSER
from parsetrail.core.v2_loan_payments import LOAN_PARSERS
from parsetrail.core.v2_profile_store import (
    CARD_STATEMENT_PARSERS,
    ProfileFormatError,
    V2ProfileStore,
)
from parsetrail.core.v2_source_import import ImportCancelled, SourceImportResult
from parsetrail.core.v2_statement_summary_review import SUMMARY_VALUE_PARSERS
from parsetrail.core.v2_workspace import ImportSkipped, V2Workspace, folder_source_files
from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview
from parsetrail.gui.v2_account_consolidation import V2AccountConsolidation
from parsetrail.gui.v2_batch_account_assignment import V2BatchAccountAssignment
from parsetrail.gui.v2_batch_import import (
    V2BatchImportReport,
    V2BatchImportWorker,
    V2ImportProgress,
    import_automation_summary,
    import_failure_guidance,
    review_import_accounts,
)
from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
from parsetrail.gui.v2_cash_movement import V2CashMovementDialog
from parsetrail.gui.v2_categories import V2CategoryDialog
from parsetrail.gui.v2_document_browser import (
    DocumentInventoryWorker,
    document_account_association,
    document_period,
    document_title,
    profile_revision,
)
from parsetrail.gui.v2_documents_table import DocumentFilters, DocumentsFilterBar, DocumentsTable
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
from parsetrail.gui.v2_form_state import install_form_styles, install_initial_focus, set_field_state
from parsetrail.gui.v2_gui_lifetime import clear_exception_tracebacks, exec_disposable
from parsetrail.gui.v2_import_account_review import V2ImportAccountReview
from parsetrail.gui.v2_opening_review import V2OpeningReview
from parsetrail.gui.v2_original_document import open_original_document
from parsetrail.gui.v2_path_notice import show_data_locations, show_path_notice
from parsetrail.gui.v2_profile_jobs import ProfileJobs
from parsetrail.gui.v2_profile_startup import choose_new_workspace
from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
from parsetrail.gui.v2_source_account_review import V2SourceAccountReview
from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog
from parsetrail.gui.v2_transfer_review import V2TransferReview
from parsetrail.gui.v2_workspace_help import show_workspace_about, show_workspace_help


class V2ImportWorker(QThread):
    """Keep bounded parsing off the GUI thread and expose a cancellation flag."""

    import_review_requested = Signal(object)

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
            self.result = self.workspace.import_file(
                self.source_path,
                cancelled=self.cancel_event.is_set,
                review_import=lambda path, review: review_import_accounts(self, path, review),
            )
        except Exception as exc:
            self.error = exc


class V2WorkspaceWindow(QMainWindow):
    """Open only an explicitly selected fresh profile and verified catalog cache."""

    DOCUMENTS, ACCOUNTS, REVIEW, TRANSFERS, BUDGET, REPORTS = range(6)

    def __init__(self, workspace: V2Workspace, parent=None):
        super().__init__(parent)
        install_initial_focus(self)
        self.workspace = workspace
        self.import_worker: V2ImportWorker | V2BatchImportWorker | None = None
        self.progress: V2ImportProgress | None = None
        self.import_preview = None
        self._import_generation = 0
        self._import_review_request = None
        self._import_presentation = None
        self._import_avoid = ()
        self._import_presentation_timer = QTimer(self)
        self._import_presentation_timer.setSingleShot(True)
        self._import_presentation_timer.timeout.connect(self._show_import_surface)
        self._close_after_import = False
        self._consolidation_dialog = None
        self._inventory_worker = None
        self._inventory_generation = 0
        self._inventory_requested = False
        self._inventory_selection = None
        self._inventory_account_selection = None
        self._inventory_profile = None
        self._inventory_revision = profile_revision(workspace.profile_path)
        self._document_summaries = {}
        self._closing = False
        self._search_prior_source = None
        self._review_widget = None
        self._review_source_id = None
        self._initial_post_pending = None
        self._previous_completed_source = None
        self._positions_view = None
        self._reports_view = None
        self._transfers_view = None
        self._transfer_return_row = None
        self._report_review_target = None
        self._report_return_destination = self.REPORTS
        self._last_report_tab = 0
        self._document_report_context = None
        self._budget_document_seed = None
        self._budget_context_notice = ""
        self._returning_to_report = False
        self._close_after_job = False
        self._profile_job_handlers = {}
        self.profile_jobs = ProfileJobs(self, workspace.profile_path)
        self.profile_jobs.completed.connect(self._profile_job_finished)
        self.profile_jobs.failed.connect(self._profile_job_failed)
        self.profile_jobs.busy_changed.connect(self._profile_job_busy)
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
        self.formats_action = settings_menu.addAction("Manage statement formats…", self._choose_catalog_release)
        preview_menu = settings_menu.addMenu("Import previews")
        self.preview_mode_group = QActionGroup(self)
        self.preview_mode_actions = {}
        for mode, label in (("always", "Always"), ("when_needed", "Only when attention is needed")):
            action = preview_menu.addAction(label)
            action.setCheckable(True)
            action.setData(mode)
            action.setChecked(workspace.preferences().import_preview_mode == mode)
            self.preview_mode_group.addAction(action)
            self.preview_mode_actions[mode] = action
        self.preview_mode_group.triggered.connect(self._preview_mode_selected)
        self.abbreviated_matching_action = QAction("Suggest accounts using abbreviated account numbers", self)
        self.abbreviated_matching_action.setCheckable(True)
        self.abbreviated_matching_action.setChecked(workspace.preferences().allow_abbreviated_account_matching)
        self.abbreviated_matching_action.toggled.connect(self._set_abbreviated_matching)
        settings_menu.addAction(self.abbreviated_matching_action)
        self.auto_post_loan_action = QAction("Automatically post supported loan payments", self)
        self.auto_post_loan_action.setCheckable(True)
        self.auto_post_loan_action.setChecked(workspace.preferences().auto_post_loan_payments)
        self.auto_post_loan_action.setToolTip(
            "Future imports only: complete supported payments reduce principal and record interest. "
            "The paying account stays unresolved in Transfers; other payments need review. "
            "Currently supports single Capital One Auto payments."
        )
        self.auto_post_loan_action.setStatusTip(self.auto_post_loan_action.toolTip())
        self.auto_post_loan_action.toggled.connect(self._set_auto_post_loan_payments)
        settings_menu.addAction(self.auto_post_loan_action)
        self.auto_record_statement_values_action = QAction("Automatically record supported statement values", self)
        self.auto_record_statement_values_action.setCheckable(True)
        self.auto_record_statement_values_action.setChecked(workspace.preferences().auto_record_statement_values)
        self.auto_record_statement_values_action.setToolTip(
            "Future imports only. Records supported retirement and HSA statement closing values at statement end. "
            "Summary totals remain evidence; no transactions or budget changes."
        )
        self.auto_record_statement_values_action.setStatusTip(self.auto_record_statement_values_action.toolTip())
        self.auto_record_statement_values_action.toggled.connect(self._set_auto_record_statement_values)
        settings_menu.addAction(self.auto_record_statement_values_action)
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
        self.consolidate_accounts_action = accounts_menu.addAction("Consolidate accounts…")
        self.consolidate_accounts_action.triggered.connect(self._consolidate_accounts)
        self.account_anchors_action = accounts_menu.addAction("Reviewed openings, dated values and closure…")
        self.account_anchors_action.triggered.connect(self._review_account_anchors)
        self.source_values_action = accounts_menu.addAction("Review statement closing values…")
        self.source_values_action.triggered.connect(self._review_source_values)
        self.source_opening_action = accounts_menu.addAction("Review source-backed opening…")
        self.source_opening_action.triggered.connect(self._review_openings)
        review_menu = self.menuBar().addMenu("Review")
        self.batch_accounts_action = review_menu.addAction("Assign document accounts…")
        self.batch_accounts_action.triggered.connect(self._assign_document_accounts)
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
        self.profile_name = QLabel(workspace.profile_path.stem)
        self.profile_name.setTextFormat(Qt.PlainText)
        self.profile_name.setToolTip(str(workspace.profile_path))
        profile_row.addWidget(self.profile_name)
        self.profile_label = QLineEdit(str(workspace.profile_path))
        self.profile_label.setReadOnly(True)
        self.profile_label.setCursorPosition(0)
        profile_row.addWidget(self.profile_label)
        self.profile_label.hide()
        profile_details = QPushButton("Show profile path")
        profile_details.setCheckable(True)
        profile_details.toggled.connect(self.profile_label.setVisible)
        profile_row.addWidget(profile_details)
        profile_details.hide()
        path_action = profile_menu.addAction("Show profile path")
        path_action.setCheckable(True)
        path_action.toggled.connect(self.profile_label.setVisible)
        profile_row.addStretch()
        layout.addLayout(profile_row)
        catalog_controls = QHBoxLayout()
        self.catalog_label = QLabel()
        catalog_controls.addWidget(self.catalog_label)
        self.install_catalog_button = QPushButton("Install statement formats…")
        self.install_catalog_button.setObjectName("installFormats")
        self.install_catalog_button.setToolTip(
            "Choose the local signed statement-format package folder containing catalog.json and catalog.sig. "
            "ParseTrail verifies its signature before enabling import."
        )
        self.install_catalog_button.clicked.connect(self._choose_catalog_release)
        catalog_controls.addWidget(self.install_catalog_button)
        catalog_controls.addStretch()
        layout.addLayout(catalog_controls)
        body = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setAccessibleName("Workspace navigation")
        self.navigation.addItems(("Documents", "Accounts", "Review", "Transfers", "Budget", "Reports"))
        self.navigation.setFixedWidth(142)
        body.addWidget(self.navigation)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        documents = QWidget()
        document_layout = QVBoxLayout(documents)
        document_heading = QLabel("Statements")
        document_heading.setStyleSheet("font-size: 16px; font-weight: 600")
        document_layout.addWidget(document_heading)
        self.pages.addWidget(documents)
        imports = QHBoxLayout()
        self.import_button = QPushButton("Import statement…")
        self.import_button.setObjectName("firstImport")
        self.import_button.clicked.connect(self._choose_import)
        imports.addWidget(self.import_button)
        self.import_folder_button = QPushButton("Import folder…")
        self.import_folder_button.clicked.connect(self._choose_import_folder)
        imports.addWidget(self.import_folder_button)
        imports.addStretch()
        self.batch_accounts_button = QPushButton("Assign document accounts…")
        self.batch_accounts_button.clicked.connect(self._assign_document_accounts)
        imports.addWidget(self.batch_accounts_button)
        self.document_more_button = QPushButton("More…")
        document_menu = QMenu(self.document_more_button)
        self.document_more_button.setMenu(document_menu)
        imports.addWidget(self.document_more_button)
        self.import_folder_button.hide()
        self.batch_accounts_button.hide()
        self.folder_action = document_menu.addAction("Import folder…", self.import_folder_button.click)
        self.document_assign_action = document_menu.addAction(
            "Assign document accounts…", self.batch_accounts_button.click
        )
        document_layout.addLayout(imports)
        self.document_filters = DocumentsFilterBar(self)
        self.document_search = self.document_filters.search
        self._document_filter_state = DocumentFilters()
        self.document_filters.changed.connect(self._filter_documents)
        document_layout.addWidget(self.document_filters)
        inventory_row = QHBoxLayout()
        self.inventory_status = QLabel("Loading saved documents…")
        self.inventory_status.setWordWrap(True)
        inventory_row.addWidget(self.inventory_status, 1)
        self.retry_inventory = QPushButton("Reload documents")
        self.retry_inventory.clicked.connect(lambda: self.refresh())
        inventory_row.addWidget(self.retry_inventory)
        self.retry_inventory.hide()
        document_menu.addAction("Reload statements", self.retry_inventory.click)
        document_layout.addLayout(inventory_row)
        self.sources = DocumentsTable(self)
        self.sources.source_changed.connect(self._update_controls)
        self.sources.review_requested.connect(self._review_document)
        document_layout.addWidget(self.sources, 1)
        self.selected_details = QLabel()
        self.selected_details.setWordWrap(True)
        self.selected_details.setTextFormat(Qt.PlainText)
        self.selected_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        document_layout.addWidget(self.selected_details)
        document_actions = QHBoxLayout()
        self.review_document_button = QPushButton("Review document")
        install_form_styles(self.review_document_button)
        self.review_document_button.clicked.connect(self._review_document)
        document_actions.addWidget(self.review_document_button)
        self.preview_button = QPushButton("Preview evidence")
        self.preview_button.clicked.connect(self._preview)
        document_actions.addWidget(self.preview_button)
        self.open_original_button = QPushButton("Open original…")
        self.open_original_button.clicked.connect(self._open_original)
        document_actions.addWidget(self.open_original_button)
        self.document_details_button = QPushButton("Show details")
        self.document_details_button.setCheckable(True)
        document_actions.addWidget(self.document_details_button)
        self.document_details_button.hide()
        self.document_details_action = document_menu.addAction("Show statement details")
        self.document_details_action.setCheckable(True)
        self.document_details_action.toggled.connect(self.document_details_button.setChecked)
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
        document_switch = QHBoxLayout()
        document_switch.addWidget(QLabel("Document:"))
        self.review_document_selector = QComboBox()
        self.review_document_selector.setAccessibleName("Document to review")
        self.review_document_selector.setMinimumContentsLength(15)
        self.review_document_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.review_document_selector.currentIndexChanged.connect(self._switch_review_document)
        document_switch.addWidget(self.review_document_selector, 1)
        self.next_document_button = QPushButton("Next needs attention")
        self.next_document_button.clicked.connect(self._next_document)
        document_switch.addWidget(self.next_document_button)
        review_layout.addLayout(document_switch)
        self.review_period = QLabel()
        self.review_period.setWordWrap(True)
        self.review_period.setTextFormat(Qt.PlainText)
        self.review_period.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.review_period.setAccessibleName("Selected document period")
        self.review_period.hide()
        review_layout.addWidget(self.review_period)
        self.review_context = QLabel("Choose a document to review.")
        self.review_context.setWordWrap(True)
        self.review_context.setTextFormat(Qt.PlainText)
        review_heading = QHBoxLayout()
        review_heading.addWidget(self.review_context, 1)
        choose_document = QPushButton("Choose a document")
        choose_document.clicked.connect(lambda: self.navigation.setCurrentRow(self.DOCUMENTS))
        review_heading.addWidget(choose_document)
        choose_document.hide()
        related = QPushButton("Related actions…")
        self.related_menu = QMenu(related)
        self.related_menu.addAction("Choose another statement", lambda: self.navigation.setCurrentRow(self.DOCUMENTS))
        self.related_menu.addAction(self.transfer_review_action)
        self.related_menu.addAction(self.settlement_review_action)
        self.related_menu.addAction(self.loan_payment_action)
        self.related_menu.addSeparator()
        self.change_document_account_action = self.related_menu.addAction("Change document accounts…")
        self.change_document_account_action.triggered.connect(self._review_source_account)
        self.change_row_accounts_action = self.related_menu.addAction("Review row account assignments…")
        self.change_row_accounts_action.triggered.connect(self._review_account)
        original_action = self.related_menu.addAction("Open original document…")
        original_action.triggered.connect(self._open_original)
        self.related_menu.addSeparator()
        self.related_menu.addAction("Check possible repeated rows…", self._review_source_overlap)
        self.related_menu.addAction("Statement coverage and checks…", self._open_statement_coverage)
        related.setMenu(self.related_menu)
        review_heading.addWidget(related)
        review_layout.addLayout(review_heading)
        journey_actions = QHBoxLayout()
        self.review_progress = QLabel()
        self.review_progress.setWordWrap(True)
        self.review_progress.setTextFormat(Qt.PlainText)
        journey_actions.addWidget(self.review_progress, 1)
        self.review_progress.hide()
        self.document_spending_button = QPushButton("View spending")
        self.document_spending_button.setToolTip(
            "Show reviewed spending across all profile accounts for this document's dates. "
            "This does not filter spending to this document or its accounts."
        )
        self.document_spending_button.clicked.connect(self._show_document_spending)
        review_heading.addWidget(self.document_spending_button)
        self.back_to_report_button = QPushButton("Back to report")
        self.back_to_report_button.clicked.connect(self._back_to_report)
        self.back_to_report_button.hide()
        review_heading.addWidget(self.back_to_report_button)
        review_layout.addLayout(journey_actions)
        completion_row = QHBoxLayout()
        self.review_completion = QLabel()
        self.review_completion.setWordWrap(True)
        self.review_completion.setTextFormat(Qt.PlainText)
        self.review_completion.hide()
        completion_row.addWidget(self.review_completion, 1)
        self.previous_document_button = QPushButton("Back to completed statement")
        self.previous_document_button.clicked.connect(self._back_to_completed_statement)
        self.previous_document_button.hide()
        completion_row.addWidget(self.previous_document_button)
        review_layout.addLayout(completion_row)
        account_group = QGroupBox("Account association")
        self.account_group = account_group
        account_controls = QHBoxLayout(account_group)
        self._account_group_margins = account_controls.contentsMargins()
        self.source_review_button = QPushButton("Confirm document accounts")
        self.source_review_button.clicked.connect(self._review_source_account)
        account_controls.addWidget(self.source_review_button)
        self.review_button = QPushButton("Assign rows without an account")
        self.review_button.clicked.connect(self._review_account)
        account_controls.addWidget(self.review_button)
        review_layout.addWidget(account_group)
        self.account_assignment_status = QLabel()
        self.account_assignment_status.setWordWrap(True)
        account_controls.insertWidget(0, self.account_assignment_status, 1)
        activity_group = QGroupBox("Activity and related workflows")
        self.activity_group = activity_group
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
        self.more_review_button = QPushButton("More actions")
        self.more_review_button.setCheckable(True)
        controls.addWidget(self.more_review_button)
        activity_layout.addLayout(controls)
        specialized_widget = QWidget()
        specialized = QHBoxLayout(specialized_widget)
        self.register_button = QPushButton("Review loan register")
        self.register_button.clicked.connect(self._review_register_activity)
        specialized.addWidget(self.register_button)
        settlement_button = QPushButton("Fees and partial transfers…")
        settlement_button.clicked.connect(self._review_settlements)
        specialized.addWidget(settlement_button)
        loan_button = QPushButton("Loan principal and interest…")
        loan_button.clicked.connect(self._review_loan_payments)
        specialized.addWidget(loan_button)
        activity_layout.addWidget(specialized_widget)
        specialized_widget.hide()
        self.more_review_button.toggled.connect(specialized_widget.setVisible)
        specialized.setContentsMargins(12, 0, 12, 0)
        self.review_guidance = QLabel()
        self.review_guidance.setWordWrap(True)
        activity_layout.addWidget(self.review_guidance)
        review_layout.addWidget(activity_group)
        activity_group.hide()
        self.review_host = QVBoxLayout()
        review_layout.addLayout(self.review_host, 1)
        self.review_empty = QLabel("Select a document to see its supported activity and remaining decisions.")
        self.review_empty.setWordWrap(True)
        self.review_host.addWidget(self.review_empty)
        checks = QGroupBox("Supporting evidence and checks")
        checks_layout = QHBoxLayout(checks)
        self.overlap_review_button = QPushButton("Check possible repeated rows")
        self.overlap_review_button.clicked.connect(self._review_source_overlap)
        checks_layout.addWidget(self.overlap_review_button)
        check_statement = QPushButton("Statement checks…")
        check_statement.clicked.connect(self._open_statement_coverage)
        checks_layout.addWidget(check_statement)
        review_layout.addWidget(checks)
        checks.hide()

        accounts = QWidget()
        accounts_layout = QVBoxLayout(accounts)
        self.pages.addWidget(accounts)
        accounts_note = QLabel("Your accounts")
        accounts_note.setStyleSheet("font-size: 16px; font-weight: 600")
        accounts_note.setWordWrap(True)
        accounts_layout.addWidget(accounts_note)
        self.accounts_list = QListWidget()
        self.accounts_list.setAccessibleName("Your financial accounts")
        self.accounts_list.setWordWrap(True)
        accounts_layout.addWidget(self.accounts_list)
        self.accounts_list.itemDoubleClicked.connect(self._edit_account)
        self.accounts_status = QLabel("Loading accounts…")
        self.accounts_status.setWordWrap(True)
        accounts_layout.addWidget(self.accounts_status)
        account_actions = QHBoxLayout()
        self.account_button = QPushButton("Add account…")
        self.account_button.clicked.connect(self._add_account)
        account_actions.addWidget(self.account_button)
        self.tangible_button = QPushButton("Tangible assets…")
        self.tangible_button.clicked.connect(self._review_tangible_assets)
        account_actions.addWidget(self.tangible_button)
        self.edit_account_button = QPushButton("Edit account…")
        self.edit_account_button.clicked.connect(self._edit_account)
        account_actions.addWidget(self.edit_account_button)
        self.consolidate_accounts_button = QPushButton("Consolidate accounts…")
        self.consolidate_accounts_button.setObjectName("consolidateAccounts")
        self.consolidate_accounts_button.clicked.connect(self._consolidate_accounts)
        account_actions.addWidget(self.consolidate_accounts_button)
        self.openings_button = QPushButton("Review source-backed openings…")
        self.openings_button.clicked.connect(self._review_openings)
        account_actions.addWidget(self.openings_button)
        self.openings_button.hide()
        self.categories_button = QPushButton("Manage categories…")
        self.categories_button.clicked.connect(self._edit_categories)
        account_actions.addWidget(self.categories_button)
        account_actions.addStretch()
        accounts_layout.addLayout(account_actions)
        self.account_details_toggle = QPushButton("Balances and history (optional)")
        self.account_details_toggle.setCheckable(True)
        accounts_layout.addWidget(self.account_details_toggle)
        self.positions_container = QWidget()
        self.positions_host = QVBoxLayout(self.positions_container)
        self.positions_host.setContentsMargins(0, 0, 0, 0)
        self.positions_container.hide()
        accounts_layout.addWidget(self.positions_container, 2)
        self.account_details_toggle.toggled.connect(self._toggle_account_details)

        reports = QWidget()
        report_layout = QVBoxLayout(reports)
        self.pages.addWidget(reports)
        self.reports_heading = QLabel("Reports")
        self.reports_heading.setStyleSheet("font-size: 16px; font-weight: 600")
        reports_note = self.reports_heading
        reports_note.setWordWrap(True)
        report_layout.addWidget(reports_note)
        self.report_context = QLabel("All profile accounts · Reviewed entries only")
        self.report_context.setWordWrap(True)
        self.report_context.setTextFormat(Qt.PlainText)
        report_layout.addWidget(self.report_context)
        report_actions = QHBoxLayout()
        self.reports_button = QPushButton("Review pending activity")
        self.reports_button.clicked.connect(lambda: self._open_pending_review(self.REPORTS))
        report_actions.addWidget(self.reports_button)
        movement_button = QPushButton("Cash movement…")
        movement_button.clicked.connect(lambda: V2CashMovementDialog(self.workspace.profile_path, self).exec())
        report_actions.addWidget(movement_button)
        movement_button.hide()
        self.coverage_button = QPushButton("Statement coverage and checks…")
        self.coverage_button.clicked.connect(self._open_statement_coverage)
        report_actions.addWidget(self.coverage_button)
        self.coverage_button.hide()
        report_more = QPushButton("Other reports…")
        report_menu = QMenu(report_more)
        report_more.setMenu(report_menu)
        report_menu.addAction("Cash movement…", movement_button.click)
        report_menu.addAction("Statement coverage and checks…", self.coverage_button.click)
        report_actions.addWidget(report_more)
        report_actions.addStretch()
        report_layout.addLayout(report_actions)
        self.reports_host = QVBoxLayout()
        report_layout.addLayout(self.reports_host, 1)
        transfers = QWidget()
        self.transfers_host = QVBoxLayout(transfers)
        self.pages.addWidget(transfers)
        self._page_widgets = {
            self.DOCUMENTS: documents,
            self.ACCOUNTS: accounts,
            self.REVIEW: review,
            self.TRANSFERS: transfers,
            self.BUDGET: reports,
            self.REPORTS: reports,
        }
        self.navigation.currentRowChanged.connect(self._navigation_changed)
        self.navigation.setCurrentRow(self.DOCUMENTS)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def _navigation_changed(self, page):
        from_document = self.pages.currentWidget() in (
            self._page_widgets[self.DOCUMENTS],
            self._page_widgets[self.REVIEW],
        )
        if page not in self._page_widgets:
            return
        self.pages.setCurrentWidget(self._page_widgets[page])
        if page == self.REVIEW:
            self._ensure_review_view()
        elif page in (self.BUDGET, self.REPORTS):
            view = self._ensure_report_view(self.REPORTS)
            if (
                page == self.BUDGET
                and from_document
                and not self._returning_to_report
                and self._budget_document_seed != self._selected_source()
            ):
                if not self._seed_document_results(view):
                    self._document_report_context = None
                    self._budget_context_notice = "Document dates unknown · Choose a budget month"
            view.tabs.setCurrentIndex(2 if page == self.BUDGET else self._last_report_tab)
            self._update_report_context()
        elif page == self.ACCOUNTS and self.account_details_toggle.isChecked():
            self._ensure_report_view(self.ACCOUNTS)
        elif page == self.TRANSFERS:
            self._ensure_transfers_view().refresh()
        if hasattr(self, "status"):
            self._refresh_changed_profile()

    def _ensure_report_view(self, page):
        attribute = "_positions_view" if page == self.ACCOUNTS else "_reports_view"
        view = getattr(self, attribute)
        if view is None:
            view = V2ReviewedReportsDialog(
                self.workspace.profile_path,
                self,
                embedded=True,
                initial_tab=4 if page == self.ACCOUNTS else 0,
                positions_only=page == self.ACCOUNTS,
            )
            setattr(self, attribute, view)
            view.review_requested.connect(lambda: self._open_pending_review(page))
            view.source_review_requested.connect(self._review_report_source)
            if page != self.ACCOUNTS:
                view.review_pending_button.hide()
                view.tabs.currentChanged.connect(self._report_tab_changed)
                view.budget_month.dateChanged.connect(self._update_report_context)
                view.categories_changed.connect(self._categories_changed)
            (self.positions_host if page == self.ACCOUNTS else self.reports_host).addWidget(view)
            if page == self.ACCOUNTS:
                view.positions_table.selectionModel().currentRowChanged.connect(self._position_selected)
            view.export_jobs.busy_changed.connect(self._embedded_busy)
        elif view._loaded.get(view.tabs.currentIndex()) != view._key(view.tabs.currentIndex()):
            view._queue_selected_read(0)
        return view

    def _ensure_transfers_view(self):
        if self._transfers_view is None:
            from parsetrail.gui.v2_transfer_workspace import V2TransferWorkspace

            view = self._transfers_view = V2TransferWorkspace(self.workspace, self)
            self.transfers_host.addWidget(view)
            view.changed.connect(lambda: self.refresh(select_source=self._selected_source()))
            view.source_requested.connect(self._review_report_source)
            view.manual_requested.connect(self._review_manual_transfers)
            view.jobs.busy_changed.connect(self._embedded_busy)
        return self._transfers_view

    def _open_transfers(self, row_id=""):
        self.navigation.setCurrentRow(self.TRANSFERS)
        view = self._ensure_transfers_view()
        if row_id:
            view.focus_row(row_id)

    def _review_tangible_assets(self):
        if self._write_in_progress():
            return
        from parsetrail.gui.v2_tangible_assets import V2TangibleAssets

        exec_disposable(V2TangibleAssets(self.workspace, self))
        self.refresh()

    def _toggle_account_details(self, checked):
        self.positions_container.setVisible(checked)
        if checked:
            self._ensure_report_view(self.ACCOUNTS)

    def _report_tab_changed(self, tab):
        if tab != 2:
            self._last_report_tab = tab
        if self.navigation.currentRow() in (self.BUDGET, self.REPORTS):
            self.navigation.blockSignals(True)
            self.navigation.setCurrentRow(self.BUDGET if tab == 2 else self.REPORTS)
            self.navigation.blockSignals(False)
        self._update_report_context()

    def _update_report_context(self, *_args):
        budget = self._reports_view is not None and self._reports_view.tabs.currentIndex() == 2
        self.reports_heading.setText("Monthly budget" if budget else "Reports")
        if self._reports_view is not None and self._reports_view.tabs.currentIndex() == 4:
            self.report_context.setText(
                "Account values and journal positions · through "
                + self._reports_view.as_of.date().toString("yyyy-MM-dd")
            )
            return
        context = "All profile accounts · Reviewed entries only"
        if self._document_report_context is not None:
            title, start, end = self._document_report_context
            if budget:
                month = self._reports_view.budget_month.date().toString("MMM yyyy")
                context += f" · Showing {month}"
                if (start.year, start.month) != (end.year, end.month):
                    context += f" · Document spans {start:%b %Y}–{end:%b %Y}"
            else:
                context += f" · Dates from {title}"
        if budget and self._budget_context_notice:
            context += f" · {self._budget_context_notice}"
        self.report_context.setText(context)

    def _categories_changed(self):
        self._refresh_changed_profile()
        if self._review_widget is not None:
            self._review_widget.refresh_preserving_draft()

    @staticmethod
    def _needs_attention(summary):
        return bool(
            summary.unassigned_source_accounts
            or summary.unassigned_activity_rows
            or summary.pending_activity_rows
            or summary.pending_summary_values
        )

    def _sync_review_selector(self):
        selected = self._selected_source()
        self.review_document_selector.blockSignals(True)
        self.review_document_selector.clear()
        for summary in self._document_summaries.values():
            self.review_document_selector.addItem(
                f"{document_title(summary)} · {document_period(summary)}", summary.source_sha256
            )
            index = self.review_document_selector.count() - 1
            self.review_document_selector.setItemData(
                index, f"{document_title(summary)}\n{document_period(summary)}", Qt.ToolTipRole
            )
        self.review_document_selector.setCurrentIndex(self.review_document_selector.findData(selected))
        self.review_document_selector.blockSignals(False)

    def _select_review_source(self, source_id):
        if source_id not in self._document_summaries or self._write_in_progress():
            return False
        current = self._selected_source()
        if current != source_id and not self._discard_review():
            self._sync_review_selector()
            return False
        if current != source_id:
            self._previous_completed_source = None
            self.previous_document_button.hide()
            self.review_completion.hide()
        # An explicit handoff reveals its source without keeping it hidden by filters.
        revealed = source_id not in self.sources.visible_sources()
        self._search_prior_source = None
        if revealed:
            self._document_filter_state = DocumentFilters()
            self.document_filters.set_state(self._document_filter_state)
            self.sources.documents_proxy.set_filters(self._document_filter_state)
        self.sources.select_source(source_id)
        self._sync_review_selector()
        self._update_document_count()
        self._update_controls()
        if revealed:
            self._pending_filter_reveal_source = source_id
            QTimer.singleShot(0, self, self._announce_filter_reveal)
        return self._selected_source() == source_id

    def _announce_filter_reveal(self):
        source = getattr(self, "_pending_filter_reveal_source", None)
        self._pending_filter_reveal_source = None
        if source is not None and self._selected_source() == source:
            self.status.setText("Filters cleared to show the selected statement. " + self.status.text())

    def _switch_review_document(self, *_args):
        source_id = self.review_document_selector.currentData()
        if source_id is not None:
            self._select_review_source(source_id)

    def _next_document(self):
        summaries = list(self._document_summaries.values())
        if not summaries:
            self.navigation.setCurrentRow(self.DOCUMENTS)
            return
        selected = self._selected_source()
        current = next((i for i, summary in enumerate(summaries) if summary.source_sha256 == selected), -1)
        for offset in range(1, len(summaries) + 1):
            summary = summaries[(current + offset) % len(summaries)]
            if self._needs_attention(summary):
                if summary.source_sha256 == selected:
                    self.status.setText(
                        "This is the only document needing attention. Pending rows may include repeats or unsupported activity."
                    )
                    return
                if self._select_review_source(summary.source_sha256):
                    self.navigation.setCurrentRow(self.REVIEW)
                    self.review_document_selector.setFocus()
                return

    def _initial_review_posted(self, source_id):
        self._initial_review_completed(source_id)

    def _initial_review_completed(self, source_id):
        # This signal is delivered after a successful initial write, separately
        # from ordinary refresh/correction notifications and disposable modals.
        if (
            self._closing
            or self.navigation.currentRow() != self.REVIEW
            or self._selected_source() != source_id
            or self._review_source_id != source_id
            or self._report_review_target is not None
            or self._transfer_return_row is not None
        ):
            return
        self._initial_post_pending = (self.workspace.profile_path, source_id)
        self.refresh(select_source=source_id)

    def _advance_after_initial_post(self):
        pending = self._initial_post_pending
        if pending is None or self._closing:
            return
        profile, source_id = pending
        if (
            profile != self.workspace.profile_path
            or self.navigation.currentRow() != self.REVIEW
            or self._selected_source() != source_id
            or self._review_source_id != source_id
            or self._report_review_target is not None
            or self._transfer_return_row is not None
        ):
            self._initial_post_pending = None
            return
        if self.inventory_pending or self._write_in_progress() or self._review_widget.jobs.pending:
            return
        self._initial_post_pending = None
        summary = self._document_summaries.get(source_id)
        if summary is None or self._needs_attention(summary) or self._review_has_draft():
            return
        self._previous_completed_source = None
        self.previous_document_button.hide()
        self.review_completion.setText(
            f"Initial review complete: {document_title(summary)} · {document_period(summary)}. "
            + (
                "Statement value recorded for Accounts and Reports."
                if summary.parser_id in SUMMARY_VALUE_PARSERS
                else "Resolve any unmatched counterparts in Transfers."
            )
        )
        summaries = list(self._document_summaries.values())
        current = next(i for i, item in enumerate(summaries) if item.source_sha256 == source_id)
        for offset in range(1, len(summaries)):
            other = summaries[(current + offset) % len(summaries)]
            if self._needs_attention(other):
                if self._select_review_source(other.source_sha256):
                    self._previous_completed_source = source_id
                    self.review_completion.setText(
                        f"Initial review complete: {document_title(summary)} · {document_period(summary)}. "
                        f"Now reviewing {document_title(other)} · {document_period(other)}."
                    )
                    self.previous_document_button.show()
                    self.review_document_selector.setFocus()
                break
        self.review_completion.show()

    def _back_to_completed_statement(self):
        source_id = self._previous_completed_source
        if source_id is not None and self._select_review_source(source_id):
            self._previous_completed_source = None
            self.previous_document_button.hide()
            self.review_completion.hide()

    def _show_document_spending(self):
        summary = self._document_summaries.get(self._selected_source())
        if summary is not None and summary.parser_id in SUMMARY_VALUE_PARSERS:
            if summary.end is None or len(summary.associated_account_ids) != 1:
                return
            reports = self._ensure_report_view(self.REPORTS)
            reports.show_account_value(summary.associated_account_ids[0], summary.end)
            self.navigation.setCurrentRow(self.REPORTS)
            self._update_report_context()
            return
        reports = self._ensure_report_view(self.REPORTS)
        if not self._seed_document_results(reports):
            return
        reports.tabs.setCurrentIndex(0)
        self.navigation.setCurrentRow(self.REPORTS)
        self._update_report_context()

    def _seed_document_results(self, reports):
        summary = self._document_summaries.get(self._selected_source())
        if summary is None or summary.start is None or summary.end is None or summary.end == date.max:
            return False
        if summary.start > summary.end:
            return False
        reports.set_period(summary.start, summary.end + timedelta(days=1))
        reports.set_budget_month(summary.start)
        self._document_report_context = (document_title(summary), summary.start, summary.end)
        self._budget_document_seed = self._selected_source()
        self._budget_context_notice = ""
        return True

    def _review_report_source(self, source_id, row_id):
        origin = self.navigation.currentRow()
        if origin == self.TRANSFERS and self._transfers_view is not None:
            current = self._transfers_view._current()
            self._transfer_return_row = current.row_ids[0] if current is not None else row_id
        if not self._select_review_source(source_id):
            self.status.setText(
                "The source review was not opened. Keep your current choices, or reload documents and try again."
            )
            return
        self.navigation.setCurrentRow(self.REVIEW)
        self._ensure_review_view()
        view = self._review_widget
        if view is None:
            return
        view.navigation.reveal_row(row_id)
        if view.review_pending:
            view._selected_after_read = row_id
        self._report_review_target = (source_id, row_id)
        self._report_return_destination = (
            origin if origin in (self.BUDGET, self.REPORTS, self.TRANSFERS) else self.REPORTS
        )
        self.back_to_report_button.setText(
            "Back to transfers"
            if origin == self.TRANSFERS
            else "Back to budget"
            if origin == self.BUDGET
            else "Back to report"
        )
        self.back_to_report_button.show()
        self.status.setText(
            "Opened the transfer's source row. Nothing changes until you confirm a review. Back to transfers returns to the selected relationship."
            if origin == self.TRANSFERS
            else "Opened the report's source row. Review its saved interpretation or owning payment/transfer history. "
            "Nothing changes until you confirm. Back to report keeps its dates and tab."
        )
        view.table.setFocus()

    def _back_to_report(self):
        if self._report_return_destination == self.TRANSFERS:
            self._open_transfers(
                self._transfer_return_row or (self._report_review_target[1] if self._report_review_target else "")
            )
            return
        self._returning_to_report = True
        try:
            self.navigation.setCurrentRow(self._report_return_destination)
        finally:
            self._returning_to_report = False
        view = self._reports_view
        if view is not None:
            view.invalidate(read=True)

    def _open_pending_review(self, page):
        account_id = None
        view = self._positions_view if page == self.ACCOUNTS else self._reports_view
        if view is not None and view.tabs.currentIndex() in (1, 4):
            table = view.account_table if view.tabs.currentIndex() == 1 else view.positions_table
            model = view.account_model if view.tabs.currentIndex() == 1 else view.positions_model
            index = table.currentIndex()
            if index.isValid() and index.row() < len(model.rows):
                account_id = model.rows[index.row()].account_id
        if account_id is not None:
            related = [
                summary for summary in self._document_summaries.values() if account_id in summary.associated_account_ids
            ]
            if not related:
                self.status.setText(
                    "No saved document is associated with this account. Import a statement or inspect its history."
                )
                return
            selected = next(
                (
                    summary
                    for summary in related
                    if summary.pending_activity_rows
                    or summary.pending_summary_values
                    or summary.unassigned_activity_rows
                    or summary.unassigned_source_accounts
                ),
                related[0],
            )
            if not self._select_review_source(selected.source_sha256):
                return
        elif self._document_summaries:
            selected = next(
                (summary for summary in self._document_summaries.values() if self._needs_attention(summary)), None
            )
            if selected is None:
                self.status.setText(
                    "No activity, statement values or account assignments remain to review. Source coverage and checks are separate."
                )
                self.navigation.setCurrentRow(self.DOCUMENTS)
                return
            if not self._select_review_source(selected.source_sha256):
                return
        else:
            self.navigation.setCurrentRow(self.DOCUMENTS)
            self.status.setText("Import documents to start reviewing activity.")
            return
        self.navigation.setCurrentRow(self.REVIEW)

    def _position_selected(self, *_args):
        view = self._positions_view
        index = view.positions_table.currentIndex()
        if not index.isValid() or index.row() >= len(view.positions_model.rows):
            return
        account_id = view.positions_model.rows[index.row()].account_id
        for position in range(self.accounts_list.count()):
            item = self.accounts_list.item(position)
            if item.data(Qt.UserRole) == account_id:
                self.accounts_list.setCurrentItem(item)
                break

    def _review_has_draft(self):
        draft = getattr(self._review_widget, "has_unsaved_draft", False)
        return bool(draft() if callable(draft) else draft)

    def _discard_review(self):
        if self._review_widget is None:
            return True
        if getattr(getattr(self._review_widget, "jobs", None), "writing", False):
            self.status.setText("Finishing the confirmed review before changing its document…")
            return False
        if (
            self._review_has_draft()
            and QMessageBox.question(
                self,
                "Leave this review?",
                "Discard the staged or edited review choices? Saved entries and source evidence remain available.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return False
        cancel = getattr(self._review_widget, "request_cancel", None)
        if cancel is not None and cancel() is False:
            return False
        self.review_host.removeWidget(self._review_widget)
        self._review_widget.hide()
        self._review_widget.deleteLater()
        self._review_widget = None
        self._review_source_id = None
        return True

    def _ensure_review_view(self):
        source_id = self._selected_source()
        summary = self._document_summaries.get(source_id)
        if summary is None:
            return
        if self._review_source_id == source_id and self._review_widget is not None:
            return
        if not self._discard_review():
            return
        if summary.parser_id == REGISTER_PARSER:
            from parsetrail.gui.v2_liability_register_review import V2LiabilityRegisterReview

            view = V2LiabilityRegisterReview(self.workspace, source_id, self, embedded=True)
        elif summary.parser_id in LOAN_PARSERS:
            from parsetrail.gui.v2_loan_document_review import V2LoanDocumentReview

            view = V2LoanDocumentReview(self.workspace, source_id, self)
        elif summary.parser_id in SUMMARY_VALUE_PARSERS:
            from parsetrail.gui.v2_statement_summary_review import V2StatementSummaryReview

            view = V2StatementSummaryReview(self.workspace, source_id, self)
            view.account_assignment_requested.connect(self._review_source_account)
            view.preferences_changed.connect(self._sync_preference_controls)
        elif summary.parser_id in CARD_STATEMENT_PARSERS:
            view = V2CardPurchaseReview(self.workspace, source_id, self, embedded=True)
        else:
            view = V2CashActivityReview(
                self.workspace.profile_path,
                source_id,
                self,
                workspace=self.workspace,
                embedded=True,
            )
        self._review_widget, self._review_source_id = view, source_id
        self.review_empty.hide()
        self.review_host.addWidget(view)
        changed = getattr(view, "changed", None)
        if changed is not None:
            changed.connect(lambda: self.refresh(select_source=self._review_source_id))
        initial_posted = getattr(view, "initial_posted", None)
        if initial_posted is not None:
            initial_posted.connect(self._initial_review_posted, Qt.QueuedConnection)
        initial_completed = getattr(view, "initial_review_completed", None)
        if initial_completed is not None:
            initial_completed.connect(self._initial_review_completed, Qt.QueuedConnection)
        transfers_requested = getattr(view, "transfers_requested", None)
        if transfers_requested is not None:
            transfers_requested.connect(self._open_transfers, Qt.QueuedConnection)
        view.jobs.busy_changed.connect(self._embedded_busy)

    def _embedded_busy(self, busy):
        self._update_controls()
        if not busy and self._initial_post_pending is not None:
            QTimer.singleShot(0, self, self._advance_after_initial_post)
        if not busy and self._close_after_job:
            QTimer.singleShot(0, self, self.close)

    def _write_in_progress(self):
        return bool(
            self.import_worker is not None
            or self.profile_jobs.writing
            or self._reports_writing()
            or getattr(getattr(self._review_widget, "jobs", None), "writing", False)
            or getattr(getattr(self._transfers_view, "jobs", None), "writing", False)
            or getattr(getattr(self._consolidation_dialog, "jobs", None), "writing", False)
        )

    def _reports_writing(self):
        return any(view is not None and view.export_jobs.writing for view in (self._positions_view, self._reports_view))

    def _reset_embedded_views(self):
        if self._transfers_view is not None:
            if not self._transfers_view.shutdown():
                return False
            self.transfers_host.removeWidget(self._transfers_view)
            self._transfers_view.hide()
            self._transfers_view.deleteLater()
            self._transfers_view = None
        for attribute, host in (("_positions_view", self.positions_host), ("_reports_view", self.reports_host)):
            view = getattr(self, attribute)
            if view is not None:
                if not view.shutdown():
                    return False
                host.removeWidget(view)
                view.hide()
                view.deleteLater()
                setattr(self, attribute, None)
        self._report_review_target = None
        self._transfer_return_row = None
        self._initial_post_pending = None
        self._previous_completed_source = None
        self.review_completion.hide()
        self.previous_document_button.hide()
        self._document_report_context = None
        self._budget_document_seed = None
        self._budget_context_notice = ""
        self._report_return_destination = self.REPORTS
        self._last_report_tab = 0
        self.back_to_report_button.hide()
        self.report_context.setText("All profile accounts · Reviewed entries only")
        return True

    def _profile_job_busy(self, busy):
        for action in (
            self.new_profile_action,
            self.open_profile_action,
            self.backup_profile_action,
            self.restore_profile_action,
            self.recover_source_action,
        ):
            action.setEnabled(not busy and self.import_worker is None)
        self._update_controls()
        if not busy and self._close_after_job:
            QTimer.singleShot(0, self, self.close)

    def _profile_job_finished(self, key, result):
        handlers = self._profile_job_handlers.pop(key, None)
        self.status.setText("Operation completed.")
        if handlers:
            handlers[0](result)

    def _profile_job_failed(self, key, exc):
        handlers = self._profile_job_handlers.pop(key, None)
        self.status.setText("Operation failed; inspect details and retry.")
        QMessageBox.warning(self, handlers[1] if handlers else "Operation failed", str(exc))

    def _run_profile_job(self, key, operation, on_success, failure_title, status, *, write=True, connection=True):
        if self.profile_jobs.pending or self.import_worker is not None:
            return False
        self._profile_job_handlers[key] = on_success, failure_title
        if not self.profile_jobs.submit(key, operation, write=write, connection=connection):
            self._profile_job_handlers.pop(key, None)
            return False
        self.status.setText(status)
        return True

    def refresh(self, select_source: str | None = None) -> None:
        self._sync_preference_controls()
        revision_changed = profile_revision(self.workspace.profile_path) != self._inventory_revision
        self._inventory_revision = profile_revision(self.workspace.profile_path)
        catalog = self.workspace.catalog_cache.load_current()
        self.catalog_label.setText(
            f"Statement formats ready · Verified catalog release {catalog.release_sequence}"
            if catalog is not None
            else "Install statement formats to enable import. No verified catalog installed."
        )
        self._catalog_available = catalog is not None
        if not self._document_summaries:
            self.setProperty("initialFocusObject", "firstImport" if catalog is not None else "installFormats")
        self.install_catalog_button.setText("Manage statement formats…" if catalog else "Install statement formats…")
        self.catalog_label.setVisible(catalog is None)
        self.install_catalog_button.setVisible(catalog is None)
        for page, view in ((self.ACCOUNTS, self._positions_view), (self.REPORTS, self._reports_view)):
            if view is not None:
                active = self.navigation.currentRow()
                view.invalidate(read=active == page if page == self.ACCOUNTS else active in (self.BUDGET, self.REPORTS))
        if revision_changed and self._transfers_view is not None and self.navigation.currentRow() == self.TRANSFERS:
            self._transfers_view.refresh()
        if revision_changed and self._review_widget is not None:
            refresh_preserving_draft = getattr(self._review_widget, "refresh_preserving_draft", None)
            if refresh_preserving_draft is not None:
                refresh_preserving_draft()
            elif not self._review_has_draft():
                self._review_widget.refresh()
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
            self.sources.replace(())
            self._document_filter_state = DocumentFilters()
            self.document_filters.set_state(self._document_filter_state)
            self.sources.documents_proxy.set_filters(self._document_filter_state)
            self._search_prior_source = None
            self._inventory_profile = self.workspace.profile_path
        self._inventory_generation += 1
        self._inventory_requested = True
        self._document_summaries = {}
        self.inventory_status.setText("Loading saved documents…")
        self.status.clear()
        self._update_controls()
        QTimer.singleShot(0, self, self._start_inventory)

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
            QTimer.singleShot(0, self, self.close)
            return
        if worker.generation == self._inventory_generation:
            if worker.error is not None:
                self._initial_post_pending = None
                self.sources.replace(())
                self._document_summaries = {}
                self.inventory_status.setText("Documents are unavailable. Reload to retry; saved data has not changed.")
                self.inventory_status.setToolTip(str(worker.error))
                self.accounts_list.clear()
                self.accounts_status.setText("Account choices unavailable. Reload documents to retry.")
            else:
                self._inventory_revision = worker.revision
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
                    f"{len(worker.accounts)} account(s)"
                    if worker.accounts
                    else "No accounts yet. Add an account to connect your documents."
                )
                if self._positions_view is not None:
                    self._position_selected()
            self._update_controls()
            if worker.error is None:
                QTimer.singleShot(0, self, self._refresh_changed_profile)
                if self._initial_post_pending is not None:
                    QTimer.singleShot(0, self, self._advance_after_initial_post)
        if self._inventory_requested:
            QTimer.singleShot(0, self, self._start_inventory)

    def _apply_inventory(self, summaries) -> None:
        self._document_summaries = {summary.source_sha256: summary for summary in summaries}
        self.setProperty(
            "initialFocusObject",
            "documentSearch" if summaries else "firstImport" if self._catalog_available else "installFormats",
        )
        self.document_filters.setVisible(bool(summaries) or bool(self._document_filter_state.active_count))
        prior = self._inventory_selection
        scroll = self.sources.verticalScrollBar().value()
        self.document_filters.set_options(summaries)
        self._document_filter_state = self.document_filters.state()
        selection = self.sources.selectionModel()
        was_blocked = selection.blockSignals(True)
        try:
            self.sources.documents_proxy.set_filters(self._document_filter_state)
            self.sources.replace(summaries, prior, select_first=prior is None)
        finally:
            selection.blockSignals(was_blocked)
        self.sources.verticalScrollBar().setValue(scroll)
        self._update_document_count()
        self._sync_review_selector()

    def _filter_documents(self, state) -> None:
        from parsetrail.gui.v2_documents_table import matches

        current = self._selected_source()
        summary = self._document_summaries.get(current)
        if summary is not None and not matches(summary, state) and not self._discard_review():
            self.document_filters.set_state(self._document_filter_state)
            return
        if state.active_count and self._search_prior_source is None:
            self._search_prior_source = current
        selected = self._search_prior_source if not state.active_count else current
        self._document_filter_state = state
        selection = self.sources.selectionModel()
        selection.blockSignals(True)
        try:
            self.sources.documents_proxy.set_filters(state)
            if not self.sources.select_source(selected) and self.sources.model().rowCount():
                self.sources.select_source(self.sources.visible_sources()[0])
        finally:
            selection.blockSignals(False)
        if not state.active_count:
            self._search_prior_source = None
        self._update_document_count()
        self._update_controls()

    def _update_document_count(self):
        if not self.inventory_pending:
            count = self.sources.model().rowCount()
            total = self.sources.documents_model.rowCount()
            self.inventory_status.setText(
                f"{count} of {total} documents"
                if self._document_filter_state.active_count
                else f"{total} saved documents · select one to continue"
                if total
                else "No documents yet. Import a bank statement PDF or a supported CSV export to begin."
                if self._catalog_available
                else "First install a signed statement-format package using Install statement formats above."
            )

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and self.isActiveWindow() and hasattr(self, "_inventory_revision"):
            self._refresh_changed_profile()

    def _refresh_changed_profile(self):
        if self._closing or self.import_worker is not None or self.inventory_pending:
            return
        if profile_revision(self.workspace.profile_path) != self._inventory_revision:
            self.refresh(select_source=self._selected_source())

    def _selected_source(self) -> str | None:
        return self.sources.selected_source()

    def _update_controls(self, *_args) -> None:
        source_id = self._selected_source()
        summary = self._document_summaries.get(source_id)
        if summary is not None and self._review_widget is not None and self._review_source_id != source_id:
            previous_source = self._review_source_id
            if not self._discard_review():
                self.sources.selectionModel().blockSignals(True)
                self.sources.select_source(previous_source)
                self.sources.selectionModel().blockSignals(False)
                return
        available = (
            summary is not None and not self.inventory_pending and not self._write_in_progress() and not self._closing
        )
        self.review_period.setVisible(summary is not None)
        self.review_period.setText(document_period(summary) if summary is not None else "")
        self.sources.setEnabled(not self.inventory_pending and not self._write_in_progress() and not self._closing)
        self.document_filters.setEnabled(
            not self.inventory_pending and not self._write_in_progress() and not self._closing
        )
        if self._review_widget is not None:
            self._review_widget.setEnabled(summary is not None and not self._closing)
        self.recover_source_action.setEnabled(available)
        self.preview_button.setEnabled(available)
        self.open_original_button.setEnabled(available)
        batch_available = not self._write_in_progress() and not self._closing
        self.import_button.setEnabled(self._catalog_available and batch_available)
        self.import_folder_button.setEnabled(self.import_button.isEnabled())
        for action in (
            self.new_profile_action,
            self.open_profile_action,
            self.backup_profile_action,
            self.restore_profile_action,
            self.add_financial_account_action,
            self.edit_financial_account_action,
            self.account_anchors_action,
            self.source_values_action,
            self.source_opening_action,
            self.transfer_review_action,
            self.settlement_review_action,
            self.loan_payment_action,
        ):
            action.setEnabled(batch_available)
        self.install_catalog_button.setEnabled(batch_available)
        self.formats_action.setEnabled(batch_available)
        self.folder_action.setEnabled(self.import_folder_button.isEnabled())
        self.document_assign_action.setEnabled(batch_available)
        self.document_details_action.setEnabled(available)
        for button in (self.account_button, self.edit_account_button, self.categories_button, self.openings_button):
            button.setEnabled(batch_available)
        consolidation_available = (
            batch_available
            and not self.profile_jobs.pending
            and not self.inventory_pending
            and self.accounts_list.count() >= 2
        )
        self.consolidate_accounts_action.setEnabled(consolidation_available)
        self.consolidate_accounts_button.setEnabled(consolidation_available)
        self.batch_accounts_button.setEnabled(batch_available)
        self.batch_accounts_action.setEnabled(batch_available)
        self.review_document_button.setEnabled(available)
        self.document_details_button.setEnabled(available)
        self.review_document_selector.setEnabled(
            batch_available and not self.inventory_pending and bool(self._document_summaries)
        )
        self.review_document_selector.blockSignals(True)
        self.review_document_selector.setCurrentIndex(self.review_document_selector.findData(source_id))
        self.review_document_selector.blockSignals(False)
        self.next_document_button.setEnabled(
            batch_available
            and not self.inventory_pending
            and any(self._needs_attention(item) for item in self._document_summaries.values())
        )
        self.document_spending_button.setEnabled(
            available
            and summary.start is not None
            and summary.end is not None
            and summary.start <= summary.end < date.max
        )
        is_card = summary is not None and summary.parser_id in CARD_STATEMENT_PARSERS
        is_register = summary is not None and summary.parser_id == REGISTER_PARSER
        is_summary = summary is not None and summary.parser_id in SUMMARY_VALUE_PARSERS
        self.document_spending_button.setText("View account value" if is_summary else "View spending")
        self.document_spending_button.setToolTip(
            "View this account's recorded value at the statement end date."
            if is_summary
            else "View reviewed spending for this document's dates."
        )
        if is_summary:
            self.document_spending_button.setEnabled(
                available and summary.end is not None and len(summary.associated_account_ids) == 1
            )
        self.cash_review_button.setEnabled(available and not is_card and not is_register and not is_summary)
        self.cash_review_button.setVisible(not is_card and not is_register and not is_summary)
        self.card_review_button.setEnabled(available and is_card)
        self.card_review_button.setVisible(is_card)
        self.register_review_action.setEnabled(available and is_register)
        self.register_button.setEnabled(available and is_register)
        self.register_button.setVisible(is_register)
        self.source_review_button.setEnabled(available and summary.has_identified_accounts)
        self.source_review_button.setVisible(bool(summary and summary.has_identified_accounts))
        self.change_document_account_action.setEnabled(available and summary.has_identified_accounts)
        self.change_row_accounts_action.setEnabled(available and summary.has_unidentified_rows)
        self.source_review_button.setText(
            "Confirm document accounts"
            if summary and summary.unassigned_source_accounts
            else "Change document accounts…"
        )
        self.review_button.setEnabled(available and summary.has_unidentified_rows)
        self.review_button.setText(
            "Review row account assignments"
            if summary is not None and summary.has_unidentified_rows and summary.assigned_row_count
            else "Assign rows without an account"
        )
        if summary is not None:
            details = f"{document_title(summary)}\n{document_period(summary)} · {summary.row_count} source row(s)"
            if summary.overlapping_source_ids:
                details += (
                    f"\nPossible period overlap with {len(summary.overlapping_source_ids)} other document(s) "
                    "on a confirmed account. Check possible repeated rows before posting."
                )
            association = document_account_association(summary)
            self.selected_details.setText(f"{details}\n{association}")
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
            # Document and dates remain directly above in the selector. Keep the
            # working area for decisions and enough source rows to compare.
            partial_assignment = bool(
                summary.assigned_row_count and (summary.unassigned_source_accounts or summary.unassigned_activity_rows)
            )
            self.review_context.setText(
                (
                    "Statement value needs review"
                    if summary.pending_summary_values == 1
                    else f"{summary.pending_summary_values} statement values need review"
                )
                + " · summary totals are not transactions"
                if summary.pending_summary_values
                else "Statement value recorded · summary review complete"
                if is_summary and summary.reviewed_summary_values
                else f"{summary.pending_activity_rows} imported rows not posted · may include repeats or pending transfers"
                if summary.pending_activity_rows
                else "No pending imported rows · source coverage still needs checking"
            )
            account_state = (
                "No activity rows captured. Inspect source evidence and document checks before interpreting totals."
                if not summary.row_count
                else "Confirm the account before reviewing activity. Account assignment adds no spending."
                if summary.unassigned_source_accounts or summary.unassigned_activity_rows
                else "Review the statement's values below, then record its closing value."
                if summary.pending_summary_values
                else "Value recorded. Inspect its source or saved value history below."
                if is_summary and summary.reviewed_summary_values
                else "Choose rows below, then add your review choices."
                if summary.pending_activity_rows
                else "Review saved choices or open Budget for the monthly result."
            )
            self.review_progress.setText("" if partial_assignment else account_state)
            self.account_assignment_status.setText(
                "Review confirmed rows; "
                + (
                    f"{summary.unassigned_source_accounts} document account(s) still need assignment."
                    if summary.unassigned_source_accounts
                    else f"{summary.unassigned_activity_rows} row(s) still need an account."
                )
                if partial_assignment
                else f"{summary.unassigned_source_accounts} document account(s) need confirmation."
                if summary.unassigned_source_accounts
                else f"{summary.unassigned_activity_rows} activity row(s) still need a confirmed account."
                if summary.unassigned_activity_rows
                else association + ". Account assignment is separate from activity review."
            )
            self.review_document_button.setText(
                "Confirm account"
                if summary.unassigned_activity_rows or summary.unassigned_source_accounts
                else "Review statement value"
                if summary.pending_summary_values
                else "View statement value"
                if is_summary
                else "Review activity"
                if summary.pending_activity_rows
                else "View document"
            )
            set_field_state(
                self.review_document_button,
                "ready"
                if summary.unassigned_activity_rows
                or summary.unassigned_source_accounts
                or summary.pending_summary_values
                or summary.pending_activity_rows
                else "neutral",
            )
            self.review_guidance.setText(
                "Review confirmed rows below. Assign the remaining accounts before reviewing their activity."
                if partial_assignment
                else "Confirm the document account first. Suggestions need your confirmation."
                if summary.unassigned_activity_rows or summary.unassigned_source_accounts
                else "Record the printed closing value. Contributions and market changes remain summary evidence."
                if summary.pending_summary_values
                else "The statement value is recorded. Summary totals do not create individual transactions or budget effects."
                if is_summary and summary.reviewed_summary_values
                else "Review supported activity or check repeated evidence. Unallocated counts can include supporting copies; "
                "do not post them twice. Transfers, repayments and loan splits have separate review."
                if summary.pending_activity_rows
                else "Activity has full allocation. Statement checks, source completeness and corrections remain separate tasks."
            )
            self.account_group.setTitle(
                "Confirm account"
                if not partial_assignment and (summary.unassigned_source_accounts or summary.unassigned_activity_rows)
                else ""
            )
            self.account_group.setFlat(partial_assignment)
            if partial_assignment:
                self.account_group.layout().setContentsMargins(0, 0, 0, 0)
            else:
                self.account_group.layout().setContentsMargins(self._account_group_margins)
            self.account_group.setVisible(bool(summary.unassigned_source_accounts or summary.unassigned_activity_rows))
            self.review_button.setVisible(summary.has_unidentified_rows)
            if self.navigation.currentRow() == self.REVIEW:
                self._ensure_review_view()
        else:
            self.selected_details.setText("Select a document to see its account, dates and next action.")
            self.account_group.hide()
            self.document_technical_details.clear()
            self.review_context.setText("Choose a document in Documents to start or resume its review.")
            self.account_assignment_status.setText("Account status will appear when a document is selected.")
            self.review_guidance.setText(
                "Document details are loading." if self.inventory_pending else "Choose a document first."
            )
            self.review_progress.setText(
                "Loading documents… Saved entries are unchanged."
                if self.inventory_pending
                else self.inventory_status.text()
                if not self._document_summaries
                else "Choose a document above to review its account and activity."
            )
            self.review_empty.setText(
                "Import documents from Documents to begin. Account assignment and reviewed activity are separate steps."
                if not self.inventory_pending and not self.sources.documents_model.rowCount()
                else "Choose a document to see its supported activity and remaining decisions."
            )
            self.review_empty.setVisible(self._review_widget is None)

    def _assign_document_accounts(self) -> None:
        if self.import_worker is not None or self._closing:
            return
        source_id = self._selected_source()
        dialog = V2BatchAccountAssignment(self.workspace, self)
        dialog.exec()
        if dialog.changed:
            self.refresh(select_source=source_id)

    def _open_original(self) -> None:
        source_id = self._selected_source()
        if source_id is None or self.import_worker is not None:
            return
        operation = open_original_document(self.workspace.profile_path, source_id, self)
        self.statusBar().showMessage(operation.status)
        operation.status_changed.connect(self.statusBar().showMessage)

    def _review_document(self, *_args) -> None:
        summary = self._document_summaries.get(self._selected_source())
        if summary is None or self.import_worker is not None:
            return
        self.navigation.setCurrentRow(self.REVIEW)
        if summary.unassigned_source_accounts:
            self._review_source_account()
        elif summary.unassigned_activity_rows:
            self._review_account()
        elif summary.parser_id in SUMMARY_VALUE_PARSERS:
            self._ensure_review_view()
            self._review_widget.action_button.setFocus()
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
        self.navigation.setCurrentRow(self.ACCOUNTS)
        self.account_details_toggle.setChecked(True)

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
        folder = Path(directory)
        self._run_profile_job(
            "scan_folder",
            lambda _store, _cancelled: folder_source_files(folder),
            self.start_batch_import,
            "Folder was not imported",
            "Finding supported documents in the selected folder…",
            connection=False,
        )

    def _choose_catalog_release(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Select signed statement formats (folder containing catalog.json and catalog.sig)"
        )
        if not directory:
            return
        workspace, package = self.workspace, Path(directory)

        def installed(release):
            self.refresh()
            message = f"Statement formats ready. Verified catalog release {release.catalog.release_sequence} installed."
            if release.institution_error_code:
                message += (
                    " Institution names could not be retained in this profile. Retry when the profile is available; "
                    "account creation will also retry. Details: " + release.institution_error_code
                )
            self.status.setText(message)

        self._run_profile_job(
            "install_formats",
            lambda _store, _cancelled: workspace.install_catalog_release(package),
            installed,
            "Statement formats were not installed",
            "Verifying the signed statement-format package…",
            connection=False,
        )

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
        if self._write_in_progress():
            self.status.setText("Finish the current confirmed operation before opening another profile.")
            return
        previous = self.workspace
        previous_source = self._selected_source()
        try:
            selected.verify_local_configuration()
            source_ids = selected.source_ids()
            candidate_source = previous_source if previous_source in source_ids else next(iter(source_ids), None)
            if candidate_source is not None:
                selected.saved_import(candidate_source)
                selected.overlapping_statement_sources(candidate_source)
            if not self._discard_review() or not self._reset_embedded_views():
                return
            self.profile_jobs.close()
            self._profile_job_handlers.clear()
            self.profile_jobs.deleteLater()
            self.profile_jobs = ProfileJobs(self, selected.profile_path)
            self.profile_jobs.completed.connect(self._profile_job_finished)
            self.profile_jobs.failed.connect(self._profile_job_failed)
            self.profile_jobs.busy_changed.connect(self._profile_job_busy)
            self.workspace = selected
            self.refresh()
        except (ProfileFormatError, sqlite3.Error, OSError, ValueError) as exc:
            self.workspace = previous
            try:
                self.refresh(select_source=previous_source)
            except (ProfileFormatError, sqlite3.Error, OSError, ValueError):
                self.sources.replace(())
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
        self.profile_name.setText(selected.profile_path.stem)
        self.profile_name.setToolTip(str(selected.profile_path))
        if self.navigation.currentRow() in (self.ACCOUNTS, self.BUDGET, self.REPORTS):
            self._ensure_report_view(self.navigation.currentRow())
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
        workspace = self.workspace

        def choose_destination(suffix):
            if workspace is not self.workspace or self._selected_source() != source_id:
                return
            proposed = workspace.profile_path.with_name(f"source-{source_id[:16]}{suffix}")
            selected, _filter = QFileDialog.getSaveFileName(
                self, "Save selected source original", str(proposed), "All files (*)"
            )
            if not selected:
                return
            destination = Path(selected)
            self._run_profile_job(
                "recover_original",
                lambda _store, _cancelled: workspace.recover_source_original(source_id, destination),
                lambda saved: show_path_notice(
                    self,
                    "Source original saved",
                    "Saved the exact original document retained in this profile:",
                    saved,
                    "This file contains financial data and is not encrypted by ParseTrail. "
                    "The profile and its saved evidence were not changed.",
                ),
                "Source original was not saved",
                "Verifying and saving the selected original…",
            )

        self._run_profile_job(
            "prepare_recovery",
            lambda store, _cancelled: store.load_import(source_id).suffix,
            choose_destination,
            "Source original unavailable",
            "Loading the selected original…",
            write=False,
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
        source = self.workspace.profile_path
        self._run_profile_job(
            "backup",
            lambda _store, _cancelled: V2ProfileStore.snapshot_to(source, destination),
            lambda saved: show_path_notice(
                self,
                "Backup verified",
                "Verified 2.0 profile backup:",
                saved,
                "This file contains financial source evidence and is not encrypted by ParseTrail.",
            ),
            "Backup was not created",
            "Creating and verifying profile backup…",
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
        backup_path = Path(backup)
        self._run_profile_job(
            "restore",
            lambda _store, _cancelled: V2ProfileStore.snapshot_to(backup_path, destination),
            self._switch_profile,
            "Restore was not created",
            "Restoring and verifying a new profile…",
            connection=False,
        )

    def start_import(self, source_path: Path) -> None:
        if self.import_worker is not None:
            return
        self.import_worker = V2ImportWorker(self.workspace, source_path, self)
        self.import_worker.finished.connect(self._import_finished, Qt.QueuedConnection)
        self.import_worker.import_review_requested.connect(self._review_import_accounts)
        self._begin_import_progress((source_path,))
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
        self._update_controls()
        self.import_worker.start()

    def start_batch_import(self, paths: tuple[Path, ...]) -> None:
        if self.import_worker is not None or not paths:
            return
        self.import_worker = V2BatchImportWorker(self.workspace, paths, self)
        self.import_worker.progressed.connect(self._batch_progress)
        self.import_worker.outcomes_changed.connect(self._batch_outcomes)
        self.import_worker.finished.connect(self._import_finished, Qt.QueuedConnection)
        self.import_worker.import_review_requested.connect(self._review_import_accounts)
        self._begin_import_progress(paths)
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
        self._update_controls()
        self.import_worker.start()

    def _begin_import_progress(self, paths):
        self._import_generation += 1
        self._import_review_request = None
        self._import_avoid = ()
        self.progress = V2ImportProgress(paths, self)
        self.progress.cancel_remaining.connect(self._cancel_import)
        self._queue_import_surface("progress")

    def _queue_import_surface(self, kind, request=None):
        # A parent-owned timer crosses the native button/close callback boundary.
        # Replacing this tuple invalidates any earlier decision's pending handoff.
        self._import_presentation = (self._import_generation, self.import_worker, kind, request)
        self._import_presentation_timer.start(0)

    def _show_import_surface(self):
        pending, self._import_presentation = self._import_presentation, None
        if pending is None:
            return
        generation, worker, kind, request = pending
        if generation != self._import_generation or worker is not self.import_worker or self.progress is None:
            return
        if worker.isFinished():
            # Its queued finished delivery owns the outcome and cleanup. Do not
            # flash an obsolete surface ahead of that delivery.
            return
        if kind == "review":
            if request is not self._import_review_request or request.decided.is_set():
                return
            if worker.cancel_event.is_set() or self._close_after_import:
                request.finish(None)
                self._cancel_import()
                return
            try:
                if self.import_preview is None:
                    self.import_preview = V2ImportAccountReview(self.workspace.institutions(), self)
                    self.import_preview.abbreviated_matching_changed.connect(self._set_abbreviated_matching)
                    self.import_preview.import_preview_mode_changed.connect(self._set_import_preview_mode)
                    self.import_preview.cancel_remaining.connect(self._cancel_import)
                    self.import_preview.decision_submitted.connect(self._import_decision_submitted)
                self.progress.hide()
                self.import_preview.present(request)
            except Exception:
                request.fail()
                self._import_review_request = None
                self._queue_import_surface("progress")
            return
        # A new input request always outranks a queued automatic-work handoff.
        active = self._import_review_request
        if active is not None and not active.decided.is_set():
            return
        if request is not None and request is not active:
            return
        if self.import_preview is not None:
            self.import_preview._cancel_original()
            if self.import_preview.isVisible():
                self._import_avoid = (
                    tuple(
                        button.rect().translated(button.mapToGlobal(button.rect().topLeft()))
                        for button in (
                            self.import_preview.next_button,
                            self.import_preview.import_button,
                            self.import_preview.skip_button,
                        )
                        if button.isVisible()
                    )
                    or self._import_avoid
                )
            self.import_preview.hide()
        self.progress.present(self._import_avoid)

    def _import_decision_submitted(self, request, decision):
        if request is not self._import_review_request or self.import_worker is None or self.progress is None:
            return
        # Retained primary/secondary slots preserve the preceding decision
        # coordinates while the neutral page is already showing.
        self._import_avoid = tuple(
            button.rect().translated(button.mapToGlobal(button.rect().topLeft()))
            for button in (
                self.import_preview.next_button,
                self.import_preview.import_button,
                self.import_preview.skip_button,
            )
        )
        self.progress.set_current(
            request.index,
            request.path,
            "Saving the confirmed original, accounts and assignments…"
            if decision == "import"
            else "Skipping this file… Provisional accounts are not saved.",
        )
        self._queue_import_surface("progress", request)

    def _cancel_import(self):
        worker = self.import_worker
        if worker is None:
            return
        worker.cancel()
        request, self._import_review_request = self._import_review_request, None
        if request is not None:
            request.finish(None)
        if self.progress is not None:
            self.progress.cancelling()
            self._queue_import_surface("progress")

    def _review_import_accounts(self, request):
        worker = self.import_worker
        if (
            worker is None
            or self.sender() is not worker
            or worker.cancel_event.is_set()
            or self._closing
            or self._close_after_import
        ):
            request.finish(None)
            return
        self._import_review_request = request
        self._queue_import_surface("review", request)

    def _batch_progress(self, count: int, filename: str) -> None:
        if self.import_worker is None or self.sender() is not self.import_worker or self.progress is None:
            return
        self._import_review_request = None
        paths = self.import_worker.paths
        self.progress.set_current(
            count + 1 if count < len(paths) else count,
            paths[count] if count < len(paths) else paths[-1],
            "Reading and checking the document…" if count < len(paths) else "Finishing the batch report…",
        )
        self._queue_import_surface("progress")

    def _batch_outcomes(self, outcomes):
        if self.import_worker is not None and self.sender() is self.import_worker and self.progress is not None:
            self.progress.update_outcomes(outcomes)

    def _import_finished(self) -> None:
        worker = self.import_worker
        if worker is None:
            return
        if not worker.wait(1000):
            QTimer.singleShot(10, self, self._import_finished)
            return
        result, error = worker.result, worker.error
        clear_exception_tracebacks(error)
        self._import_generation += 1
        self._import_presentation_timer.stop()
        self._import_presentation = None
        self._import_review_request = None
        self._import_avoid = ()
        if self.import_preview is not None:
            self.import_preview.finish_queue()
            self.import_preview.deleteLater()
            self.import_preview = None
        if self.progress is not None:
            self.progress.finish()
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
        self._update_controls()
        if self._close_after_import:
            QTimer.singleShot(0, self, self.close)
            return
        if isinstance(worker, V2BatchImportWorker):
            if result is None:
                self.refresh()
                self.status.setText("Batch import could not start.")
                QMessageBox.warning(
                    self, "Batch import failed", import_failure_guidance(str(error or "Unknown import error"))
                )
                return
            imported = [item for item in result.files if item.status == "imported"]
            self.refresh(select_source=imported[-1].source_sha256 if imported else None)
            failures = sum(item.status == "failed" for item in result.files)
            automatic = []
            loans = sum(
                item.loan_automation is not None and item.loan_automation.status == "posted" for item in imported
            )
            values = sum(
                item.statement_value_automation is not None and item.statement_value_automation.status == "recorded"
                for item in imported
            )
            if loans:
                automatic.append(f"{loans} loan payment(s) posted automatically")
            if values:
                automatic.append(f"{values} statement value(s) recorded automatically")
            self.status.setText(
                f"Batch finished: {len(imported)} imported, {failures} failed. "
                + ("; ".join(automatic) + ". " if automatic else "")
                + "Other activity or statement values may need review."
            )
            exec_disposable(V2BatchImportReport(result, self))
            return
        if result is not None:
            self.refresh(select_source=result.source_sha256)
            self.status.setText(
                import_automation_summary(result) or "Source imported; evidence is pending review."
                if result.status == "imported"
                else "This exact source was already imported."
            )
        elif isinstance(error, ImportSkipped):
            self.status.setText("File skipped; no new source saved. Choose another document to continue.")
            self._update_controls()
        elif isinstance(error, ImportCancelled):
            self.status.setText("Import cancelled; no new source saved.")
            self.import_button.setEnabled(self.workspace.catalog_cache.load_current() is not None)
            self.import_folder_button.setEnabled(self.import_button.isEnabled())
        else:
            self.status.setText("Import failed; no new source saved.")
            self.import_button.setEnabled(self.workspace.catalog_cache.load_current() is not None)
            self.import_folder_button.setEnabled(self.import_button.isEnabled())
            QMessageBox.warning(self, "Import failed", import_failure_guidance(str(error or "Unknown import error")))

    def _preview(self, *_args) -> None:
        source_id = self._selected_source()
        if source_id is not None:

            def show(saved):
                if self._selected_source() == source_id:
                    exec_disposable(V2EvidencePreview(saved, self))

            self._run_profile_job(
                "preview",
                lambda store, _cancelled: store.load_import(source_id),
                show,
                "Evidence preview unavailable",
                "Loading selected source evidence…",
                write=False,
            )

    def _review_cash_activity(self) -> None:
        source_id = self._selected_source()
        if source_id is not None:
            self.navigation.setCurrentRow(self.REVIEW)
            self._ensure_review_view()

    def _review_card_purchases(self) -> None:
        source_id = self._selected_source()
        if source_id is not None:
            self.navigation.setCurrentRow(self.REVIEW)
            self._ensure_review_view()

    def _review_transfers(self) -> None:
        if self.import_worker is not None:
            return
        self._open_transfers()

    def _review_manual_transfers(self) -> None:
        if self._write_in_progress():
            return
        exec_disposable(V2TransferReview(self.workspace, self))
        self.assumed_posting_action.blockSignals(True)
        self.assumed_posting_action.setChecked(self.workspace.preferences().allow_assumed_posting_dates)
        self.assumed_posting_action.blockSignals(False)
        self._refresh_changed_profile()

    def _review_settlements(self) -> None:
        if self.import_worker is not None:
            return
        from parsetrail.gui.v2_settlement_review import V2SettlementReview

        V2SettlementReview(self.workspace, parent=self).exec()
        self.assumed_posting_action.blockSignals(True)
        self.assumed_posting_action.setChecked(self.workspace.preferences().allow_assumed_posting_dates)
        self.assumed_posting_action.blockSignals(False)
        self._refresh_changed_profile()

    def _review_loan_payments(self) -> None:
        if self.import_worker is not None:
            return
        from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview

        V2LoanPaymentReview(self.workspace, parent=self).exec()
        self.assumed_posting_action.blockSignals(True)
        self.assumed_posting_action.setChecked(self.workspace.preferences().allow_assumed_posting_dates)
        self.assumed_posting_action.blockSignals(False)
        self._refresh_changed_profile()

    def _review_register_activity(self) -> None:
        if self.import_worker is not None:
            return
        source_id = self._selected_source()
        summary = self._document_summaries.get(source_id)
        if summary is None or summary.parser_id != REGISTER_PARSER:
            return
        self.navigation.setCurrentRow(self.REVIEW)
        self._ensure_review_view()

    def _open_reviewed_reports(self) -> None:
        self.navigation.setCurrentRow(self.REPORTS)
        self._ensure_report_view(self.REPORTS)

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
        error = ""
        try:
            self.workspace.set_allow_abbreviated_account_matching(enabled)
        except (OSError, ValueError) as exc:
            error = str(exc)
            QMessageBox.warning(self, "Preference was not saved", str(exc))
        self._sync_preference_controls(error)

    def _preview_mode_selected(self, action):
        self._set_import_preview_mode(action.data())

    def _set_import_preview_mode(self, mode):
        error = ""
        try:
            self.workspace.set_import_preview_mode(mode)
        except (OSError, ValueError) as exc:
            error = str(exc)
            QMessageBox.warning(self, "Preference was not saved", str(exc))
        self._sync_preference_controls(error)

    def _sync_preference_controls(self, error=""):
        try:
            preferences = self.workspace.preferences()
        except (OSError, ValueError):
            self.status.setText("Preferences unavailable. Imports require valid settings; reopen after checking them.")
            return
        self.abbreviated_matching_action.blockSignals(True)
        self.abbreviated_matching_action.setChecked(preferences.allow_abbreviated_account_matching)
        self.abbreviated_matching_action.blockSignals(False)
        self.auto_post_loan_action.blockSignals(True)
        self.auto_post_loan_action.setChecked(preferences.auto_post_loan_payments)
        self.auto_post_loan_action.blockSignals(False)
        self.auto_record_statement_values_action.blockSignals(True)
        self.auto_record_statement_values_action.setChecked(preferences.auto_record_statement_values)
        self.auto_record_statement_values_action.blockSignals(False)
        if self._review_widget is not None and hasattr(self._review_widget, "sync_preferences"):
            self._review_widget.sync_preferences(preferences)
        self.assumed_posting_action.blockSignals(True)
        self.assumed_posting_action.setChecked(preferences.allow_assumed_posting_dates)
        self.assumed_posting_action.blockSignals(False)
        for key, action in self.preview_mode_actions.items():
            action.setChecked(key == preferences.import_preview_mode)
        if self.import_preview is not None:
            self.import_preview.sync_preferences(
                preferences.allow_abbreviated_account_matching, preferences.import_preview_mode, error
            )

    def _set_assumed_posting_dates(self, enabled: bool) -> None:
        try:
            self.workspace.set_allow_assumed_posting_dates(enabled)
        except (OSError, ValueError) as exc:
            self.assumed_posting_action.blockSignals(True)
            self.assumed_posting_action.setChecked(not enabled)
            self.assumed_posting_action.blockSignals(False)
            QMessageBox.warning(self, "Preference was not saved", str(exc))

    def _set_auto_post_loan_payments(self, enabled: bool) -> None:
        error = ""
        try:
            self.workspace.set_auto_post_loan_payments(enabled)
            self.status.setText(
                "Automatic loan posting enabled for future supported imports. Principal reduces debt; interest is expense; "
                "paying-account counterparts stay in Transfers."
                if enabled
                else "Automatic loan posting disabled. Future payments will need review."
            )
        except (OSError, ValueError) as exc:
            error = str(exc)
            QMessageBox.warning(self, "Preference was not saved", str(exc))
        self._sync_preference_controls(error)

    def _set_auto_record_statement_values(self, enabled: bool) -> None:
        error = ""
        try:
            self.workspace.set_auto_record_statement_values(enabled)
            self.status.setText(
                "Automatic statement value recording enabled for future supported imports. "
                "Summary totals remain evidence; no transactions or budget changes."
                if enabled
                else "Automatic statement value recording disabled. Future statement values will need review."
            )
        except (OSError, ValueError) as exc:
            error = str(exc)
            QMessageBox.warning(self, "Preference was not saved", str(exc))
        self._sync_preference_controls(error)

    def _add_account(self) -> None:
        try:
            dialog = V2FinancialAccountDialog(self)
        except (ProfileFormatError, sqlite3.Error, OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Account choices unavailable",
                f"Institution choices could not be read. Reload the profile and try again.\n\nDetails: {exc}",
            )
            return
        while dialog.exec() == QDialog.Accepted:
            try:
                with V2ProfileStore.open(self.workspace.profile_path) as store:
                    catalog = self.workspace.catalog_cache.load_current()
                    store.add_financial_account(dialog.account(), catalog=catalog)
            except (ProfileFormatError, sqlite3.Error, OSError) as exc:
                QMessageBox.warning(self, "Account was not saved", str(exc))
                continue
            self.status.setText(
                "Financial account and tracking scope saved. Bind sources or review its opening and values."
            )
            self.refresh()
            break

    def _consolidate_accounts(self) -> None:
        if (
            self._closing
            or self._consolidation_dialog is not None
            or self._write_in_progress()
            or self.profile_jobs.pending
            or self.inventory_pending
            or self.accounts_list.count() < 2
        ):
            return
        if not self._discard_review():
            return
        current = self.accounts_list.currentItem()
        selected_id = current.data(Qt.UserRole) if current is not None else None
        dialog = V2AccountConsolidation(self.workspace.profile_path, selected_id, parent=self)
        dialog.consolidated.connect(self._accounts_consolidated)
        dialog.jobs.busy_changed.connect(self._embedded_busy)
        self._consolidation_dialog = dialog
        try:
            exec_disposable(dialog)
        finally:
            self._consolidation_dialog = None
            self._update_controls()

    def _accounts_consolidated(self, kept_id: str) -> None:
        # refresh owns revision invalidation for documents, reports and positions.
        # Set the account selection after it captures the previous selection.
        self.refresh(select_source=self._selected_source())
        self._inventory_account_selection = kept_id
        self.navigation.setCurrentRow(self.ACCOUNTS)
        self.status.setText("Account records consolidated. The kept account contains their saved history.")

    def _edit_account(self, *_args) -> None:
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                accounts = store.active_financial_accounts()
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
        try:
            dialog = V2FinancialAccountDialog(self, existing=account, scope_locked=scope_locked)
        except (ProfileFormatError, sqlite3.Error, OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Account choices unavailable",
                f"Institution choices could not be read. Reload the profile and try again.\n\nDetails: {exc}",
            )
            return
        while dialog.exec() == QDialog.Accepted:
            try:
                with V2ProfileStore.open(self.workspace.profile_path) as store:
                    catalog = self.workspace.catalog_cache.load_current()
                    store.update_financial_account(dialog.account(), catalog=catalog)
            except (ProfileFormatError, sqlite3.Error, OSError) as exc:
                QMessageBox.warning(self, "Account was not saved", str(exc))
                continue
            self.refresh()
            self.status.setText("Financial account details saved. Existing source bindings and postings keep this ID.")
            break

    def _edit_categories(self) -> None:
        exec_disposable(V2CategoryDialog(self.workspace.profile_path, self))
        self._categories_changed()

    def _review_openings(self) -> None:
        V2OpeningReview(self.workspace, self).exec()
        self._refresh_changed_profile()

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
        if self._write_in_progress():
            self._close_after_job = True
            if self.import_worker is not None:
                self._close_after_import = True
                self._cancel_import()
            self.status.setText("Finishing the current operation before closing…")
            return False
        if self._consolidation_dialog is not None:
            self._consolidation_dialog.reject()
        if not self._discard_review() or not self._reset_embedded_views():
            return False
        self.profile_jobs.close()
        self._profile_job_handlers.clear()
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
            self._cancel_import()
            self.status.setText("Cancelling import before closing…")
            event.ignore()
            return
        if self._write_in_progress():
            self._close_after_job = True
            self.status.setText("Finishing the confirmed operation before closing…")
            event.ignore()
            return
        if self._consolidation_dialog is not None:
            self._consolidation_dialog.reject()
        if not self._discard_review() or not self._reset_embedded_views():
            event.ignore()
            return
        self.profile_jobs.close()
        self._profile_job_handlers.clear()
        self._closing = True
        self._inventory_requested = False
        if self._inventory_worker is not None:
            self._inventory_worker.requestInterruption()
            event.ignore()
            return
        super().closeEvent(event)

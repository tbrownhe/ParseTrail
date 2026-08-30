import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from loguru import logger
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core import learn, plot
from parsetrail.core.artifacts import ArtifactService, ArtifactServiceError
from parsetrail.core.build_metadata import build_provenance_label
from parsetrail.core.client import (
    ClientUpdateThread,
    install_client,
)
from parsetrail.core.dashboard import DashboardQueryService, DashboardServiceError
from parsetrail.core.initialize import initialize_db
from parsetrail.core.parser_routing import ParseError, ParseWarningsRejectedError, present_parse_error
from parsetrail.core.plugins import PluginManager, PluginUpdateThread
from parsetrail.core.review import TransactionReviewError, TransactionReviewService
from parsetrail.core.settings import save_settings, settings
from parsetrail.core.statements import ArchivePendingError
from parsetrail.core.utils import open_file_in_os
from parsetrail.gui.accounts import (
    AppreciationDialog,
    BalanceCheckDialog,
    EditAccountsDialog,
)
from parsetrail.gui.budget_view import BudgetTab
from parsetrail.gui.category import CategoryManagerDialog
from parsetrail.gui.dashboard_widgets import MatplotlibCanvas, PandasModel
from parsetrail.gui.importing import StatementImportController, choose_source_file_action
from parsetrail.gui.plugins import (
    ParseTestDialog,
    PluginManagerDialog,
    PluginSyncDialog,
    start_plugin_sync,
)
from parsetrail.gui.preferences import PreferencesDialog
from parsetrail.gui.send import StatementSubmissionDialog
from parsetrail.gui.statements import CompletenessDialog
from parsetrail.gui.transactions import (
    InsertTransactionDialog,
    RecurringTransactionsDialog,
)
from parsetrail.gui.verification import TransactionReviewWindow
from parsetrail.version import (
    __developer__,
    __repo__,
    __version__,
    __website__,
    __year__,
)

AUTOMATIC_UPDATE_DELAY_MS = 3000


class ParseTrail(QMainWindow):
    def __init__(self):
        super().__init__()
        # Set the custom exception hook
        sys.excepthook = self.exception_hook

        # Initialize the GUI window
        self.setWindowTitle("ParseTrail")
        self.resize(1000, 800)

        # Maximize to primary screen
        screen = QApplication.primaryScreen()
        geometry = screen.availableGeometry()
        self.setGeometry(
            int(0.2 * geometry.width()),
            int(0.1 * geometry.height()),
            int(0.6 * geometry.width()),
            int(0.8 * geometry.height()),
        )
        self.showMaximized()

        # Non modal window handles
        self.transaction_review_window = None

        # MENU BAR #######################
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("File")
        file_menu.addAction("Preferences", self.preferences)
        file_menu.addAction("Open Database", self.open_db)
        file_menu.addAction("Export Account Configuration", self.export_init_accounts)

        # Plugins Menu
        plugins_menu = menubar.addMenu("Plugins")
        plugins_menu.addAction("Plugin Manager", self.manage_plugins)
        plugins_menu.addAction("Troubleshoot Parsing", self.parse_test)

        # Accounts Menu
        accounts_menu = menubar.addMenu("Accounts")
        accounts_menu.addAction("Edit Accounts", self.edit_accounts)
        accounts_menu.addAction("Appreciation Calculator", self.appreciation_calc)

        # Statements Menu
        statements_menu = menubar.addMenu("Statements")
        statements_menu.addAction("Import All", self.import_all_statements)
        statements_menu.addAction("Pick File for Import", self.import_one_statement)
        statements_menu.addAction("Completeness Grid", self.statement_matrix)
        statements_menu.addAction("Correct Discrepancies", self.statement_discrepancies)
        statements_menu.addAction("Send for Plugin Development", self.send_statement)

        # Categories Menu
        categorize_menu = menubar.addMenu("Categories")
        categorize_menu.addAction("Category Manager", self.open_category_manager)

        # Transactions Menu
        transactions_menu = menubar.addMenu("Transactions")
        transactions_menu.addAction("Review Transactions", self.open_transaction_review)
        transactions_menu.addAction("Identify Recurring", self.recurring_transactions)
        transactions_menu.addAction("Insert Manually", self.insert_transaction)

        # Train Model Menu
        train_menu = menubar.addMenu("Train Model")
        train_menu.addAction("Train Model for Testing", self.train_pipeline_test)
        train_menu.addAction("Train Model for Deployment", self.train_pipeline_save)

        # Reports Menu
        reports_menu = menubar.addMenu("Reports")
        reports_menu.addAction("Export Three Months", self.report_3months)
        reports_menu.addAction("Export One Year", self.report_1year)
        reports_menu.addAction("Export All Time", self.report_all_time)

        # Help Menu
        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About", self.about)
        help_menu.addAction(
            "Check for Updates",
            lambda: self.check_for_client_updates_async(manual=True),
        )

        # CENTRAL WIDGET

        # Create the main layout and central widget
        central_widget = QWidget(self)
        self.main_layout = QHBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        # Create the latest balances table view
        self.table_view = QTableView()
        self.table_view.setSortingEnabled(True)
        self.main_layout.addWidget(self.table_view)

        # Create page selector for right panel
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Create a QTabWidget to manage pages
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)  # Tabs at the top

        # Page 1: Balance History
        self.page1 = QWidget()
        page1_layout = QHBoxLayout(self.page1)

        # Create balance history control group
        balance_controls_layout = QGridLayout()

        # Add account name selection
        row = 0
        balance_account_label = QLabel("Select Accounts:")
        balance_controls_layout.addWidget(balance_account_label, row, 0, 1, 2)
        row += 1

        # Add "Select All" checkbox
        select_all_accounts_checkbox = QCheckBox("Select All")
        select_all_accounts_checkbox.setCheckState(Qt.Unchecked)
        balance_controls_layout.addWidget(select_all_accounts_checkbox, row, 0, 1, 2)
        row += 1

        # Add checkable accounts list for plot filtering
        self.account_select_list = QListWidget()
        self.account_select_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        balance_controls_layout.addWidget(self.account_select_list, row, 0, 1, 2)

        # Make the listbox fill all available space
        balance_controls_layout.setRowStretch(row, 10)
        row += 1

        # Connect "Select All" checkbox to toggle function
        def toggle_select_all_accounts(state):
            for index in range(self.account_select_list.count()):
                item = self.account_select_list.item(index)
                item.setCheckState(Qt.Checked if state == Qt.Checked else Qt.Unchecked)

        select_all_accounts_checkbox.stateChanged.connect(toggle_select_all_accounts)

        # Add days of smoothing selection
        balance_smoothing_label = QLabel("Smoothing Days:")
        balance_controls_layout.addWidget(balance_smoothing_label, row, 0, 1, 1)
        self.balance_smoothing_input = QLineEdit("0")
        self.balance_smoothing_input.setPlaceholderText("Enter number of days")
        self.balance_smoothing_input.editingFinished.connect(lambda: self.validate_int(self.balance_smoothing_input, 0))
        balance_controls_layout.addWidget(self.balance_smoothing_input, row, 1, 1, 1)
        row += 1

        # Add years of balance history selection
        balance_years_label = QLabel("Years of History:")
        balance_controls_layout.addWidget(balance_years_label, row, 0, 1, 1)
        self.balance_years_input = QLineEdit("10")
        self.balance_years_input.setPlaceholderText("Enter number of years")
        self.balance_years_input.editingFinished.connect(lambda: self.validate_float(self.balance_years_input, 10))
        balance_controls_layout.addWidget(self.balance_years_input, row, 1, 1, 1)
        row += 1

        # Add Update Balance Plot button
        balance_filter_button = QPushButton("Update Balance Plot")
        balance_filter_button.clicked.connect(self.update_balance_history_button)
        balance_controls_layout.addWidget(balance_filter_button, row, 0, 1, 2)
        row += 1

        # Add a spacer to push the widgets to the top
        bspacer = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        balance_controls_layout.addItem(bspacer, row, 0, 1, 2)

        # Place the QGridLayout in a GroupBox so its max size can be set
        self.balance_controls_group = QGroupBox("Balance History Controls")
        self.balance_controls_group.setLayout(balance_controls_layout)

        # Limit how much the control group can expand laterally
        max_width = int(0.7 * self.balance_controls_group.sizeHint().width())
        self.balance_controls_group.setMaximumWidth(max_width)

        page1_layout.addWidget(self.balance_controls_group)

        # Add balance history chart
        self.balance_canvas = MatplotlibCanvas(self, width=7, height=5)
        balance_toolbar = NavigationToolbar(self.balance_canvas, self)

        balance_chart_layout = QVBoxLayout()
        balance_chart_layout.addWidget(balance_toolbar)
        balance_chart_layout.addWidget(self.balance_canvas)

        balance_chart_group = QGroupBox("Balance History Chart")
        balance_chart_group.setLayout(balance_chart_layout)
        balance_chart_group.adjustSize()

        # Set the layouts
        page1_layout.addWidget(balance_chart_group)
        self.page1.setLayout(page1_layout)
        self.tabs.addTab(self.page1, "Balance History")

        # Page 2: Category Spending
        self.page2 = QWidget()
        page2_layout = QHBoxLayout(self.page2)

        # Create Category Spending control group
        category_controls_layout = QGridLayout()

        # Add category selection
        row = 0
        select_category_label = QLabel("Select Categories:")
        category_controls_layout.addWidget(select_category_label, row, 0, 1, 2)
        row += 1

        # Add "Select All" checkbox
        select_all_category_checkbox = QCheckBox("Select All")
        select_all_category_checkbox.setCheckState(Qt.Unchecked)
        category_controls_layout.addWidget(select_all_category_checkbox, row, 0, 1, 2)
        row += 1

        # Add checkable accounts list for plot filtering
        self.category_select_list = QListWidget()
        self.category_select_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        category_controls_layout.addWidget(self.category_select_list, row, 0, 1, 2)

        # Make the listbox fill all available space
        category_controls_layout.setRowStretch(row, 10)
        row += 1

        # Connect "Select All" checkbox to toggle function
        def toggle_select_all_categories(state):
            for index in range(self.category_select_list.count()):
                item = self.category_select_list.item(index)
                item.setCheckState(Qt.Checked if state == Qt.Checked else Qt.Unchecked)

        select_all_category_checkbox.stateChanged.connect(toggle_select_all_categories)

        # Add days of smoothing selection
        category_smoothing_label = QLabel("Smoothing Months:")
        category_controls_layout.addWidget(category_smoothing_label, row, 0, 1, 1)
        self.category_smoothing_input = QLineEdit("0")
        self.category_smoothing_input.setPlaceholderText("Enter number of days")
        self.category_smoothing_input.editingFinished.connect(
            lambda: self.validate_int(self.category_smoothing_input, 0)
        )
        category_controls_layout.addWidget(self.category_smoothing_input, row, 1, 1, 1)
        row += 1

        # Add years of balance history selection
        category_years_label = QLabel("Years of History:")
        category_controls_layout.addWidget(category_years_label, row, 0, 1, 1)
        self.category_years_input = QLineEdit("10")
        self.category_years_input.setPlaceholderText("Enter number of years")
        self.category_years_input.editingFinished.connect(lambda: self.validate_float(self.category_years_input, 10))
        category_controls_layout.addWidget(self.category_years_input, row, 1, 1, 1)
        row += 1

        # Add Update Balance Plot button
        category_filter_button = QPushButton("Update Category Plot")
        category_filter_button.clicked.connect(self.update_category_spending_button)
        category_controls_layout.addWidget(category_filter_button, row, 0, 1, 2)
        row += 1

        # Add a spacer to push the widgets to the top
        cspacer = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        category_controls_layout.addItem(cspacer, row, 0, 1, 2)

        # Place the QGridLayout in a GroupBox so its max size can be set
        self.category_controls_group = QGroupBox("Category Spending Controls")
        self.category_controls_group.setLayout(category_controls_layout)

        # Limit how much the control group can expand laterally
        max_width = int(0.7 * self.category_controls_group.sizeHint().width())
        self.category_controls_group.setMaximumWidth(max_width)

        page2_layout.addWidget(self.category_controls_group)

        # Add category spending chart
        self.category_canvas = MatplotlibCanvas(self, width=7, height=5)
        category_toolbar = NavigationToolbar(self.category_canvas, self)

        category_chart_layout = QVBoxLayout()
        category_chart_layout.addWidget(category_toolbar)
        category_chart_layout.addWidget(self.category_canvas)

        category_chart_group = QGroupBox("Category Spending Chart")
        category_chart_group.setLayout(category_chart_layout)
        category_chart_group.adjustSize()

        # Set the layouts
        page2_layout.addWidget(category_chart_group)
        self.page2.setLayout(page2_layout)
        self.tabs.addTab(self.page2, "Category Spending")

        # Page 3: Budgets (modular widget)
        self.budget_tab = BudgetTab(session_factory=None, parent=self)
        self.tabs.addTab(self.budget_tab, "Budgets")

        # Add right panel to the main layout
        right_layout.addWidget(self.tabs)
        self.main_layout.addWidget(right_widget)

        # INITIALIZE #########################
        self.initialize_all_elements()

    def exception_hook(self, exc_type, exc_value, exc_traceback):
        """
        Handle uncaught exceptions by displaying an error dialog with traceback.
        """
        # Get screen dimensions
        app = QApplication.instance() or QApplication([])
        screen_geometry = app.primaryScreen().geometry()
        max_width = screen_geometry.width() // 2
        max_height = screen_geometry.height() // 2

        # Create dialog
        dialog = QDialog()
        dialog.setWindowTitle("Unhandled Exception")
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)

        # Create layout
        layout = QVBoxLayout(dialog)
        label = QLabel("An unexpected error occurred. You can review the details below:")
        layout.addWidget(label)

        # Create text edit for exception traceback
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        text_edit = QTextEdit()
        text_edit.setPlainText(tb)
        text_edit.setReadOnly(True)

        # Compute window size
        font_metrics = QFontMetrics(text_edit.font())
        tb_lines = tb.splitlines()
        max_line_width = max(font_metrics.horizontalAdvance(line) for line in tb_lines)
        max_line_height = len(tb_lines) * font_metrics.lineSpacing()
        max_width = min(max_width, max_line_width) + 50
        max_height = min(max_height, max_line_height) + 100

        text_edit.document().setTextWidth(max_width)

        # Add "Close" button
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)

        # Add widgets to layout
        layout.addWidget(text_edit)
        layout.addWidget(close_button)

        # Set layout and display
        dialog.setLayout(layout)
        dialog.resize(max_width, max_height)
        dialog.exec()

    def initialize_all_elements(self):
        # Make sure the config file exists and load into memory
        try:
            self.Session = initialize_db(self)
        except RuntimeError as e:
            QMessageBox.critical(self, "Database Required", str(e))
            sys.exit(0)

        # Attach Session to budget tab after DB initialization
        self.budget_tab.set_session_factory(self.Session)
        self.artifact_service = ArtifactService(self.Session)
        self.dashboard_service = DashboardQueryService(self.Session)
        self.review_service = TransactionReviewService(self.Session)

        # Initialize the plugin manager
        self.plugin_manager = PluginManager()
        self.plugin_manager.load_plugins()

        pending_archives = StatementImportController(
            self.Session,
            self.plugin_manager,
            parent=self,
        ).find_pending_archives()
        if pending_archives:
            logger.warning("Found {} committed statement archive(s) awaiting recovery", len(pending_archives))
            QMessageBox.warning(
                self,
                "Statement Archive Recovery Needed",
                (
                    f"{len(pending_archives)} committed statement file(s) are still in the import folder. "
                    "Run Import All Statements to finish archiving them safely."
                ),
            )

        # Update all tables, checklists, and graphs
        self.update_main_gui()

        # A documented, optional background check runs only after the event loop
        # starts, so networking can never delay construction or first paint.
        self.schedule_automatic_update_check()

    def schedule_automatic_update_check(self):
        if settings.automatic_update_checks:
            QTimer.singleShot(
                AUTOMATIC_UPDATE_DELAY_MS,
                self.check_for_client_updates_async,
            )

    def check_for_client_updates_async(self, manual: bool = False):
        if getattr(self, "client_update_thread", None) and self.client_update_thread.isRunning():
            return
        self.client_update_thread = ClientUpdateThread()
        self.client_update_thread.update_available.connect(
            lambda success, installer, message: self.handle_client_update(
                success,
                installer,
                message,
                manual=manual,
            )
        )
        self.client_update_thread.start()

    def handle_client_update(self, success: bool, latest_installer, message: str, *, manual: bool = False):
        if success:
            logger.info(message)
            if latest_installer:
                install_client(latest_installer, self)
            elif manual:
                QMessageBox.information(self, "Client Up to Date", "You are already using the latest version.")
        else:
            logger.error(message)
            if manual:
                QMessageBox.critical(self, "Update Check Failed", message)

        # Check for plugin update after client check is done
        self.check_for_plugin_updates_async()

    def check_for_plugin_updates_async(self):
        self.plugin_update_thread = PluginUpdateThread(
            self.plugin_manager,
        )
        self.plugin_update_thread.update_available.connect(self.handle_plugin_update_available)
        self.plugin_update_thread.update_complete.connect(self.handle_plugin_update_complete)
        self.plugin_update_thread.start()

    def handle_plugin_update_available(self, local_plugins: list, remote_release):
        server_plugins = remote_release.legacy_metadata()
        dialog = PluginSyncDialog(local_plugins, server_plugins, parent=self)
        if dialog.exec() == QDialog.Accepted:
            start_plugin_sync(
                self,
                local_plugins,
                remote_release,
                self.plugin_manager,
            )
        else:
            logger.info("User declined to sync plugins")

    def handle_plugin_update_complete(self, success: bool, message: str):
        if success:
            logger.info(message)
        else:
            logger.error(message)

    # MENUBAR FUNCTIONS
    def about(self):
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setTextFormat(Qt.RichText)
        msg_box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        msg_box.setText(
            f"<b>ParseTrail v{__version__}</b><br>"
            f"(c) {__year__} ParseTrail contributors<br>"
            f"Original author: {__developer__}<br>"
            f"Build: {build_provenance_label()}<br>"
            f'<a href="{__website__}">Website</a> | '
            f'<a href="{__repo__}">GitHub</a>'
        )
        msg_box.setWindowTitle("About")
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

    def open_db(self):
        open_file_in_os(settings.db_path)

    def preferences(self):
        dialog = PreferencesDialog()
        if dialog.exec() == QDialog.Accepted:
            try:
                self.Session = initialize_db()
                self.budget_tab.set_session_factory(self.Session)
                self.artifact_service = ArtifactService(self.Session)
                self.dashboard_service = DashboardQueryService(self.Session)
                self.review_service = TransactionReviewService(self.Session)
                self.update_main_gui()
            except RuntimeError as e:
                QMessageBox.warning(self, "Database Required", str(e))

    def export_init_accounts(self):
        reply = QMessageBox.question(
            self,
            "Export Accounts Config?",
            (
                "This will store the Accounts list and any associated Account Numbers"
                f" from <pre>{settings.db_path}</pre> so any new databases use the same settings."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            result = self.artifact_service.export_accounts(settings.accounts_json)
        except ArtifactServiceError:
            logger.exception("Failed to export account configuration")
            QMessageBox.critical(self, "Export Failed", "Failed to export account configuration. See log for details.")
            return
        QMessageBox.information(
            self,
            "Configuration Saved",
            (f"Exported {result.account_count} account(s) and {result.account_number_count} account number(s)."),
        )

    def manage_plugins(self):
        dialog = PluginManagerDialog(self.plugin_manager)
        if dialog.exec() == QDialog.Accepted:
            return

    def parse_test(self):
        dialog = ParseTestDialog(self.Session, self.plugin_manager)
        if dialog.exec() == QDialog.Accepted:
            return

    def edit_accounts(self):
        dialog = EditAccountsDialog(self.Session)
        dialog.exec()

        # Update all GUI elements
        self.update_main_gui()

    def appreciation_calc(self):
        dialog = AppreciationDialog()
        if dialog.exec() == QDialog.Accepted:
            pass

    def insert_transaction(self):
        dialog = InsertTransactionDialog(self.Session)
        if dialog.exec() == QDialog.Accepted:
            self.update_main_gui()

    def recurring_transactions(self):
        dialog = RecurringTransactionsDialog(self.Session)
        if dialog.exec() == QDialog.Accepted:
            pass

    def import_all_statements(self):
        # Import everything
        try:
            processor = StatementImportController(self.Session, self.plugin_manager, parent=self)
            processor.import_all()
        finally:
            # Categorize new transactions and update all GUI elements
            self._categorize_with_missing_category_prompt(
                model_path=settings.model_path,
                uncategorized=True,
            )
            self.update_main_gui()

    def import_one_statement(self):
        # Show file selection dialog
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        file_filter = "Supported Files (*.csv *.pdf *.xlsx);;All Files (*)"
        fpath, _ = QFileDialog.getOpenFileName(
            None,
            "Select a File",
            str(settings.download_dir),
            file_filter,
            options=options,
        )

        # Prevent weird things from happening
        if not fpath:
            return
        fpath = Path(fpath).resolve()
        if fpath.parents[0] == settings.success_dir:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setText("Cannot import statements from the SUCCESS folder.")
            msg_box.setWindowTitle("Protected Folder")
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.exec()
            return

        source_action = choose_source_file_action(self, fpath)
        if source_action is None:
            return

        # Import statement
        processor = StatementImportController(self.Session, self.plugin_manager, parent=self)
        try:
            outcome = processor.import_one(fpath, source_action=source_action)
        except ParseWarningsRejectedError:
            QMessageBox.information(self, "Import Canceled", "The statement was not imported.")
            return
        except ParseError as exc:
            logger.warning("Statement parse failed with {}", exc.code)
            presentation = present_parse_error(exc)
            QMessageBox.critical(self, presentation.title, presentation.message)
            return
        except ArchivePendingError as exc:
            logger.exception("Statement archive action failed after import commit")
            QMessageBox.warning(self, "Archive Recovery Needed", str(exc))
            return
        except Exception:
            logger.exception("Unexpected one-off statement import failure")
            QMessageBox.critical(
                self,
                "Statement Not Imported",
                "The statement could not be imported. Its source remains in place; see the application log for details.",
            )
            return
        if outcome == "success":
            QMessageBox.information(self, "Import Complete", "The statement was imported successfully.")
        elif outcome == "recovered":
            QMessageBox.information(
                self,
                "Archive Recovered",
                "The statement data was already committed; its managed archive has now been recovered.",
            )
        else:
            QMessageBox.information(self, "Duplicate Statement", "This statement was already imported.")

        # Categorize new transactions and update all GUI elements
        self._categorize_with_missing_category_prompt(
            model_path=settings.model_path,
            uncategorized=True,
        )
        self.update_main_gui()

    def _categorize_with_missing_category_prompt(
        self,
        model_path: Path,
        unverified: bool = True,
        uncategorized: bool = False,
    ) -> None:
        try:
            result = self.review_service.auto_categorize(
                model_path,
                missing_category_decision=self._prompt_add_missing_categories,
                unverified=unverified,
                uncategorized=uncategorized,
            )
            if not result.completed:
                QMessageBox.information(
                    self,
                    "Auto-categorization Skipped",
                    "Missing model categories were not added.",
                )
            elif result.added_categories:
                QMessageBox.information(
                    self,
                    "Categories Added",
                    (
                        "Missing categories were added with Type set to 'Expense'.\n\n"
                        "Please update the type as needed in the Category Manager."
                    ),
                )
        except TransactionReviewError:
            logger.exception("Auto-categorization failed after statement import")
            QMessageBox.critical(self, "Auto-categorization Failed", "See the log for details.")

    def _prompt_add_missing_categories(self, missing: list[str]) -> bool:
        missing_text = ", ".join(missing)
        reply = QMessageBox.question(
            self,
            "Add Missing Categories?",
            (
                "The trained model expects categories that are missing from this database:\n\n"
                f"{missing_text}\n\n"
                "Would you like to add these categories now and continue auto-categorizing?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        return reply == QMessageBox.Yes

    def statement_matrix(self):
        dialog = CompletenessDialog(self.Session)
        if dialog.exec() == QDialog.Accepted:
            pass

    def statement_discrepancies(self):
        try:
            discrepancy_data = self.dashboard_service.statement_discrepancy_data()
        except DashboardServiceError:
            logger.exception("Failed to inspect statement discrepancies")
            QMessageBox.critical(self, "Error", "Failed to inspect statement discrepancies. See log for details.")
            return

        # Prompt the user whether they want to correct the issue
        count = 0
        for latest in discrepancy_data.balances:
            days = (discrepancy_data.latest_statement_date - latest.date).days
            if days < 120 or latest.balance == 0:
                continue
            count += 1
            balance_dialog = BalanceCheckDialog(latest.account_name, latest.balance)
            if balance_dialog.exec() != QDialog.Accepted:
                continue

            insert_dialog = InsertTransactionDialog(
                self.Session,
                account_name=latest.account_name,
                close_account=True,
            )
            if insert_dialog.exec() == QDialog.Accepted:
                self.update_main_gui()

        # Completed dialog
        QMessageBox.information(
            self,
            "Search Complete",
            ("No additional discrepancies found." if count > 0 else "No discrepancies found."),
        )

    def plot_balances(self):
        try:
            data, debt_columns = self.dashboard_service.balance_history()
            plot.show_balance_history(data, debt_columns)
        except DashboardServiceError:
            logger.exception("Failed to open balance history plot")
            QMessageBox.critical(self, "Plot Failed", "Failed to load balance history. See log for details.")

    def plot_categories(self):
        try:
            plot.show_category_spending(self.dashboard_service.category_spending())
        except DashboardServiceError:
            logger.exception("Failed to open category spending plot")
            QMessageBox.critical(self, "Plot Failed", "Failed to load category spending. See log for details.")

    def report_all_time(self):
        timestamp = datetime.now().strftime(r"%Y%m%d%H%M%S")
        dpath = settings.report_dir / f"{timestamp}_Report_AllTime.xlsx"
        self._generate_report(dpath)

    def report_1year(self):
        timestamp = datetime.now().strftime(r"%Y%m%d%H%M%S")
        dpath = settings.report_dir / f"{timestamp}_Report_OneYear.xlsx"
        self._generate_report(dpath, months=12)

    def report_3months(self):
        timestamp = datetime.now().strftime(r"%Y%m%d%H%M%S")
        dpath = settings.report_dir / f"{timestamp}_Report_ThreeMonths.xlsx"
        self._generate_report(dpath, months=3)

    def _generate_report(self, destination: Path, *, months: int | None = None) -> None:
        try:
            report_path = self.artifact_service.generate_report(destination, months=months)
            open_file_in_os(report_path)
        except ArtifactServiceError:
            logger.exception("Failed to generate transaction report")
            QMessageBox.critical(self, "Report Failed", "Failed to generate report. See log for details.")

    def open_category_manager(self):
        dialog = CategoryManagerDialog(self.Session)
        if dialog.exec():
            self.update_main_gui()

    def open_transaction_review(self):
        if self.transaction_review_window is None:
            self.transaction_review_window = TransactionReviewWindow(self.Session, parent=self)

            self.transaction_review_window.setAttribute(Qt.WA_DeleteOnClose)
            self.transaction_review_window.destroyed.connect(self._on_transaction_review_closed)
            self.transaction_review_window.data_changed.connect(self._handle_transactions_data_changed)

        # Show and bring to front
        self.transaction_review_window.show()
        self.transaction_review_window.raise_()
        self.transaction_review_window.activateWindow()

    def _handle_transactions_data_changed(self):
        """Behavior when user clicks Save Changes in TransactionReviewWindow"""
        pass

    def _on_transaction_review_closed(self, _obj=None):
        self.transaction_review_window = None
        self.update_main_gui()

    def train_pipeline_test(self):
        try:
            data, columns = self.dashboard_service.training_set()
        except DashboardServiceError:
            logger.exception("Failed to load model-training data")
            QMessageBox.critical(self, "Error", "Failed to load model-training data. See log for details.")
            return
        if len(data) == 0:
            QMessageBox.information(
                self,
                "No Verified Categories",
                "There are no verified transactions to train a model.",
            )
            return
        df = pd.DataFrame(data, columns=columns)

        # Train and test a pipeline
        learn.train_pipeline_test(df, amount=False)

    def train_pipeline_save(self):
        # Prompt user for new save location
        options = QFileDialog.Options()
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Save Location",
            str(settings.model_path),
            "MDL Files (*.mdl);;All Files (*);;",
            options=options,
        )
        if save_path == "":
            return
        model_path = Path(save_path).resolve()

        # Retrieve verified transactions
        try:
            data, columns = self.dashboard_service.training_set()
        except DashboardServiceError:
            logger.exception("Failed to load model-training data")
            QMessageBox.critical(self, "Error", "Failed to load model-training data. See log for details.")
            return
        if len(data) == 0:
            QMessageBox.information(
                self,
                "No Verified Categories",
                "There are no verified transactions to train a model.",
            )
            return
        df = pd.DataFrame(data, columns=columns)

        # Train and save pipeline
        learn.train_pipeline_save(df, model_path, amount=False)

        QMessageBox.information(self, "Pipeline Saved", "Trained pipeline has been saved successfully.")

        # Save new pipeline path to config
        settings.model_path = model_path
        save_settings(settings)

    # CENTRAL WIDGET FUNCTIONS

    def update_balance_history_button(self):
        self.update_balance_history_chart()

    def update_category_spending_button(self):
        self.update_category_spending_chart()

    def update_main_gui(self):
        """Update all tables, checklists, and charts in the main GUI window"""
        self.setWindowTitle(f"ParseTrail v{__version__} - {settings.db_path}")
        try:
            self.update_balances_table()
        except Exception:
            logger.exception("Failed to update balances table")
            QMessageBox.critical(
                self,
                "Critical",
                "Failed to update balances table. See the application log for details.",
            )

        try:
            self.update_accounts_checklist()
            self.update_balance_history_chart()
        except Exception:
            logger.exception("Failed to update balance history chart")
            QMessageBox.critical(
                self,
                "Critical",
                "Failed to update balance history chart. See the application log for details.",
            )

        try:
            self.update_category_checklist()
            self.update_category_spending_chart()
        except Exception:
            logger.exception("Failed to update category spending chart")
            QMessageBox.critical(
                self,
                "Critical",
                "Failed to update category spending chart. See the application log for details.",
            )

    def update_balances_table(self):
        # Fetch data for the table
        balances = self.dashboard_service.latest_balances()
        df_balances = pd.DataFrame(
            [(row.account_name, row.balance, row.date) for row in balances],
            columns=["AccountName", "LatestBalance", "LatestDate"],
        )

        # Update the table contents
        table_model = PandasModel(df_balances)
        self.table_view.setModel(table_model)
        self.table_view.resizeColumnsToContents()

        # Set default sorting
        self.table_view.sortByColumn(1, Qt.DescendingOrder)

        # Fix the table width
        total_width = sum(self.table_view.columnWidth(i) for i in range(self.table_view.model().columnCount()))
        vertical_scrollbar_width = self.table_view.verticalScrollBar().sizeHint().width()
        table_width = total_width + vertical_scrollbar_width + 30
        self.table_view.setFixedWidth(table_width)

    def update_accounts_checklist(self):
        self.update_generic_checklist(
            list_widget=self.account_select_list,
            initial_checked=["Net Worth", "Total Assets", "Total Debts"],
            names=self.dashboard_service.account_names(),
        )

    def update_category_checklist(self):
        self.update_generic_checklist(
            list_widget=self.category_select_list,
            initial_checked=[],
            names=self.dashboard_service.category_names(),
        )

    def update_generic_checklist(
        self,
        list_widget: QListWidget,
        initial_checked: list[str],
        names: list[str],
    ):
        if list_widget.count() == 0:
            # App just started, initialize checklist
            self.initialize_checklist(list_widget, initial_checked, names)
        else:
            # Update based on previous checked/unchecked state
            self.update_checklist(list_widget, initial_checked + names)

    def initialize_checklist(self, list_widget: QListWidget, checked: list[str], unchecked: list[str]):
        list_widget.clear()
        for name, state in [(name, Qt.Checked) for name in checked] + [(name, Qt.Unchecked) for name in unchecked]:
            item = QListWidgetItem(name)
            item.setCheckState(state)
            list_widget.addItem(item)

    def update_checklist(self, list_widget: QListWidget, names: list[str]):
        checked, unchecked = self.get_checked_items(list_widget)

        list_widget.clear()
        for name in names:
            item = QListWidgetItem(name)
            # Preserve checked/unchecked state; default new items to checked
            item.setCheckState(Qt.Checked if name in checked else Qt.Unchecked if name in unchecked else Qt.Checked)
            list_widget.addItem(item)

    def get_checked_items(self, list_widget: QListWidget) -> tuple[list[str], list[str]]:
        checked, unchecked = [], []
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            (checked if item.checkState() == Qt.Checked else unchecked).append(item.text())
        return checked, unchecked

    def validate_float(self, line_edit: QLineEdit, fallback: float) -> float:
        try:
            return float(line_edit.text())
        except ValueError:
            line_edit.setText(str(fallback))
            return fallback

    def validate_int(self, line_edit: QLineEdit, fallback: int) -> int:
        try:
            # Attempt to parse the input as an integer
            value = int(float(line_edit.text()))
            line_edit.setText(str(value))
            return value
        except ValueError:
            # On failure, reset to fallback
            line_edit.setText(str(fallback))
            return fallback

    def update_balance_history_chart(self):
        QApplication.processEvents()
        # Get filter prefs
        smoothing_days = self.validate_int(self.balance_smoothing_input, 0)
        limit_years = self.validate_float(self.balance_years_input, 10)
        selected_accounts, _ = self.get_checked_items(self.account_select_list)

        # Plot all balances on the same chart
        df, debt_cols = self.dashboard_service.balance_history()

        # Limit the data to the specified year range
        now = datetime.now()
        cutoff_date = now - timedelta(days=limit_years * 365)
        df = df[df.index >= cutoff_date]

        # Apply smoothing (rolling average)
        if smoothing_days > 1:
            df = df.rolling(window=smoothing_days, min_periods=1).mean()

        # Plot selected account data
        filtered_accounts = [acct for acct in df.columns.values if acct in selected_accounts]
        self.balance_canvas.plot(
            df,
            filtered_accounts,
            left=cutoff_date,
            right=now,
            title="Balance History",
            xlabel="Date",
            ylabel="Balance",
            dashed=debt_cols,
        )

    def update_category_spending_chart(self):
        QApplication.processEvents()
        # Get filter prefs
        smoothing_months = self.validate_int(self.category_smoothing_input, 0)
        limit_years = self.validate_float(self.category_years_input, 10)
        selected_cats, _ = self.get_checked_items(self.category_select_list)

        # Get the category spending data by month
        df = self.dashboard_service.category_spending()

        # Limit the data to the specified year range
        now = datetime.now()
        cutoff_date = now - timedelta(days=(1.2 * limit_years * 365))
        df = df[df.index >= cutoff_date]

        # Apply smoothing (rolling average)
        if smoothing_months > 1:
            df = df.rolling(window=smoothing_months, min_periods=1).mean()

        # Plot the selected categories
        filtered_cats = [cat for cat in df.columns.values if cat in selected_cats]
        self.category_canvas.plot(
            df,
            filtered_cats,
            left=cutoff_date,
            right=now,
            title="Monthly Spending by Category",
            xlabel="Date",
            ylabel="Amount",
        )

    def send_statement(self):
        dialog = StatementSubmissionDialog()
        if dialog.exec():
            pass

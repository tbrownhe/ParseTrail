import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import pandas as pd
from loguru import logger
from matplotlib import rcParams
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from parsetrail.core import config, learn, plot, query, reports
from parsetrail.core.categorize import transactions as categorize_transactions
from parsetrail.core.client import (
    ClientUpdateThread,
    check_for_client_updates,
    install_client,
)
from parsetrail.core.initialize import initialize_db
from parsetrail.core.plugins import PluginManager, PluginUpdateThread, sync_plugins
from parsetrail.core.settings import save_settings, settings
from parsetrail.core.statements import StatementProcessor
from parsetrail.core.utils import open_file_in_os
from parsetrail.gui.accounts import (
    AppreciationDialog,
    BalanceCheckDialog,
    EditAccountsDialog,
)
from parsetrail.gui.category import CategoryManagerDialog
from parsetrail.gui.plugins import (
    ParseTestDialog,
    PluginManagerDialog,
    PluginSyncDialog,
)
from parsetrail.gui.budget_view import BudgetTab
from parsetrail.gui.preferences import PreferencesDialog
from parsetrail.gui.send import StatementSubmissionDialog
from parsetrail.gui.statements import CompletenessDialog
from parsetrail.gui.transactions import (
    InsertTransactionDialog,
    RecurringTransactionsDialog,
)
from parsetrail.gui.verification import TransactionReviewWindow
from parsetrail.version import __developer__, __version__, __year__
from PyQt5.QtCore import QAbstractTableModel, Qt
from PyQt5.QtGui import QColor, QFontMetrics
from PyQt5.QtWidgets import (
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
from sqlalchemy.orm import Session


class MatplotlibCanvas(FigureCanvas):
    def __init__(self, parent=None, width=3, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi, constrained_layout=True)
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)

        # Set higher resolution for toolbar exports
        rcParams["savefig.dpi"] = 300

        # Connect the resize event
        self.resize_event_id = self.fig.canvas.mpl_connect("resize_event", self.on_resize)

        # Connect the legend pick event
        self.fig.canvas.mpl_connect("pick_event", self.on_legend_click)

        # Connect mouse events for moving the legend
        self.fig.canvas.mpl_connect("button_press_event", self.on_mouse_press)
        self.fig.canvas.mpl_connect("button_release_event", self.on_mouse_release)
        self.fig.canvas.mpl_connect("motion_notify_event", self.on_mouse_move)
        self.legend_dragging = False

    def on_resize(self, event):
        # Get the canvas size in pixels
        width, height = self.get_width_height()

        # Calculate maximum ticks based on canvas size and ticks per pixel
        max_x_ticks = int(width / 80)
        max_y_ticks = int(height / 50)

        # Update tick locators dynamically
        locator = mdates.AutoDateLocator(maxticks=max_x_ticks)
        formatter = mdates.ConciseDateFormatter(locator)
        self.axes.xaxis.set_major_locator(locator)
        self.axes.xaxis.set_major_formatter(formatter)
        self.axes.yaxis.set_major_locator(MaxNLocator(nbins=max_y_ticks))

        # Apply custom Y-axis formatting for accounting format
        self.axes.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"))

        # Redraw the canvas to apply changes
        self.draw()

    def plot(
        self,
        df: pd.DataFrame,
        selected_accounts: list[str],
        left=None,
        right=None,
        title="",
        xlabel="",
        ylabel="",
        dashed=[],
    ):
        self.axes.clear()

        # Handle empty data
        if df.empty or not selected_accounts:
            self.axes.text(
                0.5,
                0.5,
                "No data selected",
                transform=self.axes.transAxes,
                ha="center",
            )
            self.draw()
            return

        # Plot the lines
        self.lines = {}
        for account_name in selected_accounts:
            linestyle = "dashed" if account_name in dashed else "solid"
            (line,) = self.axes.plot(
                df.index,
                df[account_name],
                label=account_name,
                picker=True,
                linestyle=linestyle,
            )
            self.lines[account_name] = line

        # Handle options
        left = left if left else df.index.min()
        right = right if right else df.index.max()

        # Customize appearance
        self.axes.set_xlim(left=left, right=right)
        self.axes.axhline(0, color="black", linewidth=1.5, linestyle="-")
        self.axes.axvline(right, color="red", linewidth=1.5, linestyle="-")
        self.axes.set_title(title)
        self.axes.set_xlabel(xlabel)
        self.axes.set_ylabel(ylabel)
        self.axes.grid(True)

        self.axes.fmt_xdata = lambda x: mdates.num2date(x).strftime(r"%Y-%m-%d")

        # Add legend with picking enabled
        self.legend = self.axes.legend(loc="upper left", fontsize="x-small")
        hitbox = 5.0
        for legend_entry in self.legend.get_lines():
            legend_entry.set_picker(hitbox)

        # Set consistent tick format. Includes self.draw().
        self.on_resize(None)

    def on_legend_click(self, event):
        # Get the corresponding label
        legend_entry = event.artist
        label = legend_entry.get_label()

        # Find the line corresponding to the label
        line = self.lines.get(label)

        if line is None:
            logger.warning(f"No line found for label {label}")
            return

        if line:
            # Toggle the line's visibility
            visible = not line.get_visible()
            line.set_visible(visible)

            # Toggle legend entry alpha (fade when hidden)
            legend_entry.set_alpha(1.0 if visible else 0.2)

            # Redraw the canvas
            self.draw()

    def on_mouse_press(self, event):
        if self.legend and self.legend.contains(event)[0]:
            self.legend_dragging = True

    def on_mouse_release(self, event):
        if self.legend_dragging:
            self.legend_dragging = False

    def on_mouse_move(self, event):
        if self.legend_dragging and event.inaxes:
            self.legend.set_bbox_to_anchor((event.xdata, event.ydata), transform=self.axes.transData)
            self.draw()


class PandasModel(QAbstractTableModel):
    def __init__(self, data):
        super().__init__()
        self._data = data

    def rowCount(self, parent=None):
        return self._data.shape[0]

    def columnCount(self, parent=None):
        return self._data.shape[1]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        value = self._data.iloc[index.row(), index.column()]

        if role == Qt.DisplayRole:
            if index.column() == 1:
                try:
                    return f"{float(value):,.2f}"
                except (TypeError, ValueError):
                    return str(value)
            return str(value)
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter  # Center-align text in cells
        elif role == Qt.BackgroundRole:
            # Apply background color based on positive/negative value
            try:
                numeric_value = float(value)
                if numeric_value > 0:
                    return QColor(140, 225, 140)  # Light green
                elif numeric_value < 0:
                    return QColor(225, 160, 160)  # Light red
            except ValueError:
                return None
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return self._data.columns[section]
            if orientation == Qt.Vertical:
                return self._data.index[section]
        return None

    def sort(self, column, order):
        """
        Sort the model by the given column.
        :param column: The column index to sort by.
        :param order: Qt.AscendingOrder or Qt.DescendingOrder
        """
        column_name = self._data.columns[column]
        ascending = order == Qt.AscendingOrder
        self.layoutAboutToBeChanged.emit()
        self._data.sort_values(by=column_name, ascending=ascending, inplace=True)
        self._data.reset_index(drop=True, inplace=True)
        self.layoutChanged.emit()


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
            lambda: check_for_client_updates(parent=self),
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
        dialog.exec_()

    def initialize_all_elements(self):
        # Make sure the config file exists and load into memory
        try:
            self.Session = initialize_db(self)
        except RuntimeError as e:
            QMessageBox.critical(self, "Database Required", str(e))
            sys.exit(0)

        # Attach Session to budget tab after DB initialization
        self.budget_tab.set_session_factory(self.Session)

        # Initialize the plugin manager
        self.plugin_manager = PluginManager()
        self.plugin_manager.load_plugins()

        # Update all tables, checklists, and graphs
        with self.Session() as session:
            self.update_main_gui(session)

        # Check for new versions of client and plugins
        self.check_for_client_updates_async()

    def check_for_client_updates_async(self):
        self.client_update_thread = ClientUpdateThread()
        self.client_update_thread.update_available.connect(self.handle_client_update)
        self.client_update_thread.start()

    def handle_client_update(self, success: bool, latest_installer: dict, message: str):
        if success:
            logger.info(message)
            if latest_installer:
                install_client(latest_installer, self)
        else:
            logger.error(message)

        # Check for plugin update after client check is done
        self.check_for_plugin_updates_async()

    def check_for_plugin_updates_async(self):
        self.plugin_update_thread = PluginUpdateThread(
            self.plugin_manager,
        )
        self.plugin_update_thread.update_available.connect(self.handle_plugin_update_available)
        self.plugin_update_thread.update_complete.connect(self.handle_plugin_update_complete)
        self.plugin_update_thread.start()

    def handle_plugin_update_available(self, local_plugins: list, server_plugins: list):
        dialog = PluginSyncDialog(local_plugins, server_plugins, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            sync_plugins(local_plugins, server_plugins, progress=True, parent=self)
            self.plugin_manager.load_plugins()
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
        msg_box.setText(f"ParseTrail v{__version__}\n© {__year__} {__developer__}")
        msg_box.setWindowTitle("About")
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec_()

    def open_db(self):
        open_file_in_os(settings.db_path)

    def preferences(self):
        dialog = PreferencesDialog()
        if dialog.exec_() == QDialog.Accepted:
            try:
                self.Session = initialize_db()
                with self.Session() as session:
                    self.update_main_gui(session)
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
        with self.Session() as session:
            config.export_init_accounts(session)

    def manage_plugins(self):
        dialog = PluginManagerDialog(self.plugin_manager)
        if dialog.exec_() == QDialog.Accepted:
            return

    def parse_test(self):
        dialog = ParseTestDialog(self.Session, self.plugin_manager)
        if dialog.exec_() == QDialog.Accepted:
            return

    def edit_accounts(self):
        dialog = EditAccountsDialog(self.Session)
        dialog.exec_()

        # Update all GUI elements
        with self.Session() as session:
            self.update_main_gui(session)

    def appreciation_calc(self):
        dialog = AppreciationDialog()
        if dialog.exec_() == QDialog.Accepted:
            pass

    def insert_transaction(self):
        dialog = InsertTransactionDialog(self.Session)
        if dialog.exec_() == QDialog.Accepted:
            # Update all GUI elements
            with self.Session() as session:
                self.update_main_gui(session)

    def recurring_transactions(self):
        dialog = RecurringTransactionsDialog(self.Session)
        if dialog.exec_() == QDialog.Accepted:
            pass

    def import_all_statements(self):
        # Import everything
        try:
            processor = StatementProcessor(self.Session, self.plugin_manager)
            processor.import_all(parent=self)
        finally:
            # Categorize new transactions and update all GUI elements
            with self.Session() as session:
                categorize_transactions(session, settings.model_path, uncategorized=True)
                self.update_main_gui(session)

    def import_one_statement(self):
        # Show file selection dialog
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        file_filter = "Supported Files (*.csv *.pdf *.xlsx);;All Files (*)"
        fpath, _ = QFileDialog.getOpenFileName(
            None,
            "Select a File",
            str(settings.import_dir),
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
            msg_box.exec_()
            return

        # Import statement
        processor = StatementProcessor(self.Session, self.plugin_manager)
        processor.import_one(fpath)

        # Categorize new transactions and update all GUI elements
        with self.Session() as session:
            categorize_transactions(session, settings.model_path, uncategorized=True)
            self.update_main_gui(session)

    def statement_matrix(self):
        dialog = CompletenessDialog(self.Session)
        if dialog.exec_() == QDialog.Accepted:
            pass

    def statement_discrepancies(self):
        # Fetch data for the table
        with self.Session() as session:
            data = query.latest_balances(session)
            max_date = query.statement_max_date(session)

        # Prompt the user whether they want to correct the issue
        count = 0
        for account_name, balance, date in data:
            days = (max_date - datetime.strptime(date, r"%Y-%m-%d")).days
            if days < 120 or balance == 0.0:
                continue
            count += 1
            balance_dialog = BalanceCheckDialog(account_name, balance)
            if balance_dialog.exec_() != QDialog.Accepted:
                continue

            insert_dialog = InsertTransactionDialog(self.Session, account_name=account_name, close_account=True)
            if insert_dialog.exec_() == QDialog.Accepted:
                # Update all GUI elements
                with self.Session() as session:
                    self.update_main_gui(session)

        # Completed dialog
        QMessageBox.information(
            self,
            "Search Complete",
            ("No additional discrepancies found." if count > 0 else "No discrepancies found."),
        )

    def plot_balances(self):
        with self.Session() as session:
            plot.plot_balance_history(session)

    def plot_categories(self):
        with self.Session() as session:
            plot.plot_category_spending(session)

    def report_all_time(self):
        timestamp = datetime.now().strftime(r"%Y%m%d%H%M%S")
        dpath = settings.report_dir / f"{timestamp}_Report_AllTime.xlsx"
        with self.Session() as session:
            reports.report(session, dpath)

    def report_1year(self):
        timestamp = datetime.now().strftime(r"%Y%m%d%H%M%S")
        dpath = settings.report_dir / f"{timestamp}_Report_OneYear.xlsx"
        with self.Session() as session:
            reports.report(session, dpath, months=12)

    def report_3months(self):
        timestamp = datetime.now().strftime(r"%Y%m%d%H%M%S")
        dpath = settings.report_dir / f"{timestamp}_Report_ThreeMonths.xlsx"
        with self.Session() as session:
            reports.report(session, dpath, months=3)

    def open_category_manager(self):
        dialog = CategoryManagerDialog(self.Session)
        if dialog.exec_():
            with self.Session() as session:
                self.update_main_gui(session)

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
        # with self.Session() as session:
        #    self.update_main_gui(session)

    def _on_transaction_review_closed(self, _obj=None):
        self.transaction_review_window = None
        with self.Session() as session:
            self.update_main_gui(session)

    def train_pipeline_test(self):
        with self.Session() as session:
            data, columns = query.training_set(session, verified=True)
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
        with self.Session() as session:
            data, columns = query.training_set(session, verified=True)
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
        with self.Session() as session:
            self.update_balance_history_chart(session)

    def update_category_spending_button(self):
        with self.Session() as session:
            self.update_category_spending_chart(session)

    def update_main_gui(self, session: Session):
        """Update all tables, checklists, and charts in the main GUI window"""
        self.setWindowTitle(f"ParseTrail v{__version__} - {settings.db_path}")
        try:
            self.update_balances_table(session)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Critical",
                f"Failed to update balances table: {e}",
            )

        try:
            self.update_accounts_checklist(session)
            self.update_balance_history_chart(session)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Critical",
                f"Failed to update balance history chart: {e}",
            )

        try:
            self.update_category_checklist(session)
            self.update_category_spending_chart(session)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Critical",
                f"Failed to update category spending chart: {e}",
            )

    def update_balances_table(self, session: Session):
        # Fetch data for the table
        data = query.latest_balances(session)
        df_balances = pd.DataFrame(data, columns=["AccountName", "LatestBalance", "LatestDate"])

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

    def update_accounts_checklist(self, session: Session):
        self.update_generic_checklist(
            session=session,
            list_widget=self.account_select_list,
            initial_checked=["Net Worth", "Total Assets", "Total Debts"],
            query_func=query.account_names,
        )

    def update_category_checklist(self, session: Session):
        self.update_generic_checklist(
            session=session,
            list_widget=self.category_select_list,
            initial_checked=[],
            query_func=query.distinct_categories,
        )

    def update_generic_checklist(
        self,
        session: Session,
        list_widget: QListWidget,
        initial_checked: list[str],
        query_func,
    ):
        items = query_func(session)

        if list_widget.count() == 0:
            # App just started, initialize checklist
            self.initialize_checklist(list_widget, initial_checked, items)
        else:
            # Update based on previous checked/unchecked state
            self.update_checklist(list_widget, initial_checked + items)

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

    def update_balance_history_chart(self, session: Session):
        QApplication.processEvents()
        # Get filter prefs
        smoothing_days = self.validate_int(self.balance_smoothing_input, 0)
        limit_years = self.validate_float(self.balance_years_input, 10)
        selected_accounts, _ = self.get_checked_items(self.account_select_list)

        # Plot all balances on the same chart
        df, debt_cols = plot.get_balance_data(session)

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

    def update_category_spending_chart(self, session: Session):
        QApplication.processEvents()
        # Get filter prefs
        smoothing_months = self.validate_int(self.category_smoothing_input, 0)
        limit_years = self.validate_float(self.category_years_input, 10)
        selected_cats, _ = self.get_checked_items(self.category_select_list)

        # Get the category spending data by month
        df = plot.get_category_data(session)

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
        if dialog.exec_():
            pass

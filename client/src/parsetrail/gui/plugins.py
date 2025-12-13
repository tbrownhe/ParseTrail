from pathlib import Path

import pandas as pd
from loguru import logger
from parsetrail.core.parse import ParseInput, parse_any
from parsetrail.core.plugins import (
    PluginManager,
    compare_plugins,
    get_plugin_lists,
    sync_plugins,
)
from parsetrail.core.settings import settings
from parsetrail.core.utils import PDFReader
from PyQt5.QtGui import QBrush, QColor, QFont
from PyQt5.QtWidgets import (
    QDesktopWidget,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)
from sqlalchemy.orm import sessionmaker


def resize_to_table(parent, table):
    """
    Resize the dialog to fit the table, up to 90% of the screen width and height.
    """
    table_width = sum(table.columnWidth(col) for col in range(table.columnCount())) + 50
    table_height = table.verticalHeader().length() + table.horizontalHeader().height() + 75

    # Get screen dimensions
    screen_rect = QDesktopWidget().screenGeometry()
    screen_width = screen_rect.width()
    screen_height = screen_rect.height()

    # Limit dimensions to 90% of the screen size
    max_width = int(screen_width * 0.9)
    max_height = int(screen_height * 0.9)

    # Set dialog size
    parent.resize(min(table_width, max_width), min(table_height, max_height))


class PluginManagerDialog(QDialog):
    def __init__(self, plugin_manager: PluginManager, parent=None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.setWindowTitle("Plugin Manager")

        # Main layout
        main_layout = QVBoxLayout(self)

        # Description
        self.desc = QLabel("Click on a plugin to show instructions for downloading a financial statement.")
        main_layout.addWidget(self.desc)

        # Plugins Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            [
                "Filename",
                "Plugin Name",
                "Version",
                "Company",
                "Suffix",
                "Statement Type",
            ]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)

        # Set font for better readability
        font = QFont("Arial", 10)
        self.table.setFont(font)

        # Connect the row selection to the instructions popup
        self.table.cellClicked.connect(self.show_instructions_dialog)

        # Populate the table with plugin data
        self.update_table()
        main_layout.addWidget(self.table)

        # Buttons layout
        buttons_layout = QHBoxLayout()

        self.check_updates_button = QPushButton("Check For Updates")
        self.check_updates_button.clicked.connect(self.check_for_updates)
        buttons_layout.addWidget(self.check_updates_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons_layout.addWidget(self.close_button)

        main_layout.addLayout(buttons_layout)

        # Resize the window to fit the table
        resize_to_table(self, self.table)

    def update_table(self):
        """
        Populate the table with available plugin data from metadata.
        """
        self.table.setRowCount(0)
        for plugin_name, metadata in self.plugin_manager.metadata.items():
            row_position = self.table.rowCount()
            self.table.insertRow(row_position)

            # Plugin Name
            plugin_item = QTableWidgetItem(plugin_name)
            self.table.setItem(row_position, 0, plugin_item)

            # Metadata fields
            metadata_fields = [
                metadata.get("PLUGIN_NAME", "ERROR"),
                metadata.get("VERSION", "ERROR"),
                metadata.get("COMPANY", "ERROR"),
                metadata.get("SUFFIX", "ERROR"),
                metadata.get("STATEMENT_TYPE", "ERROR"),
            ]
            for col, field in enumerate(metadata_fields, start=1):
                item = QTableWidgetItem(field)
                self.table.setItem(row_position, col, item)

                # Highlight errors in red
                if field.startswith("ERROR"):
                    item.setBackground(QBrush(QColor(255, 182, 193)))  # Light red

        # Resize table columns to fit content
        self.table.resizeColumnsToContents()

    def show_instructions_dialog(self, row, column):
        """
        Show the INSTRUCTIONS metadata for the selected plugin.
        """
        plugin_name = self.table.item(row, 0).text()
        metadata = self.plugin_manager.metadata.get(plugin_name, {})
        instructions = metadata.get("INSTRUCTIONS", "No instructions available.")

        QMessageBox.information(self, f"Instructions for {plugin_name}", instructions, QMessageBox.Ok)

    def check_for_updates(self):
        """
        Check for updates to plugins and update the table if plugins are synchronized.
        """
        self.plugin_manager.load_plugins()
        try:
            local_plugins, server_plugins = get_plugin_lists(self.plugin_manager)
            new_plugins = compare_plugins(local_plugins, server_plugins)
            if new_plugins:
                dialog = PluginSyncDialog(local_plugins, server_plugins, parent=self)
                if dialog.exec_() == QDialog.Accepted:
                    sync_plugins(local_plugins, server_plugins, progress=True, parent=self)
            else:
                QMessageBox.information(self, "Plugins Up to Date", "Plugins are already up to date.")
        except Exception as e:
            QMessageBox.critical(self, "Update Failed", f"Update failed: {e}")

        self.plugin_manager.load_plugins()
        self.update_table()
        resize_to_table(self, self.table)


class PluginSyncDialog(QDialog):
    def __init__(self, local_plugins, server_plugins, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugin Sync Status")
        self.local_plugins = local_plugins
        self.server_plugins = server_plugins

        # Main layout
        layout = QVBoxLayout(self)

        # Table for plugin status
        layout.addWidget(QLabel("Some plugins are out of date:"))
        self.table = self.create_table()
        layout.addWidget(self.table)

        # Buttons
        buttons_layout = QHBoxLayout()
        self.sync_button = QPushButton("Update Plugins")
        self.sync_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("No Update")
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.sync_button)
        buttons_layout.addWidget(self.cancel_button)

        layout.addLayout(buttons_layout)

        # Resize the window to fit the table
        resize_to_table(self, self.table)

    def create_table(self):
        """
        Create a table displaying all plugins with local and remote versions.
        """

        def rename_keys(data):
            """Renames dictionary keys to Titlecase."""
            return [{k.title().replace("_", " "): v for k, v in item.items()} for item in data]

        # Merge local and server plugin data
        local_df = pd.DataFrame(rename_keys(self.local_plugins)).rename(columns={"Version": "Current Version"})
        server_df = pd.DataFrame(rename_keys(self.server_plugins)).rename(columns={"Version": "New Version"})

        # Handle empty DataFrame cases
        if local_df.empty:
            local_df = pd.DataFrame(columns=["Plugin Name", "Current Version"])
        if server_df.empty:
            server_df = pd.DataFrame(columns=["Plugin Name", "New Version"])

        # Join local and remote data
        merged_df = pd.merge(
            server_df,
            local_df,
            on=["Plugin Name"],
            how="outer",
            suffixes=("_server", "_local"),
        )

        # Fill missing values for clarity
        merged_df["Current Version"] = merged_df["Current Version"].fillna("Not Installed")
        merged_df["New Version"] = merged_df["New Version"].fillna("Unknown")

        # Create a QTableWidget to display the data
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Plugin Name", "Current Version", "New Version"])
        table.setRowCount(len(merged_df))

        # Populate the table
        for row, data in merged_df.iterrows():
            plugin_name = data["Plugin Name"]
            local_version = data["Current Version"]
            remote_version = data["New Version"]

            # Add items to the table
            table.setItem(row, 0, QTableWidgetItem(plugin_name))
            table.setItem(row, 1, QTableWidgetItem(local_version))
            table.setItem(row, 2, QTableWidgetItem(remote_version))

            # Apply background color based on version comparison
            if local_version == "Not Installed" or local_version < remote_version:
                # Outdated or missing: light red
                color = QBrush(QColor(255, 182, 193))
            else:
                # Up-to-date: light green
                color = QBrush(QColor(144, 238, 144))

            for col in range(3):
                table.item(row, col).setBackground(color)

        # Resize columns to fit content
        table.resizeColumnsToContents()
        return table


class ParseTestDialog(QDialog):
    def __init__(
        self,
        Session: sessionmaker,
        plugin_manager: PluginManager,
        initial_fpath: Path | None = None,
        initial_input: ParseInput | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("PDF Parsing Troubleshooter")
        self.resize(800, 600)

        self.Session = Session
        self.plugin_manager = plugin_manager
        self.current_fpath: Path | None = initial_fpath
        self.parse_input: ParseInput | None = initial_input or (
            ParseInput.from_path(initial_fpath) if initial_fpath else None
        )

        # Layout
        layout = QVBoxLayout(self)

        # File chooser row
        file_row = QHBoxLayout()
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("Select a file to inspect/parse")
        if self.current_fpath:
            self.file_input.setText(str(self.current_fpath))
        elif self.parse_input:
            self.file_input.setText(self.parse_input.name)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.select_file)
        file_row.addWidget(self.file_input)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        # Buttons
        self.read_pdf_button = QPushButton("Read PDF")
        self.read_pdf_button.clicked.connect(self.read_pdf)
        layout.addWidget(self.read_pdf_button)

        self.extract_tables_button = QPushButton("Extract Tables")
        self.extract_tables_button.clicked.connect(self.extract_tables)
        layout.addWidget(self.extract_tables_button)

        self.test_import_button = QPushButton("Import and Parse File")
        self.test_import_button.clicked.connect(self.test_import)
        layout.addWidget(self.test_import_button)

        # Output Display
        self.output_display = QTextEdit()
        self.output_display.setReadOnly(True)
        self.output_display.setFont(QFont("Courier New"))
        layout.addWidget(self.output_display)

    def select_file(self):
        """Open a file dialog to select a file and store it."""
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        file_filter = "Supported Files (*.csv *.pdf *.xlsx);;All Files (*)"
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Select a File",
            str(settings.import_dir),
            file_filter,
            options=options,
        )
        if fpath:
            self.current_fpath = Path(fpath).resolve()
            self.parse_input = ParseInput.from_path(self.current_fpath)
            self.file_input.setText(str(self.current_fpath))
            self.display_output(f"Selected file: {self.current_fpath}")

    def display_output(self, text: str):
        """Append text to the output display."""
        self.output_display.append(text)

    def set_parse_input(self, parse_input: ParseInput):
        """Set the current input from in-memory data."""
        self.parse_input = parse_input
        self.current_fpath = None
        self.file_input.setText(parse_input.name)
        self.display_output(f"Loaded in-memory input: {parse_input.name}")

    def _ensure_fpath(self) -> Path | None:
        if self.current_fpath and self.current_fpath.exists():
            return self.current_fpath
        candidate = self.file_input.text().strip()
        if candidate:
            maybe = Path(candidate)
            if maybe.exists():
                self.current_fpath = maybe
                return self.current_fpath
        QMessageBox.information(self, "Select a file", "Please choose a file first.")
        return None

    def _ensure_input(self) -> ParseInput | None:
        """Ensure we have a ParseInput, creating one from disk if needed."""
        if self.parse_input:
            return self.parse_input
        fpath = self._ensure_fpath()
        if not fpath:
            return None
        self.parse_input = ParseInput.from_path(fpath)
        return self.parse_input

    def read_pdf(self):
        """Read and display raw PDF content."""
        try:
            parse_input = self._ensure_input()
            if not parse_input:
                return

            with PDFReader(parse_input.data, parse_input.path_hint) as reader:
                self.display_raw_output(parse_input.path_hint, reader)
        except Exception as e:
            logger.exception("Error reading PDF:")
            self.display_output(f"Error: {e}")

    def display_raw_output(self, fpath: Path, reader: PDFReader):
        """Display raw output from the PDFReader."""
        self.output_display.clear()
        self.display_output(f"File: {fpath}")

        # Metadata
        self.display_output("\nMetadata:\n" + "=" * 60)
        for key, value in reader.PDF.metadata.items():
            self.display_output(f"{key}: {value}")

        # Annotations
        self.display_output("\nAnnotations:\n" + "=" * 60)
        for i, page in enumerate(reader.PDF.pages):
            for annot in page.annots:
                self.display_output(f"Annotation {i}:")
                self.display_nested_dict(annot)

        # Simple Text Extraction
        self.display_output("\nSimple Extraction Lines:\n" + "=" * 60)
        self.display_output("\n".join(reader.extract_lines_simple()))

        # Layout Lines
        self.display_output("\nLayout Text:\n" + "=" * 60)
        self.display_output(reader.extract_text_layout())

    def display_nested_dict(self, nested_dict: dict, level=0):
        """Recursively display nested dictionaries."""
        for key, value in nested_dict.items():
            if isinstance(value, dict):
                self.display_output("  " * level + f"{key}:")
                self.display_nested_dict(value, level + 1)
            else:
                self.display_output("  " * level + f"{key}: {value}")

    def extract_tables(self):
        """Extract and display tables from a PDF."""
        try:
            parse_input = self._ensure_input()
            if not parse_input:
                return

            with PDFReader(parse_input.data, parse_input.path_hint) as reader:
                self.display_table_output(parse_input.path_hint, reader)
        except Exception as e:
            logger.exception("Error extracting tables:")
            self.display_output(f"Error: {e}")

    def display_table_output(self, fpath: Path, reader: PDFReader):
        """Display table data extracted from a PDF."""
        self.output_display.clear()
        self.display_output(f"File: {fpath}")

        table_settings = {"vertical_strategy": "text", "horizontal_strategy": "text"}
        for page_no, page in enumerate(reader.PDF.pages):
            self.display_output(f"Page {page_no}:\n" + "=" * 20)
            tables = page.extract_tables(table_settings=table_settings)
            for table_no, table in enumerate(tables):
                self.display_output(f"Table {table_no}:")
                for row in table:
                    self.display_output(" | ".join(row))

    def test_import(self):
        """Test parsing a file and display results."""
        try:
            parse_input = self._ensure_input()
            if not parse_input:
                return

            # Return the statement object
            statement = parse_any(self.Session, self.plugin_manager, parse_input, hard_fail=False)

            # Display results
            self.output_display.clear()
            self.display_output(f"File: {statement.fpath}")
            self.display_output(f"Plugin Name: {statement.plugin_name}")
            self.display_output(f"Start Date: {statement.start_date}")
            self.display_output(f"End Date: {statement.end_date}")
            for account in statement.accounts:
                self.display_output(f"  Account Number: {account.account_num}")
                self.display_output(f"  Start Balance: {account.start_balance}")
                self.display_output(f"  End Balance: {account.end_balance}")
                self.display_output("  Transactions:")
                for transaction in account.transactions:
                    self.display_output(
                        f"    {transaction.transaction_date} {transaction.posting_date}"
                        f" {transaction.amount} {transaction.balance} {transaction.desc}"
                    )
        except Exception as e:
            logger.exception("Error importing file:")
            self.display_output(f"Error: {e}")

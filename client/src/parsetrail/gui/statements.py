from dataclasses import asdict, is_dataclass
from datetime import timedelta

import pandas as pd
from PyQt5.QtCore import QAbstractTableModel, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QPushButton,
    QTableView,
    QTextEdit,
    QVBoxLayout,
)
from sqlalchemy.orm import sessionmaker

from parsetrail.core import query
from parsetrail.core.validation import Statement


def get_missing_coverage(Session: sessionmaker, months=12):
    """
    Returns a DataFrame showing coverage for the first of the month for each account.
    """
    with Session() as session:
        data, columns = query.statement_date_ranges(session, months=months + 3)
    df = pd.DataFrame(data, columns=columns)
    df["StartDate"] = pd.to_datetime(df["StartDate"])
    df["EndDate"] = pd.to_datetime(df["EndDate"])

    start_date = df["StartDate"].min() - timedelta(weeks=4)
    end_date = df["EndDate"].max() + timedelta(weeks=4)
    date_range = pd.date_range(start_date, end_date, freq="D")
    nick_names = df["AccountName"].unique()
    df_missing = pd.DataFrame("Missing", index=date_range, columns=nick_names)

    # Set all days that have statement coverage to True
    for i in range(len(df)):
        account = df["AccountName"].iloc[i]
        start_date = df["StartDate"].iloc[i]
        end_date = df["EndDate"].iloc[i]
        df_missing.loc[start_date:end_date, account] = "OK"

    # Stack the table so coverage is all in a single column
    df_stacked = (
        df_missing.stack().reset_index().rename(columns={"level_0": "Date", "level_1": "AccountName", 0: "Coverage"})
    )

    # Add a month column
    df_stacked["Month"] = df_stacked["Date"].dt.strftime(r"%Y-%m-01")

    # Make a pivot table showing coverage for the first of the month
    df_pivot = df_stacked.pivot_table(values="Coverage", index="Month", columns="AccountName", aggfunc="first")

    # Return the last 13 months as a transposed DataFrame
    return df_pivot.tail(months).T.astype(str)


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
            return str(value)
        elif role == Qt.BackgroundRole:
            if value == "OK":
                return QColor(140, 225, 140)  # Light green
            elif value == "Missing":
                return QColor(225, 160, 160)  # Light red
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return self._data.columns[section]
            if orientation == Qt.Vertical:
                return self._data.index[section]
        return None


class CompletenessDialog(QDialog):
    def __init__(self, Session: sessionmaker, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Statement Completeness Grid")

        # Main layout
        layout = QVBoxLayout()

        # Fetch DataFrame from the function
        self.df = get_missing_coverage(Session, months=60)

        # Create a PandasModel and attach it to a QTableView
        self.table_model = PandasModel(self.df)
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)

        # Ensure columns resize to fit contents
        self.table_view.resizeColumnsToContents()

        # Calculate the total width required for the table
        self.adjust_table_size()

        # Add the table view to the layout
        layout.addWidget(self.table_view)

        # Add a Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self.setLayout(layout)

    def adjust_table_size(self):
        """
        Adjust the size of the dialog and fix the table width based on its contents.
        """
        # Calculate the total width of the table
        total_column_width = sum(self.table_view.columnWidth(col) for col in range(self.table_model.columnCount()))
        vertical_scrollbar_width = self.table_view.verticalScrollBar().sizeHint().width()
        table_width = total_column_width + vertical_scrollbar_width + 100

        # Calculate the total height of the table
        total_row_height = sum(self.table_view.rowHeight(row) for row in range(self.table_model.rowCount()))
        horizontal_header_height = self.table_view.horizontalHeader().height()
        horizontal_scrollbar_height = self.table_view.horizontalScrollBar().sizeHint().height()
        table_height = total_row_height + horizontal_header_height + horizontal_scrollbar_height + 50

        # Get the available screen size
        screen = QApplication.primaryScreen().availableGeometry()
        max_width = int(screen.width() * 0.95)
        max_height = int(screen.height() * 0.95)

        # Constrain the dialog size to the screen size
        final_width = min(table_width, max_width)
        final_height = min(table_height, max_height)

        # Fix the table's width
        self.table_view.setMaximumWidth(final_width)

        # Resize the dialog
        self.resize(final_width, final_height)


class ValidationErrorDialog(QDialog):
    def __init__(self, statement: Statement, errors: str, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Validation Error")
        self.resize(600, 400)

        layout = QVBoxLayout(self)

        # Text display for errors
        error_display = QTextEdit(self)
        error_display.setReadOnly(True)

        # Generate the full display text
        statement_data = self.format_statement(statement)
        display_text = f"Errors:\n{errors}\n\n{statement_data}"
        error_display.setPlainText(display_text)
        layout.addWidget(error_display)

        # Close button
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

    def format_statement(self, statement) -> str:
        """
        Format the Statement data for display, handling up to three levels:
        Statement > Account > Transaction.
        """
        if not is_dataclass(statement):
            raise ValueError("Expected a dataclass instance.")

        output = []

        # Format the top-level Statement fields
        output.append("Statement Data:")
        for field, value in asdict(statement).items():
            if field == "accounts":
                output.append("  accounts:")
                for account in value:
                    output.append(self.format_account(account, level=2))
            else:
                output.append(f"  {field}: {value}")

        return "\n".join(output)

    def format_account(self, account, level=2) -> str:
        """
        Format an Account dataclass, including nested Transactions.
        """
        indent = "  " * level
        output = []

        # Format Account fields
        output.append(f"{indent}Account:")
        for field, value in account.items():
            if field == "transactions":
                output.append(f"{indent}  transactions:")
                for transaction in value:
                    output.append(self.format_transaction(transaction, level + 2))
            else:
                output.append(f"{indent}  {field}: {value}")

        return "\n".join(output)

    def format_transaction(self, transaction, level=3) -> str:
        """
        Format a Transaction dataclass.
        """
        indent = "  " * level
        output = []

        # Format Transaction fields
        output.append(f"{indent}Transaction:")
        for field, value in transaction.items():
            output.append(f"{indent}  {field}: {value}")

        return "\n".join(output)

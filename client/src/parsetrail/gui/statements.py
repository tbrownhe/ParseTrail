from dataclasses import asdict, is_dataclass
from datetime import timedelta

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QSize, Qt
from PySide6.QtGui import QColor, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
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


def get_account_coverage(Session: sessionmaker, months=60):
    """
    Returns per-account statement coverage ranges and the global time window.
    """
    with Session() as session:
        data, columns = query.statement_date_ranges(session, months=months + 3)
    df = pd.DataFrame(data, columns=columns)
    if df.empty:
        return [], None, None

    df["StartDate"] = pd.to_datetime(df["StartDate"])
    df["EndDate"] = pd.to_datetime(df["EndDate"])

    overall_start = df["StartDate"].min().to_pydatetime()
    overall_end = df["EndDate"].max().to_pydatetime()

    accounts = []
    for account, group in df.groupby("AccountName"):
        intervals = []
        for _, row in group.sort_values("StartDate").iterrows():
            intervals.append((row["StartDate"].to_pydatetime(), row["EndDate"].to_pydatetime()))

        merged = []
        for start, end in sorted(intervals, key=lambda item: item[0]):
            if not merged:
                merged.append([start, end])
                continue
            last_start, last_end = merged[-1]
            if start <= last_end + timedelta(days=1):
                merged[-1][1] = max(last_end, end)
            else:
                merged.append([start, end])

        accounts.append(
            {
                "name": account,
                "intervals": [(start, end) for start, end in merged],
            }
        )

    accounts.sort(key=lambda item: item["name"])
    return accounts, overall_start, overall_end


class CoverageModel(QAbstractTableModel):
    ACCOUNT_COL = 0
    COVERAGE_COL = 1

    def __init__(self, accounts):
        super().__init__()
        self._accounts = accounts

    def rowCount(self, parent=None):
        return len(self._accounts) + 2

    def columnCount(self, parent=None):
        return 2

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        if index.row() == 0 or index.row() == len(self._accounts) + 1:
            if role == Qt.DisplayRole and index.column() == self.ACCOUNT_COL:
                return ""
            if role == Qt.UserRole and index.column() == self.COVERAGE_COL:
                return "label_row"
            return None

        account_index = index.row() - 1
        account = self._accounts[account_index]
        if role == Qt.DisplayRole and index.column() == self.ACCOUNT_COL:
            return account["name"]
        if role == Qt.UserRole and index.column() == self.COVERAGE_COL:
            return account["intervals"]
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return "Account" if section == self.ACCOUNT_COL else "Coverage"
        return section + 1


class CoverageBarDelegate(QStyledItemDelegate):
    def __init__(self, overall_start, overall_end, parent=None):
        super().__init__(parent)
        self._overall_start = overall_start
        self._overall_end = overall_end
        if overall_start and overall_end:
            self._total_seconds = max((overall_end - overall_start).total_seconds(), 0)
            month_start = overall_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            self._month_starts = [ts.to_pydatetime() for ts in pd.date_range(month_start, overall_end, freq="MS")]
        else:
            self._total_seconds = 0
            self._month_starts = []

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if index.column() != CoverageModel.COVERAGE_COL:
            return size
        if index.data(Qt.UserRole) == "label_row":
            return QSize(size.width(), max(option.fontMetrics.height() + 18, 30))
        return QSize(size.width(), max(size.height(), 26))

    def paint(self, painter, option, index):
        if index.column() != CoverageModel.COVERAGE_COL:
            super().paint(painter, option, index)
            return

        rect = option.rect.adjusted(6, 6, -6, -6)
        is_label_row = index.data(Qt.UserRole) == "label_row"
        y = rect.center().y()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        if self._total_seconds > 0 and self._month_starts:
            grid_pen = QPen(QColor(200, 200, 200))
            grid_pen.setWidth(1)
            painter.setPen(grid_pen)
            if is_label_row:
                label_pen = QPen(QColor(120, 120, 120))
                painter.setPen(label_pen)
                metrics = painter.fontMetrics()
                base_bounds = metrics.boundingRect("0000-00")
                label_y = rect.top() + (base_bounds.width() / 2)
                min_spacing = max(metrics.height() + 6, 18)
                last_label_x = None
                for month_start in self._month_starts:
                    x = (
                        rect.left()
                        + ((month_start - self._overall_start).total_seconds() / self._total_seconds) * rect.width()
                    )
                    x = max(rect.left(), min(rect.right(), x))
                    if last_label_x is not None and x - last_label_x < min_spacing:
                        continue
                    label = month_start.strftime("%Y-%m")
                    label_x = int(x)
                    painter.save()
                    painter.translate(label_x, label_y)
                    painter.rotate(-90)
                    bounds = metrics.boundingRect(label)
                    center_x = bounds.x() + bounds.width() / 2
                    center_y = bounds.y() + bounds.height() / 2
                    painter.drawText(
                        -int(center_x),
                        -int(center_y),
                        label,
                    )
                    painter.restore()
                    last_label_x = x
            else:
                for month_start in self._month_starts:
                    x = (
                        rect.left()
                        + ((month_start - self._overall_start).total_seconds() / self._total_seconds) * rect.width()
                    )
                    x = max(rect.left(), min(rect.right(), x))
                    painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
        if is_label_row:
            painter.restore()
            return

        red_pen = QPen(QColor(40, 40, 40))
        red_pen.setWidth(4)
        red_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(red_pen)
        painter.drawLine(rect.left(), y, rect.right(), y)

        intervals = index.data(Qt.UserRole) or []
        if intervals:
            green_pen = QPen(QColor(80, 170, 80))
            green_pen.setWidth(8)
            green_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(green_pen)

            if self._total_seconds <= 0:
                painter.drawLine(rect.left(), y, rect.right(), y)
            else:
                for start, end in intervals:
                    start_x = (
                        rect.left()
                        + ((start - self._overall_start).total_seconds() / self._total_seconds) * rect.width()
                    )
                    end_x = (
                        rect.left() + ((end - self._overall_start).total_seconds() / self._total_seconds) * rect.width()
                    )
                    if end_x < start_x:
                        start_x, end_x = end_x, start_x
                    start_x = max(rect.left(), min(rect.right(), start_x))
                    end_x = max(rect.left(), min(rect.right(), end_x))
                    painter.drawLine(int(start_x), y, int(end_x), y)

        painter.restore()


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
        self._Session = Session

        # Main layout
        layout = QVBoxLayout()

        self.table_view = QTableView()
        self.table_model = None
        self._apply_table_model(months=12)

        # Calculate the total width required for the table
        self.adjust_table_size()

        # Add the table view to the layout
        layout.addWidget(self.table_view)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Months to show:"))
        self.months_input = QLineEdit("12")
        self.months_input.setValidator(QIntValidator(1, 1200, self))
        self.months_input.editingFinished.connect(self._update_months)
        self.months_input.setMaximumWidth(80)
        controls_layout.addWidget(self.months_input)
        controls_layout.addStretch(1)

        # Add a Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        controls_layout.addWidget(close_button)

        layout.addLayout(controls_layout)

        self.setLayout(layout)

    def _apply_table_model(self, months: int) -> None:
        accounts, overall_start, overall_end = get_account_coverage(self._Session, months=months)

        self.table_model = CoverageModel(accounts)
        self.table_view.setModel(self.table_model)

        if overall_start and overall_end:
            delegate = CoverageBarDelegate(overall_start, overall_end, self.table_view)
            self.table_view.setItemDelegateForColumn(CoverageModel.COVERAGE_COL, delegate)

        self.table_view.horizontalHeader().setSectionResizeMode(CoverageModel.ACCOUNT_COL, QHeaderView.ResizeToContents)
        self.table_view.horizontalHeader().setSectionResizeMode(CoverageModel.COVERAGE_COL, QHeaderView.Stretch)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.verticalHeader().setDefaultSectionSize(28)
        self.table_view.setColumnWidth(CoverageModel.COVERAGE_COL, 600)
        self.table_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if self.table_model.rowCount() > 0:
            top_label_row = 0
            bottom_label_row = self.table_model.rowCount() - 1
            label_height = self.table_view.fontMetrics().horizontalAdvance("0000-00") + 18
            self.table_view.setRowHeight(top_label_row, label_height)
            self.table_view.setRowHeight(bottom_label_row, label_height)

    def _update_months(self) -> None:
        text = self.months_input.text().strip()
        if not text:
            return
        months = int(text)
        if months <= 0:
            return
        self._apply_table_model(months)
        self.adjust_table_size()

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
        preferred_width = int(screen.width() * 0.9)
        final_width = min(max(table_width, preferred_width), max_width)
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

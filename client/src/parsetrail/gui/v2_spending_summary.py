"""Read-only 2.0 spending summary from the reviewed journal."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QTableView,
    QTabWidget,
    QVBoxLayout,
)

from parsetrail.core.v2_profile_store import (
    FinancialJournalMovement,
    FinancialJournalSummary,
    ProfileFormatError,
    SpendingCategoryTotal,
    SpendingSummary,
    V2ProfileStore,
)
from parsetrail.gui.v2_evidence_preview import _money


class _SpendingModel(QAbstractTableModel):
    HEADERS = ("Expense category", "Net reviewed spending")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: tuple[SpendingCategoryTotal, ...] = ()

    def replace(self, rows: tuple[SpendingCategoryTotal, ...]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.ToolTipRole}:
            return None
        row = self.rows[index.row()]
        return row.name if index.column() == 0 else _money(row.amount_minor)


class _AccountMovementModel(QAbstractTableModel):
    HEADERS = ("Financial account", "Class", "Reviewed change", "Opening position")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: tuple[FinancialJournalMovement, ...] = ()

    def replace(self, rows: tuple[FinancialJournalMovement, ...]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.ToolTipRole}:
            return None
        row = self.rows[index.row()]
        sign = 1 if row.kind == "asset" else -1
        values = (
            row.name,
            row.kind.title(),
            _money(row.nonopening_change_minor * sign),
            _money(row.opening_minor * sign) if row.opening_minor is not None else "Not established",
        )
        return values[index.column()]


class V2SpendingSummaryDialog(QDialog):
    """Show reviewed net spending without claiming complete source coverage."""

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("2.0 spending and account movement")
        self.resize(850, 550)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        today = date.today()
        first = date(today.year, today.month, 1)
        next_month = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
        self.start = QDateEdit(QDate(first.year, first.month, first.day))
        self.end = QDateEdit(QDate(next_month.year, next_month.month, next_month.day))
        for control in (self.start, self.end):
            control.setCalendarPopup(True)
            control.setDisplayFormat("yyyy-MM-dd")
        form.addRow("From (inclusive)", self.start)
        form.addRow("To (exclusive)", self.end)
        layout.addLayout(form)
        self.model = _SpendingModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.account_model = _AccountMovementModel(self)
        self.account_table = QTableView()
        self.account_table.setModel(self.account_model)
        self.account_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.account_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.account_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.table, "Spending")
        self.tabs.addTab(self.account_table, "Account movement")
        layout.addWidget(self.tabs)
        self.total = QLabel()
        layout.addWidget(self.total)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.start.dateChanged.connect(self.refresh)
        self.end.dateChanged.connect(self.refresh)
        self.tabs.currentChanged.connect(self._show_selected_tab)
        self.spending_report: SpendingSummary | None = None
        self.account_report: FinancialJournalSummary | None = None
        self.refresh()

    def refresh(self, *_args) -> None:
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                start, end = self.start.date().toPython(), self.end.date().toPython()
                self.spending_report = store.spending_summary(start=start, end=end)
                self.account_report = store.financial_journal_summary(start=start, end=end)
        except ProfileFormatError as exc:
            if str(exc) != "report_period_invalid":
                raise
            self.model.replace(())
            self.account_model.replace(())
            self.spending_report = None
            self.account_report = None
            self.total.setText("Choose an end date after the start date.")
            self.scope.clear()
            return
        self.model.replace(self.spending_report.categories)
        self.account_model.replace(self.account_report.accounts)
        self._show_selected_tab()

    def _show_selected_tab(self, *_args) -> None:
        report = self.spending_report
        if report is None:
            return
        if self.tabs.currentIndex() == 1:
            self.total.setText(
                "Reviewed journal change: positive increases asset value or liability owed; "
                "negative decreases it. Opening positions are shown separately."
            )
        else:
            self.total.setText(f"Net reviewed spending from posted journal entries: {_money(report.total_minor)}")
        excluded = (
            self.account_report.excluded_unreviewed_financial_entries
            if self.tabs.currentIndex() == 1
            else report.excluded_unreviewed_expense_entries
        )
        unreviewed_note = f"{excluded} unreviewed journal entries were excluded. " if excluded else ""
        account_note = (
            "These are journal changes, not account balances or certified cash flow. "
            "An opening position marked Not established is unknown, not zero. "
            if self.tabs.currentIndex() == 1
            else ""
        )
        self.scope.setText(
            f"Across the whole profile, {report.activity_rows_without_full_allocation} activity source row(s) "
            f"from {report.sources_with_incomplete_activity} source(s) lack a full ledger allocation. "
            f"The date range above filters posted journal entries only. "
            f"{unreviewed_note}"
            f"{account_note}"
            "Source rows may overlap; this summary does not establish unique activity, statement coverage "
            "or reconciled balances."
        )

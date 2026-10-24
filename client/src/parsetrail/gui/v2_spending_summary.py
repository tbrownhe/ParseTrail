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
    QVBoxLayout,
)

from parsetrail.core.v2_profile_store import ProfileFormatError, SpendingCategoryTotal, V2ProfileStore
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


class V2SpendingSummaryDialog(QDialog):
    """Show reviewed net spending without claiming complete source coverage."""

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("2.0 spending summary")
        self.resize(720, 510)
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
        layout.addWidget(self.table)
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
        self.refresh()

    def refresh(self, *_args) -> None:
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                report = store.spending_summary(start=self.start.date().toPython(), end=self.end.date().toPython())
        except ProfileFormatError as exc:
            if str(exc) != "spending_period_invalid":
                raise
            self.model.replace(())
            self.total.setText("Choose an end date after the start date.")
            self.scope.clear()
            return
        self.model.replace(report.categories)
        self.total.setText(f"Net reviewed spending from posted journal entries: {_money(report.total_minor)}")
        unreviewed_note = (
            f"{report.excluded_unreviewed_expense_entries} unreviewed expense entries were excluded. "
            if report.excluded_unreviewed_expense_entries
            else ""
        )
        self.scope.setText(
            f"Across the whole profile, {report.activity_rows_without_full_allocation} activity source row(s) "
            f"from {report.sources_with_incomplete_activity} source(s) lack a full ledger allocation. "
            f"The date range above filters posted journal entries only. "
            f"{unreviewed_note}"
            "Source rows may overlap; this summary does not establish unique activity, statement coverage "
            "or reconciled balances."
        )

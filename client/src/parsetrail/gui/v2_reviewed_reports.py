"""Read-only 2.0 category, account movement and budget reports."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_profile_store import (
    FinancialJournalMovement,
    FinancialJournalSummary,
    MonthlyBudgetRow,
    MonthlyBudgetSummary,
    ProfileFormatError,
    ReviewedCategorySummary,
    ReviewedCategoryTotal,
    V2ProfileStore,
)
from parsetrail.core.v2_report_export import ReportExportError, write_reviewed_journal_workbook
from parsetrail.gui.v2_evidence_preview import _money


class _CategoryModel(QAbstractTableModel):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.headers = (
            ("Expense category", "Net reviewed spending")
            if kind == "expense"
            else ("Income category", "Net reviewed income")
        )
        self.rows: tuple[ReviewedCategoryTotal, ...] = ()

    def replace(self, rows: tuple[ReviewedCategoryTotal, ...]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.headers)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
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


class _MonthlyBudgetModel(QAbstractTableModel):
    HEADERS = ("Expense category", "Monthly target", "Reviewed spending", "Remaining")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: tuple[MonthlyBudgetRow, ...] = ()

    def replace(self, rows: tuple[MonthlyBudgetRow, ...]) -> None:
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
        values = (
            row.name,
            _money(row.target_minor) if row.target_minor is not None else "No target",
            _money(row.reviewed_spending_minor),
            _money(row.remaining_minor) if row.remaining_minor is not None else "—",
        )
        if role == Qt.ToolTipRole and index.column() == 1 and row.target_effective_month is not None:
            return f"Target effective {row.target_effective_month:%Y-%m}"
        return values[index.column()]


class V2ReviewedReportsDialog(QDialog):
    """Show reviewed journal totals with visible source coverage limits."""

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("2.0 reviewed reports")
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
        layout.addWidget(
            QLabel("Date range applies to Spending, Income and Account movement; Monthly budgets use their own month.")
        )
        self.model = _CategoryModel("expense", self)
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
        budget_panel = QWidget()
        budget_layout = QVBoxLayout(budget_panel)
        budget_form = QFormLayout()
        self.budget_month = QDateEdit(QDate(first.year, first.month, 1))
        self.budget_month.setCalendarPopup(True)
        self.budget_month.setDisplayFormat("yyyy-MM")
        self.budget_month.setMaximumDate(QDate(9999, 11, 1))
        budget_form.addRow("Budget month", self.budget_month)
        budget_layout.addLayout(budget_form)
        self.budget_model = _MonthlyBudgetModel(self)
        self.budget_table = QTableView()
        self.budget_table.setModel(self.budget_model)
        self.budget_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.budget_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.budget_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        budget_layout.addWidget(self.budget_table)
        self.tabs.addTab(budget_panel, "Monthly budgets")
        self.income_model = _CategoryModel("income", self)
        self.income_table = QTableView()
        self.income_table.setModel(self.income_model)
        self.income_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.income_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.income_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tabs.addTab(self.income_table, "Income")
        layout.addWidget(self.tabs)
        self.total = QLabel()
        layout.addWidget(self.total)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.export_button = buttons.addButton("Export reviewed rows…", QDialogButtonBox.ActionRole)
        self.export_button.clicked.connect(self._export_reviewed_rows)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.start.dateChanged.connect(self.refresh)
        self.end.dateChanged.connect(self.refresh)
        self.tabs.currentChanged.connect(self._show_selected_tab)
        self.budget_month.dateChanged.connect(self._refresh_budget)
        self.spending_report: ReviewedCategorySummary | None = None
        self.income_report: ReviewedCategorySummary | None = None
        self.account_report: FinancialJournalSummary | None = None
        self.budget_report: MonthlyBudgetSummary | None = None
        self.refresh()
        self._refresh_budget()

    def refresh(self, *_args) -> None:
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                start, end = self.start.date().toPython(), self.end.date().toPython()
                self.spending_report = store.reviewed_category_summary(kind="expense", start=start, end=end)
                self.income_report = store.reviewed_category_summary(kind="income", start=start, end=end)
                self.account_report = store.financial_journal_summary(start=start, end=end)
        except ProfileFormatError as exc:
            if str(exc) != "report_period_invalid":
                raise
            self.model.replace(())
            self.income_model.replace(())
            self.account_model.replace(())
            self.spending_report = None
            self.income_report = None
            self.account_report = None
            self.export_button.setEnabled(False)
            self._show_selected_tab()
            return
        self.model.replace(self.spending_report.categories)
        self.income_model.replace(self.income_report.categories)
        self.account_model.replace(self.account_report.accounts)
        self.export_button.setEnabled(True)
        self._show_selected_tab()

    def _export_reviewed_rows(self) -> None:
        if self.spending_report is None:
            return
        start, end = self.start.date().toPython(), self.end.date().toPython()
        default = self.profile.with_name(f"reviewed-{start:%Y%m%d}-{end:%Y%m%d}.xlsx")
        selected, _filter = QFileDialog.getSaveFileName(
            self, "Export active reviewed journal rows", str(default), "Excel workbooks (*.xlsx);;All files (*)"
        )
        if not selected:
            return
        destination = Path(selected)
        if not destination.suffix:
            destination = destination.with_suffix(".xlsx")
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                report = store.reviewed_journal_export(start=start, end=end)
            saved = write_reviewed_journal_workbook(report, destination)
        except (ProfileFormatError, ReportExportError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Export was not saved", str(exc))
            return
        QMessageBox.information(
            self,
            "Reviewed export saved",
            f"Saved {len(report.entries)} active reviewed entries to {saved}. "
            "The workbook includes posting lines, source allocations, corrections and coverage notes. "
            "It contains financial data and is not encrypted by ParseTrail.",
        )

    def _refresh_budget(self, *_args) -> None:
        selected = self.budget_month.date()
        month = date(selected.year(), selected.month(), 1)
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            self.budget_report = store.monthly_budget_summary(month)
        self.budget_model.replace(self.budget_report.categories)
        self._show_selected_tab()

    def _show_selected_tab(self, *_args) -> None:
        if self.tabs.currentIndex() == 2:
            budget = self.budget_report
            if budget is None:
                return
            untargeted = sum(row.target_minor is None for row in budget.categories)
            if budget.total_target_minor is None:
                target_note = f"{untargeted} expense category(s) have no target; no total target is shown."
            else:
                target_note = f"Total target: {_money(budget.total_target_minor)}."
            self.total.setText(
                f"{budget.month:%Y-%m}: {target_note} "
                f"Net reviewed spending: {_money(budget.total_reviewed_spending_minor)}. "
                "Remaining means target minus reviewed spending."
            )
            self.scope.setText(
                f"Across the whole profile, {budget.activity_rows_without_full_allocation} activity source row(s) "
                f"from {budget.sources_with_incomplete_activity} source(s) lack a full ledger allocation. "
                f"{budget.excluded_unreviewed_expense_entries} unreviewed expense journal entries were excluded. "
                "Targets apply to whole calendar months; spending includes reviewed journal entries only. "
                "Source rows may overlap, and this view does not establish complete spending or budget compliance."
            )
            return
        if self.tabs.currentIndex() == 3:
            income = self.income_report
            if income is None:
                self.total.setText("Choose an end date after the start date.")
                self.scope.clear()
                return
            self.total.setText(f"Net reviewed income from posted journal entries: {_money(income.total_minor)}")
            self.scope.setText(
                f"Across the whole profile, {income.activity_rows_without_full_allocation} activity source row(s) "
                f"from {income.sources_with_incomplete_activity} source(s) lack a full ledger allocation. "
                "The date range above filters posted journal entries only. "
                f"{income.excluded_unreviewed_entries} unreviewed income journal entries were excluded. "
                "This is explicitly categorized income, not all deposits or certified cash flow. "
                "Source rows may overlap; this view does not establish complete income or statement coverage."
            )
            return
        report = self.spending_report
        if report is None:
            self.total.setText("Choose an end date after the start date.")
            self.scope.clear()
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
            else report.excluded_unreviewed_entries
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

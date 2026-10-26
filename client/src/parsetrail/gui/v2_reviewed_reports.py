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
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_builtin_categories import category_labels
from parsetrail.core.v2_profile_store import (
    AccountPosition,
    AccountPositionHistoryRow,
    AccountPositionsSummary,
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
from parsetrail.gui.v2_path_notice import show_path_notice
from parsetrail.gui.v2_report_drilldown import V2ReviewedEntryDrilldown


def _dated_value_note(row: AccountPosition, *, full_reference: bool = False) -> str:
    direction = 1 if row.kind == "asset" else -1
    if row.value_status == "conflict":
        facts = "; ".join(
            f"{_money(direction * value.amount_minor)} ({value.origin}, value {value.value_id})"
            for value in row.conflicting_dated_values
        )
        return (
            f"Conflicting reviewed dated values at {row.conflicting_dated_values[0].value_date.isoformat()}: "
            f"{facts}. No single value is selected. "
            "These nonposting facts do not replace the books or establish settlement."
        )
    value = row.latest_dated_value
    if value is None:
        return "No reviewed dated value applies through this as-of date."
    reference = value.reference
    if not full_reference and len(reference) > 100:
        reference = reference[:100] + "…"
    note = (
        f"Latest {value.origin} dated value: {_money(direction * value.amount_minor)} as of {value.value_date.isoformat()}; "
        f"reference: {reference}. This nonposting value does not replace the books or establish settlement."
    )
    agreeing = tuple(point for point in row.current_dated_values if point.value_date == value.value_date)
    if len(agreeing) > 1:
        note += f" {len(agreeing)} current points agree at this date; their amounts are not added."
    if value.source_proof is not None:
        proof = value.source_proof
        rule = {
            "debit-signed-1": "already debit signed",
            "positive-owed-negate-1": "positive amount owed converted to negative debit",
        }[proof.sign_rule]
        note += (
            f" Extracted closing {_money(proof.closing.minor)} ({proof.closing.provenance}); "
            f"reviewed debit {_money(value.amount_minor)} ({rule}). "
            f"Source endpoint {proof.value_date.iso} ({proof.value_date.provenance})."
        )
    if any(point.source_review_changed for point in agreeing) or value.source_review_changed:
        note += " Source review annotations changed since a point was recorded; inspect its retained review context."
    return note


class _CategoryModel(QAbstractTableModel):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.labels = {}
        self.headers = (
            ("Expense category", "Net reviewed spending")
            if kind == "expense"
            else ("Income category", "Net reviewed income")
        )
        self.rows: tuple[ReviewedCategoryTotal, ...] = ()

    def replace(self, rows: tuple[ReviewedCategoryTotal, ...]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.labels = category_labels((row.category_id, row.name, self.kind) for row in rows)
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
        return self.labels[row.category_id] if index.column() == 0 else _money(row.amount_minor)


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
        self.labels = {}

    def replace(self, rows: tuple[MonthlyBudgetRow, ...]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.labels = category_labels((row.category_id, row.name, "expense") for row in rows)
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
            self.labels[row.category_id],
            _money(row.target_minor) if row.target_minor is not None else "No target",
            _money(row.reviewed_spending_minor),
            _money(row.remaining_minor) if row.remaining_minor is not None else "—",
        )
        if role == Qt.ToolTipRole and index.column() == 1 and row.target_effective_month is not None:
            return f"Target effective {row.target_effective_month:%Y-%m}"
        return values[index.column()]


class _AccountPositionModel(QAbstractTableModel):
    HEADERS = (
        "Financial account",
        "Class",
        "Recorded\njournal total",
        "Opening-based\njournal position",
        "Opening state",
        "Pending rows\n(all dates)",
        "Live check\nthrough",
        "Latest source\nperiod end",
        "Latest saved\ncutoff",
        "Saved cutoff\n(current inputs)",
        "Tracking scope",
        "Opening origin",
        "Latest reviewed\ndated value",
        "Tracking state\nat as-of",
    )
    OPENING_STATES = {
        "missing": "Not established",
        "withdrawn": "Withdrawn — unknown",
        "stale": "Stale — review opening",
        "future": "After as-of date",
        "conflict": "Earlier postings need review",
        "valid": "Valid at as-of date",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: tuple[AccountPosition, ...] = ()

    def replace(self, rows: tuple[AccountPosition, ...]) -> None:
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
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.TextAlignmentRole and index.column() in (2, 3, 5):
            return Qt.AlignRight | Qt.AlignVCenter
        if role == Qt.ToolTipRole:
            if index.column() == 12:
                return _dated_value_note(row, full_reference=True)
            return (
                f"{row.name} ({row.account_id}); {row.currency}. "
                "Positive means asset value or liability owed. Recorded totals include reviewed postings only. "
                "A live successful check is computed now; it is not a saved reconciliation decision. "
                "Latest saved cutoff includes historical decisions; the current-input cutoff excludes stale decisions. "
                "Pending rows cover all dates and may include supporting repeats. "
                "Dated values are nonposting reviews; closure metadata never zeros residual books."
            )
        if role != Qt.DisplayRole:
            return None
        sign = 1 if row.kind == "asset" else -1
        value, lifecycle = row.latest_dated_value, row.lifecycle
        values = (
            row.name,
            row.kind.title(),
            _money(sign * row.recorded_debit_minor),
            _money(sign * row.position_debit_minor) if row.position_debit_minor is not None else "Unknown",
            self.OPENING_STATES[row.opening_status],
            str(row.pending_activity_rows),
            (
                row.live_reconciled_cutoff.isoformat()
                if row.live_reconciled_cutoff
                else "Unavailable"
                if "live_reconciliation_unavailable" in row.coverage_warnings
                else "None passing"
            ),
            row.latest_source_cutoff.isoformat() if row.latest_source_cutoff else "Unavailable",
            row.latest_saved_reconciled_cutoff.isoformat() if row.latest_saved_reconciled_cutoff else "None saved",
            row.current_saved_reconciled_cutoff.isoformat() if row.current_saved_reconciled_cutoff else "None current",
            {
                "account_total": "Whole account",
                "principal_component": "Loan principal",
                "cash_component": "Cash component",
            }[row.tracking_scope],
            {"source": "Source-backed", "manual": "Reviewed manual", None: "None current"}[row.opening_origin],
            f"{_money(sign * value.amount_minor)}\n{value.value_date.isoformat()} ({value.origin})"
            if value
            else f"Conflicting reviewed values\n{row.conflicting_dated_values[0].value_date.isoformat()}"
            if row.value_status == "conflict"
            else "None through as-of",
            f"Tracking {lifecycle.state}\n{lifecycle.effective_date.isoformat()}"
            if lifecycle
            else "No effective closure",
        )
        return values[index.column()]


class _AccountPositionHistoryModel(QAbstractTableModel):
    HEADERS = ("Accounting date", "Description", "Change", "Recorded total", "Opening-based position", "History")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: tuple[AccountPositionHistoryRow, ...] = ()
        self.sign = 1

    def replace(self, rows: tuple[AccountPositionHistoryRow, ...], kind: str = "asset") -> None:
        self.beginResetModel()
        self.rows = rows
        self.sign = 1 if kind == "asset" else -1
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
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.TextAlignmentRole and index.column() in (2, 3, 4):
            return Qt.AlignRight | Qt.AlignVCenter
        if role == Qt.ToolTipRole:
            return (
                f"{row.description}\nOrigin: {row.origin}; entry: {row.entry_key}; event: {row.event_id}.\n"
                "History uses accounting dates and the reviewed books as they stand now, including corrections. "
                "Rows on the same date are ordered by entry key; intermediate totals are not intraday bank balances."
            )
        if role != Qt.DisplayRole:
            return None
        values = (
            row.posting_date.isoformat(),
            row.description,
            _money(self.sign * row.debit_change_minor),
            _money(self.sign * row.recorded_debit_minor),
            _money(self.sign * row.position_debit_minor) if row.position_debit_minor is not None else "Unknown",
            (row.correction_role or row.origin).replace("_", " ").title(),
        )
        return values[index.column()]


class V2ReviewedReportsDialog(QDialog):
    """Show reviewed journal totals with visible source coverage limits."""

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("2.0 reviewed reports")
        self.resize(1180, 780)
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
        period_scope = QLabel(
            "Date range applies to Spending, Income and Account movement. "
            "Monthly budgets and Account positions use their own dates."
            " Select a category or movement account, then Inspect entries to see its current reviewed rows."
        )
        period_scope.setWordWrap(True)
        layout.addWidget(period_scope)
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
        self._create_positions_panel(today)
        layout.addWidget(self.tabs)
        self.total = QLabel()
        self.total.setWordWrap(True)
        layout.addWidget(self.total)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.inspect_button = buttons.addButton("Inspect entries…", QDialogButtonBox.ActionRole)
        self.inspect_button.clicked.connect(self._inspect_current)
        self.inspect_button.setEnabled(False)
        self.refresh_reports_button = buttons.addButton("Refresh reports", QDialogButtonBox.ActionRole)
        self.refresh_reports_button.clicked.connect(self._refresh_all_reports)
        for tab, table in enumerate((self.table, self.account_table, self.budget_table, self.income_table)):
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setSelectionMode(QAbstractItemView.SingleSelection)
            table.doubleClicked.connect(lambda index, selected_tab=tab: self._inspect_report_row(selected_tab, index))
            table.selectionModel().currentRowChanged.connect(self._update_inspect_button)
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
        self.report_error: str | None = None
        self.budget_error: str | None = None
        self.positions_report: AccountPositionsSummary | None = None
        self.positions_error: str | None = None
        self.refresh()
        self._refresh_budget()
        self._refresh_positions()

    def _refresh_all_reports(self) -> None:
        self.refresh()
        self._refresh_budget()
        self._refresh_positions()

    def _update_inspect_button(self, *_args) -> None:
        tables = (self.table, self.account_table, self.budget_table, self.income_table)
        tab = self.tabs.currentIndex()
        self.inspect_button.setEnabled(tab < len(tables) and tables[tab].currentIndex().isValid())

    def _inspect_current(self) -> None:
        tables = (self.table, self.account_table, self.budget_table, self.income_table)
        tab = self.tabs.currentIndex()
        if tab < len(tables):
            self._inspect_report_row(tab, tables[tab].currentIndex())

    def _inspect_report_row(self, tab: int, index: QModelIndex) -> None:
        models = (self.model, self.account_model, self.budget_model, self.income_model)
        if not index.isValid() or not 0 <= tab < len(models) or not 0 <= index.row() < models[tab].rowCount():
            return
        start, end = self.start.date().toPython(), self.end.date().toPython()
        if tab == 0 and self.spending_report is not None:
            row = self.model.rows[index.row()]
            account_id, expected = row.category_id, row.amount_minor
        elif tab == 1 and self.account_report is not None:
            row = self.account_model.rows[index.row()]
            account_id = row.account_id
            expected = row.nonopening_change_minor * (1 if row.kind == "asset" else -1)
        elif tab == 2 and self.budget_report is not None:
            row = self.budget_model.rows[index.row()]
            account_id, expected = row.category_id, row.reviewed_spending_minor
            start = self.budget_report.month
            end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        elif tab == 3 and self.income_report is not None:
            row = self.income_model.rows[index.row()]
            account_id, expected = row.category_id, row.amount_minor
        else:
            return
        V2ReviewedEntryDrilldown(
            self.profile, account_id, start=start, end=end, expected_total_minor=expected, parent=self
        ).exec()

    def _create_positions_panel(self, today: date) -> None:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("As of (inclusive)"))
        self.as_of = QDateEdit(QDate(today.year, today.month, today.day))
        self.as_of.setCalendarPopup(True)
        self.as_of.setDisplayFormat("yyyy-MM-dd")
        controls.addWidget(self.as_of)
        refresh = QPushButton("Refresh positions")
        refresh.clicked.connect(self._refresh_positions)
        controls.addWidget(refresh)
        self.account_anchor_button = QPushButton("Review selected account…")
        self.account_anchor_button.setEnabled(False)
        self.account_anchor_button.clicked.connect(self._review_selected_account)
        controls.addWidget(self.account_anchor_button)
        self.source_value_button = QPushButton("Review source values…")
        self.source_value_button.setEnabled(False)
        self.source_value_button.clicked.connect(self._review_selected_source_values)
        controls.addWidget(self.source_value_button)
        controls.addStretch()
        layout.addLayout(controls)
        note = QLabel(
            "USD reviewed books through the selected accounting date. Positive means asset value or liability owed. "
            "An opening-based journal position needs a valid opening; Unknown is not zero. "
            "Select an account to inspect its history and evidence limits."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.positions_model = _AccountPositionModel(self)
        self.positions_table = QTableView()
        self.positions_table.setModel(self.positions_model)
        self.positions_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.positions_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.positions_table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.positions_table.horizontalHeader()
        header.setMinimumHeight(header.fontMetrics().lineSpacing() * 2 + 16)
        for column, width in enumerate((180, 80, 130, 150, 185, 115, 125, 125, 130, 150, 150, 150, 190, 180)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.positions_table.setColumnWidth(column, width)
        self.positions_table.setMinimumHeight(120)
        self.positions_table.verticalHeader().setDefaultSectionSize(44)
        self.position_details = QLabel("No financial accounts in this profile.")
        self.position_details.setWordWrap(True)
        self.position_details.setTextFormat(Qt.PlainText)
        self.position_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.history_model = _AccountPositionHistoryModel(self)
        self.history_table = QTableView()
        self.history_table.setModel(self.history_model)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        history_header = self.history_table.horizontalHeader()
        for column, width in enumerate((125, 260, 110, 130, 165, 110)):
            history_header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.history_table.setColumnWidth(column, width)
        history_header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.history_table.setMinimumHeight(120)
        upper = QWidget()
        upper_layout = QVBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.addWidget(self.positions_table)
        upper_layout.addWidget(self.position_details)
        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        self.history_title = QLabel("Reviewed accounting history")
        lower_layout.addWidget(self.history_title)
        lower_layout.addWidget(self.history_table)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(upper)
        splitter.addWidget(lower)
        splitter.setSizes([260, 180])
        layout.addWidget(splitter)
        self.tabs.addTab(panel, "Account positions")
        self.positions_table.selectionModel().currentRowChanged.connect(self._show_position_history)
        self.as_of.dateChanged.connect(self._refresh_positions)

    def _refresh_positions(self, *_args) -> None:
        selected = self.positions_table.currentIndex()
        selected_id = self.positions_model.rows[selected.row()].account_id if selected.isValid() else None
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                report = store.account_positions(as_of=self.as_of.date().toPython())
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self._clear_unavailable_reports(exc)
        else:
            self.positions_report = report
            self.positions_error = None
            self.positions_model.replace(report.accounts)
            if report.accounts:
                selected_row = next(
                    (index for index, row in enumerate(report.accounts) if row.account_id == selected_id), 0
                )
                self.positions_table.selectRow(selected_row)
                self._show_position_history()
            else:
                self.history_model.replace(())
                self.account_anchor_button.setEnabled(False)
                self.source_value_button.setEnabled(False)
                self.position_details.setToolTip("")
                self.position_details.setText("No financial accounts in this profile. Add an account to begin.")
                self.history_title.setText("Reviewed accounting history")
        self._show_selected_tab()

    def _show_position_history(self, *_args) -> None:
        index = self.positions_table.currentIndex()
        if not index.isValid():
            self.history_model.replace(())
            self.account_anchor_button.setEnabled(False)
            self.source_value_button.setEnabled(False)
            self.position_details.setText("Select an account to inspect its reviewed history and limits.")
            self.position_details.setToolTip("")
            return
        row = self.positions_model.rows[index.row()]
        self.account_anchor_button.setEnabled(True)
        self.source_value_button.setEnabled(True)
        self.history_model.replace(row.history, row.kind)
        self.history_title.setText(
            f"{row.name}: reviewed accounting history through {self.as_of.date().toString('yyyy-MM-dd')} "
            f"({len(row.history)} entries)"
        )
        direction = 1 if row.kind == "asset" else -1
        opening = (
            f"{_money(direction * row.opening_minor)} at {row.opening_cutoff}"
            if row.opening_minor is not None
            else "not established"
        )
        latest_activity = row.latest_activity_date.isoformat() if row.latest_activity_date else "unavailable"
        warning_labels = {
            "no_statement_coverage": "No bound statement periods",
            "source_period_gap": "Gap between bound statement periods",
            "source_period_overlap": "Bound statement periods overlap",
            "source_capture_incomplete": "Source page capture unverified",
            "source_cutoff_before_as_of": "Latest source period ends before the as-of date",
            "source_period_extends_after_as_of": "A source period extends beyond the as-of date",
            "live_reconciliation_unavailable": "Live reconciliation unavailable; review bound source sections",
        }
        limits = "; ".join(warning_labels.get(reason, reason.replace("_", " ")) for reason in row.coverage_warnings)
        latest_saved = row.latest_saved_reconciled_cutoff.isoformat() if row.latest_saved_reconciled_cutoff else "none"
        current_saved = (
            row.current_saved_reconciled_cutoff.isoformat() if row.current_saved_reconciled_cutoff else "none"
        )
        scope_label = {
            "account_total": "whole account",
            "principal_component": "loan principal only",
            "cash_component": "cash component only",
        }[row.tracking_scope]
        origin_label = {"source": "source-backed review", "manual": "reviewed manual fact", None: "not established"}[
            row.opening_origin
        ]
        value_note = _dated_value_note(row)
        lifecycle_note = "No closure is effective in tracking metadata at this as-of date."
        if row.lifecycle is not None:
            lifecycle_note = (
                f"Tracking metadata: {row.lifecycle.state} effective {row.lifecycle.effective_date.isoformat()}."
            )
            if row.lifecycle.state == "closed":
                residual = (
                    _money(direction * row.closure_residual_debit_minor)
                    if row.closure_residual_debit_minor is not None
                    else "unavailable"
                )
                lifecycle_note += (
                    f" Recorded journal residual at {row.closure_residual_date}: {residual}. "
                    + ("The opening-based residual is unknown. " if row.closure_residual_unknown else "")
                    + "Closing tracking does not zero journals or prove settlement."
                )
        details = (
            f"Tracking scope: {scope_label}; opening origin: {origin_label}. "
            f"Opening: {opening}; {_AccountPositionModel.OPENING_STATES[row.opening_status].lower()}. "
            f"Latest source activity date: {latest_activity}. "
            f"{row.pending_activity_rows} pending source row(s) across all dates; "
            f"{row.excluded_unreviewed_entries} unreviewed journal entry(s) excluded through the as-of date. "
            f"Evidence / coverage limits: {limits or 'none identified'}. "
            f"Latest saved cutoff: {latest_saved}; saved cutoff matching current inputs: {current_saved}. "
            "The live check is computed now and is not a saved reconciliation cutoff. "
            "History includes original, reversal and replacement entries as the reviewed books stand now. "
            + value_note
            + " "
            + lifecycle_note
        )
        self.position_details.setText(details)
        self.position_details.setToolTip(details + "\n" + _dated_value_note(row, full_reference=True))

    def _review_selected_account(self) -> None:
        self._open_selected_account_review()

    def _review_selected_source_values(self) -> None:
        self._open_selected_account_review("source_values")

    def _open_selected_account_review(self, initial_tab: str | None = None) -> None:
        index = self.positions_table.currentIndex()
        if not index.isValid() or self.positions_report is None or index.row() >= len(self.positions_model.rows):
            return
        from parsetrail.gui.v2_account_anchors import V2AccountAnchors

        options = {"initial_tab": initial_tab} if initial_tab is not None else {}
        V2AccountAnchors(self.profile, self.positions_model.rows[index.row()].account_id, self, **options).exec()
        self._refresh_all_reports()

    def _clear_unavailable_reports(self, exc: Exception) -> None:
        """A shared profile failure invalidates every previously displayed total."""
        self.report_error = f"Reviewed reports are unavailable: {exc}"
        self.budget_error = f"Monthly budgets are unavailable: {exc}"
        self.positions_error = str(exc)
        self.spending_report = self.income_report = self.account_report = None
        self.budget_report = self.positions_report = None
        for model in (
            self.model,
            self.income_model,
            self.account_model,
            self.budget_model,
            self.positions_model,
            self.history_model,
        ):
            model.replace(())
        self.position_details.setText("Account positions are unavailable. Refresh to retry.")
        self.position_details.setToolTip("")
        self.account_anchor_button.setEnabled(False)
        self.source_value_button.setEnabled(False)
        self.history_title.setText("Reviewed accounting history")
        self.export_button.setEnabled(False)

    def refresh(self, *_args) -> None:
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                start, end = self.start.date().toPython(), self.end.date().toPython()
                self.spending_report = store.reviewed_category_summary(kind="expense", start=start, end=end)
                self.income_report = store.reviewed_category_summary(kind="income", start=start, end=end)
                self.account_report = store.financial_journal_summary(start=start, end=end)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            invalid_period = str(exc) == "report_period_invalid"
            self.report_error = (
                "Choose an end date after the start date."
                if invalid_period
                else f"Reviewed reports are unavailable: {exc}"
            )
            self.model.replace(())
            self.income_model.replace(())
            self.account_model.replace(())
            self.spending_report = None
            self.income_report = None
            self.account_report = None
            if not invalid_period:
                self._clear_unavailable_reports(exc)
            self.export_button.setEnabled(False)
            self._show_selected_tab()
            return
        self.report_error = None
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
        show_path_notice(
            self,
            "Reviewed export saved",
            f"Saved {len(report.entries)} active reviewed entries.",
            saved,
            "The workbook includes posting lines, source allocations, corrections and coverage notes. "
            "It contains financial data and is not encrypted by ParseTrail.",
        )

    def _refresh_budget(self, *_args) -> None:
        selected = self.budget_month.date()
        month = date(selected.year(), selected.month(), 1)
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                self.budget_report = store.monthly_budget_summary(month)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self._clear_unavailable_reports(exc)
            self._show_selected_tab()
            return
        self.budget_error = None
        self.budget_model.replace(self.budget_report.categories)
        self._show_selected_tab()

    def _show_selected_tab(self, *_args) -> None:
        self._update_inspect_button()
        if self.tabs.currentIndex() == 4:
            positions = self.positions_report
            if positions is None:
                self.total.setText("Account positions are unavailable. Refresh positions to retry.")
                self.scope.setText(self.positions_error or "")
                return
            self.total.setText(
                f"As of {positions.as_of.isoformat()} (inclusive), {positions.currency}. "
                f"Transfer clearing recorded total: {_money(positions.transfer_clearing_debit_minor)}. "
                "A nonzero clearing total can represent a transfer between source posting dates."
            )
            self.scope.setText(
                f"Across the whole profile and all dates, {positions.activity_rows_without_full_allocation} "
                f"activity source row(s) from {positions.sources_with_incomplete_activity} source(s) lack a full "
                f"ledger allocation; {positions.unbound_activity_rows} activity row(s) have no account binding. "
                "Pending counts are conservative and may include supporting repeats. "
                "Latest source dates do not establish complete coverage or current balances. "
                "Opening-based journal positions remain subject to pending activity, source capture and coverage limits. "
                "These are reviewed books, not certified bank balances or complete net worth."
            )
            return
        if self.tabs.currentIndex() == 2:
            budget = self.budget_report
            if budget is None:
                self.total.setText(self.budget_error or "Monthly budgets are unavailable.")
                self.scope.clear()
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
                self.total.setText(self.report_error or "Choose an end date after the start date.")
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
            self.total.setText(self.report_error or "Choose an end date after the start date.")
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

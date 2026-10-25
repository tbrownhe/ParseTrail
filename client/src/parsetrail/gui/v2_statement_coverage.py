"""Read-only printed statement-period inventory for explicitly bound accounts."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.source_evidence import MoneyValue
from parsetrail.core.v2_profile_store import (
    EarliestSourceOpening,
    StatementCoverageRow,
    StatementJournalComparison,
    V2ProfileStore,
)
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview, _money


def _balance(value: MoneyValue | None) -> str:
    if value is None or value.provenance == "unknown":
        return "Unknown"
    if value.provenance == "observed":
        return value.raw or "Unknown"
    return f"Derived {_money(value.minor)}" if value.minor is not None else "Unknown"


class _CoverageModel(QAbstractTableModel):
    HEADERS = (
        "Financial account",
        "Source period",
        "Compared with known periods",
        "Opening",
        "Closing",
        "Scope",
        "Balance equation",
        "Page capture",
        "Printed endpoint comparison",
        "Source",
    )
    RELATIONS = {
        "first_known": "First known period",
        "adjacent": "Adjacent dates",
        "overlap": "Overlapping dates",
        "gap": "Calendar gap",
        "unknown_start": "Unknown start",
    }
    ENDPOINTS = {
        "not_adjacent": "Not compared",
        "unavailable": "Observed values unavailable",
        "ambiguous_prior": "Multiple prior endpoints",
        "same": "Same printed amount",
        "different": "Different printed amounts",
    }

    def __init__(self, rows: tuple[StatementCoverageRow, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

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
            row.account_name,
            f"{row.period_start.isoformat() if row.period_start else 'Unknown'} to {row.period_end.isoformat()}",
            self.RELATIONS[row.relation_to_known_periods],
            _balance(row.opening),
            _balance(row.closing),
            row.balance_scope.replace("_", " "),
            "Passed" if row.independent_balance_verified else "Not independently verified",
            "Verified" if row.capture_verified else "Incomplete",
            self.ENDPOINTS[row.endpoint_comparison],
            row.source_sha256[:16],
        )
        if role == Qt.ToolTipRole:
            return (
                f"Source: {row.source_sha256}\nParser: {row.parser_id}\n"
                f"Period start: {row.period_start_provenance}; end: {row.period_end_provenance}\n"
                f"Compared closing source: {row.compared_source_sha256 or 'None'}"
            )
        return values[index.column()]


class _OpeningModel(QAbstractTableModel):
    HEADERS = (
        "Financial account",
        "Class",
        "Earliest known start",
        "Bound sections",
        "Printed opening candidate",
        "Review needed",
        "Sources considered",
    )
    BLOCKERS = {
        "no_bound_statement": "No bound statement",
        "unknown_source_period": "Unknown source period",
        "non_account_total_scope": "Not an account-total balance",
        "printed_opening_unavailable": "Printed opening unavailable",
        "conflicting_earliest_openings": "Conflicting printed openings",
        "duplicate_earliest_source_sections": "Multiple earliest sections from one source",
        "source_timing_unreviewed": "Source timing unreviewed",
    }

    def __init__(self, rows: tuple[EarliestSourceOpening, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

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
        natural_sign = 1 if row.account_kind == "asset" else -1
        values = (
            row.account_name,
            row.account_kind.title(),
            row.earliest_period_start.isoformat() if row.earliest_period_start else "Unknown",
            str(row.bound_statement_sections),
            _money(row.printed_opening_minor * natural_sign)
            if row.printed_opening_minor is not None
            else "Unavailable",
            ", ".join(self.BLOCKERS[blocker] for blocker in row.blockers),
            ", ".join(source[:12] for source in row.earliest_source_ids),
        )
        if role == Qt.ToolTipRole:
            return (
                f"Account ID: {row.account_id}\n"
                f"Source IDs considered: {', '.join(row.earliest_source_ids) or 'None'}\n"
                f"Review codes: {', '.join(row.blockers)}"
            )
        return values[index.column()]


class _JournalComparisonModel(QAbstractTableModel):
    HEADERS = (
        "Financial account",
        "Source period",
        "Printed change",
        "Source activity",
        "Journal change",
        "Journal minus printed",
        "Unallocated rows",
        "Unallocated amount",
        "Allocations outside period",
        "Other postings",
        "Comparison status",
        "Source",
    )

    def __init__(self, rows: tuple[StatementJournalComparison, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

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
        natural = 1 if row.account_kind == "asset" else -1
        values = (
            row.account_name,
            f"{row.period_start.isoformat() if row.period_start else 'Unknown'} to {row.period_end.isoformat()}",
            _money(row.printed_change_minor * natural) if row.printed_change_minor is not None else "Unavailable",
            _money(row.source_activity_change_minor * natural)
            if row.source_activity_change_minor is not None
            else "Unavailable",
            _money(row.journal_change_minor * natural) if row.journal_change_minor is not None else "Unavailable",
            _money(row.difference_minor * natural) if row.difference_minor is not None else "Unavailable",
            str(row.unallocated_rows),
            _money(row.unallocated_magnitude_minor),
            str(row.allocations_outside_period),
            str(row.outside_postings),
            row.status,
            row.source_sha256[:16],
        )
        if role == Qt.ToolTipRole:
            return (
                f"Source: {row.source_sha256}\nAccount: {row.account_id} ({row.account_kind})\n"
                f"{row.activity_rows} source activity rows; unresolved amount is the sum of absolute row remainders.\n"
                "Signed changes are displayed as asset value or liability owed. This is not reconciliation certification."
            )
        return values[index.column()]


class V2StatementCoverageDialog(QDialog):
    """Show source facts and calendar relationships without reconciliation claims."""

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("2.0 statement coverage")
        self.resize(1200, 560)
        with V2ProfileStore.open(profile, read_only=True) as store:
            rows = store.statement_coverage()
            openings = store.earliest_source_openings()
            comparisons = store.statement_journal_comparisons()
            account_count = len(store.financial_accounts())
        layout = QVBoxLayout(self)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self.profile_path = QLineEdit(str(profile))
        self.profile_path.setReadOnly(True)
        self.profile_path.setCursorPosition(0)
        profile_row.addWidget(self.profile_path)
        layout.addLayout(profile_row)
        bound_accounts = len({row.account_id for row in rows})
        summary = QLabel(
            f"{len(rows)} explicitly bound statement section(s) on {bound_accounts} account(s); "
            f"{account_count - bound_accounts} financial account(s) have no bound statement."
        )
        layout.addWidget(summary)
        scope = QLabel(
            "Calendar comparisons use saved, explicitly bound statements only. Source period dates may be derived; "
            "hover a row for provenance. A gap or adjacent dates do not establish missing or complete activity. "
            "Printed endpoint comparisons use observed account-total amounts on adjacent dated periods only; "
            "equal amounts do not certify reconciliation or complete coverage. "
            "Printed balances are source evidence, not posted account balances. "
            "In Saved periods, double-click a row to inspect its source."
        )
        scope.setWordWrap(True)
        layout.addWidget(scope)
        self.model = _CoverageModel(rows, self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for column in range(len(_CoverageModel.HEADERS)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._preview)
        tabs = QTabWidget()
        tabs.addTab(self.table, "Saved periods")
        opening_panel = QWidget()
        opening_layout = QVBoxLayout(opening_panel)
        opening_scope = QLabel(
            "A candidate needs matching observed account-total openings across all tied earliest sources. "
            "Asset values and liability amounts owed are shown in their natural direction. "
            "Source timing needs explicit review in Review openings. This tab is a read-only source inventory; "
            "inspect details in Saved periods and use Review openings to record a decision."
        )
        opening_scope.setWordWrap(True)
        opening_layout.addWidget(opening_scope)
        self.opening_model = _OpeningModel(openings, self)
        self.opening_table = QTableView()
        self.opening_table.setModel(self.opening_model)
        self.opening_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.opening_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for column in range(len(_OpeningModel.HEADERS)):
            self.opening_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.opening_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        opening_layout.addWidget(self.opening_table)
        tabs.addTab(opening_panel, "Printed openings")
        comparison_panel = QWidget()
        comparison_layout = QVBoxLayout(comparison_panel)
        comparison_scope = QLabel(
            "Printed and journal changes are displayed in asset-value or liability-owed direction. "
            "Unallocated amount sums absolute row remainders, so opposite pending movements do not cancel. "
            "Other postings are journal movements outside this statement's source rows. "
            "An equal change does not establish reconciliation, complete source capture or period coverage. "
            "Double-click a row to inspect the saved source."
        )
        comparison_scope.setWordWrap(True)
        comparison_layout.addWidget(comparison_scope)
        self.comparison_model = _JournalComparisonModel(comparisons, self)
        self.comparison_table = QTableView()
        self.comparison_table.setModel(self.comparison_model)
        self.comparison_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.comparison_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for column in range(len(_JournalComparisonModel.HEADERS)):
            self.comparison_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.comparison_table.horizontalHeader().setSectionResizeMode(10, QHeaderView.Stretch)
        self.comparison_table.doubleClicked.connect(self._preview_comparison)
        comparison_layout.addWidget(self.comparison_table)
        tabs.addTab(comparison_panel, "Journal comparison")
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _preview(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            saved = store.load_import(self.model.rows[index.row()].source_sha256)
        V2EvidencePreview(saved, self).exec()

    def _preview_comparison(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            saved = store.load_import(self.comparison_model.rows[index.row()].source_sha256)
        V2EvidencePreview(saved, self).exec()

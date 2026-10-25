"""Read-only printed statement-period inventory for explicitly bound accounts."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
)

from parsetrail.core.source_evidence import MoneyValue
from parsetrail.core.v2_profile_store import StatementCoverageRow, V2ProfileStore
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
        "Source",
    )
    RELATIONS = {
        "first_known": "First known period",
        "adjacent": "Adjacent dates",
        "overlap": "Overlapping dates",
        "gap": "Calendar gap",
        "unknown_start": "Unknown start",
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
            row.source_sha256[:16],
        )
        if role == Qt.ToolTipRole:
            return (
                f"Source: {row.source_sha256}\nParser: {row.parser_id}\n"
                f"Period start: {row.period_start_provenance}; end: {row.period_end_provenance}"
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
            account_count = len(store.financial_accounts())
        layout = QVBoxLayout(self)
        bound_accounts = len({row.account_id for row in rows})
        summary = QLabel(
            f"{len(rows)} explicitly bound statement section(s) on {bound_accounts} account(s); "
            f"{account_count - bound_accounts} financial account(s) have no bound statement."
        )
        layout.addWidget(summary)
        scope = QLabel(
            "Calendar comparisons use saved, explicitly bound statements only. Source period dates may be derived; "
            "hover a row for provenance. A gap or adjacent dates do not establish missing or complete activity. "
            "Printed balances are source evidence, not posted account balances. "
            "Double-click a row to inspect its source."
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
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _preview(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            saved = store.load_import(self.model.rows[index.row()].source_sha256)
        V2EvidencePreview(saved, self).exec()

"""Explicit cash-expense review for posted-date activity exports in one 2.0 profile."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from parsetrail.core.v2_profile_store import CashExpenseReviewRow, ProfileFormatError, V2ProfileStore


def _money(minor: int | None) -> str:
    if minor is None:
        return "Unknown"
    sign = "-" if minor < 0 else ""
    amount = abs(minor)
    return f"{sign}${amount // 100:,}.{amount % 100:02d}"


class _ReviewModel(QAbstractTableModel):
    HEADERS = ("Posting date", "Description", "Amount", "Financial account", "Review status")

    def __init__(self, rows: tuple[CashExpenseReviewRow, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

    def replace(self, rows: tuple[CashExpenseReviewRow, ...]) -> None:
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
            row.date or "Unknown",
            row.description or "Description not printed",
            _money(row.amount_minor),
            row.financial_account or "Not assigned",
            row.status,
        )
        return values[index.column()]


class V2CashExpenseReview(QDialog):
    """Post or recategorize a selected, source-supported asset outflow."""

    def __init__(self, profile: Path, source_sha256: str, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.source_sha256 = source_sha256
        self.setWindowTitle("2.0 cash expense review")
        self.resize(1050, 620)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Select an activity export row. Only an explicitly assigned asset outflow with a source posting date "
            "can be posted here. Other rows remain pending."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.model = _ReviewModel((), self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        layout.addWidget(self.table)
        form = QFormLayout()
        self.category = QComboBox()
        form.addRow("Expense category", self.category)
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        self.reason.setPlaceholderText("Required review or correction reason")
        form.addRow("Reason", self.reason)
        layout.addLayout(form)
        self.action_button = QPushButton("Post reviewed expense")
        self.action_button.clicked.connect(self._act)
        layout.addWidget(self.action_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _current(self) -> CashExpenseReviewRow | None:
        index = self.table.currentIndex()
        return self.model.rows[index.row()] if index.isValid() and index.row() < len(self.model.rows) else None

    def _selected(self, *_args) -> None:
        row = self._current()
        correcting = row is not None and row.entry_key is not None
        self.action_button.setText("Correct expense category" if correcting else "Post reviewed expense")
        self.action_button.setEnabled(
            row is not None and (correcting or row.status == "Ready for expense review") and self.category.count() > 0
        )
        if correcting:
            category_index = self.category.findData(row.category_id)
            if category_index >= 0:
                self.category.setCurrentIndex(category_index)
        self.status.setText(
            row.status if row is not None else f"{len(self.model.rows)} source row(s). Select one to review."
        )

    def refresh(self, selected_row_id: str | None = None) -> None:
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            rows = store.cash_expense_review_rows(self.source_sha256)
            categories = tuple(category for category in store.category_accounts() if category.kind == "expense")
        self.model.replace(rows)
        self.category.clear()
        for category in categories:
            self.category.addItem(category.name, category.id)
        if selected_row_id is not None:
            for index, row in enumerate(rows):
                if row.row_id == selected_row_id:
                    self.table.selectRow(index)
                    break
        self._selected()

    def _act(self) -> None:
        row = self._current()
        category_id = self.category.currentData()
        reason = self.reason.text().strip()
        if row is None or category_id is None or not reason:
            QMessageBox.warning(self, "Review is incomplete", "Select a row, expense category and review reason.")
            return
        correcting = row.entry_key is not None
        if correcting and category_id == row.category_id:
            QMessageBox.warning(self, "Choose another category", "A correction needs a different expense category.")
            return
        action = "Correct the posted expense" if correcting else "Post this expense"
        message = (
            f"{action}?\n\n{row.date or 'Unknown'}  {row.description}\n"
            f"{_money(row.amount_minor)}  {row.financial_account}\n"
            f"Category: {self.category.currentText()}\nReason: {reason}"
        )
        if QMessageBox.question(self, "Confirm reviewed expense", message) != QMessageBox.StandardButton.Yes:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                if correcting:
                    store.correct_reviewed_cash_expense(row.entry_key, category_id, reason=reason)
                else:
                    store.post_reviewed_cash_expense(row.row_id, category_id, reason=reason)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Expense was not saved", str(exc))
            self.refresh(selected_row_id=row.row_id)
            return
        self.reason.clear()
        self.refresh(selected_row_id=row.row_id)
        self.status.setText("Correction saved with its reversal and replacement." if correcting else "Expense posted.")

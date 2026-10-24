"""Explicit cash expense and income review for posted-date activity exports."""

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
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from parsetrail.core.v2_profile_store import CashActivityReviewRow, ProfileFormatError, V2ProfileStore


def _money(minor: int | None) -> str:
    if minor is None:
        return "Unknown"
    sign = "-" if minor < 0 else ""
    amount = abs(minor)
    return f"{sign}${amount // 100:,}.{amount % 100:02d}"


class _ReviewModel(QAbstractTableModel):
    HEADERS = ("Posting date", "Description", "Amount", "Financial account", "Review status")

    def __init__(self, rows: tuple[CashActivityReviewRow, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

    def replace(self, rows: tuple[CashActivityReviewRow, ...]) -> None:
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


class V2CashActivityReview(QDialog):
    """Post or recategorize a selected, source-supported asset movement."""

    def __init__(self, profile: Path, source_sha256: str, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.source_sha256 = source_sha256
        self.setWindowTitle("2.0 cash activity review")
        self.resize(1050, 620)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Select an activity export row assigned to an asset account with a source posting date. "
            "Classify a positive deposit as income only after confirming it is income; transfers and loan proceeds "
            "must remain pending here."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.model = _ReviewModel((), self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in (0, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        layout.addWidget(self.table)
        form = QFormLayout()
        self.category = QComboBox()
        form.addRow("Expense or income category", self.category)
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        self.reason.setPlaceholderText("Required review or correction reason")
        form.addRow("Reason", self.reason)
        layout.addLayout(form)
        self.action_button = QPushButton("Post reviewed cash activity")
        self.action_button.clicked.connect(self._act)
        layout.addWidget(self.action_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.categories = ()
        self.refresh()

    def _current(self) -> CashActivityReviewRow | None:
        index = self.table.currentIndex()
        return self.model.rows[index.row()] if index.isValid() and index.row() < len(self.model.rows) else None

    def _selected(self, *_args) -> None:
        row = self._current()
        kind = "expense" if row is not None and row.amount_minor is not None and row.amount_minor < 0 else "income"
        correcting = row is not None and row.entry_key is not None
        prior_category = row.category_id if correcting else self.category.currentData()
        self.category.clear()
        for category in self.categories:
            if category.kind == kind:
                self.category.addItem(category.name, category.id)
        if prior_category is not None:
            category_index = self.category.findData(prior_category)
            if category_index >= 0:
                self.category.setCurrentIndex(category_index)
        self.action_button.setText(f"Correct {kind} category" if correcting else f"Post reviewed {kind}")
        self.action_button.setEnabled(
            row is not None and (correcting or row.status == f"Ready for {kind} review") and self.category.count() > 0
        )
        self.status.setText(
            (row.status + (f"; add an {kind} category first" if self.category.count() == 0 else ""))
            if row is not None
            else f"{len(self.model.rows)} source row(s). Select one to review."
        )

    def refresh(self, selected_row_id: str | None = None) -> None:
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            rows = store.cash_activity_review_rows(self.source_sha256)
            self.categories = store.category_accounts()
        self.model.replace(rows)
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
        kind = "expense" if row is not None and row.amount_minor is not None and row.amount_minor < 0 else "income"
        if row is None or category_id is None or not reason:
            QMessageBox.warning(self, "Review is incomplete", "Select a row, category and review reason.")
            return
        correcting = row.entry_key is not None
        if correcting and category_id == row.category_id:
            QMessageBox.warning(self, "Choose another category", "A correction needs a different category.")
            return
        action = f"Correct the posted {kind}" if correcting else f"Post this {kind}"
        assertion = "\nI confirm this receipt is income." if kind == "income" and not correcting else ""
        message = (
            f"{action}?\n\n{row.date or 'Unknown'}  {row.description}\n"
            f"{_money(row.amount_minor)}  {row.financial_account}\n"
            f"Category: {self.category.currentText()}\nReason: {reason}{assertion}"
        )
        if QMessageBox.question(self, f"Confirm reviewed {kind}", message) != QMessageBox.StandardButton.Yes:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                if correcting:
                    store.correct_reviewed_cash_category(row.entry_key, category_id, reason=reason)
                else:
                    store.post_reviewed_cash_category(row.row_id, category_id, reason=reason)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Cash activity was not saved", str(exc))
            self.refresh(selected_row_id=row.row_id)
            return
        self.reason.clear()
        self.refresh(selected_row_id=row.row_id)
        self.status.setText(
            "Correction saved with its reversal and replacement." if correcting else f"{kind.title()} posted."
        )

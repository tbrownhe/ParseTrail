"""Explicit cash expense and income review for eligible source rows."""

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
    QHBoxLayout,
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


def _interpretation_effects(entry, row, categories, *, financial_kind: str) -> str | None:
    """Describe an exact supported entry's inverse, keeping natural account signs."""
    category = next((category for category in categories if category.id == row.category_id), None)
    if category is None:
        return None
    category_postings = [posting for posting in entry.postings if posting.account_id == category.id]
    financial_postings = [posting for posting in entry.postings if posting.account_id != category.id]
    if len(category_postings) != 1 or len(financial_postings) != 1:
        return None
    financial_sign = 1 if financial_kind == "asset" else -1
    category_sign = 1 if category.kind == "expense" else -1
    return (
        f"Accounting date: {entry.posting_date.isoformat()}\n{entry.description}\n"
        f"{row.financial_account}: {'asset value' if financial_kind == 'asset' else 'amount owed'} change "
        f"{_money(-financial_sign * financial_postings[0].amount_minor)}.\n"
        f"{category.name}: reviewed {category.kind} change {_money(-category_sign * category_postings[0].amount_minor)}.\n"
        f"Active entry: {entry.key}; original reason: {entry.reason}."
    )


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
        self.basis, self.entries, self.history = None, {}, ()
        self.setWindowTitle("2.0 cash activity review")
        self.resize(1050, 620)
        layout = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
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
        self.reason.textChanged.connect(self._update_withdraw)
        form.addRow("Reason", self.reason)
        layout.addLayout(form)
        self.action_button = QPushButton("Post reviewed cash activity")
        self.action_button.clicked.connect(self._act)
        self.withdraw_button = QPushButton("Withdraw active interpretation")
        self.withdraw_button.clicked.connect(self._withdraw)
        actions = QHBoxLayout()
        actions.addWidget(self.action_button)
        actions.addWidget(self.withdraw_button)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.history_details = QLabel()
        self.history_details.setWordWrap(True)
        self.history_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.history_details)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        reload_button = buttons.addButton("Reload saved review", QDialogButtonBox.ActionRole)
        reload_button.clicked.connect(
            lambda: self.refresh(selected_row_id=self._current().row_id if self._current() else None)
        )
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
        self._update_withdraw()

    def _update_withdraw(self, *_args) -> None:
        row = self._current()
        self.withdraw_button.setEnabled(
            row is not None
            and row.entry_key in self.entries
            and self.basis is not None
            and bool(self.reason.text().strip())
        )
        history = tuple(action for action in self.history if row and action.row_id == row.row_id)
        self.history_details.setText(
            "Retained interpretation history: "
            + "; ".join(
                f"{action.kind.replace('_', ' ')} — {action.reason} ({action.created_at} UTC)" for action in history[:3]
            )
            if history
            else ""
        )

    def refresh(self, selected_row_id: str | None = None) -> None:
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                snapshot = store.source_interpretation_snapshot(self.source_sha256, kind="cash")
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.basis, self.entries, self.history, self.categories = None, {}, (), ()
            self.model.replace(())
            self._selected()
            self.status.setText(f"Source review unavailable. Reopen or refresh the review: {exc}")
            return
        self.basis, self.entries, self.history = (
            snapshot.basis_sha256,
            {entry.key: entry for entry in snapshot.entries},
            snapshot.history,
        )
        rows, self.categories, overlaps = snapshot.rows, snapshot.categories, snapshot.overlapping_source_ids
        self.note.setText(
            "Select a row assigned to an asset account with a source posting date. "
            "Bank statement rows also need account-total scope; other statement rows stay pending. "
            "Confirm a positive receipt is income before categorizing it; transfers and loan proceeds stay pending."
            + (
                f" This statement has {len(overlaps)} possible overlapping saved source(s). Review before posting."
                if overlaps
                else ""
            )
        )
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
                    store.correct_reviewed_cash_category(
                        row.entry_key, category_id, reason=reason, expected_basis_sha256=self.basis
                    )
                else:
                    store.post_reviewed_cash_category(
                        row.row_id, category_id, reason=reason, expected_basis_sha256=self.basis
                    )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Cash activity was not saved", str(exc))
            self.refresh(selected_row_id=row.row_id)
            return
        self.reason.clear()
        self.refresh(selected_row_id=row.row_id)
        self.status.setText(
            "Correction saved with its reversal and replacement." if correcting else f"{kind.title()} posted."
        )

    def _withdraw(self) -> None:
        row, reason = self._current(), self.reason.text().strip()
        entry = self.entries.get(row.entry_key) if row else None
        if row is None or entry is None or not reason or self.basis is None:
            return
        effects = _interpretation_effects(entry, row, self.categories, financial_kind="asset")
        if effects is None:
            return
        message = (
            f"Withdraw this supported cash interpretation?\n\nInverse effects:\n{effects}\n\nReason: {reason}\n\n"
            "The active entry is reversed at its original accounting date. Original entries and allocations remain history. "
            "The immutable source row returns to pending; posting it again requires a fresh review. "
            "This withdraws an interpretation, not a bank movement."
        )
        if QMessageBox.question(self, "Confirm interpretation withdrawal", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                store.withdraw_reviewed_interpretation(entry.key, expected_basis_sha256=self.basis, reason=reason)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Interpretation was not withdrawn", str(exc))
            self.refresh(selected_row_id=row.row_id)
            return
        self.reason.clear()
        self.refresh(selected_row_id=row.row_id)
        self.status.setText(
            "The selected interpretation's withdrawal is recorded. The refreshed row shows its current posting state; "
            "original and inverse entries remain history."
        )

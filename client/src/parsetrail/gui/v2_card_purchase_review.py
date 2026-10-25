"""Explicit expense review for negative card activity and accounting-date corrections."""

from __future__ import annotations

import sqlite3
from datetime import date

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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

from parsetrail.core.v2_profile_store import CardPurchaseReviewRow, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_cash_activity_review import _money


class _CardRowsModel(QAbstractTableModel):
    HEADERS = ("Source date", "Posting candidate", "Description", "Amount", "Financial account", "Review status")

    def __init__(self, rows: tuple[CardPurchaseReviewRow, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

    def replace(self, rows: tuple[CardPurchaseReviewRow, ...]) -> None:
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
        candidate = row.posting_candidate or "Unavailable"
        if row.date_provenance == "assumed":
            candidate += " (assumed)"
        elif row.date_provenance == "derived":
            candidate += " (derived from source)"
        values = (
            row.source_date or "Unknown",
            candidate,
            row.description or "Description not printed",
            _money(row.amount_minor),
            row.financial_account or "Not assigned",
            row.status,
        )
        return values[index.column()]


class V2CardPurchaseReview(QDialog):
    """Keep card classification and date decisions explicit before journal writes."""

    def __init__(self, workspace: V2Workspace, source_sha256: str, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.source_sha256 = source_sha256
        self.setWindowTitle("2.0 card purchase review")
        self.resize(1200, 650)
        layout = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.model = _CardRowsModel((), self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        for column in (0, 1, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        layout.addWidget(self.table)
        form = QFormLayout()
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self._update_action)
        form.addRow("Expense category", self.category)
        self.accounting_date = QLineEdit()
        self.accounting_date.setPlaceholderText("YYYY-MM-DD")
        self.accounting_date.setMaxLength(10)
        self.accounting_date.textChanged.connect(self._update_action)
        form.addRow("Accounting date", self.accounting_date)
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        self.reason.setPlaceholderText("Required review or correction reason")
        form.addRow("Reason", self.reason)
        layout.addLayout(form)
        self.assumed_dates = QCheckBox("Allow best guess posting dates when a statement does not print one")
        self.assumed_dates.setChecked(workspace.preferences().allow_assumed_posting_dates)
        self.assumed_dates.toggled.connect(self._toggle_assumed_dates)
        layout.addWidget(self.assumed_dates)
        self.action_button = QPushButton("Post reviewed card expense")
        self.action_button.clicked.connect(self._act)
        layout.addWidget(self.action_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _current(self) -> CardPurchaseReviewRow | None:
        index = self.table.currentIndex()
        return self.model.rows[index.row()] if index.isValid() and index.row() < len(self.model.rows) else None

    def _selected(self, *_args) -> None:
        row = self._current()
        self.category.blockSignals(True)
        self.category.clear()
        for category in self.categories:
            if category.kind == "expense":
                self.category.addItem(category.name, category.id)
        if row is not None and row.category_id is not None:
            index = self.category.findData(row.category_id)
            if index >= 0:
                self.category.setCurrentIndex(index)
        self.category.blockSignals(False)
        self.accounting_date.blockSignals(True)
        self.accounting_date.setText((row.effective_date or row.posting_candidate or "") if row else "")
        self.accounting_date.blockSignals(False)
        self.action_button.setText("Correct card expense" if row is not None and row.entry_key else "Post card expense")
        self._update_action()

    def _update_action(self, *_args) -> None:
        row = self._current()
        selected_date = self.accounting_date.text().strip()
        try:
            valid_date = date.fromisoformat(selected_date).isoformat() == selected_date
        except ValueError:
            valid_date = False
        correction = row is not None and row.entry_key is not None
        changed = row is not None and (
            selected_date != row.effective_date or self.category.currentData() != row.category_id
        )
        ready = row is not None and (
            correction
            or row.status == "Ready for expense review"
            or (
                row.status == "Enable assumed dates or enter a corrected date"
                and selected_date != row.posting_candidate
            )
        )
        self.action_button.setEnabled(
            ready and valid_date and self.category.count() > 0 and (not correction or changed)
        )
        if row is None:
            self.status.setText(f"{len(self.model.rows)} source row(s). Select one to review.")
        else:
            self.status.setText(row.status + ("; add an expense category first" if self.category.count() == 0 else ""))

    def refresh(self, selected_row_id: str | None = None) -> None:
        with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
            rows = store.card_purchase_review_rows(self.source_sha256, preferences=self.workspace.preferences())
            self.categories = store.category_accounts()
            overlaps = store.overlapping_statement_sources(self.source_sha256)
        self.note.setText(
            "Only a negative card movement can be reviewed here as an expense. Payments, refunds, cash advances "
            "and transfers need their own interpretation and should stay pending. Printed Post dates are preferred; "
            "assumed dates need the global choice or an explicit different accounting date. "
            "A correction reverses the old entry and replaces it without changing source evidence."
            + (
                f" This statement has {len(overlaps)} possible overlapping saved source(s). Review before posting."
                if overlaps
                else ""
            )
        )
        self.model.replace(rows)
        self.assumed_dates.blockSignals(True)
        self.assumed_dates.setChecked(self.workspace.preferences().allow_assumed_posting_dates)
        self.assumed_dates.blockSignals(False)
        self.assumed_dates.setVisible(any(row.date_provenance == "assumed" for row in rows))
        if selected_row_id is not None:
            for index, row in enumerate(rows):
                if row.row_id == selected_row_id:
                    self.table.selectRow(index)
                    break
        self._selected()

    def _toggle_assumed_dates(self, enabled: bool) -> None:
        try:
            self.workspace.set_allow_assumed_posting_dates(enabled)
        except (OSError, ValueError) as exc:
            self.assumed_dates.blockSignals(True)
            self.assumed_dates.setChecked(not enabled)
            self.assumed_dates.blockSignals(False)
            QMessageBox.warning(self, "Preference was not saved", str(exc))
            return
        selected = self._current()
        self.refresh(selected_row_id=selected.row_id if selected is not None else None)

    def _act(self) -> None:
        row = self._current()
        category_id = self.category.currentData()
        reason = self.reason.text().strip()
        try:
            accounting_date = date.fromisoformat(self.accounting_date.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Review is incomplete", "Enter a valid accounting date (YYYY-MM-DD).")
            return
        if row is None or category_id is None or not reason:
            QMessageBox.warning(self, "Review is incomplete", "Select a row, expense category and review reason.")
            return
        correction = row.entry_key is not None
        message = (
            f"{'Correct' if correction else 'Post'} this reviewed card expense?\n\n"
            f"Source date: {row.source_date or 'Unknown'}\n"
            f"Posting candidate: {row.posting_candidate or 'Unavailable'}"
            f"{f' ({row.date_provenance})' if row.date_provenance else ''}\n"
            f"Accounting date: {accounting_date.isoformat()}\n"
            f"{row.description}  {_money(row.amount_minor)}  {row.financial_account}\n"
            f"Category: {self.category.currentText()}\nReason: {reason}\n\n"
            "I confirm this movement is an expense, not a transfer or cash advance."
        )
        if QMessageBox.question(self, "Confirm card expense", message) != QMessageBox.StandardButton.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                if correction:
                    store.correct_reviewed_card_purchase(
                        row.entry_key, category_id, reason=reason, accounting_date=accounting_date
                    )
                else:
                    store.post_reviewed_card_purchase(
                        row.row_id,
                        category_id,
                        reason=reason,
                        preferences=self.workspace.preferences(),
                        accounting_date=accounting_date
                        if accounting_date.isoformat() != row.posting_candidate
                        else None,
                    )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Card expense was not saved", str(exc))
            self.refresh(selected_row_id=row.row_id)
            return
        self.reason.clear()
        self.refresh(selected_row_id=row.row_id)
        self.status.setText("Correction saved with reversal and replacement." if correction else "Card expense posted.")

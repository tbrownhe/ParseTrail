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

from parsetrail.core.v2_builtin_categories import category_labels
from parsetrail.core.v2_profile_store import CashActivityReviewRow, ProfileFormatError, V2ProfileStore

PURPOSE_LABELS = {
    "expense": "Expense",
    "expense_refund": "Expense refund",
    "income": "Income",
    "income_adjustment": "Income adjustment",
}
PURPOSE_KINDS = {"expense": "expense", "expense_refund": "expense", "income": "income", "income_adjustment": "income"}
PURPOSE_ASSERTIONS = {
    "expense": "I confirm this movement is an expense.",
    "expense_refund": "I confirm this is a refund of an expense; it reduces reviewed spending.",
    "income": "I confirm this receipt is income.",
    "income_adjustment": "I confirm this is an income adjustment; it reduces reviewed income.",
}


def _category_labels(categories):
    return category_labels((category.id, category.name, category.kind) for category in categories)


def _purpose_effects(purpose, amount_minor, *, financial_kind):
    kind = PURPOSE_KINDS[purpose]
    return (
        f"{'Asset value' if financial_kind == 'asset' else 'Liability owed'} change: "
        f"{_money(amount_minor * (1 if financial_kind == 'asset' else -1))}; "
        f"reviewed {kind} change: {_money(-amount_minor * (1 if kind == 'expense' else -1))}."
    )


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
    HEADERS = ("Posting date", "Description", "Amount", "Financial account", "Review status", "Reviewed purpose")

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
            f"{row.financial_account} ({row.tracking_scope.replace('_', ' ')})"
            if row.financial_account
            else "Not assigned",
            row.status,
            PURPOSE_LABELS.get(row.purpose, "Pending explicit review"),
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
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        layout.addWidget(self.table)
        self.source_context = QLabel()
        self.source_context.setWordWrap(True)
        self.source_context.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.source_context)
        form = QFormLayout()
        self.purpose = QComboBox()
        self.purpose.currentIndexChanged.connect(self._purpose_changed)
        form.addRow("Reviewed purpose", self.purpose)
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self._update_withdraw)
        form.addRow("Category", self.category)
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
        correcting = row is not None and row.entry_key is not None
        self.purpose.blockSignals(True)
        self.purpose.clear()
        self.purpose.addItem("Choose a purpose; amount sign does not decide it", None)
        purposes = (row.purpose,) if correcting else row.allowed_purposes if row is not None else ()
        for purpose in purposes:
            if purpose in PURPOSE_LABELS:
                self.purpose.addItem(PURPOSE_LABELS[purpose], purpose)
        self.purpose.setEnabled(row is not None and not correcting)
        if correcting:
            self.purpose.setCurrentIndex(max(0, self.purpose.findData(row.purpose)))
        self.purpose.blockSignals(False)
        self._purpose_changed()

    def _purpose_changed(self, *_args) -> None:
        row = self._current()
        kind = PURPOSE_KINDS.get(self.purpose.currentData())
        correcting = row is not None and row.entry_key is not None
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("Choose a category explicitly", None)
        labels = _category_labels(self.categories)
        for category in self.categories:
            if category.kind == kind:
                self.category.addItem(labels[category.id], category.id)
        if correcting:
            category_index = self.category.findData(row.category_id)
            if category_index >= 0:
                self.category.setCurrentIndex(category_index)
        self.category.blockSignals(False)
        self._update_withdraw()

    def _update_withdraw(self, *_args) -> None:
        row = self._current()
        self.source_context.setText(
            f"Reviewed account scope: {(row.tracking_scope or 'unavailable until account assignment').replace('_', ' ')}. "
            + (
                f"Source description: {row.description}."
                if row.source_description_known
                else f"Source description unavailable / unknown; evidence remains unchanged. Code-owned accounting label only: {row.accounting_description}. No interest, contribution or investment purpose is inferred."
            )
            if row is not None
            else "Select a source row to inspect its description provenance and account scope."
        )
        purpose = self.purpose.currentData()
        correcting = row is not None and row.entry_key is not None
        label = PURPOSE_LABELS.get(purpose, "purpose")
        self.action_button.setText(
            f"Correct {label.lower()} category" if correcting else f"Post reviewed {label.lower()}"
        )
        self.action_button.setEnabled(
            bool(
                row is not None
                and (correcting or row.status == "Ready for purpose review")
                and purpose in PURPOSE_KINDS
                and self.category.currentData() is not None
                and (not correcting or (purpose == row.purpose and self.category.currentData() != row.category_id))
                and self.basis is not None
                and self.reason.text().strip()
            )
        )
        self.status.setText(
            row.status
            + (
                "; purpose and category class are retained; withdraw and freshly review to change purpose"
                if correcting
                else "; choose a purpose explicitly; transfers use their own review"
                if purpose is None
                else f"; add an {PURPOSE_KINDS[purpose]} category first"
                if self.category.count() == 1
                else ""
            )
            if row
            else f"{len(self.model.rows)} source row(s). Select one to review."
        )
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
            "Supported bank statements use account-total scope; the admitted HealthEquity cash section uses asset cash-component scope only. "
            "Choose expense, expense refund, income or income adjustment explicitly when supported. Amount signs do not establish purpose. "
            "HSA contributions, medical spending and investment movements are never inferred. Cash-component review does not review the whole HSA or portfolio. "
            "Owned transfers, card repayments and loan proceeds require their own supported review; leave unsupported movements pending."
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
        purpose = self.purpose.currentData()
        if (
            row is None
            or category_id is None
            or purpose not in PURPOSE_KINDS
            or not reason
            or not self.action_button.isEnabled()
        ):
            return
        label = PURPOSE_LABELS[purpose].lower()
        correcting = row.entry_key is not None
        if correcting and category_id == row.category_id:
            QMessageBox.warning(self, "Choose another category", "A correction needs a different category.")
            return
        action = f"Correct the posted {label} category, preserving purpose" if correcting else f"Post this {label}"
        effects = _purpose_effects(purpose, row.amount_minor, financial_kind="asset")
        effects = (
            "Replacement entry effects only:\n"
            + effects
            + "\nThe previous entry is reversed at its original accounting date. "
            + f"This category-only correction adds $0.00 net account movement and leaves total reviewed {PURPOSE_KINDS[purpose]} unchanged. "
            + "It reallocates the category amount; no second money movement is recorded."
            if correcting
            else "New entry effects:\n" + effects
        )
        message = (
            f"{action}?\n\n{row.date or 'Unknown'}  {row.description if row.source_description_known else 'Source description unavailable / unknown'}\n"
            f"{_money(row.amount_minor)}  {row.financial_account}\n"
            f"Account scope: {row.tracking_scope.replace('_', ' ')}. "
            + (
                "Only this cash component is reviewed; the whole HSA and investment portfolio remain outside this review. "
                if row.tracking_scope == "cash_component"
                else ""
            )
            + (
                f"\nCode-owned accounting label only: {row.accounting_description}; this does not supply missing printed source text.\n"
                if not row.source_description_known
                else "\n"
            )
            + f"Purpose: {PURPOSE_LABELS[purpose]}\nCategory: {self.category.currentText()}\nReason: {reason}\n"
            f"{effects}\n"
            f"{PURPOSE_ASSERTIONS[purpose]} Owned transfers and card repayments use a separate review."
        )
        if QMessageBox.question(self, f"Confirm reviewed {label}", message) != QMessageBox.StandardButton.Yes:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                if correcting:
                    store.correct_reviewed_cash_category(
                        row.entry_key, category_id, reason=reason, expected_basis_sha256=self.basis
                    )
                else:
                    store.post_reviewed_cash_category(
                        row.row_id, category_id, purpose=purpose, reason=reason, expected_basis_sha256=self.basis
                    )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Cash activity was not saved", str(exc))
            self.refresh(selected_row_id=row.row_id)
            return
        self.reason.clear()
        self.refresh(selected_row_id=row.row_id)
        self.status.setText(
            "Correction saved with its reversal and replacement; purpose retained."
            if correcting
            else f"{label.title()} posted."
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

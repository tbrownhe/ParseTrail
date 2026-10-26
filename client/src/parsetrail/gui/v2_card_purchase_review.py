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
    QHBoxLayout,
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
from parsetrail.gui.v2_cash_activity_review import (
    PURPOSE_ASSERTIONS,
    PURPOSE_KINDS,
    PURPOSE_LABELS,
    _category_labels,
    _interpretation_effects,
    _money,
    _purpose_effects,
)
from parsetrail.gui.v2_evidence_preview import preview_saved_source


class _CardRowsModel(QAbstractTableModel):
    HEADERS = (
        "Source date",
        "Posting candidate",
        "Description",
        "Amount",
        "Financial account",
        "Review status",
        "Reviewed purpose",
    )

    def __init__(self, rows: tuple[CardPurchaseReviewRow, ...], parent=None, *, register_mode=False):
        super().__init__(parent)
        self.rows = rows
        self.register_mode = register_mode
        if register_mode:
            self.HEADERS = ("Transaction date", "Source posting date", *self.HEADERS[2:])

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
        candidate = (row.posting_date if self.register_mode else row.posting_candidate) or "Unavailable"
        provenance = row.posting_date_provenance if self.register_mode else row.date_provenance
        if provenance == "assumed":
            candidate += " (assumed)"
        elif provenance == "derived":
            candidate += " (derived from source)"
        values = (
            (row.transaction_date.isoformat() if row.transaction_date else "Unknown")
            if self.register_mode
            else row.source_date or "Unknown",
            candidate,
            row.description or "Description not printed",
            _money(row.amount_minor),
            _register_identity(row) if self.register_mode else row.financial_account or "Not assigned",
            row.status,
            PURPOSE_LABELS.get(row.purpose, "Pending explicit review"),
        )
        return values[index.column()]


def _register_identity(row):
    return (
        f"{row.financial_account or 'Not assigned'} ({row.financial_account_kind or 'kind unavailable'}, "
        f"{(row.tracking_scope or 'scope unavailable').replace('_', ' ')}, ID {row.financial_account_id or 'unassigned'})"
    )


class V2CardPurchaseReview(QDialog):
    """Keep card classification and date decisions explicit before journal writes."""

    def __init__(self, workspace: V2Workspace, source_sha256: str, parent=None, *, register_mode=False):
        super().__init__(parent)
        self.workspace = workspace
        self.source_sha256 = source_sha256
        self.register_mode = register_mode
        self.review_label = "register" if register_mode else "card"
        self.basis, self.entries, self.history, self.categories = None, {}, (), ()
        self.review_preferences = workspace.preferences()
        self.setWindowTitle(
            "2.0 account-total liability register review" if register_mode else "2.0 card category purpose review"
        )
        self.resize(1200, 650)
        layout = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.PlainText)
        layout.addWidget(self.note)
        self.model = _CardRowsModel((), self, register_mode=register_mode)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        for column in (0, 1, 3, 4, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        layout.addWidget(self.table)
        self.source_context = QLabel()
        self.source_context.setWordWrap(True)
        self.source_context.setTextFormat(Qt.PlainText)
        self.source_context.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.source_context.setVisible(register_mode)
        layout.addWidget(self.source_context)
        form = QFormLayout()
        self.purpose = QComboBox()
        self.purpose.currentIndexChanged.connect(self._purpose_changed)
        form.addRow("Reviewed purpose", self.purpose)
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self._update_action)
        form.addRow("Category", self.category)
        self.accounting_date = QLineEdit()
        self.accounting_date.setPlaceholderText("YYYY-MM-DD")
        self.accounting_date.setMaxLength(10)
        self.accounting_date.setReadOnly(register_mode)
        self.accounting_date.textChanged.connect(self._update_action)
        form.addRow("Accounting date", self.accounting_date)
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        self.reason.setPlaceholderText("Required review or correction reason")
        self.reason.textChanged.connect(self._update_action)
        self.reason.textChanged.connect(self._update_action)
        form.addRow("Reason", self.reason)
        layout.addLayout(form)
        self.assumed_dates = QCheckBox("Allow best guess posting dates when a statement does not print one")
        self.assumed_dates.setChecked(workspace.preferences().allow_assumed_posting_dates)
        self.assumed_dates.setEnabled(not register_mode)
        self.assumed_dates.toggled.connect(self._toggle_assumed_dates)
        layout.addWidget(self.assumed_dates)
        self.action_button = QPushButton("Post reviewed card expense")
        self.action_button.clicked.connect(self._act)
        self.withdraw_button = QPushButton("Withdraw active interpretation")
        self.withdraw_button.clicked.connect(self._withdraw)
        actions = QHBoxLayout()
        actions.addWidget(self.action_button)
        actions.addWidget(self.withdraw_button)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        self.history_details = QLabel()
        self.history_details.setWordWrap(True)
        self.history_details.setTextFormat(Qt.PlainText)
        self.history_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.history_details)
        self.preview_source_button = QPushButton("Open immutable register source")
        self.preview_source_button.setVisible(register_mode)
        self.preview_source_button.clicked.connect(self._preview_source)
        layout.addWidget(self.preview_source_button)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        reload_button = buttons.addButton("Reload saved review", QDialogButtonBox.ActionRole)
        reload_button.clicked.connect(
            lambda: self.refresh(selected_row_id=self._current().row_id if self._current() else None)
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _current(self) -> CardPurchaseReviewRow | None:
        index = self.table.currentIndex()
        return self.model.rows[index.row()] if index.isValid() and index.row() < len(self.model.rows) else None

    def _selected(self, *_args) -> None:
        row = self._current()
        correcting = row is not None and row.entry_key is not None
        self.purpose.blockSignals(True)
        self.purpose.clear()
        self.purpose.addItem("Choose a purpose; a credit is not necessarily a refund", None)
        purposes = (row.purpose,) if correcting else row.allowed_purposes if row is not None else ()
        for purpose in purposes:
            if purpose in PURPOSE_LABELS:
                self.purpose.addItem(PURPOSE_LABELS[purpose], purpose)
        self.purpose.setEnabled(row is not None and not correcting)
        if correcting:
            self.purpose.setCurrentIndex(max(0, self.purpose.findData(row.purpose)))
        self.purpose.blockSignals(False)
        self._purpose_changed()
        self.accounting_date.blockSignals(True)
        self.accounting_date.setText((row.effective_date or self._posting_candidate(row) or "") if row else "")
        self.accounting_date.blockSignals(False)
        self._update_action()

    def _purpose_changed(self, *_args) -> None:
        row = self._current()
        kind = PURPOSE_KINDS.get(self.purpose.currentData())
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("Choose a category explicitly", None)
        labels = _category_labels(self.categories)
        for category in self.categories:
            if category.kind == kind:
                self.category.addItem(labels[category.id], category.id)
        if row is not None and row.category_id is not None:
            index = self.category.findData(row.category_id)
            if index >= 0:
                self.category.setCurrentIndex(index)
        self.category.blockSignals(False)
        self._update_action()

    def _update_action(self, *_args) -> None:
        row = self._current()
        selected_date = self.accounting_date.text().strip()
        try:
            valid_date = date.fromisoformat(selected_date).isoformat() == selected_date
        except ValueError:
            valid_date = False
        correction = row is not None and row.entry_key is not None
        purpose = self.purpose.currentData()
        label = PURPOSE_LABELS.get(purpose, "purpose").lower()
        self.action_button.setText(
            f"Correct {self.review_label} {label}" if correction else f"Post {self.review_label} {label}"
        )
        if self.register_mode:
            self.source_context.setText(
                f"{_register_identity(row)}. Transaction date: {row.transaction_date.isoformat() if row.transaction_date else 'unavailable'} "
                f"({row.transaction_date_provenance or 'unknown'}); source posting date: {row.posting_date or 'unavailable'} "
                f"({row.posting_date_provenance or 'unknown'}). Whole liability effect only; principal/interest breakdown is unavailable and is not inferred."
                if row
                else "Select a register row. Account kind/scope and both source dates remain unavailable until selection."
            )
        changed = row is not None and (
            selected_date != row.effective_date or self.category.currentData() != row.category_id
        )
        ready = row is not None and (
            correction
            or row.status == "Ready for purpose review"
            or (
                row.status == "Enable assumed dates or enter a corrected date"
                and selected_date != self._posting_candidate(row)
            )
        )
        self.action_button.setEnabled(
            ready
            and valid_date
            and (not self.register_mode or selected_date == self._posting_candidate(row))
            and purpose in PURPOSE_KINDS
            and self.category.currentData() is not None
            and (not correction or purpose == row.purpose)
            and (not correction or changed)
            and self.basis is not None
            and bool(self.reason.text().strip())
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
        if row is None:
            self.status.setText(f"{len(self.model.rows)} source row(s). Select one to review.")
        else:
            self.status.setText(
                row.status
                + (
                    "; purpose and category class are retained; withdraw and freshly review to change purpose"
                    if correction
                    else "; choose purpose explicitly; owned card and loan-register repayments use transfer review"
                    if purpose is None
                    else f"; add an {PURPOSE_KINDS[purpose]} category first"
                    if self.category.count() == 1
                    else ""
                )
            )

    def refresh(self, selected_row_id: str | None = None) -> None:
        if self.register_mode:
            self.reason.clear()
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                snapshot = store.source_interpretation_snapshot(
                    self.source_sha256,
                    kind="register" if self.register_mode else "card",
                    preferences=None if self.register_mode else self.workspace.preferences(),
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.basis, self.entries, self.history, self.categories = None, {}, (), ()
            self.model.replace(())
            self._selected()
            self.preview_source_button.setEnabled(False)
            self.status.setText(
                "Register source or retained interpretation history could not be verified. Reopen or refresh before another action."
                if self.register_mode
                else f"Source review unavailable. Reopen or refresh the review: {exc}"
            )
            return
        self.basis, self.entries, self.history = (
            snapshot.basis_sha256,
            {entry.key: entry for entry in snapshot.entries},
            snapshot.history,
        )
        self.review_preferences = snapshot.preferences
        self.preview_source_button.setEnabled(True)
        rows, self.categories, overlaps = snapshot.rows, snapshot.categories, snapshot.overlapping_source_ids
        self.note.setText(
            "Only the admitted Yamaha account-total liability register is supported here. Select purpose and category explicitly; a positive credit is not automatically a refund or repayment. "
            "Owned card and loan-register repayments use transfer review and create no second expense. "
            "Transaction and posting dates are retained independently; printed-derived posting dates are fixed here and need no assumed-date preference. "
            "Whole liability effects do not establish principal/interest components. Category correction retains date, purpose and class; withdrawal permits fresh review."
            if self.register_mode
            else "Choose expense, expense refund, income or income adjustment explicitly when supported. "
            "A card credit does not establish a refund; owned card payments, transfers and cash advances require their own supported review. "
            "Amount signs do not establish purpose. Printed Post dates are preferred; "
            "assumed dates need the global choice or an explicit different accounting date. "
            "A correction reverses the old entry and replaces it without changing source evidence."
            + (
                f" This statement has {len(overlaps)} possible overlapping saved source(s). Review before posting."
                if overlaps
                else ""
            )
        )
        if self.register_mode and overlaps:
            self.note.setText(
                self.note.text()
                + f" This statement has {len(overlaps)} possible overlapping saved source(s); review occurrence guards before posting."
            )
        self.model.replace(rows)
        self.assumed_dates.blockSignals(True)
        self.assumed_dates.setChecked(
            False if self.register_mode else self.review_preferences.allow_assumed_posting_dates
        )
        self.assumed_dates.blockSignals(False)
        self.assumed_dates.setVisible(not self.register_mode and any(row.date_provenance == "assumed" for row in rows))
        if selected_row_id is not None:
            for index, row in enumerate(rows):
                if row.row_id == selected_row_id:
                    self.table.selectRow(index)
                    break
        self._selected()

    def _toggle_assumed_dates(self, enabled: bool) -> None:
        if self.register_mode:
            return
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
        purpose = self.purpose.currentData()
        reason = self.reason.text().strip()
        try:
            accounting_date = date.fromisoformat(self.accounting_date.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Review is incomplete", "Enter a valid accounting date (YYYY-MM-DD).")
            return
        if (
            row is None
            or category_id is None
            or purpose not in PURPOSE_KINDS
            or not reason
            or not self.action_button.isEnabled()
        ):
            return
        correction = row.entry_key is not None
        label = PURPOSE_LABELS[purpose].lower()
        effects = _purpose_effects(purpose, row.amount_minor, financial_kind="liability")
        if correction:
            if accounting_date.isoformat() != row.effective_date:
                correction_effects = (
                    f"The previous entry is reversed at its original accounting date ({row.effective_date}); "
                    f"the replacement is dated {accounting_date.isoformat()}. "
                    f"Across both dates, the inverse and replacement add $0.00 net account movement and leave total reviewed {PURPOSE_KINDS[purpose]} unchanged. "
                    "Individual dates and periods are restated; no second money movement is recorded."
                )
            else:
                correction_effects = (
                    "The previous entry is reversed at its original accounting date. "
                    f"This category-only correction adds $0.00 net account movement and leaves total reviewed {PURPOSE_KINDS[purpose]} unchanged. "
                    "It reallocates the category amount; no second money movement is recorded."
                )
            effects = "Replacement entry effects only:\n" + effects + "\n" + correction_effects
        else:
            effects = "New entry effects:\n" + effects
        message = (
            f"{'Correct, retaining purpose,' if correction else 'Post'} this reviewed {self.review_label} {label}?\n\n"
            + (
                f"Source transaction date: {row.transaction_date.isoformat() if row.transaction_date else 'Unknown'} ({row.transaction_date_provenance or 'unknown'})\n"
                if self.register_mode
                else f"Source date: {row.source_date or 'Unknown'}\n"
            )
            + f"Posting candidate: {self._posting_candidate(row) or 'Unavailable'}"
            f"{f' ({self._date_provenance(row)})' if self._date_provenance(row) else ''}\n"
            f"Accounting date: {accounting_date.isoformat()}\n"
            f"{row.description}  {_money(row.amount_minor)}  {row.financial_account}\n"
            f"Purpose: {PURPOSE_LABELS[purpose]}\nCategory: {self.category.currentText()}\nReason: {reason}\n"
            f"{effects}\n\n"
            f"{PURPOSE_ASSERTIONS[purpose]} This is not an owned liability payment, transfer or cash advance."
        )
        if self.register_mode:
            message += "\n\n" + self.source_context.text()
        if (
            QMessageBox.question(self, f"Confirm {self.review_label} {label}", message)
            != QMessageBox.StandardButton.Yes
        ):
            return
        if not self.register_mode and self.workspace.preferences() != self.review_preferences:
            QMessageBox.warning(
                self,
                "Review preferences changed",
                "Posting-date preferences changed after this review was loaded. Inspect the refreshed row before confirming again.",
            )
            self.refresh(selected_row_id=row.row_id)
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                if self.register_mode and correction:
                    store.correct_reviewed_register_category(
                        row.entry_key, category_id, reason=reason, expected_basis_sha256=self.basis
                    )
                elif self.register_mode:
                    store.post_reviewed_register_category(
                        row.row_id, category_id, purpose=purpose, reason=reason, expected_basis_sha256=self.basis
                    )
                elif correction:
                    store.correct_reviewed_card_purchase(
                        row.entry_key,
                        category_id,
                        reason=reason,
                        accounting_date=accounting_date,
                        expected_basis_sha256=self.basis,
                    )
                else:
                    store.post_reviewed_card_purchase(
                        row.row_id,
                        category_id,
                        purpose=purpose,
                        reason=reason,
                        preferences=self.workspace.preferences(),
                        accounting_date=accounting_date
                        if accounting_date.isoformat() != row.posting_candidate
                        else None,
                        expected_basis_sha256=self.basis,
                    )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(
                self,
                f"{self.review_label.title()} interpretation was not saved",
                "The register source, assignment or saved review changed. Inspect refreshed facts before another action."
                if self.register_mode
                else str(exc),
            )
            self.refresh(selected_row_id=row.row_id)
            return
        self.reason.clear()
        self.refresh(selected_row_id=row.row_id)
        self.status.setText(
            "Correction saved with reversal and replacement; purpose retained."
            if correction
            else f"{self.review_label.title()} {label} posted."
        )

    def _withdraw(self) -> None:
        row, reason = self._current(), self.reason.text().strip()
        entry = self.entries.get(row.entry_key) if row else None
        if row is None or entry is None or not reason or self.basis is None:
            return
        effects = _interpretation_effects(entry, row, self.categories, financial_kind="liability")
        if effects is None:
            return
        message = (
            f"Withdraw this supported {self.review_label} interpretation?\n\nInverse effects:\n{effects}\n\nReason: {reason}\n\n"
            "The active entry is reversed at its recorded accounting date, including any reviewed date correction. "
            "The immutable source row returns to pending; posting it again requires a fresh review. "
            "Original entries and allocations remain history. This withdraws an interpretation, not a financial transaction."
        )
        if self.register_mode:
            message += "\n\n" + self.source_context.text()
        if QMessageBox.question(self, "Confirm interpretation withdrawal", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.withdraw_reviewed_interpretation(entry.key, expected_basis_sha256=self.basis, reason=reason)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Interpretation was not withdrawn", str(exc))
            self.refresh(selected_row_id=row.row_id)
            return
        self.reason.clear()
        self.refresh(selected_row_id=row.row_id)
        self.status.setText(
            f"The selected {self.review_label} interpretation's withdrawal is recorded. The refreshed row shows its current posting state; "
            "original and inverse entries remain history."
        )

    def _posting_candidate(self, row):
        return row.posting_date if self.register_mode else row.posting_candidate

    def _date_provenance(self, row):
        return row.posting_date_provenance if self.register_mode else row.date_provenance

    def _preview_source(self):
        if self.basis is None:
            return
        try:
            preview_saved_source(self.workspace.profile_path, self.source_sha256, parent=self).exec()
        except (ProfileFormatError, sqlite3.Error, OSError):
            self.refresh()
            self.status.setText(
                "Source preview is unavailable. Inspect the refreshed register state before another action."
            )

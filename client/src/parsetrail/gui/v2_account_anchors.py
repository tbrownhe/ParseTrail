"""Explicit manual account anchors and nonposting observations over V2 services."""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
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
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_cash_movement import cash_account_labels
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.gui.v2_cash_activity_review import _money


def _typed_minor(text: str) -> int:
    entered = text.strip()
    if re.fullmatch(r"-?\$?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", entered) is None:
        raise ValueError("Enter an exact USD amount with at most two decimal places.")
    unsigned = entered.lstrip("-").replace("$", "").replace(",", "")
    whole, _separator, fraction = unsigned.partition(".")
    minor = int(whole) * 100 + int(fraction.ljust(2, "0"))
    return -minor if entered.startswith("-") else minor


def _typed_date(text: str) -> date:
    entered = text.strip()
    parsed = date.fromisoformat(entered)
    if parsed.isoformat() != entered:
        raise ValueError("Use a complete YYYY-MM-DD date.")
    return parsed


class _AmountItem(QTableWidgetItem):
    def __init__(self, amount: int):
        super().__init__(_money(amount))
        self.amount = amount
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.amount < other.amount if isinstance(other, _AmountItem) else super().__lt__(other)


class V2AccountAnchors(QDialog):
    """Prompts own review; the profile service owns eligibility and transactions."""

    def __init__(self, profile: Path, account_id: str | None = None, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.snapshot = None
        self.setWindowTitle("2.0 account openings, dated values and tracking")
        self.resize(1080, 740)
        layout = QVBoxLayout(self)
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Profile:"))
        self.profile_path = QLineEdit(str(profile))
        self.profile_path.setReadOnly(True)
        self.profile_path.setCursorPosition(0)
        path_row.addWidget(self.profile_path, 1)
        self.reload = QPushButton("Reload saved state")
        self.reload.clicked.connect(self.refresh)
        path_row.addWidget(self.reload)
        layout.addLayout(path_row)
        form = QFormLayout()
        self.account = QComboBox()
        self.account.currentIndexChanged.connect(self.refresh)
        form.addRow("Financial account", self.account)
        self.scope = self._label()
        form.addRow("Reviewed scope / direction", self.scope)
        self.books = self._label()
        form.addRow("Books through today", self.books)
        layout.addLayout(form)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._opening_tab()
        self._values_tab()
        self._lifecycle_tab()
        self.status = self._label()
        layout.addWidget(self.status)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.account.blockSignals(True)
        try:
            with V2ProfileStore.open(profile, read_only=True) as store:
                accounts = store.financial_accounts()
            labels = cash_account_labels(accounts)
            for account in accounts:
                self.account.addItem(labels[account.id], account.id)
        except (ProfileFormatError, sqlite3.Error, OSError):
            pass
        if account_id is not None:
            self.account.setCurrentIndex(self.account.findData(account_id))
        self.account.blockSignals(False)
        self.refresh()

    @staticmethod
    def _label(text=""):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _field(self, placeholder, *, required=True):
        field = QLineEdit()
        field.setMaxLength(500)
        field.setPlaceholderText(placeholder)
        if required:
            field.textChanged.connect(self._update_actions)
        return field

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column in range(len(headers)):
            table.setColumnWidth(column, 125 if column < 4 else 220)
        return table

    def _panel(self, title, note):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(self._label(note))
        self.tabs.addTab(panel, title)
        return layout

    def _opening_tab(self):
        layout = self._panel(
            "Opening",
            "A manual opening is an independently reviewed starting point for missing opening information. "
            "It uses opening equity, never income or spending. It cannot skip earlier known activity or explain a later difference. "
            "Printed source review remains available in the workspace's source opening review.",
        )
        self.opening_state = self._label()
        layout.addWidget(self.opening_state)
        self.history_boundary_note = self._label()
        layout.addWidget(self.history_boundary_note)
        form = QFormLayout()
        self.opening_amount = self._field("Exact USD in the account direction shown above; zero must be typed")
        self.opening_date = self._field("Inclusive opening cutoff: YYYY-MM-DD")
        self.opening_reference = self._field(
            "Required: independent information/reference; this is not printed source evidence"
        )
        self.opening_reason = self._field("Required reason for establishment, correction or withdrawal")
        for label, field in (
            ("Manual amount", self.opening_amount),
            ("Opening cutoff", self.opening_date),
            ("Manual reference", self.opening_reference),
            ("Action reason", self.opening_reason),
        ):
            form.addRow(label, field)
        self.opening_ack = QCheckBox("I reviewed this account's financial kind, tracking scope and opening information")
        self.opening_ack.toggled.connect(self._update_actions)
        form.addRow("Explicit review", self.opening_ack)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.opening_save = QPushButton("Confirm manual opening")
        self.opening_save.clicked.connect(self._save_opening)
        self.opening_withdraw = QPushButton("Withdraw saved opening")
        self.opening_withdraw.clicked.connect(self._withdraw_opening)
        actions.addWidget(self.opening_save)
        actions.addWidget(self.opening_withdraw)
        layout.addLayout(actions)
        self.opening_history = self._table(("Revision", "Amount", "Cutoff", "Origin / state", "Scope", "Reason"))
        layout.addWidget(self.opening_history, 1)
        self.opening_details = QPlainTextEdit()
        self.opening_details.setReadOnly(True)
        self.opening_details.setPlaceholderText(
            "Select an opening revision to inspect its origin, reason and journal references."
        )
        self.opening_details.setMaximumHeight(95)
        layout.addWidget(self.opening_details)
        self.opening_history.itemSelectionChanged.connect(self._opening_selected)

    def _values_tab(self):
        layout = self._panel(
            "Dated values",
            "Manual dated values are nonposting observations. They do not replace openings, fill missing history or establish settlement. "
            "A final zero leaves residual or unknown books visible. Corrections retain the prior observation.",
        )
        form = QFormLayout()
        self.value_target = QComboBox()
        self.value_target.currentIndexChanged.connect(self._value_target_changed)
        form.addRow("Observation to record", self.value_target)
        self.value_amount = self._field("Exact USD in the account direction shown above; zero must be typed")
        self.value_date = self._field("Observation date: YYYY-MM-DD")
        self.value_reference = self._field("Required independent reference")
        self.value_reason = self._field("Required observation/correction reason")
        for label, field in (
            ("Manual amount", self.value_amount),
            ("Value date", self.value_date),
            ("Manual reference", self.value_reference),
            ("Reason", self.value_reason),
        ):
            form.addRow(label, field)
        self.value_ack = QCheckBox("I reviewed this account's financial kind, tracking scope and manual observation")
        self.value_ack.toggled.connect(self._update_actions)
        form.addRow("Explicit review", self.value_ack)
        layout.addLayout(form)
        self.value_save = QPushButton("Record manual dated value (no posting)")
        self.value_save.clicked.connect(self._save_value)
        layout.addWidget(self.value_save)
        self.value_history = self._table(
            ("Value ID", "Date", "Manual amount", "Scope", "Current / corrected", "Reference", "Reason")
        )
        self.value_history.setSortingEnabled(True)
        self.value_history.itemSelectionChanged.connect(self._value_selected)
        layout.addWidget(self.value_history, 1)
        self.value_details = QPlainTextEdit()
        self.value_details.setReadOnly(True)
        self.value_details.setPlaceholderText(
            "Select an observation to inspect its manual origin, full reference and correction history."
        )
        self.value_details.setMaximumHeight(85)
        layout.addWidget(self.value_details)

    def _lifecycle_tab(self):
        layout = self._panel(
            "Tracking closure",
            "Stopping tracking records metadata only. It does not settle a debt, invent a payment, zero the books or hide the account. "
            "All residual and unknown positions remain visible. Reopening tracking retains prior decisions.",
        )
        self.lifecycle_state = self._label()
        layout.addWidget(self.lifecycle_state)
        form = QFormLayout()
        self.lifecycle_choice = QComboBox()
        self.lifecycle_choice.addItem("Choose tracking state", None)
        self.lifecycle_choice.addItem("Closed / stop tracking", "closed")
        self.lifecycle_choice.addItem("Open / resume tracking", "open")
        self.lifecycle_choice.currentIndexChanged.connect(self._update_actions)
        self.lifecycle_date = self._field("Effective tracking date: YYYY-MM-DD")
        self.lifecycle_reason = self._field("Required reason; this does not establish financial settlement")
        form.addRow("Tracking state", self.lifecycle_choice)
        form.addRow("Effective date", self.lifecycle_date)
        form.addRow("Reason", self.lifecycle_reason)
        layout.addLayout(form)
        self.lifecycle_save = QPushButton("Record tracking decision (no posting)")
        self.lifecycle_save.clicked.connect(self._save_lifecycle)
        layout.addWidget(self.lifecycle_save)
        self.lifecycle_history = self._table(("Revision", "State", "Effective date", "Reason", "Saved at (UTC)"))
        self.lifecycle_history.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.lifecycle_history.itemSelectionChanged.connect(self._lifecycle_selected)
        layout.addWidget(self.lifecycle_history, 1)
        self.lifecycle_details = QPlainTextEdit()
        self.lifecycle_details.setReadOnly(True)
        self.lifecycle_details.setPlaceholderText(
            "Select a tracking decision to inspect its reason and retained version history."
        )
        self.lifecycle_details.setMaximumHeight(95)
        layout.addWidget(self.lifecycle_details)

    def _natural(self):
        return 1 if self.snapshot.account.kind == "asset" else -1

    def _opening_text(self, opening):
        if opening is None:
            return "Opening not established; unknown is not zero."
        if opening.state == "withdrawn":
            return f"Opening withdrawn (revision {opening.revision_id}); unknown, not zero. Prior amounts/dates remain in history."
        return (
            f"{opening.origin.title()} opening: {_money(opening.amount_minor * self._natural())} as of {opening.cutoff_date.isoformat()}; "
            f"{opening.tracking_scope.replace('_', ' ')}; revision {opening.revision_id}"
            + ("; stale source basis." if opening.stale else ".")
        )

    def refresh(self, *_args):
        self.snapshot = None
        self.history_boundary_note.setToolTip("")
        for field in (
            self.opening_amount,
            self.opening_date,
            self.opening_reference,
            self.opening_reason,
            self.value_amount,
            self.value_date,
            self.value_reference,
            self.value_reason,
            self.lifecycle_date,
            self.lifecycle_reason,
        ):
            field.clear()
        self.opening_ack.setChecked(False)
        self.value_ack.setChecked(False)
        self.lifecycle_choice.setCurrentIndex(0)
        self.value_target.blockSignals(True)
        self.value_target.clear()
        self.value_target.addItem("New manual dated observation", None)
        for table in (self.opening_history, self.value_history, self.lifecycle_history):
            table.setRowCount(0)
        for details in (self.opening_details, self.value_details, self.lifecycle_details):
            details.clear()
        account_id = self.account.currentData()
        try:
            if account_id is not None:
                with V2ProfileStore.open(self.profile, read_only=True) as store:
                    self.snapshot = store.account_anchor_snapshot(account_id, as_of=date.today())
        except (ProfileFormatError, sqlite3.Error, OSError):
            pass
        if self.snapshot is None:
            self.scope.setText("Account scope unavailable.")
            self.books.setText("Books unavailable; unknown is not zero.")
            self.opening_state.setText("Opening state unavailable.")
            self.history_boundary_note.setText("Known history boundaries unavailable.")
            self.lifecycle_state.setText("Tracking state unavailable.")
            self.status.setText(
                "Select an account, or reload after checking the profile. No saved state is available for an action."
            )
        else:
            snapshot = self.snapshot
            natural = self._natural()
            self.scope.setText(
                f"{snapshot.account.tracking_scope.replace('_', ' ')}; {snapshot.account.kind}; "
                + ("positive amount means asset value." if natural == 1 else "positive amount means liability owed.")
            )
            self.books.setText(
                f"Through {date.today().isoformat()} inclusive: recorded journal movement {_money(natural * snapshot.recorded_debit_minor)}; "
                f"opening-based journal position {_money(natural * snapshot.position_debit_minor) if snapshot.position_debit_minor is not None else 'unknown'}. "
                "Manual observations and closure do not replace these books."
            )
            earliest = snapshot.earliest_known_activity_date
            self.opening_state.setText(
                self._opening_text(snapshot.opening)
                + f" Earliest known activity: {earliest.isoformat() if earliest else 'none known; missing activity may still exist'}."
            )
            first_history = snapshot.earliest_known_history_date
            first_bounds = sorted(
                {
                    (self._boundary_label(bound.kind), bound.allows_equal)
                    for bound in snapshot.opening_boundaries
                    if bound.boundary_date == first_history
                }
            )
            self.history_boundary_note.setText(
                f"Earliest known history boundary: {first_history.isoformat()}; "
                + "; ".join(
                    f"{kind}: cutoff {'on or before' if allows_equal else 'strictly before'} this date"
                    for kind, allows_equal in first_bounds
                )
                + ". Every known boundary applies; full context is below."
                if first_history
                else "No known history boundaries; missing history may still exist."
            )
            self.history_boundary_note.setToolTip(self._boundary_details())
            self._fill_openings()
            self._fill_values()
            lifecycle = snapshot.lifecycle
            self.lifecycle_state.setText(
                f"Latest saved tracking decision: {lifecycle.state}, effective {lifecycle.effective_date.isoformat()}; reason: {lifecycle.reason}."
                if lifecycle
                else "Tracking open; no explicit lifecycle decision recorded."
            )
            self._fill_lifecycle()
            self.status.setText(
                "Review explicit dates, scope, references and reasons. Nothing is written until confirmation."
            )
        self.value_target.blockSignals(False)
        self._update_actions()

    @staticmethod
    def _put(table, rows, *, money_column=None):
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for index, values in enumerate(rows):
            for column, value in enumerate(values):
                item = (
                    _AmountItem(value)
                    if column == money_column and isinstance(value, int)
                    else QTableWidgetItem(str(value))
                )
                item.setData(Qt.UserRole, index)
                item.setToolTip(item.text())
                table.setItem(index, column, item)

    def _fill_openings(self):
        self._put(
            self.opening_history,
            [
                (
                    row.revision_id,
                    row.amount_minor * self._natural() if row.amount_minor is not None else "Unknown (withdrawn)",
                    row.cutoff_date.isoformat() if row.cutoff_date else "Not established",
                    f"{row.origin} / {row.state}",
                    row.tracking_scope.replace("_", " "),
                    row.reason,
                )
                for row in self.snapshot.opening_history
            ],
            money_column=1,
        )
        if self.opening_history.rowCount():
            self.opening_history.selectRow(0)
        else:
            self.opening_details.setPlainText(self._boundary_details())

    def _fill_values(self):
        self._put(
            self.value_history,
            [
                (
                    row.value_id,
                    row.value_date.isoformat(),
                    row.amount_minor * self._natural(),
                    row.tracking_scope.replace("_", " "),
                    f"Corrected by {row.superseded_by_value_id}"
                    if row.superseded_by_value_id is not None
                    else "Current observation",
                    row.reference,
                    row.reason,
                )
                for row in self.snapshot.dated_values
            ],
            money_column=2,
        )
        self.value_history.setSortingEnabled(True)
        if self.value_history.rowCount():
            self.value_history.selectRow(0)
        for row in self.snapshot.dated_values:
            if row.superseded_by_value_id is None:
                self.value_target.addItem(
                    f"Correct value {row.value_id}: {row.value_date.isoformat()}, {_money(row.amount_minor * self._natural())}",
                    row.value_id,
                )

    def _fill_lifecycle(self):
        self._put(
            self.lifecycle_history,
            [
                (row.revision_id, row.state, row.effective_date.isoformat(), row.reason, row.created_at)
                for row in self.snapshot.lifecycle_history
            ],
        )
        if self.lifecycle_history.rowCount():
            self.lifecycle_history.selectRow(0)

    def _selected(self, table, records):
        item = table.item(table.currentRow(), 0)
        index = item.data(Qt.UserRole) if item else None
        return records[index] if isinstance(index, int) and 0 <= index < len(records) else None

    def _opening_selected(self):
        row = self._selected(self.opening_history, self.snapshot.opening_history) if self.snapshot else None
        self.opening_details.setPlainText(
            f"Origin: {row.origin}; state: {row.state}; reference: {row.reference}.\nReason: {row.reason}\n"
            f"Journal: {row.entry_key or 'none'}; reviewed basis: {row.basis_sha256}\nVersion: {row.version}; prior: {row.prior_version or 'none'}"
            if row
            else "Select an opening revision to inspect its origin, reason and journal reference."
        )
        if self.snapshot is not None:
            self.opening_details.appendPlainText("\n" + self._boundary_details())

    @staticmethod
    def _boundary_label(kind):
        return {
            "activity": "Source activity",
            "journal": "Reviewed journal activity",
            "statement_start": "Known statement start",
            "statement_end": "Known statement end (start unknown)",
            "dated_value": "Manual dated value",
            "lifecycle": "Tracking effective date",
        }.get(kind, f"Unsupported history boundary ({kind})")

    def _boundary_details(self):
        if self.snapshot is None or not self.snapshot.opening_boundaries:
            return "No known opening-history boundaries. Missing history may still exist."
        return "Opening cutoff must satisfy every known history boundary:\n" + "\n".join(
            f"{self._boundary_label(bound.kind)}: cutoff {'on or before' if bound.allows_equal else 'strictly before'} "
            f"{bound.boundary_date.isoformat()}; reference: {bound.reference or 'not supplied'}; "
            f"source: {bound.source_sha256 or 'not a source statement'}."
            for bound in self.snapshot.opening_boundaries
        )

    def _value_selected(self):
        row = self._selected(self.value_history, self.snapshot.dated_values) if self.snapshot else None
        self.value_details.setPlainText(
            f"{row.origin.title()} nonposting observation {row.value_id}; reference: {row.reference}.\nReason: {row.reason}\n"
            f"Corrects: {row.corrects_value_id}; corrected by: {row.superseded_by_value_id}; version: {row.version}. Saved {row.created_at}."
            if row
            else "Select a manual dated value to inspect retained correction history."
        )

    def _lifecycle_selected(self):
        row = self._selected(self.lifecycle_history, self.snapshot.lifecycle_history) if self.snapshot else None
        self.lifecycle_details.setPlainText(
            f"{row.state} from {row.effective_date.isoformat()}; reason: {row.reason}.\n"
            f"Version: {row.version}; prior: {row.prior_version or 'none'}. No journal posting."
            if row
            else "Select a tracking decision to inspect its retained history."
        )

    def _value_target_changed(self, *_args):
        row = (
            next((row for row in self.snapshot.dated_values if row.value_id == self.value_target.currentData()), None)
            if self.snapshot
            else None
        )
        if row is not None:
            amount = row.amount_minor * self._natural()
            self.value_amount.setText(f"{'-' if amount < 0 else ''}{abs(amount) // 100}.{abs(amount) % 100:02}")
        else:
            self.value_amount.clear()
        self.value_date.setText(row.value_date.isoformat() if row else "")
        self.value_reference.setText(row.reference if row else "")
        self.value_reason.clear()
        self.value_ack.setChecked(False)
        self._update_actions()

    def _valid_money_date(self, amount, day):
        try:
            _typed_minor(amount.text())
            _typed_date(day.text())
        except (ValueError, ArithmeticError):
            return False
        return True

    def _update_actions(self, *_args):
        if not hasattr(self, "lifecycle_save"):
            return
        ready = self.snapshot is not None
        opening = self.snapshot.opening if ready else None
        self.opening_save.setText(
            "Replace source with manual opening"
            if opening and opening.state == "active" and opening.origin == "source"
            else "Correct manual opening"
            if opening and opening.state == "active"
            else "Establish fresh manual opening"
            if opening
            else "Confirm manual opening"
        )
        self.opening_save.setEnabled(
            bool(
                ready
                and self.opening_ack.isChecked()
                and self._valid_money_date(self.opening_amount, self.opening_date)
                and self.opening_reference.text().strip()
                and self.opening_reason.text().strip()
            )
        )
        self.opening_withdraw.setEnabled(
            bool(ready and opening and opening.state == "active" and self.opening_reason.text().strip())
        )
        self.value_save.setEnabled(
            bool(
                ready
                and self.value_ack.isChecked()
                and self._valid_money_date(self.value_amount, self.value_date)
                and self.value_reference.text().strip()
                and self.value_reason.text().strip()
            )
        )
        try:
            _typed_date(self.lifecycle_date.text())
            valid_day = True
        except ValueError:
            valid_day = False
        self.lifecycle_save.setEnabled(
            bool(ready and valid_day and self.lifecycle_choice.currentData() and self.lifecycle_reason.text().strip())
        )

    def _write(self, title, message, action):
        if QMessageBox.question(self, title, message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                action(store)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.refresh()
            explanation = {
                "account_anchor_changed_since_selection": "Account information, books or another saved review changed after selection. Review the refreshed facts.",
                "opening_decision_changed_since_selection": "The saved opening changed after selection. Review the refreshed opening and history.",
                "account_lifecycle_changed_since_selection": "The saved tracking decision changed after selection. Review the refreshed history.",
                "account_lifecycle_date_order": "The effective date cannot precede the previous tracking phase. Review the saved tracking dates and enter a date in the correct order.",
                "account_lifecycle_history_integrity": "Saved tracking history could not be verified. Check the profile before reviewing another tracking decision.",
                "account_dated_value_correction_unavailable": "That manual value has already been corrected or is no longer available for correction.",
                "opening_correction_requires_changed_basis": "The proposed opening matches the saved opening information. Enter a changed opening fact for a correction.",
                "opening_earlier_posting_conflict": "Known activity predates the proposed opening. An opening cannot skip known activity or serve as a later balancing adjustment.",
                "opening_earlier_activity_conflict": "The proposed opening conflicts with known account history. Review the dated boundaries below; an opening cannot skip history or serve as a later balancing adjustment.",
                "account_anchor_scope_mismatch": "The account tracking scope changed or does not match this review. Review the refreshed account scope.",
                "account_anchor_value_invalid": "The amount, date or manual reference is invalid or outside the supported range. Review exact USD values with at most two decimal places.",
            }.get(
                str(exc),
                "This review could not be saved. Check the date, exact amount, reference and account scope, then inspect the refreshed state.",
            )
            self.status.setText("Action was not recorded. " + explanation)
            QMessageBox.warning(self, "Account review was not saved", explanation)
            return
        self.refresh()
        self.status.setText(
            "The selected review action is recorded. Refreshed facts and history show current state; manual values and tracking decisions post no money."
        )

    def _save_opening(self):
        if not self.opening_save.isEnabled() or self.snapshot is None:
            return
        snapshot = self.snapshot
        amount = _typed_minor(self.opening_amount.text())
        cutoff = _typed_date(self.opening_date.text())
        reference, reason = self.opening_reference.text().strip(), self.opening_reason.text().strip()
        account = snapshot.account
        message = (
            f"{self.opening_save.text()} for {self.account.currentText()}?\n\n"
            f"Saved: {self._opening_text(snapshot.opening)}\n"
            f"Manual amount: {_money(amount)} ({account.kind} {'value' if account.kind == 'asset' else 'owed'}); "
            f"cutoff {cutoff.isoformat()}; scope {account.tracking_scope.replace('_', ' ')}.\nReference: {reference}\nReason: {reason}\n\n"
            "This independently reviewed opening uses opening equity, with no income or spending. Any replaced active opening is retired at its original date. "
            "Zero records an explicit decision without a replacement posting. Prior revisions remain history. This is not printed source evidence or a later balancing adjustment."
        )
        self._write(
            "Confirm manual opening",
            message,
            lambda store: store.post_reviewed_manual_opening(
                account.id,
                amount_minor=amount * (1 if account.kind == "asset" else -1),
                cutoff_date=cutoff,
                tracking_scope=account.tracking_scope,
                reference=reference,
                reason=reason,
                expected_decision_version=snapshot.opening.version if snapshot.opening else None,
                expected_basis_sha256=snapshot.basis_sha256,
            ),
        )

    def _withdraw_opening(self):
        if not self.opening_withdraw.isEnabled() or self.snapshot is None:
            return
        opening = self.snapshot.opening
        reason = self.opening_reason.text().strip()
        message = (
            f"Withdraw {self.account.currentText()}'s saved opening?\n\n{self._opening_text(opening)}\nReason: {reason}\n\n"
            "The nonzero active opening is reversed through opening equity at its original date; zero is withdrawn without postings. "
            "The opening becomes unknown, not zero. Existing activity remains. A new opening requires fresh explicit review."
        )
        self._write(
            "Confirm opening withdrawal",
            message,
            lambda store: store.withdraw_reviewed_opening(
                opening.account_id,
                expected_decision_version=opening.version,
                reason=reason,
            ),
        )

    def _save_value(self):
        if not self.value_save.isEnabled() or self.snapshot is None:
            return
        snapshot = self.snapshot
        amount, value_date = _typed_minor(self.value_amount.text()), _typed_date(self.value_date.text())
        reference, reason = self.value_reference.text().strip(), self.value_reason.text().strip()
        corrects = self.value_target.currentData()
        account = snapshot.account
        message = (
            f"Record {'correction to value ' + str(corrects) if corrects is not None else 'a new manual dated value'} "
            f"for {self.account.currentText()}?\n\n{_money(amount)} on {value_date.isoformat()}; "
            f"scope {account.tracking_scope.replace('_', ' ')}; positive {'asset value' if account.kind == 'asset' else 'liability owed'}.\n"
            f"Reference: {reference}\nReason: {reason}\n\n"
            "Manual observation only: no journal, payment or settlement is recorded. It does not replace an opening or zero residual books. Prior values remain history."
        )
        self._write(
            "Confirm manual dated value",
            message,
            lambda store: store.record_reviewed_dated_value(
                account.id,
                amount_minor=amount * (1 if account.kind == "asset" else -1),
                value_date=value_date,
                tracking_scope=account.tracking_scope,
                reference=reference,
                reason=reason,
                expected_basis_sha256=snapshot.basis_sha256,
                corrects_value_id=corrects,
            ),
        )

    def _save_lifecycle(self):
        if not self.lifecycle_save.isEnabled() or self.snapshot is None:
            return
        snapshot = self.snapshot
        state, effective = self.lifecycle_choice.currentData(), _typed_date(self.lifecycle_date.text())
        reason = self.lifecycle_reason.text().strip()
        message = (
            f"Record tracking {state} for {self.account.currentText()} from {effective.isoformat()}?\n\nReason: {reason}\n\n"
            f"{self.books.text()}\n\nTracking metadata only: no money is posted, no debt is settled and no account is hidden. Prior decisions remain history."
        )
        self._write(
            "Confirm tracking decision",
            message,
            lambda store: store.record_account_lifecycle(
                snapshot.account.id,
                state=state,
                effective_date=effective,
                reason=reason,
                expected_version=snapshot.lifecycle.version if snapshot.lifecycle else None,
                expected_basis_sha256=snapshot.basis_sha256,
            ),
        )

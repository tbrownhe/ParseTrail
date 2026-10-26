"""Explicit, versioned source-assignment correction after interpretation withdrawal."""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
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

from parsetrail.core.source_evidence import StatementPayload
from parsetrail.core.v2_profile_store import BindingCorrectionTarget, ProfileFormatError, V2ProfileStore
from parsetrail.gui.v2_cash_activity_review import _money


def _scope(target: BindingCorrectionTarget) -> str:
    if target.mode == "source":
        return f"Printed identity: {target.source_identity} ({target.source_identity_form})"
    return "Entire accountless file" if target.mode == "file" else f"Selected accountless rows ({len(target.row_ids)})"


def _assignments(account_ids, accounts) -> str:
    names = {account.id: account.name for account in accounts}
    counts = Counter(
        "Unassigned" if account_id is None else names.get(account_id, account_id) for account_id in account_ids
    )
    return (
        "; ".join(f"{name} ({count} assignment{'s' if count != 1 else ''})" for name, count in counts.items())
        or "No assignments"
    )


def ordinary_binding_lock_notice(blockers) -> str:
    messages = {
        "account_binding_has_journal_history": "This assignment has posted journal history, which locks ordinary reassignment. Withdraw active interpretations before reviewing an account correction.",
        "account_binding_has_overlap_review_history": "Saved repeated-row review history locks ordinary reassignment, including after returning a pair to pending.",
        "account_binding_has_correction_history": "Recorded account-correction history locks ordinary reassignment. Use the reviewed correction workflow for another change.",
        "account_binding_has_transfer_review_history": "Saved transfer-suggestion review history locks ordinary reassignment. Use a reviewed correction to invalidate the old suggestion context explicitly.",
        "account_binding_source_backed_opening_anchor": "Source-backed opening history locks this assignment. Opening withdrawal is a separate required workflow.",
    }
    return " ".join(messages.get(code, f"Ordinary reassignment unavailable ({code}).") for code in blockers)


def _fill(table, rows):
    table.blockSignals(True)
    table.setRowCount(len(rows))
    table.clearSelection()
    table.setCurrentCell(-1, -1)
    for index, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(index, column, item)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    table.blockSignals(False)


class V2BindingCorrection(QDialog):
    """Correction changes authored account context; it never moves old journals."""

    BLOCKERS = {
        "active_source_consumption": "Active source allocations remain. Withdraw the relevant cash/card interpretations or the whole transfer event first.",
        "source_backed_opening_anchor": "A source-backed opening decision still anchors this source/account context. Opening withdrawal is a separate workflow; this correction cannot proceed.",
        "file_mode_requires_clear": "Clear the whole-file assertion explicitly before assigning individual rows.",
        "row_mode_requires_clear": "Clear individual row assignments explicitly before asserting the whole file.",
        "binding_unchanged": "The selected assignment is unchanged. Choose a different account or Unassign.",
    }

    def __init__(self, profile: Path, target: BindingCorrectionTarget, parent=None):
        super().__init__(parent)
        self.profile, self.target = profile, target
        self.snapshot = None
        self.affected_items = ()
        self.changed = False
        self.setWindowTitle("2.0 correct reviewed account assignment")
        self.resize(1080, 700)
        layout = QVBoxLayout(self)
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Profile:"))
        self.profile_path = QLineEdit(str(profile))
        self.profile_path.setReadOnly(True)
        path_row.addWidget(self.profile_path)
        layout.addLayout(path_row)
        intro = QLabel(
            "Correct or clear a source account assignment after its active interpretations have been withdrawn. "
            "Original journals remain under their original accounts; source facts remain unchanged. "
            "Affected repeated-row decisions return to pending. This workflow posts no money."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.scope_label = QLabel(_scope(target))
        self.scope_label.setWordWrap(True)
        layout.addWidget(self.scope_label)
        self.tabs = QTabWidget()
        review = QWidget()
        review_layout = QVBoxLayout(review)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        review_layout.addWidget(self.summary)
        self.rows_table = QTableWidget(0, 4)
        self.rows_table.setHorizontalHeaderLabels(("Source date", "Description", "Amount", "Current account"))
        self.rows_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rows_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        review_layout.addWidget(self.rows_table)
        form = QFormLayout()
        self.destination = QComboBox()
        self.destination.addItem("Choose a corrected assignment", None)
        self.destination.addItem("Unassign this scope", None)
        self.destination.currentIndexChanged.connect(self._destination_changed)
        form.addRow("New assignment", self.destination)
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        self.reason.setPlaceholderText("Required reason and source context for this correction")
        self.reason.textChanged.connect(self._update_action)
        form.addRow("Reason", self.reason)
        review_layout.addLayout(form)
        self.blockers = QLabel()
        self.blockers.setWordWrap(True)
        self.blockers.setTextInteractionFlags(Qt.TextSelectableByMouse)
        review_layout.addWidget(self.blockers)
        self.save_button = QPushButton("Confirm account-assignment correction")
        self.save_button.clicked.connect(self._save)
        review_layout.addWidget(self.save_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        review_layout.addWidget(self.status)
        self.tabs.addTab(review, "Review correction")
        affected = QWidget()
        affected_layout = QVBoxLayout(affected)
        affected_note = QLabel(
            "Repeated-row relationships return to pending and historical transfer-suggestion reviews become inapplicable. "
            "Connected groups can include other sources and rows beyond the selected assignment. Current bindings and source details come "
            "from the same preview. Select a relationship for full source references."
        )
        affected_note.setWordWrap(True)
        affected_layout.addWidget(affected_note)
        self.affected_table = QTableWidget(0, 7)
        self.affected_table.setHorizontalHeaderLabels(
            (
                "Affected review",
                "Source A account / date",
                "Source A description",
                "Source A",
                "Source B account / date",
                "Source B description",
                "Source B",
            )
        )
        self.affected_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.affected_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.affected_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.affected_table.verticalHeader().setDefaultSectionSize(46)
        self.affected_table.itemSelectionChanged.connect(self._show_affected)
        affected_layout.addWidget(self.affected_table)
        self.affected_details = QPlainTextEdit()
        self.affected_details.setReadOnly(True)
        self.affected_details.setMaximumHeight(160)
        affected_layout.addWidget(self.affected_details)
        self.tabs.addTab(affected, "Affected relationships")
        history = QWidget()
        history_layout = QVBoxLayout(history)
        note = QLabel(
            "Prior/new assignments, reasons and invalidated review references remain history. Account labels below use their current display names."
        )
        note.setWordWrap(True)
        history_layout.addWidget(note)
        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(
            (
                "Scope",
                "Prior assignment",
                "New assignment",
                "Invalidated reviews",
                "Reason",
                "Saved at (UTC)",
                "Revision",
            )
        )
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.itemSelectionChanged.connect(self._show_history)
        history_layout.addWidget(self.history_table)
        self.history_details = QPlainTextEdit()
        self.history_details.setReadOnly(True)
        self.history_details.setMaximumHeight(160)
        history_layout.addWidget(self.history_details)
        self.tabs.addTab(history, "Correction history")
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        reload_button = buttons.addButton("Reload saved state", QDialogButtonBox.ActionRole)
        reload_button.clicked.connect(self.refresh)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _destination_changed(self, *_args):
        self.refresh()

    def refresh(self, *_args):
        prior_index, account_id = self.destination.currentIndex(), self.destination.currentData()
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                snapshot = store.binding_correction_snapshot(self.target, destination_account_id=account_id)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.snapshot = None
            self.affected_items = ()
            _fill(self.rows_table, ())
            _fill(self.affected_table, ())
            self.affected_details.clear()
            _fill(self.history_table, ())
            self.history_details.clear()
            self.summary.setText("Account-correction review is unavailable. Reload saved state to retry.")
            self.blockers.setText(str(exc))
            self._update_action()
            return
        self.snapshot = snapshot
        self.destination.blockSignals(True)
        self.destination.clear()
        self.destination.addItem("Choose a corrected assignment", None)
        self.destination.addItem("Unassign this scope", None)
        for account in snapshot.accounts:
            self.destination.addItem(f"{account.name} ({account.institution_key}, {account.kind})", account.id)
        self.destination.setCurrentIndex(
            1 if prior_index == 1 else max(0, self.destination.findData(account_id)) if account_id else 0
        )
        self.destination.blockSignals(False)
        self.summary.setText(
            f"Current explicit scope assignment: {_assignments(snapshot.current_account_ids, snapshot.accounts)}. "
            f"{len(snapshot.affected_row_ids)} affected source row(s); "
            f"{len(snapshot.affected_review_pairs)} repeated-row relationship(s) return to pending; "
            f"{len(snapshot.affected_transfer_review_ids)} transfer-suggestion review(s) become inapplicable. "
            "Historical journals retain their original financial accounts."
        )
        names = {account.id: account.name for account in snapshot.accounts}
        bindings = {binding.row_id: binding for binding in snapshot.current_bindings}
        payload = snapshot.evidence.payload
        rows = (
            tuple(row for account in payload.accounts for row in account.rows)
            if isinstance(payload, StatementPayload)
            else payload.rows
        )
        _fill(
            self.rows_table,
            tuple(
                (
                    row.date.iso or "Unknown",
                    row.description.text or "Not printed",
                    _money(row.amount.minor),
                    names.get(bindings[row.row_id].ledger_account_id, "Unassigned"),
                )
                for row in rows
                if row.row_id in set(snapshot.affected_row_ids)
            ),
        )
        messages = [
            self.BLOCKERS.get(blocker, f"Unsupported correction condition ({blocker})") for blocker in snapshot.blockers
        ]
        if snapshot.opening_blocker_account_ids:
            messages.append(
                "Opening anchor accounts: "
                + ", ".join(names.get(account_id, account_id) for account_id in snapshot.opening_blocker_account_ids)
            )
        self.blockers.setText(
            "\n".join(messages)
            if messages
            else "No active-consumption, opening or mode blocker identified for this selected scope and destination."
        )
        contexts = {row.row_id: row for row in snapshot.affected_review_rows}
        affected_items = [
            ("Repeated source rows", left, right, "This recorded repeated-row relationship returns to pending.")
            for left, right in snapshot.affected_review_pairs
        ]
        affected_items.extend(
            (
                "Transfer suggestion",
                review.pair.outgoing.row_id,
                review.pair.incoming.row_id,
                f"Transfer suggestion review {review.revision_id}: {review.decision}; reason: {review.reason}. "
                "Its historical context becomes inapplicable and does not automatically reactivate after reassignment back.",
            )
            for review in snapshot.affected_transfer_reviews
        )
        self.affected_items = tuple(affected_items)
        relationship_rows = []
        for label, left_id, right_id, _detail in self.affected_items:
            left, right = contexts[left_id], contexts[right_id]
            relationship_rows.append(
                (
                    label,
                    f"{left.account_name or 'Unassigned'}\n{left.source_date or 'Unknown date'}",
                    left.description or "Not printed",
                    left.source_sha256[:16],
                    f"{right.account_name or 'Unassigned'}\n{right.source_date or 'Unknown date'}",
                    right.description or "Not printed",
                    right.source_sha256[:16],
                )
            )
        _fill(self.affected_table, relationship_rows)
        for column, width in enumerate((145, 155, 175, 110, 155, 175, 110)):
            self.affected_table.setColumnWidth(column, width)
        self.affected_details.setPlainText(
            "No recorded repeat or transfer-suggestion reviews are affected."
            if not relationship_rows
            else "Select a relationship to inspect its full source references."
        )
        if relationship_rows:
            self.affected_table.selectRow(0)
        _fill(
            self.history_table,
            tuple(
                (
                    _scope(item.target),
                    _assignments(item.prior_account_ids, snapshot.accounts),
                    _assignments(item.new_account_ids, snapshot.accounts),
                    f"{len(item.invalidated_review_ids)} repeat; {len(item.invalidated_transfer_review_ids)} transfer",
                    item.reason,
                    item.created_at,
                    item.correction_id,
                )
                for item in snapshot.history
            ),
        )
        self.history_details.setPlainText(
            "No binding corrections saved for this source."
            if not snapshot.history
            else "Select a correction to inspect retained context."
        )
        if snapshot.history:
            self.history_table.selectRow(0)
        self.status.clear()
        self._update_action()

    def _update_action(self, *_args):
        self.save_button.setEnabled(
            self.snapshot is not None
            and not self.snapshot.blockers
            and self.destination.currentIndex() > 0
            and bool(self.reason.text().strip())
        )

    def _show_history(self):
        index = self.history_table.currentRow()
        if self.snapshot is not None and 0 <= index < len(self.snapshot.history):
            item = self.snapshot.history[index]
            self.history_details.setPlainText(
                f"Correction {item.correction_id}: {_scope(item.target)}\nReason: {item.reason}\n"
                f"Prior account IDs: {item.prior_account_ids}\nNew account IDs: {item.new_account_ids}\n"
                f"Invalidated repeated-row review references: {item.invalidated_review_ids}\n"
                f"Invalidated transfer-suggestion review references: {item.invalidated_transfer_review_ids}\nVersion: {item.version}"
            )

    def _show_affected(self):
        index = self.affected_table.currentRow()
        if self.snapshot is not None and 0 <= index < len(self.affected_items):
            contexts = {row.row_id: row for row in self.snapshot.affected_review_rows}
            _label, left_id, right_id, detail = self.affected_items[index]
            lines = [detail]
            for side, row_id in zip(("A", "B"), (left_id, right_id), strict=True):
                row = contexts[row_id]
                lines.append(
                    f"Source {side}: {row.source_sha256}\nRow: {row.row_id}\n"
                    f"Account: {row.account_name or 'Unassigned'} ({row.account_id or 'none'}); "
                    f"source date: {row.source_date or 'Unknown'}; description: {row.description or 'Not printed'}"
                )
            self.affected_details.setPlainText("\n\n".join(lines))

    def _save(self):
        snapshot, reason = self.snapshot, self.reason.text().strip()
        if snapshot is None or not self.save_button.isEnabled():
            return
        new_name = (
            "Unassigned"
            if snapshot.destination_account_id is None
            else next(account.name for account in snapshot.accounts if account.id == snapshot.destination_account_id)
        )
        message = (
            f"Correct this account assignment?\n\n{_scope(snapshot.target)}\n"
            f"Prior: {_assignments(snapshot.current_account_ids, snapshot.accounts)}\nNew: {new_name}\n"
            f"Affected rows: {len(snapshot.affected_row_ids)}; repeated-row relationships returned to pending: {len(snapshot.affected_review_pairs)}; "
            f"transfer-suggestion reviews invalidated: {len(snapshot.affected_transfer_review_ids)}.\n"
            f"Reason: {reason}\n\nNo journal entries or allocations are created. Original journals stay under their original accounts. "
            "Changed source context requires fresh interpretation and repeat review; old decisions cannot silently reactivate."
        )
        if QMessageBox.question(self, "Confirm reviewed binding correction", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                store.correct_reviewed_binding(
                    snapshot.target,
                    destination_account_id=snapshot.destination_account_id,
                    expected_basis_sha256=snapshot.basis_sha256,
                    reason=reason,
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            message = (
                "The assignment context changed. Inspect the reloaded state before confirming again."
                if "changed_since_selection" in str(exc)
                else str(exc)
            )
            QMessageBox.warning(self, "Account assignment was not corrected", message)
            self.refresh()
            self.status.setText(message)
            return
        self.changed = True
        self.reason.clear()
        self.refresh()
        self.status.setText(
            "The selected account correction is recorded. Refreshed assignments and history show the current state. No journal entries were posted."
        )

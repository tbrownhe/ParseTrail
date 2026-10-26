"""Review complete source-backed settlements without inferred fee allocations."""

from __future__ import annotations

import re
import sqlite3

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
from parsetrail.core.v2_settlements import SettlementFee
from parsetrail.gui.v2_cash_activity_review import _category_labels, _money
from parsetrail.gui.v2_evidence_preview import preview_saved_source


def _positive_minor(text):
    entered = text.strip()
    if re.fullmatch(r"\$?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", entered) is None:
        raise ValueError("Enter an exact positive USD fee amount.")
    whole, _separator, fraction = entered.replace("$", "").replace(",", "").partition(".")
    amount = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if amount <= 0:
        raise ValueError("Enter an exact positive USD fee amount.")
    return amount


def settlement_details(settlement, *, labels=None, categories=(), inverse=False):
    """Show the entire validated manifest, never a projected first pair."""
    labels = labels or {}
    category_names = _category_labels(categories)
    sign = -1 if inverse else 1
    lines = []
    for index, movement in enumerate(settlement.movements):
        natural = 1 if movement.account_kind == "asset" else -1
        lines.append(
            f"{'Outflow' if index == 0 else f'Receipt {index}'}: {labels.get(movement.account_id, reviewed_identity(movement))}; "
            f"{'asset value' if natural == 1 else 'liability owed'} change {_money(sign * natural * movement.amount_minor)} "
            f"on {movement.posting_date} ({movement.date_provenance}). {movement.description}\n"
            f"Source {movement.source_sha256}; row {movement.row_id}."
        )
        for fee in settlement.fees_for(movement.row_id):
            lines.append(
                f"  Explicit {'inverse ' if inverse else ''}fee expense: {_money(sign * fee.amount_minor)}, "
                f"{category_names.get(fee.category_id, fee.category_id)}, at this leg's date.\n"
                f"  Reference: {fee.reference}; reason: {fee.reason}."
            )
    lines.append(
        f"{'Inverse of original ' if inverse else ''}ending transfer clearing: {_money(sign * settlement.residual_minor)} "
        "(unresolved / in transit; this does not establish missing counterpart history or settlement)."
    )
    return "\n\n".join(lines)


def reviewed_identity(movement):
    return f"{movement.account_name} (reviewed {movement.account_kind}, ID {movement.account_id})"


def _table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill(table, rows):
    table.blockSignals(True)
    table.setRowCount(len(rows))
    for row_index, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(row_index, column, item)
    table.clearSelection()
    table.setCurrentCell(-1, -1)
    table.blockSignals(False)


class V2SettlementReview(QDialog):
    """The service owns manifest validation, source consumption and transactions."""

    def __init__(self, workspace, event_id: str | None = None, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.snapshot, self.preview, self.selected_event = None, None, None
        self.review_preferences = workspace.preferences()
        self.fees = ()
        self.labels, self.movements = {}, {}
        self.setWindowTitle("2.0 transfer fees and partial settlements")
        self.resize(1180, 790)
        layout = QVBoxLayout(self)
        path = QHBoxLayout()
        path.addWidget(QLabel("Profile:"))
        self.profile_path = QLineEdit(str(workspace.profile_path))
        self.profile_path.setReadOnly(True)
        self.profile_path.setCursorPosition(0)
        path.addWidget(self.profile_path, 1)
        self.reload = QPushButton("Reload saved state / reset draft")
        self.reload.clicked.connect(self.refresh)
        path.addWidget(self.reload)
        layout.addLayout(path)
        self.mode = QComboBox()
        self.mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(30)
        self.mode.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.mode)
        self.assumed_dates = QCheckBox("Allow best guess posting dates when a statement does not print one")
        self.assumed_dates.setChecked(self.review_preferences.allow_assumed_posting_dates)
        self.assumed_dates.toggled.connect(self._toggle_dates)
        layout.addWidget(self.assumed_dates)
        note = QLabel(
            "Explicitly select one asset outflow and one or more owned-account receipts. Dates retain their reviewed source roles, "
            "even when receipts precede the outflow. No fee is inferred from a difference. Unexplained clearing remains unresolved / in transit. "
            "Unlisted unsupported or already consumed rows remain outside this review."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_sources()
        self._build_fees()
        self._build_preview()
        history = QWidget()
        history_layout = QVBoxLayout(history)
        self.history_details = QPlainTextEdit()
        self.history_details.setReadOnly(True)
        history_layout.addWidget(self.history_details)
        self.tabs.addTab(history, "Saved event / history")
        form = QFormLayout()
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        self.reason.setPlaceholderText("Required reason for this full settlement, whole replacement or withdrawal")
        self.reason.textChanged.connect(self._update_actions)
        form.addRow("Whole-event reason", self.reason)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.confirm = QPushButton("Confirm and post full settlement")
        self.confirm.clicked.connect(self._post)
        actions.addWidget(self.confirm)
        self.withdraw = QPushButton("Withdraw whole saved event")
        self.withdraw.clicked.connect(self._withdraw)
        actions.addWidget(self.withdraw)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._requested_event_id = event_id
        self.refresh()

    def _build_sources(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        row = QHBoxLayout()
        row.addWidget(QLabel("Complete source outflow"))
        self.outgoing = QComboBox()
        self.outgoing.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.outgoing.setMinimumContentsLength(30)
        self.outgoing.currentIndexChanged.connect(self._draft_changed)
        row.addWidget(self.outgoing, 1)
        self.open_outgoing = QPushButton("Open outflow evidence")
        self.open_outgoing.clicked.connect(lambda: self._open_source(self.outgoing.currentData()))
        row.addWidget(self.open_outgoing)
        layout.addLayout(row)
        layout.addWidget(QLabel("Check every receipt being reviewed; no receipt is selected automatically."))
        self.receipts = _table(
            ("Use", "Posting date / role", "Financial account", "Source allocation", "Description", "Source")
        )
        for column, width in enumerate((45, 170, 250, 125, 300, 150)):
            self.receipts.setColumnWidth(column, width)
        self.receipts.itemChanged.connect(self._draft_changed)
        self.receipts.itemSelectionChanged.connect(self._receipt_selected)
        layout.addWidget(self.receipts, 1)
        self.source_details = QPlainTextEdit()
        self.source_details.setReadOnly(True)
        self.source_details.setMaximumHeight(125)
        layout.addWidget(self.source_details)
        self.open_receipt = QPushButton("Open selected receipt evidence")
        self.open_receipt.clicked.connect(lambda: self._open_source(self._selected_receipt_id()))
        layout.addWidget(self.open_receipt)
        self.tabs.addTab(panel, "Source legs")

    def _build_fees(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        note = QLabel(
            "No fee allocation is selected by default. A fee requires its actual source leg, exact reviewed amount, expense category, "
            "reference and reason. A receiving-side fee adds to that receipt's gross settlement; it does not change its source allocation. "
            "Select and remove an existing draft fee before adding its corrected details. Draft edits write nothing."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.fee_leg = QComboBox()
        self.fee_leg.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.fee_leg.setMinimumContentsLength(30)
        form.addRow("Fee's source leg", self.fee_leg)
        self.fee_amount = QLineEdit()
        self.fee_amount.setMaxLength(100)
        self.fee_amount.setPlaceholderText("Exact positive USD fee; never calculated from the difference")
        form.addRow("Explicit fee amount", self.fee_amount)
        self.fee_category = QComboBox()
        form.addRow("Expense category", self.fee_category)
        self.fee_reference = QLineEdit()
        self.fee_reference.setMaxLength(500)
        self.fee_reference.setPlaceholderText(
            "Required source page/section/row reference supporting this fee allocation"
        )
        form.addRow("Fee reference", self.fee_reference)
        self.fee_reason = QLineEdit()
        self.fee_reason.setMaxLength(500)
        self.fee_reason.setPlaceholderText("Required reason for this exact fee allocation")
        form.addRow("Fee reason", self.fee_reason)
        layout.addLayout(form)
        for widget in (self.fee_leg, self.fee_category):
            widget.currentIndexChanged.connect(self._fee_actions)
        for widget in (self.fee_amount, self.fee_reference, self.fee_reason):
            widget.textChanged.connect(self._fee_actions)
        actions = QHBoxLayout()
        self.add_fee = QPushButton("Add explicit fee to draft")
        self.add_fee.clicked.connect(self._add_fee)
        actions.addWidget(self.add_fee)
        self.remove_fee = QPushButton("Remove selected draft fee")
        self.remove_fee.clicked.connect(self._remove_fee)
        actions.addWidget(self.remove_fee)
        layout.addLayout(actions)
        self.fee_table = _table(("Source leg / date", "Fee amount", "Expense category", "Reference", "Reason"))
        self.fee_table.itemSelectionChanged.connect(self._fee_actions)
        for column, width in enumerate((300, 110, 220, 250, 250)):
            self.fee_table.setColumnWidth(column, width)
        layout.addWidget(self.fee_table, 1)
        self.tabs.addTab(panel, "Explicit fees")

    def _build_preview(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.summary = QLabel("Select a complete source outflow and at least one receipt.")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.summary)
        self.entry_table = _table(("Accounting date", "Ledger account", "Debit (+) / credit (-)", "Source allocation"))
        for column, width in enumerate((140, 420, 170, 300)):
            self.entry_table.setColumnWidth(column, width)
        layout.addWidget(self.entry_table, 1)
        self.preview_details = QPlainTextEdit()
        self.preview_details.setReadOnly(True)
        self.preview_details.setMaximumHeight(145)
        layout.addWidget(self.preview_details)
        self.tabs.addTab(panel, "Exact journal preview")

    def _caption(self, movement):
        return (
            f"{self.labels.get(movement.account_id, movement.account_name)}; {movement.posting_date} "
            f"({movement.date_provenance}); {_money(movement.amount_minor)}; row {movement.row_id[:12]}; {movement.description}"
        )

    def _receipt_ids(self):
        return tuple(
            sorted(
                self.receipts.item(index, 0).data(Qt.UserRole)
                for index in range(self.receipts.rowCount())
                if self.receipts.item(index, 0).checkState() == Qt.Checked
            )
        )

    def _selected_receipt_id(self):
        item = self.receipts.item(self.receipts.currentRow(), 0)
        return item.data(Qt.UserRole) if item else None

    def _receipt_selected(self):
        movement = self.movements.get(self._selected_receipt_id())
        self.open_receipt.setEnabled(movement is not None)
        self.source_details.setPlainText(
            self._caption(movement)
            + f"\nSource: {movement.source_sha256}\nRow: {movement.row_id}\n"
            + (
                "Date is allowed for new posting."
                if movement.date_allowed
                else "Assumed date requires the global best guess choice."
            )
            if movement
            else "Select a receipt to inspect its exact source reference."
        )

    def refresh(self, *_args):
        selected_id = self.mode.currentData() or self._requested_event_id
        self._requested_event_id = None
        self.snapshot, self.preview, self.selected_event = None, None, None
        self.fees = ()
        self.reason.clear()
        self.review_preferences = self.workspace.preferences()
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                snapshot = store.settlement_review_snapshot(preferences=self.review_preferences)
                event = next((item for item in snapshot.events if item.event_id == selected_id), None)
                if event is not None and event.status == "active":
                    snapshot = store.settlement_review_snapshot(
                        preferences=self.review_preferences, replacing_event_id=event.event_id
                    )
                    event = next(item for item in snapshot.events if item.event_id == selected_id)
        except (ProfileFormatError, sqlite3.Error, OSError, StopIteration):
            self.movements, self.labels = {}, {}
            self.mode.blockSignals(True)
            self.mode.clear()
            self.mode.addItem("Saved settlement state unavailable", None)
            self.mode.blockSignals(False)
            self._clear_draft()
            self.status.setText("Settlement state unavailable. Reload saved state before reviewing another event.")
            return
        self.snapshot, self.selected_event = snapshot, event
        self.labels = cash_account_labels(snapshot.accounts)
        self.movements = {movement.row_id: movement for movement in snapshot.movements}
        if event is not None:
            for movement in event.settlement.movements:
                self.movements.setdefault(movement.row_id, movement)
        self.mode.blockSignals(True)
        self.mode.clear()
        self.mode.addItem("New full settlement — draft", None)
        for item in snapshot.events:
            self.mode.addItem(
                f"{item.status.title()} {item.settlement.kind}; {item.settlement.outgoing.posting_date}; "
                f"{len(item.settlement.incoming)} receipt(s), {len(item.settlement.fees)} fee(s); {item.event_id}",
                item.event_id,
            )
        if event is not None:
            self.mode.setCurrentIndex(self.mode.findData(event.event_id))
        self.mode.blockSignals(False)
        self.assumed_dates.blockSignals(True)
        self.assumed_dates.setChecked(self.review_preferences.allow_assumed_posting_dates)
        self.assumed_dates.blockSignals(False)
        self._clear_draft()
        self.outgoing.blockSignals(True)
        self.outgoing.addItem("Choose the complete asset outflow", None)
        for movement in self.movements.values():
            if movement.amount_minor < 0 and movement.account_kind == "asset":
                self.outgoing.addItem(self._caption(movement), movement.row_id)
                self.outgoing.setItemData(
                    self.outgoing.count() - 1,
                    self._caption(movement) + f"\nSource: {movement.source_sha256}\nRow: {movement.row_id}",
                    Qt.ToolTipRole,
                )
        if event is not None:
            self.outgoing.setCurrentIndex(self.outgoing.findData(event.settlement.outgoing.row_id))
            self.fees = event.settlement.fees
        self.outgoing.blockSignals(False)
        incoming_ids = set(event.settlement.row_ids[1:]) if event else set()
        incoming = tuple(movement for movement in self.movements.values() if movement.amount_minor > 0)
        self.receipts.blockSignals(True)
        self.receipts.setRowCount(len(incoming))
        for index, movement in enumerate(incoming):
            values = (
                "",
                f"{movement.posting_date} ({movement.date_provenance})",
                self.labels.get(movement.account_id, movement.account_name),
                _money(movement.amount_minor),
                movement.description,
                movement.source_sha256[:16],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, movement.row_id)
                item.setToolTip(self._caption(movement) + f"\nSource: {movement.source_sha256}\nRow: {movement.row_id}")
                if column == 0:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if movement.row_id in incoming_ids else Qt.Unchecked)
                self.receipts.setItem(index, column, item)
        self.receipts.blockSignals(False)
        self.fee_category.blockSignals(True)
        self.fee_category.addItem("Choose an expense category explicitly", None)
        category_names = _category_labels(snapshot.categories)
        for category in snapshot.categories:
            self.fee_category.addItem(category_names[category.id], category.id)
        self.fee_category.blockSignals(False)
        self.history_details.setPlainText(
            f"{event.status.title()} event {event.event_id}; version {event.version}\nOriginal reason: {event.reason}\n"
            f"Action reason: {event.action_reason or 'none'}; replacement: {event.replacement_event_id or 'none'}\n"
            f"Journal references: {', '.join(event.entry_keys)}\n\n"
            + settlement_details(event.settlement, labels=self.labels, categories=snapshot.categories)
            if event
            else "Choose a saved event above to inspect every source leg, fee and correction reference."
        )
        self._draft_changed()

    def _clear_draft(self):
        for widget in (self.outgoing, self.fee_leg, self.fee_category):
            widget.blockSignals(True)
            widget.clear()
            widget.blockSignals(False)
        for field in (self.fee_amount, self.fee_reference, self.fee_reason):
            field.clear()
        for table in (self.receipts, self.fee_table, self.entry_table):
            _fill(table, ())
        self.source_details.clear()
        self.preview_details.clear()
        self.history_details.clear()
        self.summary.setText("Select a complete source outflow and at least one receipt. No fee is inferred.")
        self.open_outgoing.setEnabled(False)
        self.open_receipt.setEnabled(False)
        self._fee_actions()
        self._update_actions()

    def _draft_changed(self, *_args):
        self.preview = None
        self.open_outgoing.setEnabled(self.outgoing.currentData() in self.movements)
        self._receipt_selected()
        prior_leg = self.fee_leg.currentData()
        self.fee_leg.blockSignals(True)
        self.fee_leg.clear()
        self.fee_leg.addItem("Choose the fee's actual source leg", None)
        for row_id in (self.outgoing.currentData(), *self._receipt_ids()):
            movement = self.movements.get(row_id)
            if movement:
                self.fee_leg.addItem(self._caption(movement), row_id)
                self.fee_leg.setItemData(
                    self.fee_leg.count() - 1,
                    self._caption(movement) + f"\nSource: {movement.source_sha256}\nRow: {movement.row_id}",
                    Qt.ToolTipRole,
                )
        if prior_leg is not None:
            self.fee_leg.setCurrentIndex(max(0, self.fee_leg.findData(prior_leg)))
        self.fee_leg.blockSignals(False)
        category_names = _category_labels(self.snapshot.categories) if self.snapshot else {}
        _fill(
            self.fee_table,
            tuple(
                (
                    self._caption(self.movements[fee.source_row_id])
                    if fee.source_row_id in self.movements
                    else fee.source_row_id,
                    _money(fee.amount_minor),
                    category_names.get(fee.category_id, fee.category_id),
                    fee.reference,
                    fee.reason,
                )
                for fee in self.fees
            ),
        )
        self._refresh_preview()
        self._fee_actions()

    def _refresh_preview(self):
        _fill(self.entry_table, ())
        self.preview_details.clear()
        if self.snapshot is None or self.outgoing.currentData() is None or not self._receipt_ids():
            self.summary.setText("Select a complete source outflow and at least one receipt. No fee is inferred.")
            self._update_actions()
            return
        if self.selected_event is not None and self.selected_event.status != "active":
            self.summary.setText(
                "This saved event is historical. Inspect its full manifest in Saved event / history; select New to review another event."
            )
            self._update_actions()
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                self.preview = store.preview_reviewed_settlement(
                    self.outgoing.currentData(),
                    self._receipt_ids(),
                    fees=self.fees,
                    preferences=self.review_preferences,
                    expected_basis_sha256=self.snapshot.basis_sha256,
                    replacing_event_id=self.selected_event.event_id if self.selected_event else None,
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.preview = None
            if "changed_since_selection" in str(exc):
                self.refresh()
                self.status.setText(
                    "Source or event context changed. The draft was reset; inspect the reloaded complete source legs before confirming."
                )
                return
            if isinstance(exc, (sqlite3.Error, OSError)) or "integrity" in str(exc):
                self.snapshot, self.selected_event = None, None
                self.movements, self.labels = {}, {}
                self._clear_draft()
                self.status.setText(
                    "Preview source state could not be verified. Reload saved state before another action."
                )
                return
            messages = {
                "settlement_overallocated": "Receipts and explicit fees exceed the source outflow, or leave no transfer principal. Review every allocation.",
                "transfer_assumed_date_disabled": "A selected leg has an assumed date. Explicitly enable the global best guess choice before new postings; withdrawal remains available.",
            }
            self.summary.setText(
                "Preview unavailable: "
                + messages.get(
                    str(exc),
                    "Source context, dates, allocations or the selected fee details do not support this manifest. Reload after source changes.",
                )
            )
            self._update_actions()
            return
        settlement = self.preview.settlement
        incoming_fee = sum(fee.amount_minor for fee in settlement.fees) - settlement.outgoing_fee_minor
        self.summary.setText(
            f"Complete outflow {_money(-settlement.outgoing.amount_minor)}; explicit outgoing fees {_money(settlement.outgoing_fee_minor)}; "
            f"transfer principal {_money(settlement.sent_principal_minor)}. Net receipt allocations {_money(sum(m.amount_minor for m in settlement.incoming))}; "
            f"explicit receiving fees {_money(incoming_fee)}; gross settlement received {_money(settlement.received_gross_minor)}. "
            f"Ending clearing {_money(settlement.residual_minor)} remains unresolved / in transit. A zero residual does not establish complete source coverage."
        )
        names = {
            **self.labels,
            **_category_labels(self.snapshot.categories),
            "internal:transfer-clearing:USD": "Transfer clearing (unresolved / in transit)",
        }
        _fill(
            self.entry_table,
            tuple(
                (
                    entry.posting_date.isoformat(),
                    names.get(posting.account_id, posting.account_id),
                    _money(posting.amount_minor),
                    "; ".join(
                        f"{allocation.observation_id}: {_money(allocation.amount_minor)}"
                        for allocation in posting.allocations
                    )
                    or "No additional source allocation",
                )
                for entry in self.preview.entries
                for posting in entry.postings
            ),
        )
        self.preview_details.setPlainText(
            settlement_details(settlement, labels=self.labels, categories=self.snapshot.categories)
        )
        self._update_actions()

    def _fee_actions(self, *_args):
        if not hasattr(self, "add_fee"):
            return
        try:
            _positive_minor(self.fee_amount.text())
            amount_valid = True
        except ValueError:
            amount_valid = False
        editing = self.snapshot is not None and (self.selected_event is None or self.selected_event.status == "active")
        self.add_fee.setEnabled(
            bool(
                editing
                and self.fee_leg.currentData()
                and self.fee_category.currentData()
                and amount_valid
                and self.fee_reference.text().strip()
                and self.fee_reason.text().strip()
            )
        )
        self.remove_fee.setEnabled(bool(editing and 0 <= self.fee_table.currentRow() < len(self.fees)))

    def _add_fee(self):
        if not self.add_fee.isEnabled():
            return
        self.fees = (
            *self.fees,
            SettlementFee(
                self.fee_leg.currentData(),
                self.fee_category.currentData(),
                _positive_minor(self.fee_amount.text()),
                self.fee_reference.text().strip(),
                self.fee_reason.text().strip(),
            ),
        )
        self.fee_amount.clear()
        self.fee_reference.clear()
        self.fee_reason.clear()
        self._draft_changed()

    def _remove_fee(self):
        index = self.fee_table.currentRow()
        if self.remove_fee.isEnabled() and 0 <= index < len(self.fees):
            self.fees = tuple(fee for position, fee in enumerate(self.fees) if position != index)
            self._draft_changed()

    def _update_actions(self, *_args):
        if not hasattr(self, "confirm"):
            return
        event = self.selected_event
        active = event is not None and event.status == "active"
        changed = self.preview is not None and (event is None or self.preview.settlement != event.settlement)
        self.confirm.setText(
            "Confirm and replace whole event" if event is not None else "Confirm and post full settlement"
        )
        self.confirm.setEnabled(
            bool(
                self.snapshot is not None
                and self.preview is not None
                and changed
                and (event is None or active)
                and self.reason.text().strip()
            )
        )
        self.withdraw.setEnabled(bool(self.snapshot is not None and active and self.reason.text().strip()))
        if self.snapshot is None:
            self.status.setText("Reload saved state before reviewing an event.")
        elif event is not None and not active:
            self.status.setText(
                "Historical event: no money can be posted, withdrawn or replaced from this saved state."
            )
        elif self.preview is None and self.outgoing.currentData() is not None and self._receipt_ids():
            self.status.setText(self.summary.text())
        elif self.preview is not None:
            self.status.setText(
                f"Draft only; ending clearing {_money(self.preview.settlement.residual_minor)} is unresolved / in transit. "
                "Inspect Exact journal preview before confirmation. No fee is inferred."
            )
        else:
            self.status.setText(
                "Draft only. Confirm the complete preview; every fee needs independent source support. Whole replacement reverses all original legs first."
            )

    def _toggle_dates(self, enabled):
        try:
            self.workspace.set_allow_assumed_posting_dates(enabled)
        except (OSError, ValueError):
            self.assumed_dates.blockSignals(True)
            self.assumed_dates.setChecked(not enabled)
            self.assumed_dates.blockSignals(False)
            return
        self.refresh()

    def _open_source(self, row_id):
        movement = self.movements.get(row_id)
        if movement is None:
            return
        try:
            preview_saved_source(self.workspace.profile_path, movement.source_sha256, parent=self).exec()
        except (ProfileFormatError, sqlite3.Error, OSError):
            QMessageBox.warning(self, "Source unavailable", "Reload the settlement and inspect the saved source again.")

    def _post(self):
        if not self.confirm.isEnabled() or self.preview is None or self.snapshot is None:
            return
        preview, snapshot, event = self.preview, self.snapshot, self.selected_event
        reason = self.reason.text().strip()
        message = (
            (
                "Replace the whole saved event?\n\nInverse original source and fee effects:\n"
                + settlement_details(event.settlement, labels=self.labels, categories=snapshot.categories, inverse=True)
                + "\n\nReplacement entry effects only (all original journal entries are reversed at their own dates):\n"
                if event
                else "Post this complete settlement?\n\nNew entry effects:\n"
            )
            + settlement_details(preview.settlement, labels=self.labels, categories=snapshot.categories)
            + f"\n\n{self.summary.text()}\nReason: {reason}\n\n"
            + "Each financial source leg is allocated in full once. Explicit fees create the listed expense; the transfer portion creates no second spending or income. "
            + "Unknown counterpart history stays unknown. Failure preserves the original event and source consumption."
        )
        if (
            QMessageBox.question(
                self, "Confirm full settlement replacement" if event else "Confirm full settlement", message
            )
            != QMessageBox.Yes
        ):
            return
        if self.workspace.preferences() != self.review_preferences:
            self.refresh()
            self.status.setText(
                "Posting-date preferences changed during review. Inspect the reloaded source legs and rebuild the draft before confirming."
            )
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                kwargs = {
                    "fees": preview.settlement.fees,
                    "preferences": self.review_preferences,
                    "expected_basis_sha256": snapshot.basis_sha256,
                    "reason": reason,
                }
                if event is not None:
                    saved_id = store.replace_reviewed_settlement(
                        event.event_id,
                        preview.settlement.outgoing.row_id,
                        tuple(m.row_id for m in preview.settlement.incoming),
                        **kwargs,
                    )
                else:
                    saved_id = store.post_reviewed_settlement(
                        preview.settlement.outgoing.row_id,
                        tuple(m.row_id for m in preview.settlement.incoming),
                        **kwargs,
                    )
        except (ProfileFormatError, sqlite3.Error, OSError):
            self.refresh()
            self.status.setText(
                "Settlement was not recorded. Source usage, bindings, repeated evidence, fees or another event may have changed. Inspect the reloaded complete state."
            )
            return
        self._requested_event_id = saved_id
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(0)
        self.mode.blockSignals(False)
        self.refresh()
        self.status.setText(
            "The selected settlement review is recorded. Refreshed complete event history shows the current state and unresolved clearing."
        )

    def _withdraw(self):
        event, snapshot, reason = self.selected_event, self.snapshot, self.reason.text().strip()
        if not self.withdraw.isEnabled() or event is None or snapshot is None:
            return
        message = (
            f"Withdraw this whole saved {event.settlement.kind}?\n\nInverse original source and fee effects:\n"
            + settlement_details(event.settlement, labels=self.labels, categories=snapshot.categories, inverse=True)
            + f"\n\nAll {len(event.entry_keys)} journal entries are reversed at their original dates. Reason: {reason}\n"
            + "This also reverses the event's fee expense and clearing. Source rows are released together; original entries and history remain. "
            + "No bank transaction or settlement is undone by this bookkeeping review."
        )
        if QMessageBox.question(self, "Confirm whole settlement withdrawal", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.withdraw_reviewed_transfer(
                    event.event_id, expected_basis_sha256=snapshot.basis_sha256, reason=reason
                )
        except (ProfileFormatError, sqlite3.Error, OSError):
            self.refresh()
            self.status.setText(
                "Whole-event withdrawal was not recorded. Inspect the reloaded full event and its source usage before trying again."
            )
            return
        self.refresh()
        self.status.setText(
            "The selected whole-event withdrawal is recorded. Refreshed event history shows current source consumption and fee state."
        )

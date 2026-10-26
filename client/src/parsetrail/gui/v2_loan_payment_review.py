"""Explicit full-source loan payment review over the authoritative profile service."""

from __future__ import annotations

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

from parsetrail.core.source_evidence import ObservationEvidence
from parsetrail.core.v2_cash_movement import cash_account_labels
from parsetrail.core.v2_loan_payments import CLEARING, INTEREST
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.gui.v2_cash_activity_review import _money
from parsetrail.gui.v2_evidence_preview import _location, preview_saved_source

REASONS = {
    "loan_account_assignment_required": "Assign this source to a financial account first.",
    "loan_principal_scope_required": "Requires a liability account tracking the principal component.",
    "loan_component_unsupported": "Printed components are incomplete, unsupported or include a nonzero fee; leave this row pending.",
    "loan_source_already_used": "This source row already has an active interpretation or payment event.",
    "loan_assumed_date_disabled": "Source activity date is observed; using it as an assumed accounting date requires the default-off preference above.",
    "source_overlap_review_required": "Repeated source evidence needs explicit occurrence review first.",
    "loan_changed_since_selection": "Sources, bindings or another review changed. The draft was reset; inspect the refreshed facts.",
    "loan_event_changed_since_selection": "The selected event changed. Inspect its refreshed history before another action.",
    "loan_event_not_active": "This event is historical; select a current active event or start a new review.",
    "loan_selection_unavailable_or_date_disabled": "A selected source is unavailable or its accounting date is not allowed. Check source use and the visible date preference.",
    "loan_selection_unavailable_or_component_mismatch": "The explicit selection does not form a supported payment. Require exact bank gross equality, one Capital/MOHELA payment or Wells rows from one source and principal account.",
    "loan_manifest_invalid": "The selected bank amount and complete loan components do not form one supported, exact payment.",
    "loan_manifest_requires_one_payment": "Select one Capital/MOHELA payment, or explicitly selected Wells rows from one source and principal account.",
    "loan_reason_reference_required": "Enter both an inspected-source reference and a reason for the whole payment event.",
}


def _label(text=""):
    result = QLabel(text)
    result.setTextFormat(Qt.PlainText)
    result.setWordWrap(True)
    result.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return result


def _table(headers):
    result = QTableWidget(0, len(headers))
    result.setEditTriggers(QAbstractItemView.NoEditTriggers)
    result.setSelectionBehavior(QAbstractItemView.SelectRows)
    result.setSelectionMode(QAbstractItemView.SingleSelection)
    result.setHorizontalHeaderLabels(headers)
    result.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    return result


def _fill(table, rows):
    table.blockSignals(True)
    table.clearSelection()
    table.setCurrentCell(-1, -1)
    table.setRowCount(len(rows))
    for index, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(index, column, item)
    table.blockSignals(False)


def _identity(account_id, name, kind, scope):
    return f"{name or 'Name unavailable'} ({kind or 'kind unavailable'}, {(scope or 'scope unavailable').replace('_', ' ')}, ID {account_id or 'unassigned'})"


def component_details(proof):
    """Display already validated source facts; normalization belongs to the proof."""
    row = ObservationEvidence.model_validate_json(proof.row_evidence)
    parts = "; ".join(
        f"{part.role}: {part.amount.raw or 'not printed'} / signed {_money(part.amount.minor)} ({part.amount.provenance}); "
        f"{', '.join(_location(location) for location in part.amount.locations)}"
        for part in row.components
    )
    return (
        f"Loan: {_identity(proof.account_id, proof.account_name, proof.account_kind, proof.tracking_scope)}\n"
        f"Source activity date: {proof.activity_date} (observed activity date). "
        f"Accounting date: {proof.effective_date} (assumed from activity date; NOT a reported posting date).\n"
        f"Printed gross: {row.amount.raw}; signed raw gross {_money(proof.raw_amount_minor)}. "
        f"Raw principal {_money(proof.raw_principal_minor) if proof.raw_principal_minor is not None else 'not a separate component in this admitted shape'}; "
        f"raw interest {_money(proof.raw_interest_minor) if proof.raw_interest_minor is not None else 'not a separate component in this admitted shape'}; "
        f"raw fee {_money(proof.raw_fee_minor) if proof.raw_fee_minor is not None else 'not a separate component in this admitted shape'}.\n"
        f"Normalized financial principal debit {_money(proof.principal_minor)}; liability owed change {_money(-proof.principal_minor)}; "
        f"interest expense {_money(proof.interest_minor)}; gross clearing credit {_money(-proof.gross_minor)}.\n"
        f"Full raw source use {_money(proof.raw_amount_minor)} is retained separately from derived principal allocation.\n"
        f"Printed components: {parts}\nDescription: {row.description.text or 'unavailable / unknown'}. "
        f"Source {proof.source_sha256}; row {proof.row_id}; parser {proof.parser_id}. "
        "Principal-component movement does not establish the total obligation or supply an unknown opening."
    )


def pending_component_details(row):
    evidence = ObservationEvidence.model_validate_json(row.row_evidence)
    facts = "; ".join(
        f"{part.role}: {part.amount.raw or 'not printed'} / {_money(part.amount.minor)} ({part.amount.provenance})"
        for part in evidence.components
    )
    return (
        f"Pending loan source {row.source_sha256}; row {row.row_id}.\n"
        f"Source activity date: {row.activity_date or 'unknown'} ({evidence.date.provenance} {evidence.date_role}); "
        "accounting date unavailable for new posting.\n"
        f"Signed raw gross: {_money(row.amount_minor)}; description {row.description or 'unavailable / unknown'}.\n"
        f"Printed component facts: {facts or 'unavailable'}.\n"
        + " ".join(REASONS.get(code, "This row is outside the admitted loan payment review.") for code in row.blockers)
        + "\nInspect the immutable source; unavailable components, fees or scope are never filled in."
    )


def manifest_details(manifest, *, inverse=False):
    sign = -1 if inverse else 1
    bank = manifest.bank
    result = [
        f"{'Inverse original' if inverse else 'Reviewed'} bank source: "
        f"{_identity(bank.account_id, bank.account_name, bank.account_kind, bank.tracking_scope)}; "
        f"asset value change {_money(sign * bank.amount_minor)} on {bank.posting_date} ({bank.date_provenance}).\n"
        f"Source {bank.source_sha256}; full raw row {bank.row_id}."
    ]
    for proof in manifest.components:
        result.append(
            f"{'Inverse original' if inverse else 'Reviewed'} loan leg: "
            f"{_identity(proof.account_id, proof.account_name, proof.account_kind, proof.tracking_scope)}; "
            f"liability owed change {_money(-sign * proof.principal_minor)}, interest expense {_money(sign * proof.interest_minor)}, "
            f"clearing {_money(-sign * proof.gross_minor)} on {proof.effective_date} "
            f"(assumed accounting date; observed activity date {proof.activity_date}, NOT reported posting).\n"
            f"Source {proof.source_sha256}; full raw row {proof.row_id}: {_money(proof.raw_amount_minor)}."
        )
    result.append(
        "Bank and loan legs keep separate dates; transfer clearing remains between those dates. "
        "Only evidenced interest is expense; gross payment is not a second expense. "
        "Zero principal or interest creates no fabricated zero financial observation or expense. "
        "Unknown opening remains unknown; principal component is not the full obligation."
    )
    return "\n\n".join(result)


class V2LoanPaymentReview(QDialog):
    """The store owns source admission, exact proofs, stale checks and transactions."""

    def __init__(self, workspace, parent=None, *, event_id=None):
        super().__init__(parent)
        self.workspace = workspace
        self.snapshot = self.preview = self.selected_event = None
        self._requested_event_id = event_id
        self.labels, self.banks, self.rows = {}, {}, ()
        self.review_preferences = workspace.preferences()
        self.setWindowTitle("2.0 evidenced loan payments")
        self.resize(1240, 800)
        layout = QVBoxLayout(self)
        path = QHBoxLayout()
        path.addWidget(_label("Profile:"))
        self.profile_path = QLineEdit(str(workspace.profile_path))
        self.profile_path.setReadOnly(True)
        self.profile_path.setCursorPosition(0)
        path.addWidget(self.profile_path, 1)
        self.reload = QPushButton("Reload saved state / reset draft")
        self.reload.clicked.connect(self.refresh)
        path.addWidget(self.reload)
        layout.addLayout(path)
        self.mode = QComboBox()
        self.mode.setMinimumContentsLength(35)
        self.mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.mode)
        self.assumed_dates = QCheckBox("Allow best guess posting dates when a statement does not print one")
        self.assumed_dates.toggled.connect(self._toggle_dates)
        layout.addWidget(self.assumed_dates)
        layout.addWidget(
            _label(
                "Select the actual bank outflow and complete printed loan components explicitly. No payment group or counterpart is inferred. "
                "Loan dates are observed activity dates; using them as accounting dates is an explicit assumed-date choice. "
                "Nonzero fees, incomplete components and unsupported source/account scopes stay pending."
            )
        )
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_sources()
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        self.summary = _label()
        preview_layout.addWidget(self.summary)
        self.entry_table = _table(
            ("Accounting date / role", "Ledger account", "Debit (+) / credit (-)", "Financial allocation")
        )
        for column, width in enumerate((210, 360, 160, 410)):
            self.entry_table.setColumnWidth(column, width)
        preview_layout.addWidget(self.entry_table, 1)
        self.preview_details = QPlainTextEdit()
        self.preview_details.setReadOnly(True)
        self.preview_details.setMaximumHeight(175)
        preview_layout.addWidget(self.preview_details)
        self.tabs.addTab(preview_panel, "Exact journal preview")
        history_panel = QWidget()
        history_layout = QVBoxLayout(history_panel)
        self.history_details = QPlainTextEdit()
        self.history_details.setReadOnly(True)
        history_layout.addWidget(self.history_details)
        history_sources = QHBoxLayout()
        self.history_source = QComboBox()
        history_sources.addWidget(self.history_source, 1)
        self.open_history_source = QPushButton("Open selected historical source")
        self.open_history_source.clicked.connect(
            lambda: self._open_source(self.history_source.currentData()) if self.history_source.currentData() else None
        )
        history_sources.addWidget(self.open_history_source)
        history_layout.addLayout(history_sources)
        self.tabs.addTab(history_panel, "Saved event / history")
        form = QFormLayout()
        self.reference = QLineEdit()
        self.reference.setMaxLength(500)
        self.reference.setPlaceholderText("Required reference for inspected bank and printed loan components")
        form.addRow("Review reference", self.reference)
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        self.reason.setPlaceholderText("Required whole-event reason; withdrawal also requires a reason")
        form.addRow("Whole-event reason", self.reason)
        for field in (self.reference, self.reason):
            field.textChanged.connect(self._update_actions)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.confirm = QPushButton("Confirm evidenced loan payment")
        self.confirm.clicked.connect(self._post)
        self.withdraw = QPushButton("Withdraw whole saved payment")
        self.withdraw.clicked.connect(self._withdraw)
        actions.addWidget(self.confirm)
        actions.addWidget(self.withdraw)
        layout.addLayout(actions)
        self.status = _label()
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _build_sources(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        bank_row = QHBoxLayout()
        bank_row.addWidget(_label("Complete bank outflow"))
        self.bank = QComboBox()
        self.bank.setMinimumContentsLength(30)
        self.bank.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.bank.currentIndexChanged.connect(self._draft_changed)
        bank_row.addWidget(self.bank, 1)
        self.open_bank = QPushButton("Open bank evidence")
        self.open_bank.clicked.connect(self._preview_bank)
        bank_row.addWidget(self.open_bank)
        layout.addLayout(bank_row)
        layout.addWidget(
            _label(
                "Check one Capital/MOHELA payment, or explicit Wells rows from one source and principal account. No loan row is selected automatically."
            )
        )
        self.components = _table(
            (
                "Use",
                "Source activity date",
                "Assumed accounting date",
                "Loan / scope",
                "Raw gross",
                "Principal debit",
                "Interest expense",
                "Eligibility",
                "Source",
            )
        )
        for column, width in enumerate((45, 130, 165, 240, 100, 110, 110, 280, 150)):
            self.components.setColumnWidth(column, width)
        self.components.itemChanged.connect(self._draft_changed)
        self.components.itemSelectionChanged.connect(self._component_selected)
        layout.addWidget(self.components, 1)
        self.source_details = QPlainTextEdit()
        self.source_details.setReadOnly(True)
        self.source_details.setMaximumHeight(190)
        layout.addWidget(self.source_details)
        self.open_component = QPushButton("Open selected loan source evidence")
        self.open_component.clicked.connect(self._preview_component)
        layout.addWidget(self.open_component)
        self.tabs.addTab(panel, "Bank and printed components")

    def _component_ids(self):
        return tuple(
            sorted(
                self.components.item(index, 0).data(Qt.UserRole)
                for index in range(self.components.rowCount())
                if self.components.item(index, 0).checkState() == Qt.Checked
            )
        )

    def _bank_caption(self, movement):
        return f"{self.labels.get(movement.account_id, _identity(movement.account_id, movement.account_name, movement.account_kind, movement.tracking_scope))}; {movement.posting_date} ({movement.date_provenance}); {_money(movement.amount_minor)}; {movement.row_id[:12]}"

    def refresh(self, *_args):
        selected_id = self.mode.currentData() or self._requested_event_id
        self._requested_event_id = None
        self.snapshot = self.preview = self.selected_event = None
        self.review_preferences = self.workspace.preferences()
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                snapshot = store.loan_review_snapshot(self.review_preferences)
                event = next((event for event in snapshot.history if event.event_id == selected_id), None)
                if event is not None and event.status == "active":
                    snapshot = store.loan_review_snapshot(self.review_preferences, replacing_event_id=event.event_id)
                    event = next(event for event in snapshot.history if event.event_id == selected_id)
        except (ProfileFormatError, sqlite3.Error, OSError, StopIteration):
            self.banks, self.rows, self.labels = {}, (), {}
            self.mode.blockSignals(True)
            self.mode.clear()
            self.mode.addItem("Loan review state unavailable", None)
            self.mode.blockSignals(False)
            self._clear_draft()
            self.status.setText("Loan sources and event history could not be verified. Reload before another action.")
            return
        self.snapshot, self.selected_event = snapshot, event
        self.labels = cash_account_labels(snapshot.accounts)
        self.banks = {bank.row_id: bank for bank in snapshot.bank_movements}
        self.rows = snapshot.components
        self.mode.blockSignals(True)
        self.mode.clear()
        self.mode.addItem("New evidenced loan payment — draft", None)
        for item in snapshot.history:
            self.mode.addItem(
                f"{item.status.title()}; {item.manifest.bank.posting_date}; principal {_money(item.manifest.principal_minor)}, interest {_money(item.manifest.interest_minor)}; {item.event_id}",
                item.event_id,
            )
        if event is not None:
            self.mode.setCurrentIndex(self.mode.findData(event.event_id))
        self.mode.blockSignals(False)
        self.assumed_dates.blockSignals(True)
        self.assumed_dates.setChecked(self.review_preferences.allow_assumed_posting_dates)
        self.assumed_dates.blockSignals(False)
        self._clear_draft()
        self.bank.blockSignals(True)
        self.bank.addItem("Choose the actual complete bank outflow", None)
        for bank in snapshot.bank_movements:
            self.bank.addItem(self._bank_caption(bank), bank.row_id)
            self.bank.setItemData(
                self.bank.count() - 1,
                f"{self._bank_caption(bank)}\nSource {bank.source_sha256}; row {bank.row_id}",
                Qt.ToolTipRole,
            )
        if event is not None:
            self.bank.setCurrentIndex(self.bank.findData(event.manifest.bank.row_id))
        self.bank.blockSignals(False)
        selected_rows = {proof.row_id for proof in event.manifest.components} if event else set()
        account_kinds = {account.id: account.kind for account in snapshot.accounts}
        self.components.blockSignals(True)
        self.components.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            proof = row.proof
            values = (
                "",
                f"{row.activity_date or 'Unknown'} (activity)",
                f"{proof.effective_date} (assumed)" if proof else "Unavailable",
                _identity(row.account_id, row.account_name, account_kinds.get(row.account_id), row.tracking_scope),
                _money(row.amount_minor),
                _money(proof.principal_minor) if proof else "Unavailable",
                _money(proof.interest_minor) if proof else "Unavailable",
                "Eligible for explicit review"
                if row.eligible
                else " ".join(
                    REASONS.get(code, "This row is outside the admitted loan payment review.") for code in row.blockers
                ),
                row.source_sha256[:16],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row.row_id)
                item.setToolTip(str(value))
                if column == 0:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    if not row.eligible:
                        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    item.setCheckState(Qt.Checked if row.row_id in selected_rows else Qt.Unchecked)
                self.components.setItem(index, column, item)
        self.components.blockSignals(False)
        self.components.resizeRowsToContents()
        if event is not None:
            actions = tuple(action for action in snapshot.actions if action.event_id == event.event_id)
            self.history_details.setPlainText(
                f"{event.status.title()} event {event.event_id}; version {event.version}; saved {event.created_at}.\n"
                f"Reference: {event.reference}\nOriginal reason: {event.reason}\n"
                f"Journal entries: {', '.join(event.entry_keys)}\nReplacement event: {event.replacement_event_id or 'none'}\n"
                + "\n".join(
                    f"Retained whole-event action: {action.reason}; replacement {action.replacement_event_id or 'none'}; saved {action.created_at}."
                    for action in actions
                )
                + "\n\n"
                + manifest_details(event.manifest)
                + "\n\n"
                + "\n\n".join(component_details(proof) for proof in event.manifest.components)
            )
            self.history_source.addItem(
                f"Bank source {event.manifest.bank.source_sha256}", event.manifest.bank.source_sha256
            )
            for source in dict.fromkeys(proof.source_sha256 for proof in event.manifest.components):
                self.history_source.addItem(f"Loan component source {source}", source)
            self.open_history_source.setEnabled(True)
        self._draft_changed()

    def _clear_draft(self):
        self.reference.clear()
        self.reason.clear()
        self.bank.blockSignals(True)
        self.bank.clear()
        self.bank.blockSignals(False)
        _fill(self.components, ())
        _fill(self.entry_table, ())
        self.source_details.clear()
        self.preview_details.clear()
        self.history_details.setPlainText(
            "Select a saved event to inspect its full source/component proof and whole-event actions."
        )
        self.history_source.clear()
        self.open_history_source.setEnabled(False)
        self.open_bank.setEnabled(False)
        self.open_component.setEnabled(False)
        self.summary.setText(
            "Explicitly choose one bank outflow and complete printed loan components. No counterpart or grouping is inferred."
        )
        self._update_actions()

    def _component_selected(self):
        index = self.components.currentRow()
        row = self.rows[index] if 0 <= index < len(self.rows) else None
        self.open_component.setEnabled(row is not None)
        self.source_details.setPlainText(
            component_details(row.proof)
            if row and row.proof
            else pending_component_details(row)
            if row
            else "Select a loan row to inspect printed values and date provenance."
        )
        if row is not None and row.proof is not None:
            self.source_details.appendPlainText(
                "Eligibility: "
                + (
                    "explicit review available"
                    if row.eligible
                    else " ".join(
                        REASONS.get(code, "This row is outside the admitted loan payment review.")
                        for code in row.blockers
                    )
                )
            )

    def _draft_changed(self, *_args):
        self.preview = None
        self.open_bank.setEnabled(self.bank.currentData() in self.banks)
        self._component_selected()
        _fill(self.entry_table, ())
        self.preview_details.clear()
        if self.snapshot is None or self.bank.currentData() is None or not self._component_ids():
            self.summary.setText(
                "Choose one actual bank outflow and explicitly check supported complete loan rows. No automatic grouping or matching is used."
            )
            self._update_actions()
            return
        if self.selected_event is not None and self.selected_event.status != "active":
            self.summary.setText("Historical event: inspect Saved event / history. Start New for a fresh review.")
            self._update_actions()
            return
        if self.workspace.preferences() != self.review_preferences:
            self.refresh()
            self.status.setText(
                "Posting-date preferences changed. The draft was reset to the current visible preference."
            )
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                preview = store.loan_payment_preview(
                    self.bank.currentData(),
                    self._component_ids(),
                    preferences=self.review_preferences,
                    expected_basis_sha256=self.snapshot.basis_sha256,
                    replacing_event_id=self.selected_event.event_id if self.selected_event else None,
                )
            if preview.basis_sha256 != self.snapshot.basis_sha256:
                raise ProfileFormatError("loan_changed_since_selection")
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            if "changed_since_selection" in str(exc):
                self.refresh()
                self.status.setText(REASONS.get(str(exc), REASONS["loan_changed_since_selection"]))
                return
            if isinstance(exc, (sqlite3.Error, OSError)) or "integrity" in str(exc):
                self.snapshot = self.preview = self.selected_event = None
                self.banks, self.rows, self.labels = {}, (), {}
                self._clear_draft()
                self.status.setText("Loan source or history could not be verified. Reload before another action.")
                return
            self.summary.setText(
                "Preview unavailable. "
                + REASONS.get(
                    str(exc),
                    "The selected sources do not support this exact payment; inspect scope, full components, dates and source use.",
                )
            )
            self._update_actions()
            return
        self.preview = preview
        manifest = preview.manifest
        self.summary.setText(
            f"Full bank outflow {_money(-manifest.bank.amount_minor)} = principal {_money(manifest.principal_minor)} + printed interest {_money(manifest.interest_minor)}. "
            "Loan activity dates remain observed; accounting dates are assumed, never reported posting dates. Separate dates retain clearing. "
            "Raw gross use and derived principal allocations remain distinct. Unknown opening stays unknown."
        )
        names = {
            **self.labels,
            INTEREST: "Loan interest (fixed built-in expense)",
            CLEARING: "Transfer clearing (unresolved between dates)",
        }
        _fill(
            self.entry_table,
            tuple(
                (
                    f"{entry.posting_date.isoformat()} ({'bank source date' if index == 0 else 'assumed loan accounting date'})",
                    names.get(posting.account_id, posting.account_id),
                    _money(posting.amount_minor),
                    "; ".join(
                        f"{allocation.observation_id}: {_money(allocation.amount_minor)}"
                        for allocation in posting.allocations
                    )
                    or "Component proof / no financial source allocation",
                )
                for index, entry in enumerate(preview.entries)
                for posting in entry.postings
            ),
        )
        self.preview_details.setPlainText(manifest_details(manifest))
        self._update_actions()

    def _update_actions(self, *_args):
        if not hasattr(self, "confirm"):
            return
        event = self.selected_event
        active = event is not None and event.status == "active"
        changed = self.preview is not None and (event is None or self.preview.manifest != event.manifest)
        self.confirm.setText("Confirm whole payment replacement" if event else "Confirm evidenced loan payment")
        self.confirm.setEnabled(
            bool(
                self.snapshot
                and self.preview
                and changed
                and (event is None or active)
                and self.reference.text().strip()
                and self.reason.text().strip()
            )
        )
        self.withdraw.setEnabled(bool(self.snapshot and active and self.reason.text().strip()))
        if self.snapshot is None:
            self.status.setText("Reload verified state before reviewing another payment.")
        elif event is not None and not active:
            self.status.setText(
                "Historical event; all original entries, source uses and action reasons remain inspectable."
            )
        else:
            self.status.setText(
                "Draft only. Inspect the exact journal preview and all date assumptions before confirming. Interest is the only expense; no balance is inferred."
                if self.preview
                else self.summary.text()
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

    def _open_source(self, source_sha256):
        try:
            preview_saved_source(self.workspace.profile_path, source_sha256, parent=self).exec()
        except (ProfileFormatError, sqlite3.Error, OSError):
            self.refresh()
            self.status.setText(
                "The selected immutable source could not be opened. Inspect reloaded state before another action."
            )

    def _preview_bank(self):
        bank = self.banks.get(self.bank.currentData())
        if bank:
            self._open_source(bank.source_sha256)

    def _preview_component(self):
        index = self.components.currentRow()
        if 0 <= index < len(self.rows):
            self._open_source(self.rows[index].source_sha256)

    def _post(self):
        if not self.confirm.isEnabled() or self.preview is None or self.snapshot is None:
            return
        preview, snapshot, event = self.preview, self.snapshot, self.selected_event
        reference, reason = self.reference.text().strip(), self.reason.text().strip()
        message = (
            (
                "Replace the WHOLE saved payment?\n\nInverse original entries at their original dates:\n"
                + manifest_details(event.manifest, inverse=True)
                + "\n\nReplacement entry effects only; the original bank and all loan legs are reversed first:\n"
                if event
                else "Post this explicitly reviewed payment?\n\nNew entry effects:\n"
            )
            + manifest_details(preview.manifest)
            + f"\n\nReference: {reference}\nReason: {reason}\n\nFailure preserves the original event and all source use."
        )
        if (
            QMessageBox.question(
                self, "Confirm whole loan payment replacement" if event else "Confirm evidenced loan payment", message
            )
            != QMessageBox.Yes
        ):
            return
        if self.workspace.preferences() != self.review_preferences:
            self.refresh()
            self.status.setText(
                "Posting-date preferences changed during confirmation. Rebuild the draft under the current visible choice."
            )
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                kwargs = {
                    "expected_basis_sha256": snapshot.basis_sha256,
                    "preferences": self.review_preferences,
                    "reference": reference,
                    "reason": reason,
                }
                if event:
                    saved_id = store.replace_reviewed_loan(
                        event.event_id,
                        preview.manifest.bank.row_id,
                        tuple(proof.row_id for proof in preview.manifest.components),
                        expected_event_version=event.version,
                        **kwargs,
                    )
                else:
                    saved_id = store.post_reviewed_loan_payment(
                        preview.manifest.bank.row_id,
                        tuple(proof.row_id for proof in preview.manifest.components),
                        **kwargs,
                    )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.refresh()
            self.status.setText(
                "Payment was not recorded. "
                + REASONS.get(
                    str(exc), "Inspect refreshed sources, scopes, complete components and current event history."
                )
            )
            return
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(0)
        self.mode.blockSignals(False)
        self._requested_event_id = saved_id.event_id
        self.refresh()
        self.status.setText(
            "The selected payment review is recorded. Refreshed full history shows the current state; source facts and date provenance are retained."
        )

    def _withdraw(self):
        event = self.selected_event
        if not self.withdraw.isEnabled() or event is None:
            return
        reason = self.reason.text().strip()
        message = (
            "Withdraw this WHOLE payment?\n\nInverse effects at the original dates:\n"
            + manifest_details(event.manifest, inverse=True)
            + f"\n\nReason: {reason}\nAll bank and loan legs are reversed together; raw and derived uses are released. Originals and proofs remain history. This does not undo any bank or loan transaction."
        )
        if QMessageBox.question(self, "Confirm whole loan payment withdrawal", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.withdraw_reviewed_loan(event.event_id, expected_event_version=event.version, reason=reason)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.refresh()
            self.status.setText(
                "Withdrawal was not recorded. "
                + REASONS.get(str(exc), "Inspect refreshed event history before another action.")
            )
            return
        self.refresh()
        self.status.setText(
            "The selected whole-payment withdrawal is recorded. Refreshed history shows current state; original and inverse entries remain inspectable."
        )

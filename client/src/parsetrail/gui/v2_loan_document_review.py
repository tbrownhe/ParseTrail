"""Source-focused loan landing; the existing loan service owns every financial decision."""

import sqlite3
from weakref import ref

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.source_evidence import ObservationEvidence
from parsetrail.core.v2_loan_automation import AUTOMATIC_REASON
from parsetrail.core.v2_profile_store import ProfileFormatError
from parsetrail.gui.v2_evidence_preview import _money, preview_saved_source
from parsetrail.gui.v2_form_state import install_form_styles, set_field_state
from parsetrail.gui.v2_gui_lifetime import exec_disposable
from parsetrail.gui.v2_loan_payment_review import REASONS, V2LoanPaymentReview
from parsetrail.gui.v2_profile_jobs import ProfileJobs


class _LoanNavigation:
    def __init__(self, owner):
        self._owner = ref(owner)

    def reveal_row(self, row_id):
        owner = self._owner()
        if owner is not None:
            owner._selected_after_read = row_id
            return owner._select_row(row_id)
        return False

    def current(self):
        owner = self._owner()
        return owner._current() if owner is not None else None


class V2LoanDocumentReview(QWidget):
    """A reusable, read-only source landing with an explicit whole-payment action."""

    changed = Signal()
    initial_posted = Signal(str)
    transfers_requested = Signal(str)

    def __init__(self, workspace, source_sha256, parent=None):
        super().__init__(parent)
        install_form_styles(self)
        self.workspace, self.source_sha256 = workspace, source_sha256
        self.rows, self.snapshot = (), None
        self._events = {}
        self.resolution_states = {}
        self.origination_rows = {}
        self.origination_events = {}
        self._selected_after_read = None
        self.navigation = _LoanNavigation(self)
        self.jobs = ProfileJobs(self, workspace.profile_path)
        self.jobs.completed.connect(self._loaded)
        self.jobs.failed.connect(self._failed)
        self.jobs.busy_changed.connect(self._busy)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Loan activity")
        title.setStyleSheet("font-weight: 600; font-size: 16px")
        layout.addWidget(title)
        self.explanation = QLabel(
            "Review origination or payment evidence. Payments can post now and be matched to the paying account later in Transfers."
        )
        self.explanation.setWordWrap(True)
        layout.addWidget(self.explanation)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("Activity date", "Description", "Source total", "Principal", "Interest", "Review state")
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table, 1)
        self.components = QLabel()
        self.components.setWordWrap(True)
        self.components.setTextFormat(Qt.PlainText)
        self.components.setStyleSheet("font-weight: 600")
        layout.addWidget(self.components)
        self.status = QLabel("Loading loan evidence…")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        limits = QLabel(
            "Principal-only loan scope · an unknown opening stays unknown. Component arithmetic does not establish complete statement capture or reconciliation."
        )
        limits.setWordWrap(True)
        layout.addWidget(limits)
        actions = QHBoxLayout()
        self.action_button = QPushButton("Review loan payment…")
        self.action_button.clicked.connect(self._review_payment)
        actions.addWidget(self.action_button)
        self.source_button = QPushButton("View statement evidence…")
        self.source_button.clicked.connect(self._open_source)
        actions.addWidget(self.source_button)
        self.transfers_button = QPushButton("Resolve in Transfers…")
        self.transfers_button.clicked.connect(self._resolve_transfer)
        self.transfers_button.hide()
        actions.addWidget(self.transfers_button)
        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self.refresh)
        actions.addWidget(reload_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.refresh()

    @property
    def review_pending(self):
        return self.jobs.pending

    @property
    def has_unsaved_draft(self):
        return False

    def request_cancel(self):
        return self.jobs.close()

    def refresh_preserving_draft(self):
        self.refresh()

    def refresh(self):
        current = self._current()
        if self._selected_after_read is None and current is not None:
            self._selected_after_read = current.row_id
        source, preferences = self.source_sha256, self.workspace.preferences()

        def read(store, cancelled):
            if cancelled():
                return None
            snapshot = store.loan_review_snapshot(preferences, source_sha256=source)
            resolution = store.resolution_snapshot(preferences=preferences)
            origination = store.origination_snapshot(source_sha256=source)
            return snapshot, {item.id: item.status for item in resolution.items}, origination

        self.jobs.submit("loan_document", read)

    def _loaded(self, _key, result):
        if result is None:
            return
        snapshot, self.resolution_states, origination = result
        self.origination_rows = {row.row_id: row for row in origination.rows}
        self.origination_events = {event.row_id: event for event in origination.events if event.status == "active"}
        self.snapshot, self.rows = snapshot, snapshot.components
        self._events = {
            proof.row_id: event
            for event in snapshot.history
            if event.status == "active"
            for proof in event.manifest.components
        }
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            evidence = ObservationEvidence.model_validate_json(row.row_evidence)
            parts = {part.role: part.amount for part in evidence.components}
            values = (
                row.activity_date or "Unknown",
                row.description or "Description not printed",
                _money(row.amount_minor),
                _money(parts["principal"].minor) if "principal" in parts else "Not printed separately",
                _money(parts["interest"].minor) if "interest" in parts else "Not printed separately",
                "Posted origination"
                if self._is_origination(row) and row.row_id in self.origination_events
                else "Origination · ready to review"
                if self._is_origination(row)
                else "Automatically posted · counterpart unresolved"
                if self._event(row) is not None
                and self._event(row).reason == AUTOMATIC_REASON
                and self._event_unresolved(self._event(row))
                else "Posted · counterpart unresolved"
                if self._event(row) is not None and self._event_unresolved(self._event(row))
                else "Automatically posted · matched"
                if self._event(row) is not None and self._event(row).reason == AUTOMATIC_REASON
                else "Posted · matched"
                if self._event(row) is not None
                else "Ready for payment review"
                if row.eligible
                else "Review accounting date"
                if set(row.blockers) == {"loan_assumed_date_disabled"}
                else "Needs attention",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(index, column, item)
        self.table.blockSignals(False)
        if not self._select_row(self._selected_after_read) and self.rows:
            self.table.selectRow(0)
        self._selected_after_read = None
        self._selected()

    def _select_row(self, row_id):
        for index, row in enumerate(self.rows):
            if row.row_id == row_id:
                self.table.selectRow(index)
                self.table.scrollToItem(self.table.item(index, 0))
                return True
        return False

    def _current(self):
        selected = self.table.selectionModel().selectedRows()
        index = selected[0].row() if selected else -1
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def _event(self, row):
        return self._events.get(row.row_id)

    def _event_unresolved(self, event):
        return event.manifest.bank is None and self.resolution_states.get(event.event_id) != "matched"

    @staticmethod
    def _is_origination(row):
        return (row.description or "").strip().casefold() == "amount financed"

    def _selected(self):
        row = self._current()
        self.action_button.setEnabled(row is not None and row.account_id is not None and not self.jobs.pending)
        saved = row is not None and (
            row.row_id in self.origination_events if self._is_origination(row) else self._event(row) is not None
        )
        set_field_state(self.action_button, "ready" if self.action_button.isEnabled() and not saved else "neutral")
        complete = bool(self.rows) and all(
            item.row_id in self.origination_events if self._is_origination(item) else self._event(item) is not None
            for item in self.rows
        )
        self.explanation.setText(
            "Review complete. You can inspect the saved evidence or resolve unmatched counterparts in Transfers."
            if complete
            else "Review origination or payment evidence. Payments can post now and be matched to the paying account later in Transfers."
        )
        self.transfers_button.setVisible(False)
        if row is None:
            self.components.clear()
            self.status.setText(
                "Select a payment to inspect its components."
                if self.rows
                else "No supported loan activity was captured. Inspect the source evidence."
            )
            return
        proof = row.proof
        if self._is_origination(row):
            self.components.setText(
                f"Loan origination · amount financed {_money(row.amount_minor)}. This is not a repayment."
            )
            event = self.origination_events.get(row.row_id)
            self.action_button.setText("View loan origination" if event else "Review loan origination…")
            if event:
                destination = next(
                    (account.name for account in self.snapshot.accounts if account.id == event.destination_account_id),
                    "Unknown",
                )
                allocated = event.acquisition_date is not None
                self.transfers_button.setVisible(not allocated)
                self.transfers_button.setEnabled(not self.jobs.pending)
                matched = self.resolution_states.get(event.event_id) == "matched"
                self.transfers_button.setText("View in Transfers…" if matched else "Resolve in Transfers…")
                self.status.setText(
                    f"Posted financing · destination: {destination}. "
                    + (
                        f"Financed principal allocated on {event.acquisition_date}. "
                        if allocated
                        else "Counterpart matched in Transfers. "
                        if matched
                        else "Counterpart unresolved in Transfers. "
                    )
                    + (
                        f"Reviewed acquisition cost {_money(event.acquisition_value_minor)}; valuation estimates stay independent."
                        if event.mode == "acquisition"
                        else "Full acquisition cost remains unknown; valuation estimates stay independent."
                    )
                )
            elif row.account_id is None:
                self.status.setText("Assign the source to a loan-principal account before reviewing its origination.")
            else:
                self.status.setText(
                    "Review the financed principal now. Destination is optional; full acquisition cost remains unknown and asset estimates are independent."
                )
            return
        if proof is not None:
            self.components.setText(
                f"Payment total {_money(proof.gross_minor)} · principal {_money(proof.principal_minor)} · interest {_money(proof.interest_minor)} · Components match total"
            )
        else:
            self.components.setText(
                "Printed component facts are retained; resolve the account or component prerequisites below."
            )
        event = self._event(row)
        self.action_button.setText("View payment" if event else "Review loan payment…")
        if event:
            unresolved = self._event_unresolved(event)
            self.transfers_button.setVisible(event.manifest.bank is None)
            self.transfers_button.setText("Resolve in Transfers…" if unresolved else "View in Transfers…")
            self.transfers_button.setEnabled(not self.jobs.pending)
            self.status.setText(
                ("Automatically posted · " if event.reason == AUTOMATIC_REASON else "Posted · ")
                + "paying-account counterpart unresolved. Resolve it later in Transfers."
                if unresolved
                else ("Automatically posted · " if event.reason == AUTOMATIC_REASON else "Posted · ")
                + "matched payment. Inspect its retained evidence or history."
            )
        else:
            messages = [
                REASONS.get(code, "This payment needs further review.")
                for code in row.blockers
                if code != "loan_assumed_date_disabled"
            ]
            messages.append(
                "Review the printed payment and its assumed accounting date. The paying account can be resolved later."
            )
            self.status.setText(" ".join(messages))

    def _review_payment(self):
        row = self._current()
        if row is None or self.jobs.pending:
            return
        event = self._event(row)
        if self._is_origination(row):
            from parsetrail.gui.v2_loan_origination_review import V2LoanOriginationReview

            dialog = V2LoanOriginationReview(
                self.workspace, self, source_sha256=self.source_sha256, focus_row_id=row.row_id
            )
            try:
                dialog.exec()
                posted = dialog.initial_posting_succeeded
            finally:
                dialog.deleteLater()
            self.refresh()
            self.changed.emit()
            if posted:
                self.initial_posted.emit(self.source_sha256)
            return
        dialog = V2LoanPaymentReview(
            self.workspace,
            self,
            event_id=event.event_id if event else None,
            source_sha256=self.source_sha256,
            focus_row_id=row.row_id,
        )
        dialog.transfers_requested.connect(self.transfers_requested)
        try:
            dialog.exec()
            posted = dialog.initial_posting_succeeded
        finally:
            dialog.deleteLater()
        self.refresh()
        self.changed.emit()
        if posted:
            self.initial_posted.emit(self.source_sha256)

    def _resolve_transfer(self):
        row = self._current()
        if row is not None and not self.jobs.pending:
            self.transfers_requested.emit(row.row_id)

    def _open_source(self):
        try:
            exec_disposable(preview_saved_source(self.workspace.profile_path, self.source_sha256, parent=self))
        except (ProfileFormatError, sqlite3.Error, OSError):
            self.refresh()
            self.status.setText("The saved evidence could not be opened. Reload and inspect it before continuing.")

    def _busy(self, _busy):
        self._selected()

    def _failed(self, _key, _error):
        self.rows, self.snapshot = (), None
        self.table.setRowCount(0)
        self.components.clear()
        self.action_button.setEnabled(False)
        set_field_state(self.action_button, "neutral")
        self.status.setText("Loan evidence is unavailable. Reload to retry; saved work is unchanged.")

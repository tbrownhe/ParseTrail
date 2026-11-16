"""Explicit full-source loan payment review over the authoritative profile service."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.source_evidence import ObservationEvidence
from parsetrail.core.v2_cash_movement import cash_account_labels
from parsetrail.core.v2_loan_payments import CLEARING, INTEREST
from parsetrail.core.v2_profile_store import ProfileFormatError
from parsetrail.gui.v2_cash_activity_review import _money
from parsetrail.gui.v2_details_disclosure import DetailsDisclosure
from parsetrail.gui.v2_evidence_preview import _location, preview_saved_source
from parsetrail.gui.v2_form_state import install_initial_focus
from parsetrail.gui.v2_gui_lifetime import exec_disposable
from parsetrail.gui.v2_profile_jobs import ProfileJobs

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
    result = (
        [
            f"{'Inverse original' if inverse else 'Reviewed'} bank source: "
            f"{_identity(bank.account_id, bank.account_name, bank.account_kind, bank.tracking_scope)}; "
            f"asset value change {_money(sign * bank.amount_minor)} on {bank.posting_date} ({bank.date_provenance}).\n"
            f"Source {bank.source_sha256}; full raw row {bank.row_id}."
        ]
        if bank is not None
        else [
            "This lender-only manifest contains no bank leg. Its current bank relationship is tracked in Transfers; no bank transaction is invented by this record."
        ]
    )
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

    def __init__(self, workspace, parent=None, *, event_id=None, source_sha256=None, focus_row_id=None):
        super().__init__(parent)
        install_initial_focus(self)
        self.workspace = workspace
        self.jobs = ProfileJobs(self, workspace.profile_path)
        self.jobs.completed.connect(self._job_completed)
        self.jobs.failed.connect(self._job_failed)
        self.jobs.busy_changed.connect(self._busy_changed)
        self.snapshot = self.preview = self.selected_event = None
        self._requested_event_id = event_id
        self._source_sha256 = source_sha256
        self._focus_row_id = focus_row_id
        self._open_saved_history = event_id is not None
        self.labels, self.banks, self.rows = {}, {}, ()
        self.resolution_states = {}
        self.review_preferences = workspace.preferences()
        self.setWindowTitle("2.0 evidenced loan payments")
        self.resize(1050, 700)
        self._reference_selection = None
        self._source_context = "All loan statements · principal-component scope"
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.context = _label("Loan statements · principal-component scope")
        self.context.setStyleSheet("font-weight: 600")
        header.addWidget(self.context, 1)
        self.profile_path = QLineEdit(str(workspace.profile_path))
        self.profile_path.setReadOnly(True)
        self.profile_path.setCursorPosition(0)
        self.reload = QPushButton("Reload saved state / reset draft")
        self.reload.clicked.connect(self.refresh)
        header.addWidget(self.reload)
        layout.addLayout(header)
        self.mode = QComboBox()
        self.mode.setMinimumContentsLength(35)
        self.mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.mode)
        self.assumed_dates = QCheckBox("Allow best guess posting dates when a statement does not print one")
        self.assumed_dates.setChecked(self.review_preferences.allow_assumed_posting_dates)
        self.assumed_dates.toggled.connect(self._toggle_dates)
        layout.addWidget(self.assumed_dates)
        rules_text = _label(
            "Review complete printed loan components. The paying account can be resolved later in Transfers. "
            "Loan dates are observed activity dates; accounting dates require the explicit assumed-date choice. "
            "Nonzero fees, incomplete components and unsupported source/account scopes stay pending. Unknown opening stays unknown."
        )
        rules_content = QWidget()
        rules_layout = QVBoxLayout(rules_content)
        rules_layout.setContentsMargins(0, 0, 0, 0)
        rules_layout.addWidget(rules_text)
        rules_layout.addWidget(_label("Profile path"))
        rules_layout.addWidget(self.profile_path)
        self.rules = DetailsDisclosure(rules_content, self, subject="review rules and date qualifications")
        layout.addWidget(self.rules)
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
        self.entry_table.setColumnHidden(3, True)
        self.entry_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.entry_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.entry_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.entry_table.setMinimumHeight(0)
        preview_splitter = QSplitter(Qt.Vertical)
        preview_splitter.addWidget(self.entry_table)
        self.preview_details = QPlainTextEdit()
        self.preview_details.setReadOnly(True)
        self.preview_details.setMinimumHeight(0)
        self.preview_details.setMaximumHeight(150)
        self.preview_disclosure = DetailsDisclosure(self.preview_details, self, subject="journal source details")
        preview_splitter.addWidget(self.preview_disclosure)
        preview_splitter.setSizes([270, 110])
        preview_layout.addWidget(preview_splitter, 1)
        self.tabs.addTab(preview_panel, "Exact journal preview")
        history_panel = QWidget()
        history_layout = QVBoxLayout(history_panel)
        self.history_details = QPlainTextEdit()
        self.history_details.setReadOnly(True)
        self.history_details.setMinimumHeight(0)
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
        self.reference.setPlaceholderText("Reference to the statement evidence; edit if useful")
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
        self.resolve_button = QPushButton("Resolve in Transfers…")
        self.resolve_button.clicked.connect(self._resolve_transfer)
        self.resolve_button.hide()
        actions.addWidget(self.resolve_button)
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
        bank_row.addWidget(_label("Paying account"))
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
                "Select the payment components to post. Match a paying-account transaction now, or resolve it later in Transfers."
            )
        )
        self.components = _table(
            (
                "Use",
                "Activity date",
                "Accounting date",
                "Loan account",
                "Source total",
                "Principal",
                "Interest",
                "Status",
                "Source",
            )
        )
        for column, width in enumerate((40, 105, 120, 180, 95, 85, 85, 170, 150)):
            self.components.setColumnWidth(column, width)
        for column in (0, 1, 2, 4, 5, 6):
            self.components.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        for column in (3, 7):
            self.components.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
        self.components.setMinimumHeight(0)
        self.components.setColumnHidden(8, True)
        self.components.itemChanged.connect(self._draft_changed)
        self.components.itemSelectionChanged.connect(self._component_selected)
        self.source_splitter = QSplitter(Qt.Vertical)
        self.source_splitter.addWidget(self.components)
        self.source_details = QPlainTextEdit()
        self.source_details.setReadOnly(True)
        self.source_details.setMinimumHeight(0)
        self.source_details.setMaximumHeight(140)
        self.source_disclosure = DetailsDisclosure(self.source_details, self, subject="selected source evidence")
        self.source_splitter.addWidget(self.source_disclosure)
        self.source_splitter.setStretchFactor(0, 1)
        self.source_splitter.setStretchFactor(1, 0)
        self.source_disclosure.toggled.connect(self._resize_source_details)
        self.source_splitter.setSizes([500, 28])
        layout.addWidget(self.source_splitter, 1)
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
        return f"{self.labels.get(movement.account_id, movement.account_name)} · {movement.posting_date} ({movement.date_provenance}) · {_money(movement.amount_minor)}"

    def refresh(self, *_args):
        if self.jobs.writing:
            return
        selected_id = self.mode.currentData() or self._requested_event_id
        self._requested_event_id = None
        self.snapshot = self.preview = self.selected_event = None
        self.review_preferences = self.workspace.preferences()
        self._clear_draft()
        self.status.setText("Loading verified loan sources and saved history...")
        preferences = self.review_preferences
        source = self._source_sha256

        def read(store, cancelled):
            snapshot = store.loan_review_snapshot(preferences, source_sha256=source)
            event = next(
                (
                    item
                    for item in snapshot.history
                    if item.event_id == selected_id
                    and (source is None or any(proof.source_sha256 == source for proof in item.manifest.components))
                ),
                None,
            )
            if event is not None and event.status == "active" and not cancelled():
                snapshot = store.loan_review_snapshot(
                    preferences, source_sha256=source, replacing_event_id=event.event_id
                )
                event = next(item for item in snapshot.history if item.event_id == selected_id)
            resolution = store.resolution_snapshot(preferences=preferences)
            context = "All loan statements · principal-component scope"
            if source is not None:
                payload = store.load_import(source).evidence.payload
                start = getattr(payload, "start", None) or getattr(payload, "activity_start", None)
                end = getattr(payload, "end", None) or getattr(payload, "activity_end", None)
                names = tuple(dict.fromkeys(row.account_name or "Account not assigned" for row in snapshot.components))
                context = " / ".join(names) + " · principal component · "
                context += f"{start.iso if start and start.iso else 'Unknown start'} to {end.iso if end and end.iso else 'unknown end'}"
            return snapshot, event, {item.id: item.status for item in resolution.items}, context

        self.jobs.submit(("snapshot", selected_id), read)

    def _apply_snapshot(self, snapshot, event, resolution_states=None, context=None):
        self.snapshot, self.selected_event = snapshot, event
        self.resolution_states = resolution_states or {}
        self.context.setText(context or "All loan statements · principal-component scope")
        self._source_context = self.context.text()
        self.labels = cash_account_labels(snapshot.accounts)
        self.banks = {bank.row_id: bank for bank in snapshot.bank_movements}
        self.rows = snapshot.components
        self.mode.blockSignals(True)
        self.mode.clear()
        self.mode.addItem("New evidenced loan payment — draft", None)
        for item in snapshot.history:
            if self._source_sha256 is not None and not any(
                proof.source_sha256 == self._source_sha256 for proof in item.manifest.components
            ):
                continue
            self.mode.addItem(
                f"{item.status.title()} · {item.manifest.components[0].activity_date} · principal {_money(item.manifest.principal_minor)} · interest {_money(item.manifest.interest_minor)}",
                item.event_id,
            )
            self.mode.setItemData(self.mode.count() - 1, item.event_id, Qt.ToolTipRole)
        if event is not None:
            self.mode.setCurrentIndex(self.mode.findData(event.event_id))
        self.mode.blockSignals(False)
        self.assumed_dates.blockSignals(True)
        self.assumed_dates.setChecked(self.review_preferences.allow_assumed_posting_dates)
        self.assumed_dates.blockSignals(False)
        self._clear_draft()
        if event is None:
            self.reason.setText("Initial Review")
        self.bank.blockSignals(True)
        self.bank.addItem("Resolve paying account later in Transfers", None)
        for bank in snapshot.bank_movements:
            self.bank.addItem(self._bank_caption(bank), bank.row_id)
            self.bank.setItemData(
                self.bank.count() - 1,
                f"{self._bank_caption(bank)}\nSource {bank.source_sha256}; row {bank.row_id}",
                Qt.ToolTipRole,
            )
        if event is not None and event.manifest.bank is not None:
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
                row.account_name or "Account not assigned",
                _money(row.amount_minor),
                _money(proof.principal_minor) if proof else "Unavailable",
                _money(proof.interest_minor) if proof else "Unavailable",
                "Posted · matched"
                if event is not None
                and row.row_id in selected_rows
                and (event.manifest.bank is not None or self.resolution_states.get(event.event_id) == "matched")
                else "Posted · counterpart unresolved"
                if event is not None and row.row_id in selected_rows
                else "Eligible for explicit review"
                if row.eligible
                else "; ".join(
                    {
                        "loan_account_assignment_required": "Assign financial account",
                        "loan_principal_scope_required": "Requires principal component",
                        "loan_component_unsupported": "Loan origination — review from statement"
                        if (row.description or "").casefold() == "amount financed"
                        else "Components need review",
                        "loan_source_already_used": "Already reviewed",
                        "loan_assumed_date_disabled": "Assumed date disabled (default-off)",
                        "source_overlap_review_required": "Repeated source needs review",
                    }.get(code, "Select for review limits")
                    for code in row.blockers
                ),
                row.source_sha256[:16],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row.row_id)
                item.setToolTip(
                    " ".join(REASONS.get(code, code) for code in row.blockers)
                    if column == 7 and row.blockers
                    else _identity(
                        row.account_id, row.account_name, account_kinds.get(row.account_id), row.tracking_scope
                    )
                    if column == 3
                    else str(value)
                )
                if column in (4, 5, 6):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if column == 0:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    if not row.eligible:
                        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    item.setCheckState(Qt.Checked if row.row_id in selected_rows else Qt.Unchecked)
                self.components.setItem(index, column, item)
        self.components.blockSignals(False)
        self.components.resizeRowsToContents()
        if self._focus_row_id is not None:
            for index, row in enumerate(self.rows):
                if row.row_id == self._focus_row_id:
                    self.components.selectRow(index)
                    self.components.scrollToItem(self.components.item(index, 0))
                    break
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
            if event.manifest.bank is not None:
                self.history_source.addItem(
                    f"Bank source {event.manifest.bank.source_sha256}", event.manifest.bank.source_sha256
                )
            for source in dict.fromkeys(proof.source_sha256 for proof in event.manifest.components):
                self.history_source.addItem(f"Loan component source {source}", source)
            self.open_history_source.setEnabled(True)
        if event is not None and self._open_saved_history:
            self._open_saved_history = False
            self.tabs.setCurrentIndex(self.tabs.count() - 1)
            self.summary.setText(
                "Saved reviewed payment. Current date preferences do not invalidate it. "
                "Inspect its source evidence here; use Bank and printed components to propose a replacement."
            )
            self._update_actions()
        else:
            self._draft_changed()
        if event is not None and event.status != "active":
            self.tabs.setCurrentIndex(self.tabs.count() - 1)
        if getattr(self, "_notice", None):
            self.status.setText(self._notice)
            if not self.jobs.pending:
                self._notice = None

    def _clear_draft(self):
        self.reference.clear()
        self._reference_selection = None
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
            "Select the complete printed payment components. The paying account can be resolved later."
        )
        self._update_actions()

    def _component_selected(self):
        index = self.components.currentRow()
        row = self.rows[index] if 0 <= index < len(self.rows) else None
        if row is None:
            checked = self._component_ids()
            if len(checked) == 1:
                row = next((item for item in self.rows if item.row_id == checked[0]), None)
        if self._source_sha256 is None:
            self.context.setText(
                self._source_context + (f" · {row.account_name}" if row is not None and row.account_name else "")
            )
        self.source_disclosure.button.setEnabled(row is not None)
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

    def _resize_source_details(self, expanded):
        height = 175 if expanded else 28
        self.source_splitter.setSizes([max(120, self.source_splitter.height() - height), height])

    def _draft_changed(self, *_args):
        if self.jobs.writing:
            return
        self.jobs.cancel_reads()
        self.preview = None
        self.open_bank.setEnabled(self.bank.currentData() in self.banks)
        self._component_selected()
        _fill(self.entry_table, ())
        self.preview_details.clear()
        if self.snapshot is None or not self._component_ids():
            self.summary.setText(
                "Select the complete printed payment components. Matching a paying-account transaction is optional."
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
        bank_id, component_ids = self.bank.currentData(), self._component_ids()
        selection = (bank_id, component_ids)
        if selection != self._reference_selection:
            self._reference_selection = selection
            selected = [row for row in self.rows if row.row_id in component_ids]
            self.reference.setText(
                "; ".join(
                    f"{row.account_name or 'Loan'} · {row.activity_date or 'date unknown'} · {row.description or 'printed payment'}"
                    for row in selected
                )[:500]
            )
        preferences, basis = self.review_preferences, self.snapshot.basis_sha256
        replacing = self.selected_event.event_id if self.selected_event else None

        def read(store, _cancelled):
            preview = store.loan_payment_preview(
                bank_id,
                component_ids,
                preferences=preferences,
                expected_basis_sha256=basis,
                replacing_event_id=replacing,
            )
            if preview.basis_sha256 != basis:
                raise ProfileFormatError("loan_changed_since_selection")
            return preview

        self.jobs.submit(("preview", bank_id, component_ids, basis, replacing), read, delay=100)
        self.summary.setText("Checking the exact selected payment preview...")
        self._update_actions()

    def _preview_failed(self, exc):
        if "changed_since_selection" in str(exc):
            self._notice = "Sources or event context changed. The draft was reset; inspect the reloaded source facts."
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

    def _apply_preview(self, preview):
        self.preview = preview
        manifest = preview.manifest
        gross = sum(proof.gross_minor for proof in manifest.components)
        self.summary.setText(
            f"Payment {_money(gross)} · principal reduction {_money(manifest.principal_minor)} · interest expense {_money(manifest.interest_minor)}. "
            + (
                "This lender posting is matched in Transfers. "
                if manifest.bank is None
                and self.selected_event is not None
                and self.resolution_states.get(self.selected_event.event_id) == "matched"
                else "Paying account unresolved; the gross payment remains in transfer clearing. "
                if manifest.bank is None
                else "Selected bank evidence will be linked at its own source date. "
            )
            + "Loan accounting dates are assumed from observed activity dates. Unknown opening stays unknown."
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
                    f"{entry.posting_date.isoformat()} ({'source' if manifest.bank is not None and index == 0 else 'assumed'})",
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
        if getattr(self, "_notice", None):
            self.status.setText(self._notice)
            self._notice = None

    def _update_actions(self, *_args):
        if not hasattr(self, "confirm"):
            return
        event = self.selected_event
        active = event is not None and event.status == "active"
        changed = self.preview is not None and (event is None or self.preview.manifest != event.manifest)
        linked = active and self.resolution_states.get(event.event_id) == "matched"
        self.confirm.setText("Confirm whole payment replacement" if event else "Post loan payment")
        self.confirm.setEnabled(
            bool(
                self.snapshot
                and self.preview
                and changed
                and not self.jobs.writing
                and (event is None or active)
                and not linked
                and self.reference.text().strip()
                and self.reason.text().strip()
            )
        )
        self.withdraw.setEnabled(
            bool(self.snapshot and active and not linked and self.reason.text().strip() and not self.jobs.writing)
        )
        unresolved = active and event.manifest.bank is None and not linked
        self.resolve_button.setVisible(bool(active and event.manifest.bank is None))
        self.resolve_button.setText("View in Transfers…" if linked else "Resolve in Transfers…")
        self.resolve_button.setEnabled(bool(active and event.manifest.bank is None and not self.jobs.writing))
        if self.snapshot is None:
            self.status.setText("Reload verified state before reviewing another payment.")
        elif event is not None and not active:
            self.status.setText(
                "Historical event; all original entries, source uses and action reasons remain inspectable."
            )
        elif linked:
            self.status.setText(
                "Posted · transfer matched. Unlink it in Transfers before changing or withdrawing the lender posting."
            )
        elif active and not changed:
            self.status.setText(
                "Posted · paying-account counterpart unresolved. Resolve it in Transfers when more evidence is available."
                if unresolved
                else "Posted payment · inspect its retained source evidence and history."
            )
        elif self.preview and not self.reference.text().strip():
            self.status.setText("Enter a reference to the reviewed statement evidence before posting.")
        elif self.preview and not self.reason.text().strip():
            self.status.setText("Enter a reason for this payment review before posting.")
        else:
            self.status.setText(
                "Ready to post. Principal reduces the loan; interest is expense. Review the posting and date assumptions before confirming."
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
            exec_disposable(preview_saved_source(self.workspace.profile_path, source_sha256, parent=self))
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
        if not 0 <= index < len(self.rows):
            checked = self._component_ids()
            if len(checked) == 1:
                index = next((i for i, row in enumerate(self.rows) if row.row_id == checked[0]), -1)
        if 0 <= index < len(self.rows):
            self._open_source(self.rows[index].source_sha256)

    def _resolve_transfer(self):
        event = self.selected_event
        if event is not None and event.status == "active" and event.manifest.bank is None:
            row_id = event.manifest.components[0].row_id
            if self.jobs.close():
                self.accept()
                self.transfers_requested.emit(row_id)

    @staticmethod
    def _payment_summary(manifest, *, inverse=False):
        sign = -1 if inverse else 1
        gross = sum(proof.gross_minor for proof in manifest.components)
        lines = [
            f"{'Reverse' if inverse else 'Record'} payment {_money(gross)}:",
            f"Principal {'increase' if inverse else 'reduction'} {_money(manifest.principal_minor)}; "
            f"interest {'reversal' if inverse else 'expense'} {_money(manifest.interest_minor)}.",
        ]
        for proof in manifest.components:
            lines.append(
                f"{proof.account_name} · {proof.effective_date} (assumed accounting date from observed activity; not a reported posting date)."
            )
        if manifest.bank is None:
            lines.append(
                f"Transfer clearing {_money(-sign * gross)} · no bank posting. The bank relationship is tracked in Transfers."
            )
        else:
            lines.append(
                f"Paying account {manifest.bank.account_name} · {_money(sign * manifest.bank.amount_minor)} "
                f"on {manifest.bank.posting_date} ({manifest.bank.date_provenance})."
            )
            lines.append("The separate source dates are retained; clearing remains between those dates.")
        lines.append(
            "Only printed interest is expense; the gross payment is not a second expense. Unknown opening remains unknown. Full source details are available in the posting preview."
        )
        return "\n".join(lines)

    def _post(self):
        if not self.confirm.isEnabled() or self.preview is None or self.snapshot is None:
            return
        preview, snapshot, event = self.preview, self.snapshot, self.selected_event
        reference, reason = self.reference.text().strip(), self.reason.text().strip()
        message = (
            (
                "Replace the WHOLE saved payment?\n\nInverse original entries at their original dates:\n"
                + self._payment_summary(event.manifest, inverse=True)
                + "\n\nReplacement entry effects only; the original bank and all loan legs are reversed first:\n"
                if event
                else "Post this explicitly reviewed payment?\n\nNew entry effects:\n"
            )
            + self._payment_summary(preview.manifest)
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
            self._notice = "Posting-date preferences changed during confirmation. Rebuild the draft under the current visible choice."
            self.refresh()
            self.status.setText(
                "Posting-date preferences changed during confirmation. Rebuild the draft under the current visible choice."
            )
            return
        preferences = self.review_preferences

        def write(store, _cancelled):
            kwargs = {
                "expected_basis_sha256": snapshot.basis_sha256,
                "preferences": preferences,
                "reference": reference,
                "reason": reason,
            }
            if event:
                return store.replace_reviewed_loan(
                    event.event_id,
                    preview.manifest.bank.row_id if preview.manifest.bank is not None else None,
                    tuple(proof.row_id for proof in preview.manifest.components),
                    expected_event_version=event.version,
                    **kwargs,
                )
            return store.post_reviewed_loan_payment(
                preview.manifest.bank.row_id if preview.manifest.bank is not None else None,
                tuple(proof.row_id for proof in preview.manifest.components),
                **kwargs,
            )

        self.jobs.submit(("post",), write, write=True)
        self.status.setText("Recording the confirmed whole payment. Wait for the saved result...")

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

        def write(store, _cancelled):
            store.withdraw_reviewed_loan(event.event_id, expected_event_version=event.version, reason=reason)

        self.jobs.submit(("withdraw",), write, write=True)
        self.status.setText("Recording the confirmed whole-payment withdrawal...")

    def _job_completed(self, key, result):
        if key[0] == "snapshot":
            self._apply_snapshot(*result)
        elif key[0] == "preview":
            if self.workspace.preferences() != self.review_preferences:
                self.refresh()
            else:
                self._apply_preview(result)
        else:
            self._notice = (
                "Recorded. Refreshed history shows current state; original evidence and actions remain inspectable."
            )
            if key[0] == "post":
                self._notice = (
                    "Posted · paying-account counterpart unresolved. Resolve it later in Transfers."
                    if result.manifest.bank is None
                    else "Posted loan payment with the selected paying-account evidence."
                )
                self._requested_event_id = result.event_id
                self.mode.blockSignals(True)
                self.mode.setCurrentIndex(0)
                self.mode.blockSignals(False)
            self.refresh()

    def _job_failed(self, key, exc):
        if key[0] == "preview":
            self._preview_failed(exc)
        elif key[0] == "snapshot":
            self.snapshot = self.preview = self.selected_event = None
            self.banks, self.rows, self.labels = {}, (), {}
            self._clear_draft()
            self.status.setText("Loan sources and event history could not be verified. Reload before another action.")
        else:
            self._notice = "The confirmed action was not recorded. Inspect refreshed sources and whole-event history."
            self.refresh()
            self.status.setText(
                "The confirmed action was not recorded. "
                + REASONS.get(str(exc), "Inspect refreshed source and event history.")
            )

    def _busy_changed(self, _busy):
        writing = self.jobs.writing
        for widget in (self.tabs, self.mode, self.reload, self.assumed_dates, self.reference, self.reason):
            widget.setEnabled(not writing)
        if writing:
            self.confirm.setEnabled(False)
            self.withdraw.setEnabled(False)

    def reject(self):
        if self.jobs.close():
            super().reject()
        else:
            self.status.setText("The confirmed write is still running. Wait for its saved outcome before closing.")

    def closeEvent(self, event):
        if self.jobs.close():
            super().closeEvent(event)
        else:
            event.ignore()
            self.status.setText("The confirmed write is still running. Wait for its saved outcome before closing.")

    transfers_requested = Signal(str)

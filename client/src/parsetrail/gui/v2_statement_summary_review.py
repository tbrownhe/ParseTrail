"""Review a retirement statement's value without inventing cash transactions."""

from datetime import date
from weakref import ref

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from parsetrail.gui.v2_account_anchors import V2AccountAnchors
from parsetrail.gui.v2_details_disclosure import DetailsDisclosure
from parsetrail.gui.v2_evidence_preview import _money, preview_saved_source
from parsetrail.gui.v2_form_state import install_form_styles, set_field_state
from parsetrail.gui.v2_gui_lifetime import exec_disposable
from parsetrail.gui.v2_profile_jobs import ProfileJobs


def _label(text=""):
    result = QLabel(text)
    result.setWordWrap(True)
    result.setTextFormat(Qt.PlainText)
    result.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
    return result


REASONS = {
    "statement_summary_account_required": "Choose the retirement account for this statement.",
    "statement_summary_binding_mixed": "The summary needs one confirmed account for this plan.",
    "statement_summary_shape_unsupported": "This statement's summary needs further inspection.",
    "statement_summary_family_unsupported": "This document needs a different review workflow.",
    "source_value_closing_unavailable": "The statement's closing value is not established.",
    "source_value_date_unavailable": "The statement's closing date is not established.",
    "source_value_scope_or_kind_mismatch": "The account does not match this statement's value scope.",
}


class _SummaryNavigation:
    def __init__(self, owner):
        self._owner = ref(owner)

    def reveal_row(self, row_id):
        owner = self._owner()
        if owner is None:
            return False
        owner._selected_after_read = row_id
        return owner._select_row(row_id)

    def current(self):
        owner = self._owner()
        return owner._current() if owner is not None else None


class V2StatementSummaryReview(QWidget):
    """Reusable embedded review; all value/proof policy stays in the profile service."""

    changed = Signal()
    initial_review_completed = Signal(str)
    account_assignment_requested = Signal()

    def __init__(self, workspace, source_sha256, parent=None):
        super().__init__(parent)
        install_form_styles(self)
        self.workspace, self.source_sha256 = workspace, source_sha256
        self.snapshot = None
        self.rows = ()
        self._selected_after_read = None
        self._awaiting_completion = False
        self._notice = ""
        self._preserved_fields = None
        self._default_fields = ("", "Initial Review")
        self.navigation = _SummaryNavigation(self)
        self.jobs = ProfileJobs(self, workspace.profile_path)
        self.jobs.completed.connect(self._loaded)
        self.jobs.failed.connect(self._failed)
        self.jobs.busy_changed.connect(self._busy)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = _label("Retirement statement review")
        title.setStyleSheet("font-weight: 600; font-size: 16px")
        layout.addWidget(title)
        self.context = _label()
        layout.addWidget(self.context)
        self.section = QComboBox()
        self.section.setAccessibleName("Statement plan")
        self.section.currentIndexChanged.connect(self._render)
        layout.addWidget(self.section)
        self.value = _label()
        self.value.setStyleSheet("font-weight: 600; font-size: 15px")
        layout.addWidget(self.value)
        self.explanation = _label(
            "Record the statement's closing value for Accounts and Reports. "
            "Summary changes do not create individual transactions."
        )
        layout.addWidget(self.explanation)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(("Statement summary", "Amount"))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setAccessibleName("Printed statement value and changes")
        layout.addWidget(self.table, 1)
        self.qualification = _label()
        layout.addWidget(self.qualification)
        self.status = _label("Loading statement value…")
        layout.addWidget(self.status)
        details_content = QWidget()
        details_layout = QVBoxLayout(details_content)
        details_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.reference = QLineEdit()
        self.reference.setMaxLength(500)
        self.reason = QLineEdit("Initial Review")
        self.reason.setMaxLength(500)
        form.addRow("Review reference", self.reference)
        form.addRow("Reason", self.reason)
        details_layout.addLayout(form)
        self.details_text = _label()
        details_layout.addWidget(self.details_text)
        self.details = DetailsDisclosure(details_content, self, subject="statement qualifications and review reference")
        self.details.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout.addWidget(self.details)
        self.reference.textChanged.connect(self._update_actions)
        self.reason.textChanged.connect(self._update_actions)
        actions = QHBoxLayout()
        self.action_button = QPushButton("Record statement value")
        self.action_button.clicked.connect(self._act)
        actions.addWidget(self.action_button)
        self.source_button = QPushButton("View statement evidence…")
        self.source_button.clicked.connect(self._open_source)
        actions.addWidget(self.source_button)
        self.reload_button = QPushButton("Reload")
        self.reload_button.clicked.connect(self._reload)
        actions.addWidget(self.reload_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.refresh()

    @property
    def review_pending(self):
        return self.jobs.pending

    @property
    def has_unsaved_draft(self):
        return (
            self.snapshot is not None
            and not self.snapshot.complete
            and (self.reference.text(), self.reason.text()) != self._default_fields
        )

    def request_cancel(self):
        return self.jobs.close()

    def refresh_preserving_draft(self):
        section = self._current_section()
        if section is not None:
            self._preserved_fields = (section.basis_sha256, self.reference.text(), self.reason.text())
        self.refresh()

    def refresh(self):
        source = self.source_sha256

        def read(store, cancelled):
            return None if cancelled() else store.statement_summary_snapshot(source)

        self.jobs.submit("summary", read)

    def _reload(self):
        self._notice = ""
        self.refresh()

    def _current_section(self):
        index = self.section.currentIndex()
        return (
            self.snapshot.sections[index]
            if self.snapshot is not None and 0 <= index < len(self.snapshot.sections)
            else None
        )

    def _loaded(self, key, result):
        if key == "save":
            self._notice = (
                "The existing historical value remains retired. Inspect its history or make a fresh review."
                if result.state != "active"
                else ""
            )
            self.refresh()
            self.changed.emit()
            return
        if result is None:
            return
        if self._notice.startswith("Statement value is unavailable"):
            self._notice = ""
        previous = self._current_section()
        self.snapshot = result
        self.section.blockSignals(True)
        self.section.clear()
        for item in result.sections:
            self.section.addItem(item.account_name or item.source_identity, item.source_identity)
        if previous is not None:
            self.section.setCurrentIndex(max(0, self.section.findData(previous.source_identity)))
        self.section.blockSignals(False)
        self.section.setVisible(len(result.sections) > 1)
        self._render()
        if self._awaiting_completion:
            self._awaiting_completion = False
            if result.complete:
                self.initial_review_completed.emit(self.source_sha256)

    def _render(self, *_args):
        section, snapshot = self._current_section(), self.snapshot
        if section is None:
            self.table.setRowCount(0)
            self._update_actions()
            return
        period = f"{snapshot.start.iso or 'Unknown start'} to {snapshot.end.iso or 'unknown end'}"
        self.context.setText(
            f"{section.account_name or 'Account not confirmed'} · {section.source_identity}\nStatement period: {period}"
        )
        self.value.setText(
            f"Ending value {_money(section.closing.minor if section.closing else None)} · {snapshot.end.iso or 'date unknown'}"
        )
        self.rows = section.rows
        bridge = [
            ("Beginning value", section.opening.minor if section.opening else None, None),
            *(
                (row.description.text or "Description not printed", row.amount.minor, row.row_id)
                for row in section.rows
            ),
            ("Ending value", section.closing.minor if section.closing else None, None),
        ]
        self.table.setRowCount(len(bridge))
        for index, (label, amount, row_id) in enumerate(bridge):
            for column, value in enumerate((label, _money(amount))):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row_id)
                item.setToolTip(value)
                if column == 1:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(index, column, item)
        self.table.resizeRowsToContents()
        if self._selected_after_read:
            self._select_row(self._selected_after_read)
            self._selected_after_read = None
        self.qualification.setText(
            "Beginning value plus printed changes equals ending value."
            if snapshot.independent_balance_verified
            else "The statement value bridge is not independently verified. Inspect the original evidence."
        )
        self.details_text.setText(
            "These are totals for the statement period, not individually dated contributions or trades. "
            "Recording the closing value creates no budget spending, income, transfer or opening balance.\n"
            + (
                "Complete source capture is verified. "
                if snapshot.capture_verified
                else "Complete source capture is not verified. "
            )
            + "The original statement, source locations and prior value history remain available."
        )
        reference = (
            f"{section.account_name or section.source_identity} · statement ending {snapshot.end.iso or 'unknown'}"[
                :500
            ]
        )
        self._default_fields = (reference, "Initial Review")
        preserved, self._preserved_fields = self._preserved_fields, None
        self.reference.setText(preserved[1] if preserved and preserved[0] == section.basis_sha256 else reference)
        self.reason.setText(preserved[2] if preserved and preserved[0] == section.basis_sha256 else "Initial Review")
        self._update_actions()

    def _update_actions(self, *_args):
        if not hasattr(self, "action_button"):
            return
        section, snapshot = self._current_section(), self.snapshot
        ready = bool(section is not None and snapshot is not None and not self.jobs.pending)
        completed = section is not None and section.status == "reviewed"
        missing_account = section is not None and section.account_id is None
        conflict = section is not None and section.status == "conflict"
        self.action_button.setText(
            "View recorded value/history…"
            if completed
            else "Choose account…"
            if missing_account
            else "Review conflicting values…"
            if conflict
            else "Record statement value"
        )
        enabled = ready and (
            completed
            or missing_account
            or conflict
            or (
                section.status == "pending"
                and not snapshot.blockers
                and not section.blockers
                and bool(self.reference.text().strip() and self.reason.text().strip())
            )
        )
        self.action_button.setEnabled(bool(enabled))
        set_field_state(self.action_button, "ready" if enabled and not completed else "neutral")
        self.source_button.setEnabled(not self.jobs.writing)
        self.reload_button.setEnabled(not self.jobs.writing)
        editable = ready and section.status == "pending"
        for field in (self.reference, self.reason):
            field.setEnabled(bool(editable))
            set_field_state(
                field, "ready" if editable and field.text().strip() else "required" if editable else "neutral"
            )
        if self._notice:
            self.status.setText(self._notice)
        elif completed:
            self.status.setText(
                "Value recorded · Review complete. The summary changes remain statement evidence."
                if snapshot.complete
                else "This plan's value is recorded. Review the remaining plan values."
            )
        elif missing_account:
            self.status.setText("Choose the retirement account before recording this statement's value.")
        elif conflict:
            self.status.setText(
                "Different values are recorded for this date. Review the conflict before completing this statement."
            )
        elif section is not None and (snapshot.blockers or section.blockers):
            self.status.setText(
                " ".join(
                    REASONS.get(code, "This statement value needs further review in its evidence or account history.")
                    for code in (*snapshot.blockers, *section.blockers)
                )
            )
        elif section is not None and not (self.reference.text().strip() and self.reason.text().strip()):
            self.status.setText("Enter a review reference and reason in Show details before recording the value.")
        elif section is not None:
            self.status.setText(
                "Ready to record the printed closing value. Contributions and market changes stay as summary evidence."
            )

    def _act(self):
        section, snapshot = self._current_section(), self.snapshot
        if section is None or snapshot is None or not self.action_button.isEnabled():
            return
        if section.account_id is None:
            self.account_assignment_requested.emit()
            return
        if section.status in {"reviewed", "conflict"}:
            selected_value = section.active_value or next(iter(section.conflicting_values), None)
            exec_disposable(
                V2AccountAnchors(
                    self.workspace.profile_path,
                    section.account_id,
                    self,
                    initial_tab="values",
                    as_of=date.fromisoformat(snapshot.end.iso) if snapshot.end.iso else None,
                    focus_value_id=selected_value.value_id if selected_value is not None else None,
                )
            )
            self.refresh()
            self.changed.emit()
            return
        candidate = section.candidate
        if candidate is None:
            return
        account, candidate_id, version, basis = (
            section.account_id,
            candidate.candidate_id,
            candidate.version,
            section.basis_sha256,
        )
        profile_identity = snapshot.profile_identity
        reference, reason = self.reference.text().strip(), self.reason.text().strip()

        def write(store, _cancelled):
            return store.record_reviewed_source_value(
                account,
                candidate_id,
                expected_candidate_sha256=version,
                expected_basis_sha256=basis,
                expected_profile_identity=profile_identity,
                reference=reference,
                reason=reason,
            )

        self._notice = ""
        self._awaiting_completion = not snapshot.complete
        self.jobs.submit("save", write, write=True)

    def _select_row(self, row_id):
        for index in range(self.table.rowCount()):
            if self.table.item(index, 0).data(Qt.UserRole) == row_id:
                self.table.selectRow(index)
                self.table.scrollToItem(self.table.item(index, 0))
                return True
        return False

    def _current(self):
        index = self.table.currentRow()
        row_id = self.table.item(index, 0).data(Qt.UserRole) if index >= 0 else None
        return next((row for row in self.rows if row.row_id == row_id), None)

    def _open_source(self):
        try:
            exec_disposable(preview_saved_source(self.workspace.profile_path, self.source_sha256, parent=self))
        except Exception:
            self._notice = "The saved evidence could not be opened. Reload before continuing."
            self.refresh()

    def _busy(self, _busy):
        self._update_actions()

    def _failed(self, key, _error):
        self._awaiting_completion = False
        self.snapshot, self.rows = None, ()
        self.table.setRowCount(0)
        self.value.clear()
        self._notice = (
            "The value could not be confirmed from this review. Check the reloaded facts before a fresh confirmation."
            if key == "save"
            else "Statement value is unavailable. Reload to retry; saved work is unchanged."
        )
        self.status.setText(self._notice)
        self._update_actions()
        if key == "save":
            self.refresh()

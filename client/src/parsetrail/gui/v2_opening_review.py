"""Review printed opening provenance and post a dated opening position explicitly."""

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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_cash_movement import cash_account_labels
from parsetrail.core.v2_profile_store import (
    EarliestSourceOpening,
    OpeningDecisionHistoryRow,
    ProfileFormatError,
    V2ProfileStore,
)
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_cash_activity_review import _money
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview


class _OpeningHistoryModel(QAbstractTableModel):
    HEADERS = (
        "Revision",
        "Opening amount",
        "Cutoff",
        "Reason",
        "Saved at (UTC)",
        "Journal",
        "Origin",
        "Scope",
        "State",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: tuple[OpeningDecisionHistoryRow, ...] = ()
        self.natural = 1

    def replace(self, rows: tuple[OpeningDecisionHistoryRow, ...], kind: str = "asset") -> None:
        self.beginResetModel()
        self.rows = rows
        self.natural = 1 if kind == "asset" else -1
        self.endResetModel()

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        return self.HEADERS[section] if role == Qt.DisplayRole and orientation == Qt.Horizontal else None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.TextAlignmentRole and index.column() in (0, 1):
            return Qt.AlignRight | Qt.AlignVCenter
        if role == Qt.ToolTipRole:
            return self.details(row)
        if role != Qt.DisplayRole:
            return None
        return (
            str(row.revision_id),
            _money(self.natural * row.amount_minor) if row.amount_minor is not None else "Unknown (withdrawn)",
            row.cutoff_date.isoformat() if row.cutoff_date is not None else "Not established",
            row.reason,
            row.created_at,
            "No current posting"
            if row.state == "withdrawn"
            else "No posting (zero)"
            if row.entry_key is None
            else "Retained reference",
            row.origin.title(),
            row.tracking_scope.replace("_", " "),
            row.state.title(),
        )[index.column()]

    @staticmethod
    def details(row: OpeningDecisionHistoryRow) -> str:
        return (
            f"Revision {row.revision_id}; reason: {row.reason}. "
            f"Journal entry: {row.entry_key or 'none'}. Origin: {row.origin}; state: {row.state}; "
            f"tracking scope: {row.tracking_scope.replace('_', ' ')}; reference: {row.reference or 'source basis below'}.\n"
            f"Decision version: {row.version}; prior version: {row.prior_version or 'none (initial decision)'}.\n"
            f"Reviewed basis: {row.basis_sha256}. Prior decisions and journals remain history."
        )


class V2OpeningReview(QDialog):
    """Keep a source assertion separate from the later opening journal decision."""

    BLOCKERS = {
        "no_bound_statement": "No bound statement",
        "unknown_source_period": "Unknown source period",
        "non_account_total_scope": "Source is not an account-total balance",
        "printed_opening_unavailable": "Printed opening unavailable",
        "conflicting_earliest_openings": "Earliest sources have conflicting printed openings",
        "duplicate_earliest_source_sections": "Multiple earliest sections in one source",
        "source_timing_unreviewed": "Earliest source timing needs review",
    }

    def __init__(self, workspace: V2Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.candidate: EarliestSourceOpening | None = None
        self.reviews = {}
        self.decision = None
        self.basis = None
        self._loaded_account_id = None
        self._loaded_form = (None, False, "", "")
        self.setWindowTitle("2.0 opening position review")
        self.resize(1080, 720)
        layout = QVBoxLayout(self)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self.profile_path = QLineEdit(str(workspace.profile_path))
        self.profile_path.setReadOnly(True)
        self.profile_path.setCursorPosition(0)
        profile_row.addWidget(self.profile_path)
        layout.addLayout(profile_row)
        note = QLabel(
            "A source-backed opening establishes a dated journal starting point after you inspect every earliest source "
            "and its inclusive period timing. The opening uses equity and creates no income or spending. "
            "USD amounts show asset value or liability owed. "
            "Corrections retain prior decisions and reverse superseded postings; later balance differences need their own review."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.account = QComboBox()
        self.account.currentIndexChanged.connect(self.refresh)
        form.addRow("Financial account", self.account)
        self.candidate_label = QLabel()
        self.candidate_label.setWordWrap(True)
        self.candidate_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Current source candidate", self.candidate_label)
        self.saved_label = QLabel()
        self.saved_label.setWordWrap(True)
        self.saved_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Saved opening decision", self.saved_label)
        layout.addLayout(form)
        self.tabs = QTabWidget()
        review_panel = QWidget()
        review_layout = QVBoxLayout(review_panel)
        form = QFormLayout()
        self.source = QComboBox()
        self.source.currentIndexChanged.connect(self._source_changed)
        form.addRow("Source to inspect", self.source)
        self.source_details = QLabel()
        self.source_details.setWordWrap(True)
        form.addRow("Printed facts", self.source_details)
        self.origin = QComboBox()
        self.origin.addItem("Choose source assessment", None)
        self.origin.addItem("Printed on statement", "reported")
        self.origin.addItem("Not established", "unestablished")
        self.origin.currentIndexChanged.connect(self._update_actions)
        form.addRow("Opening origin", self.origin)
        self.timing = QCheckBox("I checked the inclusive period start and when its opening balance applies")
        self.timing.toggled.connect(self._update_actions)
        form.addRow("Period timing", self.timing)
        self.reference = QLineEdit()
        self.reference.setMaxLength(500)
        self.reference.setPlaceholderText("Required page, section or other source reference")
        self.reference.textChanged.connect(self._update_actions)
        form.addRow("Source reference", self.reference)
        self.note = QLineEdit()
        self.note.setMaxLength(500)
        self.note.setPlaceholderText("Optional review note")
        self.note.textChanged.connect(self._update_actions)
        form.addRow("Note", self.note)
        self.correction_reason = QLineEdit()
        self.correction_reason.setMaxLength(500)
        self.correction_reason.setPlaceholderText("Required for correction, fresh establishment or withdrawal")
        self.correction_reason.textChanged.connect(self._update_actions)
        form.addRow("Action reason", self.correction_reason)
        review_layout.addLayout(form)
        actions = QHBoxLayout()
        self.preview = QPushButton("Preview source")
        self.preview.clicked.connect(self._preview)
        actions.addWidget(self.preview)
        self.save = QPushButton("Record source review")
        self.save.clicked.connect(self._record)
        actions.addWidget(self.save)
        self.confirm = QPushButton("Confirm opening position")
        self.confirm.clicked.connect(self._post)
        actions.addWidget(self.confirm)
        self.correct = QPushButton("Correct saved opening")
        self.correct.clicked.connect(self._correct)
        actions.addWidget(self.correct)
        self.reload = QPushButton("Reload saved state")
        self.reload.clicked.connect(self.refresh)
        actions.addWidget(self.reload)
        actions.addStretch()
        review_layout.addLayout(actions)
        withdrawal_row = QHBoxLayout()
        self.withdraw = QPushButton("Withdraw saved opening")
        self.withdraw.clicked.connect(self._withdraw)
        withdrawal_row.addWidget(self.withdraw)
        withdrawal_note = QLabel(
            "Withdrawal is available even when the source basis is stale or unavailable; the opening becomes unknown."
        )
        withdrawal_note.setWordWrap(True)
        withdrawal_row.addWidget(withdrawal_note, 1)
        review_layout.addLayout(withdrawal_row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        review_layout.addWidget(self.status)
        review_layout.addStretch()
        self.tabs.addTab(review_panel, "Review opening")
        history_panel = QWidget()
        history_layout = QVBoxLayout(history_panel)
        history_scope = QLabel(
            "Newest decisions appear first, including zero decisions and explicit withdrawals. Withdrawn is unknown, not zero. "
            "Amounts use asset value or liability owed signs. A basis-only correction may retain its journal reference. "
            "This history does not establish later coverage or reconciliation."
        )
        history_scope.setWordWrap(True)
        history_layout.addWidget(history_scope)
        self.history_model = _OpeningHistoryModel(self)
        self.history_table = QTableView()
        self.history_table.setModel(self.history_model)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.history_table.horizontalHeader()
        for column, width in enumerate((80, 130, 115, 300, 190, 150)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.history_table.setColumnWidth(column, width)
        history_layout.addWidget(self.history_table)
        self.history_details = QLabel("No opening decisions saved for this account.")
        self.history_details.setWordWrap(True)
        self.history_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        history_layout.addWidget(self.history_details)
        self.history_table.selectionModel().currentRowChanged.connect(self._show_history)
        self.tabs.addTab(history_panel, "Opening history")
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.account.blockSignals(True)
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            accounts = store.financial_accounts()
        labels = cash_account_labels(accounts)
        for account in accounts:
            self.account.addItem(labels[account.id], account.id)
        self.account.blockSignals(False)
        self.refresh()

    def _form(self):
        return (
            self.origin.currentData(),
            self.timing.isChecked(),
            self.reference.text().strip(),
            self.note.text().strip(),
        )

    def _source_changed(self, *_args) -> None:
        source_id = self.source.currentData()
        review = self.reviews.get(source_id)
        for widget in (self.origin, self.timing, self.reference, self.note):
            widget.blockSignals(True)
        self.origin.setCurrentIndex(self.origin.findData(review.opening_origin) if review else 0)
        self.timing.setChecked(review.timing_confirmed if review else False)
        self.reference.setText(review.source_reference if review else "")
        self.note.setText(review.note if review else "")
        for widget in (self.origin, self.timing, self.reference, self.note):
            widget.blockSignals(False)
        self._loaded_form = self._form()
        if source_id is None:
            self.source_details.setText("No earliest source is available for this account.")
        else:
            try:
                with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                    section = next(
                        (
                            row
                            for row in store.statement_coverage()
                            if row.account_id == self.account.currentData() and row.source_sha256 == source_id
                        ),
                        None,
                    )
            except (ProfileFormatError, sqlite3.Error, OSError):
                section = None
            if section is None:
                self.source_details.setText("Source section unavailable; inspect binding and evidence.")
            else:
                opening = section.opening
                self.source_details.setText(
                    f"Period {section.period_start.isoformat() if section.period_start else 'unknown'} "
                    f"to {section.period_end.isoformat()} ({section.period_start_provenance} start); "
                    f"opening {opening.raw if opening and opening.raw else 'unknown'} "
                    f"({opening.provenance if opening else 'unknown'}), {section.balance_scope.replace('_', ' ')}. "
                    f"Source {source_id}"
                )
        self._update_actions()

    def refresh(self, *_args, selected_source: str | None = None) -> None:
        try:
            self._reload(selected_source=selected_source)
        except (ProfileFormatError, sqlite3.Error, OSError):
            self.candidate = None
            self.reviews = {}
            self.decision = None
            self.basis = None
            self.source.blockSignals(True)
            self.source.clear()
            self.source.blockSignals(False)
            self.history_model.replace(())
            self.history_details.setText("Opening history unavailable; reload after checking the profile.")
            self.saved_label.setText("Saved state unavailable; unknown is not zero.")
            self.candidate_label.setText("Source candidate unavailable.")
            self._source_changed()
            self.status.setText("Opening review could not be read. Reload saved state before reviewing an opening.")

    def _reload(self, *, selected_source: str | None = None) -> None:
        account_id = self.account.currentData()
        if account_id != self._loaded_account_id:
            self.correction_reason.blockSignals(True)
            self.correction_reason.clear()
            self.correction_reason.blockSignals(False)
            self._loaded_account_id = account_id
        if account_id is None:
            self.candidate = None
            self.reviews = {}
            self.decision = None
            self.basis = None
            self.source.clear()
            self.candidate_label.setText("Add and bind a financial account first.")
            self.saved_label.setText("Not established; unknown is not zero.")
            self.history_model.replace(())
            self.history_details.setText("No opening decisions saved for this account.")
            self._source_changed()
            return
        with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
            snapshot = store.opening_review_snapshot(account_id)
        self.candidate = snapshot.candidate
        self.reviews = {review.source_sha256: review for review in snapshot.reviews}
        self.decision = snapshot.decision
        self.basis = snapshot.basis_sha256
        candidate = self.candidate
        amount = candidate.printed_opening_minor
        natural = 1 if candidate.account_kind == "asset" else -1
        self.candidate_label.setText(
            f"Start: {candidate.earliest_period_start.isoformat() if candidate.earliest_period_start else 'unknown'}; "
            f"printed candidate: {_money(amount * natural) if amount is not None else 'unavailable'}; "
            f"{candidate.bound_statement_sections} bound section(s)."
        )
        if self.decision is None:
            self.saved_label.setText("Not established; unknown is not zero.")
        elif self.decision.state == "withdrawn":
            self.saved_label.setText(
                f"Withdrawn; opening unknown, not zero. Revision {self.decision.revision_id}. Prior amounts and dates remain in history."
            )
        else:
            self.saved_label.setText(
                f"{_money(self.decision.amount_minor * natural)} as of {self.decision.cutoff_date.isoformat()}; "
                f"revision {self.decision.revision_id}; "
                f"{self.decision.origin} origin; {self.decision.tracking_scope.replace('_', ' ')}; "
                f"{'independent manual review' if self.decision.origin == 'manual' else 'stale against the current source basis' if self.decision.stale else 'current source basis'}."
            )
        self.history_model.replace(snapshot.history, candidate.account_kind)
        if snapshot.history:
            self.history_table.selectRow(0)
        else:
            self.history_details.setText("No opening decisions saved for this account.")
        previous = selected_source or self.source.currentData()
        self.source.blockSignals(True)
        self.source.clear()
        for source_id in candidate.earliest_source_ids:
            status = "reviewed" if source_id in self.reviews else "needs review"
            self.source.addItem(f"{source_id[:16]}… ({status})", source_id)
        if previous is not None:
            index = self.source.findData(previous)
            if index >= 0:
                self.source.setCurrentIndex(index)
        self.source.blockSignals(False)
        self._source_changed()

    def _update_actions(self, *_args) -> None:
        source_selected = self.source.currentData() is not None
        changed = self._form() != self._loaded_form
        self.preview.setEnabled(source_selected)
        self.save.setEnabled(
            source_selected
            and changed
            and self.origin.currentData() is not None
            and bool(self.reference.text().strip())
        )
        candidate_ready = (
            self.candidate is not None
            and not self.candidate.blockers
            and self.candidate.earliest_period_start is not None
            and self.candidate.earliest_period_start > date.min
            and not changed
        )
        self.confirm.setEnabled(candidate_ready and self.decision is None)
        self.correction_reason.setEnabled(self.decision is not None)
        self.withdraw.setEnabled(
            self.decision is not None
            and self.decision.state == "active"
            and bool(self.correction_reason.text().strip())
        )
        self.correct.setText(
            "Establish fresh source opening"
            if self.decision is not None and self.decision.state == "withdrawn"
            else "Replace manual with source opening"
            if self.decision is not None and self.decision.origin == "manual"
            else "Correct saved opening"
        )
        self.correct.setEnabled(
            candidate_ready
            and self.decision is not None
            and (
                self.decision.state == "withdrawn"
                or self.decision.origin == "manual"
                or self.decision.stale
                or self.decision.basis_sha256 != self.basis
            )
            and bool(self.correction_reason.text().strip())
        )
        if self.decision is not None:
            self.status.setText(
                "Opening withdrawn; unknown is not zero. A fresh source or manual review is required to establish another opening."
                if self.decision.state == "withdrawn"
                else "Manual opening remains independent of printed source evidence. Replacing it with a source opening requires explicit review."
                if self.decision.origin == "manual"
                else "Saved opening is stale against the current source basis. Review the earliest sources, "
                "save any source assessments and enter a reason before correcting it."
                if self.decision.stale
                else "Zero opening confirmed."
                if self.decision.entry_key is None
                else "Opening posted."
            )
            if self.candidate is not None and self.candidate.blockers:
                self.status.setText(
                    self.status.text()
                    + " Correction blocked: "
                    + ", ".join(
                        self.BLOCKERS.get(blocker, blocker.replace("_", " ")) for blocker in self.candidate.blockers
                    )
                )
        elif self.candidate is not None:
            self.status.setText(
                "Review needed: "
                + ", ".join(
                    self.BLOCKERS.get(blocker, blocker.replace("_", " ")) for blocker in self.candidate.blockers
                )
                if self.candidate.blockers
                else "All earliest sources reviewed. Confirm the opening position when the form has no unsaved changes."
            )
        else:
            self.status.setText("No financial account selected.")

    def _preview(self) -> None:
        source_id = self.source.currentData()
        if source_id is not None:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                saved = store.load_import(source_id)
            V2EvidencePreview(saved, self).exec()

    def _record(self) -> None:
        account_id, source_id = self.account.currentData(), self.source.currentData()
        if account_id is None or source_id is None:
            return
        loaded_review = self.reviews.get(source_id)
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.record_statement_source_review(
                    account_id,
                    source_id,
                    expected_revision_id=loaded_review.revision_id if loaded_review else None,
                    opening_origin=self.origin.currentData(),
                    closing_origin=loaded_review.closing_origin if loaded_review else "unestablished",
                    timing_confirmed=self.timing.isChecked(),
                    posting_dates=loaded_review.posting_dates if loaded_review else "unverified",
                    source_reference=self.reference.text(),
                    note=self.note.text(),
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            message = (
                "This source review changed after the form was loaded. The latest saved assessment has been reloaded."
                if str(exc) == "statement_source_review_changed_since_selection"
                else str(exc)
            )
            QMessageBox.warning(self, "Source review was not saved", message)
            self.refresh(selected_source=source_id)
            self.status.setText(message)
            return
        self.refresh(selected_source=source_id)
        self.status.setText("Source review recorded. Printed evidence remains unchanged.")

    def _post(self) -> None:
        candidate = self.candidate
        if candidate is None or candidate.blockers or self.decision is not None or self._form() != self._loaded_form:
            return
        cutoff = date.fromordinal(candidate.earliest_period_start.toordinal() - 1)
        natural = 1 if candidate.account_kind == "asset" else -1
        message = (
            f"Confirm {self.account.currentText()}'s printed opening of "
            f"{_money(candidate.printed_opening_minor * natural)} as of {cutoff.isoformat()}?\n\n"
            f"All {len(candidate.earliest_source_ids)} earliest source(s) have been reviewed. "
            "A nonzero amount posts through opening equity; zero records a decision without a journal. "
            "This does not create income or spending."
        )
        if QMessageBox.question(self, "Confirm opening position", message) != QMessageBox.StandardButton.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.post_reviewed_opening(candidate.account_id, expected_basis_sha256=self.basis)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Opening was not confirmed", str(exc))
            self.refresh()
            return
        self.refresh()

    def _show_history(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self.history_details.setText(
            self.history_model.details(self.history_model.rows[current.row()])
            if current.isValid()
            else "Select an opening decision to inspect its retained source basis and journal reference."
        )

    def _correct(self) -> None:
        candidate, decision = self.candidate, self.decision
        reason = self.correction_reason.text().strip()
        if (
            candidate is None
            or candidate.blockers
            or candidate.earliest_period_start is None
            or candidate.earliest_period_start <= date.min
            or decision is None
            or not reason
            or self._form() != self._loaded_form
            or (
                decision.state == "active"
                and decision.origin == "source"
                and not decision.stale
                and decision.basis_sha256 == self.basis
            )
        ):
            return
        cutoff = date.fromordinal(candidate.earliest_period_start.toordinal() - 1)
        natural = 1 if candidate.account_kind == "asset" else -1
        message = (
            f"Correct {self.account.currentText()}'s source-backed opening?\n\n"
            f"Saved: {_money(decision.amount_minor * natural) if decision.amount_minor is not None else 'unknown (withdrawn)'} "
            f"as of {decision.cutoff_date.isoformat() if decision.cutoff_date is not None else 'not established'} "
            f"(revision {decision.revision_id}).\n"
            f"Current reviewed candidate: {_money(candidate.printed_opening_minor * natural)} as of {cutoff.isoformat()}.\n"
            f"Reason: {reason}\n\n"
            "A changed amount or cutoff reverses the prior active opening at its original date and records the "
            "new source-backed opening at its own cutoff. Zero records a decision without a replacement posting. "
            "When only the source basis changes, the existing posting may be retained. "
            "Prior decisions remain history. This creates no income or spending and does not explain later balance differences."
        )
        if QMessageBox.question(self, "Confirm opening correction", message) != QMessageBox.StandardButton.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.correct_reviewed_opening(
                    candidate.account_id,
                    expected_decision_version=decision.version,
                    expected_basis_sha256=self.basis,
                    reason=reason,
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            messages = {
                "opening_review_changed_since_selection": "The source basis changed. Review the refreshed candidate before correcting it.",
                "opening_decision_changed_since_selection": "The saved opening decision changed. Review its refreshed history before correcting it.",
                "opening_review_blocked": "The current source basis is blocked. Resolve its source assessments before correcting the opening.",
                "opening_earlier_posting_conflict": "Existing activity before the proposed opening needs review. No opening correction was saved.",
            }
            message = messages.get(str(exc), str(exc))
            QMessageBox.warning(self, "Opening was not corrected", message)
            self.refresh()
            self.status.setText(message)
            return
        self.correction_reason.clear()
        self.refresh()
        self.status.setText("Opening corrected. Prior decisions and journals remain in Opening history.")

    def _withdraw(self) -> None:
        decision = self.decision
        reason = self.correction_reason.text().strip()
        if decision is None or decision.state != "active" or not reason or not self.withdraw.isEnabled():
            return
        natural = 1 if self.candidate is None or self.candidate.account_kind == "asset" else -1
        message = (
            f"Withdraw {self.account.currentText()}'s saved {decision.origin} opening of {_money(decision.amount_minor * natural)} "
            f"as of {decision.cutoff_date.isoformat()}?\n\nScope: {decision.tracking_scope.replace('_', ' ')}. "
            f"Reason: {reason}\n\n"
            "A nonzero opening is reversed through opening equity at its original date. A reviewed zero is withdrawn without money postings. "
            "The opening becomes unknown, not zero. Existing activity and prior decisions remain history. "
            "This does not establish settlement or change source assertions."
        )
        if QMessageBox.question(self, "Confirm opening withdrawal", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.withdraw_reviewed_opening(
                    decision.account_id, expected_decision_version=decision.version, reason=reason
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.refresh()
            self.status.setText("Opening withdrawal was not recorded. Review refreshed state before trying again.")
            QMessageBox.warning(self, "Opening was not withdrawn", str(exc))
            return
        self.correction_reason.clear()
        self.refresh()
        self.status.setText(
            "The selected opening withdrawal is recorded. Refreshed state and history show the current opening; unknown is not zero."
        )

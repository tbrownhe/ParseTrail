"""Shared asynchronous lifecycle and explicit staging for ordinary source review."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from weakref import ref

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from parsetrail.gui.v2_form_state import install_form_styles, set_field_state, set_status
from parsetrail.gui.v2_gui_lifetime import exec_disposable
from parsetrail.gui.v2_profile_jobs import ProfileJobs
from parsetrail.gui.v2_review_navigation import reviewed_elsewhere

INITIAL_REVIEW_REASON = "Initial Review"


class OrdinaryReviewMixin:
    """The GUI captures scope; services own eligibility, money and transactions."""

    @staticmethod
    def _presentation_rows(snapshot):
        # Raw lender evidence can be consumed through a loan source-use record
        # without an ordinary journal allocation. The snapshot's verified owner
        # is authoritative for displaying and navigating that reviewed event.
        owned = {owner.row_id for owner in snapshot.owners}
        return tuple(
            replace(row, status="Already posted to the ledger")
            if row.row_id in owned and row.entry_key is None
            else row
            for row in snapshot.rows
        )

    def _setup_jobs(self, profile, *, embedded=False):
        install_form_styles(self)
        self.decision_group.setProperty("formRole", "decision")
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.Widget)
        self._snapshot = None
        self.pending_transfers = {}
        self.zero_reviews = {}
        self.transfer_eligible_row_ids = frozenset()
        self._restore_draft = None
        self._completion_message = ""
        self._selected_after_read = None
        self._row_drafts = {}
        self._in_multi = False
        self._multi_form = (None, None, "")
        self._multi_form_ids = ()
        self._restore_multi = None
        self._form_row_id = None
        self._form_entry_key = None
        self._form_baseline = (None, None, None)
        self._reset_form_after_write = False
        self.saved_review_note = QPlainTextEdit()
        self.saved_review_note.setReadOnly(True)
        self.saved_review_note.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.saved_review_note.setTabChangesFocus(True)
        self.saved_review_note.document().setDocumentMargin(2)
        self.saved_review_note.setAccessibleName("Saved review note")
        self.saved_review_note.setAccessibleDescription(
            "The active entry's saved note. Select or copy it for context; it is not a new correction reason."
        )
        note_row, _role = self.form.getWidgetPosition(self.reason)
        self.form.insertRow(note_row, "Saved review note", self.saved_review_note)
        self.form.setRowVisible(self.saved_review_note, False)
        set_field_state(self.saved_review_note, "readonly")
        self.setTabOrder(getattr(self, "accounting_date", self.manage_categories_button), self.saved_review_note)
        self.setTabOrder(self.saved_review_note, self.reason)
        self.jobs = ProfileJobs(self, profile)
        self.jobs.completed.connect(self._job_completed)
        self.jobs.failed.connect(self._job_failed)
        self.jobs.busy_changed.connect(self._job_busy)
        self.operation_status = QLabel("Loading saved review…")
        self.operation_status.setWordWrap(True)
        self.operation_status.setAccessibleName("Review operation status")
        self.layout().insertWidget(1, self.operation_status)
        self.cancel_read_button = QPushButton("Cancel loading")
        self.cancel_read_button.clicked.connect(self._cancel_loading)
        self.layout().insertWidget(2, self.cancel_read_button, alignment=Qt.AlignLeft)
        self.batch = OrdinaryBatchPanel(self)
        self.transfer_source_date_button = QPushButton("Use statement date for transfer")
        self.transfer_source_date_button.clicked.connect(self._use_transfer_source_date)
        self.form.addRow(self.transfer_source_date_button)
        self.transfer_source_date_button.hide()
        self.table.horizontalHeader().moveSection(self.model.columnCount() - 1, 0)
        self.setTabOrder(self.reason, self.batch.reason)
        self.setTabOrder(self.batch.reason, self.batch.stage_button)
        self.setTabOrder(self.batch.stage_button, self.action_button)
        self.setTabOrder(self.action_button, self.withdraw_button)
        self.repeat_review_button = QPushButton("Review possible repeated transactions…")
        self.repeat_review_button.setToolTip(
            "Compare occurrences in different documents before deciding whether they are the same transaction."
        )
        self.repeat_review_button.clicked.connect(self._review_possible_repeats)
        self.actions_layout.addWidget(self.repeat_review_button)
        self.repeat_review_button.hide()
        self.match_transfer_button = QPushButton("Review match…")
        self.match_transfer_button.clicked.connect(self._review_pending_match)
        self.actions_layout.addWidget(self.match_transfer_button)
        self.match_transfer_button.hide()
        self.batch.reason.textChanged.connect(self._update_review_actions)
        self.table.selectionModel().selectionChanged.connect(self._selection_membership_changed)
        self.navigation.exact_row_requested.connect(self._exact_row_requested)
        self.layout().insertWidget(self.layout().count() - 1, self.batch)
        self.evidence_details_button = QPushButton("Source and interpretation details")
        self.evidence_details_button.setCheckable(True)
        self.evidence_details_button.toggled.connect(self.source_context.setVisible)
        self.evidence_details_button.toggled.connect(self.history_details.setVisible)
        self.source_context.hide()
        self.history_details.hide()
        self.layout().insertWidget(self.layout().indexOf(self.source_context), self.evidence_details_button)
        # Routine source inspection has one consistent footer action. Rare
        # reload/rule/diagnostic controls remain keyboard-accessible in a menu.
        self.secondary_button = QPushButton("More review options…")
        self.secondary_menu = QMenu(self.secondary_button)
        self.secondary_button.setMenu(self.secondary_menu)
        for button, label in (
            (self.review_limits_button, "Review rules and source limits"),
            (self.evidence_details_button, "Source and review details"),
        ):
            self.layout().removeWidget(button)
            button.hide()
            action = self.secondary_menu.addAction(label)
            action.setCheckable(True)
            action.toggled.connect(button.setChecked)
        self.layout().removeWidget(self.preview_source_button)
        self.preview_source_button.setText("View statement evidence…")
        for button_box in self.findChildren(QDialogButtonBox):
            close = button_box.button(QDialogButtonBox.Close)
            if close is not None and embedded:
                close.hide()
            for button in button_box.buttons():
                if button.text() == "Reload saved review":
                    self.secondary_menu.addAction("Reload saved review", self._reload_review)
                    button_box.removeButton(button)
                    button.deleteLater()
            button_box.addButton(self.preview_source_button, QDialogButtonBox.ActionRole)
            button_box.addButton(self.secondary_button, QDialogButtonBox.ActionRole)
        if embedded:
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.layout().setSpacing(3)
            self.review_intro.hide()
            self.overlap_note.hide()
            self.layout().removeWidget(self.cancel_read_button)
            self.navigation.layout().addWidget(self.cancel_read_button)

    def _selection_membership_changed(self, *_args):
        # Qt updates selection before emitting this signal. Navigation resolves
        # a sole selected row even when currentIndex is an old/deselected anchor.
        self._refresh_selection_scope()

    def _reload_review(self):
        if not self.jobs.writing:
            row = self._current()
            self.refresh(selected_row_id=row.row_id if row is not None else None)

    def _exact_row_requested(self, row_id):
        if self.jobs.pending and not self.jobs.writing:
            self._selected_after_read = row_id
            if self._restore_multi is not None:
                _ids, proposal, drafts = self._restore_multi
                # A report handoff replaces the restored selection, not the
                # unrelated common proposal or row drafts captured by refresh.
                self._restore_multi = ((row_id,), proposal, drafts)

    def _refresh_selection_scope(self):
        row = self.navigation.current()
        if len(self.navigation.selected()) > 1 or self._in_multi or self._form_row_id != (row.row_id if row else None):
            self._selected()

    def _single_selection(self):
        return len(self.navigation.selected()) == 1

    def _pending_transfer(self, row):
        state = self.pending_transfers.get(row.row_id) if row is not None else None
        return state if state is not None and state.review.action == "pending" and state.status != "consumed" else None

    def _row_review_key(self, row):
        if row is None:
            return None
        state = self._pending_transfer(row)
        zero = self._zero_review(row)
        if zero is not None:
            return f"zero-review:{zero.revision_id}"
        return f"pending-transfer:{state.revision_id}" if state is not None else row.entry_key

    def _zero_review(self, row):
        review = self.zero_reviews.get(row.row_id) if row is not None else None
        return review if review is not None and review.action == "reviewed" else None

    def _zero_review_form_cues(self, row):
        if row is None or row.amount_minor != 0:
            return False
        saved = self._zero_review(row)
        if saved is None and row.status != "Ready for purpose review":
            return False
        usable = not self.jobs.pending and self.basis is not None and self._profile_matches()
        self.match_transfer_button.hide()
        if hasattr(self, "accounting_date"):
            self.form.setRowVisible(self.accounting_date, False)
        if hasattr(self, "assumed_dates"):
            self.assumed_dates.hide()
        self.purpose.setEnabled(usable)
        self.category.setEnabled(usable)
        self.form.setRowVisible(self.category_row, True)
        self.form.setRowVisible(self.reason, saved is not None)
        self.form.setRowVisible(self.saved_review_note, saved is not None)
        self.batch.setVisible(saved is None or bool(self.batch.staged) or self.batch.reason_is_dirty)
        self.batch.stage_button.setVisible(saved is None)
        self.action_button.setVisible(saved is not None)
        self.withdraw_button.setVisible(saved is not None)
        self.manage_categories_button.setEnabled(usable and self.purpose.currentData() is not None)
        if saved is None:
            self.decision_group.setTitle("Review zero-value transaction")
            self.batch.update_stage_action()
            set_status(
                self.status,
                "ready" if usable else "loading",
                "$0.00 source row. Review its purpose and category; no journal entry or spending is created.",
            )
            return True
        self.decision_group.setTitle("Correct zero-value review")
        self.saved_review_note.setPlainText(saved.reason)
        self.saved_review_note.setFixedHeight(2 * self.saved_review_note.fontMetrics().lineSpacing() + 10)
        self.reason.setEnabled(usable)
        self.reason.setPlaceholderText("Enter a new reason to change or withdraw this review")
        self.form.labelForField(self.reason).setText("Reason for correction *")
        changed = (self.purpose.currentData(), self.category.currentData()) != (saved.purpose, saved.category_id)
        reason = bool(self.reason.text().strip())
        self.action_button.setText("Save zero-value review correction")
        self.action_button.setEnabled(
            usable
            and changed
            and reason
            and self.purpose.currentData() in row.allowed_purposes
            and self.category.currentData() is not None
        )
        self.withdraw_button.setText("Withdraw zero-value review")
        self.withdraw_button.setEnabled(usable and reason)
        set_status(
            self.status,
            "ready" if changed and reason else "saved",
            "$0.00 reviewed · no journal entry. Enter a new reason to change or withdraw this decision.",
        )
        return True

    def _act_zero_review(self):
        row = self._current()
        saved = self._zero_review(row)
        if saved is None:
            return False
        if not self._single_selection() or not self.action_button.isEnabled():
            return True
        reason, basis = self.reason.text().strip(), self.basis
        row_id, revision = row.row_id, saved.revision_id
        category, purpose = self.category.currentData(), self.purpose.currentData()
        if (
            QMessageBox.question(
                self,
                "Correct zero-value review",
                f"Save the changed purpose/category for this $0.00 source row?\n\n{row.description}\nReason: {reason}\n\nNo journal entry or spending is created.",
            )
            != QMessageBox.Yes
        ):
            return True
        self._submit_review_write(
            lambda store, _cancelled: store.review_zero_amount(
                row_id, category, purpose, reason=reason, expected_basis_sha256=basis, expected_revision_id=revision
            ),
            message="$0.00 review corrected. No money posted.",
            row_id=row_id,
        )
        return True

    def _withdraw_zero_review(self):
        row = self._current()
        saved = self._zero_review(row)
        if saved is None:
            return False
        if not self._single_selection() or not self.withdraw_button.isEnabled():
            return True
        reason, basis, row_id, revision = self.reason.text().strip(), self.basis, row.row_id, saved.revision_id
        if (
            QMessageBox.question(
                self,
                "Withdraw zero-value review",
                f"Return this $0.00 source row to review?\n\n{row.description}\nReason: {reason}\n\nNo money is posted or reversed.",
            )
            != QMessageBox.Yes
        ):
            return True
        self._submit_review_write(
            lambda store, _cancelled: store.withdraw_zero_amount_review(
                row_id, reason=reason, expected_basis_sha256=basis, expected_revision_id=revision
            ),
            message="$0.00 review withdrawn. No money posted.",
            row_id=row_id,
        )
        return True

    def _offered_purposes(self, row):
        if row is None or reviewed_elsewhere(row):
            return ()
        if row.entry_key is not None:
            return (row.purpose,)
        purposes = tuple(row.allowed_purposes)
        if row.row_id in self.transfer_eligible_row_ids or self._pending_transfer(row):
            purposes += ("transfer",)
        return purposes

    def _review_pending_match(self):
        row = self._current()
        state = self._pending_transfer(row)
        workspace = getattr(self, "workspace", None)
        if not self._single_selection() or state is None or state.status != "match_available" or workspace is None:
            return
        if self.jobs.pending or self.basis is None or not self._profile_matches():
            return
        from parsetrail.gui.v2_transfer_review import V2TransferReview

        exec_disposable(V2TransferReview(workspace, self, focus_row_id=row.row_id, require_pending_intents=True))
        self.refresh_preserving_draft()
        self.changed.emit()

    def _pending_transfer_form_cues(self, row):
        """Saved intent and new designation remain separate from money posting."""
        state = self._pending_transfer(row)
        transfer = self.purpose.currentData() == "transfer"
        if state is None and not transfer:
            if hasattr(self, "accounting_date"):
                self.accounting_date.setReadOnly(self.register_mode)
            self.match_transfer_button.hide()
            return False
        usable = row is not None and not self.jobs.pending and self.basis is not None and self._profile_matches()
        correcting = state is not None
        self.decision_group.setTitle("Change transfer designation" if correcting else "Selected transaction")
        self.purpose.setEnabled(usable)
        self.form.setRowVisible(self.category_row, not transfer)
        self.category.setEnabled(usable and not transfer)
        self.manage_categories_button.setEnabled(
            usable and self.purpose.currentData() in {"expense", "expense_refund", "income", "income_adjustment"}
        )
        if hasattr(self, "accounting_date"):
            self.form.setRowVisible(self.accounting_date, not correcting or not transfer)
            self.accounting_date.setReadOnly(transfer or self.register_mode)
            if transfer:
                self.form.labelForField(self.accounting_date).setText("Accounting date (from statement)")
            date_issue = self._transfer_date_issue(row) if transfer else None
            self.transfer_source_date_button.setVisible(bool(date_issue and "Use statement date" in date_issue))
            self.transfer_source_date_button.setEnabled(usable)
        if hasattr(self, "assumed_dates"):
            self.assumed_dates.setVisible(not self.register_mode and (not correcting or not transfer))
            self.assumed_dates.setEnabled(usable and not self.register_mode)
        self.form.setRowVisible(self.reason, correcting)
        self.form.setRowVisible(self.saved_review_note, correcting)
        self.action_button.setVisible(correcting)
        self.withdraw_button.setVisible(correcting)
        self.batch.stage_button.setVisible(not correcting)
        self.batch.setVisible(not correcting or bool(self.batch.staged) or self.batch.reason_is_dirty)
        self.match_transfer_button.setVisible(correcting)
        self.match_transfer_button.setEnabled(
            usable
            and state is not None
            and state.status == "match_available"
            and getattr(self, "workspace", None) is not None
        )
        if correcting:
            self.saved_review_note.setPlainText(state.reason)
            self.saved_review_note.setFixedHeight(2 * self.saved_review_note.fontMetrics().lineSpacing() + 10)
            self.saved_review_note.setToolTip(state.reason)
            self.reason.setEnabled(usable)
            self.reason.setAccessibleName("Reason for correction, required for a changed transfer designation")
            self.reason.setPlaceholderText("Enter a new reason to change or withdraw this designation")
            self.form.labelForField(self.reason).setText("Reason for correction *")
            reason = self.reason.text().strip()
            category_ok = (
                self.purpose.currentData() in row.allowed_purposes
                and self.category.currentData() is not None
                and row.status in {"Ready for purpose review", "Enable assumed dates or enter a corrected date"}
            )
            date_ok = True
            if category_ok and hasattr(self, "accounting_date"):
                try:
                    value = self.accounting_date.text().strip()
                    date_ok = date.fromisoformat(value).isoformat() == value
                    if (
                        row.status == "Enable assumed dates or enter a corrected date"
                        and value == self._posting_candidate(row)
                    ):
                        date_ok = False
                except ValueError:
                    date_ok = False
            eligible = row.row_id in self.transfer_eligible_row_ids
            self.action_button.setText("Save transfer designation" if transfer else "Confirm category instead…")
            self.action_button.setEnabled(
                usable and bool(reason) and ((transfer and eligible) or (category_ok and date_ok))
            )
            self.withdraw_button.setText("Withdraw transfer designation")
            self.withdraw_button.setEnabled(usable and bool(reason))
            set_field_state(self.reason, "ready" if reason else "required" if not transfer else "optional")
            set_field_state(self.purpose, "saved" if transfer else "ready")
            if not transfer:
                set_field_state(self.category, "ready" if category_ok else "required")
            status = {
                "waiting": "Transfer / card repayment saved · waiting. Import the other statement when available, then mark its matching row as Transfer / card repayment.",
                "match_available": "Transfer / card repayment saved · a possible match is available.",
                "stale": "Transfer designation needs review because its source or account context changed.",
                "blocked": "Transfer designation cannot be matched until its source prerequisites are resolved.",
            }.get(state.status, "Saved transfer designation.")
            set_status(
                self.status,
                "loading" if self.jobs.pending else "ready" if reason else "saved",
                status
                + " No money posted. "
                + (
                    "Use the new reason to confirm a change." if reason or not transfer else "Review match is optional."
                ),
            )
            history = tuple(
                item for item in getattr(self._snapshot, "pending_transfer_history", ()) if item.row_id == row.row_id
            )
            self.history_details.setText(
                "Transfer designation history: " + "; ".join(f"{item.action}: {item.reason}" for item in history)
            )
        else:
            self.action_button.setEnabled(False)
            self.withdraw_button.setEnabled(False)
            set_field_state(self.purpose, "ready" if usable else "loading")
            set_status(
                self.status,
                "ready" if usable else "loading",
                self._transfer_date_issue(row)
                or "Stage this transfer/card repayment. Confirmation posts this source side against clearing; resolve its counterpart later in Transfers.",
            )
        self.batch.update_stage_action()
        return True

    def _transfer_date_issue(self, row, *, multiple=False):
        if row is None or self.review_kind != "card" or self.register_mode:
            return None
        candidate = self._posting_candidate(row)
        draft = self._row_drafts.get(row.row_id)
        previous = self.batch.staged.get(row.row_id)
        value = (
            (
                draft[3]
                if draft is not None and draft[3]
                else str(previous.accounting_date)
                if getattr(previous, "accounting_date", None) is not None
                else candidate
            )
            if multiple
            else self.accounting_date.text().strip()
        )
        if value != candidate:
            return "Transfer posting uses the statement date. Use statement date for transfer to replace the category-date override, or return to category review to keep it."
        if row.date_provenance == "assumed" and not self.review_preferences.allow_assumed_posting_dates:
            return "Enable best guess posting dates before posting this transfer, or leave it for later."
        return None

    def _use_transfer_source_date(self):
        row = self._current()
        if row is not None and not self.jobs.pending and hasattr(self, "accounting_date"):
            self.accounting_date.setText(self._posting_candidate(row) or "")
            self._update_review_actions()

    def _act_pending_transfer(self):
        from parsetrail.gui.v2_cash_activity_review import _money

        row = self._current()
        state = self._pending_transfer(row)
        if state is None:
            return False
        if not self._single_selection() or not self.action_button.isEnabled():
            return True
        reason, basis, revision = self.reason.text().strip(), self.basis, state.revision_id
        if self.purpose.currentData() == "transfer":
            if (
                QMessageBox.question(
                    self,
                    "Save transfer designation",
                    f"Save this transfer/card-repayment designation?\n\n{row.description}\nAccount: {row.financial_account or 'Not assigned'}\nSource amount: {_money(row.amount_minor)}\nPreviously designated account: {state.review.movement.account_name}\nReason: {reason}\n\nNo journal entry, income or spending is created. Matching still requires a separate confirmation.",
                )
                != QMessageBox.Yes
            ):
                return True
            row_id = row.row_id
            self._submit_review_write(
                lambda store, _cancelled: store.set_pending_transfer(
                    row_id, expected_basis_sha256=basis, expected_revision_id=revision, reason=reason
                ),
                message="Transfer designation saved. No money posted.",
                row_id=row_id,
            )
        else:
            from parsetrail.core.v2_ordinary_batch import OrdinaryCategorySelection

            accounting_date = None
            if self.review_kind == "card":
                value = self.accounting_date.text().strip()
                if value != row.posting_candidate:
                    accounting_date = date.fromisoformat(value)
            selection = OrdinaryCategorySelection(
                row.row_id, self.category.currentData(), self.purpose.currentData(), accounting_date, revision
            )
            source, kind = self.source_sha256, self.review_kind
            preferences = self.review_preferences if kind == "card" else None
            self.jobs.submit(
                ("preview_pending_correction", row.row_id),
                lambda store, cancelled: store.preview_reviewed_ordinary_batch(
                    source,
                    kind=kind,
                    selections=(selection,),
                    reason=reason,
                    expected_basis_sha256=basis,
                    preferences=preferences,
                    cancelled=cancelled,
                ),
            )
        return True

    def _withdraw_pending_transfer(self):
        from parsetrail.gui.v2_cash_activity_review import _money

        row = self._current()
        state = self._pending_transfer(row)
        if state is None:
            return False
        reason = self.reason.text().strip()
        if not self._single_selection() or not reason or not self.withdraw_button.isEnabled():
            return True
        if (
            QMessageBox.question(
                self,
                "Withdraw transfer designation",
                f"Withdraw this transfer/card-repayment designation?\n\n{row.description}\nSaved account: {state.review.movement.account_name}\nSource amount: {_money(state.review.movement.amount_minor)}\nReason: {reason}\n\nThe source returns to ordinary review. No money is posted or reversed.",
            )
            != QMessageBox.Yes
        ):
            return True
        row_id, basis, revision = row.row_id, self.basis, state.revision_id
        self._submit_review_write(
            lambda store, _cancelled: store.withdraw_pending_transfer(
                row_id, expected_basis_sha256=basis, expected_revision_id=revision, reason=reason
            ),
            message="Transfer designation withdrawn. No money posted.",
            row_id=row_id,
        )
        return True

    def _handle_multi_selection(self):
        rows = self.navigation.selected()
        if len(rows) <= 1:
            if self._in_multi:
                self._multi_form = (self.purpose.currentData(), self.category.currentData(), self.reason.text())
                self._in_multi = False
                self._form_row_id = None
                self.reason.clear()
            return False
        entering = not self._in_multi
        self._multi_form_ids = tuple(row.row_id for row in rows)
        if entering:
            self._remember_row_form()
            self._in_multi = True
            purpose, category, note = self._multi_form
        else:
            purpose, category, note = self.purpose.currentData(), self.category.currentData(), self.reason.text()
        common = set.intersection(*(set(self._offered_purposes(row)) for row in rows))
        offered = tuple(
            key for key in ("expense", "expense_refund", "income", "income_adjustment", "transfer") if key in common
        )
        if entering or tuple(self.purpose.itemData(i) for i in range(1, self.purpose.count())) != offered:
            self.purpose.blockSignals(True)
            self.purpose.clear()
            self.purpose.addItem("Choose one purpose for every selected row", None)
            from parsetrail.gui.v2_cash_activity_review import PURPOSE_LABELS

            for key in offered:
                self.purpose.addItem(PURPOSE_LABELS[key], key)
            self.purpose.setCurrentIndex(max(0, self.purpose.findData(purpose)))
            self.purpose.blockSignals(False)
            self._purpose_changed()
            self.category.setCurrentIndex(max(0, self.category.findData(category)))
            self.reason.setText(note)
        self._update_review_actions()
        return True

    def _multi_form_cues(self):
        self.match_transfer_button.hide()
        self.form.setRowVisible(self.saved_review_note, False)
        self.batch.show()
        rows = self.navigation.selected()
        count = len(rows)
        self.decision_group.setTitle(f"Review {count} selected transactions")
        usable = not self.jobs.pending and self.basis is not None and self._profile_matches()
        self.action_button.setText("Review one transaction individually")
        self.action_button.setEnabled(False)
        self.action_button.hide()
        self.batch.stage_button.show()
        self.withdraw_button.setEnabled(False)
        self.withdraw_button.setVisible(False)
        if hasattr(self, "assumed_dates"):
            self.assumed_dates.setEnabled(False)
        missing = []
        rows = self.navigation.selected()
        _proposal, blockers = self.batch.propose(rows, self.purpose.currentData(), self.category.currentData())
        if self.purpose.count() == 1:
            blockers.insert(
                0, "These rows have no common review purpose. Select compatible pending rows or review individually."
            )
        self.form.setRowVisible(self.reason, False)
        transfer = self.purpose.currentData() == "transfer"
        for field, name in ((self.purpose, "type"), (self.category, "category")):
            if field is self.category and transfer:
                self.form.setRowVisible(self.category_row, False)
                continue
            self.form.setRowVisible(self.category_row if field is self.category else field, True)
            field.setEnabled(usable)
            valid = bool(field.text().strip()) if field is self.reason else field.currentData() is not None
            if not valid:
                missing.append(name)
            set_field_state(
                field, "ready" if usable and valid else "required" if usable and not blockers else "neutral"
            )
        if not self.batch.reason.text().strip():
            missing.append("shared reason")
        self.manage_categories_button.setEnabled(usable and self.purpose.currentData() is not None)
        if hasattr(self, "accounting_date"):
            self.form.setRowVisible(self.accounting_date, not transfer)
            self.form.labelForField(self.accounting_date).setText("3. Dates (per row)")
            self.accounting_date.setEnabled(False)
            self.accounting_date.setPlaceholderText("Each row keeps its own date")
            self.accounting_date.blockSignals(True)
            self.accounting_date.clear()
            self.accounting_date.blockSignals(False)
            set_field_state(
                self.accounting_date, "readonly", "Each row keeps its own date; stage date overrides individually."
            )
        changed = self.batch.selection_changed(rows)
        all_staged = all(row.row_id in self.batch.staged for row in rows)
        self.batch.stage_button.setText(f"Update {count} staged" if all_staged else f"Stage {count} selected")
        self.batch.stage_button.setEnabled(usable and not missing and not blockers and changed)
        set_field_state(self.batch.stage_button, "ready" if self.batch.stage_button.isEnabled() else "neutral")
        set_status(
            self.status,
            "blocked"
            if usable and blockers
            else "required"
            if usable and missing
            else "ready"
            if usable
            else "loading",
            (
                f"Cannot stage {count} selected; nothing changed. "
                + " · ".join(tuple(dict.fromkeys(blockers))[:2])
                + (f" · {len(blockers)} prerequisites in total; review individually." if len(blockers) > 2 else "")
                + " Prior staged choices are kept."
            )
            if usable and blockers
            else ("Choose " + ", ".join(missing) + ". " if missing else "")
            + f"Stage {count} selected, then review the set before posting."
            + (
                " Each row keeps its own date; date overrides must be staged individually."
                if hasattr(self, "accounting_date")
                else ""
            )
            if usable
            else "Loading saved review; selected choices are kept. Wait before staging.",
        )

    def _manage_multi_categories(self):
        if len(self.navigation.selected()) <= 1:
            return False
        if not self.manage_categories_button.isEnabled():
            return True
        from parsetrail.gui.v2_cash_activity_review import PURPOSE_KINDS
        from parsetrail.gui.v2_categories import V2CategoryDialog

        ids = tuple(row.row_id for row in self.navigation.selected())
        purpose, category, note = self.purpose.currentData(), self.category.currentData(), self.reason.text()
        old_ids = {item.id for item in self.categories}
        dialog = V2CategoryDialog(self.jobs.profile, self)
        dialog.add_kind.setCurrentIndex(dialog.add_kind.findData(PURPOSE_KINDS[purpose]))
        dialog.begin_add()
        dialog.exec()
        selected = dialog.categories.currentItem()
        created = selected.data(Qt.UserRole) if selected is not None else None
        self._restore_multi = (
            ids,
            (purpose, created if created is not None and created not in old_ids else category, note),
            dict(self._row_drafts),
        )
        self.refresh()
        return True

    @staticmethod
    def _repeat_blocked(row):
        return row.status in {
            "Cross-source occurrence needs review",
            "Repeated supporting evidence; post the retained row",
        }

    def _review_possible_repeats(self):
        if self.jobs.pending or self.basis is None or not self._profile_matches():
            return
        blocked = next((row for row in self.navigation.selected() if self._repeat_blocked(row)), None)
        if blocked is None:
            return
        from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview

        V2SourceOverlapReview(
            self.jobs.profile,
            self,
            focus_row_id=blocked.row_id,
            focus_requires_review=blocked.status == "Cross-source occurrence needs review",
        ).exec()
        self.refresh_preserving_draft()
        self.changed.emit()

    def _update_form_cues(self, base_status=None):
        """Describe local choices separately from saved state and posting eligibility."""
        if not hasattr(self, "jobs"):
            return
        self.transfer_source_date_button.hide()
        self.batch.update_summary()
        repeat_blocked = any(self._repeat_blocked(row) for row in self.navigation.selected())
        self.repeat_review_button.setVisible(repeat_blocked)
        self.repeat_review_button.setEnabled(
            repeat_blocked and not self.jobs.pending and self.basis is not None and self._profile_matches()
        )
        set_field_state(self.repeat_review_button, "ready" if self.repeat_review_button.isEnabled() else "neutral")
        if len(self.navigation.selected()) > 1:
            self._multi_form_cues()
            return
        self.batch.stage_button.setText("Stage selected" if self.embedded else "Stage selected rows")
        if base_status is not None:
            self._base_review_status = base_status
        row = self._current()
        if self._zero_review_form_cues(row):
            return
        if self._pending_transfer_form_cues(row):
            return
        self.withdraw_button.setText("Withdraw active interpretation")
        if hasattr(self, "assumed_dates"):
            self.assumed_dates.setVisible(not self.register_mode)
        self.batch.update_stage_action()
        if hasattr(self, "assumed_dates"):
            self.assumed_dates.setEnabled(not self.jobs.pending and not self.register_mode)
        if hasattr(self, "accounting_date"):
            self.form.labelForField(self.accounting_date).setText("3. Accounting date *")
        fields = [self.purpose, self.category, self.reason]
        if hasattr(self, "accounting_date"):
            fields.append(self.accounting_date)
        pending = self.jobs.pending
        correction = row is not None and row.entry_key is not None
        owner_route = reviewed_elsewhere(row) or self.purpose.currentData() in {"repayment", "external_history"}
        saved_entry = self.entries.get(row.entry_key) if correction and not owner_route else None
        self.form.setRowVisible(self.saved_review_note, saved_entry is not None)
        saved_note = saved_entry.reason if saved_entry is not None else ""
        if self.saved_review_note.toPlainText() != saved_note:
            self.saved_review_note.setPlainText(saved_note)
        note_width = max(300, self.saved_review_note.viewport().width())
        note_lines = (
            2
            if "\n" in saved_note or self.saved_review_note.fontMetrics().horizontalAdvance(saved_note) > note_width
            else 1
        )
        self.saved_review_note.setFixedHeight(
            note_lines * self.saved_review_note.fontMetrics().lineSpacing()
            + 2 * self.saved_review_note.frameWidth()
            + 2 * int(self.saved_review_note.document().documentMargin())
            + 2
        )
        self.saved_review_note.setToolTip(saved_note)
        # Saved corrections need no empty batch strip. Retain any unrelated
        # staged work and its explicit summary/preview controls.
        self.batch.setVisible(not (correction or owner_route) or bool(self.batch.staged) or self.batch.reason_is_dirty)
        self.form.setRowVisible(self.reason, correction and not owner_route)
        self.reason.setAccessibleName(
            "Reason for correction, required for a new decision" if correction else "Review note, required"
        )
        self.reason.setPlaceholderText(
            "Enter a new reason to correct or withdraw this saved review" if correction else ""
        )
        self.action_button.setVisible(correction or owner_route)
        if not correction and not owner_route:
            self.action_button.setEnabled(False)
        self.batch.stage_button.setVisible(not correction and not owner_route)
        self.withdraw_button.setVisible(correction)
        set_field_state(self.action_button, "neutral")
        self.decision_group.setTitle("Correct saved review" if correction else "Selected transaction")
        if pending or self.basis is None or not self._profile_matches() or row is None:
            state = "loading" if pending else "blocked" if row is not None else "neutral"
            for field in fields:
                set_field_state(field, state)
                field.setEnabled(False)
            text = (
                "Loading saved review… Your choices are kept; wait before confirming."
                if pending and not self.jobs.writing
                else "Saving confirmed review… Wait for the saved result."
                if self.jobs.writing
                else "Reload saved review before confirming; your choices are kept."
                if row is not None
                else "Select a transaction to review its required choices."
            )
            set_status(self.status, state, text)
            return
        purpose = self.purpose.currentData()
        if reviewed_elsewhere(row) or purpose in {"repayment", "external_history"}:
            for field in fields:
                set_field_state(field, "readonly", "This decision belongs to the related review workflow.")
            set_status(
                self.status,
                "saved" if reviewed_elsewhere(row) else "neutral",
                getattr(self, "_base_review_status", row.status),
            )
            return
        supported = correction or row.status in {
            "Ready for purpose review",
            "Enable assumed dates or enter a corrected date",
        }
        if not supported:
            for field in fields:
                set_field_state(field, "blocked")
                field.setEnabled(False)
            if self._repeat_blocked(row):
                self.action_button.hide()
                set_status(
                    self.status,
                    "blocked",
                    "Possible repeat in another document. Use Review possible repeated transactions to compare the "
                    "sources and decide whether they represent the same transaction or separate transactions. "
                    "This decision posts no money; category review follows for eligible rows."
                    if row.status == "Cross-source occurrence needs review"
                    else "This occurrence is saved as supporting evidence for a transaction in another document. "
                    "It cannot post separately. Review possible repeated transactions to inspect the retained occurrence.",
                )
            else:
                set_status(
                    self.status, "blocked", "Needs attention: " + getattr(self, "_base_review_status", row.status)
                )
            return
        changed = correction and self.category.currentData() != row.category_id
        selected_date = None
        valid_date = True
        date_changed = False
        date_choice_needed = False
        if hasattr(self, "accounting_date"):
            selected_date = self.accounting_date.text().strip()
            try:
                valid_date = date.fromisoformat(selected_date).isoformat() == selected_date
            except ValueError:
                valid_date = False
            date_changed = correction and selected_date != row.effective_date
            changed = changed or date_changed
            date_choice_needed = (
                not correction
                and row.status == "Enable assumed dates or enter a corrected date"
                and selected_date == self._posting_candidate(row)
            )
        missing = []
        if purpose not in {"expense", "expense_refund", "income", "income_adjustment"}:
            missing.append("type")
            set_field_state(
                self.purpose, "required", "Choose a purpose explicitly; the amount sign does not decide it."
            )
        else:
            set_field_state(self.purpose, "saved" if correction else "ready")
        category = self.category.currentData()
        if category is None:
            missing.append("category")
            set_field_state(self.category, "required", "Choose a category or add one using Manage categories.")
        else:
            set_field_state(self.category, "saved" if correction and category == row.category_id else "ready")
        if selected_date is not None:
            if getattr(self, "register_mode", False):
                set_field_state(self.accounting_date, "readonly", "The printed-derived register posting date is fixed.")
            elif not valid_date:
                missing.append("valid accounting date")
                set_field_state(
                    self.accounting_date, "required" if not selected_date else "invalid", "Enter YYYY-MM-DD."
                )
            elif date_choice_needed:
                missing.append("posting-date decision")
                set_field_state(
                    self.accounting_date,
                    "required",
                    "This estimated source candidate needs your decision: allow assumed dates or enter a different accounting date.",
                )
            else:
                set_field_state(
                    self.accounting_date,
                    "saved" if correction and not date_changed else "ready",
                    f"Source posting-date provenance: {row.date_provenance}. Source evidence is unchanged.",
                )
        note = (self.reason if correction else self.batch.reason).text().strip()
        note_required = not correction or changed
        note_label = self.form.labelForField(self.reason)
        note_label.setText(
            (
                "Reason for correction "
                if correction
                else f"{'4' if hasattr(self, 'accounting_date') else '3'}. Review note "
            )
            + ("— applies to all staged rows " if not correction else "")
            + ("*" if note_required else "(for changes)")
        )
        if not note and note_required:
            missing.append("reason for correction" if correction else "shared reason")
            if correction:
                set_field_state(self.reason, "required", "Explain this correction before confirming.")
        elif correction:
            set_field_state(self.reason, "ready" if note else "optional", "A new correction needs a review note.")
        if correction and not changed:
            editable = (
                "category or accounting date" if selected_date is not None and not self.register_mode else "category"
            )
            set_status(
                self.status,
                "saved",
                f"Saved review. Change the {editable} to correct, or enter a new reason to withdraw."
                + (" New reason · Not saved." if note else " No changes to save."),
            )
        elif date_choice_needed:
            set_status(
                self.status,
                "blocked",
                "Posting date needs your decision; nothing can post. "
                "Allow estimated dates or enter a different accounting date.",
            )
        elif missing:
            detail = (
                " Use Manage categories to add an "
                + ("income" if purpose in {"income", "income_adjustment"} else "expense")
                + " category first."
                if purpose is not None and self.category.count() == 1
                else ""
            )
            set_status(
                self.status,
                "required",
                ("Unsaved correction · " if correction else "")
                + "Required: "
                + ", ".join(missing)
                + " · Not saved."
                + detail,
            )
        elif not correction and row.row_id in self.batch.staged:
            dirty = self.batch.selection_changed((row,))
            set_status(
                self.status,
                "ready",
                "Changes not staged. Stage selected to update the review set."
                if dirty
                else "In review set · not posted. Review staged to check and confirm.",
            )
        elif not correction and self.batch.stage_button.isEnabled():
            set_status(
                self.status,
                "ready",
                "Ready. Stage selected, then review the set before posting.",
            )
        elif self.action_button.isEnabled():
            set_field_state(self.action_button, "ready", "Confirmation is still required before this choice is saved.")
            set_status(
                self.status,
                "ready",
                ("Unsaved correction · " if correction else "")
                + "Ready to confirm · Not saved. The confirmation shows the exact effects.",
            )
        else:
            set_status(self.status, "blocked", "Needs attention: " + getattr(self, "_base_review_status", row.status))

    @property
    def review_pending(self):
        return self.jobs.pending

    @property
    def has_unsaved_draft(self):
        common = (
            (self.purpose.currentData(), self.category.currentData(), self.reason.text())
            if self._in_multi
            else self._multi_form
        )
        return bool(
            self.batch.staged
            or self.reason.text().strip()
            or self.batch.reason_is_dirty
            or self._form_dirty()
            or any(
                draft[-1] or draft[-2].strip()
                for row_id, draft in self._row_drafts.items()
                if row_id != self._form_row_id
            )
            or common[0] is not None
            or common[1] is not None
            or common[2].strip()
        )

    def refresh_preserving_draft(self):
        """Refresh account/source inventory without losing the authored review scope."""
        if self.jobs.writing:
            return False
        rows = self.navigation.selected()
        self._remember_row_form()
        if len(rows) != 1:
            proposal = (
                (self.purpose.currentData(), self.category.currentData(), self.reason.text())
                if self._in_multi
                else self._multi_form
            )
            self._restore_multi = (tuple(row.row_id for row in rows), proposal, dict(self._row_drafts))
        self.refresh(selected_row_id=rows[0].row_id if len(rows) == 1 else None)
        return True

    def _form_dirty(self):
        if self._form_row_id is None:
            return False
        purpose, category, original_date = self._form_baseline
        return bool(
            self.purpose.currentData() not in {purpose, "repayment", "external_history"}
            or self.category.currentData() != category
            or (hasattr(self, "accounting_date") and self.accounting_date.text() != original_date)
        )

    def _remember_row_form(self):
        if self._in_multi:
            return
        current = self._current()
        if (
            self._completion_message
            and not self._reset_form_after_write
            and self._form_row_id is not None
            and (current is None or current.row_id != self._form_row_id)
        ):
            self._completion_message = ""
            self.operation_status.setText("Saved review loaded. Choose rows to review.")
            if self.embedded:
                self.operation_status.hide()
        if getattr(self, "_form_row_id", None) is not None:
            self._row_drafts[self._form_row_id] = (
                self._form_entry_key,
                self.purpose.currentData(),
                self.category.currentData(),
                self.accounting_date.text() if hasattr(self, "accounting_date") else None,
                self.reason.text(),
                self._form_dirty(),
            )

    def _restore_row_form(self, row):
        self._form_row_id = row.row_id if row else None
        self._form_entry_key = self._row_review_key(row)
        self._form_baseline = (
            "transfer" if self._pending_transfer(row) else row.purpose if row else None,
            row.category_id if row else None,
            (row.effective_date or self._posting_candidate(row) or "")
            if row and hasattr(self, "accounting_date")
            else None,
        )
        draft = self._row_drafts.get(self._form_row_id)
        # A previous row's text is never a reason for this new decision. Restore
        # only a draft authored against this exact active interpretation.
        self.reason.clear()
        if row is None or draft is None or draft[0] != self._row_review_key(row):
            if draft is not None:
                self._row_drafts.pop(self._form_row_id, None)
            return
        _entry, purpose, category, accounting_date, note, _dirty = draft
        self.reason.setText(note)
        index = self.purpose.findData(purpose)
        if index >= 0:
            self.purpose.setCurrentIndex(index)
        index = self.category.findData(category)
        if index >= 0:
            self.category.setCurrentIndex(index)
        if accounting_date is not None and hasattr(self, "accounting_date") and not self.register_mode:
            self.accounting_date.setText(accounting_date)

    def request_cancel(self):
        """Caller obtained any discard decision; never abandon a confirmed write."""
        return self.jobs.close()

    def _profile_matches(self):
        workspace = getattr(self, "workspace", None)
        return workspace is None or Path(workspace.profile_path).resolve() == self.jobs.profile

    def _capture_draft(self):
        row = self._current()
        return (
            row.row_id if row is not None else None,
            self.purpose.currentData(),
            self.category.currentData(),
            self.accounting_date.text() if hasattr(self, "accounting_date") else None,
            self.reason.text(),
        )

    def _queue_snapshot(self, selected_row_id=None):
        if not self._profile_matches():
            self.basis = None
            self.operation_status.setText("Profile changed. Open this document again before reviewing.")
            self._job_busy(False)
            return
        if self.jobs.writing:
            return
        captured = (*self._capture_draft(), self._form_entry_key)
        if self._reset_form_after_write:
            self._restore_draft = None
        elif captured[0] is not None or self._restore_draft is None:
            self._restore_draft = captured
        self._selected_after_read = selected_row_id or (
            self._restore_draft[0] if self._restore_draft is not None else captured[0]
        )
        source, kind = self.source_sha256, self.review_kind
        workspace = getattr(self, "workspace", None)
        preferences = workspace.preferences() if kind == "card" else None
        self.basis = None
        self.preview_source_button.setEnabled(False)
        self.operation_status.setText("Loading saved review… You can still search and inspect loaded rows.")
        self.operation_status.show()

        def read(store, cancelled):
            if cancelled():
                return None
            return store.source_interpretation_snapshot(source, kind=kind, preferences=preferences, cancelled=cancelled)

        self.jobs.submit(("snapshot", source, kind), read)

    def _job_busy(self, busy):
        self.cancel_read_button.setVisible(bool(busy and not self.jobs.writing))
        self.batch.setEnabled(not busy and self.basis is not None and self._profile_matches())
        if hasattr(self, "assumed_dates"):
            self.assumed_dates.setEnabled(not busy and not self.register_mode)
        if hasattr(self, "manage_categories_button"):
            self.manage_categories_button.setEnabled(
                not busy
                and self.basis is not None
                and self.purpose.currentData() not in {"repayment", "external_history"}
            )
        self._update_review_actions()
        if self.embedded:
            row = self._current()
            self.withdraw_button.setVisible(
                self._single_selection()
                and row is not None
                and (
                    row.entry_key is not None
                    or self._pending_transfer(row) is not None
                    or self._zero_review(row) is not None
                )
            )

    def _cancel_loading(self):
        if self.jobs.cancel_reads():
            self.basis = None
            self.operation_status.setText("Loading cancelled. Reload saved review to enable posting.")
            self.operation_status.show()
            self._job_busy(False)

    def _job_completed(self, key, result):
        if not self._profile_matches():
            self.basis = None
            self.operation_status.setText("Profile changed. This result was not displayed. Reopen the document.")
            return
        if key[0] == "snapshot":
            if result is None:
                return
            # Replacing the table temporarily clears selection and emits the
            # same signals as navigating away. Keep this operation's outcome
            # through that rebuild, until it has been displayed to the user.
            completion_message = self._completion_message
            self._snapshot = result
            self.pending_transfers = {state.row_id: state for state in result.pending_transfers}
            self.zero_reviews = {review.row_id: review for review in result.zero_reviews}
            self.transfer_eligible_row_ids = frozenset(result.transfer_eligible_row_ids)
            self.model.pending_transfers = self.pending_transfers
            self._apply_snapshot(result, self._selected_after_read)
            active_entries = {row.row_id: self._row_review_key(row) for row in result.rows}
            self._row_drafts = {
                row_id: draft
                for row_id, draft in self._row_drafts.items()
                if row_id in active_entries and draft[0] == active_entries[row_id]
            }
            self._reset_form_after_write = False
            if self._restore_multi is not None:
                ids, proposal, drafts = self._restore_multi
                self._restore_multi = None
                self._row_drafts = {
                    row_id: draft
                    for row_id, draft in drafts.items()
                    if row_id in active_entries and draft[0] == active_entries[row_id]
                }
                self._multi_form = proposal
                self._in_multi = False
                self._form_row_id = None
                self.navigation.select_ids(ids)
                self._selected()
                self._restore_draft = None
            draft, self._restore_draft = self._restore_draft, None
            if (
                draft
                and self._current() is not None
                and self._current().row_id == draft[0]
                and self._row_review_key(self._current()) == draft[5]
            ):
                _, purpose, category, accounting_date, reason, _entry = draft
                if self.purpose.findData(purpose) >= 0:
                    self.purpose.setCurrentIndex(self.purpose.findData(purpose))
                if self.category.findData(category) >= 0:
                    self.category.setCurrentIndex(self.category.findData(category))
                if accounting_date and hasattr(self, "accounting_date") and not self.register_mode:
                    self.accounting_date.setText(accounting_date)
                self.reason.setText(reason)
            self.operation_status.setText(completion_message or "Saved review loaded. Choose rows to review.")
            if self.embedded:
                self.operation_status.setVisible(bool(completion_message))
                self.review_intro.setVisible(
                    self.review_kind == "register"
                    or any(getattr(row, "tracking_scope", None) == "cash_component" for row in result.rows)
                )
                self.overlap_note.setVisible(bool(result.overlapping_source_ids))
            self._completion_message = ""
            self.batch.update_summary()
            self._update_form_cues()
            # A confirmed action may disappear or become disabled after its
            # replacement loads. Keep keyboard review usable without stealing
            # an existing focus or activating another window.
            if (
                completion_message
                and self.isVisible()
                and self.window().isActiveWindow()
                and QApplication.focusWidget() is None
            ):
                self.table.setFocus(Qt.OtherFocusReason)
        elif key[0] == "preview_batch":
            self.batch.show_preview(result)
            if not self.jobs.pending:
                self.operation_status.setText("Exact review closed; nothing posted. Review staged when ready.")
                self.batch.update_summary()
        elif key[0] == "preview_pending_correction":
            self.batch.show_preview(result, correction_row_id=key[1])
        elif key[0] == "evidence":
            from parsetrail.gui.v2_evidence_preview import V2EvidencePreview

            self.operation_status.setText("Saved source evidence loaded; this preview does not post entries.")
            self.operation_status.show()
            exec_disposable(V2EvidencePreview(result, self))
        elif key[0] == "write":
            consumed = set(self.batch.staged) if key[1] == "batch" else {self._selected_after_read}
            retain_current = any(row.row_id not in consumed for row in self.navigation.selected())
            self._row_drafts = {key: draft for key, draft in self._row_drafts.items() if key not in consumed}
            if not retain_current:
                self.reason.clear()
            if set(self._multi_form_ids) <= consumed:
                self._multi_form, self._multi_form_ids = (None, None, ""), ()
                self._in_multi = False
            else:
                self._multi_form_ids = tuple(row_id for row_id in self._multi_form_ids if row_id not in consumed)
            self._form_row_id = None
            self._reset_form_after_write = not retain_current
            self._restore_draft = None
            if key[1] == "batch":
                clear_shared = not retain_current and self.batch.reason.text().strip() == self.batch.note()
                self.batch.clear(clear_proposal=clear_shared)
            self._completion_message = (
                "These reviewed entries were already saved; no duplicate entries were posted."
                if key[1] == "batch" and getattr(result, "already_posted", False)
                else key[2]
            )
            self.changed.emit()
            if retain_current:
                self.refresh_preserving_draft()
            else:
                self.refresh(selected_row_id=self._selected_after_read)
            if len(key) > 3 and key[3] and not getattr(result, "already_posted", False):
                self.initial_posted.emit(self.source_sha256)

    def _job_failed(self, key, exc):
        self.operation_status.show()
        if key[0] == "snapshot":
            self._snapshot = None
            self.basis, self.entries, self.history, self.categories = None, {}, (), ()
            self.navigation.replace(())
            self._selected()
            self.preview_source_button.setEnabled(False)
            self.overlap_note.clear()
            self.operation_status.setText("Saved review unavailable. Reload to retry; your draft has been kept.")
            self.operation_status.setToolTip(str(exc))
        else:
            title = "Review was not saved" if key[0] == "write" else "Staged review unavailable"
            QMessageBox.warning(
                self,
                title,
                f"Saved facts may have changed. Reload and inspect the selected rows before trying again.\n\n{exc}",
            )
            self.operation_status.setText(
                "No new review result was displayed. Your staged choices are kept; reload to inspect current facts."
            )
            if key[0] == "write":
                self._completion_message = (
                    "Review attempt finished with an error. Inspect the refreshed saved state and retained "
                    "choices before confirming again."
                )
                self.refresh(selected_row_id=self._selected_after_read)

    def _submit_review_write(self, operation, *, message, row_id=None, batch=False, initial=False):
        if not self._profile_matches() or self.jobs.pending:
            QMessageBox.warning(
                self,
                "Review context changed",
                "Wait for loading, or reopen this document in its current profile before confirming.",
            )
            return
        self._selected_after_read = row_id
        preferences = self.review_preferences if self.review_kind == "card" else None
        preferences_path = self.workspace.preferences_path if preferences is not None else None

        def guarded(store, cancelled):
            if preferences_path is not None:
                from parsetrail.core.v2_preferences import load_preferences
                from parsetrail.core.v2_profile_store import ProfileFormatError

                if load_preferences(preferences_path) != preferences:
                    raise ProfileFormatError("review_preferences_changed")
            return operation(store, cancelled)

        self.basis = None
        self.operation_status.setText("Saving confirmed review… Please wait for the saved result.")
        self.operation_status.show()
        self.jobs.submit(("write", "batch" if batch else "single", message, initial), guarded, write=True)

    def _preview_evidence(self):
        if self.jobs.pending or self.basis is None or not self._profile_matches():
            return
        source = self.source_sha256
        self.operation_status.setText("Loading saved source evidence…")
        self.operation_status.show()
        self.jobs.submit(("evidence", source), lambda store, _cancelled: store.load_import(source))

    def _update_review_actions(self):
        if hasattr(self, "_update_action"):
            self._update_action()
        else:
            self._update_withdraw()
        if self.jobs.pending or not self._profile_matches():
            self.action_button.setEnabled(False)
            self.withdraw_button.setEnabled(False)

    def _allow_close(self):
        if self.jobs._closed:
            return True
        if self.jobs.writing:
            self.operation_status.setText("Saving confirmed review… Wait for its outcome before leaving.")
            return False
        if (
            self.has_unsaved_draft
            and QMessageBox.question(
                self,
                "Discard unapplied review?",
                "Discard the staged rows and unapplied review notes? Saved entries are retained.",
            )
            != QMessageBox.Yes
        ):
            return False
        return self.request_cancel()

    def reject(self):
        if not self.embedded:
            self.done(QDialog.Rejected)

    def done(self, result):
        if not self.embedded and self._allow_close():
            super().done(result)

    def closeEvent(self, event):
        if self._allow_close():
            super().closeEvent(event)
        else:
            event.ignore()

    def close(self):
        if self.jobs.writing:
            return False
        return super().close()

    def _open_reviewed_owner(self):
        if not self._single_selection():
            return
        row = self._current()
        if row is None or self._snapshot is None:
            return
        owner = next((owner for owner in getattr(self._snapshot, "owners", ()) if owner.row_id == row.row_id), None)
        workspace = getattr(self, "workspace", None)
        if owner is not None and owner.owner_kind == "resolution" and workspace is not None:
            self.transfers_requested.emit(row.row_id)
            return
        if owner is None or workspace is None or owner.owner_kind not in {"loan", "settlement", "transfer"}:
            QMessageBox.information(
                self,
                "Reviewed elsewhere",
                "This row already has an active interpretation. Open its reviewed entry or transfer/payment history; no ordinary category posting is needed.",
            )
            return
        if owner.owner_kind == "loan":
            from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview

            dialog = V2LoanPaymentReview(workspace, self, event_id=owner.event_id)
            dialog.transfers_requested.connect(self.transfers_requested)
            exec_disposable(dialog)
        elif owner.owner_kind == "settlement":
            from parsetrail.gui.v2_settlement_review import V2SettlementReview

            V2SettlementReview(workspace, event_id=owner.event_id, parent=self).exec()
        elif owner.owner_kind == "transfer":
            from parsetrail.gui.v2_transfer_review import V2TransferReview

            V2TransferReview(workspace, self, focus_row_id=row.row_id).exec()
        self.refresh(selected_row_id=row.row_id)


class OrdinaryBatchPanel(QGroupBox):
    """Stage authored choices, then ask the headless service for an exact preview."""

    def __init__(self, review):
        super().__init__(review)
        self._review_ref = ref(review)
        self.staged = {}
        self._staged_reason = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(2)
        self.reason_label = QLabel("Shared reason for all rows in this review *")
        self.reason = QLineEdit(self)
        self.reason.setMaxLength(500)
        self.reason.setText(INITIAL_REVIEW_REASON)
        self.reason.setAccessibleName(self.reason_label.text())
        self.reason.setPlaceholderText("Why you are accepting these transactions")
        self.reason_label.setBuddy(self.reason)
        reason_row = QHBoxLayout()
        reason_row.addWidget(self.reason_label)
        reason_row.addWidget(self.reason, 1)
        layout.addLayout(reason_row)
        controls = QHBoxLayout()
        self.stage_button = QPushButton("Stage selected rows")
        self.stage_button.clicked.connect(self.stage_selected)
        self.preview_button = QPushButton("Review staged…")
        self.preview_button.clicked.connect(self.preview)
        self.clear_button = QPushButton("Clear staged", self)
        self.clear_button.clicked.connect(self.clear_from_ui)
        self.remove_button = QPushButton("Remove selected", self)
        self.remove_button.setToolTip(
            "Remove selected rows from the staged set; other staged choices and saved entries are kept."
        )
        self.remove_button.clicked.connect(self.remove_selected)
        controls.addWidget(self.stage_button)
        controls.addWidget(self.preview_button)
        self.options_button = QPushButton("Review set options…")
        self.options_menu = QMenu(self.options_button)
        self.options_button.setMenu(self.options_menu)
        self.remove_action = self.options_menu.addAction("Remove selected from review set", self.remove_button.click)
        self.clear_action = self.options_menu.addAction("Clear review set", self.clear_button.click)
        self.remove_button.hide()
        self.clear_button.hide()
        controls.addWidget(self.options_button)
        layout.addLayout(controls)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.reason_scope = self.summary
        self.stage_button.setText("Stage selected")
        self.stage_button.setToolTip(
            "Capture the selected purpose, category and date. Staging replaces only selected proposals, and applies this note to ALL staged rows. Nothing posts until exact confirmation."
        )
        layout.addWidget(self.summary)
        self.reason.textChanged.connect(self.update_summary)
        review.navigation.proxy.rowsRemoved.connect(self.update_summary)
        review.navigation.proxy.rowsInserted.connect(self.update_summary)
        review.navigation.scope_changed.connect(self.update_summary)
        self.update_summary()

    @property
    def review(self):
        # The review owns this panel in Qt and Python; keep the back-reference
        # weak while returning the actual QObject for Qt API arguments.
        review = self._review_ref()
        if review is None:
            raise ReferenceError("The owning review has been released")
        return review

    @property
    def reason_is_dirty(self):
        return self.reason.text() != INITIAL_REVIEW_REASON

    def clear(self, *, clear_proposal=True):
        self.staged.clear()
        self._staged_reason = ""
        if clear_proposal:
            self.reason.setText(INITIAL_REVIEW_REASON)
        self.update_summary()

    def clear_from_ui(self):
        self.clear(clear_proposal=False)
        self.review._update_review_actions()

    def remove_selected(self):
        if self.review.jobs.pending:
            return
        for row in self.review.navigation.selected():
            self.staged.pop(row.row_id, None)
        if not self.staged:
            self._staged_reason = ""
        self.update_summary()
        self.review._update_review_actions()

    def selection_changed(self, rows):
        proposed, refused = self.propose(rows, self.review.purpose.currentData(), self.review.category.currentData())
        return bool(
            refused
            or any(self.staged.get(row.row_id) != proposed.get(row.row_id) for row in rows)
            or self.reason.text().strip() != self._staged_reason
        )

    def _present_staged_rows(self):
        from parsetrail.gui.v2_cash_activity_review import PURPOSE_LABELS, _category_labels

        review = self.review
        labels = _category_labels(review.categories)
        details, changed = {}, set()
        selected = review.navigation.selected()
        for row in review.model.rows:
            proposal = self.staged.get(row.row_id)
            if proposal is None:
                continue
            details[row.row_id] = (
                "Staged locally; not saved.\n"
                f"Purpose: {PURPOSE_LABELS.get(getattr(proposal, 'purpose', 'transfer'), 'Transfer / card repayment')}\n"
                f"Category: {labels.get(getattr(proposal, 'category_id', None), 'Not applicable')}\n"
                f"Accounting date: {getattr(proposal, 'accounting_date', None) or getattr(row, 'posting_candidate', None) or getattr(row, 'posting_date', None) or getattr(row, 'date', None) or 'Unknown'}\n"
                f"Shared staged note: {self.note()}\nCurrent source status: {row.status}"
            )
            draft = review._row_drafts.get(row.row_id)
            if draft is not None:
                expected_date = (
                    str(proposal.accounting_date)
                    if getattr(proposal, "accounting_date", None)
                    else getattr(row, "posting_candidate", None)
                )
                if (draft[1], draft[2]) != (
                    getattr(proposal, "purpose", "transfer"),
                    getattr(proposal, "category_id", None),
                ) or (review.review_kind == "card" and draft[3] != expected_date):
                    changed.add(row.row_id)
        changed.difference_update(row.row_id for row in selected)
        if selected and self.selection_changed(selected):
            changed.update(row.row_id for row in selected if row.row_id in self.staged)
        review.model.set_staged(self.staged, details, changed)

    def note(self):
        return self._staged_reason if self.staged else self.reason.text().strip()

    def update_summary(self, *_args):
        self._present_staged_rows()
        visible = {
            row.row_id
            for i, row in enumerate(self.review.model.rows)
            if self.review.navigation.proxy.mapFromSource(self.review.model.index(i, 0)).isValid()
        }
        hidden = sum(row_id not in visible for row_id in self.staged)
        count = len(self.staged)
        self.preview_button.setEnabled(bool(count and self.note()))
        self.clear_button.setEnabled(bool(count))
        self.remove_button.setEnabled(
            bool(
                not self.review.jobs.pending
                and any(row.row_id in self.staged for row in self.review.navigation.selected())
            )
        )
        set_field_state(self.preview_button, "ready" if self.preview_button.isEnabled() else "neutral")
        set_field_state(
            self.reason,
            "loading"
            if self.review.jobs.pending
            else "blocked"
            if self.review.basis is None
            else "ready"
            if self.reason.text().strip()
            else "required"
            if self.staged
            or any(
                row.entry_key is None
                and row.status in {"Ready for purpose review", "Enable assumed dates or enter a corrected date"}
                for row in self.review.navigation.selected()
            )
            else "optional",
        )
        self.setTitle(f"Review set — {count} row{'s' if count != 1 else ''} · not posted")
        self.remove_action.setEnabled(self.remove_button.isEnabled())
        self.clear_action.setEnabled(self.clear_button.isEnabled())
        self.options_button.setVisible(bool(count))
        self.update_stage_action()
        if count:
            text = f"ALL {count} staged rows included · {hidden} hidden by filters."
            changed_reason = self.reason.text().strip() != self._staged_reason
            self.summary.setText(text + (" Reason changed — stage to apply it to ALL rows." if changed_reason else ""))
            self.summary.setToolTip(text + "\nShared staged note: " + self.note())
        else:
            self.summary.setText("Stage captures this reason for ALL staged rows, including hidden rows.")

    def update_stage_action(self):
        review = self.review
        rows = review.navigation.selected()
        purpose, category = review.purpose.currentData(), review.category.currentData()
        note = self.reason.text()
        proposed, blockers = self.propose(rows, purpose, category)
        all_staged = bool(rows) and all(row.row_id in self.staged for row in rows)
        changed = any(self.staged.get(row.row_id) != proposed.get(row.row_id) for row in rows)
        changed = changed or self.reason.text().strip() != self._staged_reason
        eligible = bool(
            rows
            and not review.jobs.pending
            and review.basis is not None
            and review._profile_matches()
            and purpose in {"expense", "expense_refund", "income", "income_adjustment", "transfer"}
            and (category is not None or purpose == "transfer")
            and note.strip()
            and not blockers
            and changed
        )
        self.stage_button.setText("Update staged" if all_staged else "Stage selected")
        self.stage_button.setEnabled(eligible)
        set_field_state(self.stage_button, "ready" if eligible else "neutral")
        self.remove_button.setEnabled(bool(not review.jobs.pending and any(row.row_id in self.staged for row in rows)))
        self._present_staged_rows()

    def stage_selected(self):
        review = self.review
        if review.jobs.pending or review.basis is None or not review._profile_matches():
            self.summary.setText(
                "Reload saved review and wait for loading before staging. Existing staged choices are kept."
            )
            return
        rows = review.navigation.selected()
        if len(rows) > 1 and not review._in_multi:
            review._handle_multi_selection()
            self.summary.setText("Choose a common purpose, category and review note for all selected rows first.")
            return
        purpose, category = review.purpose.currentData(), review.category.currentData()
        proposed, refused = self.propose(rows, purpose, category)
        if refused:
            self.summary.setText(
                f"None of {len(rows)} selected rows staged; {len(self.staged)} prior staged rows kept."
            )
            QMessageBox.information(
                review, "Selected rows were not staged", "No selected choices were changed.\n" + "\n".join(refused)
            )
            return
        if (
            not rows
            or purpose not in {"expense", "expense_refund", "income", "income_adjustment", "transfer"}
            or (category is None and purpose != "transfer")
            or not self.reason.text().strip()
        ):
            self.summary.setText("Select rows and explicitly choose a purpose, category and shared review note first.")
            return
        staged_note = self.reason.text().strip()
        self.staged.update(proposed)
        self._staged_reason = staged_note
        # A successfully captured proposal becomes the staged row's editing
        # baseline. Pre-stage single-row drafts must not reappear as later edits
        # after a common selection is filtered out and restored.
        for row in review.model.rows:
            selection = proposed.get(row.row_id)
            if selection is not None:
                accounting_date = (
                    str(selection.accounting_date)
                    if getattr(selection, "accounting_date", None) is not None
                    else (row.effective_date or review._posting_candidate(row) or "")
                    if hasattr(review, "accounting_date")
                    else None
                )
                review._row_drafts[row.row_id] = (
                    row.entry_key,
                    getattr(selection, "purpose", "transfer"),
                    getattr(selection, "category_id", None),
                    accounting_date,
                    "",
                    True,
                )
        self.update_summary()
        review._update_review_actions()

    def propose(self, rows, purpose, category):
        """Pure draft preflight shared by readiness and staging; no mutation."""
        from parsetrail.core.v2_ordinary_batch import OrdinaryCategorySelection, OrdinaryTransferSelection

        review = self.review
        refused, proposed = [], {}
        if len(set(self.staged) | {row.row_id for row in rows}) > 2000:
            return {}, ["A staged set supports at most 2,000 rows. Reduce the selection or clear prior staged rows."]
        for row in rows:
            if review._pending_transfer(row) is not None:
                refused.append(
                    f"{row.description or 'Source row'}: change this saved transfer designation individually with a new reason."
                )
                continue
            if purpose == "transfer":
                date_issue = review._transfer_date_issue(row, multiple=len(rows) > 1)
                if date_issue:
                    refused.append(f"{row.description or 'Source row'}: {date_issue}")
                    continue
                if (
                    row.row_id not in review.transfer_eligible_row_ids
                    or row.entry_key is not None
                    or reviewed_elsewhere(row)
                ):
                    refused.append(
                        f"{row.description or 'Source row'}: transfer designation prerequisites are not satisfied."
                    )
                    continue
                prior = review.pending_transfers.get(row.row_id)
                proposed[row.row_id] = OrdinaryTransferSelection(
                    row.row_id, prior.revision_id if prior is not None else None
                )
                continue
            ready = row.status == "Ready for purpose review"
            accounting_date = None
            if review.review_kind == "card" and row.amount_minor != 0:
                candidate = row.posting_candidate
                edited = review.accounting_date.text().strip()
                if len(rows) == 1:
                    try:
                        parsed = date.fromisoformat(edited)
                        if parsed.isoformat() != edited:
                            raise ValueError
                    except ValueError:
                        refused.append("Enter a nonblank accounting date as YYYY-MM-DD before staging.")
                        continue
                    if edited != candidate:
                        accounting_date = parsed
                        ready = ready or row.status == "Enable assumed dates or enter a corrected date"
                elif len(rows) > 1:
                    previous = self.staged.get(row.row_id)
                    draft = review._row_drafts.get(row.row_id)
                    if (
                        previous is not None
                        and draft is not None
                        and draft[3]
                        and draft[3] not in {candidate, str(previous.accounting_date)}
                    ):
                        refused.append("A date override has changed since staging. Stage that row individually first.")
                        continue
                    if previous is not None and previous.accounting_date is not None:
                        accounting_date = previous.accounting_date
                        ready = ready or row.status == "Enable assumed dates or enter a corrected date"
                    elif draft is not None and draft[3] and draft[3] != candidate:
                        refused.append("Stage date overrides individually first. No selected rows were newly staged.")
                        continue
            if not ready or row.entry_key is not None or reviewed_elsewhere(row):
                refused.append(f"{row.description or 'Source row'}: review individually; {row.status}")
                continue
            if purpose is not None and purpose not in row.allowed_purposes:
                refused.append(f"{row.description or 'Source row'}: selected purpose does not apply")
                continue
            proposed[row.row_id] = OrdinaryCategorySelection(row.row_id, category, purpose, accounting_date)
        return proposed, refused

    def preview(self):
        review = self.review
        if (
            review.jobs.pending
            or review.basis is None
            or not review._profile_matches()
            or not self.staged
            or not self.note()
        ):
            return
        source, kind, selections, reason, basis = (
            review.source_sha256,
            review.review_kind,
            tuple(self.staged.values()),
            self.note(),
            review.basis,
        )
        preferences = review.review_preferences if kind == "card" else None

        def prepare(store, cancelled):
            return store.preview_reviewed_ordinary_batch(
                source,
                kind=kind,
                selections=selections,
                reason=reason,
                expected_basis_sha256=basis,
                preferences=preferences,
                cancelled=cancelled,
            )

        review.operation_status.setText("Preparing exact staged review…")
        review.operation_status.show()
        review.jobs.submit(("preview_batch", source, kind), prepare)

    def show_preview(self, preview, *, correction_row_id=None):
        from parsetrail.core.v2_ordinary_batch import OrdinaryCategorySelection, OrdinaryTransferSelection
        from parsetrail.gui.v2_cash_activity_review import PURPOSE_LABELS, _category_labels, _money, _purpose_effects

        review = self.review
        if not review._profile_matches():
            return
        rows = {row.row_id: row for row in review.model.rows}
        categories = _category_labels(review.categories)
        dialog = QDialog(review)
        dialog.setWindowTitle("Confirm staged review")
        dialog.resize(850, 600)
        layout = QVBoxLayout(dialog)
        count = len(preview.selections)
        transfer_count = len(preview.transfer_entries)
        zero_count = len(preview.zero_reviews)
        entry_count = len(preview.entries) + transfer_count
        title = QLabel(
            f"Post {entry_count} financial transaction{'s' if entry_count != 1 else ''} and review {zero_count} zero-value row{'s' if zero_count != 1 else ''}?"
            if entry_count and zero_count
            else f"Review {zero_count} zero-value row{'s' if zero_count != 1 else ''} without posting money?"
            if zero_count
            else f"Post {entry_count} reviewed transaction{'s together' if entry_count != 1 else ''}?"
        )
        title.setWordWrap(True)
        layout.addWidget(title)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        text, posting_details = [], []
        category_selections = tuple(
            item
            for item in preview.selections
            if isinstance(item, OrdinaryCategorySelection) and rows[item.row_id].amount_minor != 0
        )
        entries = dict(zip((item.row_id for item in category_selections), preview.entries, strict=True))
        transfer_entries = dict(
            zip(
                (item.row_id for item in preview.selections if isinstance(item, OrdinaryTransferSelection)),
                preview.transfer_entries,
                strict=True,
            )
        )
        zero_reviews = {item.row_id: item for item in preview.zero_reviews}
        transfer_drafts = {item.row_id: item for item in preview.pending_transfers}
        for selection in preview.selections:
            row = rows[selection.row_id]
            if isinstance(selection, OrdinaryTransferSelection):
                draft = transfer_drafts[selection.row_id]
                text.append(
                    f"{row.description or 'Description not printed'} · {_money(row.amount_minor)}\n"
                    f"{row.financial_account or 'Not assigned'} · Transfer / card repayment\n"
                    "Post this source side against transfer clearing. The counterpart remains unresolved. "
                    "No income or spending is created; resolve the relationship separately in Transfers."
                )
                posting_details.append(
                    f"{row.description or 'Description not printed'}\nSource: {draft.movement.source_sha256}\n"
                    f"Source row: {draft.row_id}; source posting candidate: {draft.movement.posting_date} "
                    f"({draft.movement.date_provenance}).\n"
                    + "\n".join(
                        f"{posting.account_id}: {_money(posting.amount_minor)} debit signed"
                        for posting in transfer_entries[selection.row_id].postings
                    )
                )
                continue
            if selection.row_id in zero_reviews:
                text.append(
                    f"{row.description or 'Description not printed'} · $0.00\n"
                    f"{row.financial_account or 'Not assigned'} · {PURPOSE_LABELS[selection.purpose]} / {categories.get(selection.category_id, selection.category_id)}\n"
                    "Save the reviewed classification only. No journal entry, money movement or budget spending is created."
                )
                posting_details.append(
                    f"Source row: {selection.row_id}\nOriginal date/provenance retained. Zero-value review creates no posting."
                )
                continue
            entry = entries[selection.row_id]
            source_date = (
                getattr(row, "source_date", None)
                or getattr(row, "date", None)
                or str(getattr(row, "transaction_date", None) or "Unknown")
            )
            provenance = (
                getattr(row, "date_provenance", None) or getattr(row, "posting_date_provenance", None) or "unknown"
            )
            posting_candidate = (
                getattr(row, "posting_date", None)
                or getattr(row, "posting_candidate", None)
                or getattr(row, "date", None)
                or "Unknown"
            )
            qualification = (
                "\nOnly this cash component is reviewed; the whole HSA and investment portfolio remain outside this review."
                if getattr(row, "tracking_scope", None) == "cash_component"
                else ""
            )
            if not getattr(row, "source_description_known", True):
                qualification += (
                    "\nSource description unavailable / unknown. "
                    f"Code-owned accounting label only: {getattr(row, 'accounting_description', 'Unavailable')}. "
                    "This does not supply missing printed source text; no interest, contribution or investment purpose is inferred."
                )
            if review.review_kind == "register":
                qualification += (
                    "\nWhole liability effect only; principal/interest breakdown is unavailable and is not inferred."
                )
            if selection.pending_transfer_revision_id is not None:
                qualification += "\nThis replaces the saved transfer designation with the category posting shown above."
            date_detail = (
                f"\nSource date: {source_date}; posting candidate: {posting_candidate} ({provenance}); "
                f"accounting date: {entry.posting_date} ({'explicit override' if selection.accounting_date else provenance})."
            )
            date_qualification = (
                date_detail
                if str(source_date) != str(entry.posting_date)
                or provenance in {"assumed", "unknown"}
                or selection.accounting_date is not None
                else ""
            )
            text.append(
                f"{row.description or 'Description not printed'} · {_money(row.amount_minor)}\n"
                f"{row.financial_account or 'Not assigned'} · {entry.posting_date} · "
                f"{PURPOSE_LABELS[selection.purpose]} / {categories.get(selection.category_id, selection.category_id)}\n"
                + _purpose_effects(
                    selection.purpose,
                    row.amount_minor,
                    financial_kind="asset" if review.review_kind == "cash" else "liability",
                )
                + date_qualification
                + qualification
            )
            posting_details.append(
                f"{row.description or 'Description not printed'}\n"
                f"Account: {row.financial_account or 'Not assigned'}; scope: {getattr(row, 'tracking_scope', None) or 'account total'}"
                + date_detail
                + "\n"
                + "\n".join(
                    f"{posting.account_id}: {_money(posting.amount_minor)} debit signed" for posting in entry.postings
                )
            )
        details.setAccessibleName("Transactions and exact financial effects")
        details.setPlainText(
            (
                f"Reason for correction: {preview.reason}\n\n"
                if correction_row_id is not None
                else f"Shared reason for all {count} row{'s' if count != 1 else ''}: {preview.reason}\n\n"
            )
            + "\n\n".join(text)
        )
        layout.addWidget(details, 1)
        show_postings = QCheckBox("Show source and exact posting details")
        posting_text = QPlainTextEdit("\n\n".join(posting_details))
        posting_text.setReadOnly(True)
        posting_text.setAccessibleName("Exact ledger posting detail")
        posting_text.hide()
        show_postings.toggled.connect(posting_text.setVisible)
        layout.addWidget(show_postings)
        layout.addWidget(posting_text)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        confirm = buttons.addButton(
            f"Confirm and save {count} choice{'s' if count != 1 else ''}"
            if transfer_count or zero_count
            else f"Confirm and post {entry_count} entr{'ies' if entry_count != 1 else 'y'}",
            QDialogButtonBox.AcceptRole,
        )
        set_field_state(confirm, "ready")
        confirm.clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        try:
            decision = dialog.exec()
        finally:
            # This transient exact preview is no longer needed after dismissal.
            # Dispose its Qt-owned hierarchy on the GUI thread rather than
            # leaving parent/slot cycles for a later Python collection.
            dialog.deleteLater()
        if decision != QDialog.Accepted:
            return
        correction_matches = (
            (
                review._current() is not None
                and review._current().row_id == correction_row_id
                and review.reason.text().strip() == preview.reason
                and review.purpose.currentData() == preview.selections[0].purpose
                and review.category.currentData() == preview.selections[0].category_id
            )
            if correction_row_id is not None
            else True
        )
        if (
            correction_row_id is None
            and (tuple(self.staged.values()) != preview.selections or self.note() != preview.reason)
        ) or not correction_matches:
            QMessageBox.warning(
                review,
                "Staged choices changed",
                "Review the updated staged choices in a new exact preview before posting.",
            )
            return
        if not review._profile_matches():
            QMessageBox.warning(
                review, "Profile changed", "The preview belongs to another profile. Nothing was posted."
            )
            return

        def post(store, cancelled):
            return store.post_reviewed_ordinary_batch(preview, cancelled=cancelled)

        review._submit_review_write(
            post,
            message=(
                f"Posted {entry_count} financial transaction{'s' if entry_count != 1 else ''}; reviewed {zero_count} zero-value row{'s' if zero_count != 1 else ''}. "
                + (
                    f"{transfer_count} transfer side{'s' if transfer_count != 1 else ''} await resolution in Transfers. "
                    if transfer_count
                    else ""
                )
                + ("Zero-value reviews post no money. " if zero_count else "")
                + ("Open Budget to see category impact." if entry_count > transfer_count else "")
            ),
            batch=correction_row_id is None,
            row_id=correction_row_id,
            initial=(
                correction_row_id is None
                and all(
                    review._row_review_key(row) is None and not reviewed_elsewhere(row)
                    for row in review.model.rows
                    if row.row_id in {selection.row_id for selection in preview.selections}
                )
            ),
        )

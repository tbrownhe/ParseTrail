"""Shared asynchronous lifecycle and explicit staging for ordinary source review."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from parsetrail.gui.v2_profile_jobs import ProfileJobs
from parsetrail.gui.v2_review_navigation import reviewed_elsewhere


class OrdinaryReviewMixin:
    """The GUI captures scope; services own eligibility, money and transactions."""

    def _setup_jobs(self, profile, *, embedded=False):
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.Widget)
        self._snapshot = None
        self._restore_draft = None
        self._completion_message = ""
        self._selected_after_read = None
        self._row_drafts = {}
        self._form_row_id = None
        self._form_entry_key = None
        self._form_baseline = (None, None, None)
        self._reset_form_after_write = False
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
        self.layout().insertWidget(self.layout().count() - 1, self.batch)
        self.evidence_details_button = QPushButton("Source and interpretation details")
        self.evidence_details_button.setCheckable(True)
        self.evidence_details_button.toggled.connect(self.source_context.setVisible)
        self.evidence_details_button.toggled.connect(self.history_details.setVisible)
        self.source_context.hide()
        self.history_details.hide()
        self.layout().insertWidget(self.layout().indexOf(self.source_context), self.evidence_details_button)
        if embedded:
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.layout().setSpacing(4)
            self.review_intro.hide()
            self.overlap_note.hide()
            self.layout().removeWidget(self.cancel_read_button)
            self.navigation.layout().addWidget(self.cancel_read_button)
            self.layout().removeWidget(self.batch)
            self.actions_layout.addWidget(self.batch, 1)
            self.reason.setPlaceholderText("Review reason; Stage selected applies this reason to every staged row")
            for button_box in self.findChildren(QDialogButtonBox):
                button = button_box.button(QDialogButtonBox.Close)
                if button is not None:
                    button.hide()
                self.layout().removeWidget(self.review_limits_button)
                self.layout().removeWidget(self.evidence_details_button)
                self.layout().removeWidget(self.preview_source_button)
                self.review_limits_button.setText("Rules and limits")
                self.evidence_details_button.setText("Details")
                self.preview_source_button.setText("Source evidence")
                button_box.addButton(self.review_limits_button, QDialogButtonBox.ActionRole)
                button_box.addButton(self.evidence_details_button, QDialogButtonBox.ActionRole)
                button_box.addButton(self.preview_source_button, QDialogButtonBox.ActionRole)
                for action_button in button_box.buttons():
                    if action_button.text() == "Reload saved review":
                        action_button.setText("Reload")

    @property
    def review_pending(self):
        return self.jobs.pending

    @property
    def has_unsaved_draft(self):
        return bool(
            self.batch.staged
            or self.reason.text().strip()
            or self.batch.reason.text().strip()
            or self._form_dirty()
            or any(draft[-1] for draft in self._row_drafts.values())
        )

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
        if getattr(self, "_form_row_id", None) is not None:
            self._row_drafts[self._form_row_id] = (
                self._form_entry_key,
                self.purpose.currentData(),
                self.category.currentData(),
                self.accounting_date.text() if hasattr(self, "accounting_date") else None,
                self._form_dirty(),
            )

    def _restore_row_form(self, row):
        self._form_row_id = row.row_id if row else None
        self._form_entry_key = row.entry_key if row else None
        self._form_baseline = (
            row.purpose if row else None,
            row.category_id if row else None,
            (row.effective_date or self._posting_candidate(row) or "")
            if row and hasattr(self, "accounting_date")
            else None,
        )
        draft = self._row_drafts.get(self._form_row_id)
        if row is None or draft is None or draft[0] != row.entry_key or not draft[-1]:
            return
        _entry, purpose, category, accounting_date, _dirty = draft
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
        captured = self._capture_draft()
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
            self.withdraw_button.setVisible(row is not None and row.entry_key is not None)

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
            self._snapshot = result
            self._apply_snapshot(result, self._selected_after_read)
            self._reset_form_after_write = False
            draft, self._restore_draft = self._restore_draft, None
            if draft and self._current() is not None and self._current().row_id == draft[0]:
                _, purpose, category, accounting_date, reason = draft
                if self.purpose.findData(purpose) >= 0:
                    self.purpose.setCurrentIndex(self.purpose.findData(purpose))
                if self.category.findData(category) >= 0:
                    self.category.setCurrentIndex(self.category.findData(category))
                if accounting_date and hasattr(self, "accounting_date") and not self.register_mode:
                    self.accounting_date.setText(accounting_date)
                self.reason.setText(reason)
            self.operation_status.setText(self._completion_message or "Saved review loaded. Choose rows to review.")
            if self.embedded:
                self.operation_status.setVisible(bool(self._completion_message))
                self.review_intro.setVisible(
                    self.review_kind == "register"
                    or any(getattr(row, "tracking_scope", None) == "cash_component" for row in result.rows)
                )
                self.overlap_note.setVisible(bool(result.overlapping_source_ids))
            self._completion_message = ""
            self.batch.update_summary()
        elif key[0] == "preview_batch":
            self.batch.show_preview(result)
        elif key[0] == "evidence":
            from parsetrail.gui.v2_evidence_preview import V2EvidencePreview

            self.operation_status.setText("Saved source evidence loaded; this preview does not post entries.")
            self.operation_status.show()
            V2EvidencePreview(result, self).exec()
        elif key[0] == "write":
            self.reason.clear()
            self._row_drafts.clear()
            self._form_row_id = None
            self._reset_form_after_write = True
            self._restore_draft = None
            if key[1] == "batch":
                self.batch.clear()
            self._completion_message = (
                "These reviewed entries were already saved; no duplicate entries were posted."
                if key[1] == "batch" and getattr(result, "already_posted", False)
                else key[2]
            )
            self.changed.emit()
            self.refresh(selected_row_id=self._selected_after_read)

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
            title = "Review was not saved" if key[0] == "write" else "Batch preview unavailable"
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

    def _submit_review_write(self, operation, *, message, row_id=None, batch=False):
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
        self.jobs.submit(("write", "batch" if batch else "single", message), guarded, write=True)

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
        row = self._current()
        if row is None or self._snapshot is None:
            return
        owner = next((owner for owner in getattr(self._snapshot, "owners", ()) if owner.row_id == row.row_id), None)
        workspace = getattr(self, "workspace", None)
        if owner is None or workspace is None or owner.owner_kind not in {"loan", "settlement", "transfer"}:
            QMessageBox.information(
                self,
                "Reviewed elsewhere",
                "This row already has an active interpretation. Open its reviewed entry or transfer/payment history; no ordinary category posting is needed.",
            )
            return
        if owner.owner_kind == "loan":
            from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview

            V2LoanPaymentReview(workspace, self, event_id=owner.event_id).exec()
        elif owner.owner_kind == "settlement":
            from parsetrail.gui.v2_settlement_review import V2SettlementReview

            V2SettlementReview(workspace, event_id=owner.event_id, parent=self).exec()
        elif owner.owner_kind == "transfer":
            from parsetrail.gui.v2_transfer_review import V2TransferReview

            V2TransferReview(workspace, self, focus_row_id=row.row_id).exec()
        self.refresh(selected_row_id=row.row_id)


class OrdinaryBatchPanel(QWidget):
    """Stage authored choices, then ask the headless service for an exact preview."""

    def __init__(self, review):
        super().__init__(review)
        self.review = review
        self.staged = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        self.reason.setPlaceholderText("Explicit batch reason — applies to every staged row")
        self.reason.setAccessibleName("Shared reason for every staged row")
        self.stage_button = QPushButton("Stage selected rows")
        self.stage_button.clicked.connect(self.stage_selected)
        self.preview_button = QPushButton("Review batch…")
        self.preview_button.clicked.connect(self.preview)
        self.clear_button = QPushButton("Clear staged")
        self.clear_button.clicked.connect(self.clear)
        if review.embedded:
            self.reason.deleteLater()
            self.reason = review.reason
        else:
            controls.addWidget(self.reason, 1)
        controls.addWidget(self.stage_button)
        controls.addWidget(self.preview_button)
        controls.addWidget(self.clear_button)
        layout.addLayout(controls)
        self.summary = QLabel("No rows staged. Select rows, choose purpose/category, and enter a batch reason.")
        self.summary.setWordWrap(True)
        if review.embedded:
            self.stage_button.setText("Stage selected")
            self.stage_button.setToolTip(
                "Apply the explicitly chosen purpose, category and review reason to the selected eligible rows. The reason applies to every staged row."
            )
            controls.insertWidget(0, self.summary)
        else:
            layout.addWidget(self.summary)
        self.reason.textChanged.connect(self.update_summary)
        review.navigation.proxy.rowsRemoved.connect(self.update_summary)
        review.navigation.proxy.rowsInserted.connect(self.update_summary)
        review.navigation.scope_changed.connect(self.update_summary)
        self.update_summary()

    def clear(self):
        self.staged.clear()
        self.reason.clear()
        self.update_summary()

    def update_summary(self, *_args):
        visible = {
            row.row_id
            for i, row in enumerate(self.review.model.rows)
            if self.review.navigation.proxy.mapFromSource(self.review.model.index(i, 0)).isValid()
        }
        hidden = sum(row_id not in visible for row_id in self.staged)
        count = len(self.staged)
        self.preview_button.setEnabled(bool(count and self.reason.text().strip()))
        self.clear_button.setEnabled(bool(count))
        if count:
            text = f"{count} staged row(s); {hidden} hidden by the current filter. Batch reason applies to every staged row. Corrections are reviewed individually."
            self.summary.setText(f"{count} staged · {hidden} hidden" if self.review.embedded else text)
            self.summary.setToolTip(text)
        else:
            self.summary.setText(
                "0 staged"
                if self.review.embedded
                else "No rows staged. Select rows, choose purpose/category, and enter a batch reason."
            )

    def stage_selected(self):
        from datetime import date

        from parsetrail.core.v2_ordinary_batch import OrdinaryCategorySelection

        review = self.review
        rows = review.navigation.selected()
        purpose, category = review.purpose.currentData(), review.category.currentData()
        if (
            not rows
            or purpose not in {"expense", "expense_refund", "income", "income_adjustment"}
            or category is None
            or not self.reason.text().strip()
        ):
            self.summary.setText("Select rows and explicitly choose a purpose, category and shared batch reason first.")
            return
        refused = []
        for row in rows:
            ready = row.status == "Ready for purpose review"
            accounting_date = None
            if review.review_kind == "card":
                candidate = row.posting_candidate
                edited = review.accounting_date.text().strip()
                if len(rows) == 1 and edited and edited != candidate:
                    try:
                        accounting_date = date.fromisoformat(edited)
                    except ValueError:
                        refused.append("Enter a valid accounting date before staging.")
                        continue
                    ready = ready or row.status == "Enable assumed dates or enter a corrected date"
                elif len(rows) > 1 and review._current() is not None and edited != review._current().posting_candidate:
                    refused.append(
                        "Stage date overrides individually. Multi-row staging retains each row's own posting candidate."
                    )
                    continue
            if not ready or row.entry_key is not None or reviewed_elsewhere(row) or purpose not in row.allowed_purposes:
                refused.append(f"{row.description or 'Source row'}: {row.status}")
                continue
            self.staged[row.row_id] = OrdinaryCategorySelection(row.row_id, category, purpose, accounting_date)
        self.update_summary()
        if refused:
            QMessageBox.information(review, "Some selected rows were not staged", "\n".join(refused))

    def preview(self):
        review = self.review
        if review.jobs.pending or review.basis is None or not self.staged or not self.reason.text().strip():
            return
        source, kind, selections, reason, basis = (
            review.source_sha256,
            review.review_kind,
            tuple(self.staged.values()),
            self.reason.text().strip(),
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

        review.operation_status.setText("Preparing exact batch preview…")
        review.operation_status.show()
        review.jobs.submit(("preview_batch", source, kind), prepare)

    def show_preview(self, preview):
        from parsetrail.gui.v2_cash_activity_review import PURPOSE_LABELS, _category_labels, _money, _purpose_effects

        review = self.review
        if not review._profile_matches():
            return
        rows = {row.row_id: row for row in review.model.rows}
        categories = _category_labels(review.categories)
        dialog = QDialog(review)
        dialog.setWindowTitle("Confirm staged ordinary review")
        dialog.resize(850, 600)
        layout = QVBoxLayout(dialog)
        title = QLabel(
            f"{len(preview.selections)} explicitly staged row(s). All entries post together after confirmation."
        )
        title.setWordWrap(True)
        layout.addWidget(title)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        text, posting_details = [], []
        for selection, entry in zip(preview.selections, preview.entries, strict=True):
            row = rows[selection.row_id]
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
            text.append(
                f"{row.description or 'Description not printed'}\nAccount: {row.financial_account or 'Not assigned'}; scope: {getattr(row, 'tracking_scope', None) or 'account total'}\nSource date: {source_date}; posting candidate: {posting_candidate} ({provenance}); accounting date: {entry.posting_date} ({'explicit override' if selection.accounting_date else provenance})\nSource amount: {_money(row.amount_minor)}; purpose: {PURPOSE_LABELS[selection.purpose]}; category: {categories.get(selection.category_id, selection.category_id)}\nReason: {preview.reason}\n"
                + _purpose_effects(
                    selection.purpose,
                    row.amount_minor,
                    financial_kind="asset" if review.review_kind == "cash" else "liability",
                )
            )
            posting_details.append(
                f"{entry.posting_date} · {row.description or 'Description not printed'}\n"
                + "\n".join(
                    f"{posting.account_id}: {_money(posting.amount_minor)} debit signed" for posting in entry.postings
                )
            )
        details.setPlainText("\n\n".join(text))
        layout.addWidget(details, 1)
        show_postings = QCheckBox("Show exact posting lines")
        posting_text = QPlainTextEdit("\n\n".join(posting_details))
        posting_text.setReadOnly(True)
        posting_text.setAccessibleName("Exact ledger posting detail")
        posting_text.hide()
        show_postings.toggled.connect(posting_text.setVisible)
        layout.addWidget(show_postings)
        layout.addWidget(posting_text)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        confirm = buttons.addButton(f"Confirm and post {len(preview.entries)} entries", QDialogButtonBox.AcceptRole)
        confirm.clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        if tuple(self.staged.values()) != preview.selections or self.reason.text().strip() != preview.reason:
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
            post, message=f"Saved {len(preview.entries)} reviewed entries together.", batch=True
        )

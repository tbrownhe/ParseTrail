"""Shared asynchronous lifecycle and explicit staging for ordinary source review."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from parsetrail.gui.v2_form_state import install_form_styles, set_field_state, set_status
from parsetrail.gui.v2_profile_jobs import ProfileJobs
from parsetrail.gui.v2_review_navigation import reviewed_elsewhere


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
        self.table.horizontalHeader().moveSection(self.model.columnCount() - 1, 0)
        self.actions_layout.insertWidget(0, self.batch.stage_button)
        self.setTabOrder(self.reason, self.batch.stage_button)
        self.setTabOrder(self.batch.stage_button, self.action_button)
        self.setTabOrder(self.action_button, self.withdraw_button)
        self.repeat_review_button = QPushButton("Review possible repeated transactions…")
        self.repeat_review_button.setToolTip(
            "Compare occurrences in different documents before deciding whether they are the same transaction."
        )
        self.repeat_review_button.clicked.connect(self._review_possible_repeats)
        self.actions_layout.addWidget(self.repeat_review_button)
        self.repeat_review_button.hide()
        if self.batch.reason is not self.reason:
            self.reason.textChanged.connect(self.batch.update_summary)
        self.table.selectionModel().selectionChanged.connect(self._selection_membership_changed)
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
            self.layout().setSpacing(3)
            self.review_intro.hide()
            self.overlap_note.hide()
            self.layout().removeWidget(self.cancel_read_button)
            self.navigation.layout().addWidget(self.cancel_read_button)
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

    def _selection_membership_changed(self, *_args):
        # Qt updates selection before emitting this signal. Navigation resolves
        # a sole selected row even when currentIndex is an old/deselected anchor.
        self._refresh_selection_scope()

    def _refresh_selection_scope(self):
        row = self.navigation.current()
        if len(self.navigation.selected()) > 1 or self._in_multi or self._form_row_id != (row.row_id if row else None):
            self._selected()

    def _single_selection(self):
        return len(self.navigation.selected()) == 1

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
        common = set.intersection(*(set(row.allowed_purposes) for row in rows))
        offered = tuple(key for key in ("expense", "expense_refund", "income", "income_adjustment") if key in common)
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
        self.form.setRowVisible(self.saved_review_note, False)
        self.batch.show()
        count = len(self.navigation.selected())
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
        for field, name in ((self.purpose, "purpose"), (self.category, "category"), (self.reason, "review note")):
            self.form.setRowVisible(self.category_row if field is self.category else field, True)
            field.setEnabled(usable)
            valid = bool(field.text().strip()) if field is self.reason else field.currentData() is not None
            if not valid:
                missing.append(name)
            set_field_state(
                field, "ready" if usable and valid else "required" if usable and not blockers else "neutral"
            )
        self.form.labelForField(self.reason).setText(
            f"{'4' if hasattr(self, 'accounting_date') else '3'}. Review note — applies to all staged rows *"
        )
        self.manage_categories_button.setEnabled(usable and self.purpose.currentData() is not None)
        if hasattr(self, "accounting_date"):
            self.form.setRowVisible(self.accounting_date, True)
            self.form.labelForField(self.accounting_date).setText("3. Dates (per row)")
            self.accounting_date.setEnabled(False)
            self.accounting_date.setPlaceholderText("Each row keeps its own date")
            self.accounting_date.blockSignals(True)
            self.accounting_date.clear()
            self.accounting_date.blockSignals(False)
            set_field_state(
                self.accounting_date, "readonly", "Each row keeps its own date; stage date overrides individually."
            )
        self.batch.stage_button.setText(f"Stage {count} selected")
        self.batch.stage_button.setEnabled(usable and not missing and not blockers)
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
            else ("Required: " + ", ".join(missing) + ". " if missing else "Choices apply to ALL selected rows. ")
            + f"Stage {count} selected, then Review staged for exact effects. Not saved."
            + " Stage applies the review note to all staged rows."
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
        self.batch.setVisible(not correction or bool(self.batch.staged))
        self.reason.setAccessibleName(
            "Reason for correction, required for a new decision" if correction else "Review note, required"
        )
        self.reason.setPlaceholderText(
            "Enter a new reason to correct or withdraw this saved review"
            if correction
            else "Review note — staging applies it to every staged row"
        )
        self.action_button.setVisible(correction or owner_route)
        if not correction and not owner_route:
            self.action_button.setEnabled(False)
        self.batch.stage_button.setVisible(not correction and not owner_route)
        self.withdraw_button.setVisible(correction)
        set_field_state(self.action_button, "neutral")
        self.decision_group.setTitle("Correct saved review" if correction else "Review selected transaction")
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
            missing.append("purpose")
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
        note = self.reason.text().strip()
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
            missing.append("reason for correction" if correction else "review note")
            set_field_state(self.reason, "required", "Explain this new review or correction before confirming.")
        else:
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
                "Changes not staged. Stage selected to update this proposal and the shared note for all staged rows. Review staged uses the previous staged choices."
                if dirty
                else "Staged · Not saved. Review staged to inspect exact effects and confirm. You can remove this row from staged without changing other rows.",
            )
        elif not correction and self.batch.stage_button.isEnabled():
            set_status(
                self.status,
                "ready",
                "Ready to stage · Not saved. Stage selected, then Review staged to confirm exact effects.",
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
            or self.batch.reason.text().strip()
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
        self._form_entry_key = row.entry_key if row else None
        self._form_baseline = (
            row.purpose if row else None,
            row.category_id if row else None,
            (row.effective_date or self._posting_candidate(row) or "")
            if row and hasattr(self, "accounting_date")
            else None,
        )
        draft = self._row_drafts.get(self._form_row_id)
        # A previous row's text is never a reason for this new decision. Restore
        # only a draft authored against this exact active interpretation.
        self.reason.clear()
        if row is None or draft is None or draft[0] != row.entry_key:
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
            self.withdraw_button.setVisible(self._single_selection() and row is not None and row.entry_key is not None)

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
            self._apply_snapshot(result, self._selected_after_read)
            active_entries = {row.row_id: row.entry_key for row in result.rows}
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
                and self._current().entry_key == draft[5]
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
        elif key[0] == "evidence":
            from parsetrail.gui.v2_evidence_preview import V2EvidencePreview

            self.operation_status.setText("Saved source evidence loaded; this preview does not post entries.")
            self.operation_status.show()
            V2EvidencePreview(result, self).exec()
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
                self.batch.clear(clear_proposal=not retain_current)
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
        if not self._single_selection():
            return
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
        self._staged_reason = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.title = QLabel("Staged for review")
        title_font = self.title.font()
        title_font.setBold(True)
        self.title.setFont(title_font)
        controls.addWidget(self.title)
        self.reason = review.reason
        self.reason.setPlaceholderText("Review note — staging applies it to every staged row")
        self.stage_button = QPushButton("Stage selected rows")
        self.stage_button.clicked.connect(self.stage_selected)
        self.preview_button = QPushButton("Review staged…")
        self.preview_button.clicked.connect(self.preview)
        self.clear_button = QPushButton("Clear staged")
        self.clear_button.clicked.connect(self.clear_from_ui)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.setToolTip(
            "Remove selected rows from the staged set; other staged choices and saved entries are kept."
        )
        self.remove_button.clicked.connect(self.remove_selected)
        controls.addWidget(self.preview_button)
        controls.addWidget(self.remove_button)
        controls.addWidget(self.clear_button)
        layout.addLayout(controls)
        self.summary = QLabel("No rows staged. Select rows, choose purpose/category, and enter a review note.")
        self.summary.setWordWrap(True)
        self.stage_button.setText("Stage selected")
        self.stage_button.setToolTip(
            "Capture the selected purpose, category and date. Staging replaces only selected proposals, and applies this note to ALL staged rows. Nothing posts until exact confirmation."
        )
        if review.embedded:
            self.title.hide()
            self.summary.setWordWrap(False)
            controls.insertWidget(0, self.summary, 1)
        else:
            layout.addWidget(self.summary)
        self.reason.textChanged.connect(self.update_summary)
        review.navigation.proxy.rowsRemoved.connect(self.update_summary)
        review.navigation.proxy.rowsInserted.connect(self.update_summary)
        review.navigation.scope_changed.connect(self.update_summary)
        self.update_summary()

    def clear(self, *, clear_proposal=True):
        self.staged.clear()
        self._staged_reason = ""
        if clear_proposal or self.reason is not self.review.reason:
            self.reason.clear()
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
                f"Purpose: {PURPOSE_LABELS.get(proposal.purpose, proposal.purpose)}\n"
                f"Category: {labels.get(proposal.category_id, proposal.category_id)}\n"
                f"Accounting date: {proposal.accounting_date or getattr(row, 'posting_candidate', None) or getattr(row, 'posting_date', None) or getattr(row, 'date', None) or 'Unknown'}\n"
                f"Shared staged note: {self.note()}\nCurrent source status: {row.status}"
            )
            draft = review._row_drafts.get(row.row_id)
            if draft is not None:
                expected_date = (
                    str(proposal.accounting_date)
                    if proposal.accounting_date
                    else getattr(row, "posting_candidate", None)
                )
                if (draft[1], draft[2]) != (proposal.purpose, proposal.category_id) or (
                    review.review_kind == "card" and draft[3] != expected_date
                ):
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
        self.update_stage_action()
        if count:
            text = f"{count} staged row(s); {hidden} hidden by the current filter. Not saved. Review staged includes all of them. Staging a new note replaces the note for ALL staged rows. Corrections are reviewed individually."
            self.summary.setText(
                f"{count} staged" + (f" · {hidden} hidden" if hidden else "") + " · Not saved"
                if self.review.embedded
                else text + " Not saved."
            )
            self.summary.setToolTip(text + "\nShared staged note: " + self.note())
        else:
            self.summary.setText(
                "No rows staged"
                if self.review.embedded
                else "No rows staged. Select rows, choose purpose/category, and enter a review note."
            )

    def update_stage_action(self):
        review = self.review
        rows = review.navigation.selected()
        purpose, category = review.purpose.currentData(), review.category.currentData()
        note = review.reason.text() if len(rows) > 1 else self.reason.text()
        _proposed, blockers = self.propose(rows, purpose, category)
        eligible = bool(
            rows
            and not review.jobs.pending
            and review.basis is not None
            and review._profile_matches()
            and purpose in {"expense", "expense_refund", "income", "income_adjustment"}
            and category is not None
            and note.strip()
            and not blockers
        )
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
        if len(rows) > 1 and self.reason is not review.reason:
            self.reason.setText(review.reason.text())
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
            or purpose not in {"expense", "expense_refund", "income", "income_adjustment"}
            or category is None
            or not self.reason.text().strip()
        ):
            self.summary.setText("Select rows and explicitly choose a purpose, category and shared review note first.")
            return
        previous_note = self._staged_reason
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
                    if selection.accounting_date is not None
                    else (row.effective_date or review._posting_candidate(row) or "")
                    if hasattr(review, "accounting_date")
                    else None
                )
                review._row_drafts[row.row_id] = (
                    row.entry_key,
                    selection.purpose,
                    selection.category_id,
                    accounting_date,
                    staged_note,
                    True,
                )
            elif row.row_id in self.staged:
                draft = review._row_drafts.get(row.row_id)
                if draft is not None and draft[4].strip() == previous_note:
                    review._row_drafts[row.row_id] = (*draft[:4], staged_note, draft[5])
        self.update_summary()
        review._update_review_actions()

    def propose(self, rows, purpose, category):
        """Pure draft preflight shared by readiness and staging; no mutation."""
        from parsetrail.core.v2_ordinary_batch import OrdinaryCategorySelection

        review = self.review
        refused, proposed = [], {}
        if len(set(self.staged) | {row.row_id for row in rows}) > 2000:
            return {}, ["A staged set supports at most 2,000 rows. Reduce the selection or clear prior staged rows."]
        for row in rows:
            ready = row.status == "Ready for purpose review"
            accounting_date = None
            if review.review_kind == "card":
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

    def show_preview(self, preview):
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
            text.append(
                f"{row.description or 'Description not printed'}\nAccount: {row.financial_account or 'Not assigned'}; scope: {getattr(row, 'tracking_scope', None) or 'account total'}\nSource date: {source_date}; posting candidate: {posting_candidate} ({provenance}); accounting date: {entry.posting_date} ({'explicit override' if selection.accounting_date else provenance})\nSource amount: {_money(row.amount_minor)}; purpose: {PURPOSE_LABELS[selection.purpose]}; category: {categories.get(selection.category_id, selection.category_id)}\nReason: {preview.reason}\n"
                + _purpose_effects(
                    selection.purpose,
                    row.amount_minor,
                    financial_kind="asset" if review.review_kind == "cash" else "liability",
                )
                + qualification
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
        if tuple(self.staged.values()) != preview.selections or self.note() != preview.reason:
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

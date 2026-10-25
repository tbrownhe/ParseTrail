"""Review printed opening provenance and post a dated opening position explicitly."""

from __future__ import annotations

import sqlite3
from datetime import date

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from parsetrail.core.v2_profile_store import EarliestSourceOpening, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_cash_activity_review import _money
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview


class V2OpeningReview(QDialog):
    """Keep a source assertion separate from the later opening journal decision."""

    def __init__(self, workspace: V2Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.candidate: EarliestSourceOpening | None = None
        self.reviews = {}
        self.decision = None
        self.basis = None
        self._loaded_form = (None, False, "", "")
        self.setWindowTitle("2.0 opening position review")
        self.resize(850, 510)
        layout = QVBoxLayout(self)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self.profile_path = QLineEdit(str(workspace.profile_path))
        self.profile_path.setReadOnly(True)
        self.profile_path.setCursorPosition(0)
        profile_row.addWidget(self.profile_path)
        layout.addLayout(profile_row)
        note = QLabel(
            "A printed opening becomes an account balance only after you inspect each earliest source and confirm "
            "its inclusive period timing. The opening uses equity; it creates no income or spending. "
            "Conflicts and missing source facts remain blocked. This review does not certify later statement coverage."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.account = QComboBox()
        self.account.currentIndexChanged.connect(self.refresh)
        form.addRow("Financial account", self.account)
        self.candidate_label = QLabel()
        self.candidate_label.setWordWrap(True)
        form.addRow("Earliest source", self.candidate_label)
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
        layout.addLayout(form)
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
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            for account in store.financial_accounts():
                self.account.addItem(f"{account.name} ({account.kind})", account.id)
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
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                section = next(
                    (
                        row
                        for row in store.statement_coverage()
                        if row.account_id == self.account.currentData() and row.source_sha256 == source_id
                    ),
                    None,
                )
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
        account_id = self.account.currentData()
        if account_id is None:
            self.candidate = None
            self.reviews = {}
            self.decision = None
            self.basis = None
            self.source.clear()
            self.candidate_label.setText("Add and bind a financial account first.")
            self._source_changed()
            return
        with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
            self.candidate = next(item for item in store.earliest_source_openings() if item.account_id == account_id)
            self.reviews = {review.source_sha256: review for review in store.statement_source_reviews(account_id)}
            self.decision = store.opening_decision(account_id)
            self.basis = store.opening_review_basis(account_id)
        candidate = self.candidate
        amount = candidate.printed_opening_minor
        natural = 1 if candidate.account_kind == "asset" else -1
        self.candidate_label.setText(
            f"Start: {candidate.earliest_period_start.isoformat() if candidate.earliest_period_start else 'unknown'}; "
            f"printed candidate: {_money(amount * natural) if amount is not None else 'unavailable'}; "
            f"{candidate.bound_statement_sections} bound section(s)."
        )
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
        self.confirm.setEnabled(
            self.candidate is not None
            and not self.candidate.blockers
            and self.candidate.earliest_period_start is not None
            and self.candidate.earliest_period_start > date.min
            and self.decision is None
            and not changed
        )
        if self.decision is not None:
            self.status.setText(
                "Opening decision is stale after source review changes; correction is pending."
                if self.decision.stale
                else "Zero opening confirmed."
                if self.decision.entry_key is None
                else "Opening posted."
            )
        elif self.candidate is not None:
            self.status.setText(
                "Review needed: " + ", ".join(self.candidate.blockers)
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
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.record_opening_source_review(
                    account_id,
                    source_id,
                    opening_origin=self.origin.currentData(),
                    timing_confirmed=self.timing.isChecked(),
                    source_reference=self.reference.text(),
                    note=self.note.text(),
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Source review was not saved", str(exc))
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
            f"Confirm {candidate.account_name}'s printed opening of "
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

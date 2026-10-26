"""Record reviewed provenance for one explicitly bound statement section."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from parsetrail.core.v2_profile_store import ProfileFormatError, StatementCoverageRow, V2ProfileStore
from parsetrail.core.v2_review_dates import posting_date_candidate
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview


class V2StatementSourceReview(QDialog):
    """An assertion about a source, never a journal or reconciliation decision."""

    def __init__(self, profile: Path, section: StatementCoverageRow, parent=None):
        super().__init__(parent)
        self.profile = profile
        with V2ProfileStore.open(profile, read_only=True) as store:
            snapshot = store.statement_source_review_snapshot(section.account_id, section.source_sha256)
        self.section = section = snapshot.section
        payload, account = snapshot.payload, snapshot.source_account
        self.saved, self.review = snapshot.saved, snapshot.review
        self.expected_section = account.source_identity, account.source_identity_form
        self.basis = snapshot.basis_sha256
        self._context_valid = True
        self._loaded = None
        self.reported_dates_available = all(
            (candidate := posting_date_candidate(row)) is not None and candidate.provenance in {"observed", "derived"}
            for row in account.rows
            if row.row_role == "activity"
        )
        self.setWindowTitle("2.0 statement source review")
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        scope = QLabel(
            "This saves a source-provenance assertion only. It does not post transactions, "
            "confirm an opening, or reconcile a statement. Printed source evidence remains unchanged."
        )
        scope.setWordWrap(True)
        layout.addWidget(scope)
        facts = QLabel(
            f"{section.account_name} · Source {section.source_sha256[:16]}…\n"
            f"Section: {account.source_identity} ({account.source_identity_form}); financial account ID: {section.account_id}\n"
            f"Period: {payload.start.iso or 'unknown'} to {payload.end.iso} "
            f"({payload.start.provenance} start, {payload.end.provenance} end)\n"
            f"Opening: {account.opening.raw if account.opening and account.opening.raw else 'unavailable'} "
            f"({account.opening.provenance if account.opening else 'unknown'}); "
            f"closing: {account.closing.raw if account.closing and account.closing.raw else 'unavailable'} "
            f"({account.closing.provenance if account.closing else 'unknown'}); "
            f"scope: {account.balance_scope.replace('_', ' ')}"
            + (
                ". Cash-component assertions apply only to this cash section; they do not review the whole HSA or investment portfolio."
                if account.balance_scope == "cash_component"
                else ""
            )
        )
        facts.setWordWrap(True)
        layout.addWidget(facts)
        form = QFormLayout()
        self.opening = QComboBox()
        self.opening.addItem("Choose opening assessment", None)
        self.opening.addItem("Printed on statement", "reported")
        self.opening.addItem("Not established", "unestablished")
        self.opening.currentIndexChanged.connect(self._update_action)
        form.addRow("Opening balance origin", self.opening)
        self.closing = QComboBox()
        self.closing.addItem("Choose closing assessment", None)
        self.closing.addItem("Printed on statement", "reported")
        self.closing.addItem("Not established", "unestablished")
        self.closing.currentIndexChanged.connect(self._update_action)
        form.addRow("Closing balance origin", self.closing)
        self.timing = QCheckBox("I checked the inclusive statement period timing")
        self.timing.toggled.connect(self._update_action)
        form.addRow("Period timing", self.timing)
        self.posting_dates = QComboBox()
        self.posting_dates.addItem("Choose date assessment", None)
        self.posting_dates.addItem("Reported posting dates", "reported")
        self.posting_dates.addItem("Estimated posting dates", "estimated")
        self.posting_dates.addItem("Unverified posting dates", "unverified")
        if not self.reported_dates_available:
            self.posting_dates.model().item(self.posting_dates.findData("reported")).setEnabled(False)
        self.posting_dates.currentIndexChanged.connect(self._update_action)
        form.addRow("Posting dates", self.posting_dates)
        self.reference = QLineEdit()
        self.reference.setMaxLength(500)
        self.reference.setPlaceholderText("Required page, section or other source reference")
        self.reference.textChanged.connect(self._update_action)
        form.addRow("Source reference", self.reference)
        self.note = QLineEdit()
        self.note.setMaxLength(500)
        self.note.setPlaceholderText("Optional review note")
        self.note.textChanged.connect(self._update_action)
        form.addRow("Note", self.note)
        layout.addLayout(form)
        self.status = QLabel(
            "Reported posting dates are unavailable for this source's activity rows."
            if not self.reported_dates_available
            else "Review the printed source before recording these assertions."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.preview = QPushButton("Preview saved source")
        self.preview.clicked.connect(self._preview)
        layout.addWidget(self.preview)
        self.save = QPushButton("Record source review")
        self.save.clicked.connect(self._save)
        layout.addWidget(self.save)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if self.review is not None:
            self.opening.setCurrentIndex(self.opening.findData(self.review.opening_origin))
            self.closing.setCurrentIndex(self.closing.findData(self.review.closing_origin))
            self.timing.setChecked(self.review.timing_confirmed)
            self.posting_dates.setCurrentIndex(self.posting_dates.findData(self.review.posting_dates))
            self.reference.setText(self.review.source_reference)
            self.note.setText(self.review.note)
        self._loaded = self._form()
        self._update_action()

    def _form(self):
        return (
            self.opening.currentData(),
            self.closing.currentData(),
            self.timing.isChecked(),
            self.posting_dates.currentData(),
            self.reference.text().strip(),
            self.note.text().strip(),
        )

    def _update_action(self, *_args) -> None:
        if not hasattr(self, "save"):
            return
        opening, closing, _timing, dates, reference, _note = self._form()
        self.save.setEnabled(
            opening is not None
            and closing is not None
            and dates is not None
            and bool(reference)
            and self._context_valid
            and self._loaded is not None
            and (self.review is None or self._form() != self._loaded)
        )

    def _preview(self) -> None:
        V2EvidencePreview(self.saved, self).exec()

    def _save(self) -> None:
        opening, closing, timing, dates, reference, note = self._form()
        try:
            with V2ProfileStore.open(self.profile) as store:
                store.record_statement_source_review(
                    self.section.account_id,
                    self.section.source_sha256,
                    expected_revision_id=self.review.revision_id if self.review else None,
                    expected_section=self.expected_section,
                    expected_basis_sha256=self.basis,
                    opening_origin=opening,
                    closing_origin=closing,
                    timing_confirmed=timing,
                    posting_dates=dates,
                    source_reference=reference,
                    note=note,
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            changed = str(exc) in {
                "statement_source_review_context_changed_since_selection",
                "statement_source_review_changed_since_selection",
            }
            if changed or isinstance(exc, (sqlite3.Error, OSError)):
                self._context_valid = False
                self._update_action()
            message = (
                "The loaded source section, assignment or saved review changed. Close and reopen this source review; no assessment was recorded from this stale form."
                if changed
                else "The source assessment could not be recorded. Check its printed facts, date assessment and required reference before trying again."
            )
            self.status.setText(message)
            QMessageBox.warning(self, "Source review was not saved", message)
            return
        self.accept()

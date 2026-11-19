"""Background batch import with a per-file, copyable result review."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_format_recognition import ImportCancelled
from parsetrail.core.v2_import_accounts import ImportAccountPlan, ImportAccountReview
from parsetrail.core.v2_workspace import BatchImportResult, V2Workspace, WorkspaceError
from parsetrail.gui.v2_csv_import_preview import _ExplicitDecisionButton
from parsetrail.gui.v2_evidence_preview import _money


class V2ImportProgress(QDialog):
    """Reusable GUI-owned progress; updates never process nested native events.

    Closing requests cancellation once and keeps the surface until the worker
    has actually stopped. Hiding it for account review has no cancellation side
    effect (unlike QProgressDialog reset/auto-close behavior).
    """

    cancel_remaining = Signal()

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importing statements")
        self.setWindowModality(Qt.WindowModal)
        self.paths = paths
        self._cancelling = False
        self._finished = False
        self.setFixedWidth(600)
        layout = QVBoxLayout(self)
        self.body = QWidget(self)
        self.body.setFocusPolicy(Qt.StrongFocus)
        self.body.setAccessibleName("Import in progress; Tab reaches Cancel remaining imports")
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        self.file_context = QLabel()
        self.file_context.setWordWrap(True)
        self.file_context.setTextFormat(Qt.PlainText)
        self.file_context.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.addWidget(self.file_context)
        self.selected_path = QLineEdit()
        self.selected_path.setReadOnly(True)
        self.selected_path.setFocusPolicy(Qt.ClickFocus)
        self.selected_path.setAccessibleName("Current statement file path; select to copy")
        body.addWidget(self.selected_path)
        self.phase = QLabel()
        self.phase.setWordWrap(True)
        self.phase.setTextFormat(Qt.PlainText)
        body.addWidget(self.phase)
        self.completed = QProgressBar()
        self.completed.setRange(0, len(paths))
        self.completed.setValue(0)
        self.completed.setFormat("%v of %m files completed")
        self.completed.setAccessibleName("Completed files, not current file percentage")
        body.addWidget(self.completed)
        self.outcomes = QLabel("No files completed yet.")
        self.outcomes.setWordWrap(True)
        self.outcomes.setTextFormat(Qt.PlainText)
        body.addWidget(self.outcomes)
        consequence = QLabel("Completed imports remain saved if you cancel.")
        consequence.setWordWrap(True)
        body.addWidget(consequence)
        layout.addWidget(self.body)
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = _ExplicitDecisionButton("Cancel remaining imports")
        self.cancel_button.clicked.connect(self.reject)
        actions.addWidget(self.cancel_button)
        layout.addLayout(actions)
        self.set_current(1, paths[0], "Reading and checking the document…")

    def set_current(self, index, path, phase):
        self.file_context.setText(f"File {index} of {len(self.paths)}: {path.name}")
        self.file_context.setToolTip(str(path))
        self.selected_path.setText(str(path))
        self.selected_path.setCursorPosition(0)
        if not self._cancelling:
            self.phase.setText(phase)

    def update_outcomes(self, outcomes):
        self.completed.setValue(len(outcomes))
        counts = {
            status: sum(item.status == status for item in outcomes)
            for status in ("imported", "already_imported", "skipped", "failed")
        }
        text = (
            f"{counts['imported']} imported · {counts['already_imported']} already saved · "
            f"{counts['skipped']} skipped · {counts['failed']} failed."
        )
        if outcomes:
            text += f" Last: {outcomes[-1].path.name} — {outcomes[-1].status.replace('_', ' ')}."
        self.outcomes.setText(text)

    def present(self, avoid=()):
        """Keep Cancel away from the preceding review's decision coordinates."""
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move(parent.frameGeometry().center() - self.rect().center())
        self.layout().activate()
        # The compact surface normally sits above the large review's footer.
        # Check actual screen coordinates as fonts, DPI and window sizes vary.
        for _ in range(8):
            cancel_rect = self.cancel_button.rect().translated(
                self.cancel_button.mapToGlobal(self.cancel_button.rect().topLeft())
            )
            if not any(cancel_rect.intersects(rect) for rect in avoid):
                break
            self.move(self.x(), self.y() - self.cancel_button.height() - 12)
        self.show()
        self.body.setFocus(Qt.OtherFocusReason)

    def cancelling(self):
        self._cancelling = True
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancelling…")
        self.phase.setText("Cancelling remaining imports… Waiting for the current operation to stop safely.")
        self.body.setFocus(Qt.OtherFocusReason)

    def finish(self):
        self._finished = True
        self.hide()

    def reject(self):
        if not self._finished and not self._cancelling:
            self.cancelling()
            self.cancel_remaining.emit()

    def closeEvent(self, event):
        if self._finished:
            event.accept()
        else:
            self.reject()
            event.ignore()


def loan_automation_summary(outcome) -> str:
    """Explain the separate posting result without turning a saved import into a failure."""
    if outcome is None:
        return ""
    if outcome.status == "posted":
        return (
            f"Automatically posted payment · {_money(outcome.principal_minor)} principal · "
            f"{_money(outcome.interest_minor)} interest. Paying account unresolved in Transfers."
        )
    reason = {
        "loan_auto_account_new": "Check the payment for this newly created account.",
        "loan_auto_account_required": "Choose a compatible loan account.",
        "loan_auto_source_warning": "Source evidence needs attention.",
        "loan_auto_unsupported": "This statement format requires manual loan review.",
        "loan_auto_multiple_payments": "Choose the complete payment components.",
        "loan_auto_prior_review": "Existing payment review history needs inspection.",
        "loan_auto_date_permission_required": "Allow an assumed accounting date or review the date setting.",
        "loan_auto_changed": "The profile or preferences changed before posting.",
        "loan_auto_cancelled": "Automatic posting was cancelled.",
        "loan_auto_failed": "Automatic posting could not complete. Inspect the saved evidence.",
        "loan_auto_origination": "Review the loan origination and its destination.",
        "source_overlap_review_required": "Repeated source evidence needs occurrence review.",
        "loan_source_already_used": "This activity already has a posting or interpretation.",
        "loan_principal_scope_required": "Choose a loan account that tracks principal.",
        "loan_component_unsupported": "Printed payment components need inspection.",
    }.get(outcome.reason_code, "Inspect the saved loan evidence.")
    return "Imported · loan review needed. " + reason


def statement_value_automation_summary(outcome) -> str:
    """Describe a nonposting value result separately from its successful import."""
    if outcome is None:
        return ""
    if outcome.status == "recorded":
        return (
            f"Statement value recorded automatically · {_money(outcome.amount_minor)} · "
            f"{outcome.value_date.isoformat()}. Summary totals remain evidence; no transactions or budget changes."
        )
    reason = {
        "statement_value_auto_conflict": "Different values are recorded for the statement date.",
        "statement_value_auto_source_warning": "Source evidence needs attention.",
        "statement_value_auto_prior_review": "This statement already has value review history.",
        "statement_value_auto_multiple_sections": "Review each statement plan separately.",
        "statement_value_auto_account_required": "Confirm a compatible account for this statement.",
        "statement_value_auto_unsupported": "This statement format needs manual value review.",
        "statement_value_auto_unavailable": "Check the confirmed account and the statement's closing value and date.",
        "statement_value_auto_consent_required": "Enable automatic recording for future imports or review this value manually.",
        "statement_value_auto_changed": "The profile or preferences changed before recording.",
        "statement_value_auto_cancelled": "Automatic value recording was cancelled.",
        "statement_value_auto_failed": "Automatic value recording could not complete. Inspect the saved evidence.",
        "statement_summary_value_conflict": "Different values are recorded for the statement date.",
        "account_dated_value_conflict_requires_review": "Different values are recorded for the statement date.",
        "statement_summary_account_required": "Confirm a compatible account for this statement.",
        "statement_summary_binding_mixed": "Confirm one account for this statement plan.",
        "source_value_closing_unavailable": "The statement's closing value is not established.",
        "source_value_date_unavailable": "The statement's closing date is not established.",
        "source_value_scope_or_kind_mismatch": "The account does not match the statement's value scope.",
    }.get(outcome.reason_code, "Inspect the saved statement value and its evidence.")
    return "Imported · statement value needs review. " + reason


def import_automation_summary(result) -> str:
    return "\n".join(
        text
        for text in (
            loan_automation_summary(result.loan_automation),
            statement_value_automation_summary(result.statement_value_automation),
        )
        if text
    )


@dataclass
class ImportAccountReviewRequest:
    path: Path
    review: ImportAccountReview
    index: int
    total: int
    completed: tuple = ()
    decided: Event = field(default_factory=Event)
    decision: ImportAccountPlan | None = None
    error: Exception | None = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    @property
    def recognition(self):
        return self.review.recognition

    def finish(self, decision=None):
        with self._lock:
            if not self.decided.is_set():
                self.decision = decision
                self.decided.set()

    def fail(self):
        with self._lock:
            if not self.decided.is_set():
                self.error = WorkspaceError("import_preview_unavailable")
                self.decided.set()


def review_import_accounts(worker, path, review, *, index=1, total=1):
    """Collect an explicit account/import decision without holding a connection."""
    request = ImportAccountReviewRequest(path, review, index, total, tuple(getattr(worker, "completed_outcomes", ())))
    worker.import_review_requested.emit(request)
    while not request.decided.wait(0.05):
        if worker.cancel_event.is_set():
            raise ImportCancelled("cancelled")
    if worker.cancel_event.is_set():
        raise ImportCancelled("cancelled")
    if request.error is not None:
        raise request.error
    return request.decision


def import_failure_guidance(code: str) -> str:
    explanations = {
        "catalog_no_match": "This document does not match an installed statement format. Check that you selected a supported original CSV or PDF, or install an updated signed statement-format package and try again.",
        "catalog_ambiguous_match": "More than one installed format matches this document. ParseTrail cannot safely choose one. Install an updated signed statement-format package before retrying.",
        "import_preparation_size_limit": "The document produced too much evidence to prepare safely. Nothing new was imported. Use a smaller supported export or an updated signed format package that narrows the match.",
        "import_account_routing_conflict": "This file matches conflicting supported formats. No new source, account or assignment was saved. Use a supported original export or install an updated signed statement-format package before retrying.",
        "verified_catalog_missing": "Install a signed statement-format package from Documents before importing, then try again.",
        "source_unavailable": "The selected file could not be read. Check that it still exists and is accessible, then select it again.",
        "unsupported_source_type": "Choose a supported CSV or PDF original. Other document types cannot be imported here.",
        "source_changed_since_preview": "The original changed after its preview. Nothing new was imported. Select it again to review the current bytes.",
        "catalog_selection_source_changed": "The original changed after its preview. Select it again and check a fresh preview before importing.",
        "catalog_selection_catalog_changed": "The installed statement formats changed after the preview. Select the document again to check a fresh preview.",
        "format_preview_unavailable": "The CSV preview could not be opened. No new source was saved. Reload the profile and try again; previously imported documents are retained.",
        "import_preview_unavailable": "The account and import preview could not be opened. No new source, account or assignment was saved. Retry the file; previously completed imports are retained.",
    }
    message = explanations.get(
        code,
        "The document could not be imported safely. Check the selected original and installed statement formats, then retry. Keep the details below if the problem continues.",
    )
    return f"{message}\n\nDetails: {code}"


class V2BatchImportWorker(QThread):
    progressed = Signal(int, str)
    outcomes_changed = Signal(object)
    import_review_requested = Signal(object)

    def __init__(self, workspace: V2Workspace, paths: tuple[Path, ...], parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.paths = paths
        self.cancel_event = Event()
        self.result: BatchImportResult | None = None
        self.error: Exception | None = None
        self.completed_files = 0
        self.completed_outcomes = []

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            self.result = self.workspace.import_files(
                self.paths,
                cancelled=self.cancel_event.is_set,
                progress=self._progress,
                review_import=lambda path, review: review_import_accounts(
                    self, path, review, index=self.completed_files + 1, total=len(self.paths)
                ),
            )
        except Exception as exc:
            self.error = exc

    def _progress(self, count, item):
        self.completed_files = count
        self.completed_outcomes.append(item)
        self.outcomes_changed.emit(tuple(self.completed_outcomes))
        self.progressed.emit(count, item.path.name)


class V2BatchImportReport(QDialog):
    """Review which selected files were saved, reused, refused or untouched."""

    def __init__(self, result: BatchImportResult, parent=None):
        super().__init__(parent)
        self.setWindowTitle("2.0 batch import results")
        self.resize(780, 480)
        layout = QVBoxLayout(self)
        counts = {
            status: sum(item.status == status for item in result.files)
            for status in ("imported", "already_imported", "skipped", "failed", "cancelled", "not_attempted")
        }
        summary = QLabel(
            f"{counts['imported']} imported · {counts['already_imported']} already saved · "
            f"{counts['skipped']} skipped · {counts['failed']} failed · {counts['cancelled']} cancelled · "
            f"{counts['not_attempted']} not attempted. "
            "Completed imports remain saved; automatic review results are shown per file."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.files = QListWidget()
        for item in result.files:
            label = f"{item.path.name} — {item.status.replace('_', ' ')}"
            automation = import_automation_summary(item)
            if item.loan_automation is not None:
                label += (
                    " — payment posted automatically"
                    if item.loan_automation.status == "posted"
                    else " — loan review needed"
                )
            if item.statement_value_automation is not None:
                label += (
                    " — statement value recorded automatically"
                    if item.statement_value_automation.status == "recorded"
                    else " — statement value needs review"
                )
            if item.error_code:
                label += " — select for recovery details"
            row = QListWidgetItem(label)
            row.setData(Qt.UserRole, str(item.path))
            row.setData(Qt.UserRole + 1, item.error_code)
            row.setData(Qt.UserRole + 2, automation)
            row.setToolTip(str(item.path))
            self.files.addItem(row)
        layout.addWidget(self.files)
        layout.addWidget(QLabel("Selected file:"))
        self.selected_path = QLineEdit()
        self.selected_path.setReadOnly(True)
        layout.addWidget(self.selected_path)
        self.recovery_guidance = QLabel()
        self.recovery_guidance.setWordWrap(True)
        self.recovery_guidance.setTextFormat(Qt.PlainText)
        self.recovery_guidance.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(self.recovery_guidance)
        self.files.currentItemChanged.connect(self._selected)
        if self.files.count():
            self.files.setCurrentRow(0)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _selected(self, current: QListWidgetItem | None) -> None:
        self.selected_path.setText(current.data(Qt.UserRole) if current is not None else "")
        self.selected_path.setCursorPosition(0)
        code = current.data(Qt.UserRole + 1) if current is not None else None
        self.recovery_guidance.setText(
            import_failure_guidance(code) if code else current.data(Qt.UserRole + 2) if current is not None else ""
        )

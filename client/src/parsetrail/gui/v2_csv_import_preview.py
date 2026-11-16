"""Read-only preview of an automatically recognized declared import format."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from shiboken6 import isValid

from parsetrail.core.v2_import_warnings import ImportWarning
from parsetrail.core.v2_institutions import institution_label
from parsetrail.gui.v2_evidence_preview import _location, _money
from parsetrail.gui.v2_form_state import install_form_styles, set_field_state, set_status
from parsetrail.gui.v2_original_document import open_selected_original


def _date(value, *, statement=False):
    provenance = (
        {"observed": "printed", "assumed": "estimated"}.get(value.provenance, value.provenance)
        if statement
        else value.provenance
    )
    return f"{value.iso or 'Unknown'} ({provenance})"


class _FormatChoice(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumContentsLength(24)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)

    def hidePopup(self):
        super().hidePopup()
        if self.isVisible():
            self.setFocus(Qt.PopupFocusReason)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not self.view().isVisible():
            self.showPopup()
            event.accept()
            return
        super().keyPressEvent(event)


class _ExplicitDecisionButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.setAutoDefault(False)
        self.setDefault(False)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.hasFocus() and self.isEnabled():
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)


def _date_format(value):
    return {"MM/DD/YYYY": "month/day/year", "MM/DD/YY": "month/day/short year", "YYYY-MM-DD": "year-month-day"}.get(
        value, value or "unspecified"
    )


def _money_format(value):
    return {"usd_symbol_2dp": "USD with $ and 2 decimals", "usd_number_2dp": "USD numbers, 2 decimals"}.get(
        value, (value or "unspecified").replace("_", " ")
    )


_MAPPING_LABELS = {
    "date": "Source date",
    "account": "Source account",
    "description": "Description",
    "total": "Source amount",
    "balance": "Balance",
    "principal": "Principal component",
    "interest": "Interest component",
    "fees": "Fees component",
}


class V2CsvImportPreview(QDialog):
    """Worker decisions use Events; this dialog never owns a profile connection."""

    cancel_remaining = Signal()

    def __init__(self, institutions=(), parent=None):
        super().__init__(parent)
        self.institutions = institutions
        self.request = None
        self._finished = False
        self._original_open = None
        self.setWindowTitle("Review CSV import")
        self.setWindowModality(Qt.WindowModal)
        self.resize(1050, 700)
        install_form_styles(self)
        layout = QVBoxLayout(self)
        self.file_context = QLabel()
        self.file_context.setTextFormat(Qt.PlainText)
        self.file_context.setWordWrap(True)
        layout.addWidget(self.file_context)
        self.queue_status = QLabel()
        self.queue_status.setTextFormat(Qt.PlainText)
        self.queue_status.setWordWrap(True)
        self.queue_status.setAccessibleName("Completed import queue results")
        layout.addWidget(self.queue_status)
        self.scope = QLabel(
            "Import saves the original document and extracted evidence locally. "
            "Account assignment and reviewed spending come afterward; no transactions are posted here."
        )
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.format_label = QLabel()
        self.format_label.setTextFormat(Qt.PlainText)
        self.format_label.setWordWrap(True)
        layout.addWidget(self.format_label)
        self.format_selector = _FormatChoice()
        # Internal selection state for the validated declaration, never a column-mapping control.
        self.format_selector.setAccessibleName("Recognized format")
        self.format_selector.hide()
        self.format_selector.setEnabled(False)
        self.format_selector.currentIndexChanged.connect(self._selected)
        layout.addWidget(self.format_selector)
        self.interpretation = QLabel()
        self.interpretation.setTextFormat(Qt.PlainText)
        self.interpretation.setWordWrap(True)
        layout.addWidget(self.interpretation)
        self.attention_notice = QLabel()
        self.attention_notice.setWordWrap(True)
        self.attention_notice.hide()
        layout.addWidget(self.attention_notice)
        self.rows = QTableWidget(0, 6)
        self.rows.setAccessibleName("Recognized source activity preview")
        self.rows.setHorizontalHeaderLabels(
            ("Source date", "Source account", "Description", "Amount", "Balance", "Source location")
        )
        self.rows.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rows.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rows.setTabKeyNavigation(False)
        for column in (0, 1, 3, 4, 5):
            self.rows.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.rows.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.rows, 1)
        self.mapping = QLabel()
        self.mapping.setTextFormat(Qt.PlainText)
        self.mapping.setWordWrap(True)
        self.mapping.hide()
        layout.addWidget(self.mapping)
        self.details_toggle = QPushButton("Format details")
        self.details_toggle.setAutoDefault(False)
        self.details_toggle.setCheckable(True)
        layout.addWidget(self.details_toggle, alignment=Qt.AlignLeft)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(110)
        self.details.hide()
        self.details_toggle.toggled.connect(self.details.setVisible)
        self.details_toggle.toggled.connect(self.mapping.setVisible)
        layout.addWidget(self.details)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.retained_format_notice = QLabel(
            "Check the recognized activity against your original. This import keeps the recognized format; "
            "changing it afterward is not supported yet. Cancel before importing if the preview does not match your original."
        )
        self.retained_format_notice.setWordWrap(True)
        self.retained_format_notice.setTextFormat(Qt.PlainText)
        layout.addWidget(self.retained_format_notice)
        actions = QHBoxLayout()
        self.original_button = _ExplicitDecisionButton("View original…")
        self.original_button.clicked.connect(self._view_original)
        self.import_button = _ExplicitDecisionButton("Import document")
        self.import_button.setAccessibleName("Import original and evidence locally without posting transactions")
        self.import_button.clicked.connect(self._import)
        self.skip_button = _ExplicitDecisionButton("Skip this file")
        self.skip_button.clicked.connect(self._skip)
        self.cancel_button = _ExplicitDecisionButton("Cancel remaining imports")
        self.cancel_button.clicked.connect(self.reject)
        actions.addWidget(self.original_button)
        actions.addWidget(self.import_button)
        actions.addWidget(self.skip_button)
        actions.addStretch()
        actions.addWidget(self.cancel_button)
        layout.addLayout(actions)

    def present(self, request):
        if self._original_open is not None and isValid(self._original_open):
            self._original_open.cancel()
        self.request = request
        self._finished = False
        self.file_context.setText(f"File {request.index} of {request.total}: {request.path.name}")
        self.file_context.setToolTip(str(request.path))
        self.update_queue(request.completed)
        candidates = request.recognition.candidates
        self.format_selector.blockSignals(True)
        self.format_selector.clear()
        if len(candidates) == 1:
            self.format_selector.addItem("Recognized declared format", candidates[0].parser_id)
        self.format_selector.hide()
        self.format_selector.setCurrentIndex(0)
        self.format_selector.blockSignals(False)
        self.skip_button.setEnabled(True)
        self.original_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.details_toggle.setChecked(False)
        self._selected()
        self.show()
        (self.import_button if self.import_button.isEnabled() else self.skip_button).setFocus()

    def _view_original(self):
        if self.request is None:
            return
        self._original_open = open_selected_original(self.request.path, self.request.recognition.source_sha256, self)

    def _cancel_original(self):
        if self._original_open is not None and isValid(self._original_open):
            self._original_open.cancel()
        self._original_open = None

    def _selected(self, *_args):
        if self.request is None:
            return
        parser_id = self.format_selector.currentData()
        candidate = next((item for item in self.request.recognition.candidates if item.parser_id == parser_id), None)
        self.rows.setRowCount(0)
        self.import_button.setEnabled(candidate is not None and not self.request.decided.is_set())
        set_field_state(self.import_button, "ready" if self.import_button.isEnabled() else "neutral")
        if candidate is None:
            self.attention_notice.hide()
            self.format_label.setText("Supported format could not be resolved automatically.")
            self.interpretation.setText(
                "This file matches more than one supported format for the chosen accounts. Nothing has been imported. "
                "Check the institution and account product, or use another supported export. Column meanings are fixed by each declared format."
            )
            self.mapping.clear()
            self.details.clear()
            self.details_toggle.hide()
            self.retained_format_notice.hide()
            set_status(
                self.status,
                "blocked",
                "Import is blocked until one supported format can be recognized. Skip this file or cancel the remaining queue.",
            )
            return
        self.details_toggle.show()
        self.retained_format_notice.show()
        warnings = getattr(candidate, "warnings", ())
        # Older hand-built callers may supply codes only. Keep them visible and
        # specific without promoting them into authoritative evidence.
        represented = {warning.code for warning in warnings}
        warnings = (
            *warnings,
            *(
                ImportWarning(code, "requires_review", code.replace("_", " "))
                for code in candidate.attention_codes
                if code not in represented
            ),
        )
        warning_sections = []
        for classification, label in (("requires_review", "Requires review"), ("informational", "Informational")):
            reasons = tuple(
                dict.fromkeys(warning.message for warning in warnings if warning.classification == classification)
            )
            if reasons:
                warning_sections.append(label + ": " + "; ".join(reasons) + ".")
        self.attention_notice.setText("\n".join(warning_sections))
        self.attention_notice.setVisible(bool(warning_sections))
        statement = self.request.recognition.suffix == ".pdf"
        self.retained_format_notice.setText(
            "Check statement dates and amounts against your original. This import keeps the recognized statement format; "
            "changing it afterward is not supported yet. Cancel before importing if the preview does not match your original."
            if statement
            else "Check the recognized dates and amounts against your original. This import keeps the recognized format; "
            "changing it afterward is not supported yet. Cancel before importing if the preview does not match your original."
        )
        if len(self.request.recognition.candidates) == 1:
            date_role = (candidate.date_role or "source date").replace("_", " ")
            self.format_label.setText(
                f"CSV {date_role} activity export recognized automatically. "
                "The complete header matches a supported format and all rows validated."
            )
            if statement:
                self.format_label.setText(
                    "PDF statement recognized by one signed route. Check the extracted rows and account assignments before importing."
                )
        self.interpretation.setText(
            f"From document: {institution_label(candidate.institution_key, self.institutions)} · "
            f"{candidate.account_kind or 'Account type not identified'} · {candidate.row_count} activity rows\n"
            f"{'Statement period' if statement else 'Activity dates'}: {_date(candidate.start, statement=statement)} to {_date(candidate.end, statement=statement)}. "
            f"Showing the first {len(candidate.preview_rows)} rows; this is not a reviewed spending total."
        )
        self.rows.setRowCount(len(candidate.preview_rows))
        for index, row in enumerate(candidate.preview_rows):
            values = (
                _date(row.date, statement=statement),
                row.source_account or "Not identified in source",
                row.description or "Not printed",
                _money(row.amount.minor),
                _money(row.running_balance.minor) if row.running_balance else "Not printed",
                "; ".join(_location(location) for location in row.locations),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                raw_detail = (
                    f"Raw date: {row.date.raw!r}; provenance: {row.date.provenance}."
                    if column == 0
                    else f"Raw amount: {row.amount.raw!r}; provenance: {row.amount.provenance}."
                    if column == 3
                    else f"Raw balance: {row.running_balance.raw!r}; provenance: {row.running_balance.provenance}."
                    if column == 4 and row.running_balance
                    else ""
                )
                item.setToolTip(value + ("\n" + raw_detail if raw_detail else ""))
                if column in (3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.rows.setItem(index, column, item)
        self.mapping.setText(
            "Statement preview · Amounts use the normalized financial direction. Printed values and source locations are available in row details."
            if statement
            else "Declared column mapping: "
            + " · ".join(
                f"{_MAPPING_LABELS.get(role, role.replace('_', ' '))} ← {column}"
                for role, column in candidate.column_mapping
            )
            + f"\nDate role: {(candidate.date_role or 'not specified').replace('_', ' ')} · Date format: {_date_format(candidate.date_format)} · "
            f"Money format: {_money_format(candidate.money_format)}."
        )
        self.details.setPlainText(
            f"Format: {candidate.parser_id}\nRevision: {candidate.revision}\nDefinition SHA-256: {candidate.definition_sha256}\n"
            f"Source SHA-256: {self.request.recognition.source_sha256}\n"
            + (f"Header: {', '.join(candidate.header)}\n" if not statement else "")
            + f"Engine: {candidate.engine_version}; extractor: {candidate.extractor_version}\n\n"
            + "\n".join(
                f"{'Requires review' if warning.classification == 'requires_review' else 'Informational'} [{warning.code}]: {warning.message}"
                + ("; " + "; ".join(_location(location) for location in warning.locations) if warning.locations else "")
                + (
                    f"; {warning.occurrence_count} occurrences (showing up to 16 source locations)"
                    if warning.occurrence_count > 1
                    else ""
                )
                for warning in warnings
            )
            + ("\n\n" if warnings else "")
            + "\n".join(
                f"Row {index + 1}: raw date {row.date.raw!r} → {row.date.iso or 'Unknown'} ({row.date.provenance}); "
                f"raw amount {row.amount.raw!r} → {_money(row.amount.minor)} ({row.amount.provenance}); "
                + "; ".join(_location(location) for location in row.locations)
                for index, row in enumerate(candidate.preview_rows)
            )
        )
        set_status(
            self.status,
            "ready",
            "Unique signed statement route validated · Not imported. Extracted source evidence is separate from reviewed spending."
            if statement
            else "Format validated · Not imported. Import retains evidence only; account and transaction review remain separate.",
        )

    def update_queue(self, completed):
        self.queue_status.setVisible(self.request is not None and self.request.total > 1)
        if not completed:
            self.queue_status.setText(
                "No files completed yet. Cancel stops the remaining queue; existing saved documents stay available."
            )
            return
        counts = {
            status: sum(item.status == status for item in completed)
            for status in ("imported", "already_imported", "skipped", "failed")
        }
        last = completed[-1]
        self.queue_status.setText(
            f"Completed: {counts['imported']} imported · {counts['already_imported']} already saved · "
            f"{counts['skipped']} skipped · {counts['failed']} failed. "
            f"Last: {last.path.name} — {last.status.replace('_', ' ')}. Cancel retains completed imports."
        )

    def _import(self):
        if self.request is None or not self.import_button.isEnabled():
            return
        self.request.finish(self.request.recognition.selection(self.format_selector.currentData()))
        self._waiting("Importing the selected interpretation… Completed files remain saved if you cancel later.")

    def _skip(self):
        if self.request is None or self.request.decided.is_set():
            return
        self.request.finish(None)
        self._waiting("File skipped. Waiting for the next document…")

    def _waiting(self, text):
        self._cancel_original()
        self.original_button.setEnabled(False)
        self.import_button.setEnabled(False)
        set_field_state(self.import_button, "neutral")
        self.skip_button.setEnabled(False)
        self.format_selector.setEnabled(False)
        set_status(self.status, "loading", text)

    def wait_for_next(self, index, total, path):
        self.file_context.setText(f"File {index} of {total}: {path.name} · Recognizing document…")
        self.interpretation.setText("Reading the next document. No interpretation is ready to review yet.")
        self.rows.setRowCount(0)
        self.mapping.clear()
        self.details.clear()
        self.format_selector.hide()
        self._waiting("Checking the next document… Cancel retains completed imports.")

    def finish_queue(self):
        self._cancel_original()
        self._finished = True
        self.request = None
        self.hide()

    def reject(self):
        if not self._finished:
            self.cancel_remaining.emit()
            if self.request is not None:
                self.request.finish(None)
            self._waiting("Cancelling remaining imports… Completed documents are retained.")

    def closeEvent(self, event):
        if self._finished:
            event.accept()
        else:
            self.reject()
            event.ignore()

"""Read-only developer preview of one saved 2.0 source evidence snapshot."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
)
from shiboken6 import isValid

from parsetrail.core.source_evidence import ObservationEvidence, SourceDisposition, StatementPayload
from parsetrail.core.v2_profile_store import SavedImport, V2ProfileStore
from parsetrail.core.v2_review_dates import posting_date_candidate
from parsetrail.gui.v2_original_document import open_saved_original


def _money(minor: int | None) -> str:
    if minor is None:
        return "Unknown"
    sign = "-" if minor < 0 else ""
    amount = abs(minor)
    return f"{sign}${amount // 100:,}.{amount % 100:02d}"


def _location(location) -> str:
    if location.kind == "pdf_line":
        return f"Page {location.page}, line {location.line}"
    if location.kind == "pdf_table_row":
        return f"Page {location.page}, table row {location.row}"
    if location.kind == "pdf_chars":
        return f"Page {location.page}, characters {location.start}–{location.end}"
    if location.kind == "pdf_annotation":
        return f"Page {location.page}, annotation {location.ordinal}"
    if location.kind in {"csv_cell", "xlsx_cell"}:
        prefix = f"{location.sheet}, " if location.kind == "xlsx_cell" else ""
        return f"{prefix}row {location.row}, column {location.column}"
    prefix = f"{location.sheet}, " if location.kind == "xlsx_row" else ""
    return f"{prefix}row {location.row}"


class _RowsModel(QAbstractTableModel):
    HEADERS = (
        "Source date",
        "Date role",
        "Posting candidate",
        "Source account",
        "Description",
        "Amount",
        "Running balance",
        "Location",
    )

    def __init__(self, rows: tuple[ObservationEvidence, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.ToolTipRole}:
            return None
        row = self.rows[index.row()]
        location = _location(row.fragments[0].location)
        source_date = row.transaction_date or row.date
        source_role = (
            "Transaction date" if row.transaction_date is not None else row.date_role.replace("_", " ").title()
        )
        date_suffix = {
            "observed": "",
            "derived": " (derived from source)",
            "assumed": " (assumed)",
            "unknown": "",
        }[source_date.provenance]
        posting = posting_date_candidate(row)
        values = (
            (source_date.iso or "Unknown") + date_suffix,
            source_role,
            (
                f"{posting.iso} ({posting.provenance})"
                if posting is not None and posting.provenance == "assumed"
                else posting.iso
                if posting is not None
                else "Not available"
            ),
            row.source_account or "Not identified by source",
            row.description.text or "Description not printed",
            _money(row.amount.minor),
            _money(row.running_balance.minor) if row.running_balance is not None else "Not printed",
            location,
        )
        return values[index.column()]


class _DispositionsModel(QAbstractTableModel):
    HEADERS = ("Reason", "Location", "Source text")

    def __init__(self, dispositions: tuple[SourceDisposition, ...], parent=None):
        super().__init__(parent)
        self.dispositions = dispositions

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.dispositions)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.ToolTipRole}:
            return None
        item = self.dispositions[index.row()]
        values = (item.code.replace("_", " "), _location(item.location), " | ".join(item.raw_values))
        value = values[index.column()]
        return value[:240] + "…" if role == Qt.DisplayRole and len(value) > 240 else value[:1000]


class V2EvidencePreview(QDialog):
    """Inspect saved facts in a one-shot view with no write or posting control."""

    def __init__(self, saved: SavedImport, parent=None):
        super().__init__(parent)
        self.saved = saved
        evidence = saved.evidence
        payload = evidence.payload
        rows = (
            tuple(row for account in payload.accounts for row in account.rows)
            if isinstance(payload, StatementPayload)
            else payload.rows
        )
        self.setWindowTitle("Source evidence")
        self.resize(1100, 700)
        layout = QVBoxLayout(self)
        heading = QLabel("Statement evidence" if isinstance(payload, StatementPayload) else "Activity export evidence")
        heading.setStyleSheet("font-size: 16px; font-weight: 600")
        layout.addWidget(heading)
        accounts = tuple(dict.fromkeys(row.source_account for row in rows if row.source_account))
        source_account = (
            ", ".join(value if len(value) <= 80 else value[:77] + "…" for value in accounts[:3])
            + (f" · {len(accounts) - 3} more accounts" if len(accounts) > 3 else "")
            if accounts
            else "Account not identified by the source"
        )
        start = payload.start if isinstance(payload, StatementPayload) else payload.activity_start
        end = payload.end if isinstance(payload, StatementPayload) else payload.activity_end

        def display_date(value):
            return (value.iso or "Unknown") + (f" ({value.provenance})" if value.provenance != "observed" else "")

        context = QLabel(f"{source_account} · {display_date(start)} to {display_date(end)} · {len(rows)} source rows")
        context.setTextFormat(Qt.PlainText)
        context.setWordWrap(True)
        layout.addWidget(context)
        introduction = QLabel(
            "Saved source evidence · Inspect the rows or open the original. No entries are posted here."
        )
        introduction.setWordWrap(True)
        layout.addWidget(introduction)
        coverage = payload.capture_verified if isinstance(payload, StatementPayload) else payload.coverage_verified
        unclassified_money = sum(item.code == "unclassified_monetary_line" for item in payload.dispositions)
        unclassified_note = f" · Unclassified dollar lines: {unclassified_money}" if unclassified_money else ""
        unclassified_page_text = tuple(item for item in payload.dispositions if item.code == "unclassified_page_text")
        if unclassified_page_text:
            unclassified_note += f" · Unclassified page text lines: {len(unclassified_page_text)}"
        balance = (
            (
                "Printed balance equation passed"
                if payload.independent_balance_verified
                else "No independent balance check"
            )
            if isinstance(payload, StatementPayload)
            else "Activity export has no statement balance check"
        )
        summary = QLabel(
            f"{'Source capture checked' if coverage else 'Source capture needs review'} · {balance}{unclassified_note}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        assumed = sum(
            posting_date_candidate(row) is not None and posting_date_candidate(row).provenance == "assumed"
            for row in rows
        )
        if assumed:
            date_warning = QLabel(f"{assumed} posting date(s) are estimated. Review their dates before posting.")
            date_warning.setWordWrap(True)
            layout.addWidget(date_warning)
        self.details_button = QPushButton("Evidence details")
        self.details_button.setCheckable(True)
        self.details = QPlainTextEdit(
            f"Parser: {evidence.parser_id} · Definition: {evidence.definition_revision}\n"
            f"Source SHA-256: {evidence.source_sha256}\n"
            f"Source accounts: {', '.join(accounts) if accounts else 'Not identified'}\n"
            f"Other source lines: {len(payload.dispositions)}. Assumed posting dates are parser guesses; "
            "Settings controls whether review may use them. Source dates and original bytes stay unchanged."
        )
        self.details.setReadOnly(True)
        self.details.setTabChangesFocus(True)
        self.details.setMaximumHeight(120)
        self.details.hide()
        self.details_button.toggled.connect(self.details.setVisible)
        tabs = QTabWidget()
        self.rows_model = _RowsModel(rows, self)
        self.dispositions_model = _DispositionsModel(payload.dispositions, self)
        models = [("Observations", self.rows_model), ("Other source lines", self.dispositions_model)]
        if unclassified_page_text:
            self.unclassified_text_model = _DispositionsModel(unclassified_page_text, self)
            models.append(("Unclassified page text", self.unclassified_text_model))
        for title, model in models:
            view = QTableView()
            view.setModel(model)
            view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            header = view.horizontalHeader()
            header.setStretchLastSection(False)
            for column in range(model.columnCount()):
                header.setSectionResizeMode(
                    column,
                    QHeaderView.ResizeMode.Stretch
                    if column == (4 if model is self.rows_model else model.columnCount() - 1)
                    else QHeaderView.ResizeMode.ResizeToContents,
                )
            tabs.addTab(view, title)
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.addButton(self.details_button, QDialogButtonBox.ActionRole)
        self.original_button = buttons.addButton("Open original…", QDialogButtonBox.ActionRole)
        self.original_button.setToolTip(
            "Read the saved original in ParseTrail's built-in viewer without creating a temporary file."
        )
        self.original_button.clicked.connect(self._open_original)
        buttons.rejected.connect(self.reject)
        layout.addWidget(self.details)
        layout.addWidget(buttons)
        self.original_status = QLabel()
        self.original_status.setWordWrap(True)
        layout.addWidget(self.original_status)

    def _open_original(self) -> None:
        self.original_button.setEnabled(False)
        self.original_status.setText("Preparing original document…")
        self.original_open = open_saved_original(self.saved, self)
        self.original_open.status_changed.connect(self.original_status.setText)
        self.original_open.finished.connect(self._original_finished)

    def _original_finished(self, _success: bool) -> None:
        self.original_button.setEnabled(True)

    def _cancel_original(self) -> None:
        if hasattr(self, "original_open"):
            self.original_open.cancel()

    def close(self) -> bool:
        self._cancel_original()
        closed = super().close()
        if closed and isValid(self):
            self.deleteLater()
        return closed

    def closeEvent(self, event) -> None:
        self._cancel_original()
        super().closeEvent(event)
        if event.isAccepted() and isValid(self):
            self.deleteLater()

    def done(self, result: int) -> None:
        self._cancel_original()
        super().done(result)
        if isValid(self):
            self.deleteLater()


def preview_saved_source(profile: Path, source_sha256: str, *, parent=None) -> V2EvidencePreview:
    """Load a saved snapshot through SQLite's read-only mode."""
    with V2ProfileStore.open(profile, read_only=True) as store:
        saved = store.load_import(source_sha256)
    return V2EvidencePreview(saved, parent)

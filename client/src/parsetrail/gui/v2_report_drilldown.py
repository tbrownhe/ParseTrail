"""Read-only entry and immutable-source inspection for reviewed reports."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
)

from parsetrail.core.v2_builtin_categories import category_labels
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_report_drilldown import ReviewedEntryDrilldown, read_reviewed_entry_drilldown
from parsetrail.gui.v2_document_browser import document_period, document_title
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview, _money
from parsetrail.gui.v2_form_state import install_initial_focus
from parsetrail.gui.v2_gui_lifetime import exec_disposable


class _EntryModel(QAbstractTableModel):
    HEADERS = ("Accounting date", "Description", "Selected account effect", "Asset/liability accounts")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result: ReviewedEntryDrilldown | None = None

    def replace(self, result):
        self.beginResetModel()
        self.result = result
        self.endResetModel()

    def rowCount(self, _parent=QModelIndex()):
        return len(self.result.entries) if self.result else 0

    def columnCount(self, _parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        return self.HEADERS[section] if role == Qt.DisplayRole and orientation == Qt.Horizontal else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self.result is None or role != Qt.DisplayRole:
            return None
        entry = self.result.entries[index.row()]
        accounts = {item.id: item for item in self.result.report.accounts}
        values = (
            entry.posting_date.isoformat(),
            entry.description,
            _money(self.result.effect_minor(entry)),
            ", ".join(
                dict.fromkeys(
                    accounts[p.account_id].name
                    for p in entry.postings
                    if accounts[p.account_id].kind in {"asset", "liability"}
                )
            ),
        )
        return values[index.column()]


class V2ReviewedEntryDrilldown(QDialog):
    source_review_requested = Signal(str, str)

    def __init__(
        self,
        profile: Path,
        account_id: str,
        *,
        start: date,
        end: date,
        expected_total_minor=None,
        parent=None,
        review_available=False,
    ):
        super().__init__(parent)
        install_initial_focus(self)
        self.profile, self.account_id = profile, account_id
        self.start, self.end = start, end
        self.expected_total_minor = expected_total_minor
        self._source_labels = {}
        self._review_targets = {}
        self.drilldown: ReviewedEntryDrilldown | None = None
        self.setWindowTitle("Current reviewed journal entries")
        self.resize(1040, 700)
        layout = QVBoxLayout(self)
        self.scope = QLabel()
        self.scope.setTextFormat(Qt.PlainText)
        self.scope.setWordWrap(True)
        self.scope.setStyleSheet("font-weight: 600; font-size: 16px")
        layout.addWidget(self.scope)
        self.total = QLabel()
        self.total.setWordWrap(True)
        layout.addWidget(self.total)
        self.qualification = QLabel()
        self.qualification.setWordWrap(True)
        layout.addWidget(self.qualification)
        self.stale_note = QLabel()
        self.stale_note.setWordWrap(True)
        layout.addWidget(self.stale_note)
        splitter = QSplitter(Qt.Vertical)
        self.model = _EntryModel(self)
        self.table = QTableView()
        self.table.setTabKeyNavigation(False)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for column in (0, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        splitter.addWidget(self.table)
        self.entry_summary = QLabel()
        self.entry_summary.setWordWrap(True)
        self.entry_summary.setTextFormat(Qt.PlainText)
        self.entry_summary.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(self.entry_summary)
        self.show_details = QCheckBox("Posting and evidence details")
        layout.addWidget(self.show_details)
        self.report_limits = QLabel()
        self.report_limits.setWordWrap(True)
        layout.addWidget(self.report_limits)
        self.report_limits.hide()
        self.show_details.toggled.connect(self.report_limits.setVisible)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter.addWidget(self.details)
        self.details.hide()
        self.show_details.toggled.connect(self.details.setVisible)
        splitter.setSizes([320, 200])
        layout.addWidget(splitter)
        # The transaction table leads; selected context and optional proof follow.
        layout.removeWidget(self.entry_summary)
        layout.removeWidget(self.show_details)
        layout.removeWidget(self.report_limits)
        layout.addWidget(self.entry_summary)
        layout.addWidget(self.show_details)
        layout.addWidget(self.report_limits)
        sources = QHBoxLayout()
        sources.addWidget(QLabel("Source evidence"))
        self.source = QComboBox()
        self.source.setAccessibleName("Supporting source document")
        self.source.setMinimumContentsLength(24)
        self.source.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.source.currentIndexChanged.connect(self._update_review_target)
        sources.addWidget(self.source, 1)
        self.preview = QPushButton("Preview source")
        self.preview.clicked.connect(self._preview)
        sources.addWidget(self.preview)
        self.review_source_button = QPushButton("Review / correct source row")
        self.review_source_button.setEnabled(False)
        self.review_source_button.setAccessibleName("Review or correct selected entry at its source row")
        self.review_source_button.clicked.connect(self._review_source)
        self.review_source_button.setVisible(review_available)
        sources.addWidget(self.review_source_button)
        layout.addLayout(sources)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.refresh_button = buttons.addButton("Refresh entries", QDialogButtonBox.ActionRole)
        self.refresh_button.clicked.connect(self.refresh)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        try:
            result = read_reviewed_entry_drilldown(self.profile, self.account_id, start=self.start, end=self.end)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.drilldown = None
            self.model.replace(None)
            self.scope.setText(f"Entries are unavailable: {exc}")
            self.scope.setToolTip("")
            self.total.clear()
            self.qualification.clear()
            self.report_limits.clear()
            self.stale_note.clear()
            self._selected()
            return
        self.drilldown = result
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                self._source_labels = {
                    summary.source_sha256: f"{document_title(summary)} · {document_period(summary)}"
                    for summary in store.document_summaries()
                }
        except (ProfileFormatError, sqlite3.Error, OSError):
            self._source_labels = {}
        self.model.replace(result)
        report = result.report
        labels = category_labels((account.id, account.name, account.kind) for account in report.accounts)
        self.scope.setToolTip(f"Account ID: {result.account.id}")
        through = report.end - timedelta(days=1)
        self.scope.setText(f"{labels[result.account.id]} · {report.start:%b %d, %Y}–{through:%b %d, %Y} · USD")
        count = len(result.entries)
        self.total.setText(
            f"{count} reviewed {'entry' if count == 1 else 'entries'} · "
            f"Net selected account effect {_money(result.total_minor)}"
        )
        self.qualification.setText(
            f"{report.activity_rows_without_full_allocation} imported row(s) pending across all dates "
            "(may include repeats). Source coverage may be incomplete. Opening entries excluded."
        )
        self.report_limits.setText(
            "Active reviewed non-opening entries only; corrections restate the current books. "
            "Positive follows the selected account's natural direction. "
            f"Across the whole profile and all dates, {report.activity_rows_without_full_allocation} activity source "
            f"row(s) from {report.sources_with_incomplete_activity} source(s) lack a full allocation. "
            f"Across this report period and profile, {report.excluded_unreviewed_entries} unreviewed journal "
            f"entry(s) and {report.excluded_opening_entries} opening-entry record(s) were excluded. "
            "Pending rows may include supporting repeats. "
            "These rows do not establish complete spending/income, source capture, coverage or reconciled balances."
        )
        self.stale_note.setText(
            "Reviewed entries changed since the parent summary was loaded. This view shows the current rows; refresh that summary too."
            if self.expected_total_minor is not None and result.total_minor != self.expected_total_minor
            else ""
        )
        if result.entries:
            self.table.selectRow(0)
        else:
            self._selected()
            self.entry_summary.setText("No reviewed entries in this period. Pending evidence is not zero activity.")
            self.details.setPlainText(
                "No active reviewed entries in this account and period. Pending evidence is not zero activity."
            )

    def _selected(self, *_args):
        self._review_targets = {}
        self.review_source_button.setEnabled(False)
        self.source.clear()
        self.preview.setEnabled(False)
        self.details.clear()
        self.entry_summary.clear()
        index = self.table.currentIndex()
        if self.drilldown is None or not index.isValid() or index.row() >= len(self.drilldown.entries):
            return
        result, entry = self.drilldown, self.drilldown.entries[index.row()]
        accounts = {account.id: account for account in result.report.accounts}
        reason = entry.reason if len(entry.reason) <= 180 else entry.reason[:180] + "…"
        self.entry_summary.setText(
            f"{entry.description} · Accounting date {entry.posting_date}\nSaved reason: {reason}"
        )
        self.entry_summary.setToolTip(entry.reason)
        labels = category_labels((account.id, account.name, account.kind) for account in accounts.values())
        source_rows = dict(result.report.source_rows)
        lines = [
            f"{entry.description}\nAccounting date: {entry.posting_date}; origin: {entry.origin}.",
            f"Review reason: {entry.reason}",
            "Stored posting lines (debits and credits):",
        ]
        for posting in entry.postings:
            account = accounts[posting.account_id]
            side = "Debit" if posting.amount_minor > 0 else "Credit"
            lines.append(
                f"  {labels[account.id]} ({account.kind}, ID {account.id}): {side} {_money(abs(posting.amount_minor))}"
            )
        derived_sources = {
            link.derived_observation_id: link
            for link in result.report.loan_source_links
            if link.derived_observation_id is not None
        }
        # A multi-account document may support both sides of one transfer. Keep
        # the selected financial account's row ahead of its counterpart.
        source_postings = sorted(entry.postings, key=lambda posting: posting.account_id != result.account.id)
        source_ids = dict.fromkeys(
            (
                derived_sources[a.observation_id].source_sha256
                if a.observation_id in derived_sources
                else source_rows[a.observation_id]
            )
            for p in source_postings
            for a in p.allocations
        )
        for posting in source_postings:
            for allocation in posting.allocations:
                row_id = allocation.observation_id
                if row_id in derived_sources:
                    link = derived_sources[row_id]
                    self._review_targets.setdefault(link.source_sha256, link.row_id)
                elif row_id in source_rows:
                    self._review_targets.setdefault(source_rows[row_id], row_id)
        loan_event = next((event for event in result.report.loan_events if event.event_id == entry.event_id), None)
        if loan_event is not None:
            if loan_event.manifest.bank is not None:
                source_ids[loan_event.manifest.bank.source_sha256] = None
            lines.append(
                (
                    "\nReviewed whole loan payment; "
                    if loan_event.manifest.bank is not None
                    else "\nReviewed lender-side payment; paying-account resolution is tracked separately in Transfers. "
                )
                + "These component facts are provenance, not additional money. "
                f"Reference: {loan_event.reference}; event state: {loan_event.status}."
            )
            for link in result.report.loan_source_links:
                if link.event_id != loan_event.event_id:
                    continue
                source_ids[link.source_sha256] = None
                if link.entry_key == entry.key:
                    self._review_targets[link.source_sha256] = link.row_id
                else:
                    self._review_targets.setdefault(link.source_sha256, link.row_id)
                lines.append(
                    f"  Raw source row {link.row_id}: signed amount {_money(link.raw_amount_minor)}; "
                    f"principal debit {_money(link.principal_minor)}; interest expense {_money(link.interest_minor)}.\n"
                    f"  Source activity date {link.activity_date}; accounting date {link.effective_date} "
                    f"({link.date_provenance}, separately reviewed). Principal-component scope. "
                    f"Captured loan account {link.proof.account_name} (ID {link.account_id}).\n"
                    + (
                        f"  Derived financial observation {link.derived_observation_id} uses printed principal "
                        f"x {link.proof.sign_factor}; it is separate from whole raw payment use."
                        if link.derived_observation_id is not None
                        else "  No principal financial observation/posting: this is an evidenced interest-only component."
                    )
                )
        for source_id in source_ids:
            self.source.addItem(self._source_labels.get(source_id, f"Source {source_id[:16]}…"), source_id)
            self.source.setItemData(self.source.count() - 1, source_id, Qt.ToolTipRole)
        self.preview.setEnabled(bool(source_ids))
        self._update_review_target()
        corrections, retirements = result.entry_history(entry)
        lines.append("\nRelated correction/withdrawal links may be outside this report period:")
        if not corrections and not retirements:
            lines.append("  None identified in this selection.")
        for row in corrections:
            lines.append(
                f"  Correction: {row.reason} (review saved at {row.created_at})\n    {row.original_key} → {row.replacement_key}"
            )
        for row in retirements:
            lines.append(
                f"  Withdrawn: {row.reason} (review saved at {row.created_at})\n    {row.original_key} → {row.reversal_key}"
            )
        related_entries = result.related_entries(entry)
        if related_entries:
            lines.append("\nRelated stored journal records (provenance only; not added to the total above):")
            for related in related_entries:
                lines.append(f"  {related.posting_date.isoformat()}: {related.description}; {related.reason}")
                for posting in related.postings:
                    account = accounts[posting.account_id]
                    side = "Debit" if posting.amount_minor > 0 else "Credit"
                    lines.append(
                        f"    {labels[account.id]} (ID {account.id}): {side} {_money(abs(posting.amount_minor))}"
                    )
        lines.append(f"\nEntry reference: {entry.key}\nEvent reference: {entry.event_id}")
        self.details.setPlainText("\n".join(lines))

    def _update_review_target(self, *_args):
        if hasattr(self, "review_source_button"):
            self.review_source_button.setEnabled(self.source.currentData() in self._review_targets)

    def _review_source(self):
        source_id = self.source.currentData()
        row_id = self._review_targets.get(source_id)
        if row_id is None:
            return
        # Close the inspection first; the workspace owns guarded navigation and
        # the existing explicit correction/owning-event confirmation workflows.
        self.accept()
        self.source_review_requested.emit(source_id, row_id)

    def _preview(self):
        source_id = self.source.currentData()
        if source_id is None:
            return
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                saved = store.load_import(source_id)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Source preview unavailable", str(exc))
            return
        exec_disposable(V2EvidencePreview(saved, self))

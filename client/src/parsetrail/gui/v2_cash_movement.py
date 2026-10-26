"""Qualified cash movement over a user-selected financial asset scope."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_builtin_categories import category_labels
from parsetrail.core.v2_cash_movement import MOVEMENT_LABELS, cash_account_labels, read_cash_movement
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.gui.v2_cash_activity_review import _money
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
from parsetrail.gui.v2_report_drilldown import V2ReviewedEntryDrilldown


def _table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill(table, rows, number_columns=()):
    table.blockSignals(True)
    table.setRowCount(len(rows))
    table.clearSelection()
    table.setCurrentCell(-1, -1)
    for index, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            if column in number_columns:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(index, column, item)
    table.blockSignals(False)


class V2CashMovementDialog(QDialog):
    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.report = None
        self.setWindowTitle("2.0 reviewed cash movement")
        self.resize(1100, 780)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choose the financial asset accounts you want to treat as cash in this report. "
            "No accounts are selected automatically. This reports active reviewed journal movement, "
            "with transfers and card payments separate from income and expenses."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        scope_row = QHBoxLayout()
        self.accounts = QListWidget()
        self.accounts.setMaximumHeight(100)
        scope_row.addWidget(self.accounts, 1)
        controls = QWidget()
        form = QFormLayout(controls)
        today = date.today()
        self.start = QDateEdit(QDate(today.year, today.month, 1))
        self.end = QDateEdit(QDate(today.year + (today.month == 12), today.month % 12 + 1, 1))
        for control in (self.start, self.end):
            control.setCalendarPopup(True)
            control.setDisplayFormat("yyyy-MM-dd")
        form.addRow("From (inclusive)", self.start)
        form.addRow("To (exclusive)", self.end)
        reload_accounts = QPushButton("Reload account choices")
        reload_accounts.clicked.connect(self._reload_accounts)
        form.addRow(reload_accounts)
        scope_row.addWidget(controls)
        layout.addLayout(scope_row)
        self.total = QLabel()
        self.total.setWordWrap(True)
        layout.addWidget(self.total)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.summary = _table(("Reviewed purpose", "Records with purpose", "Net selected-scope movement"))
        self.entries = _table(
            ("Accounting date", "Reviewed purpose", "Net selected scope", "Description", "Selected accounts")
        )
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.summary)
        splitter.addWidget(self.entries)
        splitter.addWidget(self.details)
        splitter.setSizes([130, 210, 140])
        layout.addWidget(splitter, 1)
        source_row = QHBoxLayout()
        self.sources = QComboBox()
        source_row.addWidget(self.sources, 1)
        self.preview = QPushButton("Preview selected source")
        self.preview.clicked.connect(self._preview)
        source_row.addWidget(self.preview)
        self.inspect_account = QComboBox()
        source_row.addWidget(self.inspect_account, 1)
        self.inspect = QPushButton("Inspect account entries…")
        self.inspect.clicked.connect(self._inspect)
        source_row.addWidget(self.inspect)
        layout.addLayout(source_row)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        refresh = buttons.addButton("Refresh movement", QDialogButtonBox.ActionRole)
        refresh.clicked.connect(self.refresh)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.accounts.itemChanged.connect(self.refresh)
        self.start.dateChanged.connect(self.refresh)
        self.end.dateChanged.connect(self.refresh)
        self.entries.itemSelectionChanged.connect(self._selected)
        self._reload_accounts()

    def _selected_ids(self):
        return tuple(
            self.accounts.item(index).data(Qt.UserRole)
            for index in range(self.accounts.count())
            if self.accounts.item(index).checkState() == Qt.Checked
        )

    def _clear(self, message):
        self.report = None
        _fill(self.summary, ())
        _fill(self.entries, ())
        self.details.clear()
        self.sources.clear()
        self.inspect_account.clear()
        self.preview.setEnabled(False)
        self.inspect.setEnabled(False)
        self.total.setText(message)
        self.scope.clear()

    def _reload_accounts(self):
        selected = set(self._selected_ids())
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                financial = store.financial_accounts()
                accounts = tuple(account for account in financial if account.kind == "asset")
                labels = cash_account_labels(financial)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self._clear(f"Account choices are unavailable: {exc}")
            return
        self.accounts.blockSignals(True)
        self.accounts.clear()
        for account in accounts:
            item = QListWidgetItem(labels[account.id])
            item.setToolTip(f"{labels[account.id]}\nAccount ID: {account.id}")
            item.setData(Qt.UserRole, account.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if account.id in selected else Qt.Unchecked)
            self.accounts.addItem(item)
        self.accounts.blockSignals(False)
        self.refresh()

    def refresh(self, *_args):
        selected = self._selected_ids()
        if not selected:
            self._clear("Choose one or more cash asset accounts. No cash scope has been established.")
            return
        try:
            report = read_cash_movement(
                self.profile, selected, start=self.start.date().toPython(), end=self.end.date().toPython()
            )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self._clear(f"Reviewed cash movement is unavailable: {exc}")
            return
        self.report = report
        self.total.setText(
            f"Net reviewed selected-account movement: {_money(report.total_minor)}. "
            "Positive increases selected asset value; negative decreases it. "
            "Within-scope transfers can have dated movement while money is in transit."
        )
        unknown = sum(row.classification == "unclassified" for row in report.rows)
        journal = report.journal
        self.scope.setText(
            f"{journal.start} inclusive to {journal.end} exclusive, USD; {len(report.rows)} selected journal record(s), "
            f"{report.outside_scope_entries} reviewed record(s) outside scope; {unknown} selected record(s) unclassified. "
            f"Across the whole profile and all dates, {journal.activity_rows_without_full_allocation} activity row(s) "
            f"from {journal.sources_with_incomplete_activity} source(s) lack full allocation. "
            f"{journal.excluded_unreviewed_entries} unreviewed and {journal.excluded_opening_entries} opening record(s) "
            "were excluded in this period. Card purchases alone are not cash movement. "
            "A settlement with a fee can appear in two purpose counts; those counts are not additive. "
            "Unallocated counts may include supporting repeats. Pending evidence and source capture/coverage gaps "
            "prevent a complete or certified cash-flow claim."
        )
        _fill(
            self.summary,
            tuple(
                (MOVEMENT_LABELS[row.classification], row.entry_count, _money(row.amount_minor))
                for row in report.buckets
            ),
            (1, 2),
        )
        names = {account.id: account.name for account in journal.accounts} | dict(report.account_labels)
        _fill(
            self.entries,
            tuple(
                (
                    row.entry.posting_date.isoformat(),
                    MOVEMENT_LABELS[row.classification],
                    _money(row.amount_minor),
                    row.entry.description,
                    ", ".join(names[account] for account, _amount in row.account_effects),
                )
                for row in report.rows
            ),
            (2,),
        )
        self.inspect_account.clear()
        for account in report.selected_accounts:
            self.inspect_account.addItem(names[account.id], account.id)
            self.inspect_account.setItemData(
                self.inspect_account.count() - 1, f"{names[account.id]}\nAccount ID: {account.id}", Qt.ToolTipRole
            )
        self.inspect.setEnabled(bool(report.selected_accounts))
        if report.rows:
            self.entries.selectRow(0)
        else:
            self._selected()

    def _selected(self):
        self.sources.clear()
        self.preview.setEnabled(False)
        self.details.clear()
        index = self.entries.currentRow()
        if self.report is None or not 0 <= index < len(self.report.rows):
            return
        row = self.report.rows[index]
        accounts = {account.id: account for account in self.report.journal.accounts}
        labels = category_labels((account.id, account.name, account.kind) for account in accounts.values())
        labels.update(self.report.account_labels)
        lines = [
            row.entry.description,
            row.event_note,
            f"Review reason: {row.entry.reason}",
            "",
            "Selected-scope components (together equal this record's selected financial movement):",
            *(f"{MOVEMENT_LABELS[part.classification]}: {_money(part.amount_minor)}" for part in row.components),
            "",
            "Stored posting lines:",
        ]
        for posting in row.entry.postings:
            side = "Debit" if posting.amount_minor > 0 else "Credit"
            label = labels.get(posting.account_id, accounts[posting.account_id].name)
            lines.append(f"{label} (ID {posting.account_id}): {side} {_money(abs(posting.amount_minor))}")
        lines.extend(("", f"Entry: {row.entry.key}", f"Event: {row.entry.event_id}"))
        self.details.setPlainText("\n".join(lines))
        source_rows = dict(self.report.journal.source_rows)
        for source in dict.fromkeys(source_rows[a.observation_id] for p in row.entry.postings for a in p.allocations):
            self.sources.addItem(f"Source {source[:16]}…", source)
        self.preview.setEnabled(self.sources.count() > 0)

    def _preview(self):
        source = self.sources.currentData()
        if source is None:
            return
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                saved = store.load_import(source)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Source preview unavailable", str(exc))
            return
        V2EvidencePreview(saved, self).exec()

    def _inspect(self):
        report, account = self.report, self.inspect_account.currentData()
        if report is None or account is None:
            return
        total = sum(
            amount for row in report.rows for account_id, amount in row.account_effects if account_id == account
        )
        V2ReviewedEntryDrilldown(
            self.profile,
            account,
            start=report.journal.start,
            end=report.journal.end,
            expected_total_minor=total,
            parent=self,
        ).exec()

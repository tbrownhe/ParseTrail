"""Exact category-split editor in a disposable ledger workflow workspace."""

import json
import re
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.ledger import LedgerError, minor_units
from parsetrail.core.ledger_expense_corrections import ExpenseCorrections
from parsetrail.core.money import to_minor_units
from parsetrail.gui.ledger_preview import PreviewPage, money
from parsetrail.gui.ledger_proposal_review import ProposalReviewWindow


def split_amount(text):
    if not re.fullmatch(r"[0-9]{1,17}(?:\.[0-9]{1,2})?", text.strip()):
        raise LedgerError(
            "Enter a positive USD amount with at most two decimal places, without commas or currency symbols."
        )
    amount = to_minor_units(text.strip())
    minor_units(amount)
    return amount


class ExpenseCorrectionDialog(QDialog):
    def __init__(self, service, record, parent=None):
        super().__init__(parent)
        self.service, self.record = service, record
        self.plan, self.result_key = None, None
        self.setWindowTitle("Preview expense/refund correction — disposable copy")
        self.resize(880, 760)
        layout = QVBoxLayout(self)
        entry = record["entry"]
        notice = QLabel(
            f"{entry['posting_date']} · {record['account_name']} · {money(record['amount_minor'])}\n"
            f"{entry['description']}\n"
            "Only expense-category amounts change. The original financial movement, date and evidence remain unchanged.\n"
            + (
                "Refund: positive split amounts below reduce the selected expenses."
                if record["amount_minor"] > 0
                else "Purchase: enter positive split amounts below."
            )
        )
        notice.setTextFormat(Qt.TextFormat.PlainText)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        definitions = {
            cid: json.loads(payload)
            for cid, payload in service.store.connection.execute("SELECT id,payload FROM CategoryDefinitions")
        }
        self.categories = {cid: d["Name"] for cid, d in definitions.items() if d["Type"] == "Expense"}
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Expense category", "Amount (USD)", ""])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 90)
        layout.addWidget(self.table)
        self.add = QPushButton("Add split")
        self.add.setAutoDefault(False)
        self.add.clicked.connect(lambda: self.add_split())
        layout.addWidget(self.add)
        self.total = QLabel()
        layout.addWidget(self.total)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Correction reason (required)")
        self.reason.textChanged.connect(self.invalidate)
        layout.addWidget(self.reason)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        layout.addWidget(self.preview_text)
        buttons = QHBoxLayout()
        self.preview = QPushButton("Preview correction")
        self.apply = QPushButton("Apply correction…")
        self.cancel = QPushButton("Cancel")
        for button in (self.preview, self.apply, self.cancel):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        self.cancel.setDefault(True)
        self.preview.clicked.connect(self.preview_plan)
        self.apply.clicked.connect(self.apply_plan)
        self.cancel.clicked.connect(self.reject)
        layout.addLayout(buttons)
        for category in record["categories"]:
            cid = next((cid for cid in self.categories if f"category:{cid}" == category["account_id"]), None)
            self.add_split(cid, abs(category["amount_minor"]))

    def add_split(self, category_id=None, amount=None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        category = QComboBox()
        for cid, name in sorted(self.categories.items(), key=lambda item: (item[1].casefold(), item[0])):
            category.addItem(f"{name} (#{cid})", cid)
        category.setCurrentIndex(category.findData(category_id) if category_id is not None else -1)
        value = QLineEdit("" if amount is None else f"{amount // 100}.{amount % 100:02d}")
        value.setPlaceholderText("0.00")
        value.setMaxLength(20)
        remove = QPushButton("Remove")
        remove.setAutoDefault(False)
        for column, widget in enumerate((category, value, remove)):
            self.table.setCellWidget(row, column, widget)
        category.currentIndexChanged.connect(self.invalidate)
        value.textChanged.connect(self.invalidate)
        remove.clicked.connect(lambda: self.remove_split(remove))
        self.invalidate()

    def remove_split(self, button):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 2) is button:
                self.table.removeRow(row)
                break
        self.invalidate()

    def invalidate(self, *_):
        self.plan = None
        self.apply.setEnabled(False)
        self.preview_text.clear()
        self.error.clear()
        try:
            total = sum(split_amount(self.table.cellWidget(row, 1).text()) for row in range(self.table.rowCount()))
            expected = abs(self.record["amount_minor"])
            self.total.setText(
                f"Split total {money(total)} · Required {money(expected)} · Remaining {money(expected - total)}"
            )
        except ValueError:
            self.total.setText(
                f"Required total: {money(abs(self.record['amount_minor']))}. Complete each amount in exact cents."
            )

    def preview_plan(self):
        self.plan = None
        self.apply.setEnabled(False)
        self.preview_text.clear()
        try:
            splits = [
                (self.table.cellWidget(row, 0).currentData(), split_amount(self.table.cellWidget(row, 1).text()))
                for row in range(self.table.rowCount())
            ]
            self.plan = self.service.preview(self.record["entry"]["key"], splits, self.reason.text())
        except (ValueError, sqlite3.Error) as exc:
            self.error.setText(str(exc))
            return
        self.error.clear()
        lines = [
            "Current category amounts:",
            *[f"  {c['name']}: {money(c['amount_minor'])}" for c in self.record["categories"]],
            "",
            "Replacement category amounts:",
        ]
        names = {a["id"]: a["name"] for a in self.plan["category_accounts"]}
        lines += [
            f"  {names[p['account_id']]}: {money(p['amount_minor'])}" for p in self.plan["replacement"]["postings"][1:]
        ]
        lines += [
            "",
            f"Financial movement preserved: {money(self.record['amount_minor'])}",
            "Total expense change: $0.00. Only category distribution changes.",
            "The original entry is reversed and a reviewed replacement is posted. Both remain in history.",
            "Previous reconciliation checks become stale.",
            f"Reason: {self.plan['reason']}",
        ]
        self.preview_text.setPlainText("\n".join(lines))
        self.apply.setEnabled(True)

    def confirm(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Apply expense/refund correction")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(
            "Apply this preview in the disposable copy?\n\nThe original journal will be reversed and replaced.\n"
            f"Financial movement: {money(self.record['amount_minor'])} (unchanged)\nReason: {self.plan['reason']}"
        )
        dialog.setDetailedText(self.preview_text.toPlainText())
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return dialog.exec() == QMessageBox.StandardButton.Ok

    def apply_plan(self):
        if self.plan is None or not self.confirm():
            return
        try:
            self.result_key = self.service.apply(self.plan)
        except (LedgerError, sqlite3.Error) as exc:
            self.invalidate()
            self.error.setText(str(exc))
        else:
            self.accept()


class ExpenseCorrectionWindow(QMainWindow):
    def __init__(self, review):
        super().__init__()
        self.review, self.service = review, ExpenseCorrections(review)
        self.setWindowTitle("ParseTrail — Expense correction workflow test (disposable copy)")
        self.resize(1350, 900)
        body = QWidget()
        layout = QVBoxLayout(body)
        notice = QLabel(
            "Workflow test copy — sample decisions do not approve rebuilt books or change the live database.\n"
            "The posted-entry list shows active replacements. Original proposals retain their historical categories."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        controls = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems(["Active", "Superseded", "All"])
        self.reload = QPushButton("Refresh entries")
        self.edit = QPushButton("Edit category split…")
        for widget in (QLabel("Posted entry status"), self.filter, self.reload, self.edit):
            controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)
        self.tabs = QTabWidget()
        self.page = PreviewPage(["Account", "Date", "Description", "Movement", "Categories", "Entry status"], [])
        self.page.table.setColumnWidth(2, 260)
        self.page.table.setColumnWidth(4, 280)
        self.ordinary = ProposalReviewWindow(review)
        self.tabs.addTab(self.page, "Posted expenses and refunds")
        self.tabs.addTab(self.ordinary, "Original proposals")
        layout.addWidget(self.tabs)
        self.setCentralWidget(body)
        self.filter.currentTextChanged.connect(self.render)
        self.reload.clicked.connect(lambda: self.refresh())
        self.edit.clicked.connect(self.edit_entry)
        self.page.table.selectionModel().selectionChanged.connect(self.selection_changed)
        self.tabs.currentChanged.connect(self.tab_changed)
        self.refresh()

    def selected(self):
        rows = self.page.table.selectionModel().selectedRows()
        return self.page.model.records[self.page.proxy.mapToSource(rows[0]).row()] if len(rows) == 1 else None

    def refresh(self, keep=None):
        try:
            entries = self.service.entries()
        except (LedgerError, sqlite3.Error) as exc:
            self.records = []
            self.render()
            self.summary.setText(f"Could not refresh entries: {exc}")
            return
        self.records = []
        for record in entries:
            entry = record["entry"]
            categories = "; ".join(f"{c['name']}: {money(c['amount_minor'])}" for c in record["categories"])
            details = [
                entry["description"],
                f"{record['account_name']} · {entry['posting_date']} · {money(record['amount_minor'])}",
                f"Posting-date provenance: {record['date_provenance']}",
                f"Category amounts: {categories}",
                f"Interpretation reviewed: {'Yes' if record['reviewed'] else 'No'}",
                f"Entry reason: {entry['reason']}",
                f"Entry: {entry['key']}",
                f"Previous entry: {record['previous_key'] or 'None'}",
                f"Replacement: {record['replacement_key'] or 'None'}",
                "Verified source-category history remains preserved separately from current postings.",
            ]
            self.records.append(
                {
                    "record": record,
                    "cells": [
                        record["account_name"],
                        entry["posting_date"],
                        entry["description"],
                        money(record["amount_minor"]),
                        categories,
                        "Active" if record["active"] else "Superseded",
                    ],
                    "details": "\n".join(details),
                }
            )
        self.records.sort(key=lambda r: (r["cells"][1], r["cells"][0], r["record"]["entry"]["key"]), reverse=True)
        active = sum(r["record"]["active"] for r in self.records)
        self.summary.setText(
            f"{active:,} active ordinary entries · {len(self.records) - active:,} superseded entries.\n"
            "Start in Original proposals to accept a test expense/refund, then return here to correct it. Transfers and other account interpretations are outside this editor."
        )
        self.render(keep=keep)

    def render(self, *_args, keep=None):
        state = self.filter.currentText()
        records = [r for r in self.records if state == "All" or r["cells"][-1] == state]
        self.page.model.beginResetModel()
        self.page.model.records = records
        self.page.model.endResetModel()
        self.page.filter(self.page.search.text())
        self.selection_changed()
        if keep:
            for i in range(self.page.proxy.rowCount()):
                index = self.page.proxy.mapToSource(self.page.proxy.index(i, 0)).row()
                if records[index]["record"]["entry"]["key"] == keep:
                    self.page.table.selectRow(i)
                    break

    def selection_changed(self, *_):
        selected = self.selected()
        self.edit.setEnabled(bool(self.tabs.currentIndex() == 0 and selected and selected["record"]["active"]))

    def tab_changed(self, index):
        if index == 0:
            self.refresh()
        else:
            self.ordinary.refresh()
        self.selection_changed()

    def edit_entry(self):
        selected = self.selected()
        if not selected or not self.edit.isEnabled():
            return
        dialog = ExpenseCorrectionDialog(self.service, selected["record"], self)
        dialog.exec()
        self.refresh(keep=dialog.result_key or selected["record"]["entry"]["key"])

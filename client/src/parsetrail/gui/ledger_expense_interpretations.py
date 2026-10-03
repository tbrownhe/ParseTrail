"""Explicit classification of unposted evidence in the disposable review window."""

import sqlite3

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_expense_interpretations import ExpenseInterpretations
from parsetrail.gui.ledger_expense_corrections import ExpenseCorrectionDialog
from parsetrail.gui.ledger_preview import PreviewPage, money


class ExpenseInterpretationDialog(ExpenseCorrectionDialog):
    def __init__(self, service, record, parent=None):
        adapted = {
            **record,
            "entry": {
                "key": record["observation_id"],
                "posting_date": record["posting_date"],
                "description": record["description"],
            },
            "categories": [],
        }
        super().__init__(service, adapted, parent)
        self.setWindowTitle("Preview new expense/refund interpretation — disposable copy")
        self.confirmation_title = "Post expense/refund interpretation"
        kind = "refund" if record["amount_minor"] > 0 else "expense"
        self.notice.setText(
            f"{record['posting_date']} · {record['account_name']} · {money(record['amount_minor'])}\n"
            f"{record['description']}\n"
            f"Explicitly classify this whole movement as an ordinary {kind}. "
            "Choose categories; the app has not determined its accounting meaning.\n"
            "Income, transfers/card payments, loans and asset purchases need separate workflows.\n"
            + (
                "Refund: positive split amounts reduce expenses.\n"
                if kind == "refund"
                else "Enter positive expense split amounts.\n"
            )
            + f"Posting-date provenance: {record['date_provenance']}. Source facts and historical categories are preserved."
        )
        self.reason.setPlaceholderText(
            "Reason for replacing rejected interpretation (required)" if record["proposal"] else "Optional note"
        )
        self.preview.setText("Preview interpretation")
        self.apply.setText("Post interpretation…")
        self.add_split(amount=abs(record["amount_minor"]))

    def preview_lines(self):
        entry = self.plan["entry"]
        names = {a["id"]: a["name"] for a in self.plan["category_accounts"]}
        lines = [
            "New expense-category postings:",
            *[f"  {names[p['account_id']]}: {money(p['amount_minor'])}" for p in entry["postings"][1:]],
            "",
            f"Expense total added to ledger: {money(-self.record['amount_minor'])}",
            f"Financial movement added to ledger: {money(self.record['amount_minor'])}",
            "One balanced, reviewed journal will consume the entire source movement once.",
            "Source amount, account, date and description are unchanged. No prior journal is reversed.",
            f"Posting-date provenance: {self.plan['date_provenance']}",
            "This interpretation does not certify statement balances or coverage.",
            "Previous reconciliation checks become stale.",
            f"Reason: {self.plan['reason']}",
        ]
        if self.plan["proposal"]:
            lines += ["", "Original proposal remains rejected in history:", self.plan["proposal"]["decision"]["reason"]]
        return lines

    def confirm_message(self):
        return (
            "Post this explicit expense/refund interpretation in the disposable copy?\n\n"
            f"Expense total added: {money(-self.record['amount_minor'])}\n"
            f"Financial movement added: {money(self.record['amount_minor'])}\n"
            "Only proceed if expense/refund treatment is intended.\n"
            f"Reason: {self.plan['reason']}"
        )


class ExpenseInterpretationPage(QWidget):
    def __init__(self, review, on_posted, parent=None):
        super().__init__(parent)
        self.service, self.on_posted = ExpenseInterpretations(review), on_posted
        layout = QVBoxLayout(self)
        notice = QLabel(
            "These movements have no posted interpretation. Their presence here does not mean they are expenses.\n"
            "Use this action only for ordinary expenses/refunds. Pending proposals remain in Original proposals; "
            "income, transfers, loans and assets need their own workflows."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        controls = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems(["All", "Unclassified", "Rejected proposal"])
        self.reload = QPushButton("Refresh movements")
        self.interpret = QPushButton("Classify as expense/refund…")
        for widget in (QLabel("Prior interpretation"), self.filter, self.reload, self.interpret):
            controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.page = PreviewPage(
            ["Account", "Date", "Description", "Movement", "Prior interpretation", "Date provenance"], []
        )
        self.page.table.setColumnWidth(2, 280)
        layout.addWidget(self.page)
        self.filter.currentTextChanged.connect(self.render)
        self.reload.clicked.connect(self.refresh)
        self.interpret.clicked.connect(self.edit)
        self.page.table.selectionModel().selectionChanged.connect(self.selection_changed)
        self.refresh()

    def selected(self):
        rows = self.page.table.selectionModel().selectedRows()
        return self.page.model.records[self.page.proxy.mapToSource(rows[0]).row()] if len(rows) == 1 else None

    def refresh(self):
        try:
            records = self.service.inventory()
        except (LedgerError, sqlite3.Error) as exc:
            self.records = []
            self.render()
            self.summary.setText(f"Could not refresh movements: {exc}")
            return
        self.records = []
        for record in records:
            proposal = record["proposal"]
            details = [
                record["description"],
                f"{record['account_name']} · {record['posting_date']} · {money(record['amount_minor'])}",
                f"Posting-date provenance: {record['date_provenance']}",
                f"Prior interpretation: {record['status']}",
                "No expense/refund classification is implied. Choose the accounting treatment explicitly.",
                f"Observation: {record['observation_id']}",
            ]
            if proposal:
                details += [
                    f"Rejected proposal: {proposal['id']}",
                    f"Rejection reason: {proposal['decision']['reason']}",
                    "Original category amounts (history):",
                    *[f"  {p['account_id']}: {money(p['amount_minor'])}" for p in proposal["payload"]["postings"][1:]],
                    "A new interpretation preserves this rejection and verified source-category history.",
                ]
            self.records.append(
                {
                    "record": record,
                    "cells": [
                        record["account_name"],
                        record["posting_date"],
                        record["description"],
                        money(record["amount_minor"]),
                        record["status"],
                        record["date_provenance"],
                    ],
                    "details": "\n".join(details),
                }
            )
        self.records.sort(key=lambda r: (r["cells"][1], r["cells"][0], r["record"]["observation_id"]), reverse=True)
        self.summary.setText(f"{len(self.records):,} wholly unallocated movements without a pending ordinary proposal.")
        self.render()

    def render(self, *_):
        state = self.filter.currentText()
        self.page.model.beginResetModel()
        self.page.model.records = [r for r in self.records if state == "All" or r["record"]["status"] == state]
        self.page.model.endResetModel()
        self.page.filter(self.page.search.text())
        self.selection_changed()

    def selection_changed(self, *_):
        self.interpret.setEnabled(self.selected() is not None)

    def edit(self):
        selected = self.selected()
        if not selected:
            return
        dialog = ExpenseInterpretationDialog(self.service, selected["record"], self)
        dialog.exec()
        self.refresh()
        if dialog.result_key:
            self.on_posted(dialog.result_key)

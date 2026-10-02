"""Ordinary journal review in an explicitly prepared disposable workspace."""

import json
import sqlite3
from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_proposal_review import DEFAULT_ACCEPTANCE_REASON
from parsetrail.core.ledger_store import decode_entry
from parsetrail.gui.ledger_preview import PreviewPage, money

STATUS = {"pending": "Pending", "accepted": "Posted", "rejected": "Rejected — needs interpretation"}


class ProposalReviewWindow(QMainWindow):
    def __init__(self, review):
        super().__init__()
        self.review = review
        self.setWindowTitle("ParseTrail — Ordinary journal review (disposable copy)")
        self.resize(1320, 850)
        body = QWidget()
        layout = QVBoxLayout(body)
        notice = QLabel(
            "Review ordinary expenses and refunds in this disposable copy.\n"
            "Verified categories suggest these entries; acceptance confirms their accounting treatment. "
            "Opening balances, transfers and statement reconciliation remain unfinished."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["Pending", "Posted", "Rejected", "All"])
        layout.addWidget(self.status_filter)
        self.page = PreviewPage(["Account", "Date", "Description", "Source amount", "Category", "Review status"], [])
        self.page.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.page)
        self.selection_summary = QLabel()
        layout.addWidget(self.selection_summary)
        controls = QHBoxLayout()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Optional acceptance note; reason required for rejection")
        controls.addWidget(self.reason, 1)
        self.accept = QPushButton("Accept and post selected…")
        self.reject = QPushButton("Reject selected…")
        controls.addWidget(self.accept)
        controls.addWidget(self.reject)
        layout.addLayout(controls)
        self.setCentralWidget(body)
        self.page.table.selectionModel().selectionChanged.connect(self.selection_changed)
        self.reason.textChanged.connect(self.selection_changed)
        self.status_filter.currentTextChanged.connect(self.render)
        self.accept.clicked.connect(lambda: self.act("accepted"))
        self.reject.clicked.connect(lambda: self.act("rejected"))
        self.refresh()

    def refresh(self):
        store = self.review.store
        accounts, decisions = store.accounts(), self.review.decisions()
        c = store.connection
        files = {
            sid: json.loads(payload).get("filename", sid)
            for sid, payload in c.execute("SELECT id,payload FROM SourceFiles")
        }
        statements = {sid: files[source] for sid, source in c.execute("SELECT id,source_id FROM SourceStatements")}
        memberships = defaultdict(set)
        for tid, sid in c.execute("SELECT transaction_id,statement_id FROM SourceMemberships"):
            memberships[tid].add(statements[sid])
        self.records = []
        for pid, payload in self.review.proposals.items():
            entry = decode_entry(payload)
            financial, expense = entry.postings
            observation_id = financial.allocations[0].observation_id
            tid = observation_id.removeprefix("source:")
            decision = decisions.get(pid)
            state = decision["action"] if decision else "pending"
            amount = financial.amount_minor
            financial_account = accounts[financial.account_id]
            if financial_account.kind.value == "liability":
                effect = "Card debt decreases" if amount > 0 else "Card debt increases"
            else:
                effect = "Cash increases" if amount > 0 else "Cash decreases"
            details = [
                entry.description,
                f"{entry.posting_date} · {financial_account.name}",
                f"{effect} by {money(abs(amount))}.",
                f"Expense {'increases' if expense.amount_minor > 0 else 'decreases'} by {money(abs(expense.amount_minor))}.",
                "",
                "Accounting entry:",
            ]
            for posting in entry.postings:
                details.append(
                    f"{'Debit' if posting.amount_minor > 0 else 'Credit'} {accounts[posting.account_id].name}: {money(abs(posting.amount_minor))}"
                )
            details += [
                "",
                "Category verification: retained",
                f"Accounting status: {STATUS[state]}",
                "Statement reconciliation: not established",
                "",
                "Source statements:",
                *sorted(memberships[tid]),
            ]
            if decision:
                details += [
                    "",
                    f"Decision reason: {decision['reason']}",
                    f"Recorded at (UTC): {decision['created_at']}",
                ]
            self.records.append(
                {
                    "key": pid,
                    "state": state,
                    "expense_minor": expense.amount_minor,
                    "cells": [
                        financial_account.name,
                        entry.posting_date.isoformat(),
                        entry.description,
                        money(amount),
                        accounts[expense.account_id].name,
                        STATUS[state],
                    ],
                    "details": "\n".join(details),
                }
            )
        self.records.sort(key=lambda r: (r["cells"][1], r["cells"][0], r["key"]), reverse=True)
        counts = {state: sum(r["state"] == state for r in self.records) for state in STATUS}
        self.summary.setText(
            f"{counts['pending']:,} pending · {counts['accepted']:,} posted · {counts['rejected']:,} rejected\n"
            "Other movements remain outside this ordinary-proposal review. Ctrl/Shift select rows; Ctrl+A selects visible rows."
        )
        self.render()

    def render(self, *_):
        state = {"Pending": "pending", "Posted": "accepted", "Rejected": "rejected"}.get(
            self.status_filter.currentText()
        )
        model = self.page.model
        model.beginResetModel()
        model.records = [r for r in self.records if state is None or r["state"] == state]
        model.endResetModel()
        self.page.filter(self.page.search.text())
        self.selection_changed()

    def selected(self):
        return [
            self.page.model.records[self.page.proxy.mapToSource(index).row()]
            for index in self.page.table.selectionModel().selectedRows()
        ]

    def selection_changed(self, *_):
        rows = self.selected()
        self.selection_summary.setText(
            f"{len(rows):,} selected · Net expense effect: {money(sum(r['expense_minor'] for r in rows))}"
        )
        enabled = bool(rows and all(r["state"] == "pending" for r in rows))
        self.accept.setEnabled(enabled)
        self.reject.setEnabled(enabled and bool(self.reason.text().strip()))

    def confirm(self, action, rows, reason):
        verb = "Accept and post" if action == "accepted" else "Reject"
        dialog = QMessageBox(self)
        dialog.setWindowTitle(f"{verb} selected proposals")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(
            f"{verb} {len(rows):,} selected proposal(s)?\n"
            f"Net proposed expense effect: {money(sum(r['expense_minor'] for r in rows))}\n\n"
            + (
                "Acceptance posts these entries in the disposable copy."
                if action == "accepted"
                else "Rejection posts nothing and leaves the movements awaiting another interpretation."
            )
            + f"\n\nReason: {reason}"
        )
        dialog.setDetailedText("\n".join(" · ".join(r["cells"][:5]) for r in rows))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return dialog.exec() == QMessageBox.StandardButton.Ok

    def act(self, action):
        rows, reason = self.selected(), self.reason.text().strip()
        if action == "accepted" and not reason:
            reason = DEFAULT_ACCEPTANCE_REASON
        if not rows or not reason or any(r["state"] != "pending" for r in rows):
            return
        if not self.confirm(action, rows, reason):
            return
        try:
            self.review.decide([r["key"] for r in rows], action, reason)
        except (LedgerError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Decision not saved", str(exc))
        else:
            self.reason.clear()
        self.refresh()

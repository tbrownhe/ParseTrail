"""Disposable transfer/card-payment confirmation and evidence review."""

import json
import sqlite3
from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_transfers import DEFAULT_REASON, TransferReview
from parsetrail.gui.ledger_preview import PreviewPage, money
from parsetrail.gui.ledger_proposal_review import ProposalReviewWindow

LABELS = {
    "unique_candidate": "Single possible match",
    "ambiguous": "Multiple possible matches",
    "expense_conflict": "Expense interpretation needs review",
    "allocated": "Already allocated",
    "confirmed": "Confirmed",
    "dismissed": "Dismissed",
    "no_candidate": "No candidate in window",
    "one_candidate": "One candidate",
    "multiple_candidates": "Multiple candidates",
    "partially_allocated": "Partially allocated",
}


class TransferReviewWindow(QMainWindow):
    def __init__(self, review):
        super().__init__()
        self.review, self.transfers = review, TransferReview(review)
        self.setWindowTitle("ParseTrail — Transfer and card-payment workflow test (disposable copy)")
        self.resize(1380, 900)
        self.accounts, self.observations = review.store.accounts(), review.store.observations()
        c = review.store.connection
        self.raw = {tid: json.loads(payload) for tid, payload in c.execute("SELECT id,payload FROM SourceTransactions")}
        categories = {
            cid: json.loads(payload)["Name"] for cid, payload in c.execute("SELECT id,payload FROM CategoryDefinitions")
        }
        self.categories = {
            tid: categories[cid] for tid, cid in c.execute("SELECT transaction_id,category_id FROM CategoryAnnotations")
        }
        files = {
            fid: json.loads(payload).get("filename", fid)
            for fid, payload in c.execute("SELECT id,payload FROM SourceFiles")
        }
        statements = {sid: files[fid] for sid, fid in c.execute("SELECT id,source_id FROM SourceStatements")}
        self.sources = defaultdict(set)
        for tid, sid in c.execute("SELECT transaction_id,statement_id FROM SourceMemberships"):
            self.sources[tid].add(statements[sid])
        body = QWidget()
        layout = QVBoxLayout(body)
        notice = QLabel(
            "Workflow test copy — sample decisions here do not approve or change your live financial history.\n"
            "Only checking/savings transfers and cash-to-card payments are supported. Equal amounts suggest a match; confirmation is yours."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Maximum posting-date gap (days):"))
        self.days = QSpinBox()
        self.days.setRange(0, 31)
        self.days.setValue(7)
        controls.addWidget(self.days)
        self.filter = QComboBox()
        self.filter.addItems(
            ["Ready for review", "Expense conflict", "Already allocated", "Confirmed", "Dismissed", "All"]
        )
        controls.addWidget(self.filter)
        controls.addStretch()
        layout.addLayout(controls)
        self.tabs = QTabWidget()
        self.page = PreviewPage(["From", "Out date", "To", "In date", "Amount", "Type", "Review status"], [])
        self.movements = PreviewPage(["Account", "Date", "Description", "Amount", "Category", "Match status"], [])
        self.ordinary = ProposalReviewWindow(review)
        self.tabs.addTab(self.page, "Transfer candidates")
        self.tabs.addTab(self.movements, "All source movements")
        self.tabs.addTab(self.ordinary, "Expense/refund interpretations")
        layout.addWidget(self.tabs)
        action_row = QHBoxLayout()
        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional confirmation note; explanation required to dismiss a pair")
        action_row.addWidget(self.note, 1)
        self.confirm_button = QPushButton("Confirm and post pair…")
        self.dismiss_button = QPushButton("Dismiss this pair…")
        action_row.addWidget(self.confirm_button)
        action_row.addWidget(self.dismiss_button)
        layout.addLayout(action_row)
        self.setCentralWidget(body)
        self.page.table.selectionModel().selectionChanged.connect(self.update_actions)
        self.note.textChanged.connect(self.update_actions)
        self.days.valueChanged.connect(self.refresh)
        self.filter.currentTextChanged.connect(self.render)
        self.tabs.currentChanged.connect(self.tab_changed)
        self.confirm_button.clicked.connect(lambda: self.act("confirmed"))
        self.dismiss_button.clicked.connect(lambda: self.act("dismissed"))
        self.refresh()

    def source_detail(self, oid):
        o = self.observations[oid]
        tid = oid.removeprefix("source:")
        return "\n".join(
            [
                f"{self.accounts[o.account_id].name} · {o.posting_date} · {money(o.amount_minor)}",
                self.raw[tid]["Description"],
                f"Retained category: {self.categories.get(tid, 'None')}",
                "Source statements:",
                *sorted(self.sources[tid]),
            ]
        )

    def refresh(self, *_):
        snapshot = self.transfers.snapshot(self.days.value())
        self.records = []
        decisions = self.transfers.decisions()
        for pair in snapshot["pairs"]:
            outgoing, incoming = [self.observations[pair[k]] for k in ("outgoing_id", "incoming_id")]
            details = [
                self.source_detail(outgoing.id),
                "",
                self.source_detail(incoming.id),
                "",
                f"Possible counterparts for outgoing/incoming: {pair['alternative_counts']}",
                f"Posting-date provenance (outgoing/incoming): {', '.join(pair['posting_date_basis'])}",
                "Spending effect if confirmed: $0.00. The original cash/card movements remain recorded.",
            ]
            if pair["date_gap_days"]:
                details.append(
                    "Two dated entries preserve both source posting dates; transfer clearing holds the amount in transit between dates."
                )
            else:
                details.append("One balanced entry links the two same-day observations.")
            if pair["status"] == "expense_conflict":
                details.append(
                    "Review the conflicting proposal in Expense/refund interpretations. Reject that interpretation with a reason before confirming a transfer."
                )
            if pair["id"] in decisions:
                d = decisions[pair["id"]]
                details += [
                    f"Decision: {d['action']}",
                    f"Reason: {d['reason']}",
                    f"Recorded at (UTC): {d['created_at']}",
                ]
            self.records.append(
                {
                    "pair": pair,
                    "cells": [
                        self.accounts[outgoing.account_id].name,
                        outgoing.posting_date.isoformat(),
                        self.accounts[incoming.account_id].name,
                        incoming.posting_date.isoformat(),
                        money(pair["amount_minor"]),
                        "Card payment" if pair["kind"] == "card_payment" else "Cash transfer",
                        LABELS[pair["status"]],
                    ],
                    "details": "\n".join(details),
                }
            )
        self.records.sort(key=lambda r: (r["cells"][1], r["cells"][0], r["pair"]["id"]), reverse=True)
        movements = []
        for m in snapshot["movements"]:
            o = self.observations[m["id"]]
            tid = o.id.removeprefix("source:")
            movements.append(
                {
                    "cells": [
                        self.accounts[o.account_id].name,
                        o.posting_date.isoformat(),
                        self.raw[tid]["Description"],
                        money(o.amount_minor),
                        self.categories.get(tid, ""),
                        LABELS[m["status"]],
                    ],
                    "details": self.source_detail(o.id) + f"\n\nRemaining unallocated: {money(m['remaining_minor'])}\n"
                    f"Candidate count: {m['candidate_count']}\nPending ordinary proposal: {'Yes' if m['pending_expense'] else 'No'}\n"
                    "No candidate does not imply missing activity: ordinary expenses and external income may have no owned-account counterpart.",
                }
            )
        self.set_records(self.movements, movements)
        self.summary.setText(
            " · ".join(f"{LABELS[s]}: {count:,}" for s, count in sorted(snapshot["summary"].items()))
            + "\nFees, partial settlements, loans, card-to-card transfers and cash advances need separate interpretation; no balancing adjustment is inferred."
        )
        self.render()

    @staticmethod
    def set_records(page, records):
        page.model.beginResetModel()
        page.model.records = records
        page.model.endResetModel()
        page.filter(page.search.text())

    def render(self, *_):
        states = {
            "Ready for review": {"unique_candidate", "ambiguous"},
            "Expense conflict": {"expense_conflict"},
            "Already allocated": {"allocated"},
            "Confirmed": {"confirmed"},
            "Dismissed": {"dismissed"},
        }.get(self.filter.currentText())
        self.set_records(self.page, [r for r in self.records if states is None or r["pair"]["status"] in states])
        self.update_actions()

    def tab_changed(self, index):
        if index == 2:
            self.ordinary.refresh()
        else:
            self.refresh()
        self.update_actions()

    def selected(self):
        indices = self.page.table.selectionModel().selectedRows()
        return self.page.model.records[self.page.proxy.mapToSource(indices[0]).row()] if len(indices) == 1 else None

    def update_actions(self, *_):
        row = self.selected() if self.tabs.currentIndex() == 0 else None
        status = row["pair"]["status"] if row else None
        self.confirm_button.setEnabled(status in {"unique_candidate", "ambiguous"})
        self.dismiss_button.setEnabled(
            status in {"unique_candidate", "ambiguous", "expense_conflict"} and bool(self.note.text().strip())
        )

    def confirm(self, action, row, reason):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Confirm transfer interpretation" if action == "confirmed" else "Dismiss candidate pair")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(
            (
                "Post this transfer in the disposable test copy?"
                if action == "confirmed"
                else "Dismiss only this pairing? Both source movements remain available for other interpretations."
            )
            + "\n\n"
            + " · ".join(row["cells"][:6])
            + f"\n\nReason: {reason}"
        )
        dialog.setDetailedText(row["details"])
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return dialog.exec() == QMessageBox.StandardButton.Ok

    def act(self, action):
        row = self.selected()
        if self.tabs.currentIndex() != 0 or row is None:
            return
        status = row["pair"]["status"]
        allowed = (
            {"unique_candidate", "ambiguous"}
            if action == "confirmed"
            else {"unique_candidate", "ambiguous", "expense_conflict"}
        )
        reason = self.note.text().strip() or (DEFAULT_REASON if action == "confirmed" else "")
        if status not in allowed or not reason or not self.confirm(action, row, reason):
            return
        pair = row["pair"]
        try:
            self.transfers.decide([(pair["outgoing_id"], pair["incoming_id"])], action, reason, self.days.value())
        except (LedgerError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Transfer decision not saved", str(exc))
        else:
            self.note.clear()
        self.refresh()

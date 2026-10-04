"""Explicit loan payment/interest confirmation in a disposable review workspace."""

import json
import sqlite3

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_loan_payments import LoanPayments
from parsetrail.gui.ledger_preview import PreviewPage, money
from parsetrail.gui.ledger_proposal_review import ProposalReviewWindow


def set_records(page, records):
    page.model.beginResetModel()
    page.model.records = records
    page.model.endResetModel()
    page.filter(page.search.text())


def source_details(sources):
    return "\n".join(
        f"{s['file'].get('filename', s['statement']['source'])} · {s['statement']['start']} to {s['statement']['end']}"
        for s in sources
    )


class LoanPaymentDialog(QDialog):
    def __init__(self, service, pair, days, parent=None):
        super().__init__(parent)
        self.service, self.pair, self.days, self.plan = service, pair, days, None
        self.setWindowTitle("Preview loan payment and interest — disposable copy")
        self.resize(850, 640)
        layout = QVBoxLayout(self)
        notice = QLabel(
            f"{pair['bank']} → {pair['loan']}\nBank date: {pair['bank_date']} · Loan date: {pair['loan_date']}\n"
            "Confirm that these movements represent the same payment. Amount matching alone is not proof.\n"
            "The full payment reduces bank cash; only the separately recorded interest counts as expense.\n"
            "Capital One's derived opening balance is not independent reconciliation. Loan dates remain unverified."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addWidget(QLabel("Expense category for the separate interest component:"))
        self.category = QComboBox()
        definitions = [
            json.loads(p) for (p,) in service.store.connection.execute("SELECT payload FROM CategoryDefinitions")
        ]
        for row in sorted(definitions, key=lambda r: (r["Name"], r["CategoryID"])):
            if row["Type"] == "Expense":
                self.category.addItem(row["Name"], row["CategoryID"])
        self.category.setCurrentIndex(-1)
        self.category.setEnabled(bool(pair["interest_minor"]))
        layout.addWidget(self.category)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Optional confirmation note")
        layout.addWidget(self.reason)
        self.preview = QPushButton("Preview payment and interest")
        layout.addWidget(self.preview)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        layout.addWidget(self.preview_text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply = buttons.addButton("Confirm and post…", QDialogButtonBox.ButtonRole.ActionRole)
        self.apply.setEnabled(False)
        layout.addWidget(buttons)
        buttons.rejected.connect(self.reject)
        self.category.currentIndexChanged.connect(self.invalidate)
        self.reason.textChanged.connect(self.invalidate)
        self.preview.clicked.connect(self.build_preview)
        self.apply.clicked.connect(self.post)

    def invalidate(self, *_):
        self.plan = None
        self.apply.setEnabled(False)
        self.preview_text.clear()

    def build_preview(self):
        self.invalidate()
        try:
            self.plan = self.service.preview(
                self.pair["outgoing_id"],
                self.pair["payment_id"],
                self.category.currentData() if self.category.isEnabled() else None,
                self.reason.text(),
                self.days,
            )
        except (LedgerError, sqlite3.Error) as exc:
            self.preview_text.setPlainText(str(exc))
            return
        p = self.plan
        self.preview_text.setPlainText(
            "\n".join(
                [
                    f"Bank cash outflow: {money(self.pair['amount_minor'])} on {self.pair['bank_date']}",
                    f"Loan payment credit: {money(self.pair['amount_minor'])} on {self.pair['loan_date']}",
                    f"Interest expense: {money(p['interest_minor'])}"
                    + (f" · {self.category.currentText()}" if p["interest_minor"] else " · explicitly zero in source"),
                    f"Net loan principal reduction: {money(p['principal_reduction_minor'])}",
                    "The payment transfer adds no expense; interest is recognized once.",
                    "Different dates use clearing to preserve the bank outflow and loan receipt on their own dates.",
                    "All components save together. This does not establish an opening balance or certify reconciliation.",
                    f"Date provenance (bank, loan payment, nonzero interest): {', '.join(p['date_provenance'])}",
                    f"Reason: {p['reason']}",
                    "",
                    "Loan source statements:",
                    source_details(p["source_basis"]["sources"]),
                ]
            )
        )
        self.apply.setEnabled(True)

    def confirm(self):
        return (
            QMessageBox.question(
                self,
                "Post loan payment and interest",
                f"Post this payment and its interest together in the disposable copy?\n\n"
                f"Bank cash outflow: {money(self.pair['amount_minor'])}\n"
                f"Interest expense: {money(self.plan['interest_minor'])}\n"
                f"Principal reduction: {money(self.plan['principal_reduction_minor'])}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        )

    def post(self):
        if not self.plan or not self.confirm():
            return
        try:
            self.service.apply(self.plan)
        except (LedgerError, sqlite3.Error) as exc:
            self.invalidate()
            self.preview_text.setPlainText(f"{exc}\nRefresh the preview before posting.")
            return
        self.accept()


class LoanPaymentWindow(QMainWindow):
    def __init__(self, review):
        super().__init__()
        self.review, self.service = review, LoanPayments(review)
        self.setWindowTitle("ParseTrail — Loan payment workflow test (disposable copy)")
        self.resize(1380, 900)
        body = QWidget()
        layout = QVBoxLayout(body)
        notice = QLabel(
            "Workflow test copy — sample decisions do not change or approve live financial history.\n"
            "Capital One Auto payments only. Review the full bank outflow, separate interest expense and principal reduction together.\n"
            "Other loans, financing, openings and corrections remain outside this posting workflow."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Maximum posting-date gap (days):"))
        self.days = QSpinBox()
        self.days.setRange(0, 31)
        self.days.setValue(7)
        controls.addWidget(self.days)
        self.status = QComboBox()
        self.status.addItems(["Ready for review", "Blocked", "All"])
        controls.addWidget(self.status)
        self.summary = QLabel()
        controls.addWidget(self.summary)
        controls.addStretch()
        layout.addLayout(controls)
        self.tabs = QTabWidget()
        self.page = PreviewPage(["Bank", "Bank date", "Loan", "Loan date", "Payment", "Interest", "Review status"], [])
        self.confirmed = PreviewPage(
            ["Bank", "Bank date", "Loan", "Loan date", "Payment", "Interest", "Principal reduction", "Review status"],
            [],
        )
        self.unmatched = PreviewPage(["Loan", "Date", "Payment", "Review status"], [])
        self.ordinary = ProposalReviewWindow(review)
        self.tabs.addTab(self.page, "Payment candidates")
        self.tabs.addTab(self.confirmed, "Confirmed payments")
        self.tabs.addTab(self.unmatched, "No bank match")
        self.tabs.addTab(self.ordinary, "Expense/refund interpretations")
        layout.addWidget(self.tabs)
        self.edit = QPushButton("Review payment and interest…")
        layout.addWidget(self.edit)
        self.setCentralWidget(body)
        self.page.table.selectionModel().selectionChanged.connect(self.update_actions)
        self.days.valueChanged.connect(self.refresh)
        self.status.currentIndexChanged.connect(self.refresh)
        self.tabs.currentChanged.connect(self.refresh)
        self.edit.clicked.connect(self.open_review)
        self.refresh()

    def selected(self):
        rows = self.page.table.selectionModel().selectedRows()
        return self.page.model.records[self.page.proxy.mapToSource(rows[0]).row()] if rows else None

    def update_actions(self, *_):
        row = self.selected()
        self.edit.setEnabled(self.tabs.currentIndex() == 0 and bool(row) and not row["pair"]["blockers"])

    def refresh(self, *_):
        snapshot = self.service.snapshot(self.days.value())
        accounts, observations = self.review.store.accounts(), self.review.store.observations()
        records = []
        for p in snapshot["pairs"]:
            if p["payment_id"] in snapshot["decisions"]:
                continue
            if self.status.currentText() == "Ready for review" and p["blockers"]:
                continue
            if self.status.currentText() == "Blocked" and not p["blockers"]:
                continue
            status = "; ".join(p["blockers"]) or (
                "Multiple possible matches — choose explicitly"
                if max(p["alternatives"]) > 1
                else "Ready for review — unconfirmed"
            )
            bank_sources = self.review.store.connection.execute(
                "SELECT f.payload FROM SourceMemberships m JOIN SourceStatements s ON s.id=m.statement_id JOIN SourceFiles f ON f.id=s.source_id WHERE m.transaction_id=?",
                (p["outgoing_id"].removeprefix("source:"),),
            ).fetchall()
            bank_files = [json.loads(r[0]).get("filename", "Retained bank source") for r in bank_sources]
            details = "\n".join(
                [
                    status,
                    p["bank_description"],
                    f"Possible counterparts (bank / loan): {p['alternatives']}",
                    f"Posting-date provenance (bank / loan): {', '.join(p['date_provenance'])}",
                    "The full payment reduces bank cash. Only the interest component adds expense.",
                    "Loan opening is derived; matching these movements does not certify balances.",
                    "",
                    "Bank source statements:",
                    *bank_files,
                    "",
                    "Loan source statements:",
                    source_details(p["sources"]),
                ]
            )
            records.append(
                {
                    "pair": p,
                    "cells": [
                        p["bank"],
                        p["bank_date"],
                        p["loan"],
                        p["loan_date"],
                        money(p["amount_minor"]),
                        money(p["interest_minor"]) if p["interest_minor"] is not None else "Unknown",
                        status,
                    ],
                    "details": details,
                }
            )
        set_records(self.page, records)
        confirmed = []
        for p in snapshot["decisions"].values():
            o = observations[p["outgoing_id"]]
            incoming = observations["source:" + p["payment_id"]]
            category = (
                accounts[f"category:{p['category_id']}"].name if p["interest_minor"] else "Explicit zero interest"
            )
            confirmed.append(
                {
                    "plan": p,
                    "cells": [
                        accounts[o.account_id].name,
                        str(o.posting_date),
                        accounts[incoming.account_id].name,
                        str(incoming.posting_date),
                        money(incoming.amount_minor),
                        money(p["interest_minor"]),
                        money(p["principal_reduction_minor"]),
                        "Confirmed and posted",
                    ],
                    "details": "\n".join(
                        [
                            "Confirmed and posted together",
                            f"Interest category: {category}",
                            f"Reason: {p['reason']}",
                            "Date provenance: " + ", ".join(p["date_provenance"]),
                            "Source balances remain uncertified. Corrections require a future loan correction workflow.",
                            "",
                            source_details(p["source_basis"]["sources"]),
                        ]
                    ),
                }
            )
        set_records(self.confirmed, confirmed)
        unmatched = []
        for tid in snapshot["unmatched_payment_ids"]:
            b = snapshot["components"][tid]
            p = b["payment"]
            status = "; ".join(["No exact bank amount in date window", *b["blockers"]])
            unmatched.append(
                {
                    "cells": [
                        accounts["account:" + str(p["AccountID"])].name,
                        p["PostingDate"],
                        money(p["AmountMinor"]),
                        status,
                    ],
                    "details": status + "\n" + source_details(b["sources"]),
                }
            )
        set_records(self.unmatched, unmatched)
        self.summary.setText(f"{len(confirmed)} confirmed · {len(unmatched)} without bank match")
        self.update_actions()

    def open_review(self):
        row = self.selected()
        if not row or row["pair"]["blockers"] or self.tabs.currentIndex() != 0:
            return
        dialog = LoanPaymentDialog(self.service, row["pair"], self.days.value(), self)
        saved = dialog.exec() == QDialog.DialogCode.Accepted
        self.refresh()
        if saved:
            self.tabs.setCurrentIndex(1)
            for i, r in enumerate(self.confirmed.model.records):
                if r["plan"]["payment_id"] == row["pair"]["payment_id"]:
                    self.confirmed.table.selectRow(
                        self.confirmed.proxy.mapFromSource(self.confirmed.model.index(i, 0)).row()
                    )
                    break

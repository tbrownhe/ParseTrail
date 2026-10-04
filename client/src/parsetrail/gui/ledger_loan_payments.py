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
from parsetrail.core.ledger_categories import LOAN_INTEREST
from parsetrail.core.ledger_loan_corrections import LoanPaymentCorrections
from parsetrail.core.ledger_loan_payments import RULE as PAYMENT_RULE
from parsetrail.core.ledger_loan_payments import LoanPayments
from parsetrail.gui.ledger_loan_corrections import LoanCorrectionDialog
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
        self.category = QLabel(
            f"Expense category: {LOAN_INTEREST.name} (fixed by the interest component)"
            if pair["interest_minor"]
            else "Explicit zero interest — no expense category or posting needed."
        )
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
                reason=self.reason.text(),
                window_days=self.days,
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
                    + (f" · {LOAN_INTEREST.name}" if p["interest_minor"] else " · explicitly zero in source"),
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
        self.corrections = LoanPaymentCorrections(review)
        self.setWindowTitle("ParseTrail — Loan payment workflow test (disposable copy)")
        self.resize(1380, 900)
        body = QWidget()
        layout = QVBoxLayout(body)
        notice = QLabel(
            "Workflow test copy — sample decisions do not change or approve live financial history.\n"
            "Capital One Auto payments only. Review the full bank outflow, separate interest expense and principal reduction together.\n"
            "Confirmed payments support bank-match corrections. Other loans, financing and openings remain outside this workflow."
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
        self.history = PreviewPage(self.confirmed.model.headers, [])
        self.tabs.addTab(self.history, "Previous bank matches")
        layout.addWidget(self.tabs)
        self.edit = QPushButton("Review payment and interest…")
        layout.addWidget(self.edit)
        self.correct = QPushButton("Correct bank match…")
        layout.addWidget(self.correct)
        self.setCentralWidget(body)
        self.page.table.selectionModel().selectionChanged.connect(self.update_actions)
        self.confirmed.table.selectionModel().selectionChanged.connect(self.update_actions)
        self.days.valueChanged.connect(self.refresh)
        self.status.currentIndexChanged.connect(self.refresh)
        self.tabs.currentChanged.connect(self.refresh)
        self.edit.clicked.connect(self.open_review)
        self.correct.clicked.connect(self.open_correction)
        self.refresh()

    def selected(self):
        rows = self.page.table.selectionModel().selectedRows()
        return self.page.model.records[self.page.proxy.mapToSource(rows[0]).row()] if rows else None

    def update_actions(self, *_):
        row = self.selected()
        self.edit.setEnabled(self.tabs.currentIndex() == 0 and bool(row) and not row["pair"]["blockers"])
        confirmed = self.selected_confirmed()
        self.correct.setEnabled(
            self.tabs.currentIndex() == 1 and bool(confirmed) and confirmed["plan"]["rule"] == PAYMENT_RULE
        )

    def selected_confirmed(self):
        rows = self.confirmed.table.selectionModel().selectedRows()
        return self.confirmed.model.records[self.confirmed.proxy.mapToSource(rows[0]).row()] if rows else None

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
        confirmed, history = [], []
        histories = self.corrections.histories()
        for p in [p for versions in histories.values() for p in versions]:
            versions = histories[p["payment_id"]]
            active = p == versions[-1]
            status = (
                ("Corrected and posted" if len(versions) > 1 else "Confirmed and posted")
                if active
                else "Superseded bank match"
            )
            o = observations[p["outgoing_id"]]
            incoming = observations["source:" + p["payment_id"]]
            # Earlier disposable decisions keep their actual category; never relabel history.
            interest_account_id = p.get("interest_account_id") or f"category:{p.get('category_id')}"
            category = accounts[interest_account_id].name if p["interest_minor"] else "Explicit zero interest"
            (confirmed if active else history).append(
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
                        status,
                    ],
                    "details": "\n".join(
                        [
                            status,
                            f"Interest category: {category}",
                            f"Reason: {p['reason']}",
                            "Date provenance: " + ", ".join(p["date_provenance"]),
                            "Source balances remain uncertified. Loan components are fixed; only the bank match can be corrected.",
                            "Previous bank movements remain evidence and return to review after correction."
                            if len(versions) > 1
                            else "",
                            "",
                            source_details(p["source_basis"]["sources"]),
                        ]
                    ),
                }
            )
        set_records(self.confirmed, confirmed)
        set_records(self.history, history)
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

    def open_correction(self):
        row = self.selected_confirmed()
        if not row or self.tabs.currentIndex() != 1 or row["plan"]["rule"] != PAYMENT_RULE:
            return
        payment_id = row["plan"]["payment_id"]
        dialog = LoanCorrectionDialog(self.corrections, payment_id, self.days.value(), self)
        dialog.exec()
        self.refresh()
        for i, record in enumerate(self.confirmed.model.records):
            if record["plan"]["payment_id"] == payment_id:
                self.confirmed.table.selectRow(
                    self.confirmed.proxy.mapFromSource(self.confirmed.model.index(i, 0)).row()
                )
                break

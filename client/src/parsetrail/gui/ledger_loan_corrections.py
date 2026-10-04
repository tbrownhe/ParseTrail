"""Preview a replacement bank match without editing loan components."""

import sqlite3

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from parsetrail.core.ledger import LedgerError
from parsetrail.gui.ledger_preview import PreviewPage, money


class LoanCorrectionDialog(QDialog):
    def __init__(self, service, payment_id, days=7, parent=None):
        super().__init__(parent)
        self.service, self.payment_id, self.plan = service, payment_id, None
        self.setWindowTitle("Correct loan payment bank match — disposable copy")
        self.resize(1050, 850)
        layout = QVBoxLayout(self)
        notice = QLabel(
            "Choose the bank movement that actually funded this loan payment. Equal amounts alone do not prove a match.\n"
            "The loan amount, date, principal and fixed Loan interest expense remain unchanged.\n"
            "The previous bank movement returns to review; it is not deleted or refunded. A correction reason is required."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addWidget(QLabel("Maximum posting-date gap (days):"))
        self.days = QSpinBox()
        self.days.setRange(0, 31)
        self.days.setValue(days)
        layout.addWidget(self.days)
        self.page = PreviewPage(["Bank", "Date", "Amount", "Description", "Review status"], [])
        layout.addWidget(self.page, 2)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Why is this bank match being corrected? (required)")
        layout.addWidget(self.reason)
        self.preview = QPushButton("Preview match correction")
        layout.addWidget(self.preview)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        layout.addWidget(self.preview_text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply = buttons.addButton("Apply correction…", QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(buttons)
        buttons.rejected.connect(self.reject)
        self.page.table.selectionModel().selectionChanged.connect(self.invalidate)
        self.days.valueChanged.connect(self.refresh)
        self.reason.textChanged.connect(self.invalidate)
        self.preview.clicked.connect(self.build_preview)
        self.apply.clicked.connect(self.post)
        self.refresh()

    def selected(self):
        rows = self.page.table.selectionModel().selectedRows()
        return self.page.model.records[self.page.proxy.mapToSource(rows[0]).row()]["candidate"] if rows else None

    def invalidate(self, *_):
        self.plan = None
        self.apply.setEnabled(False)
        self.preview_text.clear()
        row = self.selected()
        self.preview.setEnabled(bool(row) and not row["blockers"] and bool(self.reason.text().strip()))

    def refresh(self, *_):
        records = []
        error = ""
        try:
            for row in self.service.candidates(self.payment_id, self.days.value()):
                status = "; ".join(row["blockers"]) or "Possible replacement — unconfirmed"
                records.append(
                    {
                        "candidate": row,
                        "cells": [row["account"], row["date"], money(row["amount_minor"]), row["description"], status],
                        "details": "\n".join(
                            [
                                status,
                                f"Date provenance: {row['date_provenance']}",
                                "Bank source statements:",
                                *row["sources"],
                            ]
                        ),
                    }
                )
        except (LedgerError, sqlite3.Error) as exc:
            error = str(exc)
        self.page.model.beginResetModel()
        self.page.model.records = records
        self.page.model.endResetModel()
        self.page.filter(self.page.search.text())
        self.invalidate()
        if error or not any(not r["candidate"]["blockers"] for r in records):
            self.preview_text.setPlainText(
                error
                or "No available replacement in this date window. Review blocked candidates or adjust the window; no match is inferred."
            )

    def build_preview(self):
        row = self.selected()
        self.invalidate()
        if not row or row["blockers"]:
            return
        try:
            self.plan = self.service.preview(self.payment_id, row["outgoing_id"], self.reason.text(), self.days.value())
        except (LedgerError, sqlite3.Error) as exc:
            self.preview_text.setPlainText(str(exc))
            return
        accounts = self.service.store.accounts()
        effect = self.plan["cash_effect"]
        before, after = self.plan["previous"], self.plan["replacement"]
        self.preview_text.setPlainText(
            "\n".join(
                [
                    f"Previous bank: {accounts[effect['released_account_id']].name} · {effect['released_date']} · {money(effect['amount_minor'])}",
                    f"Replacement bank: {accounts[effect['replacement_account_id']].name} · {effect['replacement_date']} · {money(effect['amount_minor'])}",
                    "The previous bank movement becomes unallocated and needs its own interpretation.",
                    f"Loan payment unchanged: {money(effect['amount_minor'])} on {after['source_basis']['payment']['PostingDate']}",
                    f"Loan interest unchanged: {money(after['interest_minor'])} · fixed Loan interest category",
                    f"Principal reduction unchanged: {money(after['principal_reduction_minor'])}",
                    "Net expense change: $0.00. Clearing preserves the replacement bank date and loan date.",
                    f"Reverse all {len(before['entries'])} original entries and post {len(after['entries'])} replacement entries together.",
                    "Original entries and the correction reason remain in history. Previous reconciliation results become stale.",
                    f"Date provenance (previous): {', '.join(before['date_provenance'])}",
                    f"Date provenance (replacement): {', '.join(after['date_provenance'])}",
                    f"Reason: {self.plan['reason']}",
                ]
            )
        )
        self.apply.setEnabled(True)

    def confirm(self):
        return (
            QMessageBox.question(
                self,
                "Apply loan match correction",
                "Reverse the current payment bundle and post the replacement match in the disposable copy?\n\n"
                "Loan principal and interest totals stay unchanged. The previous bank movement returns to review.\n"
                f"Reason: {self.plan['reason']}",
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
            self.preview_text.setPlainText(f"{exc}\nRefresh and preview the current match before applying.")
            return
        self.accept()

"""Opening provenance and position controls for a disposable workflow test."""

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
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
from parsetrail.gui.ledger_preview import PreviewPage, money

BALANCES = {"assumed": "Unverified", "reported": "Printed on statement", "derived": "Derived from other values"}
DATES = {"unknown": "Unknown", "reported": "Reported bank posting dates", "estimated": "Estimated posting dates"}
STATES = {
    "blocked": "Source review needed",
    "ready_for_confirmation": "Ready for confirmation",
    "posted": "Opening posted",
    "confirmed_zero": "Zero opening confirmed",
    "stale_source_review": "Source review changed — correction needed",
}


class OpeningReviewWindow(QMainWindow):
    def __init__(self, openings):
        super().__init__()
        self.openings = openings
        self.current_source, self.loaded_form = None, None
        self.setWindowTitle("ParseTrail — Opening positions workflow test (disposable copy)")
        self.resize(1300, 930)
        body = QWidget()
        layout = QVBoxLayout(body)
        notice = QLabel(
            "Workflow test copy — these sample decisions do not approve your rebuilt books or change the live database.\n"
            "Review the earliest source balance and period timing before confirming an opening. Coverage and transaction-date certainty remain separate."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.page = PreviewPage(["Account", "Proposed cutoff", "Opening amount", "Review status"], [])
        layout.addWidget(self.page, 1)
        form = QFormLayout()
        self.source = QComboBox()
        form.addRow("Earliest source statement", self.source)
        self.source_balances = QLabel()
        form.addRow("Parsed source balances", self.source_balances)
        self.opening = self.combo(BALANCES)
        self.closing = self.combo(BALANCES)
        self.dates = self.combo(DATES)
        form.addRow("Opening balance origin", self.opening)
        form.addRow("Closing balance origin", self.closing)
        form.addRow("Transaction posting dates", self.dates)
        self.timing = QCheckBox("I checked: opening is before the inclusive start; closing is at the inclusive end")
        form.addRow("Period timing", self.timing)
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("Source page/section or other precise reference (required)")
        form.addRow("Source reference", self.reference)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional source-review note")
        form.addRow("Review note", self.note)
        layout.addLayout(form)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        buttons = QHBoxLayout()
        self.save = QPushButton("Record source review…")
        self.post = QPushButton("Confirm opening position…")
        buttons.addWidget(self.save)
        buttons.addWidget(self.post)
        layout.addLayout(buttons)
        self.setCentralWidget(body)
        self.page.table.selectionModel().selectionChanged.connect(self.anchor_changed)
        self.source.currentIndexChanged.connect(self.load_source)
        for combo in (self.opening, self.closing, self.dates):
            combo.currentIndexChanged.connect(self.update_actions)
        self.timing.toggled.connect(self.update_actions)
        self.reference.textChanged.connect(self.update_actions)
        self.note.textChanged.connect(self.update_actions)
        self.save.clicked.connect(self.save_source)
        self.post.clicked.connect(self.confirm_opening)
        self.refresh()

    @staticmethod
    def combo(labels):
        combo = QComboBox()
        for value, label in labels.items():
            combo.addItem(label, value)
        return combo

    def selected(self):
        rows = self.page.table.selectionModel().selectedRows()
        return self.page.model.records[self.page.proxy.mapToSource(rows[0]).row()] if len(rows) == 1 else None

    def refresh(self, keep=None):
        records = []
        for aid, anchor in self.openings.anchors.items():
            status = self.openings.status(aid)
            amount = anchor["proposed_amount_minor"]
            details = [
                f"{anchor['account_name']} · {anchor['proposed_date'] or 'No cutoff'}",
                anchor.get("date_basis", "No source statement is available."),
                "Zero openings record a decision only; nonzero openings balance against opening equity, not income or expense.",
                "",
                *[f"Source: {s['filename']} · {s['start']} to {s['end']}" for s in anchor["sources"]],
                *anchor.get("posting_date_limitations", []),
                "",
                *[f"Blocker: {b.replace('_', ' ')}" for b in status["blockers"]],
            ]
            if status["decision"]:
                d = status["decision"]
                details += [f"Decision reason: {d['reason']}", f"Recorded at (UTC): {d['created_at']}"]
            gaps = [
                r
                for r in self.openings.plan["continuity"]
                if r["account_id"] == anchor["account_id"] and r["status"] != "adjacent_balances_agree"
            ]
            details += [
                f"\nContinuity exceptions retained: {len(gaps)}",
                "This opening does not certify statement reconciliation or fill coverage gaps.",
            ]
            records.append(
                {
                    "account_id": aid,
                    "cells": [
                        anchor["account_name"],
                        anchor["proposed_date"] or "",
                        money(amount) if amount is not None else "Unresolved",
                        STATES[status["state"]],
                    ],
                    "details": "\n".join(details),
                }
            )
        self.page.model.beginResetModel()
        self.page.model.records = records
        self.page.model.endResetModel()
        self.page.filter(self.page.search.text())
        self.anchor_changed()
        if keep:
            for row in range(self.page.proxy.rowCount()):
                index = self.page.proxy.mapToSource(self.page.proxy.index(row, 0)).row()
                if records[index]["account_id"] == keep:
                    self.page.table.selectRow(row)
                    break

    def anchor_changed(self, *_):
        row = self.selected()
        self.source.clear()
        if row:
            anchor = self.openings.anchors[row["account_id"]]
            for s in anchor["sources"]:
                self.source.addItem(f"{s['filename']} ({s['start']} to {s['end']})", s["statement_id"])
        self.load_source()

    def form_values(self):
        return (
            self.opening.currentData(),
            self.closing.currentData(),
            self.timing.isChecked(),
            self.dates.currentData(),
            self.reference.text(),
            self.note.text(),
        )

    def load_source(self, *_):
        self.current_source, self.loaded_form = None, None
        self.source_balances.clear()
        sid = self.source.currentData()
        if sid:
            raw = self.openings.sources[sid]
            self.source_balances.setText(
                f"Opening {money(raw['opening_minor'])} · Closing {money(raw['closing_minor'])}. Debt uses negative ledger amounts."
            )
            try:
                p = self.openings.provenance(sid)
            except LedgerError:
                self.hint.setText("This earliest statement is not eligible. Resolve its source exception first.")
            else:
                self.opening.setCurrentIndex(self.opening.findData(p["opening"]))
                self.closing.setCurrentIndex(self.closing.findData(p["closing"]))
                self.dates.setCurrentIndex(self.dates.findData(p["posting_dates"]))
                self.timing.setChecked(p["timing_confirmed"])
                self.reference.setText(p["reference"])
                self.note.setText(p["reason"] if p["sequence"] else "")
                baseline = self.openings.store.connection.execute(
                    "SELECT basis FROM SourceDateProvenance WHERE statement_id=?", (sid,)
                ).fetchone()[0]
                self.dates.setEnabled(baseline != "estimated")
                self.current_source, self.loaded_form = sid, self.form_values()
                self.hint.setText(
                    "Known posting-date proxies must remain estimated."
                    if baseline == "estimated"
                    else "Record what the source establishes. Unverified or derived openings cannot authorize a source-backed opening position."
                )
        else:
            self.hint.setText("Select an account and its earliest source statement.")
        self.update_actions()

    def update_actions(self, *_):
        row = self.selected()
        dirty = self.loaded_form is not None and self.form_values() != self.loaded_form
        self.save.setEnabled(bool(self.current_source and self.reference.text().strip() and dirty))
        ready = row and self.openings.status(row["account_id"])["state"] == "ready_for_confirmation"
        self.post.setEnabled(bool(ready and not dirty))

    def confirm(self, title, text):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(text)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return dialog.exec() == QMessageBox.StandardButton.Ok

    def save_source(self):
        row, sid = self.selected(), self.current_source
        if not row or not sid or not self.reference.text().strip():
            return
        payload = dict(
            zip(
                ("opening", "closing", "timing_confirmed", "posting_dates", "reference", "reason"),
                self.form_values(),
                strict=True,
            )
        )
        payload["reason"] = payload["reason"].strip() or "Recorded statement source provenance"
        if not self.confirm(
            "Record source assertions",
            f"Record these assertions in the disposable workflow copy?\n\n{self.source.currentText()}\n"
            f"Opening: {self.opening.currentText()}\nClosing: {self.closing.currentText()}\n"
            f"Inclusive-period timing checked: {'Yes' if payload['timing_confirmed'] else 'No'}\n"
            f"Posting dates: {self.dates.currentText()}\nReference: {payload['reference']}",
        ):
            return
        try:
            self.openings.assert_source(sid, **payload)
        except (LedgerError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Source review not saved", str(exc))
        self.refresh(row["account_id"])

    def confirm_opening(self):
        row = self.selected()
        if not row or not self.post.isEnabled():
            return
        anchor = self.openings.anchors[row["account_id"]]
        basis = self.openings.status(row["account_id"])["provenance_hash"]
        effect = (
            "Record a zero opening without creating a journal?"
            if anchor["proposed_amount_minor"] == 0
            else "Post this opening against opening equity?"
        )
        if not self.confirm(
            "Confirm opening position",
            f"{effect}\n\n{anchor['account_name']} · {anchor['proposed_date']} · {money(anchor['proposed_amount_minor'])}\n\n"
            "This affects only the disposable workflow copy. It does not certify transaction dates, coverage or reconciliation.",
        ):
            return
        try:
            self.openings.confirm_opening(row["account_id"], expected_provenance_hash=basis)
        except (LedgerError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Opening not saved", str(exc))
        self.refresh(row["account_id"])

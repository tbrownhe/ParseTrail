"""Statement reconciliation and source review in an isolated workflow copy."""

import json
import sqlite3

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_opening_review import OpeningReview
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reconciliation_view import ReconciliationView
from parsetrail.gui.ledger_opening_review import BALANCES, DATES, OpeningReviewWindow
from parsetrail.gui.ledger_preview import LABELS, PreviewPage, money

EXCEPTIONS = {
    **LABELS,
    "source_period_timing_unverified": "Statement period timing needs review",
    "opening_position_unverified_or_stale": "Opening position needs confirmation or correction",
    "posting_dates_not_verified": "Posting dates remain unknown or estimated",
    "statement_not_eligible": "Source statement needs correction before reconciliation",
}


class SourceReviewDialog(QDialog):
    def __init__(self, openings, sid, parent=None):
        super().__init__(parent)
        self.openings, self.sid = openings, sid
        p, raw = openings.provenance(sid), openings.sources[sid]
        self.expected = key(p)
        self.setWindowTitle("Review statement source — disposable copy")
        self.resize(760, 450)
        layout = QVBoxLayout(self)
        label = QLabel(
            f"{openings.files[raw['source']]['filename']}\n{raw['start']} to {raw['end']}\n"
            f"Parsed opening {money(raw['opening_minor'])} · closing {money(raw['closing_minor'])}\n"
            "Debt uses negative ledger amounts. Saving records source assertions only; it does not post or reconcile activity."
        )
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout()
        self.opening, self.closing, self.dates = (
            OpeningReviewWindow.combo(labels) for labels in (BALANCES, BALANCES, DATES)
        )
        for widget, value in (
            (self.opening, p["opening"]),
            (self.closing, p["closing"]),
            (self.dates, p["posting_dates"]),
        ):
            widget.setCurrentIndex(widget.findData(value))
        baseline = openings.store.connection.execute(
            "SELECT basis FROM SourceDateProvenance WHERE statement_id=?", (sid,)
        ).fetchone()[0]
        self.dates.setEnabled(baseline != "estimated")
        self.timing = QCheckBox("Opening is before the inclusive start; closing is at the inclusive end")
        self.timing.setChecked(p["timing_confirmed"])
        self.reference, self.note = QLineEdit(p["reference"]), QLineEdit(p["reason"] if p["sequence"] else "")
        self.reference.setPlaceholderText("Source page/section (required; use 'Workflow test' for this exercise)")
        self.note.setPlaceholderText("Optional source-review note")
        for title, widget in (
            ("Opening origin", self.opening),
            ("Closing origin", self.closing),
            ("Posting dates", self.dates),
            ("Period timing", self.timing),
            ("Source reference", self.reference),
            ("Review note", self.note),
        ):
            form.addRow(title, widget)
        layout.addLayout(form)
        self.error = QLabel("Known posting-date proxies must remain estimated." if baseline == "estimated" else "")
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save.setDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        self.save.setEnabled(bool(self.reference.text().strip()))
        self.reference.textChanged.connect(lambda text: self.save.setEnabled(bool(text.strip())))
        buttons.accepted.connect(self.save_source)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save_source(self):
        try:
            self.openings.assert_source(
                self.sid,
                opening=self.opening.currentData(),
                closing=self.closing.currentData(),
                posting_dates=self.dates.currentData(),
                timing_confirmed=self.timing.isChecked(),
                reference=self.reference.text(),
                reason=self.note.text().strip() or "Recorded statement source provenance",
                expected_provenance_hash=self.expected,
            )
        except (LedgerError, sqlite3.Error) as exc:
            self.error.setText(str(exc))
        else:
            self.accept()


class ReconciliationReviewWindow(QMainWindow):
    def __init__(self, review, folder):
        super().__init__()
        self.review, self.openings = review, OpeningReview(review)
        self.view = ReconciliationView(review, folder)
        if self.view.report is None:
            self.view.check()
        self.current, self.revision = False, None
        self.setWindowTitle("ParseTrail — Statement reconciliation workflow test (disposable copy)")
        self.resize(1350, 900)
        body, layout = QWidget(), QVBoxLayout()
        body.setLayout(layout)
        notice = QLabel(
            "Workflow test copy — sample source reviews do not approve rebuilt books or change the live database."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        layout.addWidget(self.banner)
        buttons = QHBoxLayout()
        self.check = QPushButton("Check statements")
        self.edit = QPushButton("Review selected source…")
        buttons.addWidget(self.check)
        buttons.addWidget(self.edit)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.tabs = QTabWidget()
        self.page = PreviewPage(
            ["Account", "Start", "End", "Balance check", "Reconciliation", "Source review", "Source"], []
        )
        self.source_filter = QComboBox()
        self.source_filter.addItems(["All sources", "Recorded", "Not recorded", "Unavailable"])
        source_filter_row = QHBoxLayout()
        source_filter_row.addWidget(QLabel("Source review"))
        source_filter_row.addWidget(self.source_filter)
        source_filter_row.addWidget(QLabel("Current saved review; reconciliation results may still be stale."))
        source_filter_row.addStretch()
        self.page.layout().insertLayout(0, source_filter_row)
        self.source_filter.currentTextChanged.connect(self.filter_statements)
        self.evidence = PreviewPage(["Date", "Description", "Amount", "Unallocated", "Date provenance"], [])
        self.coverage = PreviewPage(
            ["Account", "First period", "Last period", "Coverage gaps", "Statements reconciled"], []
        )
        self.unmapped = PreviewPage(["Account", "Date", "Description", "Amount", "Reason"], [])
        for title, page in (
            ("Saved statement checks", self.page),
            ("Selected statement evidence", self.evidence),
            ("Account coverage", self.coverage),
            ("Movements outside ledger", self.unmapped),
        ):
            self.tabs.addTab(page, title)
        layout.addWidget(self.tabs)
        self.setCentralWidget(body)
        self.page.table.selectionModel().selectionChanged.connect(self.selection_changed)
        self.edit.clicked.connect(self.review_source)
        self.check.clicked.connect(self.check_statements)
        self.render()
        self.check_current(force=True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_current)
        self.timer.start(1000)

    @staticmethod
    def set_records(page, records):
        page.model.beginResetModel()
        page.model.records = records
        page.model.endResetModel()
        page.filter(page.search.text())

    def selected(self):
        rows = self.page.table.selectionModel().selectedRows()
        return self.page.model.records[self.page.proxy.mapToSource(rows[0]).row()] if len(rows) == 1 else None

    def render(self, keep=None):
        report = self.view.report
        self.accounts = self.review.store.accounts()
        self.raw = {
            tid: json.loads(payload)
            for tid, payload in self.review.store.connection.execute("SELECT id,payload FROM SourceTransactions")
        }
        self.memberships = {}
        for sid, tid in self.review.store.connection.execute(
            "SELECT statement_id,transaction_id FROM SourceMemberships ORDER BY statement_id,row_number"
        ):
            self.memberships.setdefault(sid, []).append(tid)
        records = []
        for row in report["statements"]:
            raw = self.openings.sources[row["statement_id"]]
            filename = self.openings.files[row["source_id"]]["filename"]
            details = [
                filename,
                f"{row['start']} to {row['end']}",
                f"Opening position: {row['opening_state'].replace('_', ' ')}",
            ]
            balance = row.get("balance_check")
            if balance:
                for label, field in (("Opening", "opening"), ("Closing", "closing")):
                    source = raw[f"{field}_minor"]
                    difference = balance[f"{field}_difference_minor"]
                    details.append(
                        f"{label}: source {money(source)} · ledger {money(source + difference)} · difference {money(difference)}"
                    )
                details += [
                    f"Source activity equation difference: {money(balance['source_difference_minor'])}",
                    f"Posted interpretations reviewed: {'Yes' if row['posted_interpretations_reviewed'] else 'No'}",
                    f"Source reference at last check: {row['source_review']['reference'] or 'Not reviewed'}",
                    f"Posting-date provenance at last check: {row['source_review']['posting_dates']}",
                    "Unreviewed entries: " + (", ".join(row["unreviewed_entry_keys"]) or "None"),
                    "Postings outside statement evidence: " + (", ".join(balance["uncovered_entry_keys"]) or "None"),
                ]
            else:
                details += [
                    "Eligibility: " + row["eligibility"]["status"].replace("_", " "),
                    f"Source activity equation difference: {money(row['eligibility']['source_difference_minor'])}",
                ]
            details += [EXCEPTIONS.get(e, e.replace("_", " ")) for e in row["exceptions"]]
            details += ["Select the evidence tab for individual movements. Account coverage is a separate check."]
            records.append(
                {
                    "row": row,
                    "cells": [
                        self.accounts[row["account_id"]].name,
                        row["start"],
                        row["end"],
                        "Agrees" if balance and balance["reconciled"] else "Needs review" if balance else "Unavailable",
                        "Reconciled" if row["reconciled"] else "Needs review" if balance else "Unavailable",
                        "",
                        filename,
                    ],
                    "check_details": "\n".join(details),
                }
            )
        records.sort(key=lambda record: record["cells"][:3])
        self.statement_records = records
        self.refresh_source_reviews(keep)
        coverage = []
        for account in report["accounts"]:
            details = [f"Opening: {account['opening_state']['state'].replace('_', ' ')}"]
            for boundary in account["continuity_exceptions"]:
                details.append(
                    f"{boundary['status'].replace('_', ' ')}: {boundary['prior_end']} to {boundary['next_start']} · "
                    f"uncovered days {boundary['uncovered_days']} · endpoint differences "
                    + ", ".join(money(amount) for amount in boundary["endpoint_differences_minor"])
                )
            details += [
                "Unavailable statements: " + (", ".join(account["unavailable_statement_ids"]) or "None"),
                "Continuous source periods do not certify all financial activity or current balances.",
                f"Incomplete source files in workspace: {len(report['incomplete_source_ids'])}",
                f"Statements outside cash/card scope: {len(report['outside_scope_statement_ids'])}",
            ]
            coverage.append(
                {
                    "cells": [
                        self.accounts[account["account_id"]].name,
                        account["first_start"] or "None",
                        account["last_end"] or "None",
                        "Yes" if account["has_coverage_gaps"] else "No" if account["has_source_periods"] else "Unknown",
                        "Yes" if account["all_statements_reconciled"] else "No",
                    ],
                    "details": "\n".join(details),
                }
            )
        self.set_records(self.coverage, coverage)
        unmapped = []
        for movement in report["unmapped_movements"]:
            raw = self.raw[movement["transaction_id"]]
            account = self.accounts.get(f"account:{movement['account_id']}")
            unmapped.append(
                {
                    "cells": [
                        account.name if account else "Outside cash/card scope",
                        raw["PostingDate"],
                        raw["Description"],
                        money(movement["amount_minor"]),
                        movement["status"].replace("_", " "),
                    ],
                    "details": "Source statements: " + (", ".join(movement["statement_ids"]) or "Missing membership"),
                }
            )
        self.set_records(self.unmapped, unmapped)
        self.selection_changed()

    def refresh_source_reviews(self, keep=None):
        for record in self.statement_records:
            row = record["row"]
            current = []
            state = "Unavailable"
            if row["status"] == "checked":
                p = self.openings.provenance(row["statement_id"])
                state = "Recorded" if p["sequence"] is not None else "Not recorded"
                if p["sequence"] is not None:
                    current = [
                        f"Current source reference: {p['reference']}",
                        f"Current balance origins: opening {BALANCES[p['opening']]}; closing {BALANCES[p['closing']]}",
                        f"Current period timing checked: {'Yes' if p['timing_confirmed'] else 'No'}",
                        f"Current posting-date provenance: {p['posting_dates']}",
                    ]
            record["source_review_state"] = state
            record["cells"][5] = state
            record["details"] = "\n".join(
                [
                    f"Source review now: {state}",
                    *current,
                    "Recorded means a source review was saved, not that reconciliation passed.",
                    "",
                    "Last reconciliation check:",
                    record["check_details"],
                ]
            )
        self.filter_statements(keep=keep)

    def filter_statements(self, *_args, keep=None):
        selected = self.selected()
        if keep is None and selected:
            keep = selected["row"]["statement_id"]
        state = self.source_filter.currentText()
        records = [r for r in self.statement_records if state == "All sources" or r["source_review_state"] == state]
        self.set_records(self.page, records)
        self.selection_changed()
        if keep:
            for index in range(self.page.proxy.rowCount()):
                source = self.page.proxy.mapToSource(self.page.proxy.index(index, 0)).row()
                if records[source]["row"]["statement_id"] == keep:
                    self.page.table.selectRow(index)
                    break

    def selection_changed(self, *_):
        selected = self.selected()
        self.edit.setEnabled(bool(selected and selected["row"]["status"] == "checked"))
        records = []
        if selected:
            row = selected["row"]
            observations = self.review.store.observations()
            for tid in self.memberships.get(row["statement_id"], []):
                raw, oid = self.raw[tid], f"source:{tid}"
                remaining = self.view.report["remaining_observations"].get(oid, 0)
                basis = row.get("date_uncertain_observations", {}).get(
                    oid,
                    "reported"
                    if oid in observations and row["status"] == "checked"
                    else row.get("source_review", {}).get("posting_dates", "Unavailable"),
                )
                records.append(
                    {
                        "cells": [
                            raw["PostingDate"],
                            raw["Description"],
                            money(raw["AmountMinor"]),
                            money(remaining) if oid in observations else "Not admitted",
                            basis,
                        ],
                        "details": f"Saved check for {row['start']} to {row['end']}\n{selected['cells'][-1]}\n"
                        "Evidence is retained even when it cannot yet be posted. Date labels do not change the source date.",
                    }
                )
        self.set_records(self.evidence, records)

    def check_current(self, *, force=False):
        c = self.review.store.connection
        try:
            revision = (c.execute("PRAGMA data_version").fetchone()[0], c.total_changes)
            if not force and self.revision == revision:
                return
            self.current = self.view.is_current()
            self.refresh_source_reviews()
            self.revision = revision
            self.banner.setText(
                "Current saved check. Balances, interpretation review, dates and coverage are separate."
                if self.current
                else "STALE — displayed results are from an earlier check. Choose Check statements to update them."
            )
        except (LedgerError, sqlite3.Error) as exc:
            self.revision = None
            self.current = False
            self.banner.setText(f"Could not verify saved results: {exc}. Check statements before relying on them.")
        self.banner.setStyleSheet("font-weight: bold;" + ("color: #a33;" if not self.current else ""))

    def check_statements(self):
        selected = self.selected()
        try:
            self.view.check()
        except (LedgerError, sqlite3.Error, OSError) as exc:
            self.check_current(force=True)
            QMessageBox.warning(self, "Check not saved", str(exc))
            return
        self.render(selected["row"]["statement_id"] if selected else None)
        self.check_current(force=True)

    def review_source(self):
        selected = self.selected()
        if not selected or selected["row"]["status"] != "checked":
            return
        dialog = SourceReviewDialog(self.openings, selected["row"]["statement_id"], self)
        dialog.exec()
        self.check_current(force=True)

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)

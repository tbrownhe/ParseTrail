"""Read-only shadow-ledger acceptance window. Never loads the active profile."""

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.ledger_migration import read_legacy
from parsetrail.core.ledger_store import encoded
from parsetrail.core.recovery_bundle import digest

LABELS = {
    "posted_legacy_category_unreviewed": "Category carried forward — needs review",
    "unconfirmed_transfer": "Transfer needs confirmation",
    "uncategorized_evidence": "Needs category",
    "manual_closure_control_evidence": "Tracking closure — excluded from cash activity",
    "zero_amount_evidence": "Zero amount — retained as evidence",
    "investment_scope_review": "Investment treatment needs review",
    "synthetic_loan_opening_review": "Synthetic loan opening — needs review",
    "tangible_asset_valuation_review": "Asset valuation needs review",
    "manual_entry_review": "Manual entry needs review",
    "balance_evidence_not_independent": "Source balances not independently verified",
    "source_balance_equation": "Source activity does not match balance change",
    "opening_balance": "Opening position differs",
    "closing_balance": "Closing position differs",
    "unallocated_evidence": "Activity still needs accounting interpretation",
    "postings_outside_statement_evidence": "Posted activity outside this statement's evidence",
}


def money(value: int) -> str:
    sign = "-" if value < 0 else ""
    amount = abs(value)
    return f"{sign}${amount // 100:,}.{amount % 100:02d}"


def load_preview(folder: Path) -> dict:
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    if (
        plan["plan_sha256"]
        != hashlib.sha256(encoded({k: v for k, v in plan.items() if k != "plan_sha256"}).encode()).hexdigest()
        or report["plan_sha256"] != plan["plan_sha256"]
        or digest(folder / "legacy.db") != report["source_sha256"]
        or digest(folder / "ledger.db") != report["ledger_sha256"]
        or digest(folder / "source-corrections.json") != report["corrections_sha256"]
    ):
        raise ValueError("Preview files have changed or do not belong to the same verified run.")
    legacy = read_legacy(folder / "legacy.db")
    names = {r["AccountID"]: r["AccountName"] for r in legacy["Accounts"]}
    categories = {r["CategoryID"]: r["Name"] for r in legacy["Categories"]}
    raw = {r["TransactionID"]: r for r in legacy["Transactions"]}
    observations = {r["id"]: r for r in plan["observations"]}
    descriptions = {
        p["allocations"][0]["observation_id"]: e["description"]
        for e in plan["entries"]
        for p in e["postings"]
        if p["allocations"]
    }
    source_rows = json.loads((folder / "source-corrections.json").read_text(encoding="utf-8"))
    added_ids = {r["observation_id"] for r in plan["added_source_rows"]}
    for correction in source_rows:
        for index, row in enumerate(correction["rows"]):
            token = hashlib.sha256(encoded([correction["source_hash"], index, row]).encode()).hexdigest()
            key = f"legacy:{plan['source_namespace']}:source-row:{token}"
            if key in added_ids:
                descriptions[key] = row["Description"]
    candidates = {r["observation_id"]: r["candidate_ids"] for r in plan["transfer_candidates"]}
    decisions = {r["observation_id"]: r for r in plan["decisions"]}
    transactions = []
    for decision in plan["decisions"]:
        key = decision["observation_id"]
        original = raw.get(decision["legacy_transaction_id"])
        observation = observations.get(key)
        posting_date = original["PostingDate"] if original else observation["posting_date"]
        amount = original["AmountMinor"] if original else observation["amount_minor"]
        desc = original["Description"] if original else descriptions[key]
        status = LABELS.get(decision["reason"], decision["reason"])
        origin = "Original record" if original else "Added from archived HSA statement"
        possible = candidates.get(key, [])
        details = [
            f"{names[decision['account_id']]} · {posting_date}",
            desc,
            money(amount),
            "",
            status,
            origin,
            f"Legacy category verified: {'Yes' if decision['legacy_verified'] else 'No'}",
            "Ledger interpretation confirmed: No",
        ]
        if decision["reason"] == "unconfirmed_transfer":
            details += [
                "",
                f"Possible counterparts within seven days: {len(possible)}",
                "These are suggestions, not confirmed transfers.",
            ]
            for other in possible:
                candidate = observations[other]
                candidate_decision = decisions[other]
                candidate_raw = raw.get(candidate_decision["legacy_transaction_id"])
                candidate_desc = candidate_raw["Description"] if candidate_raw else descriptions[other]
                details.append(
                    f"{names[candidate_decision['account_id']]} · {candidate['posting_date']} · {money(candidate['amount_minor'])} · {candidate_desc}"
                )
        transactions.append(
            {
                "cells": [
                    names[decision["account_id"]],
                    posting_date,
                    desc,
                    money(amount),
                    categories.get(decision["legacy_category_id"], "Uncategorized"),
                    status,
                    origin,
                ],
                "details": "\n".join(details),
            }
        )
    source_statements = {r["StatementID"]: r for r in legacy["Statements"]}
    statements = []
    for s in plan["statements"]:
        sid = int(s["id"].rsplit(":", 1)[-1])
        original = source_statements[sid]
        result = report["statement_results"][s["id"]]
        exceptions = [LABELS[x] for x in result["exceptions"]]
        statement_status = "Reconciled" if result["reconciled"] else "Needs review"
        evidence = (
            "Reparsed printed balances"
            if s["opening_provenance"] == s["closing_provenance"] == "reported"
            else "Legacy balances — not reverified"
        )
        statements.append(
            {
                "cells": [
                    names[original["AccountID"]],
                    s["start_date"],
                    s["end_date"],
                    money(original["EndBalanceMinor"]),
                    money(s["closing_minor"]),
                    evidence,
                    statement_status,
                ],
                "details": "\n".join(
                    [
                        f"Statement {sid}",
                        original["Filename"],
                        evidence,
                        "",
                        *exceptions,
                        "",
                        f"Opening difference: {money(result['opening_difference_minor'])}",
                        f"Closing difference: {money(result['closing_difference_minor'])}",
                        "Differences are retained; no balancing entries were created.",
                    ]
                ),
            }
        )
    gaps = []
    for gap in plan["continuity_exceptions"]:
        prior, later = [source_statements[sid] for sid in gap["statement_ids"]]
        gaps.append(
            {
                "cells": [
                    names[gap["account_id"]],
                    prior["EndDate"],
                    later["StartDate"],
                    money(gap["difference_minor"]),
                    "Printed balances" if gap["both_reported"] else "Legacy balances — not reverified",
                ],
                "details": "The next opening differs from the preceding closing.\nNo transaction or equity adjustment has been invented to bridge this gap.",
            }
        )
    openings = [
        {
            "cells": [names[r["account_id"]], r["date"], money(r["amount_minor"]), "Not posted — needs anchor review"],
            "details": "Proposed ledger anchor before the earliest statement period.\nThis is not a confirmed loan origination or cash receipt date.\nSource timing and balance provenance need review before posting.",
        }
        for r in plan["opening_proposals"]
    ]
    return {
        "summary": f"{len(legacy['Transactions']):,} original records preserved · {len(added_ids)} HSA rows added\n"
        f"{report['entry_count']:,} balanced category entries, all unreviewed · {report['reconciled_statement_count']} statements reconciled\n"
        "Transfers and uncertain records remain unresolved. Opening proposals have not been posted.",
        "tabs": [
            (
                "Transactions",
                ["Account", "Date", "Description", "Amount", "Legacy category", "Review status", "Source"],
                transactions,
            ),
            (
                "Statements",
                ["Account", "From", "Through", "Original closing", "Shadow closing", "Balance evidence", "Status"],
                statements,
            ),
            ("Balance gaps", ["Account", "Prior closing date", "Next opening date", "Difference", "Evidence"], gaps),
            ("Opening proposals", ["Account", "Proposed anchor date", "Amount", "Status"], openings),
        ],
    }


class PreviewModel(QAbstractTableModel):
    def __init__(self, headers, records, parent=None):
        super().__init__(parent)
        self.headers, self.records = headers, records

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            return self.records[index.row()]["cells"][index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None


class PreviewPage(QWidget):
    def __init__(self, headers, records, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter across all columns…")
        self.count = QLabel()
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.count)
        layout.addLayout(search_row)
        self.model = PreviewModel(headers, records, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, header in enumerate(headers):
            self.table.setColumnWidth(
                column, {"Description": 280, "Review status": 280, "Balance evidence": 240}.get(header, 140)
            )
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.details)
        splitter.setSizes([450, 180])
        layout.addWidget(splitter)
        self.search.textChanged.connect(self.filter)
        self.table.selectionModel().currentRowChanged.connect(self.show_details)
        self.filter("")

    def filter(self, text):
        self.proxy.setFilterFixedString(text)
        self.count.setText(f"{self.proxy.rowCount():,} of {self.model.rowCount():,}")
        self.table.clearSelection()
        self.table.setCurrentIndex(QModelIndex())
        self.details.clear()

    def show_details(self, current, _previous):
        if current.isValid():
            row = self.proxy.mapToSource(current).row()
            self.details.setPlainText(self.model.records[row]["details"])


class LedgerPreviewWindow(QMainWindow):
    def __init__(self, data: dict):
        super().__init__()
        self.setWindowTitle(data.get("window_title", "ParseTrail — Shadow ledger review (read only)"))
        self.resize(1280, 820)
        body = QWidget()
        layout = QVBoxLayout(body)
        title = QLabel(data.get("title", "Shadow ledger preview — live accounts and reports are unchanged"))
        title.setStyleSheet("font-size: 17px; font-weight: bold;")
        layout.addWidget(title)
        summary = QLabel(data["summary"])
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.tabs = QTabWidget()
        for name, headers, records in data["tabs"]:
            self.tabs.addTab(PreviewPage(headers, records), name)
        layout.addWidget(self.tabs)
        self.setCentralWidget(body)

"""Cached presentation of the headless full-window transfer plan."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_transfer_planning import pair_key
from parsetrail.gui.v2_cash_activity_review import _money
from parsetrail.gui.v2_settlement_review import reviewed_identity

PLAN_REASON = "Confirmed selected transfer plan"


@dataclass(frozen=True)
class PlanRow:
    pair: object
    status: str
    why: str
    explanation: str
    component: object
    selectable: bool
    included: bool = False


def presentation_rows(plan):
    """Describe service classifications; never choose or score financial pairs."""
    ready = {pair_key(p) for p in plan.ready_pairs}
    proposals = {pair_key(p.pair): p for p in plan.proposals}
    estimated = {pair_key(p) for p in plan.estimated_date_pairs}
    selectable = {pair_key(p) for p in plan.selectable_pairs}
    rows = []
    reasons = {
        "ties": "Equal best date alternatives; review manually",
        "oversized": "Too many alternatives for date planning; review manually",
        "estimated_dates": "Estimated-date alternatives; review manually",
        "date_blocked": "Posting date preference required",
        "tentative": "Not proposed by the date rule",
    }
    for component in plan.components:
        for pair in component.pairs:
            key = pair_key(pair)
            if key in ready:
                status, why = "Ready", "Only candidate on both legs in this date window"
            elif key in proposals:
                status, why = "Suggested", "Best overall date fit; check both sources"
            elif key in estimated:
                status, why = "Suggested", "Estimated posting date; explicit choice required"
            elif component.status == "tentative" and not component.unmatched_row_ids:
                status, why = "Alternative", "Not part of the date-based proposal; inspect in All matches"
            else:
                status, why = "Needs review", reasons.get(component.status, "Inspect alternatives manually")
            explanation = proposals[key].explanation if key in proposals else component.explanation
            included = key in ready and all(m.date_provenance != "assumed" for m in (pair.outgoing, pair.incoming))
            rows.append(PlanRow(pair, status, why, explanation, component, key in selectable, included))
    order = {"Ready": 0, "Suggested": 1, "Needs review": 2, "Alternative": 3}
    return tuple(sorted(rows, key=lambda row: (order[row.status], pair_key(row.pair))))


def _table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.horizontalHeader().setResizeContentsPrecision(100)
    for column in range(len(headers)):
        table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
    return table


def _put(table, row, values):
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        item.setToolTip(str(value))
        table.setItem(row, column, item)


class V2TransferPlanPage(QWidget):
    review_requested = Signal()
    alternatives_requested = Signal(object)

    def __init__(self, *, date_label, pair_details, parent=None):
        super().__init__(parent)
        self.date_label, self.pair_details = date_label, pair_details
        self.plan, self.rows = None, ()
        self._included = set()
        self._available = False
        layout = QVBoxLayout(self)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.counts = QLabel()
        self.counts.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.counts)
        self.qualification = QLabel(
            "Ready means only one candidate on both legs in this date window; check both sources. "
            "Suggested pairs use dates only and start unchecked. Highlighting a row shows details; "
            "only Include checkboxes select pairs for posting."
        )
        self.qualification.setWordWrap(True)
        layout.addWidget(self.qualification)
        self.table = _table(("Include", "Status", "Sent", "From", "Received", "To", "Amount", "Why"))
        for column in (3, 5, 7):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._changed)
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(115)
        layout.addWidget(self.details)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("Posting note (optional)"))
        self.note = QLineEdit()
        self.note.setMaxLength(200)
        self.note.setAccessibleName("Optional note for selected transfer plan")
        note_row.addWidget(self.note, 1)
        layout.addLayout(note_row)
        actions = QHBoxLayout()
        self.alternatives = QPushButton("Inspect alternatives in All matches")
        self.alternatives.setAutoDefault(False)
        self.alternatives.clicked.connect(self._inspect)
        actions.addWidget(self.alternatives)
        actions.addStretch()
        self.review = QPushButton("Review 0 selected pairs…")
        self.review.setAutoDefault(False)
        self.review.clicked.connect(self.review_requested)
        actions.addWidget(self.review)
        layout.addLayout(actions)
        self.clear("Finding transfers across the full profile…")

    def clear(self, message):
        self.plan, self.rows = None, ()
        self._included.clear()
        self._available = False
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        self.note.clear()
        self.scope.setText("Whole profile; loading the chosen date window and posting date policy.")
        self.counts.setText("Ready —  ·  Suggested —  ·  Needs review —")
        self.details.setPlainText("Select a pair to inspect its source descriptions, dates and alternatives.")
        self.status.setText(message)
        self.set_available(False)

    def set_plan(self, plan, *, note_limit):
        self.plan = plan
        self.rows = presentation_rows(plan)
        self._included = {pair_key(row.pair) for row in self.rows if row.included}
        selectable = {pair_key(p) for p in plan.selectable_pairs}
        groups = {row.component.component_id for row in self.rows if row.status == "Needs review"}
        groups.update(c.component_id for c in plan.components if c.unmatched_row_ids)
        self.scope.setText(
            f"Whole profile · maximum date gap {plan.max_day_gap} days · "
            f"best guess posting dates {'allowed' if plan.preferences.allow_assumed_posting_dates else 'disabled'}."
        )
        ready_count, suggested_count = len(plan.ready_pairs), len(plan.proposals) + len(plan.estimated_date_pairs)
        self.counts.setText(
            f"Ready {ready_count} {'pair' if ready_count == 1 else 'pairs'}  ·  "
            f"Suggested {suggested_count} {'pair' if suggested_count == 1 else 'pairs'}  ·  "
            f"Needs review {len(groups)} {'group' if len(groups) == 1 else 'groups'}"
        )
        self.note.setMaxLength(note_limit)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            p = row.pair
            _put(
                self.table,
                index,
                (
                    "",
                    row.status,
                    self.date_label(p.outgoing),
                    p.outgoing.account_name,
                    self.date_label(p.incoming),
                    p.incoming.account_name,
                    _money(-p.outgoing.amount_minor),
                    row.why,
                ),
            )
            include = self.table.item(index, 0)
            if pair_key(p) in selectable:
                include.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                include.setCheckState(Qt.Checked if row.included else Qt.Unchecked)
            else:
                include.setText("—")
                include.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            include.setToolTip(
                "Include this pair in the posting review"
                if row.selectable
                else "Review this pair manually in All matches"
            )
        self.table.blockSignals(False)
        unproposed = {r for c in plan.components for r in c.unmatched_row_ids}
        self.status.setText(
            f"{len(unproposed)} movements were not proposed by the date rule. Inspect alternatives in All matches."
            if unproposed
            else "Nothing is posted until you review and confirm the selected pairs."
            if self.rows
            else "No candidate pairs in this date window. Import and assign both sources, or change the date gap."
        )
        self.set_available(True)

    def set_available(self, available):
        self._available = available and self.plan is not None
        self.table.setEnabled(self._available)
        self.note.setEnabled(self._available and bool(self.plan.selectable_pairs))
        self._update_actions()

    def selected_keys(self):
        return tuple(sorted(self._included))

    def row_lookup(self):
        return {pair_key(row.pair): row for row in self.rows}

    def _changed(self, item):
        if item.column() != 0 or not 0 <= item.row() < len(self.rows):
            return
        row = self.rows[item.row()]
        if not row.selectable:
            return
        key = pair_key(row.pair)
        if item.checkState() == Qt.Checked:
            self._included.add(key)
        else:
            self._included.discard(key)
        self._update_actions()

    def _update_actions(self):
        count = len(self._included)
        self.review.setText(f"Review {count} selected {'pair' if count == 1 else 'pairs'}…")
        self.review.setEnabled(self._available and bool(count))
        self.alternatives.setEnabled(self._available and 0 <= self.table.currentRow() < len(self.rows))

    def _selected(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.rows):
            row = self.rows[index]
            component = row.component
            if component.status == "tentative":
                qualification = f"{len(component.unmatched_row_ids)} movements not proposed by the date rule."
            elif component.status == "ties":
                qualification = "Some alternatives share the best date fit and still need review."
                if row.status == "Suggested":
                    qualification = "This pair occurs in every best date fit. Other alternatives still need review."
            elif component.status in {"estimated_dates", "oversized", "date_blocked"}:
                qualification = "This group was not date-ranked. Inspect its dates and alternatives manually."
            else:
                qualification = "Unique candidate on both legs within the chosen date window."
            self.details.setPlainText(
                f"{row.status}: {row.why}.\n{self.pair_details(row.pair)}\n\n"
                f"Why: {row.explanation}\n{len(row.component.pairs)} candidate pairs in this group. "
                + qualification
                + " "
                + "Source descriptions are for your review; they are not structured matching evidence."
            )
        self._update_actions()

    def _inspect(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.rows):
            self.alternatives_requested.emit(self.rows[index].pair)


class V2TransferSelectionManifest(QDialog):
    def __init__(self, selection, rows, *, scope, reason, date_label, pair_details, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review selected transfer plan")
        self.resize(1100, 680)
        layout = QVBoxLayout(self)
        info = QLabel(
            scope + f"\nOnly these {len(selection.pairs)} pairs will be posted; "
            f"{selection.plan.candidate_count - len(selection.pairs)} candidate pairs are not selected. "
            "This may include alternative pairs; it is not a count of missing movements. "
            "Suggested pairs are tentative date-only proposals. Check both sources. "
            "No income or spending is created; both source dates are retained. "
            "Liability repayments do not establish a principal/interest split."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self.table = _table(("Status", "Sent", "From", "Received", "To", "Amount", "Why"))
        for column in (2, 4, 6):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
        self.table.setRowCount(len(selection.pairs))
        for index, p in enumerate(selection.pairs):
            row = rows[pair_key(p)]
            _put(
                self.table,
                index,
                (
                    row.status,
                    date_label(p.outgoing),
                    reviewed_identity(p.outgoing),
                    date_label(p.incoming),
                    reviewed_identity(p.incoming),
                    _money(-p.outgoing.amount_minor),
                    row.why,
                ),
            )
        layout.addWidget(self.table, 1)
        self.details = QPlainTextEdit("Select a pair to inspect both sources and the reason for its status.")
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(150)
        self.table.itemSelectionChanged.connect(
            lambda: self.details.setPlainText(
                pair_details(selection.pairs[self.table.currentRow()])
                + "\n\n"
                + rows[pair_key(selection.pairs[self.table.currentRow()])].explanation
                if 0 <= self.table.currentRow() < len(selection.pairs)
                else ""
            )
        )
        layout.addWidget(self.details)
        note = QLabel("Posting reason: " + reason)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        count = len(selection.pairs)
        self.post = self.buttons.addButton(
            f"Confirm and post {count} {'pair' if count == 1 else 'pairs'}", QDialogButtonBox.AcceptRole
        )
        self.post.setAutoDefault(False)
        self.post.clicked.connect(self.accept)
        self.buttons.button(QDialogButtonBox.Cancel).setDefault(True)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

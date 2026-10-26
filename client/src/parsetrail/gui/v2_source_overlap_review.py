"""Explicit review of possible repeated activity across saved V2 sources."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.gui.v2_cash_activity_review import _interpretation_effects, _money
from parsetrail.gui.v2_evidence_preview import _location, preview_saved_source

if TYPE_CHECKING:
    from parsetrail.core.v2_profile_store import SourceOverlapCandidate, SourceOverlapRow


STATE_LABELS = {
    "pending": "Pending review",
    "distinct": "Reviewed: distinct movements",
    "repeat": "Reviewed: same movement",
    "supporting": "Supporting evidence involved",
    "stale": "Review needs updating",
    "posted_conflict": "Both rows have journal history",
}


class _MoneyItem(QTableWidgetItem):
    def __init__(self, minor: int):
        super().__init__(_money(minor))
        self.minor = minor
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _MoneyItem):
            return self.minor < other.minor
        return super().__lt__(other)


def _row_details(row: SourceOverlapRow) -> str:
    return "\n".join(
        (
            f"Account: {row.account_name}",
            f"Source: {row.source_sha256}",
            f"Row: {row.row_id}",
            f"Source date: {row.source_date} ({row.date_role.replace('_', ' ')}, {row.date_provenance})",
            f"Signed source amount: {_money(row.amount_minor)}",
            f"Description: {row.description or 'Not printed'}",
            "Source locations:",
            *(f"  {_source_location(location)}" for location in row.locations),
            f"Active source allocation: {_money(row.active_allocated_minor)}",
            f"Journal history: {'Yes' if row.has_journal_history else 'None'}",
            f"Validated prior repeat repair with no active allocation: {'Yes' if row.repeat_support_history_validated else 'No'}",
        )
    )


def _source_location(value: str) -> str:
    try:
        location = SimpleNamespace(**json.loads(value))
        text = _location(location)
        if location.kind == "pdf_line" and location.end_line is not None:
            text += f" through line {location.end_line}"
        return text
    except (ValueError, TypeError, AttributeError):
        return value


class V2SourceOverlapReview(QDialog):
    """Save evidence relationships without merging imports or changing journals."""

    HEADERS = (
        "Account",
        "Source date",
        "Signed amount",
        "Review state",
        "Source A description",
        "Source B description",
    )

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.candidates: tuple[SourceOverlapCandidate, ...] = ()
        self.repair_preview = None
        self.setWindowTitle("2.0 repeated source rows")
        self.resize(1180, 760)
        layout = QVBoxLayout(self)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self.profile_path = QLineEdit(str(profile))
        self.profile_path.setReadOnly(True)
        self.profile_path.setCursorPosition(0)
        profile_row.addWidget(self.profile_path)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        profile_row.addWidget(self.refresh_button)
        layout.addLayout(profile_row)
        self.note = QLabel(
            "Candidates share an explicitly bound account, signed amount, source date and date role across different sources. "
            "Matching values do not prove a repeated movement. Unresolved candidates block new postings. "
            "Review the source evidence and choose distinct movements or retain one occurrence of the same movement. "
            "Shifted dates, different date roles and unbound rows are outside this matcher; an empty list does not establish "
            "unique or complete source coverage. Period overlap and reconciliation remain separate."
        )
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        for column, width in enumerate((150, 100, 105, 215)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        for column in (4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table, 2)
        self.details_state = QLabel()
        self.details_state.setWordWrap(True)
        self.details_state.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details_state)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left_details = QPlainTextEdit()
        self.right_details = QPlainTextEdit()
        self.preview_left = QPushButton("Open source A evidence")
        self.preview_right = QPushButton("Open source B evidence")
        self.preview_left.clicked.connect(lambda: self._preview("left"))
        self.preview_right.clicked.connect(lambda: self._preview("right"))
        for title, details, preview in (
            ("Source A", self.left_details, self.preview_left),
            ("Source B", self.right_details, self.preview_right),
        ):
            panel = QWidget()
            side_layout = QVBoxLayout(panel)
            side_layout.setContentsMargins(0, 0, 0, 0)
            side_layout.addWidget(QLabel(title))
            details.setReadOnly(True)
            side_layout.addWidget(details)
            side_layout.addWidget(preview)
            splitter.addWidget(panel)
        layout.addWidget(splitter, 2)
        form = QFormLayout()
        self.decision = QComboBox()
        self.decision.addItem("Choose a review decision", None)
        self.decision.addItem("Distinct movements — both may be reviewed for posting", "distinct")
        self.decision.addItem("Same movement — retain A; B is supporting evidence", "retain_left")
        self.decision.addItem("Same movement — retain B; A is supporting evidence", "retain_right")
        self.decision.addItem("Return this pair to pending review", "pending")
        self.decision.currentIndexChanged.connect(self._update_action)
        form.addRow("Decision", self.decision)
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        self.reason.setPlaceholderText("Required: evidence and reason for this decision")
        self.reason.textChanged.connect(self._update_action)
        form.addRow("Reason", self.reason)
        layout.addLayout(form)
        self.review_note = QLabel(
            "Saving a review fixes these account assignments; returning to pending preserves that history. "
            "Check the bound accounts before saving."
        )
        self.review_note.setWordWrap(True)
        layout.addWidget(self.review_note)
        self.save_button = QPushButton("Save source-row review")
        self.save_button.clicked.connect(self._save)
        layout.addWidget(self.save_button)
        self.repair_button = QPushButton("Repair posted repeat — retain selected occurrence")
        self.repair_button.clicked.connect(self._repair)
        layout.addWidget(self.repair_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _current(self) -> SourceOverlapCandidate | None:
        item = self.table.item(self.table.currentRow(), 0)
        index = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return self.candidates[index] if isinstance(index, int) and 0 <= index < len(self.candidates) else None

    def refresh(self, *_args) -> None:
        pair = self._current()
        selected_ids = (pair.left.row_id, pair.right.row_id) if pair is not None else None
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                inventory = store.source_overlap_inventory()
        except (ProfileFormatError, sqlite3.Error, OSError):
            self.candidates = ()
            self.table.setRowCount(0)
            self.summary.setText("Candidate inventory could not be read. Refresh after checking the profile.")
            self._selected()
            return
        self.candidates = inventory.candidates
        summary = f"{inventory.total_pairs} candidate pair(s); {len(self.candidates)} shown."
        if inventory.truncated:
            summary += (
                " Display limit reached. Additional pairs are still checked before posting; this list is incomplete."
            )
        self.summary.setText(summary)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.candidates))
        selected_row = None
        for index, candidate in enumerate(self.candidates):
            values = (
                candidate.left.account_name,
                candidate.left.source_date,
                _money(candidate.left.amount_minor),
                STATE_LABELS.get(candidate.state, candidate.state),
                candidate.left.description or "Not printed",
                candidate.right.description or "Not printed",
            )
            for column, value in enumerate(values):
                item = _MoneyItem(candidate.left.amount_minor) if column == 2 else QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setToolTip(value)
                self.table.setItem(index, column, item)
            if (candidate.left.row_id, candidate.right.row_id) == selected_ids:
                selected_row = index
        if selected_row is not None:
            self.table.selectRow(selected_row)
        self.table.setSortingEnabled(True)
        self._selected()

    def _selected(self) -> None:
        pair = self._current()
        self.repair_preview = None
        self.decision.setCurrentIndex(0)
        self.reason.clear()
        self.preview_left.setEnabled(pair is not None)
        self.preview_right.setEnabled(pair is not None)
        indirect = pair is not None and (
            pair.state == "supporting"
            or (pair.state == "repeat" and pair.retained_row_id not in {pair.left.row_id, pair.right.row_id})
        )
        self.decision.setEnabled(pair is not None and not indirect)
        self.reason.setEnabled(pair is not None and not indirect)
        if pair is None:
            self.left_details.clear()
            self.right_details.clear()
            self.details_state.setText("Select a candidate pair to compare its immutable source evidence.")
            self.status.setText(
                "Select a pair to review."
                if self.candidates
                else "No candidate pairs shown. Import and bind sources first; unmatched evidence remains outside this review."
            )
        else:
            self.left_details.setPlainText(_row_details(pair.left))
            self.right_details.setPlainText(_row_details(pair.right))
            detail = STATE_LABELS.get(pair.state, pair.state)
            if pair.revision_id is not None:
                detail += f"; saved review revision {pair.revision_id}"
            if pair.retained_row_id is not None:
                if pair.retained_row_id in {pair.left.row_id, pair.right.row_id}:
                    retained = "A" if pair.retained_row_id == pair.left.row_id else "B"
                    detail += f"; retained occurrence: {retained}"
                else:
                    detail += f"; retained occurrence is in another pair: {pair.retained_row_id}"
                    if pair.state == "supporting":
                        detail += ". This pair itself has no same-movement assertion."
            self.details_state.setText(detail)
            self.status.setText(
                "Both rows have journal history. Confirm distinct movements only if supported by the evidence. "
                "A repeated movement needs journal correction beyond this review; existing entries are unchanged."
                if pair.left.has_journal_history and pair.right.has_journal_history
                else "A repeated row becomes supporting evidence and cannot post independently. This review posts no money."
            )
            if indirect:
                self.status.setText(
                    "One or both rows already support a retained occurrence in another pair. "
                    "This pair cannot change that decision. Select the pair containing the retained row to review it."
                )
            elif (
                pair.left.active_allocated_minor == pair.left.amount_minor
                and pair.right.active_allocated_minor == pair.right.amount_minor
            ):
                self.repair_preview = self._load_repair_preview(pair)
                if self.repair_preview is not None:
                    self.status.setText(
                        "Both occurrences have supported active interpretations. If the sources describe one movement, "
                        "choose the occurrence to retain and use Repair posted repeat. Ordinary evidence review cannot retire money."
                    )
        self._update_action()

    def _load_repair_preview(self, pair):
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                account = next(account for account in store.financial_accounts() if account.id == pair.left.account_id)
                kind = "cash" if account.kind == "asset" else "card"
                previews = []
                for source_row in (pair.left, pair.right):
                    snapshot = store.source_interpretation_snapshot(
                        source_row.source_sha256, kind=kind, preferences=V2Preferences() if kind == "card" else None
                    )
                    if snapshot.basis_sha256 != pair.basis_sha256:
                        return None
                    row = next(row for row in snapshot.rows if row.row_id == source_row.row_id)
                    entry = next(entry for entry in snapshot.entries if entry.key == row.entry_key)
                    effects = _interpretation_effects(entry, row, snapshot.categories, financial_kind=account.kind)
                    if effects is None:
                        return None
                    previews.append((row, entry, snapshot.categories, effects))
                return tuple(previews)
        except (ProfileFormatError, sqlite3.Error, OSError, StopIteration):
            return None

    def _update_action(self, *_args) -> None:
        pair = self._current()
        choice = self.decision.currentData()
        supported = pair is not None and choice is not None and self.decision.isEnabled()
        if supported and choice == "retain_left":
            supported = not pair.right.has_journal_history or (
                pair.right.repeat_support_history_validated and pair.right.active_allocated_minor == 0
            )
        elif supported and choice == "retain_right":
            supported = not pair.left.has_journal_history or (
                pair.left.repeat_support_history_validated and pair.left.active_allocated_minor == 0
            )
        self.save_button.setEnabled(bool(supported and self.reason.text().strip()))
        self.repair_button.setEnabled(
            self.repair_preview is not None
            and self.decision.isEnabled()
            and choice in {"retain_left", "retain_right"}
            and bool(self.reason.text().strip())
        )
        if (
            pair is not None
            and self.decision.isEnabled()
            and choice in {"retain_left", "retain_right"}
            and not supported
        ):
            self.status.setText(
                "The supporting row has journal history and cannot be excluded by ordinary evidence review. "
                + (
                    "Use Repair posted repeat to explicitly retire its supported active interpretation."
                    if self.repair_preview is not None
                    else "Its interpretation is outside the supported repeat repair workflow."
                )
            )

    def _preview(self, side: str) -> None:
        pair = self._current()
        if pair is None:
            return
        row = pair.left if side == "left" else pair.right
        try:
            preview_saved_source(self.profile, row.source_sha256, parent=self).exec()
        except (ProfileFormatError, sqlite3.Error, OSError):
            QMessageBox.warning(
                self, "Evidence could not be opened", "Refresh the inventory and try opening the saved source again."
            )

    def _save(self) -> None:
        pair = self._current()
        choice = self.decision.currentData()
        if pair is None or choice is None or not self.save_button.isEnabled():
            return
        decision = "repeat" if choice in {"retain_left", "retain_right"} else choice
        retained = (
            pair.left.row_id if choice == "retain_left" else pair.right.row_id if choice == "retain_right" else None
        )
        reason = self.reason.text().strip()
        message = (
            self.decision.currentText()
            + "?\n\n"
            + reason
            + "\n\nSource evidence and existing journal entries remain unchanged."
        )
        if QMessageBox.question(self, "Confirm source-row review", message) != QMessageBox.StandardButton.Yes:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                store.record_source_overlap_review(
                    pair.left.row_id,
                    pair.right.row_id,
                    decision=decision,
                    retained_row_id=retained,
                    reason=reason,
                    expected_basis_sha256=pair.basis_sha256,
                )
        except (ProfileFormatError, sqlite3.Error, OSError):
            self.refresh()
            self.status.setText(
                "Review was not saved. The source bindings, allocations or another review may have changed, "
                "or this decision conflicts with journal history or another retained occurrence. "
                "Inspect the refreshed pair before trying again."
            )
            return
        self.refresh()
        self.status.setText("Source-row review saved. No journal entries were created or changed.")

    def _repair(self) -> None:
        pair, choice, reason = self._current(), self.decision.currentData(), self.reason.text().strip()
        if pair is None or self.repair_preview is None or not self.repair_button.isEnabled():
            return
        keep_index = 0 if choice == "retain_left" else 1
        retained, redundant = (pair.left, pair.right) if keep_index == 0 else (pair.right, pair.left)
        kept_row, kept_entry, kept_categories, _effects = self.repair_preview[keep_index]
        _row, _entry, _categories, inverse = self.repair_preview[1 - keep_index]
        category = next(category for category in kept_categories if category.id == kept_row.category_id)
        message = (
            f"Repair two posted occurrences of one movement?\n\nRetain {'A' if keep_index == 0 else 'B'}: "
            f"{kept_row.financial_account}, {category.name}, {kept_entry.posting_date.isoformat()}; "
            f"entry {kept_entry.key}. Its postings remain unchanged.\n\n"
            f"Retire the other active interpretation with these exact inverse effects:\n{inverse}\n\nReason: {reason}\n\n"
            "The redundant entry is reversed at its own accounting date and its allocation is released. "
            "The repeated source row becomes supporting evidence, not another allocation. "
            "The retirement and repeat decision commit together. All original entries, corrections and source evidence remain history."
        )
        if QMessageBox.question(self, "Confirm posted-repeat repair", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                store.repair_posted_repeat(
                    retained.row_id, redundant.row_id, expected_basis_sha256=pair.basis_sha256, reason=reason
                )
        except (ProfileFormatError, sqlite3.Error, OSError):
            self.refresh()
            self.status.setText(
                "Posted repeat was not repaired. Source bindings, active interpretations or another review changed or the repair is unsupported. Inspect the refreshed pair."
            )
            return
        self.refresh()
        self.status.setText(
            "The selected pair's posted-repeat repair is recorded. Refreshed source allocations show the current state; "
            "original and inverse entries remain history."
        )

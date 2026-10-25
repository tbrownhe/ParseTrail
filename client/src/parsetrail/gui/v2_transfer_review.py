"""Explicit cross-source review of owned-account transfers and card payments."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from parsetrail.core.v2_profile_store import ProfileFormatError, TransferCandidate, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_cash_activity_review import _money


class V2TransferReview(QDialog):
    """A candidate is only a suggestion until the owner selects and confirms it."""

    HEADERS = ("Type", "Sent", "From", "Received", "To", "Amount", "Other matches", "Source descriptions")

    def __init__(self, workspace: V2Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.candidates: tuple[TransferCandidate, ...] = ()
        self.setWindowTitle("2.0 transfer and card payment review")
        self.resize(1250, 650)
        layout = QVBoxLayout(self)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self.profile_path = QLineEdit(str(workspace.profile_path))
        self.profile_path.setReadOnly(True)
        self.profile_path.setCursorPosition(0)
        profile_row.addWidget(self.profile_path)
        layout.addLayout(profile_row)
        note = QLabel(
            "Equal and opposite movements are suggestions only. Confirm the pair from both sources. "
            "A card repayment moves cash to the card liability and does not add spending. "
            "Different source dates use transfer clearing. Fees, partial payments, and other unmatched movements stay pending."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Maximum date gap (days)"))
        self.gap = QSpinBox()
        self.gap.setRange(0, 31)
        self.gap.setValue(7)
        self.gap.valueChanged.connect(self.refresh)
        controls.addWidget(self.gap)
        self.assumed_dates = QCheckBox("Allow best guess posting dates when a statement does not print one")
        self.assumed_dates.setChecked(workspace.preferences().allow_assumed_posting_dates)
        self.assumed_dates.toggled.connect(self._toggle_assumed_dates)
        controls.addWidget(self.assumed_dates)
        controls.addStretch()
        layout.addLayout(controls)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        for column in range(len(self.HEADERS) - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(self.HEADERS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.note = QLineEdit()
        self.note.setMaxLength(450)
        self.note.setPlaceholderText("Optional note about this pair")
        layout.addWidget(self.note)
        self.confirm = QPushButton("Confirm and post selected pair")
        self.confirm.clicked.connect(self._post)
        layout.addWidget(self.confirm)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _current(self) -> TransferCandidate | None:
        index = self.table.currentRow()
        return self.candidates[index] if 0 <= index < len(self.candidates) else None

    def _selected(self) -> None:
        pair = self._current()
        self.confirm.setEnabled(pair is not None and pair.posting_allowed)
        if pair is None:
            if self.candidates:
                self.status.setText(f"{len(self.candidates)} candidate pair(s). Select one to inspect and confirm.")
            else:
                self.status.setText(
                    "No candidate pairs in this profile and date window. Import both sources, assign their "
                    "financial accounts, or widen the date gap. Unmatched movements remain pending."
                )
        elif not pair.posting_allowed:
            self.status.setText(
                "This pair includes an assumed card date. Enable best guess posting dates to confirm it."
            )
        else:
            self.status.setText(
                f"{pair.kind.capitalize()}; {pair.day_gap} day(s) between source dates. "
                "Check both descriptions and sources before confirming."
            )

    def refresh(self, *_args) -> None:
        selected = self._current()
        selected_ids = (selected.outgoing.row_id, selected.incoming.row_id) if selected is not None else None
        with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
            self.candidates = store.transfer_candidates(
                preferences=self.workspace.preferences(), max_day_gap=self.gap.value()
            )
        out_counts: dict[str, int] = {}
        in_counts: dict[str, int] = {}
        for pair in self.candidates:
            out_counts[pair.outgoing.row_id] = out_counts.get(pair.outgoing.row_id, 0) + 1
            in_counts[pair.incoming.row_id] = in_counts.get(pair.incoming.row_id, 0) + 1
        self.table.setRowCount(len(self.candidates))
        for index, pair in enumerate(self.candidates):
            values = (
                pair.kind.capitalize(),
                pair.outgoing.posting_date,
                pair.outgoing.account_name,
                pair.incoming.posting_date + (" (assumed)" if pair.incoming.date_provenance == "assumed" else ""),
                pair.incoming.account_name,
                _money(-pair.outgoing.amount_minor),
                f"{out_counts[pair.outgoing.row_id] - 1} / {in_counts[pair.incoming.row_id] - 1}",
                f"{pair.outgoing.description}  /  {pair.incoming.description}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.table.setItem(index, column, item)
        if selected_ids is not None:
            for index, pair in enumerate(self.candidates):
                if (pair.outgoing.row_id, pair.incoming.row_id) == selected_ids:
                    self.table.selectRow(index)
                    break
        self._selected()

    def _toggle_assumed_dates(self, enabled: bool) -> None:
        try:
            self.workspace.set_allow_assumed_posting_dates(enabled)
        except (OSError, ValueError) as exc:
            self.assumed_dates.blockSignals(True)
            self.assumed_dates.setChecked(not enabled)
            self.assumed_dates.blockSignals(False)
            QMessageBox.warning(self, "Preference was not saved", str(exc))
            return
        self.refresh()

    def _post(self) -> None:
        pair = self._current()
        if pair is None or not pair.posting_allowed:
            return
        outgoing, incoming = pair.outgoing, pair.incoming
        message = (
            f"Confirm this {pair.kind}?\n\n"
            f"From: {outgoing.account_name}, {_money(outgoing.amount_minor)}, {outgoing.posting_date}\n"
            f"{outgoing.description}\nSource {outgoing.source_sha256[:16]}… / row {outgoing.row_id}\n\n"
            f"To: {incoming.account_name}, {_money(incoming.amount_minor)}, {incoming.posting_date}"
            f" ({incoming.date_provenance})\n"
            f"{incoming.description}\nSource {incoming.source_sha256[:16]}… / row {incoming.row_id}\n\n"
            "No income or expense is created. The two source dates are preserved."
        )
        if QMessageBox.question(self, "Confirm transfer pair", message) != QMessageBox.StandardButton.Yes:
            return
        reason = "Confirmed owned-account transfer"
        if self.note.text().strip():
            reason += ": " + self.note.text().strip()
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.post_reviewed_transfer(
                    outgoing.row_id, incoming.row_id, preferences=self.workspace.preferences(), reason=reason
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Transfer was not posted", str(exc))
            self.refresh()
            return
        self.note.clear()
        self.refresh()
        self.status.setText("Transfer pair posted; both source movements are allocated.")

"""Explicit cross-source review of owned-account transfers and card payments."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_profile_store import ProfileFormatError, TransferCandidate, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_cash_activity_review import _money
from parsetrail.gui.v2_settlement_review import (
    V2SettlementReview,
    expected_identity,
    reviewed_identity,
    settlement_details,
)


def _pair_key(pair):
    return pair.outgoing.row_id, pair.incoming.row_id


def _pair_details(pair, *, inverse=False):
    result = []
    for title, movement in (("From", pair.outgoing), ("To", pair.incoming)):
        natural = 1 if movement.account_kind == "asset" else -1
        amount = movement.amount_minor * natural * (-1 if inverse else 1)
        direction = "asset value" if movement.account_kind == "asset" else "amount owed"
        result.append(
            f"{title}: {reviewed_identity(movement)}; {direction} change {_money(amount)} on {movement.posting_date} "
            f"({movement.date_provenance}). "
            + (
                movement.description
                if movement.source_description_known
                else f"Source description unavailable; accounting label only: {movement.description}"
            )
            + "\n"
            f"Source {movement.source_sha256}; row {movement.row_id}."
        )
    return "\n".join(result)


def _history_table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    for column in range(len(headers) - 1):
        table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(len(headers) - 1, QHeaderView.Stretch)
    return table


def _fill_table(table, rows):
    table.blockSignals(True)
    table.clearSelection()
    table.setCurrentCell(-1, -1)
    table.setRowCount(len(rows))
    for index, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(index, column, item)
    table.blockSignals(False)


class V2TransferReview(QDialog):
    """A candidate is only a suggestion until the owner selects and confirms it."""

    HEADERS = ("Type", "Sent", "From", "Received", "To", "Amount", "Other matches", "Source descriptions")

    def __init__(self, workspace: V2Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.candidates: tuple[TransferCandidate, ...] = ()
        self.events, self.pair_reviews, self.replacements = (), (), ()
        self.basis, self.event_basis, self.selected_event = None, None, None
        self.setWindowTitle("2.0 transfer and card payment review")
        self.resize(1250, 750)
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
            "Different source dates use transfer clearing. Corrections withdraw or replace the whole confirmed event. "
            "Dismissal changes suggestions only; its evidence remains pending. Use the full settlement review for explicit fees, multiple or partial receipts, or an owned outflow awaiting receipt evidence."
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
        reload_button = QPushButton("Reload saved state")
        reload_button.clicked.connect(self.refresh)
        controls.addWidget(reload_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.tabs = QTabWidget()
        suggestions = QWidget()
        suggestions_layout = QVBoxLayout(suggestions)
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
        suggestions_layout.addWidget(self.table)
        self.status = QLabel()
        self.status.setWordWrap(True)
        suggestions_layout.addWidget(self.status)
        self.note = QLineEdit()
        self.note.setMaxLength(450)
        self.note.setPlaceholderText("Optional posting note; required reason to dismiss a suggestion")
        self.note.textChanged.connect(self._selected)
        suggestions_layout.addWidget(self.note)
        self.confirm = QPushButton("Confirm and post selected pair")
        self.confirm.clicked.connect(self._post)
        self.dismiss = QPushButton("Dismiss selected suggestion")
        self.dismiss.clicked.connect(self._dismiss)
        suggestion_actions = QHBoxLayout()
        suggestion_actions.addWidget(self.confirm)
        suggestion_actions.addWidget(self.dismiss)
        suggestions_layout.addLayout(suggestion_actions)
        self.tabs.addTab(suggestions, "Suggestions")
        self.full_settlement = QPushButton("Review transfer fees / partial settlements…")
        self.full_settlement.clicked.connect(self._new_settlement)
        layout.addWidget(self.full_settlement)
        self._build_history_tabs()
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _build_history_tabs(self):
        confirmed = QWidget()
        layout = QVBoxLayout(confirmed)
        self.event_table = _history_table(
            ("State", "Type", "Sent", "From", "Received", "To", "Amount", "Legs", "Reason")
        )
        self.event_table.itemSelectionChanged.connect(self._event_selected)
        layout.addWidget(self.event_table)
        self.event_details = QPlainTextEdit(
            "Select a confirmed event to inspect its complete effect and retained history."
        )
        self.event_details.setReadOnly(True)
        self.event_details.setMaximumHeight(180)
        layout.addWidget(self.event_details)
        self.review_settlement = QPushButton("Inspect / replace complete settlement manifest…")
        self.review_settlement.clicked.connect(self._open_settlement)
        layout.addWidget(self.review_settlement)
        replacement_row = QHBoxLayout()
        replacement_row.addWidget(QLabel("Replacement pair"))
        self.replacement = QComboBox()
        self.replacement.currentIndexChanged.connect(self._event_actions)
        replacement_row.addWidget(self.replacement, 1)
        layout.addLayout(replacement_row)
        self.replacement_details = QLabel("Select an active event to load eligible replacement pairs.")
        self.replacement_details.setWordWrap(True)
        layout.addWidget(self.replacement_details)
        self.correction_reason = QLineEdit()
        self.correction_reason.setMaxLength(500)
        self.correction_reason.setPlaceholderText("Required reason to withdraw or replace the whole event")
        self.correction_reason.textChanged.connect(self._event_actions)
        layout.addWidget(self.correction_reason)
        actions = QHBoxLayout()
        self.withdraw = QPushButton("Withdraw whole event")
        self.withdraw.clicked.connect(self._withdraw)
        actions.addWidget(self.withdraw)
        self.replace = QPushButton("Replace with selected pair")
        self.replace.clicked.connect(self._replace)
        actions.addWidget(self.replace)
        layout.addLayout(actions)
        self.event_status = QLabel()
        self.event_status.setWordWrap(True)
        layout.addWidget(self.event_status)
        self.tabs.addTab(confirmed, "Confirmed events")
        reviews = QWidget()
        layout = QVBoxLayout(reviews)
        scope = QLabel(
            "Suggestion decisions retain their reason and source/account context. Reopening changes no money or allocations."
        )
        scope.setWordWrap(True)
        layout.addWidget(scope)
        self.review_table = _history_table(
            ("Decision", "Sent / from", "Received / to", "Amount", "Context", "Saved at (UTC)", "Reason")
        )
        self.review_table.itemSelectionChanged.connect(self._review_selected)
        layout.addWidget(self.review_table)
        self.review_details = QLabel("No suggestion decisions saved.")
        self.review_details.setWordWrap(True)
        self.review_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.review_details)
        self.reopen_reason = QLineEdit()
        self.reopen_reason.setMaxLength(500)
        self.reopen_reason.setPlaceholderText("Required reason to reopen the latest dismissed suggestion")
        self.reopen_reason.textChanged.connect(self._review_actions)
        layout.addWidget(self.reopen_reason)
        self.reopen = QPushButton("Reopen dismissed suggestion")
        self.reopen.clicked.connect(self._reopen)
        layout.addWidget(self.reopen)
        self.tabs.addTab(reviews, "Suggestion history")

    def _current(self) -> TransferCandidate | None:
        index = self.table.currentRow()
        return self.candidates[index] if 0 <= index < len(self.candidates) else None

    def _selected(self) -> None:
        pair = self._current()
        self.confirm.setEnabled(pair is not None and pair.posting_allowed and self.basis is not None)
        self.dismiss.setEnabled(pair is not None and bool(self.note.text().strip()) and self.basis is not None)
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
        preferences = self.workspace.preferences()
        self.assumed_dates.blockSignals(True)
        self.assumed_dates.setChecked(preferences.allow_assumed_posting_dates)
        self.assumed_dates.blockSignals(False)
        selected = self._current()
        selected_ids = (selected.outgoing.row_id, selected.incoming.row_id) if selected is not None else None
        event_id = self.selected_event.event_id if self.selected_event else None
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                snapshot = store.transfer_review_snapshot(preferences=preferences, max_day_gap=self.gap.value())
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.basis = None
            self.candidates, self.events, self.pair_reviews = (), (), ()
            _fill_table(self.table, ())
            _fill_table(self.event_table, ())
            _fill_table(self.review_table, ())
            self._clear_event()
            self._selected()
            self._review_selected()
            self.status.setText(f"Transfer review unavailable. Reload to retry: {exc}")
            self.event_status.setText(self.status.text())
            return
        self.basis = snapshot.basis_sha256
        self.candidates, self.events, self.pair_reviews = snapshot.candidates, snapshot.events, snapshot.pair_reviews
        out_counts: dict[str, int] = {}
        in_counts: dict[str, int] = {}
        for pair in self.candidates:
            out_counts[pair.outgoing.row_id] = out_counts.get(pair.outgoing.row_id, 0) + 1
            in_counts[pair.incoming.row_id] = in_counts.get(pair.incoming.row_id, 0) + 1
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
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
                item.setToolTip(_pair_details(pair))
                self.table.setItem(index, column, item)
        self.table.blockSignals(False)
        _fill_table(
            self.event_table,
            tuple(
                (
                    event.status.title(),
                    event.pair.kind.capitalize() if event.pair is not None else f"Full {event.settlement.kind}",
                    event.settlement.outgoing.posting_date,
                    reviewed_identity(event.settlement.outgoing),
                    event.pair.incoming.posting_date
                    if event.pair is not None
                    else f"{len(event.settlement.incoming)} dated receipt(s)",
                    reviewed_identity(event.pair.incoming)
                    if event.pair is not None
                    else (
                        "Receipt missing; expected owned: "
                        + expected_identity(event.settlement.expected_destination)
                        + f"; {_money(event.settlement.residual_minor)} clearing"
                    )
                    if event.settlement.expected_destination is not None
                    else "; ".join(dict.fromkeys(reviewed_identity(m) for m in event.settlement.incoming))
                    + f"; {_money(event.settlement.residual_minor)} clearing",
                    _money(-event.settlement.outgoing.amount_minor),
                    len(event.entry_keys),
                    event.reason,
                )
                for event in self.events
            ),
        )
        _fill_table(
            self.review_table,
            tuple(
                (
                    review.decision.title(),
                    f"{review.pair.outgoing.posting_date} / {review.pair.outgoing.account_name}",
                    f"{review.pair.incoming.posting_date} / {review.pair.incoming.account_name}",
                    _money(-review.pair.outgoing.amount_minor),
                    "Current context" if review.context_current else "Context changed",
                    review.created_at,
                    review.reason,
                )
                for review in self.pair_reviews
            ),
        )
        self._clear_event()
        if selected_ids is not None:
            for index, pair in enumerate(self.candidates):
                if (pair.outgoing.row_id, pair.incoming.row_id) == selected_ids:
                    self.table.selectRow(index)
                    break
        if event_id is not None:
            for index, event in enumerate(self.events):
                if event.event_id == event_id:
                    self.event_table.selectRow(index)
                    break
        self._selected()
        self._review_selected()

    def _clear_event(self):
        self.selected_event, self.event_basis, self.replacements = None, None, ()
        self.replacement.clear()
        self.withdraw.setEnabled(False)
        self.replace.setEnabled(False)
        self.review_settlement.setEnabled(False)
        self.event_details.setPlainText("Select a confirmed event to inspect its complete effect and retained history.")
        self.replacement_details.setText("Select an active event to load eligible replacement pairs.")
        self.event_status.clear()

    def _event_selected(self):
        index = self.event_table.currentRow()
        self._clear_event()
        if not 0 <= index < len(self.events):
            return
        event = self.events[index]
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=True) as store:
                snapshot = store.transfer_review_snapshot(
                    preferences=self.workspace.preferences(),
                    max_day_gap=self.gap.value(),
                    replacing_event_id=event.event_id if event.status == "active" else None,
                )
            event = next(item for item in snapshot.events if item.event_id == event.event_id)
        except (ProfileFormatError, sqlite3.Error, OSError, StopIteration) as exc:
            self.event_status.setText(f"Selected event unavailable or changed. Reload saved state: {exc}")
            return
        self.selected_event, self.event_basis = event, snapshot.basis_sha256
        self.review_settlement.setEnabled(True)
        self.event_details.setPlainText(
            f"{event.status.title()} {event.settlement.kind}; {len(event.entry_keys)} journal leg(s); "
            f"{len(event.settlement.incoming)} receipt(s), {len(event.settlement.fees)} explicit fee(s). Original reason: {event.reason}. "
            f"Action reason: {event.action_reason or 'none'}. Replacement event: {event.replacement_event_id or 'none'}.\n"
            f"{settlement_details(event.settlement)}\nEvent: {event.event_id}; version: {event.version}."
        )
        self.replacements = snapshot.candidates if event.status == "active" and event.pair is not None else ()
        self.replacement.blockSignals(True)
        self.replacement.addItem("Choose a replacement pair", None)
        for index, pair in enumerate(self.replacements):
            self.replacement.addItem(
                f"{pair.outgoing.account_name} {pair.outgoing.posting_date} → "
                f"{pair.incoming.account_name} {pair.incoming.posting_date}; {_money(-pair.outgoing.amount_minor)}",
                index,
            )
        self.replacement.blockSignals(False)
        self.event_status.clear()
        self._event_actions()

    def _new_settlement(self):
        V2SettlementReview(self.workspace, parent=self).exec()
        self.refresh()

    def _open_settlement(self):
        event = self.selected_event
        if event is not None:
            V2SettlementReview(self.workspace, event_id=event.event_id, parent=self).exec()
            self.refresh()

    def _event_actions(self, *_args):
        event = self.selected_event
        ready = (
            event is not None
            and event.status == "active"
            and self.event_basis is not None
            and bool(self.correction_reason.text().strip())
        )
        self.withdraw.setEnabled(ready)
        index = self.replacement.currentData()
        pair = self.replacements[index] if isinstance(index, int) and 0 <= index < len(self.replacements) else None
        different_pair = (
            event is not None
            and event.pair is not None
            and pair is not None
            and _pair_key(pair) != _pair_key(event.pair)
        )
        self.replace.setEnabled(ready and different_pair and pair.posting_allowed)
        if pair:
            natural = 1 if pair.incoming.account_kind == "asset" else -1
            self.replacement_details.setText(
                f"{pair.outgoing.account_name}: asset change {_money(pair.outgoing.amount_minor)} on {pair.outgoing.posting_date}; "
                f"{pair.incoming.account_name}: {'asset value' if natural == 1 else 'amount owed'} change "
                f"{_money(natural * pair.incoming.amount_minor)} on {pair.incoming.posting_date}. "
                + (
                    "Confirm both sources before replacing."
                    if pair.posting_allowed
                    else "Assumed dates require the global best guess choice."
                )
            )
            if not different_pair:
                self.replacement_details.setText(
                    "Choose a different pair. The selected pair is already this event's interpretation."
                )
        else:
            self.replacement_details.setText(
                "This event uses a complete settlement manifest. Inspect / replace it above; a pair cannot represent all of its receipts and fees."
                if event is not None and event.pair is None
                else "Choose an eligible replacement pair; its exact account effects will appear here."
            )

    def _review_selected(self):
        index = self.review_table.currentRow()
        if 0 <= index < len(self.pair_reviews):
            review = self.pair_reviews[index]
            self.review_details.setText(
                f"Revision {review.revision_id}: {review.decision}; reason: {review.reason}. Saved {review.created_at} UTC. "
                f"Version: {review.version}. This review does not allocate source rows or post money."
            )
        else:
            self.review_details.setText(
                "Select a suggestion decision to inspect its retained reason and context."
                if self.pair_reviews
                else "No suggestion decisions saved."
            )
        self._review_actions()

    def _review_actions(self, *_args):
        index = self.review_table.currentRow()
        review = self.pair_reviews[index] if 0 <= index < len(self.pair_reviews) else None
        latest = max(
            (
                item.revision_id
                for item in self.pair_reviews
                if review and item.context_current and _pair_key(item.pair) == _pair_key(review.pair)
            ),
            default=None,
        )
        self.reopen.setEnabled(
            review is not None
            and review.revision_id == latest
            and review.decision == "dismiss"
            and review.context_current
            and self.basis is not None
            and bool(self.reopen_reason.text().strip())
        )

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
        if pair is None or not pair.posting_allowed or self.basis is None:
            return
        outgoing, incoming = pair.outgoing, pair.incoming
        message = (
            f"Confirm this {pair.kind}?\n\n{_pair_details(pair)}\n\n"
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
                    outgoing.row_id,
                    incoming.row_id,
                    preferences=self.workspace.preferences(),
                    reason=reason,
                    expected_basis_sha256=self.basis,
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self._failed("Transfer was not posted", exc)
            return
        self.note.clear()
        self.refresh()
        self.status.setText("Transfer pair posted; both source movements are allocated.")

    def _failed(self, title, exc):
        message = str(exc)
        if "changed_since_selection" in message:
            message = "The selected transfer context changed. Inspect the reloaded state before confirming again."
        else:
            message = {
                "transfer_event_not_active": "This event is no longer active. Inspect its retained history before choosing another action.",
                "transfer_pair_unavailable_or_already_posted": "The selected pair is no longer eligible. Review the refreshed source rows and interpretations.",
                "transfer_assumed_date_disabled": "New postings need the best guess date choice for this pair. Existing interpretations can still be withdrawn.",
            }.get(message, message)
        QMessageBox.warning(self, title, message)
        self.refresh()
        self.status.setText(message)
        self.event_status.setText(message)

    def _dismiss(self):
        pair, reason = self._current(), self.note.text().strip()
        if pair is None or not reason or self.basis is None:
            return
        message = f"Dismiss this suggested {pair.kind}?\n\n{_pair_details(pair)}\n\nReason: {reason}\n\nNo money is posted or allocated. Source evidence remains pending."
        if QMessageBox.question(self, "Dismiss transfer suggestion", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.record_transfer_pair_review(
                    *_pair_key(pair),
                    decision="dismiss",
                    expected_basis_sha256=self.basis,
                    preferences=self.workspace.preferences(),
                    reason=reason,
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self._failed("Suggestion was not dismissed", exc)
            return
        self.note.clear()
        self.refresh()
        self.status.setText("Suggestion dismissed; source rows remain pending. See Suggestion history to reopen it.")

    def _reopen(self):
        index, reason = self.review_table.currentRow(), self.reopen_reason.text().strip()
        if not self.reopen.isEnabled() or not 0 <= index < len(self.pair_reviews) or not reason:
            return
        pair = self.pair_reviews[index].pair
        message = f"Reopen this dismissed pair?\n\n{_pair_details(pair)}\n\nReason: {reason}\n\nReopening creates no journal or evidence allocation."
        if QMessageBox.question(self, "Reopen transfer suggestion", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.record_transfer_pair_review(
                    *_pair_key(pair),
                    decision="reopen",
                    expected_basis_sha256=self.basis,
                    preferences=self.workspace.preferences(),
                    reason=reason,
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self._failed("Suggestion was not reopened", exc)
            return
        self.reopen_reason.clear()
        self.refresh()

    def _withdraw(self):
        event, reason = self.selected_event, self.correction_reason.text().strip()
        if event is None or event.status != "active" or not reason or self.event_basis is None:
            return
        message = (
            f"Withdraw this whole {event.settlement.kind} settlement?\n\nInverse source and fee effects:\n"
            f"{settlement_details(event.settlement, inverse=True)}\n\nAll {len(event.entry_keys)} journal leg(s) are reversed at "
            f"their original accounting dates. Reason: {reason}\n\nAll event fee expense and clearing effects are also reversed. "
            "Original entries remain history; the whole source manifest is released together. This withdraws an interpretation, not a bank payment."
            if event.pair is None
            else f"Withdraw this whole {event.pair.kind} interpretation?\n\nInverse account effects:\n"
            f"{_pair_details(event.pair, inverse=True)}\n\nAll {len(event.entry_keys)} journal leg(s) are reversed at "
            f"their original accounting dates. Reason: {reason}\n\nOriginal entries remain history; source rows return to pending. "
            "No income or expense is created. This withdraws an interpretation, not a bank payment."
        )
        if QMessageBox.question(self, "Confirm whole transfer withdrawal", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.withdraw_reviewed_transfer(event.event_id, expected_basis_sha256=self.event_basis, reason=reason)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self._failed("Transfer was not withdrawn", exc)
            return
        self.correction_reason.clear()
        self.refresh()
        self.event_status.setText(
            "The selected whole-event withdrawal is recorded. Refreshed history shows current source usage; original and inverse entries remain history."
        )

    def _replace(self):
        event, index, reason = (
            self.selected_event,
            self.replacement.currentData(),
            self.correction_reason.text().strip(),
        )
        pair = self.replacements[index] if isinstance(index, int) and 0 <= index < len(self.replacements) else None
        if (
            event is None
            or event.pair is None
            or event.status != "active"
            or pair is None
            or not pair.posting_allowed
            or _pair_key(pair) == _pair_key(event.pair)
            or not reason
            or self.event_basis is None
        ):
            return
        message = (
            f"Replace this whole {event.pair.kind} interpretation?\n\nWithdraw original effects:\n"
            f"{_pair_details(event.pair, inverse=True)}\n\nPost selected replacement:\n{_pair_details(pair)}\n\nReason: {reason}\n\n"
            "Every original leg is withdrawn and the selected pair is posted together. Failure preserves the original event. "
            "Both pairs' source dates and complete history are retained. No income or expense is created."
        )
        if QMessageBox.question(self, "Confirm whole transfer replacement", message) != QMessageBox.Yes:
            return
        try:
            with V2ProfileStore.open(self.workspace.profile_path) as store:
                store.replace_reviewed_transfer(
                    event.event_id,
                    *_pair_key(pair),
                    expected_basis_sha256=self.event_basis,
                    preferences=self.workspace.preferences(),
                    reason=reason,
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self._failed("Transfer was not replaced", exc)
            return
        self.correction_reason.clear()
        self.refresh()
        self.event_status.setText(
            "Whole event replaced atomically. Original and inverse entries remain history; unused source rows remain pending."
        )

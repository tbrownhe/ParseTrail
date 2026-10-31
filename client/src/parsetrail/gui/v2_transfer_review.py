"""Explicit cross-source review of owned transfers and liability payments."""

from __future__ import annotations

import atexit
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
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

from parsetrail.core.v2_profile_store import TransferCandidate, V2ProfileStore
from parsetrail.core.v2_transfer_planning import (
    max_user_reason_length,
    pair_key,
    plan_transfers,
    post_reviewed_transfer_selection,
    select_transfer_plan,
)
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_cash_activity_review import _money
from parsetrail.gui.v2_settlement_review import (
    V2SettlementReview,
    expected_identity,
    reviewed_identity,
    settlement_details,
)
from parsetrail.gui.v2_transfer_plan import (
    PLAN_REASON,
    V2TransferManualReview,
    V2TransferPlanPage,
    V2TransferSelectionManifest,
)

_TRANSFER_WORKERS: set[QThread] = set()


def _planning_error(exc):
    return {
        "transfer_planning_graph_changed": "Transfer matches or saved account context changed. No pairs were posted. Review the refreshed plan.",
        "transfer_planning_plan_invalid": "This transfer plan is no longer valid. Reload saved state and review it again.",
        "transfer_planning_selection_invalid": "These selected pairs cannot be posted together. Review the refreshed plan.",
        "transfer_planning_reason_too_long": "The posting note is too long for the retained review record. Shorten it and retry.",
        "transfer_planning_snapshot_invalid": "The saved transfer context is unavailable. Reload saved state to retry.",
        "transfer_planning_graph_invalid": "The saved transfer evidence could not be validated. Reload saved state to retry.",
    }.get(str(exc), str(exc))


def _finish_transfer_workers():
    workers = tuple(_TRANSFER_WORKERS)
    for worker in workers:
        worker.requestInterruption()
    for worker in workers:
        while worker.isRunning():
            worker.wait(10)
            time.sleep(0.001)
        worker.wait()
        _TRANSFER_WORKERS.discard(worker)


atexit.register(_finish_transfer_workers)


class _TransferWorker(QThread):
    """Connections and transactions belong solely to this worker."""

    def __init__(self, profile, kind, generation, operation):
        super().__init__()
        self.profile, self.kind, self.generation = Path(profile), kind, generation
        self.operation = operation
        self.result, self.error = None, None
        self.completed = False

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            if self.kind == "prepare":
                self.result = self.operation(None, self)
                self.completed = True
                return
            with V2ProfileStore.open(self.profile, read_only=self.kind != "write") as store:
                if self.kind != "write":
                    store.connection.set_progress_handler(lambda: int(self.isInterruptionRequested()), 1000)
                self.result = self.operation(store, self)
                self.completed = True
        except Exception as exc:
            self.error = exc
        finally:
            self.operation = None


def _pair_key(pair):
    return pair.outgoing.row_id, pair.incoming.row_id


def _source_date(movement):
    qualification = f" ({movement.date_provenance})" if movement.date_provenance in {"derived", "assumed"} else ""
    return movement.posting_date + qualification


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
    table.horizontalHeader().setResizeContentsPrecision(200)
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

    def __init__(self, workspace: V2Workspace, parent=None, *, focus_row_id=None):
        super().__init__(parent)
        self.workspace = workspace
        self._focus_row_id = focus_row_id
        self._worker = None
        self._generation = 0
        self._closed = False
        self._requested = False
        self.pending = True
        self._snapshot = None
        self._snapshot_profile = None
        self.window_plan = None
        self._replacement_cache = {}
        self._selection_ids = self._event_id = None
        self._completion_message = ""
        self._read_error = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_read)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_finish_transfer_workers)
        self.candidates: tuple[TransferCandidate, ...] = ()
        self.events, self.pair_reviews, self.replacements = (), (), ()
        self.basis, self.event_basis, self.selected_event = None, None, None
        self.setWindowTitle("2.0 owned transfers, card and loan-register repayments")
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
            "Review both sources before confirming a transfer. No income or spending is created. "
            "Liability repayments do not establish a principal/interest split. Different source dates retain transfer clearing."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Maximum date gap (days)"))
        self.gap = QSpinBox()
        self.gap.setRange(0, 31)
        self.gap.setValue(7)
        self.gap.valueChanged.connect(lambda: self.refresh(debounce=True))
        controls.addWidget(self.gap)
        self.assumed_dates = QCheckBox("Allow best guess posting dates when a statement does not print one")
        self.assumed_dates.setChecked(workspace.preferences().allow_assumed_posting_dates)
        self.assumed_dates.toggled.connect(self._toggle_assumed_dates)
        controls.addWidget(self.assumed_dates)
        self.reload_button = QPushButton("Reload saved state")
        self.reload_button.clicked.connect(self.refresh)
        controls.addWidget(self.reload_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.tabs = QTabWidget()
        self.plan_page = V2TransferPlanPage(date_label=_source_date, pair_details=_pair_details, parent=self)
        self.plan_page.review_requested.connect(self._review_selected_plan)
        self.plan_page.alternatives_requested.connect(self._inspect_plan_alternatives)
        self.plan_page.manual_review_requested.connect(self._review_plan_pair)
        self.tabs.addTab(self.plan_page, "Plan transfers")
        suggestions = self.matches_page = QWidget()
        suggestions_layout = QVBoxLayout(suggestions)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setResizeContentsPrecision(200)
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
        self.confirm.setAutoDefault(False)
        self.confirm.clicked.connect(self._post)
        self.batch = QPushButton("Review pairs with no other matches…")
        self.batch.clicked.connect(self._review_batch)
        self.batch.setAutoDefault(False)
        self.batch_scope = QLabel()
        self.batch_scope.setWordWrap(True)
        suggestions_layout.addWidget(self.batch_scope)
        self.dismiss = QPushButton("Dismiss selected suggestion")
        self.dismiss.setAutoDefault(False)
        self.dismiss.clicked.connect(self._dismiss)
        suggestion_actions = QHBoxLayout()
        suggestion_actions.addWidget(self.confirm)
        suggestion_actions.addWidget(self.dismiss)
        suggestion_actions.addWidget(self.batch)
        suggestions_layout.addLayout(suggestion_actions)
        self.tabs.addTab(suggestions, "All matches")
        self.full_settlement = QPushButton("Review transfer fees / partial settlements…")
        self.full_settlement.clicked.connect(self._new_settlement)
        layout.addWidget(self.full_settlement)
        self._build_history_tabs()
        self.tabs.currentChanged.connect(
            lambda: self.plan_page.review.setDefault(self.tabs.currentWidget() is self.plan_page)
        )
        self.plan_page.review.setDefault(True)
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _build_history_tabs(self):
        confirmed = self.events_page = QWidget()
        layout = QVBoxLayout(confirmed)
        instructions = QLabel(
            "Manual and planned matches use the same correction workflow. "
            "Select an Active row, then enter a reason to correct or undo that match."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.event_table = _history_table(
            ("State", "Type", "Sent", "From", "Received", "To", "Amount", "Legs", "Reason")
        )
        self.event_table.itemSelectionChanged.connect(self._event_selected)
        layout.addWidget(self.event_table, 1)
        self.event_details = QPlainTextEdit(
            "Select a confirmed event to inspect its complete effect and retained history."
        )
        self.event_details.setReadOnly(True)
        self.event_details.setMaximumHeight(110)
        layout.addWidget(self.event_details)
        self.correction_group = QGroupBox("Correct or undo selected transfer")
        corrections = QVBoxLayout(self.correction_group)
        reason_row = QHBoxLayout()
        reason_row.addWidget(QLabel("Reason for correction (required)"))
        self.correction_reason = QLineEdit()
        self.correction_reason.setMaxLength(500)
        self.correction_reason.setAccessibleName("Reason for correction, required")
        self.correction_reason.setPlaceholderText("Explain why this saved match needs to change")
        self.correction_reason.textChanged.connect(self._event_actions)
        reason_row.addWidget(self.correction_reason, 1)
        corrections.addLayout(reason_row)
        replacement_row = QHBoxLayout()
        replacement_row.addWidget(QLabel("Replacement pair"))
        self.replacement = QComboBox()
        self.replacement.currentIndexChanged.connect(self._event_actions)
        replacement_row.addWidget(self.replacement, 1)
        self.load_replacements = QPushButton("Load replacement pairs…")
        self.load_replacements.clicked.connect(self._load_replacements)
        replacement_row.addWidget(self.load_replacements)
        corrections.addLayout(replacement_row)
        self.replacement_details = QLabel("Select an active event to load eligible replacement pairs.")
        self.replacement_details.setWordWrap(True)
        corrections.addWidget(self.replacement_details)
        actions = QHBoxLayout()
        self.withdraw = QPushButton("Withdraw selected match")
        self.withdraw.setAutoDefault(False)
        self.withdraw.clicked.connect(self._withdraw)
        actions.addWidget(self.withdraw)
        self.replace = QPushButton("Replace selected match")
        self.replace.setAutoDefault(False)
        self.replace.clicked.connect(self._replace)
        actions.addWidget(self.replace)
        self.review_settlement = QPushButton("Inspect full settlement…")
        self.review_settlement.setAutoDefault(False)
        self.review_settlement.setToolTip("Inspect or replace the complete set of receipts and fees.")
        self.review_settlement.clicked.connect(self._open_settlement)
        actions.addWidget(self.review_settlement)
        corrections.addLayout(actions)
        self.event_status = QLabel()
        self.event_status.setWordWrap(True)
        self.event_status.setMinimumHeight(self.event_status.fontMetrics().lineSpacing() * 2)
        corrections.addWidget(self.event_status)
        layout.addWidget(self.correction_group)
        self.tabs.addTab(confirmed, "Confirmed events")
        reviews = self.reviews_page = QWidget()
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
        if self.pending:
            self.confirm.setEnabled(False)
            self.dismiss.setEnabled(False)
            return
        if self._read_error:
            self.confirm.setEnabled(False)
            self.dismiss.setEnabled(False)
            self.status.setText(self._read_error)
            return
        self.confirm.setEnabled(pair is not None and pair.posting_allowed and self.basis is not None)
        self.dismiss.setEnabled(pair is not None and bool(self.note.text().strip()) and self.basis is not None)
        if pair is None:
            if self.candidates:
                self.status.setText(f"{len(self.candidates)} candidate pair(s). Select one to inspect and confirm.")
            else:
                self.status.setText(
                    "No unposted candidate pairs in this date window. Check Confirmed events for existing matches. "
                    "If evidence is missing, import and assign the counterpart or change the date gap. "
                    "Other reviewed activity is corrected in its activity review."
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

    def refresh(self, *_args, debounce=False) -> None:
        if self._closed or (self._worker is not None and self._worker.kind == "write"):
            return
        self.profile_path.setText(str(self.workspace.profile_path))
        self.profile_path.setCursorPosition(0)
        selected = self._current()
        if selected is not None:
            self._selection_ids = _pair_key(selected)
        if self.selected_event is not None:
            self._event_id = self.selected_event.event_id
        self._generation += 1
        self._requested = True
        self.pending = True
        self._read_error = ""
        self._snapshot = None
        self._snapshot_profile = None
        self.window_plan = None
        self.plan_page.clear("Finding transfers across the full profile… Draft Include choices reset on reload.")
        self.basis = None
        self._replacement_cache.clear()
        self.candidates, self.events, self.pair_reviews = (), (), ()
        for table in (self.table, self.event_table, self.review_table):
            _fill_table(table, ())
        self._clear_event()
        self._selected()
        self._review_selected()
        self.status.setText("Loading saved transfer state…")
        self.batch_scope.setText("Checking both legs for other matches in the current date window…")
        self.batch.setEnabled(False)
        if self._worker is not None:
            self._worker.requestInterruption()
        self._timer.start(150 if debounce else 0)

    def _start_read(self):
        if self._closed or not self._requested or self._worker is not None:
            return
        self._requested = False
        preferences, gap = self.workspace.preferences(), self.gap.value()
        self.assumed_dates.blockSignals(True)
        self.assumed_dates.setChecked(preferences.allow_assumed_posting_dates)
        self.assumed_dates.blockSignals(False)

        def read(store, job):
            snapshot = store.transfer_review_snapshot(preferences=preferences, max_day_gap=gap)
            plan = plan_transfers(snapshot, cancelled=job.isInterruptionRequested)
            note_limit = 200
            if plan.selectable_pairs:
                sample = select_transfer_plan(plan, (pair_key(plan.selectable_pairs[0]),))
                note_limit = max_user_reason_length(sample) - len(PLAN_REASON) - 2
            return snapshot, plan, note_limit

        self._launch("read", read)

    def _launch(self, kind, operation, *, profile=None):
        worker = _TransferWorker(profile or self.workspace.profile_path, kind, self._generation, operation)
        self._worker = worker
        _TRANSFER_WORKERS.add(worker)
        worker.finished.connect(self._finished)
        worker.finished.connect(lambda: _TRANSFER_WORKERS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.destroyed.connect(worker.requestInterruption)
        worker.start()

    def _finished(self):
        worker, self._worker = self._worker, None
        if worker is None or self._closed:
            return
        current = worker.generation == self._generation and worker.profile == Path(self.workspace.profile_path)
        if worker.kind == "write":
            self._set_writing(False)
            if worker.error is not None:
                self._failed(self._failure_title, worker.error)
            elif worker.completed:
                self.note.clear()
                self.correction_reason.clear()
                self.reopen_reason.clear()
                self._completion_message = self._success_message(worker.result)
                self.refresh()
            else:
                self.refresh()
                self._completion_message = "Action cancelled before it started; no changes were made."
        elif current and worker.error is not None:
            self.pending = False
            self._set_writing(False)
            self.basis = self.event_basis = None
            self._snapshot = None
            self._read_error = f"Transfer review unavailable. Reload to retry: {_planning_error(worker.error)}"
            self.status.setText(self._read_error)
            self.event_status.setText(self.status.text())
            self.batch_scope.setText("Saved state unavailable; posting is disabled.")
            self.plan_page.set_available(False)
            self.plan_page.status.setText(self._read_error)
        elif current and worker.result is not None:
            self.pending = False
            self._set_writing(False)
            if worker.kind == "prepare":
                selection, context = worker.result
                self.plan_page.set_available(True)
                self._show_plan_manifest(selection, context)
            elif worker.kind == "replacement":
                event_id, snapshot = worker.result
                if snapshot.basis_sha256 != self.basis:
                    self._completion_message = "Transfer context changed. Inspect the reloaded state before confirming."
                    self.refresh()
                else:
                    self._replacement_cache[event_id] = snapshot
                    if self.selected_event is not None and self.selected_event.event_id == event_id:
                        self._event_selected()
            else:
                snapshot, self.window_plan, note_limit = worker.result
                self._snapshot_profile = worker.profile
                self.profile_path.setText(str(worker.profile))
                self.profile_path.setCursorPosition(0)
                self._apply_snapshot(snapshot)
                self.plan_page.set_plan(self.window_plan, note_limit=note_limit)
                if self._completion_message:
                    self.plan_page.status.setText(self._completion_message)
                self._completion_message = ""
        elif not current and worker.profile != Path(self.workspace.profile_path):
            self.refresh()
        if self._requested and not self._timer.isActive():
            self._timer.start(0)

    def _apply_snapshot(self, snapshot):
        self._snapshot = snapshot
        selected_ids, event_id = self._selection_ids, self._event_id
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
                _source_date(pair.outgoing),
                pair.outgoing.account_name,
                _source_date(pair.incoming),
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
        self._update_batch()
        if self._focus_row_id is not None:
            self.tabs.setCurrentWidget(self.matches_page)
            row_id, self._focus_row_id = self._focus_row_id, None
            for index, pair in enumerate(self.candidates):
                if row_id in _pair_key(pair):
                    self.tabs.setCurrentWidget(self.matches_page)
                    self.table.selectRow(index)
                    self.table.scrollToItem(self.table.item(index, 0))
                    break
            else:
                for index, event in enumerate(self.events):
                    if row_id in (event.settlement.outgoing.row_id, *(m.row_id for m in event.settlement.incoming)):
                        self.tabs.setCurrentWidget(self.events_page)
                        self.event_table.selectRow(index)
                        self.event_table.scrollToItem(self.event_table.item(index, 0))
                        break
                else:
                    self.status.setText(
                        "No eligible counterpart for this movement in the current date window. "
                        "Import and assign the paying or receiving account’s source, or widen the date gap. "
                        "No one-sided transfer entry is created."
                    )
        if self._completion_message:
            self.status.setText(self._completion_message)
            self.event_status.setText(self._completion_message)

    def _load_replacements(self):
        event = self.selected_event
        if event is None or event.status != "active" or self._worker is not None:
            return
        event_id, preferences, gap = event.event_id, self.workspace.preferences(), self.gap.value()
        self.pending = True
        self._set_writing(True)
        self.event_status.setText("Loading replacement pairs…")
        self._launch(
            "replacement",
            lambda store, _job: (
                event_id,
                store.transfer_review_snapshot(preferences=preferences, max_day_gap=gap, replacing_event_id=event_id),
            ),
        )

    def _clear_event(self):
        self.selected_event, self.event_basis, self.replacements = None, None, ()
        self.load_replacements.setEnabled(False)
        self.replacement.clear()
        self.withdraw.setEnabled(False)
        self.replace.setEnabled(False)
        self.review_settlement.setEnabled(False)
        self.event_details.setPlainText("Select a confirmed event to inspect its complete effect and retained history.")
        self.replacement_details.setText("Select an active event to load eligible replacement pairs.")
        self.correction_reason.setEnabled(False)
        self.replacement.setEnabled(False)
        self.event_status.setText("Select an Active row to correct or withdraw a saved match.")

    def _event_selected(self):
        index = self.event_table.currentRow()
        self._clear_event()
        if not 0 <= index < len(self.events):
            return
        event = self.events[index]
        snapshot = self._replacement_cache.get(event.event_id)
        self.selected_event, self.event_basis = event, self.basis
        self.load_replacements.setEnabled(event.status == "active" and event.pair is not None and not self.pending)
        self.review_settlement.setEnabled(True)
        self.event_details.setPlainText(
            f"{event.status.title()} {event.settlement.kind}; {len(event.entry_keys)} journal leg(s); "
            f"{len(event.settlement.incoming)} receipt(s), {len(event.settlement.fees)} explicit fee(s). Original reason: {event.reason}. "
            f"Action reason: {event.action_reason or 'none'}. Replacement event: {event.replacement_event_id or 'none'}.\n"
            f"{settlement_details(event.settlement)}\nEvent: {event.event_id}; version: {event.version}."
        )
        self.replacements = (
            snapshot.candidates if snapshot is not None and event.status == "active" and event.pair is not None else ()
        )
        self.replacement.blockSignals(True)
        self.replacement.addItem("Choose a replacement pair", None)
        for index, pair in enumerate(self.replacements):
            self.replacement.addItem(
                f"{pair.outgoing.account_name} {_source_date(pair.outgoing)} → "
                f"{pair.incoming.account_name} {_source_date(pair.incoming)}; {_money(-pair.outgoing.amount_minor)}",
                index,
            )
        self.replacement.blockSignals(False)
        self.event_status.setText(
            "Load replacement pairs to inspect alternatives."
            if snapshot is None and event.status == "active" and event.pair is not None
            else ""
        )
        self._event_actions()

    def _new_settlement(self):
        V2SettlementReview(self.workspace, parent=self).exec()
        self.refresh()

    def _open_settlement(self):
        event = self.selected_event
        if event is not None:
            if self._capture_review_context("Selected transfer is unavailable") is None:
                return
            V2SettlementReview(self.workspace, event_id=event.event_id, parent=self).exec()
            self.refresh()

    def _event_actions(self, *_args):
        event = self.selected_event
        active = not self.pending and event is not None and event.status == "active" and self.event_basis is not None
        loaded = event is not None and event.event_id in self._replacement_cache
        self.correction_reason.setEnabled(active)
        self.load_replacements.setEnabled(active and event.pair is not None)
        self.replacement.setEnabled(active and event.pair is not None and loaded)
        self.withdraw.setText(
            "Withdraw selected settlement" if event is not None and event.pair is None else "Withdraw selected match"
        )
        ready = (
            not self.pending
            and event is not None
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
                f"{pair.outgoing.account_name}: asset change {_money(pair.outgoing.amount_minor)} on {_source_date(pair.outgoing)}; "
                f"{pair.incoming.account_name}: {'asset value' if natural == 1 else 'amount owed'} change "
                f"{_money(natural * pair.incoming.amount_minor)} on {_source_date(pair.incoming)}. "
                + (
                    "Confirm both sources before replacing."
                    if pair.posting_allowed
                    else "Assumed dates require the global best guess choice."
                )
            )
            if not different_pair:
                self.replacement_details.setText(
                    "Choose a different pair. The selected pair is already this saved match."
                )
        else:
            self.replacement_details.setText(
                "Use Inspect full settlement to replace this complete set of receipts and fees; one pair cannot represent it."
                if event is not None and event.pair is None
                else "Choose an eligible replacement pair; its exact account effects will appear here."
            )
        if event is None:
            message = "Select an Active row to correct or withdraw a saved match."
        elif self.pending:
            message = "Wait for the current read or save to finish before correcting this match."
        elif event.status != "active":
            historical_state = "withdrawn" if event.status == "cancelled" else event.status
            message = f"This historical match was already {historical_state}. Inspect current Active history to make another correction."
        elif self.event_basis is None:
            message = "Saved context is unavailable. Reload saved state before correcting this match."
        else:
            withdrawal = (
                "Enter a reason above to enable withdrawal. "
                if not self.correction_reason.text().strip()
                else "Withdrawal is ready; it reverses all legs of the entire settlement and releases its source allocations. "
                if event.pair is None
                else "Withdrawal is ready; it reverses this match's reviewed entries and releases its source allocations. "
            )
            if event.pair is None:
                replacement = "Use Inspect full settlement to replace its complete receipts and fees."
            elif not loaded:
                replacement = "To replace: load replacement pairs, then choose a different eligible pair."
            elif not any(_pair_key(p) != _pair_key(event.pair) for p in self.replacements):
                replacement = "No different replacement pair is available in this date window."
            elif not any(_pair_key(p) != _pair_key(event.pair) and p.posting_allowed for p in self.replacements):
                replacement = "Different replacements have estimated dates that need the best guess date setting."
            elif pair is None:
                replacement = "Choose a different replacement pair, then enter a reason to enable replacement."
            elif not different_pair:
                replacement = "The chosen pair is already this match. Choose a different pair to replace it."
            elif not pair.posting_allowed:
                replacement = "This replacement's estimated date needs the best guess date setting."
            elif not self.correction_reason.text().strip():
                replacement = "Enter a reason above to enable replacement with the chosen pair."
            else:
                replacement = "Replacement is ready; the old match is withdrawn and the new pair is posted together."
            message = withdrawal + replacement + " This changes your accounting interpretation, not a bank payment."
        self.event_status.setText(message)

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
            not self.pending
            and review is not None
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
        context = self._capture_review_context("Transfer was not posted")
        if context is None:
            return
        preferences, profile, _generation = context
        basis = self.basis
        reason = "Confirmed owned-account transfer"
        if self.note.text().strip():
            reason += ": " + self.note.text().strip()
        message = (
            f"Confirm this {pair.kind}?\n\n{_pair_details(pair)}\n\n"
            "No income or expense is created. The two source dates are preserved."
        )
        if QMessageBox.question(self, "Confirm transfer pair", message) != QMessageBox.StandardButton.Yes:
            return
        if not self._review_context_current(context):
            self._failed("Transfer was not posted", "transfer_context_changed_since_selection")
            return
        self._write(
            "Transfer was not posted",
            "Transfer pair posted; both source movements are allocated.",
            lambda store, _job: store.post_reviewed_transfer(
                outgoing.row_id, incoming.row_id, preferences=preferences, reason=reason, expected_basis_sha256=basis
            ),
            profile=profile,
        )

    def _failed(self, title, exc):
        message = _planning_error(exc)
        if "changed_since_selection" in message:
            message = "The selected transfer context changed. Inspect the reloaded state before confirming again."
        else:
            message = {
                "transfer_event_not_active": "This event is no longer active. Inspect its retained history before choosing another action.",
                "transfer_pair_unavailable_or_already_posted": "The selected pair is no longer eligible. Review the refreshed source rows and interpretations.",
                "transfer_assumed_date_disabled": "New postings need the best guess date choice for this pair. Existing interpretations can still be withdrawn.",
                "transfer_batch_cancelled": "Transfer batch cancelled before commit; no pairs were posted.",
                "transfer_batch_preferences_changed": "The posting date policy changed. No pairs were posted. Inspect the reloaded suggestions and confirm again.",
                "transfer_batch_profile_changed": "The profile changed. No pairs were posted. Inspect the reloaded suggestions and confirm again.",
                "transfer_batch_graph_changed": "The transfer matches changed. No pairs were posted. Inspect the reloaded suggestions and confirm again.",
                "transfer_batch_plan_invalid": "This batch review is no longer valid. No pairs were posted. Reload and review the pairs again.",
            }.get(message, message)
        if str(exc) != "transfer_batch_cancelled":
            QMessageBox.warning(self, title, message)
        self._completion_message = message
        self.refresh()

    def _dismiss(self):
        pair, reason = self._current(), self.note.text().strip()
        if pair is None or not reason or self.basis is None:
            return
        context = self._capture_review_context("Suggestion was not dismissed")
        if context is None:
            return
        preferences, profile, _generation = context
        basis = self.basis
        message = f"Dismiss this suggested {pair.kind}?\n\n{_pair_details(pair)}\n\nReason: {reason}\n\nNo money is posted or allocated. Source evidence remains pending."
        if QMessageBox.question(self, "Dismiss transfer suggestion", message) != QMessageBox.Yes:
            return
        if not self._review_context_current(context):
            self._failed("Suggestion was not dismissed", "transfer_context_changed_since_selection")
            return
        self._write(
            "Suggestion was not dismissed",
            "Suggestion dismissed; source rows remain pending. See Suggestion history to reopen it.",
            lambda store, _job: store.record_transfer_pair_review(
                *_pair_key(pair),
                decision="dismiss",
                expected_basis_sha256=basis,
                preferences=preferences,
                reason=reason,
            ),
            profile=profile,
        )

    def _reopen(self):
        index, reason = self.review_table.currentRow(), self.reopen_reason.text().strip()
        if not self.reopen.isEnabled() or not 0 <= index < len(self.pair_reviews) or not reason:
            return
        pair = self.pair_reviews[index].pair
        context = self._capture_review_context("Suggestion was not reopened")
        if context is None:
            return
        preferences, profile, _generation = context
        basis = self.basis
        message = f"Reopen this dismissed pair?\n\n{_pair_details(pair)}\n\nReason: {reason}\n\nReopening creates no journal or evidence allocation."
        if QMessageBox.question(self, "Reopen transfer suggestion", message) != QMessageBox.Yes:
            return
        if not self._review_context_current(context):
            self._failed("Suggestion was not reopened", "transfer_context_changed_since_selection")
            return
        self._write(
            "Suggestion was not reopened",
            "Suggestion reopened; no money was posted or allocated.",
            lambda store, _job: store.record_transfer_pair_review(
                *_pair_key(pair), decision="reopen", expected_basis_sha256=basis, preferences=preferences, reason=reason
            ),
            profile=profile,
        )

    def _withdraw(self):
        event, reason = self.selected_event, self.correction_reason.text().strip()
        if event is None or event.status != "active" or not reason or self.event_basis is None:
            return
        context = self._capture_review_context("Transfer was not withdrawn")
        if context is None:
            return
        _preferences, profile, _generation = context
        basis = self.event_basis
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
        if not self._review_context_current(context):
            self._failed("Transfer was not withdrawn", "transfer_context_changed_since_selection")
            return
        self._write(
            "Transfer was not withdrawn",
            "Selected match withdrawn; original and reversing entries remain history. Select an Active row to correct another match.",
            lambda store, _job: store.withdraw_reviewed_transfer(
                event.event_id, expected_basis_sha256=basis, reason=reason
            ),
            profile=profile,
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
        context = self._capture_review_context("Transfer was not replaced")
        if context is None:
            return
        preferences, profile, _generation = context
        basis = self.event_basis
        message = (
            f"Replace this whole {event.pair.kind} interpretation?\n\nWithdraw original effects:\n"
            f"{_pair_details(event.pair, inverse=True)}\n\nPost selected replacement:\n{_pair_details(pair)}\n\nReason: {reason}\n\n"
            "Every original leg is withdrawn and the selected pair is posted together. Failure preserves the original event. "
            "Both pairs' source dates and complete history are retained. No income or expense is created."
        )
        if QMessageBox.question(self, "Confirm whole transfer replacement", message) != QMessageBox.Yes:
            return
        if not self._review_context_current(context):
            self._failed("Transfer was not replaced", "transfer_context_changed_since_selection")
            return
        self._write(
            "Transfer was not replaced",
            "Whole event replaced atomically; original and inverse entries remain history.",
            lambda store, _job: store.replace_reviewed_transfer(
                event.event_id, *_pair_key(pair), expected_basis_sha256=basis, preferences=preferences, reason=reason
            ),
            profile=profile,
        )

    def _set_writing(self, writing):
        self.plan_page.set_available(not writing and not self.pending)
        for widget in (
            self.gap,
            self.assumed_dates,
            self.reload_button,
            self.full_settlement,
            self.table,
            self.event_table,
            self.review_table,
            self.note,
            self.correction_reason,
            self.reopen_reason,
            self.replacement,
        ):
            widget.setEnabled(not writing)
        if writing:
            for button in (
                self.confirm,
                self.dismiss,
                self.batch,
                self.withdraw,
                self.replace,
                self.reopen,
                self.review_settlement,
                self.load_replacements,
            ):
                button.setEnabled(False)

    def _write(self, failure_title, success_message, operation, *, cancellable=False, profile=None):
        if self._worker is not None or self.pending or self._closed:
            return
        if profile is not None and Path(profile) != Path(self.workspace.profile_path):
            self._completion_message = "The profile changed; no pairs were posted. Review the refreshed plan."
            self.refresh()
            return
        self._failure_title = failure_title
        self._cancellable_write = cancellable
        self._success_message = success_message if callable(success_message) else lambda _result: success_message
        self.pending = True
        self._set_writing(True)
        self.status.setText(
            "Saving confirmed pairs… Close requests cancellation before commit; a committed batch is retained."
            if cancellable
            else "Saving confirmed action… Close waits for its saved outcome."
        )
        self.event_status.setText(self.status.text())
        self.plan_page.status.setText(self.status.text())
        self._launch("write", operation, profile=profile)

    def _update_batch(self):
        from parsetrail.core.v2_transfer_batch import plan_unique_transfers

        self.batch_plan = plan_unique_transfers(self._snapshot)
        plan = self.batch_plan
        count = len(plan.pairs)
        pair_label = "pair" if count == 1 else "pairs"
        self.batch.setText(f"Review {count} {pair_label} with no other matches…")
        self.batch.setEnabled(bool(plan.pairs) and not self.pending)
        self.batch_scope.setText(
            f"Whole profile; maximum date gap {self.gap.value()} days. "
            f"Best guess posting dates {'allowed' if self.assumed_dates.isChecked() else 'disabled'}. "
            f"{count} {pair_label} {'has' if count == 1 else 'have'} no other matches on either leg; "
            f"{plan.ambiguous_pair_count} competing and {plan.date_blocked_pair_count} date-blocked suggestions excluded. "
            "These are suggestions; inspect both sources before confirming. No income or spending is created."
        )

    def _inspect_plan_alternatives(self, pair):
        self.tabs.setCurrentWidget(self.matches_page)
        key = pair_key(pair)
        for index, candidate in enumerate(self.candidates):
            if pair_key(candidate) == key:
                self.table.selectRow(index)
                self.table.scrollToItem(self.table.item(index, 0))
                break

    def _review_plan_pair(self, pair):
        if self.pending or self._worker is not None or self.window_plan is None:
            return
        row = self.plan_page.row_lookup().get(pair_key(pair))
        if row is None:
            return
        context = self._capture_review_context("Transfer was not posted")
        if context is None:
            return
        preferences, profile, _generation = context
        basis = self.basis
        group = tuple(row.component.pairs)
        reviewed = {pair_key(p): p for p in group}
        initial_note = self.plan_page.note.text()
        dialog = V2TransferManualReview(
            group,
            pair_key(pair),
            scope=self.plan_page.scope.text(),
            explanation=row.component.explanation,
            date_label=_source_date,
            pair_details=_pair_details,
            initial_note=initial_note,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        if not self._review_context_current(context):
            self._failed("Transfer was not posted", "transfer_context_changed_since_selection")
            return
        # The dialog snapshots its own intentional final pair and note on
        # acceptance. Never substitute the main window's current highlight.
        chosen, note = dialog.confirmed_pair, dialog.confirmed_note
        if chosen is None or reviewed.get(pair_key(chosen)) != chosen or not chosen.posting_allowed:
            self._failed("Transfer was not posted", "transfer_pair_unavailable_or_already_posted")
            return
        reason = "Confirmed owned-account transfer" + (": " + note if note else "")
        self._write(
            "Transfer was not posted",
            "Transfer pair posted; both source movements are allocated.",
            lambda store, _job: store.post_reviewed_transfer(
                *pair_key(chosen), preferences=preferences, reason=reason, expected_basis_sha256=basis
            ),
            profile=profile,
        )

    def _review_selected_plan(self):
        if (
            self.pending
            or self._worker is not None
            or self.window_plan is None
            or not self.plan_page.review.isEnabled()
        ):
            return
        # Every reviewed value is captured before entering either nested modal
        # confirmation or background preparation. Checkbox changes are drafts.
        plan = self.window_plan
        keys = self.plan_page.selected_keys()
        frame = self._capture_review_context("Selected transfer plan was not posted")
        if frame is None:
            return
        preferences, profile, generation = frame
        reason = PLAN_REASON
        if self.plan_page.note.text().strip():
            reason += ": " + self.plan_page.note.text().strip()
        context = (preferences, profile, generation, reason, self.plan_page.scope.text(), self.plan_page.row_lookup())
        self.pending = True
        self._set_writing(True)
        self.plan_page.status.setText(f"Preparing review of {len(keys)} selected pairs…")
        self._launch("prepare", lambda _store, _job: (select_transfer_plan(plan, keys), context), profile=profile)

    def _capture_review_context(self, failure_title):
        preferences = self._snapshot.preferences if self._snapshot is not None else None
        frame = (preferences, self._snapshot_profile, self._generation)
        if preferences is None or self._snapshot_profile is None or not self._review_context_current(frame):
            self._failed(failure_title, "transfer_context_changed_since_selection")
            return None
        return frame

    def _review_context_current(self, context):
        preferences, profile, generation = context
        try:
            return (
                not self._closed
                and profile is not None
                and profile == self._snapshot_profile
                and profile == Path(self.workspace.profile_path)
                and generation == self._generation
                and preferences == self.workspace.preferences()
            )
        except (ValueError, OSError):
            return False

    def _plan_context_current(self, context):
        return self._review_context_current(context[:3])

    def _show_plan_manifest(self, selection, context):
        preferences, profile, _generation, reason, scope, rows = context
        if not self._plan_context_current(context):
            self._completion_message = (
                "The profile, date window or date policy changed; no pairs were posted. Review the refreshed plan."
            )
            self.refresh()
            return
        if len(reason) > max_user_reason_length(selection):
            self.plan_page.status.setText(
                "The posting note is too long for the retained review record. Shorten it and retry."
            )
            return
        manifest = V2TransferSelectionManifest(
            selection,
            rows,
            scope=scope,
            reason=reason,
            date_label=_source_date,
            pair_details=_pair_details,
            parent=self,
        )
        if manifest.exec() != QDialog.Accepted:
            return
        if not self._plan_context_current(context):
            self._completion_message = (
                "The profile, date window or date policy changed; no pairs were posted. Review the refreshed plan."
            )
            self.refresh()
            return
        self._write(
            "Selected transfer plan was not posted",
            lambda result: (
                f"{result.posted_pairs} selected transfer pairs posted; {result.already_posted_pairs} already posted. Both source dates and history retained."
            ),
            lambda store, job: post_reviewed_transfer_selection(
                store, selection, preferences=preferences, reason=reason, cancelled=job.isInterruptionRequested
            ),
            cancellable=True,
            profile=profile,
        )

    def _review_batch(self):
        if self.pending or self._worker is not None or not self.batch.isEnabled():
            return
        plan = self.batch_plan
        context = self._capture_review_context("Transfer pairs were not posted")
        if context is None:
            return
        preferences, profile, _generation = context
        reason = "Confirmed transfer pairs with no other matches"
        if self.note.text().strip():
            reason += ": " + self.note.text().strip()
        review = QDialog(self)
        review.setWindowTitle("Review transfer pairs with no other matches")
        review.resize(1000, 650)
        layout = QVBoxLayout(review)
        scope = QLabel(
            self.batch_scope.text()
            + "\nOnly the pairs below will be posted. Equal amounts and nearby dates do not prove a transfer. "
            "Uniquely suggested within this scope; review both sources. "
            "Different source dates retain transfer clearing. Liability repayments do not establish a principal/interest split."
        )
        scope.setWordWrap(True)
        layout.addWidget(scope)
        table = _history_table(("Type", "Sent", "From", "Received", "To", "Amount"))
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        _fill_table(
            table,
            tuple(
                (
                    p.kind.capitalize(),
                    _source_date(p.outgoing),
                    reviewed_identity(p.outgoing),
                    _source_date(p.incoming),
                    reviewed_identity(p.incoming),
                    _money(-p.outgoing.amount_minor),
                )
                for p in plan.pairs
            ),
        )
        layout.addWidget(table, 1)
        details = QPlainTextEdit("Select a pair to inspect both source descriptions and retained identifiers.")
        details.setReadOnly(True)
        details.setMaximumHeight(155)
        layout.addWidget(details)
        table.itemSelectionChanged.connect(
            lambda: details.setPlainText(
                _pair_details(plan.pairs[table.currentRow()]) if 0 <= table.currentRow() < len(plan.pairs) else ""
            )
        )
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        count = len(plan.pairs)
        post = buttons.addButton(
            f"Confirm and post {count} {'pair' if count == 1 else 'pairs'}", QDialogButtonBox.AcceptRole
        )
        post.setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setDefault(True)
        post.clicked.connect(review.accept)
        buttons.rejected.connect(review.reject)
        layout.addWidget(buttons)
        if review.exec() != QDialog.Accepted:
            return
        if not self._review_context_current(context):
            self._failed("Transfer pairs were not posted", "transfer_context_changed_since_selection")
            return
        from parsetrail.core.v2_transfer_batch import post_reviewed_transfer_batch

        self._write(
            "Transfer pairs were not posted",
            lambda result: (
                f"{result.posted_pairs} transfer pairs posted; {result.already_posted_pairs} already posted. Both source dates and history retained."
            ),
            lambda store, job: post_reviewed_transfer_batch(
                store, plan, preferences=preferences, reason=reason, cancelled=job.isInterruptionRequested
            ),
            cancellable=True,
            profile=profile,
        )

    def _stop(self):
        self._closed = True
        self._generation += 1
        self._timer.stop()
        if self._worker is not None:
            self._worker.requestInterruption()

    def done(self, result):
        if self._worker is not None and self._worker.kind == "write":
            self._worker.requestInterruption()
            self.status.setText(
                "Cancellation requested; waiting for the saved outcome. A committed batch is retained."
                if self._cancellable_write
                else "Finishing the confirmed action; waiting for its saved outcome."
            )
            self.event_status.setText(self.status.text())
            self.plan_page.status.setText(self.status.text())
            return
        self._stop()
        super().done(result)

    def close(self):
        if self._worker is not None and self._worker.kind == "write":
            self.done(QDialog.Rejected)
            return False
        self._stop()
        return super().close()

    def closeEvent(self, event):
        if self._worker is not None and self._worker.kind == "write":
            self.done(QDialog.Rejected)
            event.ignore()
            return
        self._stop()
        super().closeEvent(event)

"""Grouped, staged account association with one explicit atomic confirmation."""

from __future__ import annotations

import atexit
import sqlite3
import time
from threading import Event

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_batch_account_assignment import (
    AccountAssignmentCancelled,
    AccountAssignmentChoice,
    account_compatible,
    apply_account_assignments,
    plan_account_assignments,
)
from parsetrail.core.v2_cash_movement import cash_account_labels
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
from parsetrail.gui.v2_original_document import open_original_document

_JOBS: set[QThread] = set()


def _finish_jobs():
    for job in tuple(_JOBS):
        job.cancel()
        while job.isRunning():
            job.wait(10)
            time.sleep(0.001)
        job.wait()
        _JOBS.discard(job)


atexit.register(_finish_jobs)


class _AssignmentJob(QThread):
    def __init__(self, workspace, generation, *, plan=None, choices=(), new_accounts=()):
        super().__init__()
        self.workspace, self.generation = workspace, generation
        self.plan, self.choices, self.new_accounts = plan, choices, new_accounts
        self.cancel_event = Event()
        self.result, self.error = None, None

    def cancel(self):
        self.cancel_event.set()
        self.requestInterruption()

    def run(self):
        try:
            with V2ProfileStore.open(self.workspace.profile_path, read_only=self.plan is None) as store:
                store.connection.set_progress_handler(lambda: int(self.cancel_event.is_set()), 1000)
                if self.plan is None:
                    self.result = plan_account_assignments(
                        store,
                        catalog=self.workspace.catalog_cache.load_current(),
                        preferences=self.workspace.preferences(),
                        cancelled=self.cancel_event.is_set,
                    )
                else:
                    self.result = apply_account_assignments(
                        store,
                        self.plan,
                        self.choices,
                        new_accounts=self.new_accounts,
                        catalog_loader=self.workspace.catalog_cache.load_current,
                        preferences_loader=self.workspace.preferences,
                        cancelled=self.cancel_event.is_set,
                    )
        except Exception as exc:
            self.error = exc


def _period(target):
    def endpoint(value, origin):
        text = value.isoformat() if value else "unknown"
        return text + (" (estimated)" if origin == "assumed" else " (derived)" if origin == "derived" else "")

    return f"{endpoint(target.start, target.start_provenance)} – {endpoint(target.end, target.end_provenance)}"


_REASONS = {
    "prior_explicit_identity_assignment": "Previously confirmed for this exact printed account.",
    "unique_full_number_match": "A unique complete account number matches.",
    "opted_in_abbreviated_number_match": "A unique abbreviated number matches under your enabled matching preference.",
    "abbreviated_matching_requires_review": "Only an abbreviated number is available. Choose an account explicitly.",
    "prior_identity_has_multiple_accounts": "This printed account has been assigned to multiple accounts. Choose explicitly.",
    "number_has_multiple_accounts": "More than one account matches this number. Choose explicitly.",
    "accountless_export_requires_file_or_row_review": "No account identifier is printed. Use individual file/row assignment after this batch.",
    "verified_catalog_context_unavailable": "The exact parser context is unavailable. Review this document individually.",
    "tracking_scope_unavailable": "The represented account scope is unknown. Review this document individually.",
    "prior_assignment_incompatible": "An earlier assignment has incompatible account details. Review it individually.",
}


class _SummaryModel(QAbstractTableModel):
    headers = ("Institution", "Printed account", "Account", "Action", "Documents", "Sections")

    def __init__(self, parent):
        super().__init__(parent)
        self.rows = ()

    def replace(self, rows):
        self.beginResetModel()
        self.rows = tuple(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        return self.headers[section] if orientation == Qt.Horizontal and role == Qt.DisplayRole else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        value = self.rows[index.row()][index.column()]
        return str(value) if role in (Qt.DisplayRole, Qt.ToolTipRole) else None


class V2BatchAccountAssignment(QDialog):
    """No financial writes until the final Apply action, including new accounts."""

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.plan = None
        self.choices, self.new_accounts = {}, {}
        self.assignment_result = None
        self.changed = False
        self._job = None
        self._generation = 0
        self._requested = False
        self._closed = False
        self._close_result = None
        self._prompted = set()
        self._updating = False
        self._apply_blocked = False
        self.setWindowTitle("Assign document accounts")
        self.resize(1024, 730)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "All saved documents with unassigned account sections. Matching uses the institution and exact printed "
            "account in a compatible scope. Review the proposed groups; accounts and assignments are saved only on Apply."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.counts = QLabel("Finding accounts…")
        self.counts.setWordWrap(True)
        layout.addWidget(self.counts)
        self.pages = QStackedWidget()
        editor = QSplitter(Qt.Horizontal)
        self.groups = QListWidget()
        self.groups.setAccessibleName("Unassigned document account groups")
        self.groups.setWordWrap(True)
        self.groups.currentRowChanged.connect(self._selected)
        editor.addWidget(self.groups)
        details = QWidget()
        right = QVBoxLayout(details)
        self.group_context = QLabel("Finding accounts…")
        self.group_context.setWordWrap(True)
        self.group_context.setTextFormat(Qt.PlainText)
        self.group_context.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        right.addWidget(self.group_context)
        self.match_reason = QLabel()
        self.match_reason.setWordWrap(True)
        right.addWidget(self.match_reason)
        self.account_combo = QComboBox()
        self.account_combo.setAccessibleName("Account to use for this group")
        self.account_combo.currentIndexChanged.connect(self._choice_changed)
        right.addWidget(self.account_combo)
        self.new_account_button = QPushButton("New account for this group…")
        self.new_account_button.clicked.connect(self._new_account)
        right.addWidget(self.new_account_button, alignment=Qt.AlignLeft)
        self.stage_note = QLabel(
            "New account details stay in this batch until you apply it. Skipping leaves documents unassigned."
        )
        self.stage_note.setWordWrap(True)
        right.addWidget(self.stage_note)
        right.addWidget(QLabel("Documents in this group"))
        self.documents = QListWidget()
        self.documents.setAccessibleName("Documents in the selected account group")
        self.documents.setWordWrap(True)
        self.documents.currentRowChanged.connect(
            lambda: self.open_original_button.setEnabled(self.documents.currentRow() >= 0)
        )
        right.addWidget(self.documents, 1)
        self.source_digest = QLineEdit()
        self.source_digest.setReadOnly(True)
        self.source_digest.setAccessibleName("Selected original source digest")
        self.documents.currentRowChanged.connect(self._document_selected)
        right.addWidget(self.source_digest)
        self.open_original_button = QPushButton("Open original…")
        self.open_original_button.clicked.connect(self._open_original)
        right.addWidget(self.open_original_button, alignment=Qt.AlignLeft)
        self.original_status = QLabel()
        self.original_status.setWordWrap(True)
        right.addWidget(self.original_status)
        editor.addWidget(details)
        editor.setSizes([300, 700])
        self.pages.addWidget(editor)
        self.summary = QTableView()
        self.summary_model = _SummaryModel(self)
        self.summary.setModel(self.summary_model)
        self.summary.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary.setWordWrap(True)
        self.summary.horizontalHeader().setStretchLastSection(False)
        for column, width in enumerate((110, 175, 230, 115, 80, 80)):
            self.summary.setColumnWidth(column, width)
        for column in (1, 2):
            self.summary.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
        for column in (4, 5):
            self.summary.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.pages.addWidget(self.summary)
        layout.addWidget(self.pages, 1)
        self.status = QLabel("Finding accounts…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controls = QHBoxLayout()
        self.refresh_button = QPushButton("Reload proposals")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        self.back_button = QPushButton("Back to choices")
        self.back_button.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        controls.addWidget(self.back_button)
        controls.addStretch()
        self.review_button = QPushButton("Review assignments")
        self.review_button.clicked.connect(self._review)
        controls.addWidget(self.review_button)
        self.apply_button = QPushButton("Apply assignments")
        self.apply_button.clicked.connect(self.apply)
        controls.addWidget(self.apply_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        controls.addWidget(self.cancel_button)
        layout.addLayout(controls)
        self.pages.currentChanged.connect(self._update_actions)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_plan)
        app = QApplication.instance()
        if not app.property("parsetrail_batch_assignment_exit_hook"):
            app.setProperty("parsetrail_batch_assignment_exit_hook", True)
            app.aboutToQuit.connect(_finish_jobs)
        self.refresh()

    @property
    def pending(self):
        return self._job is not None or self._requested or self._timer.isActive()

    def refresh(self):
        if self._closed or (self._job is not None and self._job.plan is not None):
            return
        self._generation += 1
        self._apply_blocked = False
        self._requested = True
        if self._job is not None:
            self._job.cancel()
        self.plan = None
        self.groups.clear()
        self.summary_model.replace(())
        self.pages.setCurrentIndex(0)
        self.status.setText("Finding accounts…")
        self.counts.setText("Reading saved documents and confirmed associations…")
        self._timer.start(0)
        self._update_actions()

    def _start_plan(self):
        if self._closed or self._job is not None or not self._requested:
            return
        self._requested = False
        self._start_job(_AssignmentJob(self.workspace, self._generation))

    def _start_job(self, job):
        self._job = job
        _JOBS.add(job)
        self.destroyed.connect(job.cancel)
        job.finished.connect(self._finished)
        job.finished.connect(lambda: _JOBS.discard(job))
        job.finished.connect(job.deleteLater)
        job.start()
        self._update_actions()

    def _finished(self):
        job, self._job = self._job, None
        if job is None:
            return
        if job.plan is not None and job.result is not None:
            self.assignment_result = job.result
            self.changed = self.changed or bool(job.result.assigned_sections or job.result.created_accounts)
            self.status.setText(
                f"Saved {job.result.assigned_sections} account assignments and {job.result.created_accounts} new accounts. "
                f"{job.result.already_applied_sections} assignments were already saved. No transactions were posted."
            )
            self.plan = None
            self.groups.clear()
            self.summary_model.replace(())
            self.counts.setText("Batch saved. Reload proposals to find any remaining unassigned sections.")
        elif job.generation == self._generation and job.error is None and job.result is not None:
            self._load_plan(job.result)
        elif job.error is not None and job.generation == self._generation:
            cancelled = isinstance(job.error, AccountAssignmentCancelled) or (
                isinstance(job.error, sqlite3.OperationalError)
                and str(job.error) == "interrupted"
                and job.cancel_event.is_set()
            )
            if cancelled:
                self.status.setText("Cancelled. No batch accounts or assignments were saved.")
            elif str(job.error) == "batch_assignment_plan_stale":
                self._apply_blocked = True
                self.status.setText(
                    "The profile or parser context changed. Reload proposals and review the choices again. Nothing was saved."
                )
            else:
                self.status.setText(
                    "Account assignment is unavailable. Reload proposals to retry. No partial batch was saved."
                )
                self.status.setToolTip(str(job.error))
        if self._close_result is not None:
            self.done(self._close_result)
            return
        if self._requested:
            self._timer.start(0)
        self._update_actions()

    def _load_plan(self, plan):
        self.plan = plan
        accounts = {account.id: account for account in (*plan.accounts, *self.new_accounts.values())}
        self.choices = {
            group.group_id: account_id
            for group in plan.groups
            if (account_id := self.choices.get(group.group_id, group.suggested_account_id)) is not None
            and account_id in accounts
            and account_compatible(group, accounts[account_id])
        }
        self.groups.blockSignals(True)
        self.groups.clear()
        for group in plan.groups:
            title = (
                f"{group.institution_key or 'Institution unknown'} · {group.source_identity or 'No printed account'}"
            )
            label = (
                "Individual review"
                if group.status == "manual"
                else "Matched"
                if group.group_id in self.choices
                else "Choose account"
            )
            item = QListWidgetItem(f"{title}\n{len(group.targets)} section(s) · {label}")
            item.setToolTip(title)
            self.groups.addItem(item)
        self.groups.blockSignals(False)
        if plan.groups:
            index = next(
                (
                    i
                    for i, g in enumerate(plan.groups)
                    if g.status == "choose_account" and g.group_id not in self.choices
                ),
                0,
            )
            self.groups.setCurrentRow(index)
            self.status.setText("Review each account group, then review and apply the selected assignments.")
        else:
            self.status.setText("No unassigned account sections found.")
            self._selected()
        self._update_counts()

    def _current(self):
        index = self.groups.currentRow()
        return self.plan.groups[index] if self.plan is not None and 0 <= index < len(self.plan.groups) else None

    def _selected(self, *_args):
        group = self._current()
        self._updating = True
        self.account_combo.clear()
        self.documents.clear()
        self.account_combo.addItem("Leave unassigned / handle separately", None)
        if group is None:
            self.group_context.setText(
                "No account assignments needed."
                if self.plan is not None
                else "Choose an account group when proposals are ready."
            )
            self.match_reason.clear()
            self.source_digest.clear()
            self.open_original_button.setEnabled(False)
            self.account_combo.setEnabled(False)
            self.new_account_button.setEnabled(False)
            self._updating = False
            return
        self.group_context.setText(
            f"Institution: {group.institution_key or 'not identified'}\n"
            f"Document account: {group.source_identity or 'not printed'} ({group.source_identity_form or 'unknown'})\n"
            f"Kind: {group.kind or 'unknown'} · tracking scope: {(group.tracking_scope or 'unknown').replace('_', ' ')}"
        )
        self.match_reason.setText(
            _REASONS.get(
                group.reason,
                "This section has protected review history. Use individual account correction."
                if group.status == "manual"
                else "No confirmed match. Create an account or choose an existing compatible account.",
            )
        )
        accounts = {account.id: account for account in (*self.plan.accounts, *self.new_accounts.values())}
        compatible = tuple(account for account in accounts.values() if account_compatible(group, account))
        labels = cash_account_labels(compatible)
        for account in compatible:
            self.account_combo.addItem(
                labels[account.id] + (" · new, not saved" if account.id in self.new_accounts else ""), account.id
            )
        self.account_combo.setCurrentIndex(max(0, self.account_combo.findData(self.choices.get(group.group_id))))
        self.account_combo.setEnabled(group.status != "manual")
        self.new_account_button.setEnabled(group.status != "manual")
        for target in group.targets:
            item = QListWidgetItem(
                f"{'Statement' if target.document_kind == 'statement' else 'Activity export'} · {_period(target)} · {target.row_count} row(s)"
            )
            item.setToolTip(f"{item.text()}\n{target.parser_id}\n{target.source_sha256}")
            self.documents.addItem(item)
        if self.documents.count():
            self.documents.setCurrentRow(0)
        self._updating = False
        self._update_actions()
        QTimer.singleShot(0, self._maybe_prompt_new)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._maybe_prompt_new)

    def _maybe_prompt_new(self):
        group = self._current()
        if (
            self.isVisible()
            and not self._closed
            and not self.pending
            and group is not None
            and group.status == "choose_account"
            and not group.reason
            and group.group_id not in self.choices
            and group.group_id not in self._prompted
            and self.pages.currentIndex() == 0
        ):
            self._prompted.add(group.group_id)
            self._new_account()

    def _choice_changed(self, *_args):
        if self._updating or (group := self._current()) is None:
            return
        account_id = self.account_combo.currentData()
        if account_id is None:
            self.choices.pop(group.group_id, None)
        else:
            self.choices[group.group_id] = account_id
        self._update_counts()

    def _new_account(self):
        group = self._current()
        if group is None or group.status == "manual" or self.pending:
            return
        self._prompted.add(group.group_id)
        form = V2FinancialAccountDialog(self, draft=group.draft, staged=True)
        while form.exec() == QDialog.Accepted:
            account = form.account()
            if not account_compatible(group, account):
                form.save_error.setText(
                    "Use the institution, account kind and tracking scope shown for this group, or leave it for individual review."
                )
                continue
            self.new_accounts[account.id] = account
            self.choices[group.group_id] = account.id
            self._selected()
            self._update_counts()
            self.review_button.setFocus()
            break

    def _document_selected(self, *_args):
        group = self._current()
        index = self.documents.currentRow()
        self.source_digest.setText(
            group.targets[index].source_sha256 if group and 0 <= index < len(group.targets) else ""
        )
        self.source_digest.setCursorPosition(0)
        self.open_original_button.setEnabled(bool(self.source_digest.text()))

    def _open_original(self):
        source_id = self.source_digest.text()
        if source_id:
            operation = open_original_document(self.workspace.profile_path, source_id, self)
            self.original_status.setText(operation.status)
            operation.status_changed.connect(self.original_status.setText)

    def _update_counts(self):
        groups = self.plan.groups if self.plan is not None else ()
        for index, group in enumerate(groups):
            label = (
                "Individual review"
                if group.status == "manual"
                else "Selected"
                if group.group_id in self.choices
                else "Choose account"
            )
            self.groups.item(index).setText(
                f"{group.institution_key or 'Institution unknown'} · {group.source_identity or 'No printed account'}\n"
                f"{len(group.targets)} section(s) · {label}"
            )
        selected = [group for group in groups if group.group_id in self.choices]
        sections = sum(len(group.targets) for group in selected)
        documents = len({target.source_sha256 for group in selected for target in group.targets})
        remaining = sum(len(group.targets) for group in groups if group.group_id not in self.choices)
        new = len({self.choices[group.group_id] for group in selected}.intersection(self.new_accounts))
        self.counts.setText(
            f"{sections} account sections in {documents} documents selected · {new} new accounts staged · {remaining} sections left unassigned"
        )
        self.apply_button.setText(f"Apply {sections} assignments")
        self._update_actions()

    def _review(self):
        if self.plan is None or self.pending:
            return
        accounts = {account.id: account for account in (*self.plan.accounts, *self.new_accounts.values())}
        self.summary_model.replace(
            (
                group.institution_key or "Unknown",
                f"{group.source_identity or 'Not printed'}\n{group.kind or 'Unknown kind'} · "
                f"{(group.tracking_scope or 'unknown scope').replace('_', ' ')}",
                accounts[self.choices[group.group_id]].name if group.group_id in self.choices else "—",
                "Create and assign"
                if self.choices.get(group.group_id) in self.new_accounts
                else "Use existing"
                if group.group_id in self.choices
                else "Leave unassigned",
                len({target.source_sha256 for target in group.targets}),
                len(group.targets),
            )
            for group in self.plan.groups
        )
        self.pages.setCurrentIndex(1)
        self.summary.resizeRowsToContents()
        self.status.setText(
            "Confirm these account associations. Apply saves selected new accounts and assignments together; it posts no transactions."
        )
        self.apply_button.setFocus()

    def apply(self):
        if (
            self.plan is None
            or self.pending
            or self._apply_blocked
            or self.pages.currentIndex() != 1
            or not self.choices
        ):
            return
        choices = tuple(AccountAssignmentChoice(group_id, account_id) for group_id, account_id in self.choices.items())
        self._generation += 1
        self.status.setText("Saving account assignments…")
        self._start_job(
            _AssignmentJob(
                self.workspace,
                self._generation,
                plan=self.plan,
                choices=choices,
                new_accounts=tuple(self.new_accounts.values()),
            )
        )

    def _update_actions(self, *_args):
        ready = self.plan is not None and not self.pending and not self._closed
        self.groups.setEnabled(ready)
        self.refresh_button.setEnabled(not self.pending and not self._closed)
        self.review_button.setVisible(self.pages.currentIndex() == 0)
        self.review_button.setEnabled(ready and bool(self.choices))
        self.apply_button.setVisible(self.pages.currentIndex() == 1)
        self.apply_button.setEnabled(ready and bool(self.choices) and not self._apply_blocked)
        self.back_button.setVisible(self.pages.currentIndex() == 1)
        self.back_button.setEnabled(ready)
        self.pages.setEnabled(not self.pending)
        self.cancel_button.setText(
            "Cancel operation" if self.pending else "Close" if self.assignment_result else "Cancel"
        )

    def done(self, result):
        self._requested = False
        self._timer.stop()
        if self._job is not None:
            self._close_result = result
            self._job.cancel()
            self.status.setText("Finishing the current operation before closing…")
            return
        self._closed = True
        super().done(result)

    def close(self):
        self.done(QDialog.Rejected)
        return True

    def closeEvent(self, event):
        if self._job is not None:
            event.ignore()
            self.done(QDialog.Rejected)
        else:
            super().closeEvent(event)

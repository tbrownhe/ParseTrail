"""Printed statement inventory and explicitly confirmed reconciliation history."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.source_evidence import MoneyValue
from parsetrail.core.v2_profile_store import (
    EarliestSourceOpening,
    ProfileFormatError,
    ReconciliationDecision,
    StatementCoverageRow,
    StatementJournalComparison,
    StatementReconciliationCheck,
    V2ProfileStore,
)
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview, _money
from parsetrail.gui.v2_statement_source_review import V2StatementSourceReview


def _reconciliation_unavailable_message(reason: str | None) -> str:
    if reason == "statement_review_requires_one_bound_section":
        return (
            "Live reconciliation is unavailable because this account has multiple sections in a bound source. "
            "Saved decisions remain historical and stale until the source sections can be reviewed."
        )
    return f"Live reconciliation is unavailable: unsupported state ({reason})." if reason else ""


def _balance(value: MoneyValue | None) -> str:
    if value is None or value.provenance == "unknown":
        return "Unknown"
    if value.provenance == "observed":
        return value.raw or "Unknown"
    return f"Derived {_money(value.minor)}" if value.minor is not None else "Unknown"


class _CoverageModel(QAbstractTableModel):
    HEADERS = (
        "Financial account",
        "Source period",
        "Compared with known periods",
        "Opening",
        "Closing",
        "Scope",
        "Balance equation",
        "Page capture",
        "Printed endpoint comparison",
        "Source",
        "Source review",
    )
    RELATIONS = {
        "first_known": "First known period",
        "adjacent": "Adjacent dates",
        "overlap": "Overlapping dates",
        "gap": "Calendar gap",
        "unknown_start": "Unknown start",
    }
    ENDPOINTS = {
        "not_adjacent": "Not compared",
        "unavailable": "Observed values unavailable",
        "ambiguous_prior": "Multiple prior endpoints",
        "same": "Same printed amount",
        "different": "Different printed amounts",
    }

    def __init__(self, rows: tuple[StatementCoverageRow, ...], reviewed: frozenset[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.rows = rows
        self.reviewed = reviewed

    def set_reviewed(self, reviewed: frozenset[tuple[str, str]]) -> None:
        self.reviewed = reviewed
        if self.rows:
            self.dataChanged.emit(self.index(0, 10), self.index(len(self.rows) - 1, 10))

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.ToolTipRole}:
            return None
        row = self.rows[index.row()]
        values = (
            row.account_name,
            f"{row.period_start.isoformat() if row.period_start else 'Unknown'} to {row.period_end.isoformat()}",
            self.RELATIONS[row.relation_to_known_periods],
            _balance(row.opening),
            _balance(row.closing),
            row.balance_scope.replace("_", " "),
            "Passed" if row.independent_balance_verified else "Not independently verified",
            "Verified" if row.capture_verified else "Incomplete",
            self.ENDPOINTS[row.endpoint_comparison],
            row.source_sha256[:16],
            "Recorded" if (row.account_id, row.source_sha256) in self.reviewed else "Not recorded",
        )
        if role == Qt.ToolTipRole:
            return (
                f"Source: {row.source_sha256}\nParser: {row.parser_id}\n"
                f"Period start: {row.period_start_provenance}; end: {row.period_end_provenance}\n"
                f"Compared closing source: {row.compared_source_sha256 or 'None'}"
            )
        return values[index.column()]


class _OpeningModel(QAbstractTableModel):
    HEADERS = (
        "Financial account",
        "Class",
        "Earliest known start",
        "Bound sections",
        "Printed opening candidate",
        "Review needed",
        "Sources considered",
    )
    BLOCKERS = {
        "no_bound_statement": "No bound statement",
        "unknown_source_period": "Unknown source period",
        "non_account_total_scope": "Not an account-total balance",
        "printed_opening_unavailable": "Printed opening unavailable",
        "conflicting_earliest_openings": "Conflicting printed openings",
        "duplicate_earliest_source_sections": "Multiple earliest sections from one source",
        "source_timing_unreviewed": "Source timing unreviewed",
    }

    def __init__(self, rows: tuple[EarliestSourceOpening, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

    def replace(self, rows: tuple[EarliestSourceOpening, ...]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.ToolTipRole}:
            return None
        row = self.rows[index.row()]
        natural_sign = 1 if row.account_kind == "asset" else -1
        values = (
            row.account_name,
            row.account_kind.title(),
            row.earliest_period_start.isoformat() if row.earliest_period_start else "Unknown",
            str(row.bound_statement_sections),
            _money(row.printed_opening_minor * natural_sign)
            if row.printed_opening_minor is not None
            else "Unavailable",
            ", ".join(self.BLOCKERS[blocker] for blocker in row.blockers),
            ", ".join(source[:12] for source in row.earliest_source_ids),
        )
        if role == Qt.ToolTipRole:
            return (
                f"Account ID: {row.account_id}\n"
                f"Source IDs considered: {', '.join(row.earliest_source_ids) or 'None'}\n"
                f"Review codes: {', '.join(row.blockers)}"
            )
        return values[index.column()]


class _JournalComparisonModel(QAbstractTableModel):
    HEADERS = (
        "Financial\naccount",
        "Source\nperiod",
        "Comparison\nstatus",
        "Printed\nchange",
        "Source\nactivity",
        "Journal\nchange",
        "Journal minus\nprinted",
        "Unallocated\nrows",
        "Unallocated\namount",
        "Allocations\noutside period",
        "Other\npostings",
        "Source",
    )

    def __init__(self, rows: tuple[StatementJournalComparison, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.ToolTipRole}:
            return None
        row = self.rows[index.row()]
        natural = 1 if row.account_kind == "asset" else -1
        values = (
            row.account_name,
            f"{row.period_start.isoformat() if row.period_start else 'Unknown'}\n{row.period_end.isoformat()}",
            row.status,
            _money(row.printed_change_minor * natural) if row.printed_change_minor is not None else "Unavailable",
            _money(row.source_activity_change_minor * natural)
            if row.source_activity_change_minor is not None
            else "Unavailable",
            _money(row.journal_change_minor * natural) if row.journal_change_minor is not None else "Unavailable",
            _money(row.difference_minor * natural) if row.difference_minor is not None else "Unavailable",
            str(row.unallocated_rows),
            _money(row.unallocated_magnitude_minor),
            str(row.allocations_outside_period),
            str(row.outside_postings),
            row.source_sha256[:16],
        )
        if role == Qt.ToolTipRole:
            return (
                f"{row.status}\nSource: {row.source_sha256}\nAccount: {row.account_id} ({row.account_kind})\n"
                f"{row.activity_rows} source activity rows; unresolved amount is the sum of absolute row remainders.\n"
                "Signed changes are displayed as asset value or liability owed. This is not reconciliation certification."
            )
        return values[index.column()]


class _ReconciliationModel(QAbstractTableModel):
    HEADERS = (
        "Financial\naccount",
        "Source\nperiod",
        "Check\nresult",
        "Opening\ndifference",
        "Closing\ndifference",
        "Source equation\ndifference",
        "Evidence / coverage\nlimits",
        "Source",
    )
    REASONS = {
        "account_total_scope_unavailable": "Source is not an account-total balance",
        "source_period_start_unavailable": "Source period start unavailable",
        "reported_balance_endpoints_unavailable": "Reported printed endpoints unavailable",
        "source_balance_equation_unverified": "Printed source equation unverified",
        "source_capture_incomplete": "Source page capture incomplete",
        "unallocated_source_movements": "Source movements awaiting allocation",
        "source_allocations_outside_period": "Allocated source movement dated outside period",
        "postings_outside_statement_evidence": "Journal posting outside this source evidence",
        "opening_balance_difference": "Journal opening differs from printed opening",
        "closing_balance_difference": "Journal closing differs from printed closing",
        "source_endpoints_not_reviewed": "Printed endpoint origins need source review",
        "source_period_timing_unreviewed": "Inclusive source period timing needs review",
        "posting_dates_not_reported": "Posting dates are estimated or unverified",
        "opening_position_unverified_or_stale": "Opening decision missing or stale",
        "overlapping_bound_source_periods": "Bound source periods overlap",
        "calendar_gap_before_source": "Calendar gap before this source",
        "adjacent_printed_endpoints_differ": "Adjacent printed endpoints differ",
        "confirmed_repeated_supporting_evidence": "Confirmed supporting repeats remain separate source evidence",
        "cross_source_occurrence_review_pending": "Repeated activity across sources needs review",
    }

    @classmethod
    def supported_codes(cls, row: StatementReconciliationCheck) -> bool:
        return all(reason in cls.REASONS for reason in (*row.exceptions, *row.coverage_warnings))

    @classmethod
    def reason_label(cls, reason: str) -> str:
        return cls.REASONS.get(reason, f"Unsupported check code ({reason})")

    def __init__(self, rows: tuple[StatementReconciliationCheck, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

    def replace(self, rows: tuple[StatementReconciliationCheck, ...]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.ToolTipRole}:
            return None
        row = self.rows[index.row()]
        natural = 1 if row.account_kind == "asset" else -1

        def difference(value: int | None) -> str:
            return _money(value * natural) if value is not None else "Unavailable"

        values = (
            row.account_name,
            f"{row.period_start.isoformat() if row.period_start else 'Unknown'}\n{row.period_end.isoformat()}",
            (
                "Unsupported check result"
                if not self.supported_codes(row)
                else "Reconciled"
                if row.reconciled
                else f"Needs review ({len(row.exceptions)})"
            ),
            difference(row.opening_difference_minor),
            difference(row.closing_difference_minor),
            difference(row.source_difference_minor),
            ", ".join(self.reason_label(reason) for reason in row.coverage_warnings) or "None identified",
            row.source_sha256[:16],
        )
        if role == Qt.ToolTipRole:
            return self.details(row)
        return values[index.column()]

    @classmethod
    def details(cls, row: StatementReconciliationCheck) -> str:
        natural = 1 if row.account_kind == "asset" else -1

        def amount(value: int | None) -> str:
            return _money(value * natural) if value is not None else "Unavailable"

        return (
            f"Printed opening {amount(row.printed_opening_minor)}; journal opening {amount(row.journal_opening_minor)}. "
            f"Printed closing {amount(row.printed_closing_minor)}; journal closing {amount(row.journal_closing_minor)}.\n"
            f"Check blockers: {', '.join(cls.reason_label(reason) for reason in row.exceptions) or 'None'}.\n"
            f"Evidence / coverage limits: {', '.join(cls.reason_label(reason) for reason in row.coverage_warnings) or 'None identified'}. "
            f"Posted interpretation review: {'Complete' if row.posted_interpretations_reviewed else 'Pending'}.\n"
            f"{'Unsupported check codes prevent interpreting this result. ' if not cls.supported_codes(row) else ''}"
            f"Source: {row.source_sha256}; rule: {row.rule}; input version: {row.input_version}"
        )


class _ReconciliationHistoryModel(QAbstractTableModel):
    HEADERS = ("Financial account", "Saved cutoff", "Input state", "Saved at (UTC)", "Reason", "Rule", "Source")

    def __init__(self, rows: tuple[ReconciliationDecision, ...], parent=None):
        super().__init__(parent)
        self.rows = rows

    def replace(self, rows: tuple[ReconciliationDecision, ...]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.ToolTipRole:
            return self.details(row)
        if role != Qt.DisplayRole:
            return None
        values = (
            row.check.account_name,
            row.cutoff_date.isoformat(),
            (
                "Unsupported saved check"
                if not _ReconciliationModel.supported_codes(row.check)
                else "Stale — inputs changed"
                if row.stale
                else "Current inputs"
            ),
            row.created_at,
            row.reason,
            row.rule,
            row.source_sha256[:16],
        )
        return values[index.column()]

    @staticmethod
    def details(row: ReconciliationDecision) -> str:
        state = (
            "Unsupported check codes prevent interpreting this saved result"
            if not _ReconciliationModel.supported_codes(row.check)
            else "Inputs changed; retained as historical evidence"
            if row.stale
            else "Matches current check inputs"
        )
        return (
            f"Decision {row.decision_id}; saved cutoff {row.cutoff_date.isoformat()}; "
            f"saved at {row.created_at} UTC. "
            f"{state}. "
            f"Reason: {row.reason}.\n"
            f"{_ReconciliationModel.details(row.check)}\n"
            f"Retained versions of {len(row.journal_versions)} journal entry(s). "
            "A saved statement check does not establish full page capture, complete period coverage or a current bank balance."
        )


class V2StatementCoverageDialog(QDialog):
    """Show source facts, live checks and append-only saved reconciliation decisions."""

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("2.0 statement coverage")
        self.resize(1320, 760)
        with V2ProfileStore.open(profile, read_only=True) as store:
            rows = store.statement_coverage()
            openings = store.earliest_source_openings()
            comparisons = store.statement_journal_comparisons()
            reconciliation_snapshot = store.reconciliation_snapshot()
            reconciliation = reconciliation_snapshot.checks
            history = reconciliation_snapshot.history
            accounts = store.financial_accounts()
            reviewed = frozenset(
                (account.id, review.source_sha256)
                for account in accounts
                for review in store.statement_source_reviews(account.id)
            )
            account_count = len(accounts)
        layout = QVBoxLayout(self)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self.profile_path = QLineEdit(str(profile))
        self.profile_path.setReadOnly(True)
        self.profile_path.setCursorPosition(0)
        profile_row.addWidget(self.profile_path)
        layout.addLayout(profile_row)
        bound_accounts = len({row.account_id for row in rows})
        summary = QLabel(
            f"{len(rows)} explicitly bound statement section(s) on {bound_accounts} account(s); "
            f"{account_count - bound_accounts} financial account(s) have no bound statement."
        )
        layout.addWidget(summary)
        scope = QLabel(
            "Calendar comparisons use saved, explicitly bound statements only. Source period dates may be derived; "
            "hover a row for provenance. A gap or adjacent dates do not establish missing or complete activity. "
            "Printed endpoint comparisons use observed account-total amounts on adjacent dated periods only; "
            "equal amounts do not certify reconciliation or complete coverage. "
            "Printed balances are source evidence, not posted account balances. "
            "In Saved periods, double-click a row to inspect its source."
        )
        scope.setWordWrap(True)
        layout.addWidget(scope)
        self.model = _CoverageModel(rows, reviewed, self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for column in range(len(_CoverageModel.HEADERS)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._preview)
        saved_panel = QWidget()
        saved_layout = QVBoxLayout(saved_panel)
        saved_layout.addWidget(self.table)
        self.review_source_button = QPushButton("Review selected source")
        self.review_source_button.clicked.connect(self._review_selected_source)
        self.table.selectionModel().currentRowChanged.connect(self._update_review_source_button)
        saved_layout.addWidget(self.review_source_button)
        self.tabs = tabs = QTabWidget()
        tabs.addTab(saved_panel, "Saved periods")
        opening_panel = QWidget()
        opening_layout = QVBoxLayout(opening_panel)
        opening_scope = QLabel(
            "A candidate needs matching observed account-total openings across all tied earliest sources. "
            "Asset values and liability amounts owed are shown in their natural direction. "
            "Source timing needs explicit review in Review openings. This tab is a read-only source inventory; "
            "inspect details in Saved periods and use Review openings to record a decision."
        )
        opening_scope.setWordWrap(True)
        opening_layout.addWidget(opening_scope)
        self.opening_model = _OpeningModel(openings, self)
        self.opening_table = QTableView()
        self.opening_table.setModel(self.opening_model)
        self.opening_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.opening_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for column in range(len(_OpeningModel.HEADERS)):
            self.opening_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.opening_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        opening_layout.addWidget(self.opening_table)
        tabs.addTab(opening_panel, "Printed openings")
        comparison_panel = QWidget()
        comparison_layout = QVBoxLayout(comparison_panel)
        comparison_scope = QLabel(
            "Printed and journal changes are displayed in asset-value or liability-owed direction. "
            "Unallocated amount sums absolute row remainders, so opposite pending movements do not cancel. "
            "Other postings are journal movements outside this statement's source rows. "
            "An equal change does not establish reconciliation, complete source capture or period coverage. "
            "Double-click a row to inspect the saved source."
        )
        comparison_scope.setWordWrap(True)
        comparison_layout.addWidget(comparison_scope)
        self.comparison_model = _JournalComparisonModel(comparisons, self)
        self.comparison_table = QTableView()
        self.comparison_table.setModel(self.comparison_model)
        self.comparison_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.comparison_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.comparison_table.setWordWrap(True)
        comparison_header = self.comparison_table.horizontalHeader()
        comparison_header.setFixedHeight(max(46, comparison_header.fontMetrics().lineSpacing() * 2 + 12))
        for column, width in enumerate((135, 105, 260, 88, 88, 88, 94, 78, 90, 94, 76)):
            comparison_header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.comparison_table.setColumnWidth(column, width)
        comparison_header.setSectionResizeMode(11, QHeaderView.Stretch)
        self.comparison_table.verticalHeader().setDefaultSectionSize(56)
        self.comparison_table.doubleClicked.connect(self._preview_comparison)
        comparison_layout.addWidget(self.comparison_table)
        tabs.addTab(comparison_panel, "Journal comparison")
        reconciliation_panel = QWidget()
        reconciliation_layout = QVBoxLayout(reconciliation_panel)
        reconciliation_scope = QLabel(
            "The live check requires matching printed and journal opening/closing balances, complete source allocation, "
            "reviewed source provenance and a current opening decision. "
            "Page capture, period coverage and posted interpretation review remain separate. "
            "Select a successful check to confirm and save its cutoff. Saved decisions retain the inputs checked; "
            "changed inputs leave that decision in history as stale."
        )
        reconciliation_scope.setWordWrap(True)
        reconciliation_layout.addWidget(reconciliation_scope)
        self.reconciliation_model = _ReconciliationModel(reconciliation, self)
        self.reconciliation_table = QTableView()
        self.reconciliation_table.setModel(self.reconciliation_model)
        self.reconciliation_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.reconciliation_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.reconciliation_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.reconciliation_table.setWordWrap(True)
        reconciliation_header = self.reconciliation_table.horizontalHeader()
        reconciliation_header.setFixedHeight(max(46, reconciliation_header.fontMetrics().lineSpacing() * 2 + 12))
        for column, width in enumerate((150, 120, 140, 100, 100, 120, 260)):
            reconciliation_header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.reconciliation_table.setColumnWidth(column, width)
        reconciliation_header.setSectionResizeMode(7, QHeaderView.Stretch)
        self.reconciliation_table.verticalHeader().setDefaultSectionSize(50)
        self.reconciliation_table.selectionModel().currentRowChanged.connect(self._show_reconciliation_details)
        self.reconciliation_details = QLabel("Select a statement to see its printed and journal endpoints.")
        self.reconciliation_details.setWordWrap(True)
        self.reconciliation_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        reconciliation_layout.addWidget(self.reconciliation_table)
        reconciliation_layout.addWidget(self.reconciliation_details)
        save_controls = QHBoxLayout()
        self.reconciliation_reason = QLineEdit()
        self.reconciliation_reason.setMaxLength(450)
        self.reconciliation_reason.setPlaceholderText("Optional note about this reconciliation decision")
        save_controls.addWidget(self.reconciliation_reason)
        self.save_reconciliation_button = QPushButton("Confirm and save selected check")
        self.save_reconciliation_button.setEnabled(False)
        self.save_reconciliation_button.clicked.connect(self._save_reconciliation)
        save_controls.addWidget(self.save_reconciliation_button)
        self.refresh_reconciliation_button = QPushButton("Refresh checks and history")
        self.refresh_reconciliation_button.clicked.connect(self._refresh_reconciliation)
        save_controls.addWidget(self.refresh_reconciliation_button)
        reconciliation_layout.addLayout(save_controls)
        self.reconciliation_status = QLabel()
        self.reconciliation_status.setText(
            _reconciliation_unavailable_message(reconciliation_snapshot.unavailable_reason)
        )
        self.reconciliation_status.setWordWrap(True)
        reconciliation_layout.addWidget(self.reconciliation_status)
        tabs.addTab(reconciliation_panel, "Reconciliation check")
        history_panel = QWidget()
        history_layout = QVBoxLayout(history_panel)
        history_scope = QLabel(
            "Saved decisions are append-only. Current inputs means the saved version still matches the live check; "
            "Stale means inputs changed, including conservative profile-wide changes. "
            "History retains the original result and journal versions without changing the books."
        )
        history_scope.setWordWrap(True)
        history_layout.addWidget(history_scope)
        self.reconciliation_history_model = _ReconciliationHistoryModel(history, self)
        self.reconciliation_history_table = QTableView()
        self.reconciliation_history_table.setModel(self.reconciliation_history_model)
        self.reconciliation_history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.reconciliation_history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.reconciliation_history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        history_header = self.reconciliation_history_table.horizontalHeader()
        for column, width in enumerate((150, 110, 175, 160, 270, 200, 145)):
            history_header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.reconciliation_history_table.setColumnWidth(column, width)
        history_layout.addWidget(self.reconciliation_history_table)
        self.reconciliation_history_details = QLabel("No saved reconciliation decisions in this profile.")
        self.reconciliation_history_details.setWordWrap(True)
        self.reconciliation_history_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        history_layout.addWidget(self.reconciliation_history_details)
        self.reconciliation_history_table.selectionModel().currentRowChanged.connect(self._show_reconciliation_history)
        tabs.addTab(history_panel, "Saved reconciliations")
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_review_source_button()
        if history:
            self.reconciliation_history_table.selectRow(0)

    def _preview(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            saved = store.load_import(self.model.rows[index.row()].source_sha256)
        V2EvidencePreview(saved, self).exec()

    def _preview_comparison(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            saved = store.load_import(self.comparison_model.rows[index.row()].source_sha256)
        V2EvidencePreview(saved, self).exec()

    def _update_review_source_button(self, *_args) -> None:
        index = self.table.currentIndex()
        self.review_source_button.setEnabled(index.isValid())
        if index.isValid():
            status = self.model.data(self.model.index(index.row(), 10))
            self.review_source_button.setText(f"Review selected source ({status})")
        else:
            self.review_source_button.setText("Review selected source")

    def _show_reconciliation_details(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self.save_reconciliation_button.setEnabled(False)
        if current.isValid():
            row = self.reconciliation_model.rows[current.row()]
            self.reconciliation_details.setText(self.reconciliation_model.details(row))
            self.save_reconciliation_button.setEnabled(
                row.reconciled
                and row.posted_interpretations_reviewed
                and self.reconciliation_model.supported_codes(row)
            )
        else:
            self.reconciliation_details.setText("Select a statement to see its printed and journal endpoints.")

    def _show_reconciliation_history(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self.reconciliation_history_details.setText(
            self.reconciliation_history_model.details(self.reconciliation_history_model.rows[current.row()])
            if current.isValid()
            else "Select a saved decision to inspect its original inputs and result."
        )

    def _refresh_reconciliation(self, *_args) -> None:
        selected = self.reconciliation_table.currentIndex()
        selected_key = None
        if selected.isValid():
            row = self.reconciliation_model.rows[selected.row()]
            selected_key = row.account_id, row.source_sha256
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                reconciliation_snapshot = store.reconciliation_snapshot()
                reconciliation = reconciliation_snapshot.checks
                history = reconciliation_snapshot.history
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.reconciliation_model.replace(())
            self.reconciliation_history_model.replace(())
            self.save_reconciliation_button.setEnabled(False)
            self.reconciliation_details.setText("Reconciliation checks are unavailable. Refresh to retry.")
            self.reconciliation_history_details.setText(
                "Saved reconciliation history is unavailable. Refresh to retry."
            )
            self.reconciliation_status.setText(f"Refresh failed: {exc}")
            return
        self.reconciliation_model.replace(reconciliation)
        self.reconciliation_history_model.replace(history)
        self.reconciliation_status.setText(
            _reconciliation_unavailable_message(reconciliation_snapshot.unavailable_reason)
        )
        self.save_reconciliation_button.setEnabled(False)
        self.reconciliation_details.setText("Select a statement to see its printed and journal endpoints.")
        self.reconciliation_history_details.setText("No saved reconciliation decisions in this profile.")
        for index, row in enumerate(reconciliation):
            if (row.account_id, row.source_sha256) == selected_key:
                self.reconciliation_table.selectRow(index)
                break
        if history:
            self.reconciliation_history_table.selectRow(0)

    def _save_reconciliation(self) -> None:
        index = self.reconciliation_table.currentIndex()
        if not index.isValid():
            return
        row = self.reconciliation_model.rows[index.row()]
        if (
            not row.reconciled
            or not row.posted_interpretations_reviewed
            or not self.reconciliation_model.supported_codes(row)
        ):
            return
        reason = "Confirmed statement reconciliation"
        if self.reconciliation_reason.text().strip():
            reason += ": " + self.reconciliation_reason.text().strip()
        message = (
            f"Save this successful reconciliation for {row.account_name} through {row.period_end.isoformat()}?\n\n"
            f"{self.reconciliation_model.details(row)}\n\n"
            f"Reason: {reason}\n\n"
            "The saved decision retains this result and its input versions. "
            "Page capture and period coverage remain separate; saving does not post or adjust money."
        )
        if QMessageBox.question(self, "Confirm reconciliation decision", message) != QMessageBox.StandardButton.Yes:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                decision = store.save_reconciliation_decision(
                    row.account_id, row.source_sha256, expected_input_version=row.input_version, reason=reason
                )
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            reasons = {
                "reconciliation_changed_since_selection": "Inputs changed after this check was selected. Review the refreshed result.",
                "reconciliation_check_not_successful": "The current check is not successful and cannot be saved.",
            }
            message = reasons.get(str(exc), str(exc))
            QMessageBox.warning(self, "Reconciliation was not saved", message)
            self._refresh_reconciliation()
            self.reconciliation_status.setText(message)
            return
        self.reconciliation_reason.clear()
        self._refresh_reconciliation()
        self.reconciliation_status.setText(
            f"Saved reconciliation through {decision.cutoff_date.isoformat()}. "
            "See Saved reconciliations for retained inputs and current/stale state."
        )

    def _review_selected_source(self) -> None:
        index = self.table.currentIndex()
        if not index.isValid():
            return
        section = self.model.rows[index.row()]
        if V2StatementSourceReview(self.profile, section, self).exec() != QDialog.Accepted:
            return
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            accounts = store.financial_accounts()
            reviewed = frozenset(
                (account.id, review.source_sha256)
                for account in accounts
                for review in store.statement_source_reviews(account.id)
            )
            openings = store.earliest_source_openings()
        self.model.set_reviewed(reviewed)
        self.opening_model.replace(openings)
        self._refresh_reconciliation()
        self._update_review_source_button()

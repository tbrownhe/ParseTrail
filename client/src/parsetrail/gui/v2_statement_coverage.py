"""Read-only printed statement-period inventory for explicitly bound accounts."""

from __future__ import annotations

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
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.source_evidence import MoneyValue
from parsetrail.core.v2_profile_store import (
    EarliestSourceOpening,
    StatementCoverageRow,
    StatementJournalComparison,
    StatementReconciliationCheck,
    V2ProfileStore,
)
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview, _money
from parsetrail.gui.v2_statement_source_review import V2StatementSourceReview


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
    }

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
            "Reconciled" if row.reconciled else f"Needs review ({len(row.exceptions)})",
            difference(row.opening_difference_minor),
            difference(row.closing_difference_minor),
            difference(row.source_difference_minor),
            ", ".join(self.REASONS[reason] for reason in row.coverage_warnings) or "None identified",
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
            f"Check blockers: {', '.join(cls.REASONS[reason] for reason in row.exceptions) or 'None'}.\n"
            f"Evidence / coverage limits: {', '.join(cls.REASONS[reason] for reason in row.coverage_warnings) or 'None identified'}. "
            f"Posted interpretation review: {'Complete' if row.posted_interpretations_reviewed else 'Pending'}.\n"
            f"Source: {row.source_sha256}; rule: {row.rule}; input version: {row.input_version}"
        )


class V2StatementCoverageDialog(QDialog):
    """Show source facts and calendar relationships without reconciliation claims."""

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("2.0 statement coverage")
        self.resize(1320, 600)
        with V2ProfileStore.open(profile, read_only=True) as store:
            rows = store.statement_coverage()
            openings = store.earliest_source_openings()
            comparisons = store.statement_journal_comparisons()
            reconciliation = store.statement_reconciliation_checks()
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
        tabs = QTabWidget()
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
            "Reconciled requires matching printed and journal opening/closing balances, complete source allocation, "
            "reviewed source provenance and a current opening decision. "
            "Page capture, period coverage and posted interpretation review remain separate. "
            "Select a row for exact blockers and values."
        )
        reconciliation_scope.setWordWrap(True)
        reconciliation_layout.addWidget(reconciliation_scope)
        self.reconciliation_model = _ReconciliationModel(reconciliation, self)
        self.reconciliation_table = QTableView()
        self.reconciliation_table.setModel(self.reconciliation_model)
        self.reconciliation_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.reconciliation_table.setSelectionBehavior(QAbstractItemView.SelectRows)
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
        tabs.addTab(reconciliation_panel, "Reconciliation check")
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_review_source_button()

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
        if current.isValid():
            self.reconciliation_details.setText(
                self.reconciliation_model.details(self.reconciliation_model.rows[current.row()])
            )
        else:
            self.reconciliation_details.setText("Select a statement to see its printed and journal endpoints.")

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
            reconciliation = store.statement_reconciliation_checks()
        self.model.set_reviewed(reviewed)
        self.opening_model.replace(openings)
        self.reconciliation_model.replace(reconciliation)
        self._update_review_source_button()

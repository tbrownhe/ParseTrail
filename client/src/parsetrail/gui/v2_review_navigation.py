"""Local filtering, stable row selection and exact sorting for source review."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QItemSelectionModel, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


def reviewed_elsewhere(row):
    return row is not None and row.entry_key is None and row.status == "Already posted to the ledger"


def tracking_scope_label(scope):
    return {
        "account_total": "Whole account",
        "cash_component": "Cash component only",
        "principal_component": "Loan principal only",
        None: "Not established",
    }.get(scope, (scope or "Not established").replace("_", " ").capitalize())


def review_status_label(status):
    """Keep table labels compact; the row status and tooltip retain full detail."""
    return {
        "Ready for purpose review": "Ready for review",
        "Already posted to the ledger": "Reviewed in another workflow",
        "Enable assumed dates or enter a corrected date": "Review posting date",
        "Cross-source occurrence needs review": "Possible repeat — review needed",
        "Repeated supporting evidence; post the retained row": "Supporting — use retained row",
        "Reviewed zero amount": "$0.00 reviewed · no posting",
    }.get(status, status)


def review_state(row):
    if row.entry_key is not None or reviewed_elsewhere(row) or row.status == "Reviewed zero amount":
        return "reviewed"
    return "ready" if row.status == "Ready for purpose review" else "blocked"


class StagedRowPresentation:
    """Local proposal cues; the immutable financial row never changes state."""

    def set_staged(self, staged, details, changed=()):
        if getattr(self, "_resetting", False):
            # Selection signals emitted by begin/endResetModel may update form
            # cues. A dataChanged notification during that reset is invalid;
            # the completed snapshot refresh projects staging afterward.
            return
        values = (dict(staged), dict(details), frozenset(changed))
        if values == getattr(self, "_stage_presentation", None):
            return
        self._stage_presentation = values
        self.staged, self.staging_details, self.staging_changed = values
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))

    def staged_data(self, index, role, row):
        staged = row.row_id in getattr(self, "staged", {})
        choice_column = index.column() == self.columnCount() - 1
        if (
            staged
            and index.column() == self.columnCount() - 2
            and role in {Qt.DisplayRole, Qt.AccessibleTextRole, Qt.UserRole}
        ):
            from parsetrail.core.v2_ordinary_batch import OrdinaryTransferSelection

            if isinstance(self.staged[row.row_id], OrdinaryTransferSelection):
                return True, "Transfer staged · not posted"
        intent = getattr(self, "pending_transfers", {}).get(row.row_id)
        if not staged and intent is not None and intent.review.action == "pending" and intent.status != "consumed":
            label = {
                "waiting": "Transfer saved · waiting",
                "match_available": "Transfer saved · match available",
                "stale": "Transfer saved · needs review",
                "blocked": "Transfer saved · prerequisites blocked",
            }.get(intent.status, "Transfer designation saved")
            if (choice_column or index.column() == self.columnCount() - 2) and role in {
                Qt.DisplayRole,
                Qt.AccessibleTextRole,
                Qt.UserRole,
            }:
                return True, label
            if role == Qt.ToolTipRole:
                return True, f"{label}. No money posted.\nSaved reason: {intent.reason}"
        if staged and role == Qt.BackgroundRole:
            return True, QColor("#EDF7EF")
        if staged and role == Qt.FontRole and choice_column:
            font = QFont()
            font.setBold(True)
            return True, font
        if choice_column and role in {Qt.DisplayRole, Qt.AccessibleTextRole, Qt.UserRole}:
            value = (
                "Staged · needs recheck"
                if staged and (row.entry_key is not None or reviewed_elsewhere(row))
                else "Staged · changes not staged"
                if staged and row.row_id in self.staging_changed
                else "Staged · not saved"
                if staged
                else "Reviewed elsewhere"
                if reviewed_elsewhere(row)
                else "Reviewed · " + (row.purpose or "").replace("_", " ").title()
                if row.entry_key is not None or row.status == "Reviewed zero amount"
                else "Not staged"
            )
            return True, value
        if staged and role == Qt.ToolTipRole:
            return True, self.staging_details.get(row.row_id, "Staged locally; not saved.")
        return False, None


class ReviewProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.words, self.status = (), "needs"
        self.setDynamicSortFilter(True)

    def filterAcceptsRow(self, source_row, _parent):
        model = self.sourceModel()
        row = model.rows[source_row]
        state = review_state(row)
        if self.status == "needs" and state == "reviewed":
            return False
        if self.status not in {"needs", "all"} and state != self.status:
            return False
        text = " ".join(str(model.data(model.index(source_row, col)) or "") for col in range(model.columnCount()))
        return all(word in text.casefold() for word in self.words)

    def lessThan(self, left, right):
        model = self.sourceModel()
        a, b = model.data(left, Qt.UserRole), model.data(right, Qt.UserRole)
        if a == b:
            return model.rows[left.row()].row_id < model.rows[right.row()].row_id
        if a is None or b is None:
            return a is None
        return a < b


class ReviewNavigation(QWidget):
    scope_changed = Signal()
    exact_row_requested = Signal(str)

    def __init__(self, parent, model, table):
        super().__init__(parent)
        self.model, self.table = model, table
        self.proxy = ReviewProxy(self)
        self.proxy.setSourceModel(model)
        table.setModel(self.proxy)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        palette = table.palette()
        palette.setColor(QPalette.Inactive, QPalette.Highlight, QColor("#DCEBFA"))
        palette.setColor(QPalette.Inactive, QPalette.HighlightedText, QColor("#172B4D"))
        table.setPalette(palette)
        # Windows' native unfocused selection ignores the palette highlight.
        # Scope the fallback to this table after focus moves into review fields;
        # focused keyboard/table selection keeps the platform's native painting.
        table.setProperty("reviewSelectionFocus", table.hasFocus())
        table.setStyleSheet(
            'QTableView[reviewSelectionFocus="false"]::item:selected { background-color: #DCEBFA; color: #172B4D; }'
        )
        table.installEventFilter(self)
        table.setTabKeyNavigation(False)
        table.setSortingEnabled(True)
        table.sortByColumn(-1, Qt.AscendingOrder)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search transactions, accounts or amounts")
        self.search.setAccessibleName("Search source transactions")
        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName("Review status filter")
        for label, key in (
            ("Needs review", "needs"),
            ("Ready", "ready"),
            ("Blocked", "blocked"),
            ("Reviewed", "reviewed"),
            ("All", "all"),
        ):
            self.status_filter.addItem(label, key)
        self.count = QLabel()
        self.count.setToolTip(
            "Ctrl+click adds or removes rows; Shift selects a range; Ctrl+A selects visible rows only."
        )
        table.selectionModel().selectionChanged.connect(self.update_count)
        self.next_button = QPushButton("Next unstaged")
        self.next_button.setShortcut(QKeySequence("Alt+N"))
        self.next_button.setToolTip("Move to the next visible unstaged row needing review (Alt+N)")
        self.next_button.clicked.connect(self.next_pending)
        layout.addWidget(self.search, 1)
        layout.addWidget(self.status_filter)
        layout.addWidget(self.count)
        layout.addWidget(self.next_button)
        self.search.textChanged.connect(self._filter)
        self.status_filter.currentIndexChanged.connect(self._filter)
        self.proxy.modelReset.connect(self.update_count)
        self.proxy.rowsInserted.connect(self.update_count)
        self.proxy.rowsRemoved.connect(self.update_count)
        self.model.dataChanged.connect(self.update_count)
        shortcut = QShortcut(QKeySequence.Find, parent)
        shortcut.activated.connect(self.search.setFocus)
        self.update_count()

    def eventFilter(self, watched, event):
        if watched is self.table and event.type() in {QEvent.FocusIn, QEvent.FocusOut}:
            watched.setProperty("reviewSelectionFocus", event.type() == QEvent.FocusIn)
            watched.style().unpolish(watched)
            watched.style().polish(watched)
            watched.viewport().update()
        return super().eventFilter(watched, event)

    def _filter(self, *_args):
        selected = self.current()
        self.proxy.words = tuple(self.search.text().casefold().split())
        self.proxy.status = self.status_filter.currentData()
        self.proxy.invalidate()
        if selected is not None:
            self.select_id(selected.row_id)
        if not self.table.currentIndex().isValid() and self.proxy.rowCount():
            self.table.selectRow(0)
        self.update_count()

        self.scope_changed.emit()

    def update_count(self, *_args):
        selected = len(self.table.selectionModel().selectedRows())
        self.count.setText(f"{self.proxy.rowCount()} of {len(self.model.rows)} · {selected} selected")
        self.next_button.setEnabled(
            any(
                review_state(row) != "reviewed" and row.row_id not in getattr(self.model, "staged", {})
                for row in (
                    self.model.rows[self.proxy.mapToSource(self.proxy.index(index, 0)).row()]
                    for index in range(self.proxy.rowCount())
                )
            )
        )

    def current(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        # Ctrl may leave currentIndex on a deselected anchor. A single selected
        # row, rather than that anchor, is the only possible single-entry scope.
        current = selected[0] if len(selected) == 1 else self.table.currentIndex()
        index = self.proxy.mapToSource(current)
        return self.model.rows[index.row()] if index.isValid() and index.row() < len(self.model.rows) else None

    def selected(self):
        return tuple(
            self.model.rows[self.proxy.mapToSource(index).row()]
            for index in sorted(self.table.selectionModel().selectedRows(), key=lambda index: index.row())
            if index.isValid() and self.proxy.mapToSource(index).isValid()
        )

    def select_id(self, row_id):
        for i, row in enumerate(self.model.rows):
            if row.row_id == row_id:
                index = self.proxy.mapFromSource(self.model.index(i, 0))
                if index.isValid():
                    self.table.selectRow(index.row())
                    self.table.scrollTo(index)
                    return True
        return False

    def select_ids(self, row_ids):
        """Restore only still-visible members after an explicit category refresh."""
        wanted = set(row_ids)
        selection = self.table.selectionModel()
        selection.blockSignals(True)
        selection.clearSelection()
        for i, row in enumerate(self.model.rows):
            index = self.proxy.mapFromSource(self.model.index(i, 0))
            if row.row_id in wanted and index.isValid():
                selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        selection.blockSignals(False)
        self.update_count()

    def reveal_row(self, row_id):
        """Expose an exact report-linked row, including a reviewed or blocked owner."""
        self.exact_row_requested.emit(row_id)
        self.search.clear()
        self.status_filter.setCurrentIndex(self.status_filter.findData("all"))
        return self.select_id(row_id)

    def next_pending(self):
        count = self.proxy.rowCount()
        if not count:
            return
        start = self.table.currentIndex().row()
        for offset in range(1, count + 1):
            index = self.proxy.index((start + offset) % count, 0)
            row = self.model.rows[self.proxy.mapToSource(index).row()]
            if review_state(row) != "reviewed" and row.row_id not in getattr(self.model, "staged", {}):
                self.table.selectRow(index.row())
                self.table.scrollTo(index)
                return

    def replace(self, rows, selected_row_id=None):
        old = self.current()
        selected_row_id = selected_row_id or (old.row_id if old else None)
        scroll = self.table.verticalScrollBar().value()
        self.model.replace(rows)
        self.update_count()
        if not self.select_id(selected_row_id) and self.proxy.rowCount():
            self.table.selectRow(0)
        self.table.verticalScrollBar().setValue(scroll)
        self.scope_changed.emit()

"""Local filtering, stable row selection and exact sorting for source review."""

from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


def reviewed_elsewhere(row):
    return row is not None and row.entry_key is None and row.status == "Already posted to the ledger"


def review_state(row):
    if row.entry_key is not None or reviewed_elsewhere(row):
        return "reviewed"
    return "ready" if row.status == "Ready for purpose review" else "blocked"


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

    def __init__(self, parent, model, table):
        super().__init__(parent)
        self.model, self.table = model, table
        self.proxy = ReviewProxy(self)
        self.proxy.setSourceModel(model)
        table.setModel(self.proxy)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
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
        self.next_button = QPushButton("Next pending")
        self.next_button.setShortcut(QKeySequence("Alt+N"))
        self.next_button.setToolTip("Move to the next visible row needing review (Alt+N)")
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
        shortcut = QShortcut(QKeySequence.Find, parent)
        shortcut.activated.connect(self.search.setFocus)
        self.update_count()

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
        self.count.setText(f"{self.proxy.rowCount()} of {len(self.model.rows)}")
        self.next_button.setEnabled(any(review_state(row) != "reviewed" for row in self.model.rows))

    def current(self):
        index = self.proxy.mapToSource(self.table.currentIndex())
        return self.model.rows[index.row()] if index.isValid() and index.row() < len(self.model.rows) else None

    def selected(self):
        return tuple(
            self.model.rows[self.proxy.mapToSource(index).row()] for index in self.table.selectionModel().selectedRows()
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

    def next_pending(self):
        count = self.proxy.rowCount()
        if not count:
            return
        start = self.table.currentIndex().row()
        for offset in range(1, count + 1):
            index = self.proxy.index((start + offset) % count, 0)
            row = self.model.rows[self.proxy.mapToSource(index).row()]
            if review_state(row) != "reviewed":
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

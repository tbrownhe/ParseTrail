"""Source-identity document discovery with typed sorting and explicit filters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionFocusRect,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_institutions import institution_label
from parsetrail.gui.v2_document_browser import (
    document_account_association,
    document_period,
    document_status,
    document_title,
)

SOURCE_ROLE = int(Qt.UserRole)
SUMMARY_ROLE = SOURCE_ROLE + 1


def document_type(summary):
    parser = summary.parser_id
    if any(token in parser for token in ("401k", "vanguard", "transamerica")):
        return "Retirement summary"
    if "fidelityhsa" in parser:
        return "HSA summary"
    if "hsa_cash" in parser:
        return "HSA cash statement"
    if any(token in parser for token in ("capitaloneauto", "wfloan", "mohela")):
        return "Loan statement"
    return "Statement" if summary.document_kind == "statement" else "Activity export"


def review_key(summary):
    if summary.unassigned_source_accounts or summary.unassigned_activity_rows:
        return "account"
    if summary.pending_summary_values:
        return "value"
    if summary.pending_activity_rows:
        return "activity"
    return "complete"


def review_label(summary):
    key = review_key(summary)
    if key == "account":
        return "Confirm accounts"
    if key == "value":
        return "Review statement value"
    if key == "activity":
        count = summary.pending_activity_rows
        return f"Review {count} row" + ("s" if count != 1 else "")
    return "Value recorded" if summary.reviewed_summary_values else "No activity pending"


def account_label(summary):
    values = summary.bound_account_names or summary.source_accounts
    return "; ".join(values) if values else "Account not confirmed"


@dataclass(frozen=True)
class DocumentFilters:
    query: str = ""
    account: str | None = None
    institution: str | None = None
    kind: str | None = None
    review: str | None = None
    start: date | None = None
    end: date | None = None

    @property
    def active_count(self):
        return sum(
            bool(value)
            for value in (
                self.query.strip(),
                self.account is not None,
                self.institution is not None,
                self.kind,
                self.review,
                self.start is not None,
            )
        )


def matches(summary, state):
    text = " ".join(
        (
            account_label(summary),
            institution_label(summary.institution_key) if summary.institution_key else "Unknown institution",
            document_period(summary),
            document_type(summary),
            document_status(summary),
            summary.parser_id,
            " ".join(summary.source_accounts),
        )
    ).casefold()
    if not all(word in text for word in state.query.casefold().split()):
        return False
    if state.account is not None:
        if state.account == "":
            if not (
                summary.unassigned_source_accounts
                or summary.unassigned_activity_rows
                or not summary.associated_account_ids
            ):
                return False
        elif state.account not in summary.associated_account_ids:
            return False
    if state.institution is not None and (summary.institution_key or "") != state.institution:
        return False
    if state.kind is not None and document_type(summary) != state.kind:
        return False
    if state.review is not None and review_key(summary) != state.review:
        return False
    if state.start is not None:
        if summary.start is None or summary.end is None:
            return False
        if state.end < state.start or summary.end < state.start or summary.start > state.end:
            return False
    return True


class DocumentsModel(QAbstractTableModel):
    HEADERS = ("Account(s)", "Institution", "Period", "Type", "Review")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = ()

    def replace(self, summaries):
        self.beginResetModel()
        self.rows = tuple(summaries)
        self.endResetModel()

    def rowCount(self, _parent=QModelIndex()):
        return 0 if _parent.isValid() else len(self.rows)

    def columnCount(self, _parent=QModelIndex()):
        return 0 if _parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        return self.HEADERS[section] if orientation == Qt.Horizontal and role == Qt.DisplayRole else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        summary = self.rows[index.row()]
        if role == SOURCE_ROLE:
            return summary.source_sha256
        if role == SUMMARY_ROLE:
            return summary
        if role == Qt.ToolTipRole:
            return (
                f"{document_title(summary)}\n{document_period(summary)}\n{document_status(summary)}\n"
                f"{document_account_association(summary)}\nSource checks and complete capture are separate."
            )
        if role == Qt.DisplayRole:
            return (
                account_label(summary),
                institution_label(summary.institution_key) if summary.institution_key else "Unknown",
                f"{summary.start.isoformat() if summary.start else 'Unknown'} – "
                f"{summary.end.isoformat() if summary.end else 'unknown'}",
                document_type(summary),
                review_label(summary),
            )[index.column()]
        return None


class DocumentsProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filters = DocumentFilters()
        self.setDynamicSortFilter(True)

    def set_filters(self, filters):
        self.beginFilterChange()
        self.filters = filters
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, row, parent):
        return matches(self.sourceModel().rows[row], self.filters)

    def lessThan(self, left, right):
        a, b = self.sourceModel().rows[left.row()], self.sourceModel().rows[right.row()]
        column = left.column()
        if column == 2:
            a_date, b_date = a.end or a.start, b.end or b.start
            if (a_date is None) != (b_date is None):
                return (a_date is None) if self.sortOrder() == Qt.DescendingOrder else (b_date is None)

            def key(item):
                return item.end or item.start or date.min, item.start or date.min, item.source_sha256
        elif column == 4:

            def key(item):
                return (
                    {"account": 0, "value": 1, "activity": 2, "complete": 3}[review_key(item)],
                    item.unassigned_source_accounts
                    + item.unassigned_activity_rows
                    + item.pending_summary_values
                    + item.pending_activity_rows,
                    item.source_sha256,
                )
        else:

            def key(item):
                return (
                    (
                        account_label(item)
                        if column == 0
                        else institution_label(item.institution_key)
                        if column == 1 and item.institution_key
                        else "Unknown"
                        if column == 1
                        else document_type(item)
                    ).casefold(),
                    item.source_sha256,
                )

        return key(a) < key(b)


class DocumentsHeader(QHeaderView):
    """Keep column sorting reachable without a mouse."""

    def __init__(self, parent):
        super().__init__(Qt.Horizontal, parent)
        self._keyboard_section = 2
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Document columns. Left and right choose a column; Space sorts it.")
        self.setToolTip("Click a column to sort. With keyboard focus, use Left/Right then Space to sort.")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            self._keyboard_section = (
                0
                if event.key() == Qt.Key_Home
                else self.count() - 1
                if event.key() == Qt.Key_End
                else max(0, min(self.count() - 1, self._keyboard_section + (1 if event.key() == Qt.Key_Right else -1)))
            )
            self.viewport().update()
            event.accept()
        elif event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            order = (
                Qt.DescendingOrder
                if self.sortIndicatorSection() == self._keyboard_section
                and self.sortIndicatorOrder() == Qt.AscendingOrder
                else Qt.AscendingOrder
            )
            self.setSortIndicator(self._keyboard_section, order)
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintSection(self, painter, rect, logical_index):
        super().paintSection(painter, rect, logical_index)
        if self.hasFocus() and logical_index == self._keyboard_section:
            option = QStyleOptionFocusRect()
            option.initFrom(self)
            option.rect = rect.adjusted(2, 2, -2, -2)
            self.style().drawPrimitive(QStyle.PE_FrameFocusRect, option, painter, self)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.viewport().update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.viewport().update()

    def focusNextPrevChild(self, forward):
        # QAbstractItemView otherwise consumes Tab as cell navigation even for
        # a header. Leave this single header control through the window chain.
        candidate = self.nextInFocusChain() if forward else self.previousInFocusChain()
        while candidate is not self:
            if (
                candidate.isVisibleTo(self.window())
                and candidate.isEnabled()
                and candidate.focusPolicy() & Qt.TabFocus
                and not self.isAncestorOf(candidate)
            ):
                candidate.setFocus(Qt.TabFocusReason if forward else Qt.BacktabFocusReason)
                return True
            candidate = candidate.nextInFocusChain() if forward else candidate.previousInFocusChain()
        return False


class DocumentsTable(QTableView):
    source_changed = Signal()
    review_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.documents_model = DocumentsModel(self)
        self.documents_proxy = DocumentsProxy(self)
        self.documents_proxy.setSourceModel(self.documents_model)
        self.setModel(self.documents_proxy)
        self.setHorizontalHeader(DocumentsHeader(self))
        self.setAccessibleName("Saved documents table")
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(36)
        self.horizontalHeader().setSectionsMovable(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate((220, 120, 195, 110, 175)):
            self.setColumnWidth(column, width)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSortingEnabled(True)
        self.sortByColumn(2, Qt.DescendingOrder)
        self.selectionModel().currentRowChanged.connect(self.source_changed)
        self.doubleClicked.connect(self.review_requested)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.selected_source() is not None:
            self.review_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def selected_source(self):
        index = self.currentIndex()
        return index.data(SOURCE_ROLE) if index.isValid() else None

    def visible_sources(self):
        return tuple(self.model().index(row, 0).data(SOURCE_ROLE) for row in range(self.model().rowCount()))

    def select_source(self, source_id):
        for row in range(self.model().rowCount()):
            index = self.model().index(row, 0)
            if index.data(SOURCE_ROLE) == source_id:
                self.setCurrentIndex(index)
                self.selectRow(row)
                self.scrollTo(index)
                return True
        self.clearSelection()
        self.setCurrentIndex(QModelIndex())
        return False

    def replace(self, summaries, selected=None, *, select_first=False):
        selection = self.selectionModel()
        was_blocked = selection.blockSignals(True)
        try:
            self.documents_model.replace(summaries)
            if not self.select_source(selected) and select_first and self.model().rowCount():
                self.select_source(self.model().index(0, 0).data(SOURCE_ROLE))
        finally:
            selection.blockSignals(was_blocked)


class DocumentsFilterBar(QWidget):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("documentSearch")
        self.search.setPlaceholderText("Find an account, statement period or document type")
        self.search.setAccessibleName("Find documents")
        self.search.setClearButtonEnabled(True)
        row.addWidget(self.search, 1)
        self.toggle = QToolButton()
        self.toggle.setText("Filters")
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName("Show document column filters")
        row.addWidget(self.toggle)
        self.active = QLabel()
        row.addWidget(self.active)
        self.clear = QPushButton("Clear filters")
        row.addWidget(self.clear)
        layout.addLayout(row)
        self.panel = QWidget()
        self.panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        grid = QGridLayout(self.panel)
        grid.setContentsMargins(0, 0, 0, 0)
        self.account, self.institution, self.kind, self.review = (QComboBox() for _ in range(4))
        for index, (label, widget) in enumerate(
            (("Account", self.account), ("Institution", self.institution), ("Type", self.kind), ("Review", self.review))
        ):
            widget.setAccessibleName(f"Filter documents by {label.lower()}")
            widget.setMinimumContentsLength(12)
            widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            grid.addWidget(QLabel(label), index // 2, (index % 2) * 2)
            grid.addWidget(widget, index // 2, (index % 2) * 2 + 1)
            widget.currentIndexChanged.connect(self._changed)
        self.period = QCheckBox("Periods overlapping")
        self.period.setToolTip("Includes statements overlapping these inclusive dates. Unknown periods are excluded.")
        self.start = QDateEdit(QDate(1900, 1, 1))
        self.end = QDateEdit(QDate.currentDate())
        for label, widget in (("From date", self.start), ("Through date", self.end)):
            widget.setAccessibleName(label)
            widget.setDisplayFormat("yyyy-MM-dd")
            widget.setCalendarPopup(True)
            widget.dateChanged.connect(self._changed)
        period_row = QHBoxLayout()
        period_row.addWidget(self.period)
        period_row.addWidget(self.start)
        period_row.addWidget(QLabel("through"))
        period_row.addWidget(self.end)
        period_row.addStretch()
        grid.addLayout(period_row, 2, 0, 1, 4)
        self.period.toggled.connect(self._changed)
        self.toggle.toggled.connect(self.panel.setVisible)
        self.panel.hide()
        layout.addWidget(self.panel)
        self.search.textChanged.connect(self._changed)
        self.clear.clicked.connect(self._clear)
        self.set_options(())
        self._refresh_labels()

    def state(self):
        return DocumentFilters(
            self.search.text(),
            self.account.currentData(),
            self.institution.currentData(),
            self.kind.currentData(),
            self.review.currentData(),
            self.start.date().toPython() if self.period.isChecked() else None,
            self.end.date().toPython() if self.period.isChecked() else None,
        )

    def set_state(self, state, *, emit=False):
        self._updating = True
        try:
            self.search.setText(state.query)
            for widget, value in (
                (self.account, state.account),
                (self.institution, state.institution),
                (self.kind, state.kind),
                (self.review, state.review),
            ):
                widget.setCurrentIndex(max(0, widget.findData(value)))
            self.period.setChecked(state.start is not None)
            if state.start is not None:
                self.start.setDate(QDate(state.start.year, state.start.month, state.start.day))
                self.end.setDate(QDate(state.end.year, state.end.month, state.end.day))
        finally:
            self._updating = False
        self._refresh_labels()
        if emit:
            self.changed.emit(self.state())

    def set_options(self, summaries):
        state = self.state()
        prior_labels = {
            widget: (widget.currentData(), widget.currentText())
            for widget in (self.account, self.institution, self.kind, self.review)
        }
        accounts, institutions, kinds = {}, {}, set()
        for summary in summaries:
            accounts.update(zip(summary.associated_account_ids, summary.bound_account_names, strict=True))
            institutions[summary.institution_key or ""] = (
                institution_label(summary.institution_key) if summary.institution_key else "Unknown institution"
            )
            kinds.add(document_type(summary))
        self._updating = True
        try:
            for widget, all_label, values in (
                (
                    self.account,
                    "All accounts",
                    (("", "Unconfirmed accounts"), *sorted(accounts.items(), key=lambda v: v[1].casefold())),
                ),
                (self.institution, "All institutions", sorted(institutions.items(), key=lambda v: v[1].casefold())),
                (self.kind, "All types", ((kind, kind) for kind in sorted(kinds))),
                (
                    self.review,
                    "All review states",
                    (
                        ("account", "Confirm accounts"),
                        ("value", "Review values"),
                        ("activity", "Review activity"),
                        ("complete", "No review pending"),
                    ),
                ),
            ):
                widget.clear()
                widget.addItem(all_label, None)
                for value, label in values:
                    widget.addItem(label, value)
                prior_value, prior_label = prior_labels[widget]
                if prior_value is not None and widget.findData(prior_value) < 0:
                    widget.addItem(prior_label, prior_value)
        finally:
            self._updating = False
        self.set_state(state)

    def _refresh_labels(self):
        count = self.state().active_count
        self.active.setText(f"{count} active" if count else "")
        self.clear.setVisible(bool(count))
        self.start.setEnabled(self.period.isChecked())
        self.end.setEnabled(self.period.isChecked())

    def _clear(self):
        self.set_state(DocumentFilters(), emit=True)

    def _changed(self, *_args):
        if not self._updating:
            self._refresh_labels()
            self.changed.emit(self.state())

"""Qt models for transaction review."""

from PySide6 import QtCore, QtGui

from parsetrail.core.review import TransactionRecord


class TransactionTableModel(QtCore.QAbstractTableModel):
    """Display review records and allow their verified flag to change in memory."""

    COL_ID = 0
    COL_DATE = 1
    COL_ACCOUNT = 2
    COL_DESC = 3
    COL_AMOUNT = 4
    COL_CATEGORY = 5
    COL_VERIFIED = 6
    COL_CONFIDENCE = 7
    COL_CLUSTER = 8

    HEADERS = [
        "ID",
        "Date",
        "Account",
        "Description",
        "Amount",
        "Category",
        "Verified",
        "Confidence",
        "Cluster",
    ]

    def __init__(self, records: list[TransactionRecord] | None = None, parent=None):
        super().__init__(parent)
        self._records: list[TransactionRecord] = records or []

    def set_records(self, records: list[TransactionRecord]):
        self.beginResetModel()
        self._records = records
        self.endResetModel()

    def record_at(self, row: int) -> TransactionRecord:
        return self._records[row]

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index: QtCore.QModelIndex, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        col = index.column()
        record = self._records[index.row()]
        if role == QtCore.Qt.DisplayRole:
            if col == self.COL_ID:
                return record.transaction_id
            if col == self.COL_DATE:
                return record.date
            if col == self.COL_ACCOUNT:
                return record.account_name
            if col == self.COL_DESC:
                return record.description
            if col == self.COL_AMOUNT:
                return f"{record.amount:.2f}"
            if col == self.COL_CATEGORY:
                return record.category_name
            if col == self.COL_CONFIDENCE:
                return f"{record.confidence:.3f}" if record.confidence is not None else ""
            if col == self.COL_CLUSTER:
                return "" if record.cluster is None or record.cluster == -1 else str(record.cluster)

        if role == QtCore.Qt.UserRole:
            if col == self.COL_AMOUNT:
                return record.amount
            if col == self.COL_CONFIDENCE:
                return record.confidence if record.confidence is not None else -1.0
            if col == self.COL_ID:
                return record.transaction_id
            if col == self.COL_CLUSTER:
                return record.cluster if record.cluster is not None else -1
            if col == self.COL_DATE:
                return record.date or ""
            if col == self.COL_ACCOUNT:
                return (record.account_name or "").lower()
            if col == self.COL_DESC:
                return (record.description or "").lower()
            if col == self.COL_CATEGORY:
                return (record.category_name or "").lower()
            if col == self.COL_VERIFIED:
                return int(record.verified)

        if role == QtCore.Qt.BackgroundRole:
            if col == self.COL_CATEGORY and record.category_id is not None and not record.category_active:
                return QtGui.QBrush(QtGui.QColor(255, 220, 220))
        if role == QtCore.Qt.CheckStateRole and col == self.COL_VERIFIED:
            return QtCore.Qt.Checked if record.verified else QtCore.Qt.Unchecked
        if role == QtCore.Qt.TextAlignmentRole:
            if col in (self.COL_AMOUNT, self.COL_CONFIDENCE, self.COL_ID, self.COL_CLUSTER):
                return QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
            return QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
        return None

    def flags(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        base_flags = QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
        if index.column() == self.COL_VERIFIED:
            return base_flags | QtCore.Qt.ItemIsUserCheckable
        return base_flags

    def setData(self, index: QtCore.QModelIndex, value, role=QtCore.Qt.EditRole):
        if not index.isValid():
            return False
        record = self._records[index.row()]
        if index.column() == self.COL_VERIFIED and role == QtCore.Qt.CheckStateRole:
            record.verified = value == QtCore.Qt.Checked
            self.dataChanged.emit(index, index, [QtCore.Qt.CheckStateRole])
            return True
        return False


class TransactionFilterProxyModel(QtCore.QSortFilterProxyModel):
    """Filter transaction descriptions, categories, and accounts by substring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""
        self.setSortRole(QtCore.Qt.UserRole)

    def setFilterText(self, text: str):
        self._filter_text = text.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        if not self._filter_text:
            return True
        model: TransactionTableModel = self.sourceModel()
        description = model.data(model.index(source_row, TransactionTableModel.COL_DESC), QtCore.Qt.DisplayRole) or ""
        category = model.data(model.index(source_row, TransactionTableModel.COL_CATEGORY), QtCore.Qt.DisplayRole) or ""
        account = model.data(model.index(source_row, TransactionTableModel.COL_ACCOUNT), QtCore.Qt.DisplayRole) or ""
        return self._filter_text in f"{description} {category} {account}".lower()

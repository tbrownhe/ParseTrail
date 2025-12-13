from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd
from loguru import logger
from parsetrail.core.categorize import transactions as categorize_transactions
from parsetrail.core.cluster import recurring_transactions
from parsetrail.core.orm import Categories, Transactions
from parsetrail.core.query import update_db_where
from PyQt5 import QtCore, QtWidgets, QtGui
from sqlalchemy.orm import sessionmaker, joinedload
from parsetrail.core.settings import settings


@dataclass
class TransactionRecord:
    transaction_id: int
    date: str
    account_name: str
    description: str
    amount: float
    category_id: Optional[int]
    category_name: str
    verified: bool
    category_active: bool
    confidence: Optional[float] = None
    cluster: Optional[int] = None
    orig_category_id: Optional[int] = field(init=False)
    orig_verified: bool = field(init=False)

    def __post_init__(self):
        self.orig_category_id = self.category_id
        self.orig_verified = self.verified


class TransactionTableModel(QtCore.QAbstractTableModel):
    """
    A table model for displaying and editing transaction records.
    Category is editable; Verified is shown as a checkbox.
    """

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

    def __init__(self, records: List[TransactionRecord] | None = None, parent=None):
        super().__init__(parent)
        self._records: List[TransactionRecord] = records or []

    def set_records(self, records: List[TransactionRecord]):
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
        if orientation == QtCore.Qt.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index: QtCore.QModelIndex, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        rec = self._records[row]

        if role == QtCore.Qt.DisplayRole:
            if col == self.COL_ID:
                return rec.transaction_id
            elif col == self.COL_DATE:
                return rec.date
            elif col == self.COL_ACCOUNT:
                return rec.account_name
            elif col == self.COL_DESC:
                return rec.description
            elif col == self.COL_AMOUNT:
                return f"{rec.amount:.2f}"
            elif col == self.COL_CATEGORY:
                return rec.category_name
            elif col == self.COL_CONFIDENCE:
                return f"{rec.confidence:.3f}" if rec.confidence is not None else ""
            elif col == self.COL_CLUSTER:
                return "" if rec.cluster is None or rec.cluster == -1 else str(rec.cluster)

        if role == QtCore.Qt.UserRole:
            # Numeric columns: use raw numeric values
            if col == self.COL_AMOUNT:
                return rec.amount
            if col == self.COL_CONFIDENCE:
                return rec.confidence if rec.confidence is not None else -1.0
            if col == self.COL_ID:
                return rec.transaction_id
            if col == self.COL_CLUSTER:
                return rec.cluster if rec.cluster is not None else -1

            # Text / boolean columns: use normalized strings or ints
            if col == self.COL_DATE:
                return rec.date or ""
            if col == self.COL_ACCOUNT:
                return (rec.account_name or "").lower()
            if col == self.COL_DESC:
                return (rec.description or "").lower()
            if col == self.COL_CATEGORY:
                return (rec.category_name or "").lower()
            if col == self.COL_VERIFIED:
                return int(rec.verified)

        if role == QtCore.Qt.BackgroundRole:
            # Highlight light red inactive categories (archived)
            if col == self.COL_CATEGORY and rec.category_id is not None and not rec.category_active:
                return QtGui.QBrush(QtGui.QColor(255, 220, 220))

        if role == QtCore.Qt.CheckStateRole and col == self.COL_VERIFIED:
            return QtCore.Qt.Checked if rec.verified else QtCore.Qt.Unchecked

        if role == QtCore.Qt.TextAlignmentRole:
            if col in (
                self.COL_AMOUNT,
                self.COL_CONFIDENCE,
                self.COL_ID,
                self.COL_CLUSTER,
            ):
                return QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
            return QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter

        return None

    def flags(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return QtCore.Qt.NoItemFlags

        base_flags = QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
        col = index.column()

        # Category is read-only in the table; changes happen via bulk apply.
        if col == self.COL_VERIFIED:
            return base_flags | QtCore.Qt.ItemIsUserCheckable

        return base_flags

    def setData(self, index: QtCore.QModelIndex, value, role=QtCore.Qt.EditRole):
        if not index.isValid():
            return False

        row = index.row()
        col = index.column()
        rec = self._records[row]

        if col == self.COL_VERIFIED and role == QtCore.Qt.CheckStateRole:
            rec.verified = value == QtCore.Qt.Checked
            self.dataChanged.emit(index, index, [QtCore.Qt.CheckStateRole])
            return True

        return False


class TransactionFilterProxyModel(QtCore.QSortFilterProxyModel):
    """
    Filters by Description and Category using a simple substring match.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""
        self.setSortRole(QtCore.Qt.UserRole)  # use numeric values for sorting

    def setFilterText(self, text: str):
        self._filter_text = text.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        if not self._filter_text:
            return True

        model: TransactionTableModel = self.sourceModel()
        idx_desc = model.index(source_row, TransactionTableModel.COL_DESC)
        idx_cat = model.index(source_row, TransactionTableModel.COL_CATEGORY)
        idx_acc = model.index(source_row, TransactionTableModel.COL_ACCOUNT)

        desc = model.data(idx_desc, QtCore.Qt.DisplayRole) or ""
        cat = model.data(idx_cat, QtCore.Qt.DisplayRole) or ""
        acc = model.data(idx_acc, QtCore.Qt.DisplayRole) or ""
        text = f"{desc} {cat} {acc}".lower()
        return self._filter_text in text


class TransactionReviewWindow(QtWidgets.QMainWindow):
    """
    Main UI for reviewing, categorizing, and verifying transactions.

    - Uses normalized Categories table via Transactions.CategoryID.
    - Does not create or modify Categories; it only assigns existing ones.
    - Edits are kept in-memory until the user clicks "Save Changes".
    """

    # Signal to main window when db is updated
    data_changed = QtCore.pyqtSignal()

    def __init__(
        self,
        Session: sessionmaker,
        parent=None,
    ):
        super().__init__(parent)
        self.Session = Session

        self.categories: list[tuple[int, str]] = []  # (CategoryID, Name)

        self.setWindowTitle("Transaction Review")
        self.resize(1350, 800)

        self._create_widgets()
        self._create_layout()
        self._connect_signals()

        self._load_categories()
        self.load_transactions()

    def _create_widgets(self):
        # Filter
        self.filter_label = QtWidgets.QLabel("Filter (Description / Account / Category):")
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("e.g. 'STATE FARM', 'groceries', 'Visa'")

        # Toggle for unverified vs all
        self.chk_only_unverified = QtWidgets.QCheckBox("Show only unverified")
        self.chk_only_unverified.setChecked(True)

        # Toggle for archived vs all
        self.show_archived_only_checkbox = QtWidgets.QCheckBox("Only archived categories")
        self.show_archived_only_checkbox.setChecked(False)
        # self.show_archived_only_checkbox.toggled.connect(self.load_transactions)

        # Table + models
        self.table_view = QtWidgets.QTableView()
        self.table_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table_view.setSortingEnabled(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.setAlternatingRowColors(True)

        self.model = TransactionTableModel()
        self.proxy = TransactionFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.table_view.setModel(self.proxy)

        # Buttons - top level actions
        self.btn_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_mark_verified = QtWidgets.QPushButton("Mark Selected as Verified")
        self.btn_clear_verified = QtWidgets.QPushButton("Clear Verified on Selected")
        self.btn_auto_categorize = QtWidgets.QPushButton("Auto-Categorize Unverified")
        self.btn_save_changes = QtWidgets.QPushButton("Save Changes")

        if settings.model_path is None:
            self.btn_auto_categorize.setEnabled(False)
            self.btn_auto_categorize.setToolTip("No model path configured")

        # Category bulk-apply controls
        self.label_apply_category = QtWidgets.QLabel("Apply category to selected:")
        self.combo_category = QtWidgets.QComboBox()
        self.btn_apply_category = QtWidgets.QPushButton("Apply Category to Selected")

        # Clustering options
        self.group_clustering = QtWidgets.QGroupBox("Clustering Options")
        self.group_clustering.setCheckable(False)

        self.spin_eps = QtWidgets.QDoubleSpinBox()
        self.spin_eps.setRange(0.01, 2.0)
        self.spin_eps.setSingleStep(0.05)
        self.spin_eps.setValue(0.3)

        self.spin_min_samples = QtWidgets.QSpinBox()
        self.spin_min_samples.setRange(1, 100)
        self.spin_min_samples.setValue(2)

        self.chk_include_amount = QtWidgets.QCheckBox("Include Amount")
        self.chk_include_amount.setChecked(False)

        self.chk_use_min_size = QtWidgets.QCheckBox("Use min_size")
        self.spin_min_size = QtWidgets.QSpinBox()
        self.spin_min_size.setRange(1, 365)
        self.spin_min_size.setValue(3)

        self.chk_use_min_interval = QtWidgets.QCheckBox("Use min_interval (days)")
        self.spin_min_interval = QtWidgets.QSpinBox()
        self.spin_min_interval.setRange(0, 365)
        self.spin_min_interval.setValue(0)

        self.chk_use_max_interval = QtWidgets.QCheckBox("Use max_interval (days)")
        self.spin_max_interval = QtWidgets.QSpinBox()
        self.spin_max_interval.setRange(1, 365)
        self.spin_max_interval.setValue(35)

        self.chk_use_max_variance = QtWidgets.QCheckBox("Use max_variance")
        self.spin_max_variance = QtWidgets.QDoubleSpinBox()
        self.spin_max_variance.setRange(0.0, 10.0)
        self.spin_max_variance.setSingleStep(0.05)
        self.spin_max_variance.setValue(0.3)

        self.label_extra_stopwords = QtWidgets.QLabel("Extra stopwords (comma-separated):")
        self.edit_extra_stopwords = QtWidgets.QLineEdit()
        self.edit_extra_stopwords.setPlaceholderText("e.g. 'payment, purchase, debit'")

        self.btn_cluster = QtWidgets.QPushButton("Find Recurring Transactions")

        # Status label
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color: gray;")

        self._update_clustering_controls_enabled()

    def _create_layout(self):
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)

        # Top filter row
        top_layout = QtWidgets.QHBoxLayout()
        top_layout.addWidget(self.filter_label)
        top_layout.addWidget(self.filter_edit)
        top_layout.addSpacing(20)
        top_layout.addWidget(self.chk_only_unverified)
        top_layout.addSpacing(20)
        top_layout.addWidget(self.show_archived_only_checkbox)

        # Buttons row
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.btn_refresh)
        button_layout.addStretch(1)
        button_layout.addWidget(self.btn_auto_categorize)
        button_layout.addSpacing(20)
        button_layout.addWidget(self.btn_mark_verified)
        button_layout.addWidget(self.btn_clear_verified)
        button_layout.addWidget(self.btn_save_changes)

        # Category apply row
        apply_layout = QtWidgets.QHBoxLayout()
        apply_layout.addWidget(self.label_apply_category)
        apply_layout.addWidget(self.combo_category)
        apply_layout.addWidget(self.btn_apply_category)
        apply_layout.addStretch(1)

        # Clustering layout
        cluster_form = QtWidgets.QGridLayout()
        row = 0
        cluster_form.addWidget(QtWidgets.QLabel("eps:"), row, 0)
        cluster_form.addWidget(self.spin_eps, row, 1)
        cluster_form.addWidget(QtWidgets.QLabel("min_samples:"), row, 2)
        cluster_form.addWidget(self.spin_min_samples, row, 3)
        cluster_form.addWidget(self.chk_include_amount, row, 4)
        row += 1

        cluster_form.addWidget(self.chk_use_min_size, row, 0)
        cluster_form.addWidget(self.spin_min_size, row, 1)
        cluster_form.addWidget(self.chk_use_min_interval, row, 2)
        cluster_form.addWidget(self.spin_min_interval, row, 3)
        row += 1

        cluster_form.addWidget(self.chk_use_max_interval, row, 0)
        cluster_form.addWidget(self.spin_max_interval, row, 1)
        cluster_form.addWidget(self.chk_use_max_variance, row, 2)
        cluster_form.addWidget(self.spin_max_variance, row, 3)
        row += 1

        cluster_form.addWidget(self.label_extra_stopwords, row, 0, 1, 1)
        cluster_form.addWidget(self.edit_extra_stopwords, row, 1, 1, 3)
        cluster_form.addWidget(self.btn_cluster, row, 4)
        row += 1

        self.group_clustering.setLayout(cluster_form)

        # Status bar row
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.addWidget(self.status_label)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(top_layout)
        layout.addWidget(self.table_view)
        layout.addLayout(button_layout)
        layout.addLayout(apply_layout)
        layout.addWidget(self.group_clustering)
        layout.addLayout(bottom_layout)

        main_widget.setLayout(layout)

    def _connect_signals(self):
        self.filter_edit.textChanged.connect(self.proxy.setFilterText)
        self.chk_only_unverified.toggled.connect(self.load_transactions)
        self.show_archived_only_checkbox.toggled.connect(self.load_transactions)
        self.btn_refresh.clicked.connect(self.load_transactions)
        self.btn_mark_verified.clicked.connect(self.mark_selected_verified)
        self.btn_clear_verified.clicked.connect(self.clear_selected_verified)
        self.btn_auto_categorize.clicked.connect(self.auto_categorize_unverified)
        self.btn_save_changes.clicked.connect(self.save_changes)
        self.btn_apply_category.clicked.connect(self.apply_category_to_selected)
        self.btn_cluster.clicked.connect(self.cluster_recurring_transactions)

        self.chk_use_min_size.toggled.connect(self._update_clustering_controls_enabled)
        self.chk_use_min_interval.toggled.connect(self._update_clustering_controls_enabled)
        self.chk_use_max_interval.toggled.connect(self._update_clustering_controls_enabled)
        self.chk_use_max_variance.toggled.connect(self._update_clustering_controls_enabled)

    def _update_clustering_controls_enabled(self):
        self.spin_min_size.setEnabled(self.chk_use_min_size.isChecked())
        self.spin_min_interval.setEnabled(self.chk_use_min_interval.isChecked())
        self.spin_max_interval.setEnabled(self.chk_use_max_interval.isChecked())
        self.spin_max_variance.setEnabled(self.chk_use_max_variance.isChecked())

    def _load_categories(self):
        """
        Load active categories from the database to populate the combo box.
        The set of categories is assumed to remain stable while this window is open.
        """
        try:
            session = self.Session()
            try:
                rows: List[Categories] = (
                    session.query(Categories).filter(Categories.Active == 1).order_by(Categories.Name).all()
                )
            finally:
                session.close()

            self.categories = [(c.CategoryID, c.Name) for c in rows]

            self.combo_category.clear()
            for cat_id, name in self.categories:
                self.combo_category.addItem(name, cat_id)

            if not self.categories:
                self.combo_category.addItem("(No active categories)", None)
                self.combo_category.setEnabled(False)
                self.btn_apply_category.setEnabled(False)
            else:
                self.combo_category.setEnabled(True)
                self.btn_apply_category.setEnabled(True)

        except Exception as exc:
            logger.exception("Failed to load categories")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load categories:\n{exc}")
            self.categories = []
            self.combo_category.clear()
            self.combo_category.addItem("(Error loading categories)", None)
            self.combo_category.setEnabled(False)
            self.btn_apply_category.setEnabled(False)

    def load_transactions(self):
        """
        Load unverified transactions from the database and populate the model.
        """
        try:
            logger.info("Loading unverified transactions for review")
            session = self.Session()

            try:
                query = (
                    session.query(Transactions)
                    .options(
                        joinedload(Transactions.accounts),
                        joinedload(Transactions.category),
                    )
                    .order_by(Transactions.Date)
                )

                only_unverified = (
                    getattr(self, "chk_only_unverified", None) is None or self.chk_only_unverified.isChecked()
                )
                if only_unverified:
                    query = query.filter(Transactions.Verified == 0)

                only_archived = (
                    getattr(self, "show_archived_only_checkbox", None) is not None
                    and self.show_archived_only_checkbox.isChecked()
                )
                if only_archived:
                    query = query.join(Transactions.category).filter(Categories.Active == 0)

                rows: List[Transactions] = query.all()
            finally:
                session.close()

            records: List[TransactionRecord] = []
            for tx in rows:
                if tx.category is not None and tx.CategoryID is not None:
                    category_id = tx.CategoryID
                    category_name = tx.category.Name
                else:
                    category_id = None
                    category_name = ""

                is_active = True
                if tx.category is not None and tx.category.Active is not None:
                    is_active = bool(tx.category.Active)

                records.append(
                    TransactionRecord(
                        transaction_id=tx.TransactionID,
                        date=tx.Date,
                        account_name=tx.accounts.AccountName,
                        description=tx.Description or "",
                        amount=float(tx.Amount) if tx.Amount is not None else 0.0,
                        category_id=category_id,
                        category_name=category_name,
                        verified=bool(tx.Verified),
                        category_active=is_active,
                        confidence=(float(tx.ConfidenceScore) if tx.ConfidenceScore is not None else None),
                        cluster=None,
                    )
                )

            self.model.set_records(records)
            self._resize_columns()
            if only_unverified:
                self.status_label.setText(f"Loaded {len(records)} unverified transactions.")
            else:
                self.status_label.setText(f"Loaded {len(records)} transactions (verified + unverified).")
        except Exception as exc:
            logger.exception("Failed to load transactions")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load transactions:\n{exc}")

    def _resize_columns(self):
        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(False)
        for col in range(self.model.columnCount()):
            if col in (TransactionTableModel.COL_DESC,):
                header.setSectionResizeMode(col, QtWidgets.QHeaderView.Stretch)
            else:
                header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)

    def _get_selected_records(self) -> List[TransactionRecord]:
        selection_model = self.table_view.selectionModel()
        if not selection_model:
            return []

        records: List[TransactionRecord] = []
        for index in selection_model.selectedRows():
            source_index = self.proxy.mapToSource(index)
            records.append(self.model.record_at(source_index.row()))
        return records

    def mark_selected_verified(self):
        records = self._get_selected_records()
        if not records:
            QtWidgets.QMessageBox.information(self, "No Selection", "No rows selected.")
            return

        skipped = 0
        for rec in records:
            if not rec.category_name:
                skipped += 1
                continue

            rec.verified = True
            row = self.model._records.index(rec)
            idx = self.model.index(row, TransactionTableModel.COL_VERIFIED)
            self.model.dataChanged.emit(idx, idx, [QtCore.Qt.CheckStateRole])

        msg = f"Marked {len(records)-skipped} transactions as verified (not yet saved)."
        if skipped > 0:
            msg += f" Skipped {skipped} uncategorized lines."
        self.status_label.setText(msg)

    def clear_selected_verified(self):
        records = self._get_selected_records()
        if not records:
            QtWidgets.QMessageBox.information(self, "No Selection", "No rows selected.")
            return

        for rec in records:
            rec.verified = False

        for rec in records:
            row = self.model._records.index(rec)
            idx = self.model.index(row, TransactionTableModel.COL_VERIFIED)
            self.model.dataChanged.emit(idx, idx, [QtCore.Qt.CheckStateRole])

        self.status_label.setText(f"Cleared Verified on {len(records)} transactions (not yet saved).")

    def apply_category_to_selected(self):
        """
        Apply the currently selected category from the combo box to all selected rows,
        and mark those rows as verified.
        """
        if not self.categories or self.combo_category.currentData() is None:
            QtWidgets.QMessageBox.warning(
                self,
                "No Categories",
                "No active categories are available to apply.",
            )
            return

        progress = QtWidgets.QProgressDialog(
            "Applying category to selected transactions...",
            None,
            0,
            0,
            self,
        )
        progress.setWindowTitle("Please Wait")
        progress.setWindowModality(QtCore.Qt.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(2000)
        progress.show()
        QtWidgets.QApplication.processEvents()

        records = self._get_selected_records()
        if not records:
            QtWidgets.QMessageBox.information(self, "No Selection", "No rows selected.")
            return

        progress.setMaximum(len(records))

        cat_id = self.combo_category.currentData()
        cat_name = self.combo_category.currentText()

        for i, rec in enumerate(records):
            progress.setValue(i)

            # Update memory
            rec.category_id = cat_id
            rec.category_name = cat_name
            rec.verified = True

            # Update GUI
            row = self.model._records.index(rec)
            idx_cat = self.model.index(row, TransactionTableModel.COL_CATEGORY)
            self.model.dataChanged.emit(idx_cat, idx_cat, [QtCore.Qt.DisplayRole])
            idx_ver = self.model.index(row, TransactionTableModel.COL_VERIFIED)
            self.model.dataChanged.emit(idx_ver, idx_ver, [QtCore.Qt.CheckStateRole])

        progress.close()

        self.status_label.setText(
            f"Applied category '{cat_name}' and marked {len(records)} transactions as verified " "(not yet saved)."
        )

    def save_changes(self):
        """
        Persist CategoryID + Verified changes to the database for all modified records.
        """
        modified = [
            rec
            for rec in self.model._records
            if (rec.category_id != rec.orig_category_id) or (rec.verified != rec.orig_verified)
        ]

        if not modified:
            QtWidgets.QMessageBox.information(self, "No Changes", "There are no changes to save.")
            return

        # Ensure no records have category_id None if they changed category
        invalid = [rec for rec in modified if rec.category_id is None]
        if invalid:
            QtWidgets.QMessageBox.warning(
                self,
                "Missing Category",
                "Some modified transactions have no category selected. " "Please apply a valid category before saving.",
            )
            return

        try:
            session = self.Session()
            try:
                logger.info(f"Saving changes for {len(modified)} transactions")

                update_cols = ["CategoryID", "Verified", "ConfidenceScore"]
                update_list = []
                for rec in modified:
                    # If category or verified changed, clear confidence
                    if rec.category_id != rec.orig_category_id or rec.verified != rec.orig_verified:
                        confidence = None
                    else:
                        confidence = rec.confidence

                    update_list.append((rec.category_id, int(rec.verified), confidence))

                where_cols = ["TransactionID"]
                where_list = [(rec.transaction_id,) for rec in modified]

                update_db_where(
                    session,
                    Transactions,
                    update_cols,
                    update_list,
                    where_cols,
                    where_list,
                )
                # update_db_where commits internally

            finally:
                session.close()

            # Reload unverified transactions (these will drop out if Verified=1)
            self.load_transactions()
            self.status_label.setText(f"Saved changes for {len(modified)} transactions.")

            # Notify main window that db changed
            self.data_changed.emit()
        except Exception as exc:
            logger.exception("Failed to save changes")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save changes:\n{exc}")

    def auto_categorize_unverified(self):
        if settings.model_path is None:
            QtWidgets.QMessageBox.warning(
                self,
                "No Model",
                "No model path configured. Train a model first.",
            )
            return

        if not settings.model_path.exists():
            QtWidgets.QMessageBox.warning(
                self,
                "Model Not Found",
                f"Model file not found at:\n{settings.model_path}",
            )
            return

        progress = QtWidgets.QProgressDialog(
            "Auto-categorizing unverified transactions...",
            None,
            0,
            0,
            self,
        )
        progress.setWindowTitle("Please Wait")
        progress.setWindowModality(QtCore.Qt.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QtWidgets.QApplication.processEvents()

        try:
            logger.info("Running auto-categorization on unverified transactions")
            session = self.Session()
            try:
                # Update db with predicted categories
                categorize_transactions(
                    session=session,
                    model_path=settings.model_path,
                    unverified=True,
                    uncategorized=False,
                )
            finally:
                session.close()

            # Load predicted categories
            self.load_transactions()
            self.status_label.setText("Auto-categorization complete.")
        except Exception as exc:
            logger.exception("Auto-categorization failed")
            QtWidgets.QMessageBox.critical(self, "Error", f"Auto-categorization failed:\n{exc}")
        finally:
            progress.close()

    def _build_clustering_kwargs(self):
        """
        Build kwargs dict for recurring_transactions based on the UI controls.
        """
        kwargs = {
            "eps": self.spin_eps.value(),
            "min_samples": self.spin_min_samples.value(),
            "include_amount": self.chk_include_amount.isChecked(),
        }

        if self.chk_use_min_size.isChecked():
            kwargs["min_size"] = self.spin_min_size.value()
        if self.chk_use_min_interval.isChecked():
            kwargs["min_interval"] = self.spin_min_interval.value()
        if self.chk_use_max_interval.isChecked():
            kwargs["max_interval"] = self.spin_max_interval.value()
        if self.chk_use_max_variance.isChecked():
            kwargs["max_variance"] = self.spin_max_variance.value()

        text = self.edit_extra_stopwords.text().strip()
        if text:
            extra = [w.strip() for w in text.split(",") if w.strip()]
            if extra:
                kwargs["extra_stopwords"] = extra

        return kwargs

    def cluster_recurring_transactions(self):
        """
        Use recurring_transactions(...) to identify recurring clusters and
        annotate the current rows with Cluster IDs.
        """
        if not self.model._records:
            QtWidgets.QMessageBox.information(self, "No Data", "No transactions loaded.")
            return

        try:
            logger.info("Running recurring transaction clustering")

            df = pd.DataFrame(
                [
                    {
                        "TransactionID": rec.transaction_id,
                        "Date": rec.date,
                        "Amount": rec.amount,
                        "Description": rec.description,
                    }
                    for rec in self.model._records
                ]
            )

            kwargs = self._build_clustering_kwargs()
            clustered = recurring_transactions(df, **kwargs)

            # Map TransactionID -> Cluster
            cluster_map = {int(row["TransactionID"]): int(row["Cluster"]) for _, row in clustered.iterrows()}

            # Update records in place
            for rec in self.model._records:
                rec.cluster = cluster_map.get(rec.transaction_id, None)

            # Notify view: Cluster column changed
            row_count = self.model.rowCount()
            if row_count > 0:
                top_left = self.model.index(0, TransactionTableModel.COL_CLUSTER)
                bottom_right = self.model.index(row_count - 1, TransactionTableModel.COL_CLUSTER)
                self.model.dataChanged.emit(top_left, bottom_right, [QtCore.Qt.DisplayRole])

            self._resize_columns()

            num_clusters = len({c for c in cluster_map.values() if c != -1})
            num_rows = len(cluster_map)
            self.status_label.setText(f"Found {num_clusters} recurring clusters affecting {num_rows} transactions.")
        except Exception as exc:
            logger.exception("Clustering recurring transactions failed")
            QtWidgets.QMessageBox.critical(self, "Error", f"Clustering failed:\n{exc}")

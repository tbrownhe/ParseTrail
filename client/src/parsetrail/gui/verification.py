from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
from loguru import logger
from PySide6 import QtCore, QtWidgets
from sqlalchemy.orm import sessionmaker

from parsetrail.core.cluster import recurring_transactions
from parsetrail.core.review import (
    InvalidReviewChangesError,
    TransactionRecord,
    TransactionReviewError,
    TransactionReviewService,
)
from parsetrail.core.settings import settings
from parsetrail.gui.review_models import TransactionFilterProxyModel, TransactionTableModel


class TransactionReviewWindow(QtWidgets.QMainWindow):
    """
    Main UI for reviewing, categorizing, and verifying transactions.

    - Uses normalized Categories table via Transactions.CategoryID.
    - Assigns existing categories and can restore categories required by a model.
    - Edits are kept in-memory until the user clicks "Save Changes".
    """

    # Signal to main window when db is updated
    data_changed = QtCore.Signal()

    def __init__(
        self,
        Session: sessionmaker,
        parent=None,
    ):
        super().__init__(parent)
        self.review_service = TransactionReviewService(Session)

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
            self.categories = self.review_service.active_categories()

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

        except TransactionReviewError:
            logger.exception("Failed to load categories")
            QtWidgets.QMessageBox.critical(self, "Error", "Failed to load categories. See log for details.")
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
            only_unverified = getattr(self, "chk_only_unverified", None) is None or self.chk_only_unverified.isChecked()
            only_archived = (
                getattr(self, "show_archived_only_checkbox", None) is not None
                and self.show_archived_only_checkbox.isChecked()
            )
            records = self.review_service.list_transactions(
                only_unverified=only_unverified,
                only_archived_categories=only_archived,
            )

            self.model.set_records(records)
            self._resize_columns()
            if only_unverified:
                self.status_label.setText(f"Loaded {len(records)} unverified transactions.")
            else:
                self.status_label.setText(f"Loaded {len(records)} transactions (verified + unverified).")
        except TransactionReviewError:
            logger.exception("Failed to load transactions")
            QtWidgets.QMessageBox.critical(self, "Error", "Failed to load transactions. See log for details.")

    def _resize_columns(self):
        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(False)
        for col in range(self.model.columnCount()):
            if col in (TransactionTableModel.COL_DESC,):
                header.setSectionResizeMode(col, QtWidgets.QHeaderView.Stretch)
            else:
                header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)

    def _get_selected_records(self) -> list[TransactionRecord]:
        selection_model = self.table_view.selectionModel()
        if not selection_model:
            return []

        records: list[TransactionRecord] = []
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

        msg = f"Marked {len(records) - skipped} transactions as verified (not yet saved)."
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
            f"Applied category '{cat_name}' and marked {len(records)} transactions as verified (not yet saved)."
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

        try:
            logger.info("Saving changes for {} transactions", len(modified))
            saved_count = self.review_service.save_changes(modified)

            # Reload unverified transactions (these will drop out if Verified=1)
            self.load_transactions()
            self.status_label.setText(f"Saved changes for {saved_count} transactions.")

            # Notify main window that db changed
            self.data_changed.emit()
        except InvalidReviewChangesError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Changes", str(exc))
        except TransactionReviewError:
            logger.exception("Failed to save changes")
            QtWidgets.QMessageBox.critical(self, "Error", "Failed to save changes. See log for details.")

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
            result = self.review_service.auto_categorize(
                settings.model_path,
                missing_category_decision=self._prompt_add_missing_categories,
            )
            if not result.completed:
                self.status_label.setText("Auto-categorization skipped (missing categories).")
                return
            if result.added_categories:
                QtWidgets.QMessageBox.information(
                    self,
                    "Categories Added",
                    (
                        "Missing categories were added with Type set to 'Expense'.\n\n"
                        "Please update the type as needed in the Category Manager."
                    ),
                )

            # Load predicted categories
            self._load_categories()
            self.load_transactions()
            self.status_label.setText("Auto-categorization complete.")
        except TransactionReviewError:
            logger.exception("Auto-categorization failed")
            QtWidgets.QMessageBox.critical(self, "Error", "Auto-categorization failed. See log for details.")
        finally:
            progress.close()

    def _prompt_add_missing_categories(self, missing: Sequence[str]) -> bool:
        missing_text = ", ".join(missing)
        reply = QtWidgets.QMessageBox.question(
            self,
            "Add Missing Categories?",
            (
                "The trained model expects categories that are missing from this database:\n\n"
                f"{missing_text}\n\n"
                "Would you like to add these categories now and continue auto-categorizing?"
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        return reply == QtWidgets.QMessageBox.Yes

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
        except Exception:
            logger.exception("Clustering recurring transactions failed")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                "Clustering failed. See the application log for details.",
            )

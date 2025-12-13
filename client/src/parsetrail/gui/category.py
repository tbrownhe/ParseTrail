from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional, List, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
from parsetrail.core.orm import Categories, Transactions


class TypeComboDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate to provide a dropdown for the Type column."""

    def __init__(self, type_choices: list[str], parent=None) -> None:
        super().__init__(parent)
        self.type_choices = type_choices

    def createEditor(self, parent, option, index):
        combo = QtWidgets.QComboBox(parent)
        combo.addItems(self.type_choices)
        return combo

    def setEditorData(self, editor, index):
        current_value = index.data(QtCore.Qt.EditRole) or ""
        idx = editor.findText(current_value)
        editor.setCurrentIndex(idx if idx >= 0 else 0)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), QtCore.Qt.EditRole)


class RenameCategoryDialog(QtWidgets.QDialog):
    """
    Simple wizard to rename/migrate a category:
      - Select existing category A
      - Provide new name B
      - Optionally unverify affected transactions

    Semantics:
      - Create new category B (Active=1, Type copied from A)
      - UPDATE Transactions SET CategoryID=B WHERE CategoryID=A
        - Always sets ConfidenceScore=NULL
        - Optionally sets Verified=0
      - Set A.Active=0
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget], categories: List[Tuple[int, str]]):
        super().__init__(parent)
        self.setWindowTitle("Rename / Migrate Category")
        self.setModal(True)

        self.categories = categories  # list of (id, name)

        self.combo_source = QtWidgets.QComboBox()
        for cat_id, name in self.categories:
            self.combo_source.addItem(name, cat_id)

        self.edit_new_name = QtWidgets.QLineEdit()
        self.edit_new_name.setPlaceholderText("Enter new category name")

        self.chk_unverify = QtWidgets.QCheckBox(
            "Unverify affected transactions (recommended for major meaning changes)"
        )
        self.chk_unverify.setChecked(False)

        form = QtWidgets.QFormLayout()
        form.addRow("Category to rename:", self.combo_source)
        form.addRow("New name:", self.edit_new_name)
        form.addRow("", self.chk_unverify)

        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(btn_box)
        self.setLayout(layout)

    def get_values(self) -> Tuple[int, str, bool]:
        cat_id = self.combo_source.currentData()
        new_name = self.edit_new_name.text().strip()
        unverify = self.chk_unverify.isChecked()
        return cat_id, new_name, unverify

    def accept(self) -> None:
        _, new_name, _ = self.get_values()
        if not new_name:
            QtWidgets.QMessageBox.warning(self, "Missing Name", "Please enter a new category name.")
            return
        super().accept()


class MergeCategoryDialog(QtWidgets.QDialog):
    """
    Wizard to merge one category into another:
      - Source category D (to archive)
      - Target category C (to keep)
      - Optionally unverify affected transactions

    Semantics:
      - UPDATE Transactions SET CategoryID=C WHERE CategoryID=D
        - Always sets ConfidenceScore=NULL
        - Optionally sets Verified=0
      - Set D.Active=0
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget], categories: List[Tuple[int, str]]):
        super().__init__(parent)
        self.setWindowTitle("Merge Categories")
        self.setModal(True)

        self.categories = categories  # list of (id, name)

        self.combo_source = QtWidgets.QComboBox()
        self.combo_target = QtWidgets.QComboBox()
        for cat_id, name in self.categories:
            self.combo_source.addItem(name, cat_id)
            self.combo_target.addItem(name, cat_id)

        self.chk_unverify = QtWidgets.QCheckBox(
            "Unverify affected transactions (recommended for major meaning changes)"
        )
        self.chk_unverify.setChecked(False)

        form = QtWidgets.QFormLayout()
        form.addRow("Merge from:", self.combo_source)
        form.addRow("Into:", self.combo_target)
        form.addRow("", self.chk_unverify)

        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(btn_box)
        self.setLayout(layout)

    def _on_accept(self) -> None:
        src_id = self.combo_source.currentData()
        tgt_id = self.combo_target.currentData()
        if src_id == tgt_id:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Selection",
                "Source and target categories must be different.",
            )
            return
        super().accept()

    def get_values(self) -> Tuple[int, int, bool]:
        src_id = self.combo_source.currentData()
        tgt_id = self.combo_target.currentData()
        unverify = self.chk_unverify.isChecked()
        return src_id, tgt_id, unverify


class CategoryManagerDialog(QtWidgets.QDialog):
    """
    Modal dialog for managing Categories.

    Features:
      - Show ID, Name, Type, Active
      - Add category
      - Rename/migrate (A -> B, archive A)
      - Merge categories (D -> C, archive D)
      - Toggle Active / edit Type inline (immediate DB updates)
      - Show/hide inactive categories
    """

    COL_ID = 0
    COL_NAME = 1
    COL_TYPE = 2
    COL_BUDGET = 3
    COL_ACTIVE = 4
    COL_COUNT = 5

    HEADERS = ["ID", "Name", "Type", "Budget/Mo", "Active", "Transactions"]
    TYPE_CHOICES = ["Expense", "Income", "Transfer"]

    def __init__(self, Session: sessionmaker, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Manage Categories")
        self.setModal(True)
        self.resize(600, 800)

        self.Session = Session

        self._creating_model = False  # guard to suppress itemChanged during setup

        self._create_widgets()
        self._create_layout()
        self._connect_signals()

        self.load_categories()

    def _create_widgets(self) -> None:
        self.table = QtWidgets.QTableView()
        self.model = QtGui.QStandardItemModel(0, len(self.HEADERS), self)
        self.model.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(self.COL_TYPE, TypeComboDelegate(self.TYPE_CHOICES, self.table))
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.SelectedClicked
        )

        # Controls
        self.btn_add = QtWidgets.QPushButton("Add Category")
        self.btn_rename = QtWidgets.QPushButton("Rename / Migrate…")
        self.btn_merge = QtWidgets.QPushButton("Merge Categories…")
        for btn in (self.btn_add, self.btn_rename, self.btn_merge):
            btn.setAutoDefault(False)
            btn.setDefault(False)

        self.chk_show_inactive = QtWidgets.QCheckBox("Show inactive categories")
        self.chk_show_inactive.setChecked(False)

        self.btn_close = QtWidgets.QPushButton("Close")
        self.btn_close.setDefault(True)
        self.btn_close.setAutoDefault(True)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

    def _create_layout(self) -> None:
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_rename)
        btn_row.addWidget(self.btn_merge)
        btn_row.addStretch()
        btn_row.addWidget(self.chk_show_inactive)

        bottom_row = QtWidgets.QHBoxLayout()
        bottom_row.addWidget(self.status_label)
        bottom_row.addStretch()
        bottom_row.addWidget(self.btn_close)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(btn_row)
        layout.addWidget(self.table)
        layout.addLayout(bottom_row)

        self.setLayout(layout)

    def _connect_signals(self) -> None:
        self.btn_close.clicked.connect(self.accept)
        self.btn_add.clicked.connect(self.add_category)
        self.btn_rename.clicked.connect(self.rename_category)
        self.btn_merge.clicked.connect(self.merge_categories)
        self.chk_show_inactive.toggled.connect(self.load_categories)
        self.model.itemChanged.connect(self._on_item_changed)

    def load_categories(self) -> None:
        """
        Load categories from the database into the table model.
        Respects the 'show inactive' checkbox.
        """
        self._creating_model = True
        self.model.setRowCount(0)

        with self.Session() as session:
            try:
                counts = dict(
                    session.query(
                        Transactions.CategoryID,
                        func.count(Transactions.TransactionID),
                    )
                    .group_by(Transactions.CategoryID)
                    .all()
                )

                query = session.query(Categories)
                if not self.chk_show_inactive.isChecked():
                    query = query.filter(Categories.Active == 1)
                categories = query.order_by(Categories.Name.asc()).all()

                query = session.query(Categories)
                if not self.chk_show_inactive.isChecked():
                    query = query.filter(Categories.Active == 1)
                categories = query.order_by(Categories.Name.asc()).all()
            finally:
                pass

        for cat in categories:
            row = self.model.rowCount()
            self.model.insertRow(row)

            # ID (read-only)
            item_id = QtGui.QStandardItem(str(cat.CategoryID))
            item_id.setEditable(False)

            # Name (read-only; renames go through wizard)
            item_name = QtGui.QStandardItem(cat.Name or "")
            item_name.setEditable(False)

            # Type (editable)
            item_type = QtGui.QStandardItem(cat.Type or "")
            item_type.setEditable(True)

            # Budget (editable numeric)
            budget_text = "" if cat.Budget is None else f"{cat.Budget:.2f}"
            item_budget = QtGui.QStandardItem(budget_text)
            item_budget.setEditable(True)

            # Active (checkable)
            item_active = QtGui.QStandardItem()
            item_active.setCheckable(True)
            item_active.setCheckState(QtCore.Qt.Checked if cat.Active else QtCore.Qt.Unchecked)
            item_active.setEditable(False)  # toggled via checkbox, not text edit

            # Show transaction count
            tx_count = counts.get(cat.CategoryID, 0)
            item_count = QtGui.QStandardItem(str(tx_count))
            item_count.setEditable(False)

            self.model.setItem(row, self.COL_ID, item_id)
            self.model.setItem(row, self.COL_NAME, item_name)
            self.model.setItem(row, self.COL_TYPE, item_type)
            self.model.setItem(row, self.COL_BUDGET, item_budget)
            self.model.setItem(row, self.COL_ACTIVE, item_active)
            self.model.setItem(row, self.COL_COUNT, item_count)

        self._creating_model = False
        self.status_label.setText(f"Loaded {self.model.rowCount()} categories.")

    def _on_item_changed(self, item: QtGui.QStandardItem) -> None:
        """
        Handle inline edits: Type, Budget, and Active flag.
        Name is not editable inline (use rename/migrate wizard).
        """
        if self._creating_model:
            return

        row = item.row()
        col = item.column()

        # Get ID
        id_item = self.model.item(row, self.COL_ID)
        if id_item is None:
            return
        try:
            cat_id = int(id_item.text())
        except ValueError:
            return

        with self.Session() as session:
            try:
                category = session.query(Categories).get(cat_id)
                if category is None:
                    return

                if col == self.COL_TYPE:
                    new_type = item.text().strip()
                    if new_type not in self.TYPE_CHOICES:
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Invalid Type",
                            f"Type must be one of: {', '.join(self.TYPE_CHOICES)}.",
                        )
                        self.load_categories()
                        return
                    category.Type = new_type
                    session.commit()
                    self.status_label.setText(f"Updated Type for '{category.Name}'.")
                elif col == self.COL_BUDGET:
                    raw_value = item.text().strip()
                    if raw_value == "":
                        category.Budget = None
                        session.commit()
                        self.status_label.setText(f"Cleared budget for '{category.Name}'.")
                        return
                    try:
                        budget_value = Decimal(raw_value)
                    except (InvalidOperation, ValueError):
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Invalid Budget",
                            "Please enter a valid number for the budget (e.g. 1250.00).",
                        )
                        self.load_categories()
                        return
                    category.Budget = budget_value
                    session.commit()
                    self.status_label.setText(f"Updated budget for '{category.Name}' to {budget_value:.2f}.")
                elif col == self.COL_ACTIVE:
                    # Checkable item
                    is_active = item.checkState() == QtCore.Qt.Checked
                    category.Active = 1 if is_active else 0
                    session.commit()
                    self.status_label.setText(
                        f"{'Activated' if is_active else 'Deactivated'} category '{category.Name}'."
                    )
            except Exception:
                session.rollback()
                logger.exception("Failed to update category inline")
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    "Failed to update category. See log for details.",
                )
                # Reload to restore consistency
                self.load_categories()

    def add_category(self) -> None:
        """
        Prompt for a new category name and type, then insert into Categories (Active=1).
        """
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Add Category",
            "Category name:",
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Missing Name", "Category name cannot be empty.")
            return

        type_text, ok_type = QtWidgets.QInputDialog.getItem(
            self,
            "Add Category",
            "Category type:",
            self.TYPE_CHOICES,
            0,
            False,
        )
        if not ok_type:
            return
        type_text = type_text.strip() or self.TYPE_CHOICES[0]

        with self.Session() as session:
            try:
                new_cat = Categories(Name=name, Type=type_text, Active=1)
                session.add(new_cat)
                session.commit()
                self.status_label.setText(f"Added category '{name}'.")
                self.load_categories()
            except IntegrityError:
                session.rollback()
                QtWidgets.QMessageBox.warning(
                    self,
                    "Duplicate Category",
                    f"A category named '{name}' already exists.",
                )
            except Exception:
                session.rollback()
                logger.exception("Failed to add category")
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    "Failed to add category. See log for details.",
                )

    def _get_all_categories(self, include_inactive: bool = True) -> List[Tuple[int, str]]:
        """
        Helper to fetch all categories as (id, name) tuples.
        """
        with self.Session() as session:
            try:
                query = session.query(Categories)
                if not include_inactive:
                    query = query.filter(Categories.Active == 1)
                cats = query.order_by(Categories.Name.asc()).all()
                return [(c.CategoryID, c.Name) for c in cats]
            finally:
                session.close()

    def rename_category(self) -> None:
        """
        Open the rename/migrate wizard.

        Semantics:
          - Pick category A
          - Enter new name B
          - Create B (Active=1)
          - Move all Transactions from A -> B
          - Clear ConfidenceScore
          - Optionally unverify
          - Archive A (Active=0)
        """
        categories = self._get_all_categories(include_inactive=False)
        if not categories:
            QtWidgets.QMessageBox.information(
                self,
                "No Categories",
                "There are no active categories to rename.",
            )
            return

        dlg = RenameCategoryDialog(self, categories)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return

        src_id, new_name, unverify = dlg.get_values()

        # Confirm impact
        with self.Session() as session:
            try:
                src_cat = session.query(Categories).get(src_id)
                if src_cat is None:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Category Not Found",
                        "The selected category no longer exists.",
                    )
                    return

                count_total = session.query(Transactions).filter(Transactions.CategoryID == src_cat.CategoryID).count()
                count_verified = (
                    session.query(Transactions)
                    .filter(
                        Transactions.CategoryID == src_cat.CategoryID,
                        Transactions.Verified == 1,
                    )
                    .count()
                )

                if count_total == 0:
                    text = (
                        f"Category '{src_cat.Name}' has no transactions. "
                        f"A new category '{new_name}' will be created and '{src_cat.Name}' "
                        f"will be archived."
                    )
                else:
                    text = (
                        f"Category '{src_cat.Name}' is used by {count_total} transactions "
                        f"({count_verified} verified).\n\n"
                        f"Rename/migrate to '{new_name}'?\n\n"
                        f"This will:\n"
                        f"  - Create '{new_name}' as a new active category\n"
                        f"  - Move all transactions from '{src_cat.Name}' to '{new_name}'\n"
                        f"  - Archive '{src_cat.Name}' (mark inactive)\n"
                        f"  - Clear ConfidenceScore on affected transactions\n"
                        f"  - Make any models trained on '{src_cat.Name}' stale (recommend retraining model)\n"
                    )
                    if unverify:
                        text += "  - Unverify affected transactions (Verified=0)\n"

                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Confirm Rename / Migrate",
                    text,
                    QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
                    QtWidgets.QMessageBox.Cancel,
                )
                if reply != QtWidgets.QMessageBox.Ok:
                    return

                new_cat = Categories(
                    Name=new_name,
                    Type=src_cat.Type,
                    Active=1,
                )
                session.add(new_cat)
                session.flush()  # obtain new_cat.CategoryID

                # Move transactions A -> B
                update_values = {
                    Transactions.CategoryID: new_cat.CategoryID,
                    Transactions.ConfidenceScore: None,
                }
                if unverify:
                    update_values[Transactions.Verified] = 0

                session.query(Transactions).filter(Transactions.CategoryID == src_cat.CategoryID).update(
                    update_values, synchronize_session=False
                )

                # Archive A
                src_cat.Active = 0

                session.commit()
                self.status_label.setText(
                    f"Renamed/migrated '{src_cat.Name}' to '{new_name}'. " f"Affected transactions: {count_total}."
                )
                self.load_categories()

            except IntegrityError:
                session.rollback()
                QtWidgets.QMessageBox.warning(
                    self,
                    "Duplicate Category",
                    f"A category named '{new_name}' already exists.",
                )
            except Exception:
                session.rollback()
                logger.exception("Failed to rename/migrate category")
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    "Failed to rename/migrate category. See log for details.",
                )

    def merge_categories(self) -> None:
        """
        Open the merge wizard.

        Semantics:
          - Source A, Target B
          - Move all Transactions from A -> B
          - Clear ConfidenceScore
          - Optionally unverify
          - Archive A (Active=0)
        """
        categories = self._get_all_categories(include_inactive=True)
        if len(categories) < 2:
            QtWidgets.QMessageBox.information(
                self,
                "Not Enough Categories",
                "You need at least two categories to perform a merge.",
            )
            return

        dlg = MergeCategoryDialog(self, categories)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return

        src_id, tgt_id, unverify = dlg.get_values()

        with self.Session() as session:
            try:
                src_cat = session.query(Categories).get(src_id)
                tgt_cat = session.query(Categories).get(tgt_id)
                if src_cat is None or tgt_cat is None:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Category Not Found",
                        "The selected categories no longer exist.",
                    )
                    return

                count_total = session.query(Transactions).filter(Transactions.CategoryID == src_cat.CategoryID).count()
                count_verified = (
                    session.query(Transactions)
                    .filter(
                        Transactions.CategoryID == src_cat.CategoryID,
                        Transactions.Verified == 1,
                    )
                    .count()
                )

                if count_total == 0:
                    text = (
                        f"Category '{src_cat.Name}' has no transactions. "
                        f"It will simply be archived and '{tgt_cat.Name}' will be kept."
                    )
                else:
                    text = (
                        f"Category '{src_cat.Name}' is used by {count_total} transactions "
                        f"({count_verified} verified).\n\n"
                        f"Merge into '{tgt_cat.Name}'?\n\n"
                        f"This will:\n"
                        f"  - Move all transactions from '{src_cat.Name}' to '{tgt_cat.Name}'\n"
                        f"  - Archive '{src_cat.Name}' (mark inactive)\n"
                        f"  - Clear ConfidenceScore on affected transactions\n"
                        f"  - Make any models trained on '{src_cat.Name}' stale (recommend retraining model)\n"
                    )
                    if unverify:
                        text += "  - Unverify affected transactions (Verified=0)\n"

                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Confirm Merge",
                    text,
                    QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
                    QtWidgets.QMessageBox.Cancel,
                )
                if reply != QtWidgets.QMessageBox.Ok:
                    return

                # Move transactions A -> B
                update_values = {
                    Transactions.CategoryID: tgt_cat.CategoryID,
                    Transactions.ConfidenceScore: None,
                }
                if unverify:
                    update_values[Transactions.Verified] = 0

                session.query(Transactions).filter(Transactions.CategoryID == src_cat.CategoryID).update(
                    update_values, synchronize_session=False
                )

                # Archive A
                src_cat.Active = 0

                # Ensure B is active
                tgt_cat.Active = 1

                session.commit()
                self.status_label.setText(
                    f"Merged '{src_cat.Name}' into '{tgt_cat.Name}'. " f"Affected transactions: {count_total}."
                )
                self.load_categories()

            except Exception:
                session.rollback()
                logger.exception("Failed to merge categories")
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    "Failed to merge categories. See log for details.",
                )

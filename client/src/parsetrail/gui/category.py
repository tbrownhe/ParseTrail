from __future__ import annotations

from loguru import logger
from PySide6 import QtCore, QtGui, QtWidgets
from sqlalchemy.orm import sessionmaker

from parsetrail.core.categories import (
    CATEGORY_TYPES,
    CategoryNotFoundError,
    CategoryService,
    CategoryServiceError,
    DuplicateCategoryError,
    InvalidCategoryError,
)


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

    def __init__(self, parent: QtWidgets.QWidget | None, categories: list[tuple[int, str]]):
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

    def get_values(self) -> tuple[int, str, bool]:
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

    def __init__(self, parent: QtWidgets.QWidget | None, categories: list[tuple[int, str]]):
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

    def get_values(self) -> tuple[int, int, bool]:
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
    TYPE_CHOICES = list(CATEGORY_TYPES)

    def __init__(self, Session: sessionmaker, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Manage Categories")
        self.setModal(True)
        self.resize(600, 800)

        self.category_service = CategoryService(Session)

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

        try:
            categories = self.category_service.list_categories(include_inactive=self.chk_show_inactive.isChecked())
        except CategoryServiceError:
            self._creating_model = False
            logger.exception("Failed to load categories")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                "Failed to load categories. See log for details.",
            )
            return

        for cat in categories:
            row = self.model.rowCount()
            self.model.insertRow(row)

            # ID (read-only)
            item_id = QtGui.QStandardItem(str(cat.category_id))
            item_id.setEditable(False)

            # Name (read-only; renames go through wizard)
            item_name = QtGui.QStandardItem(cat.name or "")
            item_name.setEditable(False)

            # Type (editable)
            item_type = QtGui.QStandardItem(cat.category_type or "")
            item_type.setEditable(True)

            # Budget (editable numeric)
            budget_text = "" if cat.budget is None else f"{cat.budget:.2f}"
            item_budget = QtGui.QStandardItem(budget_text)
            item_budget.setEditable(True)

            # Active (checkable)
            item_active = QtGui.QStandardItem()
            item_active.setCheckable(True)
            item_active.setCheckState(QtCore.Qt.Checked if cat.active else QtCore.Qt.Unchecked)
            item_active.setEditable(False)  # toggled via checkbox, not text edit

            # Show transaction count
            item_count = QtGui.QStandardItem(str(cat.transaction_count))
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

        try:
            if col == self.COL_TYPE:
                category = self.category_service.set_type(cat_id, item.text())
                self.status_label.setText(f"Updated Type for '{category.name}'.")
            elif col == self.COL_BUDGET:
                category = self.category_service.set_budget(cat_id, item.text())
                if category.budget is None:
                    self.status_label.setText(f"Cleared budget for '{category.name}'.")
                else:
                    self.status_label.setText(f"Updated budget for '{category.name}' to {category.budget:.2f}.")
            elif col == self.COL_ACTIVE:
                is_active = item.checkState() == QtCore.Qt.Checked
                category = self.category_service.set_active(cat_id, is_active)
                self.status_label.setText(f"{'Activated' if is_active else 'Deactivated'} category '{category.name}'.")
        except InvalidCategoryError as exc:
            title = "Invalid Type" if col == self.COL_TYPE else "Invalid Budget"
            QtWidgets.QMessageBox.warning(self, title, str(exc))
            self.load_categories()
        except CategoryNotFoundError:
            self.load_categories()
        except CategoryServiceError:
            logger.exception("Failed to update category inline")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                "Failed to update category. See log for details.",
            )
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

        try:
            category = self.category_service.add(name, type_text)
            self.status_label.setText(f"Added category '{category.name}'.")
            self.load_categories()
        except DuplicateCategoryError as exc:
            QtWidgets.QMessageBox.warning(self, "Duplicate Category", str(exc))
        except InvalidCategoryError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Category", str(exc))
        except CategoryServiceError:
            logger.exception("Failed to add category")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                "Failed to add category. See log for details.",
            )

    def _get_all_categories(self, include_inactive: bool = True) -> list[tuple[int, str]]:
        """
        Helper to fetch all categories as (id, name) tuples.
        """
        return self.category_service.category_pairs(include_inactive=include_inactive)

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
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        src_id, new_name, unverify = dlg.get_values()

        try:
            impact = self.category_service.describe(src_id)
        except CategoryNotFoundError:
            QtWidgets.QMessageBox.warning(
                self,
                "Category Not Found",
                "The selected category no longer exists.",
            )
            return
        except CategoryServiceError:
            logger.exception("Failed to inspect category before rename")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                "Failed to inspect the category. See log for details.",
            )
            return

        if impact.transaction_count == 0:
            text = (
                f"Category '{impact.name}' has no transactions. "
                f"A new category '{new_name}' will be created and '{impact.name}' "
                f"will be archived."
            )
        else:
            text = (
                f"Category '{impact.name}' is used by {impact.transaction_count} transactions "
                f"({impact.verified_transaction_count} verified).\n\n"
                f"Rename/migrate to '{new_name}'?\n\n"
                f"This will:\n"
                f"  - Create '{new_name}' as a new active category\n"
                f"  - Move all transactions from '{impact.name}' to '{new_name}'\n"
                f"  - Archive '{impact.name}' (mark inactive)\n"
                f"  - Clear ConfidenceScore on affected transactions\n"
                f"  - Make any models trained on '{impact.name}' stale (recommend retraining model)\n"
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

        try:
            change = self.category_service.rename(src_id, new_name, unverify=unverify)
            self.status_label.setText(
                f"Renamed/migrated '{change.source_name}' to '{change.target_name}'. "
                f"Affected transactions: {change.affected_transactions}."
            )
            self.load_categories()
        except DuplicateCategoryError as exc:
            QtWidgets.QMessageBox.warning(self, "Duplicate Category", str(exc))
        except CategoryNotFoundError:
            QtWidgets.QMessageBox.warning(
                self,
                "Category Not Found",
                "The selected category no longer exists.",
            )
        except InvalidCategoryError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Category", str(exc))
        except CategoryServiceError:
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
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        src_id, tgt_id, unverify = dlg.get_values()

        try:
            source = self.category_service.describe(src_id)
            target = self.category_service.describe(tgt_id)
        except CategoryNotFoundError:
            QtWidgets.QMessageBox.warning(
                self,
                "Category Not Found",
                "The selected categories no longer exist.",
            )
            return
        except CategoryServiceError:
            logger.exception("Failed to inspect categories before merge")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                "Failed to inspect the categories. See log for details.",
            )
            return

        if source.transaction_count == 0:
            text = (
                f"Category '{source.name}' has no transactions. "
                f"It will simply be archived and '{target.name}' will be kept."
            )
        else:
            text = (
                f"Category '{source.name}' is used by {source.transaction_count} transactions "
                f"({source.verified_transaction_count} verified).\n\n"
                f"Merge into '{target.name}'?\n\n"
                f"This will:\n"
                f"  - Move all transactions from '{source.name}' to '{target.name}'\n"
                f"  - Archive '{source.name}' (mark inactive)\n"
                f"  - Clear ConfidenceScore on affected transactions\n"
                f"  - Make any models trained on '{source.name}' stale (recommend retraining model)\n"
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

        try:
            change = self.category_service.merge(src_id, tgt_id, unverify=unverify)
            self.status_label.setText(
                f"Merged '{change.source_name}' into '{change.target_name}'. "
                f"Affected transactions: {change.affected_transactions}."
            )
            self.load_categories()
        except (CategoryNotFoundError, InvalidCategoryError) as exc:
            QtWidgets.QMessageBox.warning(self, "Category Error", str(exc))
        except CategoryServiceError:
            logger.exception("Failed to merge categories")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                "Failed to merge categories. See log for details.",
            )

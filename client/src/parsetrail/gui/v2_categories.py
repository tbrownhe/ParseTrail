"""Fresh 2.0 category authoring without automatic transaction interpretation."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore


class V2CategoryDialog(QDialog):
    """Create and rename category accounts in the selected fresh profile."""

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("2.0 categories")
        self.resize(520, 440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Categories are saved in this profile. No transactions are categorized automatically."))
        self.categories = QListWidget()
        self.categories.currentItemChanged.connect(self._selected)
        layout.addWidget(self.categories)
        add_form = QFormLayout()
        self.add_name = QLineEdit()
        self.add_name.setMaxLength(200)
        add_form.addRow("New category name", self.add_name)
        self.add_kind = QComboBox()
        self.add_kind.addItem("Expense", "expense")
        self.add_kind.addItem("Income", "income")
        add_form.addRow("Category kind", self.add_kind)
        layout.addLayout(add_form)
        self.add_button = QPushButton("Add category")
        self.add_button.clicked.connect(self._add)
        layout.addWidget(self.add_button)
        rename_row = QHBoxLayout()
        self.rename_name = QLineEdit()
        self.rename_name.setMaxLength(200)
        self.rename_name.setPlaceholderText("Selected category name")
        rename_row.addWidget(self.rename_name)
        self.rename_button = QPushButton("Rename selected")
        self.rename_button.clicked.connect(self._rename)
        rename_row.addWidget(self.rename_button)
        layout.addLayout(rename_row)
        self.status = QLabel()
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        self.rename_button.setEnabled(current is not None)
        self.rename_name.setText(current.data(Qt.UserRole + 1) if current is not None else "")

    def refresh(self, selected_id: str | None = None) -> None:
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            accounts = store.category_accounts()
        self.categories.clear()
        for account in accounts:
            item = QListWidgetItem(f"{account.name} ({account.kind.title()})")
            item.setData(Qt.UserRole, account.id)
            item.setData(Qt.UserRole + 1, account.name)
            self.categories.addItem(item)
            if account.id == selected_id:
                self.categories.setCurrentItem(item)
        self.status.setText(f"{len(accounts)} category account(s). No ledger entry was posted.")
        self._selected(self.categories.currentItem())

    def _add(self) -> None:
        try:
            account_id = "category:" + uuid4().hex
            with V2ProfileStore.open(self.profile) as store:
                store.add_category_account(account_id, self.add_name.text().strip(), self.add_kind.currentData())
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Category was not saved", str(exc))
            return
        self.add_name.clear()
        self.refresh(selected_id=account_id)

    def _rename(self) -> None:
        item = self.categories.currentItem()
        if item is None:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                store.rename_category_account(item.data(Qt.UserRole), self.rename_name.text())
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Category was not renamed", str(exc))
            return
        self.refresh(selected_id=item.data(Qt.UserRole))

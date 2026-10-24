"""Fresh 2.0 category authoring without automatic transaction interpretation."""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
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
    """Author categories and effective-month budget targets in a fresh profile."""

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("2.0 categories")
        self.resize(600, 650)
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
        budget_box = QGroupBox("Monthly target for selected category")
        budget_layout = QVBoxLayout(budget_box)
        budget_form = QFormLayout()
        self.budget_month = QDateEdit()
        self.budget_month.setCalendarPopup(True)
        self.budget_month.setDisplayFormat("yyyy-MM")
        today = QDate.currentDate()
        self.budget_month.setDate(QDate(today.year(), today.month(), 1))
        self.budget_month.dateChanged.connect(self._refresh_budget)
        budget_form.addRow("Effective month", self.budget_month)
        self.budget_amount = QLineEdit()
        self.budget_amount.setPlaceholderText("USD, for example 250.00")
        budget_form.addRow("Monthly target", self.budget_amount)
        budget_layout.addLayout(budget_form)
        budget_row = QHBoxLayout()
        self.budget_save = QPushButton("Save target from month")
        self.budget_save.clicked.connect(self._save_budget)
        budget_row.addWidget(self.budget_save)
        self.budget_clear = QPushButton("No target from month")
        self.budget_clear.clicked.connect(lambda: self._save_budget(clear=True))
        budget_row.addWidget(self.budget_clear)
        budget_layout.addLayout(budget_row)
        self.budget_current = QLabel()
        budget_layout.addWidget(self.budget_current)
        budget_layout.addWidget(QLabel("Target changes by effective month. These values do not post transactions."))
        budget_layout.addWidget(QLabel("Saved changes"))
        self.budget_history = QListWidget()
        self.budget_history.setMaximumHeight(100)
        budget_layout.addWidget(self.budget_history)
        layout.addWidget(budget_box)
        self.status = QLabel()
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        self.rename_button.setEnabled(current is not None)
        self.rename_name.setText(current.data(Qt.UserRole + 1) if current is not None else "")
        self.budget_month.setEnabled(current is not None)
        self.budget_amount.setEnabled(current is not None)
        self.budget_save.setEnabled(current is not None)
        self.budget_clear.setEnabled(current is not None)
        self._refresh_budget()

    @staticmethod
    def _money(minor: int) -> str:
        return f"${minor // 100:,}.{minor % 100:02d}"

    def _month(self) -> date:
        selected = self.budget_month.date()
        return date(selected.year(), selected.month(), 1)

    def _refresh_budget(self, *_args) -> None:
        item = self.categories.currentItem()
        self.budget_history.clear()
        if item is None:
            self.budget_current.setText("Select a category to see its monthly target.")
            return
        category_id = item.data(Qt.UserRole)
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            history = store.category_budget_history(category_id)
            target = next(
                target for target in store.category_budget_targets(self._month()) if target.category_id == category_id
            )
        for rate in history:
            amount = "No target" if rate.amount_minor is None else self._money(rate.amount_minor)
            self.budget_history.addItem(f"{rate.effective_month:%Y-%m}: {amount}")
        if target.effective_month is None:
            self.budget_current.setText(f"{self._month():%Y-%m}: No target established")
        else:
            amount = "No target" if target.amount_minor is None else self._money(target.amount_minor)
            self.budget_current.setText(f"{self._month():%Y-%m}: {amount} (effective {target.effective_month:%Y-%m})")

    def _save_budget(self, *, clear: bool = False) -> None:
        item = self.categories.currentItem()
        if item is None:
            return
        try:
            amount_minor = None
            if not clear:
                entered = self.budget_amount.text().strip()
                if re.fullmatch(r"\$?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", entered) is None:
                    raise ValueError("Enter a nonnegative USD amount with at most two decimal places.")
                amount_minor = int(Decimal(entered.lstrip("$").replace(",", "")) * 100)
            with V2ProfileStore.open(self.profile) as store:
                store.set_category_budget_rate(item.data(Qt.UserRole), self._month(), amount_minor)
        except (ValueError, ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Budget target was not saved", str(exc))
            return
        self._refresh_budget()
        self.status.setText(f"Monthly target saved from {self._month():%Y-%m}. No ledger entry was posted.")

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

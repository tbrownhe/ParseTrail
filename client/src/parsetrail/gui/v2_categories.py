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

from parsetrail.core.v2_builtin_categories import BUILTIN_CATEGORIES, builtin_category
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.gui.v2_cash_activity_review import _category_labels
from parsetrail.gui.v2_form_state import install_form_styles, set_field_state, set_status


class V2CategoryDialog(QDialog):
    """Author categories and effective-month budget targets in a fresh profile."""

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        install_form_styles(self)
        self.profile = profile
        self.setWindowTitle("Categories and budgets")
        self.resize(600, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Categories are saved in this profile. No transactions are categorized automatically."))
        self.categories = QListWidget()
        self.categories.currentItemChanged.connect(self._selected)
        layout.addWidget(self.categories)
        self.category_identity = QLabel()
        self.category_identity.setWordWrap(True)
        self.category_identity.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.category_identity)
        builtin_row = QHBoxLayout()
        self.builtin = QComboBox()
        self.builtin.addItem("Choose an optional built-in category", None)
        for item in BUILTIN_CATEGORIES:
            self.builtin.addItem(f"{item.name} ({item.kind.title()}, built-in)", item.account_id)
        self.builtin.currentIndexChanged.connect(self._update_builtin)
        builtin_row.addWidget(self.builtin, 1)
        self.add_builtin_button = QPushButton("Add selected built-in")
        self.add_builtin_button.clicked.connect(self._add_builtin)
        builtin_row.addWidget(self.add_builtin_button)
        add_form = QFormLayout()
        self.add_name = QLineEdit()
        self.add_name.setMaxLength(200)
        add_form.addRow("1. New category name *", self.add_name)
        self.add_kind = QComboBox()
        self.add_kind.addItem("Expense", "expense")
        self.add_kind.addItem("Income", "income")
        add_form.addRow("2. Category kind *", self.add_kind)
        layout.addLayout(add_form)
        self.add_choice_status = QLabel()
        self.add_choice_status.setWordWrap(True)
        layout.addWidget(self.add_choice_status)
        self.add_button = QPushButton("Add custom category")
        self.add_button.clicked.connect(self._add)
        layout.addWidget(self.add_button)
        layout.addLayout(builtin_row)
        rename_row = QHBoxLayout()
        self.rename_name = QLineEdit()
        self.rename_name.setMaxLength(200)
        self.rename_name.setPlaceholderText("Selected category name")
        rename_row.addWidget(self.rename_name)
        self.rename_button = QPushButton("Rename selected")
        self.rename_button.clicked.connect(self._rename)
        rename_row.addWidget(self.rename_button)
        layout.addLayout(rename_row)
        budget_box = QGroupBox("Monthly budget for selected category")
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
        budget_form.addRow("Monthly budget (USD, optional)", self.budget_amount)
        budget_layout.addLayout(budget_form)
        budget_row = QHBoxLayout()
        self.budget_save = QPushButton("Save budget from month")
        self.budget_save.clicked.connect(self._save_budget)
        budget_row.addWidget(self.budget_save)
        self.budget_clear = QPushButton("Remove budget from month")
        self.budget_clear.clicked.connect(lambda: self._save_budget(clear=True))
        budget_row.addWidget(self.budget_clear)
        budget_layout.addLayout(budget_row)
        self.budget_current = QLabel()
        budget_layout.addWidget(self.budget_current)
        budget_layout.addWidget(
            QLabel(
                "A budget applies from the effective month until the next saved change. It does not post transactions."
            )
        )
        budget_layout.addWidget(QLabel("Budget history"))
        self.budget_history = QListWidget()
        self.budget_history.setMaximumHeight(100)
        budget_layout.addWidget(self.budget_history)
        layout.addWidget(budget_box)
        self.status = QLabel()
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.add_name.textChanged.connect(self._update_cues)
        self.add_kind.currentIndexChanged.connect(self._update_cues)
        self.rename_name.textChanged.connect(self._update_cues)
        self.budget_amount.textChanged.connect(self._update_cues)
        self.setTabOrder(self.categories, self.add_name)
        self.setTabOrder(self.add_name, self.add_kind)
        self.setTabOrder(self.add_kind, self.add_button)
        self.setTabOrder(self.add_button, self.builtin)
        self.setTabOrder(self.builtin, self.add_builtin_button)
        self.setTabOrder(self.add_builtin_button, self.rename_name)
        self._saved_budget_draft = None
        self.refresh()

    def _update_cues(self, *_args) -> None:
        if not hasattr(self, "budget_clear"):
            return
        readable = getattr(self, "_readable", False)
        name = self.add_name.text().strip()
        set_field_state(self.add_name, "ready" if name and readable else "required" if readable else "blocked")
        set_field_state(self.add_kind, "ready" if readable else "blocked")
        self.add_button.setEnabled(readable and bool(name))
        set_field_state(self.add_button, "ready" if self.add_button.isEnabled() else "neutral")
        set_status(
            self.add_choice_status,
            "ready" if name and readable else "required" if readable else "blocked",
            "Valid choice · Not saved. Add custom category saves this name and kind; no activity is categorized."
            if name and readable
            else "Required · Enter a name to add a category."
            if readable
            else "Category state unavailable. Reopen this dialog to retry.",
        )
        item = self.categories.currentItem()
        original = item.data(Qt.UserRole + 1) if item else None
        editable = item is not None and not self.rename_name.isReadOnly() and readable
        rename = self.rename_name.text().strip()
        rename_state = (
            ("saved" if rename == original else "ready" if rename else "required") if editable else "readonly"
        )
        set_field_state(self.rename_name, rename_state)
        self.rename_button.setEnabled(editable and bool(rename) and rename != original)
        set_field_state(self.rename_button, "ready" if self.rename_button.isEnabled() else "neutral")
        entered = self.budget_amount.text().strip()
        valid = re.fullmatch(r"\$?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", entered) is not None
        parsed = Decimal(entered.lstrip("$").replace(",", "")) if valid else None
        valid = parsed is not None and parsed < 90_000_000_000_000  # Existing store budget bound, in USD.
        minor = int(parsed * 100) if valid else None
        saved = valid and self._saved_budget_draft == (item.data(Qt.UserRole), self._month(), minor) if item else False
        budget_state = (
            "blocked"
            if not readable or item is None
            else "optional"
            if not entered
            else "saved"
            if saved
            else "ready"
            if valid
            else "invalid"
        )
        set_field_state(
            self.budget_amount,
            budget_state,
            "Enter a nonnegative USD amount with at most two decimal places." if budget_state == "invalid" else "",
        )
        self.budget_save.setEnabled(readable and item is not None and valid and not saved)
        set_field_state(self.budget_save, "ready" if self.budget_save.isEnabled() else "neutral")

    def _selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        category_id = current.data(Qt.UserRole) if current is not None else None
        builtin = builtin_category(category_id) if category_id else None
        self.rename_button.setEnabled(current is not None and builtin is None)
        self.rename_name.setReadOnly(builtin is not None)
        self.rename_name.setText(current.data(Qt.UserRole + 1) if current is not None else "")
        self.category_identity.setText(
            f"Built-in category: {category_id}. Its name and expense/income class are fixed."
            if builtin is not None
            else f"Custom category: {category_id}. A matching name does not establish built-in identity."
            if category_id
            else "Select a category to inspect its identity. Built-ins are added only by explicit choice."
        )
        self.budget_month.setEnabled(current is not None)
        self.budget_amount.setEnabled(current is not None)
        self.budget_save.setEnabled(current is not None)
        self.budget_clear.setEnabled(current is not None)
        self._refresh_budget()
        self._update_cues()

    @staticmethod
    def _money(minor: int) -> str:
        return f"${minor // 100:,}.{minor % 100:02d}"

    def _month(self) -> date:
        selected = self.budget_month.date()
        return date(selected.year(), selected.month(), 1)

    def _refresh_budget(self, *_args) -> bool:
        item = self.categories.currentItem()
        self.budget_history.clear()
        if item is None:
            self.budget_current.setText("Select a category to see its monthly budget.")
            self._update_cues()
            return False
        category_id = item.data(Qt.UserRole)
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                history = store.category_budget_history(category_id)
                target = next(
                    target
                    for target in store.category_budget_targets(self._month())
                    if target.category_id == category_id
                )
        except (ProfileFormatError, sqlite3.Error, OSError, StopIteration):
            self._readable = False
            self._category_accounts = ()
            self.categories.blockSignals(True)
            self.categories.clear()
            self.categories.blockSignals(False)
            self.rename_name.clear()
            self.rename_button.setEnabled(False)
            self.add_button.setEnabled(False)
            self.category_identity.setText("Category state unavailable; reopen this dialog after checking the profile.")
            self._update_builtin()
            self.budget_current.setText("Monthly budget unavailable; saved category state could not be verified.")
            self.budget_amount.clear()
            self.budget_amount.setEnabled(False)
            self.budget_save.setEnabled(False)
            self.budget_clear.setEnabled(False)
            self.budget_month.setEnabled(False)
            self.status.setText("Category budgets could not be read. Reopen this dialog after checking the profile.")
            self._saved_budget_draft = None
            self._update_cues()
            return False
        self._saved_budget_draft = (
            (category_id, self._month(), target.amount_minor) if target.effective_month == self._month() else None
        )
        self.budget_amount.setEnabled(True)
        self.budget_save.setEnabled(True)
        self.budget_clear.setEnabled(True)
        for rate in history:
            amount = "No budget" if rate.amount_minor is None else self._money(rate.amount_minor)
            self.budget_history.addItem(f"{rate.effective_month:%Y-%m}: {amount}")
        if target.effective_month is None:
            self.budget_current.setText(f"{self._month():%Y-%m}: No budget established")
        else:
            amount = "No budget" if target.amount_minor is None else self._money(target.amount_minor)
            self.budget_current.setText(f"{self._month():%Y-%m}: {amount} (effective {target.effective_month:%Y-%m})")
        self._update_cues()
        return True

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
            self._refresh_budget()
            QMessageBox.warning(self, "Budget was not saved", str(exc))
            return
        if self._refresh_budget():
            if clear:
                self.budget_amount.clear()
            self._update_cues()
            action = "removed" if clear else "saved"
            self.status.setText(f"Monthly budget {action} from {self._month():%Y-%m}. No ledger entry was posted.")

    def refresh(self, selected_id: str | None = None) -> None:
        self._readable = True
        try:
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                accounts = store.category_accounts()
        except (ProfileFormatError, sqlite3.Error, OSError):
            self._readable = False
            accounts = ()
        self._category_accounts = accounts
        labels = _category_labels(accounts)
        self.categories.clear()
        for account in accounts:
            item = QListWidgetItem(f"{labels[account.id]} ({account.kind.title()})")
            item.setToolTip(f"{item.text()}\nID: {account.id}")
            item.setData(Qt.UserRole, account.id)
            item.setData(Qt.UserRole + 1, account.name)
            self.categories.addItem(item)
            if account.id == selected_id:
                self.categories.setCurrentItem(item)
        self.status.setText(
            f"{len(accounts)} category account(s). No ledger entry was posted."
            if self._readable
            else "Category state unavailable. Reopen this dialog after checking the profile."
        )
        self._selected(self.categories.currentItem())
        self.add_button.setEnabled(self._readable)
        self._update_builtin()
        self._update_cues()

    def _update_builtin(self, *_args) -> None:
        if not hasattr(self, "add_builtin_button"):
            return
        account_id = self.builtin.currentData()
        self.add_builtin_button.setEnabled(
            bool(
                getattr(self, "_readable", False)
                and builtin_category(account_id) is not None
                and not any(category.id == account_id for category in self._category_accounts)
            )
        )
        set_field_state(
            self.builtin,
            "blocked"
            if not getattr(self, "_readable", False)
            else "ready"
            if self.add_builtin_button.isEnabled()
            else "saved"
            if account_id
            else "optional",
        )
        set_field_state(self.add_builtin_button, "ready" if self.add_builtin_button.isEnabled() else "neutral")

    def _add_builtin(self) -> None:
        account_id = self.builtin.currentData()
        if not self.add_builtin_button.isEnabled() or builtin_category(account_id) is None:
            return
        try:
            with V2ProfileStore.open(self.profile) as store:
                store.ensure_builtin_category(account_id)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Built-in category was not added", str(exc))
            self.refresh()
            return
        self.refresh(selected_id=account_id)

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

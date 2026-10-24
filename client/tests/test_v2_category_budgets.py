"""Fresh-profile monthly budget targets retain their effective-month history."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore


def test_budget_rates_take_effect_by_month_and_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    january = date(2026, 1, 1)
    march = date(2026, 3, 1)
    april = date(2026, 4, 1)
    with V2ProfileStore.create(path) as store:
        store.add_category_account("category:food", "Food", "expense")
        store.add_category_account("category:wages", "Wages", "income")
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        assert [
            (target.name, target.effective_month, target.amount_minor)
            for target in store.category_budget_targets(january)
        ] == [
            ("Food", None, None),
            ("Wages", None, None),
        ]
        store.set_category_budget_rate("category:food", march, 25_000)
        store.set_category_budget_rate("category:food", april, 30_000)
        store.set_category_budget_rate("category:food", april, 31_000)
        store.set_category_budget_rate("category:wages", march, 0)
        store.set_category_budget_rate("category:food", date(2026, 6, 1), None)
        store.rename_category_account("category:food", "Groceries")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert [
            (rate.effective_month, rate.amount_minor) for rate in store.category_budget_history("category:food")
        ] == [
            (march, 25_000),
            (april, 31_000),
            (date(2026, 6, 1), None),
        ]
        assert store.category_budget_targets(january)[0].amount_minor is None
        assert (store.category_budget_targets(march)[0].name, store.category_budget_targets(march)[0].amount_minor) == (
            "Groceries",
            25_000,
        )
        assert store.category_budget_targets(date(2026, 5, 1))[0].amount_minor == 31_000
        cleared = store.category_budget_targets(date(2026, 7, 1))[0]
        assert (cleared.effective_month, cleared.amount_minor) == (date(2026, 6, 1), None)
        assert store.category_budget_targets(march)[1].amount_minor == 0
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            store.set_category_budget_rate("category:food", april, 1)


def test_budget_rate_rejects_invalid_month_amount_and_account(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    with V2ProfileStore.create(path) as store:
        store.add_category_account("category:food", "Food", "expense")
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        for invalid in (True, -1, 1.5, 9_000_000_000_000_000):
            with pytest.raises(ProfileFormatError, match="budget_amount_invalid"):
                store.set_category_budget_rate("category:food", date(2026, 1, 1), invalid)
        with pytest.raises(ProfileFormatError, match="budget_effective_month_invalid"):
            store.set_category_budget_rate("category:food", date(2026, 1, 2), 100)
        with pytest.raises(ProfileFormatError, match="category_account_missing"):
            store.set_category_budget_rate("checking", date(2026, 1, 1), 100)
        assert store.category_budget_history("category:food") == ()


def test_category_dialog_saves_and_displays_effective_target(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_categories import V2CategoryDialog
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "fresh.db"
    with V2ProfileStore.create(path) as store:
        store.add_category_account("category:food", "Food", "expense")
    dialog = V2CategoryDialog(path)
    try:
        dialog.categories.setCurrentRow(0)
        dialog.budget_month.setDate(QDate(2026, 3, 1))
        dialog.budget_amount.setText("$250.00")
        dialog.budget_save.click()
        assert "250.00" in dialog.budget_current.text()
        dialog.budget_month.setDate(QDate(2026, 4, 1))
        assert "250.00" in dialog.budget_current.text()
        dialog.budget_amount.setText("300.00")
        dialog.budget_save.click()
        dialog.budget_month.setDate(QDate(2026, 3, 1))
        assert "250.00" in dialog.budget_current.text()
        dialog.budget_month.setDate(QDate(2026, 5, 1))
        assert "300.00" in dialog.budget_current.text()
        dialog.budget_clear.click()
        assert "No target" in dialog.budget_current.text()
        assert dialog.budget_history.count() == 3
    finally:
        dialog.close()
        app.processEvents()

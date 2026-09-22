import sys
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from parsetrail.core.budgets import BudgetRow
from parsetrail.gui.accounts import AppreciationDialog
from parsetrail.gui.budget_view import BudgetTab
from parsetrail.gui.main_window import ParseTrail
from parsetrail.gui.transactions import RecurringTransactionsDialog
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QListWidgetItem, QMessageBox


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.mark.parametrize(
    "page_name,list_name",
    [
        ("page1", "account_select_list"),
        ("page2", "category_select_list"),
    ],
)
def test_select_all_can_check_and_clear_every_item(app, monkeypatch, page_name, list_name):
    monkeypatch.setattr(ParseTrail, "initialize_all_elements", lambda self: None)
    monkeypatch.setattr(ParseTrail, "showMaximized", lambda self: None)
    original_hook = sys.excepthook
    window = ParseTrail()
    try:
        items = getattr(window, list_name)
        for name in ("One", "Two", "Three"):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            items.addItem(item)
        (checkbox,) = [box for box in getattr(window, page_name).findChildren(QCheckBox) if box.text() == "Select All"]
        for expected in (Qt.Checked, Qt.Unchecked, Qt.Checked):
            checkbox.click()
            assert [items.item(i).checkState() for i in range(items.count())] == [expected] * 3
    finally:
        sys.excepthook = original_hook
        window.close()
        window.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("mode", ["Month", "Custom Range"])
@pytest.mark.parametrize("group_by", ["Category", "Type"])
def test_budget_refresh_renders_dates_and_decimal_spending(app, mode, group_by):
    tab = BudgetTab(None)
    # The small outflow must join Other; income must not dilute spending share.
    rows = [
        BudgetRow("Main", Decimal("-100"), Decimal("-98"), Decimal("2"), Decimal("98"), 2),
        BudgetRow("Small", None, Decimal("-2"), None, None, 1),
        BudgetRow("Income", None, Decimal("500"), None, None, 1),
    ]
    report = Mock(return_value=rows)
    tab.budget_service = SimpleNamespace(report=report)
    tab.range_mode.setCurrentText(mode)
    tab.group_by_combo.setCurrentText(group_by)
    tab.month_selector.setDate(QDate(2026, 8, 1))
    tab.start_date.setDate(QDate(2026, 8, 2))
    tab.end_date.setDate(QDate(2026, 8, 15))
    tab.include_inactive_checkbox.setChecked(True)
    try:
        tab.refresh_button.click()
        report.assert_called_once_with(
            start=date(2026, 8, 2) if mode == "Custom Range" else date(2026, 8, 1),
            end=date(2026, 8, 16) if mode == "Custom Range" else date(2026, 9, 1),
            include_inactive=True,
            group_by=group_by,
            prorate=mode == "Custom Range",
        )
        assert "Budget $-100.00 | Actual $400.00 | Variance $500.00" in tab.status_label.text()
        assert tab.table.model().rowCount() == 3
        legend = tab.util_axes.get_legend()
        assert [item.get_text() for item in legend.get_texts()] == ["Main", "Other"]
        assert len(tab.util_axes.patches) == 2
    finally:
        tab.close()
        tab.deleteLater()
        app.processEvents()


def test_appreciation_calculator_accepts_qt_dates(app, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args))
    dialog = AppreciationDialog()
    try:
        dialog.start_date.setDate(QDate(2025, 1, 1))
        dialog.end_date.setDate(QDate(2026, 1, 1))
        dialog.start_value_edit.setText("100")
        dialog.end_value_edit.setText("110")
        dialog.submit_button.click()
        assert not errors
        assert dialog.result_edit.text() == "10.00"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_recurring_input_receives_calendar_dates(app):
    dialog = RecurringTransactionsDialog(None)
    in_range = Mock(return_value=[])
    dialog.transaction_service = SimpleNamespace(in_range=in_range)
    try:
        dialog.start_date.setDate(QDate(2026, 8, 1))
        dialog.end_date.setDate(QDate(2026, 8, 31))
        dialog.analyze_transactions()
        in_range.assert_called_once_with(date(2026, 8, 1), date(2026, 8, 31))
        assert dialog.model.rowCount() == 0
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()

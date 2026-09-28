import pytest
from parsetrail.gui.ledger_preview import LedgerPreviewWindow, PreviewPage, money
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_filter_selection_uses_underlying_row_and_never_exposes_editing(app):
    records = [
        {"cells": ["Checking", "Transfer needs confirmation"], "details": "First synthetic detail"},
        {"cells": ["Card", "Needs category"], "details": "Second synthetic detail"},
    ]
    page = PreviewPage(["Account", "Status"], records)
    page.search.setText("card")
    assert page.proxy.rowCount() == 1
    page.table.selectRow(0)
    app.processEvents()
    assert page.details.toPlainText() == "Second synthetic detail"
    page.search.setText("category")
    page.table.selectRow(0)
    app.processEvents()
    assert page.details.toPlainText() == "Second synthetic detail"
    assert not (page.model.flags(page.model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable)
    page.search.setText("no result")
    assert page.proxy.rowCount() == 0
    assert page.details.toPlainText() == ""
    page.search.clear()
    assert page.proxy.rowCount() == 2
    page.close()


@pytest.mark.usefixtures("app")
def test_window_exposes_only_read_only_review_tabs():
    window = LedgerPreviewWindow({"summary": "Synthetic preview", "tabs": [("Statements", ["Account"], [])]})
    assert window.tabs.count() == 1
    assert "read only" in window.windowTitle()
    window.close()


def test_money_display_preserves_integer_precision():
    assert money(-12345) == "-$123.45"
    assert money(2**53 + 1) == "$90,071,992,547,409.93"

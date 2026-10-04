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


@pytest.mark.usefixtures("app")
@pytest.mark.parametrize(
    "values,expected",
    [
        (
            ["$100.00", "-$20.00", "$9.00", "$1,000.00", "Unknown"],
            ["-$20.00", "$9.00", "$100.00", "$1,000.00", "Unknown"],
        ),
        ([money(2**53 + 1), money(2**53)], [money(2**53), money(2**53 + 1)]),
        (["100", "9", "1,000"], ["9", "100", "1,000"]),
        (["2026-10-03", "2025-12-31", "2026-02-01"], ["2025-12-31", "2026-02-01", "2026-10-03"]),
        (["Savings", "checking", "Card"], ["Card", "checking", "Savings"]),
    ],
)
def test_sorting_every_column_uses_exact_values_and_preserves_source_order(values, expected):
    records = [{"cells": ["same", value], "details": value} for value in values]
    page = PreviewPage(["Account", "Value"], records)
    assert page.table.isSortingEnabled()
    assert [page.proxy.index(i, 1).data() for i in range(len(values))] == values
    page.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    assert [page.proxy.index(i, 1).data() for i in range(len(values))] == expected
    page.table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    assert [page.proxy.index(i, 1).data() for i in range(len(values))] == expected[::-1]
    assert [r["cells"][1] for r in records] == values
    page.close()


def test_sort_selection_details_filter_and_refresh_keep_row_identity(app):
    records = [
        {"cells": ["Checking", "$100.00"], "details": "large"},
        {"cells": ["Savings", "$9.00"], "details": "small"},
    ]
    page = PreviewPage(["Account", "Amount"], records)
    page.table.selectRow(0)
    page.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    app.processEvents()
    selected = page.table.selectionModel().selectedRows()[0]
    assert page.proxy.mapToSource(selected).row() == 0
    assert page.details.toPlainText() == "large"
    page.table.selectRow(0)
    assert page.details.toPlainText() == "small"
    page.search.setText("Checking")
    assert not page.table.selectionModel().selectedRows() and not page.details.toPlainText()
    page.table.selectRow(0)
    assert page.details.toPlainText() == "large"
    page.search.clear()
    page.model.beginResetModel()
    page.model.records = [*records, {"cells": ["Checking", "-$1.00"], "details": "negative"}]
    page.model.endResetModel()
    page.filter("")
    assert page.proxy.index(0, 1).data() == "-$1.00"
    assert not page.details.toPlainText()
    page.close()

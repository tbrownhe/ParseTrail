from datetime import date
from decimal import Decimal

import pytest
from parsetrail.core.review import TransactionRecord
from parsetrail.gui.review_models import TransactionFilterProxyModel, TransactionTableModel
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QStyledItemDelegate, QStyleOptionViewItem


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


def _record(transaction_id: int, posting_date: date) -> TransactionRecord:
    return TransactionRecord(
        transaction_id=transaction_id,
        date=posting_date,
        account_name="Example",
        description="Synthetic transaction",
        amount=Decimal("-12.34"),
        category_id=None,
        category_name="",
        verified=False,
        category_active=True,
    )


@pytest.mark.usefixtures("app")
def test_review_date_reaches_qt_delegate_as_calendar_text() -> None:
    record = _record(1, date(2024, 2, 29))
    model = TransactionTableModel([record])
    proxy = TransactionFilterProxyModel()
    proxy.setSourceModel(model)
    delegate = QStyledItemDelegate()
    option = QStyleOptionViewItem()

    delegate.initStyleOption(option, proxy.index(0, model.COL_DATE))

    assert option.text == "2024-02-29"
    assert record.date == date(2024, 2, 29)


@pytest.mark.parametrize(
    "order,expected_ids",
    [(Qt.AscendingOrder, [2, 3, 4, 1]), (Qt.DescendingOrder, [1, 4, 3, 2])],
)
@pytest.mark.usefixtures("app")
def test_review_dates_sort_chronologically_through_proxy(order, expected_ids) -> None:
    model = TransactionTableModel(
        [
            _record(1, date(2026, 1, 2)),
            _record(2, date(2024, 2, 29)),
            _record(3, date(2025, 12, 31)),
            _record(4, date(2026, 1, 1)),
        ]
    )
    proxy = TransactionFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.sort(model.COL_DATE, order)

    assert [proxy.index(row, model.COL_ID).data() for row in range(proxy.rowCount())] == expected_ids

"""The narrow desktop review posts and corrects only supported cash expenses."""

from __future__ import annotations

import os
from pathlib import Path

from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()
SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
    b"10/02/2026,Checking A,Deposit,$10.00,$1006.00\n"
)


def test_cash_expense_dialog_posts_corrects_and_keeps_other_row_pending(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_cash_expense_review import V2CashExpenseReview
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog = V2CashExpenseReview(profile, evidence.source_sha256)
    try:
        assert dialog.model.rows[0].status == "Assign a financial account first"
        dialog.table.selectRow(0)
        assert not dialog.action_button.isEnabled()
        with V2ProfileStore.open(profile) as store:
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        dialog.refresh()
        assert [row.status for row in dialog.model.rows] == [
            "Ready for expense review",
            "Outside cash expense scope",
        ]
        dialog.table.selectRow(1)
        assert not dialog.action_button.isEnabled()
        dialog.table.selectRow(0)
        assert dialog.action_button.isEnabled()
        dialog.reason.setText("Reviewed purchase")
        dialog.action_button.click()
        assert dialog.model.rows[0].status == "Posted: Food"
        assert dialog.model.rows[1].status == "Outside cash expense scope"
        assert dialog.action_button.text() == "Correct expense category"
        renamed = "A Very Long Renamed Checking Account For Testing"
        with V2ProfileStore.open(profile) as store:
            store.update_financial_account(FinancialAccount("cash", renamed, "asset", "synthetic"))
        dialog.refresh(selected_row_id=evidence.payload.rows[0].row_id)
        dialog.show()
        app.processEvents()
        assert dialog.model.rows[0].financial_account == renamed
        assert dialog.table.columnWidth(3) > dialog.table.fontMetrics().horizontalAdvance(renamed)
        dialog.category.setCurrentIndex(dialog.category.findData("expense:travel"))
        dialog.reason.setText("Correct category")
        dialog.action_button.click()
        assert dialog.model.rows[0].status == "Posted: Travel"
        assert dialog.model.rows[1].status == "Outside cash expense scope"
    finally:
        dialog.close()
        app.processEvents()
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (3,)
        assert store.connection.execute("SELECT count(*) FROM JournalCorrections").fetchone() == (1,)
        assert store._active_consumed() == {evidence.payload.rows[0].row_id: -400}
        assert store.load_import(evidence.source_sha256).evidence == evidence

"""The desktop review posts and corrects explicit asset cash categories."""

from __future__ import annotations

import os
from pathlib import Path

from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_table_bank_source_output import from_anchored_bank

from devtools.parser_engine_pilot.test_table_bank_source_output import DEFINITION as BANK_DEFINITION
from devtools.parser_engine_pilot.test_table_bank_source_output import SOURCE as BANK_SOURCE
from devtools.parser_engine_pilot.test_table_bank_source_output import evidence as bank_channels

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()
SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
    b"10/02/2026,Checking A,Deposit,$10.00,$1006.00\n"
)


def test_cash_activity_dialog_keeps_unclassified_deposit_pending(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
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
    dialog = V2CashActivityReview(profile, evidence.source_sha256)
    try:
        assert dialog.model.rows[0].status == "Assign a financial account first"
        dialog.table.selectRow(0)
        assert not dialog.action_button.isEnabled()
        with V2ProfileStore.open(profile) as store:
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        dialog.refresh()
        assert [row.status for row in dialog.model.rows] == [
            "Ready for expense review",
            "Ready for income review",
        ]
        dialog.table.selectRow(1)
        assert not dialog.action_button.isEnabled()
        assert "add an income category first" in dialog.status.text()
        dialog.table.selectRow(0)
        assert dialog.action_button.isEnabled()
        dialog.reason.setText("Reviewed purchase")
        dialog.action_button.click()
        assert dialog.model.rows[0].status == "Posted: Food"
        assert dialog.model.rows[1].status == "Ready for income review"
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
        assert dialog.model.rows[1].status == "Ready for income review"
    finally:
        dialog.close()
        app.processEvents()
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (3,)
        assert store.connection.execute("SELECT count(*) FROM JournalCorrections").fetchone() == (1,)
        assert store._active_consumed() == {evidence.payload.rows[0].row_id: -400}
        assert store.load_import(evidence.source_sha256).evidence == evidence


def test_cash_activity_dialog_explicitly_posts_and_corrects_income(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("income:pay", "Pay", "income")
        store.add_category_account("income:gift", "Gift", "income")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
    confirmations = []

    def confirm(_dialog, _title, message):
        confirmations.append(message)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = V2CashActivityReview(profile, evidence.source_sha256)
    try:
        dialog.table.selectRow(1)
        assert dialog.category.count() == 2
        assert dialog.category.findData("expense:food") == -1
        assert dialog.action_button.text() == "Post reviewed income"
        dialog.category.setCurrentIndex(dialog.category.findData("income:pay"))
        dialog.reason.setText("Confirmed income")
        dialog.action_button.click()
        assert dialog.model.rows[1].status == "Posted: Pay"
        assert any("I confirm this receipt is income." in message for message in confirmations)
        assert dialog.action_button.text() == "Correct income category"
        dialog.category.setCurrentIndex(dialog.category.findData("income:gift"))
        dialog.reason.setText("Correct classification")
        dialog.action_button.click()
        assert dialog.model.rows[1].status == "Posted: Gift"
        assert dialog.model.rows[0].status == "Ready for expense review"
    finally:
        dialog.close()
        app.processEvents()
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store._active_consumed() == {evidence.payload.rows[1].row_id: 1_000}


def test_bank_statement_rows_use_explicit_cash_review_dialog(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    evidence = from_anchored_bank(BANK_DEFINITION, *bank_channels())
    account = evidence.payload.accounts[0]
    profile = tmp_path / "bank.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(BANK_SOURCE, BANK_DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("cash", "Savings", "asset", "lendingclub"))
        store.add_category_account("expense:other", "Other", "expense")
        store.add_category_account("income:interest", "Interest", "income")
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "cash")
    confirmations = []

    def confirm(_dialog, _title, message):
        confirmations.append(message)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = V2CashActivityReview(profile, evidence.source_sha256)
    try:
        assert [row.status for row in dialog.model.rows] == ["Ready for income review", "Ready for expense review"]
        assert "account-total scope" in dialog.note.text()
        dialog.table.selectRow(0)
        dialog.category.setCurrentIndex(dialog.category.findData("income:interest"))
        dialog.reason.setText("Confirmed interest")
        dialog.action_button.click()
        assert dialog.model.rows[0].status == "Posted: Interest"
        assert any("I confirm this receipt is income." in message for message in confirmations)
        dialog.table.selectRow(1)
        dialog.category.setCurrentIndex(dialog.category.findData("expense:other"))
        dialog.reason.setText("Reviewed withdrawal")
        dialog.action_button.click()
        assert dialog.model.rows[1].status == "Posted: Other"
    finally:
        dialog.close()
        app.processEvents()
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store._active_consumed() == {account.rows[0].row_id: 1_000, account.rows[1].row_id: -2_000}

"""The 2.0 reports state their reviewed-journal and source-coverage scope."""

from __future__ import annotations

import hashlib
import os
from datetime import date
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


def test_spending_dialog_reads_posted_totals_without_changing_profile(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.set_category_budget_rate("expense:food", date(2026, 10, 1), 1_000)
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        store.post_reviewed_cash_category(evidence.payload.rows[0].row_id, "expense:food", reason="Reviewed coffee")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = V2ReviewedReportsDialog(profile)
    try:
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 11, 1))
        assert dialog.model.rowCount() == 1
        assert dialog.model.data(dialog.model.index(0, 0)) == "Food"
        assert dialog.model.data(dialog.model.index(0, 1)) == "$4.00"
        assert "$4.00" in dialog.total.text()
        assert "whole profile, 1 activity source row" in dialog.scope.text()
        assert "date range above filters posted journal entries only" in dialog.scope.text()
        dialog.tabs.setCurrentIndex(1)
        assert dialog.account_model.rowCount() == 1
        assert dialog.account_model.data(dialog.account_model.index(0, 0)) == "Checking"
        assert dialog.account_model.data(dialog.account_model.index(0, 2)) == "-$4.00"
        assert dialog.account_model.data(dialog.account_model.index(0, 3)) == "Not established"
        assert "not account balances" in dialog.scope.text()
        dialog.tabs.setCurrentIndex(2)
        dialog.budget_month.setDate(QDate(2026, 10, 1))
        assert dialog.budget_model.rowCount() == 1
        assert dialog.budget_model.data(dialog.budget_model.index(0, 1)) == "$10.00"
        assert dialog.budget_model.data(dialog.budget_model.index(0, 2)) == "$4.00"
        assert dialog.budget_model.data(dialog.budget_model.index(0, 3)) == "$6.00"
        assert "whole calendar months" in dialog.scope.text()
        dialog.end.setDate(QDate(2026, 10, 1))
        assert dialog.model.rowCount() == 0
        assert dialog.account_model.rowCount() == 0
        assert dialog.budget_model.rowCount() == 1
        dialog.tabs.setCurrentIndex(0)
        assert "end date after" in dialog.total.text()
        assert not dialog.export_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_report_dialog_exports_reviewed_rows_without_changing_profile(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from openpyxl import load_workbook
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    app = QApplication.instance() or QApplication([])
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        store.post_reviewed_cash_category(evidence.payload.rows[0].row_id, "expense:food", reason="Reviewed coffee")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    export_path = tmp_path / "reviewed.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(export_path), ""))
    notices = []
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, message: notices.append(message))
    dialog = V2ReviewedReportsDialog(profile)
    try:
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 11, 1))
        assert dialog.export_button.isEnabled()
        dialog.export_button.click()
        assert export_path.is_file()
        assert "1 active reviewed entries" in notices[0]
        workbook = load_workbook(export_path, read_only=True)
        try:
            assert len(list(workbook["Reviewed Entries"].values)) == 2
            assert len(list(workbook["Source Allocations"].values)) == 2
        finally:
            workbook.close()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_income_tab_shows_only_reviewed_income_and_coverage(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("income:pay", "Pay", "income")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        store.post_reviewed_cash_category(evidence.payload.rows[1].row_id, "income:pay", reason="Confirmed income")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = V2ReviewedReportsDialog(profile)
    try:
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 11, 1))
        dialog.tabs.setCurrentIndex(3)
        assert dialog.income_model.rowCount() == 1
        assert dialog.income_model.data(dialog.income_model.index(0, 0)) == "Pay"
        assert dialog.income_model.data(dialog.income_model.index(0, 1)) == "$10.00"
        assert "Net reviewed income" in dialog.total.text()
        assert "1 activity source row" in dialog.scope.text()
        assert "not all deposits" in dialog.scope.text()
        dialog.start.setDate(QDate(2026, 11, 1))
        dialog.end.setDate(QDate(2026, 12, 1))
        assert dialog.income_model.data(dialog.income_model.index(0, 1)) == "$0.00"
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before

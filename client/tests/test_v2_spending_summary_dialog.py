"""The 2.0 spending view states its reviewed-journal and source-coverage scope."""

from __future__ import annotations

import hashlib
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


def test_spending_dialog_reads_posted_totals_without_changing_profile(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_spending_summary import V2SpendingSummaryDialog
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        store.post_reviewed_cash_expense(evidence.payload.rows[0].row_id, "expense:food", reason="Reviewed coffee")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = V2SpendingSummaryDialog(profile)
    try:
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 11, 1))
        assert dialog.model.rowCount() == 1
        assert dialog.model.data(dialog.model.index(0, 0)) == "Food"
        assert dialog.model.data(dialog.model.index(0, 1)) == "$4.00"
        assert "$4.00" in dialog.total.text()
        assert "whole profile, 1 activity source row" in dialog.scope.text()
        assert "date range above filters posted journal entries only" in dialog.scope.text()
        dialog.end.setDate(QDate(2026, 10, 1))
        assert dialog.model.rowCount() == 0
        assert "end date after" in dialog.total.text()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before

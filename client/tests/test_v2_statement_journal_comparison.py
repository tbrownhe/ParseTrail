"""Printed statement movement and reviewed journal movement remain separate facts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_table_bank_source_output import from_anchored_bank

from devtools.parser_engine_pilot.test_table_bank_source_output import DEFINITION, SOURCE
from devtools.parser_engine_pilot.test_table_bank_source_output import evidence as bank_channels


def _profile(path: Path):
    evidence = from_anchored_bank(DEFINITION, *bank_channels())
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("cash", "Savings", "asset", "lendingclub"))
        store.add_category_account("income:interest", "Interest", "income")
        store.add_category_account("expense:other", "Other", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "cash")
    return evidence


def test_statement_comparison_keeps_unallocated_and_posted_movement_distinct(tmp_path: Path):
    path = tmp_path / "comparison.db"
    evidence = _profile(path)
    interest, withdrawal = evidence.payload.accounts[0].rows
    with V2ProfileStore.open(path) as store:
        before = store.statement_journal_comparisons()[0]
        assert before.period_start == date(2026, 1, 1)
        assert before.printed_change_minor == -1_000
        assert before.source_activity_change_minor == -1_000
        assert before.journal_change_minor == 0 and before.difference_minor == 1_000
        assert before.unallocated_rows == 2 and before.unallocated_magnitude_minor == 3_000
        assert before.status == "Source movements awaiting allocation"
        store.post_reviewed_cash_category(interest.row_id, "income:interest", reason="Reviewed interest")
        store.post_reviewed_cash_category(withdrawal.row_id, "expense:other", reason="Reviewed withdrawal")
        after = store.statement_journal_comparisons()[0]
        assert after.journal_change_minor == -1_000 and after.difference_minor == 0
        assert after.unallocated_rows == 0 and after.outside_postings == 0
        assert after.status.startswith("Movement agrees;")
        original = f"review:cash:expense:{withdrawal.row_id}"
        store.correct_reviewed_cash_category(original, "expense:travel", reason="Test correction")
        corrected = store.statement_journal_comparisons()[0]
        assert corrected.journal_change_minor == -1_000
        assert corrected.outside_postings == 0
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.statement_journal_comparisons()[0] == corrected


def test_coverage_dialog_shows_journal_comparison_without_reconciliation_claim(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "comparison.db"
    _profile(path)
    dialog = V2StatementCoverageDialog(path)
    try:
        dialog.show()
        app.processEvents()
        assert dialog.profile_path.text() == str(path)
        assert dialog.comparison_model.rowCount() == 1
        assert "\n" in dialog.comparison_model.HEADERS[0]
        assert dialog.comparison_table.columnWidth(2) >= 260
        assert dialog.comparison_model.data(dialog.comparison_model.index(0, 3)) == "-$10.00"
        assert dialog.comparison_model.data(dialog.comparison_model.index(0, 7)) == "2"
        assert "awaiting allocation" in dialog.comparison_model.data(dialog.comparison_model.index(0, 2))
    finally:
        dialog.close()
        app.processEvents()

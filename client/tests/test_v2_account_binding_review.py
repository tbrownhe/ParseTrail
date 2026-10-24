"""The accountless export review writes only explicit profile decisions."""

from __future__ import annotations

import os
from pathlib import Path

from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_account_binding_review import review_accountless_export
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication

from devtools.parser_engine_pilot.review_accountless_export import main as demo_main

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "parser_engine_pilot" / "mohela-account-history-definition.json"
).read_bytes()
SOURCE = (
    b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
    b"Date,Description,Principal,Interest,Fees,Total,\n"
    b"10/01/2026,Payment,-$80.00,-$20.00,$0.00,-$100.00,\n"
    b"10/02/2026,Payment,-$40.00,-$10.00,$0.00,-$50.00,\n"
)


def test_review_switches_explicit_file_and_mixed_row_modes(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "review.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("loan-a", "Loan A", "liability", "mohela"))
        store.add_financial_account(FinancialAccount("loan-b", "Loan B", "liability", "mohela"))
    dialog = review_accountless_export(profile, evidence.source_sha256)
    try:
        assert dialog.model.rowCount() == 2
        assert "No account assignments" in dialog.status.text()
        dialog.file_button.click()
        assert "Whole-file assertion: Loan A" in dialog.status.text()
        assert not dialog.assign_rows_button.isEnabled()
        dialog.clear_file_button.click()

        second = dialog.model.index(1, 0)
        dialog.table.selectionModel().select(
            second, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        )
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData("loan-b"))
        dialog.assign_rows_button.click()
        assert "Row assignments: 1 of 2" in dialog.status.text()
        assert dialog.model.data(dialog.model.index(1, 3)) == "Loan B"
        assert not dialog.file_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert [
            (binding.ledger_account_id, binding.basis) for binding in store.account_bindings(evidence.source_sha256)
        ] == [
            (None, None),
            ("loan-b", "row"),
        ]
        assert store.connection.execute("SELECT count(*) FROM sqlite_master WHERE name='LedgerEntries'").fetchone() == (
            0,
        )


def test_disposable_native_review_demo_has_six_rows(monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview

    opened = []
    monkeypatch.setattr(V2AccountBindingReview, "exec", lambda self: opened.append(self.model.rowCount()))
    assert demo_main(["--demo"]) == 0
    assert opened == [6]


def test_mixed_identity_export_reviews_only_unidentified_rows(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview

    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    first, second = evidence.payload.rows
    identified = first.model_copy(update={"source_account": "Loan A", "source_account_form": "opaque"})
    mixed = evidence.model_copy(update={"payload": evidence.payload.model_copy(update={"rows": (identified, second)})})
    profile = tmp_path / "mixed.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, mixed, suffix=".csv")
        store.add_financial_account(FinancialAccount("loan-a", "Loan A", "liability", "mohela"))
    dialog = V2AccountBindingReview(profile, mixed.source_sha256)
    try:
        assert dialog.model.rowCount() == 1
        assert not dialog.file_button.isEnabled()
        dialog.table.selectRow(0)
        assert dialog.assign_rows_button.isEnabled()
        dialog.assign_rows_button.click()
        assert "1 of 1" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert [
            (binding.ledger_account_id, binding.basis) for binding in store.account_bindings(mixed.source_sha256)
        ] == [
            (None, None),
            ("loan-a", "row"),
        ]

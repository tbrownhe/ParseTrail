"""The accountless export review writes only explicit profile decisions."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview, review_accountless_export
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QMessageBox

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
        assert "already associate" not in dialog.status.text()
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
        assert "Assign the remaining rows" in dialog.status.text()
        assert "no whole-document assertion is required" in dialog.status.text()
        assert dialog.model.data(dialog.model.index(1, 3)) == "Loan B (mohela, liability)"
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


@pytest.mark.parametrize("assignment", ["file", "row"])
def test_accountless_review_explains_posted_assignment_lock(tmp_path: Path, assignment: str) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    cash_definition = json.loads(
        (
            Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
        ).read_bytes()
    )
    cash_definition["parser_id"] = "synthetic_accountless_cash_csv"
    cash_definition["header"].remove("Account")
    del cash_definition["columns"]["account"]
    cash_definition["account_key"] = "unknown"
    definition = json.dumps(cash_definition).encode()
    source = b"Date,Description,Amount,ReportedBalance\n10/01/2026,Coffee,-$4.00,$996.00\n"
    evidence = build_source_evidence(source, definition, suffix=".csv")
    row_id = evidence.payload.rows[0].row_id
    profile = tmp_path / "review.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(source, definition, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Renamed Checking Account", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        if assignment == "file":
            store.assert_file_account(evidence.source_sha256, "cash")
        else:
            store.assign_row_account(row_id, "cash")
        store.post_reviewed_cash_category(row_id, "expense:food", reason="Reviewed coffee")
    dialog = review_accountless_export(profile, evidence.source_sha256)
    try:
        dialog.table.selectRow(0)
        dialog.show()
        app.processEvents()
        assert dialog.table.columnWidth(3) > dialog.table.fontMetrics().horizontalAdvance("Renamed Checking Account")
        assert "posted" in dialog.lock_notice.text().lower()
        assert not dialog.assign_rows_button.isEnabled()
        assert not dialog.clear_rows_button.isEnabled()
        if assignment == "file":
            assert not dialog.file_button.isEnabled()
            assert not dialog.clear_file_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def _review_profile(tmp_path, *, rows=2):
    raw = (
        SOURCE.splitlines()[0]
        + b"\n"
        + b"".join(f"10/01/2026,Payment {index},-$80.00,-$20.00,$0.00,-$100.00,\n".encode() for index in range(rows))
    )
    evidence = build_source_evidence(raw, DEFINITION, suffix=".csv")
    profile = tmp_path / "review.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(raw, DEFINITION, evidence, suffix=".csv")
        for suffix in ("a", "b"):
            store.add_financial_account(
                FinancialAccount(f"loan-{suffix}", f"Synthetic loan {suffix}", "liability", "mohela")
            )
    return profile, evidence


def test_one_reload_snapshot_and_100_row_selections_or_combo_repaints_do_no_database_reads(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    profile, evidence = _review_profile(tmp_path, rows=100)
    reads = []
    original_snapshot = V2ProfileStore.accountless_binding_review_snapshot

    def snapshot(store, source):
        reads.append(source)
        return original_snapshot(store, source)

    monkeypatch.setattr(V2ProfileStore, "accountless_binding_review_snapshot", snapshot)
    dialog = V2AccountBindingReview(profile, evidence.source_sha256)
    try:
        assert reads == [evidence.source_sha256]
        dialog.show()
        app.processEvents()

        def forbidden(*_args, **_kwargs):
            raise AssertionError("Selecting rows or repainting must not open or read a profile")

        monkeypatch.setattr(V2ProfileStore, "open", forbidden)
        monkeypatch.setattr(V2ProfileStore, "binding_correction_snapshot", forbidden)
        monkeypatch.setattr(V2ProfileStore, "accountless_binding_review_snapshot", forbidden)
        for index in range(100):
            dialog.table.selectRow(index)
            dialog.account_combo.setCurrentIndex(index % 2)
            dialog.table.viewport().repaint()
            dialog.account_combo.repaint()
            app.processEvents()
            assert dialog.assign_rows_button.isEnabled()
        assert dialog._selected_row_ids() == (evidence.payload.rows[-1].row_id,)
        assert reads == [evidence.source_sha256]
    finally:
        dialog.close()
        app.processEvents()


def test_saving_all_rows_publishes_current_assignments_and_preserves_selection_after_reload(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    profile, evidence = _review_profile(tmp_path)
    dialog = V2AccountBindingReview(profile, evidence.source_sha256)
    try:
        dialog.table.selectAll()
        dialog.table.selectionModel().setCurrentIndex(dialog.model.index(1, 0), QItemSelectionModel.NoUpdate)
        selected = dialog._selected_row_ids()
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData("loan-b"))
        dialog.assign_rows_button.click()
        assert "Row assignments: 2 of 2" in dialog.status.text()
        assert "already associate this document" in dialog.status.text()
        assert "no whole-document assertion is required" in dialog.status.text()
        assert [row.ledger_account_id for row in dialog.model.bindings] == ["loan-b", "loan-b"]
        assert dialog._selected_row_ids() == selected and dialog.table.currentIndex().row() == 1
        assert dialog.account_combo.currentData() == "loan-b" and not dialog.file_button.isEnabled()
        dialog.reload_button.click()
        assert "Row assignments: 2 of 2" in dialog.status.text()
        assert dialog._selected_row_ids() == selected and dialog.table.currentIndex().row() == 1
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert all(
                binding.ledger_account_id == "loan-b" for binding in store.account_bindings(evidence.source_sha256)
            )
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        dialog.close()
        app.processEvents()
    reopened = V2AccountBindingReview(profile, evidence.source_sha256)
    try:
        assert "Row assignments: 2 of 2" in reopened.status.text()
        assert [row.ledger_account_id for row in reopened.model.bindings] == ["loan-b", "loan-b"]
    finally:
        reopened.close()
        app.processEvents()


def test_cached_selection_never_bypasses_a_new_posted_history_lock_at_save(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    definition = json.loads(
        (Path(__file__).parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json").read_bytes()
    )
    definition["header"].remove("Account")
    del definition["columns"]["account"]
    definition["account_key"] = "unknown"
    definition = json.dumps(definition).encode()
    source = b"Date,Description,Amount,ReportedBalance\n10/01/2026,Coffee,-$4.00,$996.00\n"
    evidence = build_source_evidence(source, definition, suffix=".csv")
    row_id = evidence.payload.rows[0].row_id
    profile = tmp_path / "posted-after-reload.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(source, definition, evidence, suffix=".csv")
        for suffix in ("a", "b"):
            store.add_financial_account(FinancialAccount(f"cash-{suffix}", f"Checking {suffix}", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.assign_row_account(row_id, "cash-a")
    dialog = V2AccountBindingReview(profile, evidence.source_sha256)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    try:
        dialog.table.selectRow(0)
        assert dialog.assign_rows_button.isEnabled()
        with V2ProfileStore.open(profile) as store:
            store.post_reviewed_cash_category(row_id, "expense:food", reason="Reviewed after the GUI snapshot")
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData("cash-b"))
        assert dialog.assign_rows_button.isEnabled()  # Advisory view; save checks authoritative current history.
        dialog.assign_rows_button.click()
        assert warnings and "posted" in warnings[0].lower()
        assert not dialog.assign_rows_button.isEnabled() and not dialog.clear_rows_button.isEnabled()
        assert "posted" in dialog.lock_notice.text().lower()
        assert dialog._selected_row_ids() == (row_id,)
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store.account_bindings(evidence.source_sha256)[0].ledger_account_id == "cash-a"
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)
    finally:
        dialog.close()
        app.processEvents()


def test_reload_failure_invalidates_cached_safe_guards_models_and_actions_then_retries(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    profile, evidence = _review_profile(tmp_path)
    dialog = V2AccountBindingReview(profile, evidence.source_sha256)
    original = V2ProfileStore.accountless_binding_review_snapshot
    try:
        dialog.table.selectRow(0)
        assert dialog.assign_rows_button.isEnabled()

        def unavailable(*_args):
            raise sqlite3.OperationalError("synthetic guard snapshot refusal")

        monkeypatch.setattr(V2ProfileStore, "accountless_binding_review_snapshot", unavailable)
        dialog.reload_button.click()
        assert dialog._snapshot is None and not dialog.model.rows and dialog.account_combo.count() == 0
        assert "unavailable" in dialog.status.text().lower()
        assert not any(
            button.isEnabled()
            for button in (
                dialog.file_button,
                dialog.clear_file_button,
                dialog.assign_rows_button,
                dialog.clear_rows_button,
                dialog.correct_file_button,
                dialog.correct_rows_button,
                dialog.new_account_button,
            )
        )
        monkeypatch.setattr(V2ProfileStore, "accountless_binding_review_snapshot", original)
        dialog.reload_button.click()
        assert dialog._snapshot is not None and dialog.model.rowCount() == 2
        assert "No account assignments" in dialog.status.text() and dialog.file_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()

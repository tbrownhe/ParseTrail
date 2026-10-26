"""Binding choices distinguish account scope without changing ID-based decisions."""

from __future__ import annotations

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace

from .test_v2_binding_corrections_dialog import _profile


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    def unexpected(_parent, title, message):
        pytest.fail(f"{title}: {message}")

    monkeypatch.setattr(QMessageBox, "warning", unexpected)
    return QApplication.instance() or QApplication([])


def _scoped_profile(profile, mode):
    evidence, target, _key = _profile(profile, mode)
    with V2ProfileStore.open(profile) as store:
        for identity, scope in (("a", "account_total"), ("b", "cash_component")):
            store.update_financial_account(
                FinancialAccount(
                    identity,
                    "Shared account",
                    "asset",
                    "synthetic",
                    "12345678",
                    tracking_scope=scope,
                )
            )
    return evidence, target


def _labels(combo):
    total = combo.itemText(combo.findData("a"))
    component = combo.itemText(combo.findData("b"))
    assert total != component
    assert "Shared account" in total and "Shared account" in component
    assert "cash component" not in total and "cash component" in component
    for label in (total, component):
        assert "synthetic" in label and "asset" in label and "ending 5678" in label
        assert "12345678" not in label
    return total, component


def test_printed_source_choices_and_assignment_summary_distinguish_scope(tmp_path, app):
    from parsetrail.gui.v2_source_account_review import V2SourceAccountReview

    profile = tmp_path / "source-scope.db"
    evidence, _target = _scoped_profile(profile, "source")
    workspace = V2Workspace.open(
        profile, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    dialog = V2SourceAccountReview(workspace, evidence.source_sha256)
    try:
        total, component = _labels(dialog.account_combo)
        assert total in dialog.identities.currentItem().text()
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData("b"))
        assert dialog.account_combo.currentData() == "b" and dialog.assign_button.isEnabled()
        dialog.assign_button.click()
        assert component in dialog.identities.currentItem().text()
        with V2ProfileStore.open(profile, read_only=True) as store:
            binding = next(
                item
                for item in store.source_account_bindings(evidence.source_sha256)
                if item.source_identity == "Checking A"
            )
            assert binding.ledger_account_id == "b"
            assert store._active_consumed() == {}
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("mode", ["file", "rows"])
def test_accountless_choices_file_and_row_summaries_select_exact_scope_id(tmp_path, app, mode):
    from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview

    profile = tmp_path / f"{mode}-scope.db"
    evidence, _target = _scoped_profile(profile, mode)
    dialog = V2AccountBindingReview(profile, evidence.source_sha256)
    try:
        total, component = _labels(dialog.account_combo)
        assert dialog.model.data(dialog.model.index(0, 3)) == total
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData("b"))
        assert dialog.account_combo.currentData() == "b"
        if mode == "file":
            assert total in dialog.status.text()
            dialog.file_button.click()
            assert component in dialog.status.text()
        else:
            dialog.table.selectRow(0)
            dialog.assign_rows_button.click()
            assert dialog.model.data(dialog.model.index(1, 3)) == total
        assert dialog.model.data(dialog.model.index(0, 3)) == component
        with V2ProfileStore.open(profile, read_only=True) as store:
            bindings = store.account_bindings(evidence.source_sha256)
            assert bindings[0].ledger_account_id == "b"
            assert bindings[1].ledger_account_id == ("b" if mode == "file" else "a")
            assert store._active_consumed() == {}
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("mode", ["source", "file", "rows"])
def test_correction_scope_choices_preview_confirmation_and_history_remain_distinct(tmp_path, app, monkeypatch, mode):
    from parsetrail.gui.v2_binding_correction import V2BindingCorrection
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / f"correct-{mode}.db"
    evidence, target = _scoped_profile(profile, mode)
    questions = []

    def accept(_parent, _title, message):
        questions.append(message)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", accept)
    dialog = V2BindingCorrection(profile, target)
    try:
        total, component = _labels(dialog.destination)
        assert total in dialog.summary.text()
        assert all(dialog.rows_table.item(row, 3).text() == total for row in range(dialog.rows_table.rowCount()))
        dialog.destination.setCurrentIndex(dialog.destination.findData("b"))
        dialog.reason.setText("Review assignment to the cash component account with the same printed number")
        assert dialog.snapshot.destination_account_id == "b" and dialog.save_button.isEnabled()
        dialog.save_button.click()
        assert total in questions[0] and f"New: {component}" in questions[0]
        assert component in dialog.summary.text()
        assert total in dialog.history_table.item(0, 1).text()
        assert component in dialog.history_table.item(0, 2).text()
        with V2ProfileStore.open(profile, read_only=True) as store:
            history = store.binding_correction_history(evidence.source_sha256)
            assert history[0].prior_account_ids == ("a",)
            assert history[0].new_account_ids == ("b",)
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        dialog.close()
        app.processEvents()

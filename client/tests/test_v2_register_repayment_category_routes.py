"""Repayment navigation and category authoring never invent loan accounting."""

from __future__ import annotations

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_categories import V2CategoryDialog
from PySide6.QtWidgets import QApplication, QDialog

from .test_v2_liability_register_dialog import dialog, form, profile
from .test_v2_liability_register_dialog import source as source_fixture

source = source_fixture


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_printed_payment_routes_to_selected_counterpart_review_without_posting(tmp_path, source, monkeypatch):
    from parsetrail.gui import v2_transfer_review

    path = tmp_path / "payment.db"
    evidence, _bank = profile(path, source)
    view = dialog(path, evidence.source_sha256)
    opened = []

    class Transfer:
        def __init__(self, workspace, parent, *, focus_row_id):
            opened.append((workspace.profile_path, parent, focus_row_id))

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(v2_transfer_review, "V2TransferReview", Transfer)
    try:
        view.table.selectRow(1)
        view.reason.setText("Keep this draft note")
        assert view.purpose.currentData() == "repayment"
        assert view.action_button.isEnabled()
        assert not view.category.isEnabled() and not view.manage_categories_button.isEnabled()
        assert "Ready for purpose review" in view.status.text()
        assert "no income or expense" in view.status.text()
        before = path.read_bytes()
        view.action_button.click()
        assert opened == [(path, view, evidence.payload.accounts[0].rows[1].row_id)]
        assert path.read_bytes() == before
        assert view.reason.text() == "Keep this draft note"
        assert view.purpose.currentData() == "repayment"
        assert view._current().row_id == evidence.payload.accounts[0].rows[1].row_id
    finally:
        view.close()


@pytest.mark.parametrize(
    "kind,scope,bind",
    [
        ("asset", "account_total", True),
        ("liability", "principal_component", True),
        ("liability", "account_total", False),
    ],
)
def test_invalid_scope_or_unbound_payment_preserves_source_status(tmp_path, source, kind, scope, bind):
    path = tmp_path / "unsupported.db"
    evidence, _bank = profile(path, source, kind=kind, scope=scope, bind=bind)
    view = dialog(path, evidence.source_sha256)
    try:
        view.table.selectRow(1)
        assert view.purpose.currentData() is None
        assert view.purpose.findData("repayment") == -1
        assert view._current().status in view.status.text()
        assert not view.action_button.isEnabled()
    finally:
        view.close()


def test_manage_categories_creates_compatible_category_and_preserves_review_edits(tmp_path, source, monkeypatch):
    path = tmp_path / "category.db"
    evidence, _bank = profile(path, source)
    view = dialog(path, evidence.source_sha256)
    form(view)
    view.reason.setText("Authored interest review reason")
    previous_date = view.accounting_date.text()

    def add_category(manager):
        assert manager.add_kind.currentData() == "expense"
        manager.add_name.setText("Loan servicing costs")
        manager.add_button.click()
        return QDialog.Rejected

    monkeypatch.setattr(V2CategoryDialog, "exec", add_category)
    try:
        view.manage_categories_button.click()
        assert view.purpose.currentData() == "expense"
        assert view.reason.text() == "Authored interest review reason"
        assert view.accounting_date.text() == previous_date
        assert view._current().row_id == evidence.payload.accounts[0].rows[0].row_id
        assert "Loan servicing costs" in view.category.currentText()
        assert view.action_button.isEnabled()
        with V2ProfileStore.open(path, read_only=True) as store:
            assert any(category.name == "Loan servicing costs" for category in store.category_accounts())
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        view.close()


def test_category_cancel_does_not_change_profile_or_review_choice(tmp_path, source, monkeypatch):
    path = tmp_path / "cancel.db"
    evidence, _bank = profile(path, source)
    view = dialog(path, evidence.source_sha256)
    form(view)
    view.reason.setText("Retain reason on category cancel")
    old_category = view.category.currentData()
    before = path.read_bytes()
    monkeypatch.setattr(V2CategoryDialog, "exec", lambda _manager: QDialog.Rejected)
    try:
        view.manage_categories_button.click()
        assert path.read_bytes() == before
        assert view.category.currentData() == old_category and view.purpose.currentData() == "expense"
        assert view.reason.text() == "Retain reason on category cancel"
    finally:
        view.close()


def test_incompatible_new_category_is_not_selected_for_expense(tmp_path, source, monkeypatch):
    path = tmp_path / "incompatible.db"
    evidence, _bank = profile(path, source)
    view = dialog(path, evidence.source_sha256)
    form(view)
    old_category = view.category.currentData()

    def add_income(manager):
        manager.add_kind.setCurrentIndex(manager.add_kind.findData("income"))
        manager.add_name.setText("A separate income category")
        manager.add_button.click()
        return QDialog.Rejected

    monkeypatch.setattr(V2CategoryDialog, "exec", add_income)
    try:
        view.manage_categories_button.click()
        assert view.category.currentData() == old_category
        assert all("A separate income category" not in view.category.itemText(i) for i in range(view.category.count()))
    finally:
        view.close()


def test_shared_card_category_shortcut_preserves_explicit_corrected_date(tmp_path, monkeypatch):
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview

    from .test_v2_card_purchase_review import _chase_profile

    path = tmp_path / "card-category.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        section = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    view = V2CardPurchaseReview(workspace, evidence.source_sha256)
    view.table.selectRow(0)
    view.purpose.setCurrentIndex(view.purpose.findData("expense"))
    view.category.setCurrentIndex(view.category.findData("expense:food"))
    view.accounting_date.setText("2026-03-14")
    view.reason.setText("Keep explicitly corrected card date")

    def add_category(manager):
        manager.add_name.setText("Parking")
        manager.add_button.click()
        return QDialog.Rejected

    monkeypatch.setattr(V2CategoryDialog, "exec", add_category)
    try:
        view.manage_categories_button.click()
        assert view.accounting_date.text() == "2026-03-14"
        assert view.reason.text() == "Keep explicitly corrected card date"
        assert view.purpose.currentData() == "expense" and "Parking" in view.category.currentText()
        assert view.action_button.isEnabled() and not workspace.preferences().allow_assumed_posting_dates
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        view.close()


def test_register_confirmation_keeps_reviewed_basis_when_nested_events_refresh_view(tmp_path, source, monkeypatch):
    from parsetrail.core.v2_profile_store import FinancialAccount
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "nested-refresh.db"
    evidence, _bank = profile(path, source)
    view = dialog(path, evidence.source_sha256)
    form(view)
    warnings = []

    def concurrent_refresh(*_args):
        with V2ProfileStore.open(path) as store:
            store.update_financial_account(
                FinancialAccount("register", "Changed while confirming", "liability", "synthetic")
            )
        view.refresh(selected_row_id=evidence.payload.accounts[0].rows[0].row_id)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", concurrent_refresh)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(True))
    try:
        view.action_button.click()
        assert warnings
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        view.close()


def test_repayment_posted_elsewhere_shows_history_and_no_pending_category(tmp_path, source, monkeypatch):
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui import v2_transfer_review
    from PySide6.QtCore import Qt

    path = tmp_path / "reviewed-elsewhere.db"
    evidence, bank = profile(path, source)
    ws = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    payment = evidence.payload.accounts[0].rows[1]
    with V2ProfileStore.open(path) as store:
        store.post_reviewed_transfer(
            bank, payment.row_id, preferences=ws.preferences(), reason="Confirmed whole-liability repayment"
        )
    view = dialog(path, evidence.source_sha256)
    focused = []

    class Transfer:
        def __init__(self, _workspace, _parent, *, focus_row_id):
            focused.append(focus_row_id)

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(v2_transfer_review, "V2TransferReview", Transfer)
    try:
        view.table.selectRow(1)
        assert view.model.data(view.model.index(1, 6), Qt.DisplayRole) == "Reviewed elsewhere"
        assert view.purpose.currentData() == "external_history" and not view.purpose.isEnabled()
        assert not view.category.isEnabled() and not view.manage_categories_button.isEnabled()
        assert "no further categorization" in view.status.text()
        assert view.action_button.text() == "Inspect transfer / repayment history…" and view.action_button.isEnabled()
        before = path.read_bytes()
        view.action_button.click()
        assert focused == [payment.row_id] and path.read_bytes() == before
    finally:
        view.close()

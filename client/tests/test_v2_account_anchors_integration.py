"""Workspace and positions keep authored values and closed books distinct."""

from datetime import date

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _loan(profile):
    with V2ProfileStore.create(profile) as store:
        store.add_financial_account(
            FinancialAccount("loan", "New loan", "liability", "synthetic", tracking_scope="principal_component")
        )
        frame = store.account_anchor_snapshot("loan")
        opening = store.post_reviewed_manual_opening(
            "loan",
            amount_minor=-10000,
            cutoff_date=date(2026, 1, 1),
            tracking_scope="principal_component",
            reference="Reviewed missing opening information",
            reason="Initial loan principal",
            expected_decision_version=None,
            expected_basis_sha256=frame.basis_sha256,
        )
        frame = store.account_anchor_snapshot("loan")
        store.record_reviewed_dated_value(
            "loan",
            amount_minor=0,
            value_date=date(2026, 1, 31),
            tracking_scope="principal_component",
            reference="Reviewed final value without a final statement",
            reason="Record value without assuming settlement",
            expected_basis_sha256=frame.basis_sha256,
        )
        frame = store.account_anchor_snapshot("loan")
        store.record_account_lifecycle(
            "loan",
            state="closed",
            effective_date=date(2026, 1, 31),
            reason="Stopped tracking after closure",
            expected_version=None,
            expected_basis_sha256=frame.basis_sha256,
        )
    return opening


def test_financial_dialog_chooses_kind_appropriate_scope_and_preserves_locked_scope(app):
    from parsetrail.gui.v2_workspace_window import V2FinancialAccountDialog

    dialog = V2FinancialAccountDialog()
    try:
        assert dialog.scope.currentData() == "account_total"
        assert dialog.scope.findData("cash_component") >= 0 and dialog.scope.findData("principal_component") == -1
        dialog.kind.setCurrentIndex(dialog.kind.findData("liability"))
        assert dialog.scope.findData("cash_component") == -1 and dialog.scope.findData("principal_component") >= 0
        dialog.scope.setCurrentIndex(dialog.scope.findData("principal_component"))
        dialog.name.setText("New loan")
        dialog.institution.setText("synthetic")
        assert dialog.account().tracking_scope == "principal_component"
    finally:
        dialog.close()
    existing = FinancialAccount("loan", "Loan", "liability", "synthetic", "11112222", "principal_component")
    locked = V2FinancialAccountDialog(existing=existing, scope_locked=True)
    try:
        assert not locked.kind.isEnabled() and not locked.scope.isEnabled()
        assert locked.account() == existing
    finally:
        locked.close()
        app.processEvents()


def test_positions_show_manual_zero_and_closed_residual_without_overriding_books(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_account_anchors import V2AccountAnchors
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate

    profile = tmp_path / "loan.db"
    opening = _loan(profile)
    before = profile.read_bytes()
    seen = []
    monkeypatch.setattr(
        V2AccountAnchors, "exec", lambda dialog: seen.append((dialog.profile, dialog.account.currentData())) or 0
    )
    dialog = V2ReviewedReportsDialog(profile)
    try:
        dialog.tabs.setCurrentIndex(4)
        dialog.as_of.setDate(QDate(2026, 1, 31))
        model = dialog.positions_model

        def cell(column):
            return model.data(model.index(0, column))

        assert cell(2) == cell(3) == "$100.00"
        assert cell(10) == "Loan principal" and cell(11) == "Reviewed manual"
        assert "$0.00" in cell(12) and "2026-01-31" in cell(12)
        assert "closed" in cell(13)
        assert "does not replace the books" in dialog.position_details.text()
        assert "Recorded journal residual at 2026-01-31: $100.00" in dialog.position_details.text()
        assert "does not zero journals or prove settlement" in dialog.position_details.text()
        assert dialog.account_anchor_button.isEnabled()
        dialog.account_anchor_button.click()
        assert seen == [(profile, "loan")]
        assert profile.read_bytes() == before
        dialog.as_of.setDate(QDate(2026, 1, 1))
        assert "None through as-of" in cell(12) and "No effective closure" in cell(13)
        with V2ProfileStore.open(profile) as store:
            store.withdraw_reviewed_opening(
                "loan", expected_decision_version=opening.version, reason="Withdraw unsupported opening"
            )
        changed = profile.read_bytes()
        dialog.as_of.setDate(QDate(2026, 1, 31))
        assert cell(2) == "$0.00" and cell(3) == "Unknown" and cell(4) == "Withdrawn — unknown"
        assert "$0.00" in cell(12) and "opening-based residual is unknown" in dialog.position_details.text()
        assert profile.read_bytes() == changed
    finally:
        dialog.close()
        app.processEvents()


def test_accounts_menu_opens_authored_review_for_current_profile_and_failures_disable_position_action(
    tmp_path, app, monkeypatch
):
    from parsetrail.gui.v2_account_anchors import V2AccountAnchors
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    profile = tmp_path / "profile.db"
    _loan(profile)
    workspace = V2Workspace.open(
        profile, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    seen = []
    monkeypatch.setattr(V2AccountAnchors, "exec", lambda dialog: seen.append(dialog.profile) or 0)
    window = V2WorkspaceWindow(workspace)
    reports = V2ReviewedReportsDialog(profile)
    try:
        window.account_anchors_action.trigger()
        assert seen == [profile]
        assert reports.account_anchor_button.isEnabled()

        def unavailable(*_args, **_kwargs):
            raise OSError("synthetic unavailable profile")

        monkeypatch.setattr(V2ProfileStore, "account_positions", unavailable)
        reports._refresh_positions()
        assert not reports.account_anchor_button.isEnabled() and reports.positions_model.rowCount() == 0
        assert reports.position_details.toolTip() == "" and "unavailable" in reports.position_details.text()
    finally:
        reports.close()
        window.close()
        app.processEvents()


def test_edit_account_choice_shows_component_scope_and_refuses_unavailable_details(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    profile = tmp_path / "scope-identities.db"
    with V2ProfileStore.create(profile) as store:
        for account_id, scope in (("whole", "account_total"), ("cash", "cash_component")):
            store.add_financial_account(FinancialAccount(account_id, "HSA", "asset", "synthetic", "11112222", scope))
    workspace = V2Workspace.open(
        profile, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    choices, warnings = [], []

    def cancel_selection(_parent, _title, _label, items, *_args):
        choices.extend(items)
        return "", False

    monkeypatch.setattr(QInputDialog, "getItem", cancel_selection)
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, title, message: warnings.append((title, message)))
    window = V2WorkspaceWindow(workspace)
    try:
        before = profile.read_bytes()
        window._edit_account()
        assert len(set(choices)) == 2
        assert any("cash component" in label for label in choices)
        assert all("ending 2222" in label for label in choices)
        assert profile.read_bytes() == before

        def unavailable(_store):
            raise OSError("synthetic account metadata unavailable")

        monkeypatch.setattr(V2ProfileStore, "financial_accounts", unavailable)
        window._edit_account()
        assert warnings == [("Account details are unavailable", "synthetic account metadata unavailable")]
        assert profile.read_bytes() == before
    finally:
        window.close()
        app.processEvents()

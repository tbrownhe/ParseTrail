"""Same-obligation confirmation is explicit, conflict-aware and lifetime-safe."""

from dataclasses import replace
from datetime import date
from threading import Event

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_account_anchors import V2AccountAnchors
from parsetrail.gui.v2_account_consolidation import V2AccountConsolidation
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThread
from PySide6.QtWidgets import QMessageBox
from shiboken6 import isValid

from .qt_journey_helpers import JourneyArtifacts, ModalSteps, choose_combo
from .test_v2_account_consolidation import _confirm, _profile
from .test_v2_document_browser import wait_for_inventory


def settled(qtbot, dialog):
    qtbot.waitUntil(lambda: not dialog.jobs.pending, timeout=20000)


def dispose(qtbot, view):
    destroyed = []
    gui = QThread.currentThread()
    view.destroyed.connect(lambda: destroyed.append(QThread.currentThread() == gui))
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qtbot.waitUntil(lambda: not isValid(view))
    assert destroyed == [True]


@pytest.mark.parametrize("size", [(1050, 700), (1100, 650)])
def test_accounts_entrypoint_previews_confirms_and_selects_kept_record(qtbot, qapp, tmp_path, journey_artifacts, size):
    path = tmp_path / "continuing-card.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        for account in store.financial_accounts():
            store.update_financial_account(
                replace(
                    account,
                    name=(
                        "Everyday card for household spending and travel"
                        if account.id == "kept"
                        else "Previous replacement card number for the same household obligation"
                    ),
                )
            )
        before = store.connection.execute("SELECT * FROM JournalEntries ORDER BY key").fetchall()
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    wait_for_inventory(window)
    window.navigation.setCurrentRow(window.ACCOUNTS)
    for index in range(window.accounts_list.count()):
        if window.accounts_list.item(index).data(Qt.UserRole) == "kept":
            window.accounts_list.setCurrentRow(index)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    modals = ModalSteps(qtbot)

    def confirm(dialog):
        settled(qtbot, dialog)
        assert dialog.keep.currentData() == "kept"
        choose_combo(qtbot, dialog.absorb, "old")
        settled(qtbot, dialog)
        assert dialog.snapshot is not None and not dialog.snapshot.blockers
        assert "2 linked documents" in dialog.preview.text()
        assert "ending 1234" in dialog.preview.text() and "ending 5678" in dialog.preview.text()
        assert "1234567890121234" not in dialog.preview.text()
        assert "Cannot be undone" in dialog.irreversible.text()
        assert not dialog.action_button.isEnabled()
        assert dialog.same_account.property("formState") == "required"
        artifacts.capture("01-same-obligation-preview", dialog)
        dialog.same_account.setFocus()
        qtbot.keyClick(dialog.same_account, Qt.Key_Space)
        assert dialog.action_button.isEnabled() and dialog.action_button.property("formState") == "ready"
        qtbot.mouseClick(dialog.action_button, Qt.LeftButton)
        settled(qtbot, dialog)
        assert dialog.consolidation_result is not None
        assert dialog.action_button.property("formState") == "neutral"
        artifacts.capture("02-consolidated-history-retained", dialog)
        qtbot.mouseClick(dialog.close_button, Qt.LeftButton)

    modals.arm((V2AccountConsolidation, confirm))
    qtbot.mouseClick(window.consolidate_accounts_button, Qt.LeftButton)
    modals.finish()
    wait_for_inventory(window)
    assert window.accounts_list.count() == 1
    assert window.accounts_list.currentItem().data(Qt.UserRole) == "kept"
    assert not window.consolidate_accounts_button.isEnabled()
    assert all(summary.associated_account_ids == ("kept",) for summary in window._document_summaries.values())
    artifacts.capture("03-kept-account-selected", window)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.connection.execute("SELECT * FROM JournalEntries ORDER BY key").fetchall() == before
        assert len(store.account_positions(as_of=date(2026, 4, 30)).accounts) == 1
    dispose(qtbot, window)


def test_duplicate_openings_block_confirmation_and_show_recovery(qtbot, qapp, tmp_path, journey_artifacts):
    path = tmp_path / "openings.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        for account in ("old", "kept"):
            frame = store.account_anchor_snapshot(account)
            store.post_reviewed_manual_opening(
                account,
                amount_minor=-10000,
                cutoff_date=date(2026, 1, 1),
                tracking_scope="account_total",
                reference="Earlier reviewed statement",
                reason="Initial Review",
                expected_basis_sha256=frame.basis_sha256,
                expected_decision_version=None,
            )
    dialog = V2AccountConsolidation(path, "kept")
    qtbot.addWidget(dialog)
    dialog.show()
    settled(qtbot, dialog)
    choose_combo(qtbot, dialog.absorb, "old")
    settled(qtbot, dialog)
    assert "opening" in dialog.blockers.text().lower()
    assert "Accounts → Reviewed openings" in dialog.blockers.text()
    assert not dialog.same_account.isEnabled() and not dialog.action_button.isEnabled()
    JourneyArtifacts(journey_artifacts, qapp, (900, 650)).capture("04-resolve-duplicate-openings", dialog)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert not store.account_consolidation_history()
    dispose(qtbot, dialog)


def test_combined_history_and_old_member_value_withdrawal_remain_available(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts
):
    path = tmp_path / "old-value.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        frame = store.account_anchor_snapshot("old")
        value = store.record_reviewed_dated_value(
            "old",
            amount_minor=-11000,
            value_date=date(2026, 4, 30),
            tracking_scope="account_total",
            reference="Old number source reviewed",
            reason="Initial Review",
            expected_basis_sha256=frame.basis_sha256,
        )
        _confirm(store)
    view = V2AccountAnchors(path, "old", initial_tab="values")
    try:
        view.show()
        assert view.account.currentData() == "kept" and view.account.count() == 1
        assert view.snapshot.latest_dated_value.value_id == value.value_id
        view.tabs.setCurrentWidget(view.consolidation_history)
        assert "Combined Old into Kept" in view.consolidation_history.toPlainText()
        assert "ending 1234" in view.consolidation_history.toPlainText()
        JourneyArtifacts(journey_artifacts, qapp, (1080, 790)).capture("05-combined-records-and-numbers", view)
        view.tabs.setCurrentIndex(1)
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        view.value_withdraw_reason.setText("Withdraw old-number estimate after consolidation")
        assert view.value_withdraw.isEnabled()
        qtbot.mouseClick(view.value_withdraw, Qt.LeftButton)
        assert view.snapshot.latest_dated_value is None
        with V2ProfileStore.open(path, read_only=True) as store:
            row = next(
                item for item in store.account_anchor_snapshot("kept").dated_values if item.value_id == value.value_id
            )
            assert row.state == "withdrawn" and row.account_id == "old"
    finally:
        dispose(qtbot, view)


def test_changed_basis_requires_reload_and_confirmed_close_waits(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "stale.db"
    _profile(path)
    dialog = V2AccountConsolidation(path, "kept")
    qtbot.addWidget(dialog)
    dialog.show()
    settled(qtbot, dialog)
    choose_combo(qtbot, dialog.absorb, "old")
    settled(qtbot, dialog)
    with V2ProfileStore.open(path) as store:
        account = next(item for item in store.financial_accounts() if item.id == "old")
        store.update_financial_account(replace(account, name="Renamed after preview"))
    dialog.same_account.setChecked(True)
    qtbot.mouseClick(dialog.action_button, Qt.LeftButton)
    settled(qtbot, dialog)
    assert dialog.consolidation_result is None and "Reload" in dialog.status.text()
    dialog.reload()
    settled(qtbot, dialog)
    assert dialog.snapshot is not None and not dialog.same_account.isChecked()
    entered, release = Event(), Event()
    original = V2ProfileStore.consolidate_accounts

    def delayed(store, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(store, *args, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "consolidate_accounts", delayed)
    dialog.same_account.setChecked(True)
    qtbot.mouseClick(dialog.action_button, Qt.LeftButton)
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
        dialog.close()
        assert dialog.isVisible() and dialog.jobs.writing
    finally:
        release.set()
    settled(qtbot, dialog)
    assert not dialog.isVisible() and dialog.consolidation_result is not None
    with V2ProfileStore.open(path, read_only=True) as store:
        assert len(store.active_financial_accounts()) == 1
    dispose(qtbot, dialog)

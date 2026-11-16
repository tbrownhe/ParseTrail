"""Transfer designation is a saved no-money choice; matching remains explicit."""

from datetime import date

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
from parsetrail.gui.v2_transfer_review import V2TransferReview
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit

from .qt_journey_helpers import JourneyArtifacts, ModalSteps, choose_combo, enter_text
from .test_v2_card_purchase_review import _chase_profile
from .test_v2_multirow_review import select
from .test_v2_review_cues import open_review
from .test_v2_transfer_review_async import wait_for_transfers
from .test_v2_workspace_window import DEFINITION, _workspace
from .v2_institution_helpers import add_test_financial_account


@pytest.fixture
def transfer_workspace(tmp_path):
    workspace = _workspace(tmp_path)
    raw = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"10/01/2026,Checking A,Move to savings,-$25.00,$975.00\n"
        b"10/02/2026,Checking A,Groceries,-$4.00,$971.00\n"
        b"10/01/2026,Savings B,From checking,$25.00,$125.00\n"
    )
    evidence = build_source_evidence(raw, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(raw, DEFINITION, evidence, suffix=".csv")
        add_test_financial_account(store, FinancialAccount("checking", "Everyday checking", "asset", "synthetic"))
        add_test_financial_account(store, FinancialAccount("savings", "Rainy-day savings", "asset", "synthetic"))
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "checking")
        store.bind_source_account(evidence.source_sha256, "Savings B", "opaque", "savings")
        store.add_category_account("expense:food", "Food", "expense")
    ids = {row.description.text: row.row_id for row in evidence.payload.rows}
    return workspace, evidence, ids


def settle(qtbot, window, view):
    qtbot.waitUntil(
        lambda: not view.review_pending and not window.inventory_pending and not window.profile_jobs.pending,
        timeout=20000,
    )


def confirm_set(qtbot, view, *, accept=True, inspect=None):
    modals = ModalSteps(qtbot)

    def act(dialog):
        if inspect:
            inspect(dialog)
        box = dialog.findChild(QDialogButtonBox)
        button = (
            next(button for button in box.buttons() if button.text().startswith("Confirm and"))
            if accept
            else box.button(QDialogButtonBox.Cancel)
        )
        qtbot.mouseClick(button, Qt.LeftButton)

    modals.arm((QDialog, act))
    qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending, timeout=20000)


def mark(store, row_id, reason="Initial Review"):
    snapshot = store.pending_transfer_snapshot()
    prior = next((row for row in snapshot.rows if row.row_id == row_id), None)
    return store.set_pending_transfer(
        row_id,
        expected_basis_sha256=snapshot.basis_sha256,
        expected_revision_id=prior.revision_id if prior else None,
        reason=reason,
    )


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)])
def test_mixed_review_set_saves_intent_without_opening_match_and_resets_initial_reason(
    qtbot, qapp, transfer_workspace, journey_artifacts, monkeypatch, size
):
    workspace, evidence, ids = transfer_workspace
    window, view = open_review(qtbot, workspace, size=size)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    opened = []
    monkeypatch.setattr(
        V2TransferReview, "exec", lambda dialog: opened.append(dialog.require_pending_intents) or QDialog.Rejected
    )
    assert view.batch.reason.text() == "Initial Review" and not view.has_unsaved_draft
    select(qtbot, view, "Move to savings")
    choose_combo(qtbot, view.purpose, "transfer")
    assert not view.category.isVisible() and view.batch.stage_button.isEnabled() and not opened
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    select(qtbot, view, "Groceries")
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    enter_text(qtbot, view.batch.reason, "Reviewed groceries and the separate transfer designation")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert len(view.batch.staged) == 2 and not opened
    artifacts.capture("01-mixed-category-and-transfer-review-set", window)

    def inspect(dialog):
        text = dialog.findChild(QPlainTextEdit).toPlainText()
        assert text.count("Reviewed groceries and the separate transfer designation") == 1
        assert "No journal entry" in text and "reviewed expense change: $4.00" in text
        artifacts.capture("02-explicit-mixed-effects-before-saving", dialog)

    confirm_set(qtbot, view, accept=False, inspect=inspect)
    assert len(view.batch.staged) == 2 and not opened
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert not store.pending_transfer_snapshot().rows
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    confirm_set(qtbot, view)
    settle(qtbot, window, view)
    assert view.batch.reason.text() == "Initial Review" and not view.batch.staged and not opened
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        states = store.pending_transfer_snapshot().rows
        assert len(states) == 1 and states[0].row_id == ids["Move to savings"] and states[0].status == "waiting"
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 400
        )
        assert store.load_import(evidence.source_sha256).evidence == evidence
    select(qtbot, view, "From checking")
    choose_combo(qtbot, view.purpose, "transfer")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    confirm_set(qtbot, view)
    settle(qtbot, window, view)
    select(qtbot, view, "Move to savings")
    assert view.purpose.currentData() == "transfer" and view.saved_review_note.isVisible()
    assert not view.reason.text() and not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    assert view.match_transfer_button.isEnabled() and not opened
    artifacts.capture("03-saved-transfer-match-is-optional-and-reason-is-blank", window)
    qtbot.mouseClick(view.match_transfer_button, Qt.LeftButton)
    settle(qtbot, window, view)
    assert opened == [True]
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)
        assert all(state.status == "match_available" for state in store.pending_transfer_snapshot().rows)


def test_saved_intent_reclassification_uses_fresh_reason_and_keeps_unrelated_stages(
    qtbot, qapp, transfer_workspace, journey_artifacts
):
    workspace, _evidence, ids = transfer_workspace
    with V2ProfileStore.open(workspace.profile_path) as store:
        mark(store, ids["Move to savings"])
    window, view = open_review(qtbot, workspace)
    select(qtbot, view, "Groceries")
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    staged = dict(view.batch.staged)
    select(qtbot, view, "Move to savings")
    assert not view.reason.text() and not view.action_button.isEnabled()
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    assert not view.action_button.isEnabled()  # Initial Review in the shared field is no authorization.
    enter_text(qtbot, view.reason, "This is a purchase, not a transfer")
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-reclassify-with-new-reason-and-unrelated-set-retained", window
    )
    modals = ModalSteps(qtbot)

    def cancel(dialog):
        text = dialog.findChild(QPlainTextEdit).toPlainText()
        assert "Reason for correction: This is a purchase, not a transfer" in text
        assert "replaces the saved transfer designation" in text
        qtbot.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel), Qt.LeftButton)

    modals.arm((QDialog, cancel))
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    modals.finish()
    assert view.reason.text() == "This is a purchase, not a transfer" and view.batch.staged == staged
    modals.arm(
        (
            QDialog,
            lambda dialog: qtbot.mouseClick(
                next(
                    b for b in dialog.findChild(QDialogButtonBox).buttons() if b.text().startswith("Confirm and post")
                ),
                Qt.LeftButton,
            ),
        )
    )
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    modals.finish()
    settle(qtbot, window, view)
    assert view.batch.staged == staged and view.batch.reason.text() == "Initial Review"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        state = next(
            state for state in store.pending_transfer_snapshot().rows if state.row_id == ids["Move to savings"]
        )
        assert state.status == "withdrawn"
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)


def test_withdraw_saved_intent_requires_new_input_and_retains_cancelled_reason(
    qtbot, qapp, transfer_workspace, journey_artifacts
):
    workspace, _evidence, ids = transfer_workspace
    with V2ProfileStore.open(workspace.profile_path) as store:
        mark(store, ids["Move to savings"])
    window, view = open_review(qtbot, workspace)
    select(qtbot, view, "Move to savings")
    assert view.saved_review_note.toPlainText() == "Initial Review"
    assert view.reason.text() == "" and not view.withdraw_button.isEnabled()
    assert view.batch.reason.text() == "Initial Review" and not view.has_unsaved_draft
    enter_text(qtbot, view.reason, "Initial Review")  # Deliberate fresh typing may repeat old words.
    modals = ModalSteps(qtbot)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    modals.arm((QMessageBox, lambda dialog: qtbot.mouseClick(dialog.button(QMessageBox.No), Qt.LeftButton)))
    qtbot.mouseClick(view.withdraw_button, Qt.LeftButton)
    modals.finish()
    assert view.reason.text() == "Initial Review"
    artifacts.capture("01-cancelled-withdrawal-keeps-fresh-independent-reason", window)
    modals.arm((QMessageBox, lambda dialog: qtbot.mouseClick(dialog.button(QMessageBox.Yes), Qt.LeftButton)))
    qtbot.mouseClick(view.withdraw_button, Qt.LeftButton)
    modals.finish()
    settle(qtbot, window, view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        state = next(
            state for state in store.pending_transfer_snapshot().rows if state.row_id == ids["Move to savings"]
        )
        assert state.status == "withdrawn" and state.revision_id > 1
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    assert view.batch.reason.text() == "Initial Review" and not view.reason.text()


def test_stale_intent_correction_refuses_then_reloads_with_blank_reason(
    qtbot, qapp, transfer_workspace, journey_artifacts, monkeypatch
):
    workspace, _evidence, ids = transfer_workspace
    with V2ProfileStore.open(workspace.profile_path) as store:
        mark(store, ids["Move to savings"])
    window, view = open_review(qtbot, workspace)
    select(qtbot, view, "Move to savings")
    enter_text(qtbot, view.reason, "Explanation from the old revision")
    with V2ProfileStore.open(workspace.profile_path) as store:
        latest = mark(store, ids["Move to savings"], "New decision from another view")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    settle(qtbot, window, view)
    assert warnings and not view.reason.text()
    assert view.saved_review_note.toPlainText() == "New decision from another view"
    assert not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-stale-correction-refused-new-saved-note-needs-new-reason", window
    )
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        snapshot = store.pending_transfer_snapshot()
        assert len(snapshot.history) == 2 and snapshot.rows[0].revision_id == latest.revision_id
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_card_intent_needs_no_assumed_date_permission(qtbot, qapp, tmp_path, journey_artifacts):
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        source = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, source.source_identity, source.source_identity_form, "card")
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    view = V2CardPurchaseReview(workspace, evidence.source_sha256)
    qtbot.addWidget(view, before_close_func=lambda widget: widget.request_cancel())
    view.resize(1050, 700)
    view.show()
    qtbot.waitUntil(lambda: not view.review_pending, timeout=20000)
    select(qtbot, view, "PAYMENT")
    choose_combo(qtbot, view.purpose, "transfer")
    assert not view.accounting_date.isVisible() and not view.category.isVisible()
    assert view.batch.stage_button.isEnabled() and not workspace.preferences().allow_assumed_posting_dates
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    payment = view._current()
    number = next(index for index, row in enumerate(view.model.rows) if row.row_id == payment.row_id)
    assert (
        view.model.data(view.model.index(number, view.model.columnCount() - 2)) == "Transfer designation · not posted"
    )
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-card-payment-designation-without-posting-date-permission", view
    )
    confirm_set(qtbot, view)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert len(store.pending_transfer_snapshot().rows) == 1
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    assert not workspace.preferences().allow_assumed_posting_dates


def test_marked_only_matching_waits_for_both_sides_and_explicit_post(
    qtbot, qapp, transfer_workspace, journey_artifacts, monkeypatch
):
    workspace, _evidence, ids = transfer_workspace
    with V2ProfileStore.open(workspace.profile_path) as store:
        mark(store, ids["Move to savings"])
    view = V2TransferReview(workspace, require_pending_intents=True)
    qtbot.addWidget(view)
    view.show()
    wait_for_transfers(view)
    assert not view.candidates
    assert not view.tabs.isTabVisible(view.tabs.indexOf(view.events_page))
    with V2ProfileStore.open(workspace.profile_path) as store:
        mark(store, ids["From checking"])
    view.refresh()
    wait_for_transfers(view)
    assert len(view.candidates) == 1 and view._snapshot.require_pending_intents
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    view.tabs.setCurrentWidget(view.matches_page)
    view.table.selectRow(0)
    assert view.confirm.isEnabled()
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-marked-only-counterpart-requires-explicit-confirmation", view
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    qtbot.mouseClick(view.confirm, Qt.LeftButton)
    wait_for_transfers(view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)
        assert all(state.status == "consumed" for state in store.pending_transfer_snapshot().rows)
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 0
        )

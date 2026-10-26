"""Transfer UI decisions keep suggestion review separate from whole-event books."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace

from .test_v2_transfers import BANK_DEFINITION, _profile


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    def unexpected(_parent, title, message):
        pytest.fail(f"{title}: {message}")

    monkeypatch.setattr(QMessageBox, "warning", unexpected)
    return QApplication.instance() or QApplication([])


def _dialog(profile):
    from parsetrail.gui.v2_transfer_review import V2TransferReview

    workspace = V2Workspace.open(
        profile, profile.parent / "catalog", trusted_keys={}, preferences_path=profile.parent / "preferences.json"
    )
    return V2TransferReview(workspace)


def _post(profile, outgoing, incoming):
    with V2ProfileStore.open(profile) as store:
        return store.post_reviewed_transfer(
            outgoing, incoming, preferences=V2Preferences(), reason="Confirmed original payment"
        )


def test_dismiss_and_reopen_are_durable_and_never_allocate_money(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "suggestion.db"
    _profile(profile, bank_date="01/03/2026")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = _dialog(profile)
    try:
        dialog.table.selectRow(0)
        assert not dialog.dismiss.isEnabled()
        dialog.note.setText("Not the same economic event")
        assert dialog.dismiss.isEnabled()
        dialog.dismiss.click()
        assert dialog.table.rowCount() == 0
        assert dialog.review_table.rowCount() == 1
        assert dialog.pair_reviews[0].decision == "dismiss"
        dialog.review_table.selectRow(0)
        assert not dialog.reopen.isEnabled()
        dialog.reopen_reason.setText("Sources inspected again")
        assert dialog.reopen.isEnabled()
        dialog.reopen.click()
        assert dialog.table.rowCount() == 1
        assert dialog.review_table.rowCount() == 2
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store._active_consumed() == {}
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0] == 0
    finally:
        dialog.close()
        app.processEvents()
    reopened = _dialog(profile)
    try:
        assert reopened.table.rowCount() == 1
        assert reopened.review_table.rowCount() == 2
        old_dismissal = next(
            index for index, review in enumerate(reopened.pair_reviews) if review.decision == "dismiss"
        )
        reopened.review_table.selectRow(old_dismissal)
        reopened.reopen_reason.setText("Older history must not be reopened again")
        assert not reopened.reopen.isEnabled()
    finally:
        reopened.close()
        app.processEvents()


@pytest.mark.parametrize("bank_date,legs", [("01/05/2026", 1), ("01/03/2026", 2)])
def test_whole_event_withdrawal_keeps_dates_and_releases_all_rows(tmp_path, app, monkeypatch, bank_date, legs):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "withdraw.db"
    outgoing, incoming = _profile(profile, bank_date=bank_date)
    event_id = _post(profile, outgoing, incoming)
    questions = []

    def confirm(_parent, _title, message):
        questions.append(message)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = _dialog(profile)
    try:
        dialog.tabs.setCurrentIndex(1)
        dialog.event_table.selectRow(0)
        assert dialog.selected_event.event_id == event_id
        assert not dialog.withdraw.isEnabled()
        dialog.correction_reason.setText("These source movements were not an owned transfer")
        assert dialog.withdraw.isEnabled()
        dialog.replacement.setCurrentIndex(1)
        assert not dialog.replace.isEnabled()
        dialog.withdraw.click()
        assert f"All {legs} journal leg(s)" in questions[0]
        assert "amount owed change $20.00" in questions[0]
        assert "2026-01-05" in questions[0]
        assert dialog.events[0].status == "cancelled"
        assert not dialog.withdraw.isEnabled()
        assert not dialog.replace.isEnabled()
        assert dialog.table.rowCount() == 1
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store._active_consumed() == {}
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0] == legs * 2
            for kind in ("expense", "income"):
                assert (
                    store.reviewed_category_summary(kind=kind, start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
                    == 0
                )
    finally:
        dialog.close()
        app.processEvents()


def test_replacement_can_share_outgoing_row_and_change_destination_atomically(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "replace.db"
    outgoing, incoming = _profile(profile, bank_date="01/03/2026")
    event_id = _post(profile, outgoing, incoming)
    source = b"Date,Account,Description,Amount,ReportedBalance\n01/04/2026,Savings B,Owned transfer,$20.00,$1020.00\n"
    evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.open(profile) as store:
        store.add_financial_account(FinancialAccount("savings", "Savings", "asset", "synthetic"))
        store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Savings B", "opaque", "savings")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = _dialog(profile)
    try:
        dialog.event_table.selectRow(0)
        dialog.correction_reason.setText("Correct owned destination after inspecting both sources")
        assert not dialog.replace.isEnabled()
        replacement = next(
            index for index, pair in enumerate(dialog.replacements) if pair.incoming.account_id == "savings"
        )
        dialog.replacement.setCurrentIndex(dialog.replacement.findData(replacement))
        assert dialog.replace.isEnabled()
        assert "asset value change $20.00" in dialog.replacement_details.text()
        dialog.replace.click()
        assert len(dialog.events) == 2
        original = next(event for event in dialog.events if event.event_id == event_id)
        assert original.status == "replaced" and original.replacement_event_id
        replacement_event = next(event for event in dialog.events if event.status == "active")
        assert replacement_event.pair.incoming.account_id == "savings"
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store._active_consumed() == {outgoing: -2000, evidence.payload.rows[0].row_id: 2000}
            assert incoming not in store._active_consumed()
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("action", ["post", "dismiss", "withdraw", "replace", "reopen"])
def test_every_confirmation_cancel_leaves_profile_unchanged(tmp_path, app, monkeypatch, action):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "cancel.db"
    outgoing, incoming = _profile(profile, bank_date="01/03/2026")
    if action in {"withdraw", "replace"}:
        _post(profile, outgoing, incoming)
        if action == "replace":
            source = b"Date,Account,Description,Amount,ReportedBalance\n01/04/2026,Savings B,Owned transfer,$20.00,$1020.00\n"
            evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
            with V2ProfileStore.open(profile) as store:
                store.add_financial_account(FinancialAccount("savings", "Savings", "asset", "synthetic"))
                store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
                store.bind_source_account(evidence.source_sha256, "Savings B", "opaque", "savings")
    elif action == "reopen":
        with V2ProfileStore.open(profile) as store:
            snapshot = store.transfer_review_snapshot(preferences=V2Preferences())
            store.record_transfer_pair_review(
                outgoing,
                incoming,
                decision="dismiss",
                expected_basis_sha256=snapshot.basis_sha256,
                preferences=V2Preferences(),
                reason="Initially dismissed",
            )
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile)
    try:
        if action in {"post", "dismiss"}:
            dialog.table.selectRow(0)
            dialog.note.setText("Considered action")
            (dialog.confirm if action == "post" else dialog.dismiss).click()
        elif action == "reopen":
            dialog.review_table.selectRow(0)
            dialog.reopen_reason.setText("Considered reopening")
            dialog.reopen.click()
        else:
            dialog.event_table.selectRow(0)
            dialog.correction_reason.setText("Considered correction")
            if action == "replace":
                replacement = next(
                    index for index, pair in enumerate(dialog.replacements) if pair.incoming.account_id == "savings"
                )
                dialog.replacement.setCurrentIndex(dialog.replacement.findData(replacement))
                assert dialog.replace.isEnabled()
            (dialog.replace if action == "replace" else dialog.withdraw).click()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_stale_event_refuses_refreshes_and_read_failure_clears_actions(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "stale.db"
    outgoing, incoming = _profile(profile, bank_date="01/03/2026")
    _post(profile, outgoing, incoming)
    warnings = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    dialog = _dialog(profile)
    try:
        dialog.event_table.selectRow(0)
        dialog.correction_reason.setText("From the loaded event")
        previous_basis = dialog.event_basis
        with V2ProfileStore.open(profile) as store:
            store.add_category_account("expense:concurrent", "Concurrent category", "expense")
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        dialog.withdraw.click()
        assert len(warnings) == 1 and "context changed" in warnings[0]
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        assert dialog.events[0].status == "active"
        assert dialog.event_basis != previous_basis

        def unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError("Synthetic read failure")

        monkeypatch.setattr(V2ProfileStore, "transfer_review_snapshot", unavailable)
        dialog.refresh()
        assert dialog.event_table.rowCount() == dialog.table.rowCount() == dialog.review_table.rowCount() == 0
        assert not any(
            button.isEnabled()
            for button in (dialog.confirm, dialog.dismiss, dialog.withdraw, dialog.replace, dialog.reopen)
        )
        assert "unavailable" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()


def test_withdrawal_remains_available_after_assumed_date_preference_is_off(tmp_path, app, monkeypatch):
    from parsetrail.core.v2_card_lines import parse_card_lines
    from parsetrail.core.v2_card_source_output import from_card
    from parsetrail.core.v2_pdf_lines import page_lines
    from PySide6.QtWidgets import QMessageBox

    from devtools.parser_engine_pilot.test_card_lines import pages
    from devtools.parser_engine_pilot.test_card_source_output import DEFINITION as CHASE_DEFINITION

    profile = tmp_path / "assumed.db"
    source = b"Date,Account,Description,Amount,ReportedBalance\n04/01/2026,Checking A,Card payment,-$5.00,$995.00\n"
    cash = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    card_source = b"%PDF-assumed-transfer-test"
    lines = page_lines(card_source, pages(), extraction_library="synthetic-pdf-1")
    card = from_card(parse_card_lines(CHASE_DEFINITION, lines), lines)
    with V2ProfileStore.create(profile) as store:
        store.import_source(source, BANK_DEFINITION, cash, suffix=".csv")
        store.import_source(card_source, CHASE_DEFINITION, card, suffix=".pdf")
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "chase"))
        store.bind_source_account(cash.source_sha256, "Checking A", "opaque", "checking")
        account = card.payload.accounts[0]
        store.bind_source_account(card.source_sha256, account.source_identity, account.source_identity_form, "card")
        pair = store.transfer_candidates(preferences=V2Preferences(False, True))[0]
        store.post_reviewed_transfer(
            pair.outgoing.row_id,
            pair.incoming.row_id,
            preferences=V2Preferences(False, True),
            reason="Originally reviewed with best guess dates",
        )
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = _dialog(profile)
    try:
        assert not dialog.assumed_dates.isChecked()
        dialog.event_table.selectRow(0)
        dialog.correction_reason.setText("Withdraw the previously reviewed interpretation")
        assert dialog.withdraw.isEnabled()
        dialog.withdraw.click()
        assert dialog.events[0].status == "cancelled"
        assert dialog.table.rowCount() == 1
        dialog.table.selectRow(0)
        assert not dialog.confirm.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def test_reopen_uses_latest_decision_in_current_financial_context_after_rebinding(tmp_path, app, monkeypatch):
    from parsetrail.core.v2_profile_store import BindingCorrectionTarget
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "rebound-context.db"
    outgoing, incoming = _profile(profile, bank_date="01/03/2026")
    with V2ProfileStore.open(profile) as store:
        store.add_financial_account(FinancialAccount("checking-b", "Checking B", "asset", "synthetic"))
        snapshot_a = store.transfer_review_snapshot(preferences=V2Preferences())
        pair = snapshot_a.candidates[0]
        review_a = store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=snapshot_a.basis_sha256,
            preferences=V2Preferences(),
            reason="Dismissed in original checking context",
        )
        target = BindingCorrectionTarget(pair.outgoing.source_sha256, "source", "Checking A", "opaque")

        def correct_binding(destination):
            frame = store.binding_correction_snapshot(target, destination_account_id=destination)
            store.correct_reviewed_binding(
                frame.target,
                destination_account_id=destination,
                expected_basis_sha256=frame.basis_sha256,
                reason="Reviewed source account correction",
            )

        correct_binding("checking-b")
        snapshot_b = store.transfer_review_snapshot(preferences=V2Preferences())
        review_b = store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=snapshot_b.basis_sha256,
            preferences=V2Preferences(),
            reason="Dismissed in different checking context",
        )
        correct_binding("checking")
        returned = store.transfer_review_snapshot(preferences=V2Preferences())
        assert len(returned.candidates) == 1
        assert not any(review.context_current for review in returned.pair_reviews)
        current_review = store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=returned.basis_sha256,
            preferences=V2Preferences(),
            reason="Fresh source inspection in returned checking context",
        )
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = _dialog(profile)
    try:
        assert dialog.table.rowCount() == 0
        current_index = next(
            index
            for index, review in enumerate(dialog.pair_reviews)
            if review.revision_id == current_review.revision_id
        )
        stale_index = next(
            index for index, review in enumerate(dialog.pair_reviews) if review.revision_id == review_b.revision_id
        )
        assert dialog.pair_reviews[current_index].context_current
        assert not dialog.pair_reviews[stale_index].context_current
        assert not next(
            review for review in dialog.pair_reviews if review.revision_id == review_a.revision_id
        ).context_current
        assert review_b.revision_id > review_a.revision_id
        dialog.reopen_reason.setText("Reopen the original checking context after source inspection")
        dialog.review_table.selectRow(stale_index)
        assert not dialog.reopen.isEnabled()
        dialog.review_table.selectRow(current_index)
        assert dialog.reopen.isEnabled()
        dialog.reopen.click()
        assert dialog.table.rowCount() == 1
        assert dialog.candidates[0].outgoing.account_id == "checking"
        assert len(dialog.pair_reviews) == 4
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store._active_consumed() == {}
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0] == 0
    finally:
        dialog.close()
        app.processEvents()


def test_corrupt_blob_transfer_basis_refresh_refuses_and_disables_all_actions(tmp_path, app):
    profile = tmp_path / "corrupt-basis.db"
    outgoing, incoming = _profile(profile, bank_date="01/03/2026")
    _post(profile, outgoing, incoming)
    dialog = _dialog(profile)
    try:
        dialog.event_table.selectRow(0)
        dialog.correction_reason.setText("Previously selected event")
        assert dialog.withdraw.isEnabled()
        with sqlite3.connect(profile) as connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='immutable_TransferEvents_update'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER immutable_TransferEvents_update")
            connection.execute("UPDATE TransferEvents SET request_basis=?", (b"malformed BLOB basis",))
            connection.execute(trigger)
        dialog.refresh()
        assert dialog.event_table.rowCount() == dialog.table.rowCount() == dialog.review_table.rowCount() == 0
        assert dialog.selected_event is None and dialog.basis is None
        assert not any(
            button.isEnabled()
            for button in (dialog.confirm, dialog.dismiss, dialog.withdraw, dialog.replace, dialog.reopen)
        )
        assert "unavailable" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()

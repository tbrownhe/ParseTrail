"""Source interpretations are withdrawn and posted repeats repaired by explicit review."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_cash_activity_review import DEFINITION, SOURCE
from .test_v2_source_overlap_dialog import _profile as overlap_profile
from .test_v2_transfers import _profile as transfer_profile


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    def unexpected(_parent, title, message):
        pytest.fail(f"{title}: {message}")

    monkeypatch.setattr(QMessageBox, "warning", unexpected)
    return QApplication.instance() or QApplication([])


def _cash(profile, *, row_index=0, posted=True, corrected=False):
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        for identity, name, kind in (
            ("expense:food", "Food", "expense"),
            ("expense:travel", "Travel", "expense"),
            ("income:pay", "Pay", "income"),
            ("income:gift", "Gift", "income"),
        ):
            store.add_category_account(identity, name, kind)
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        key = None
        if posted:
            category, other = ("expense:food", "expense:travel") if row_index == 0 else ("income:pay", "income:gift")
            key = store.post_reviewed_cash_category(
                evidence.payload.rows[row_index].row_id, category, reason="Initial reviewed classification"
            )
            if corrected:
                key = store.correct_reviewed_cash_category(key, other, reason="First correction")
                key = store.correct_reviewed_cash_category(key, category, reason="Second correction")
    return evidence, key


def _workspace(profile):
    return V2Workspace.open(
        profile, profile.parent / "catalog", trusted_keys={}, preferences_path=profile.parent / "preferences.json"
    )


def _card(profile):
    evidence = _chase_profile(profile)
    with V2ProfileStore.open(profile) as store:
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        key = store.post_reviewed_card_purchase(
            account.rows[0].row_id,
            "expense:food",
            reason="Initial best guess review",
            preferences=V2Preferences(False, True),
        )
        key = store.correct_reviewed_card_purchase(
            key, "expense:food", reason="Corrected accounting date", accounting_date=date(2026, 4, 1)
        )
        key = store.correct_reviewed_card_purchase(key, "expense:travel", reason="Corrected expense category")
    return evidence, key


def _double_posted(profile):
    sources = overlap_profile(profile)
    with V2ProfileStore.open(profile) as store:
        store.add_category_account("expense:travel", "Travel", "expense")
        pair = store.source_overlap_inventory().candidates[0]
        store.record_source_overlap_review(
            pair.left.row_id,
            pair.right.row_id,
            decision="distinct",
            reason="Originally reviewed as distinct",
            expected_basis_sha256=pair.basis_sha256,
        )
        keys = [
            store.post_reviewed_cash_category(
                source.payload.rows[0].row_id, "expense:food", reason="Originally reviewed purchase"
            )
            for source in sources
        ]
        store.correct_reviewed_cash_category(keys[1], "expense:travel", reason="Corrected redundant category")
    return sources


@pytest.mark.parametrize("row_index", [0, 1])
def test_corrected_cash_withdrawal_uses_active_entry_then_reposts_fresh(tmp_path, app, monkeypatch, row_index):
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "cash.db"
    evidence, old_key = _cash(profile, row_index=row_index, corrected=True)
    questions = []

    def confirm(_parent, _title, message):
        questions.append(message)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = V2CashActivityReview(profile, evidence.source_sha256)
    try:
        dialog.table.selectRow(row_index)
        assert not dialog.withdraw_button.isEnabled()
        dialog.reason.setText("Withdraw the corrected interpretation")
        assert dialog.withdraw_button.isEnabled()
        dialog.withdraw_button.click()
        assert f"Active entry: {old_key}" in questions[0]
        assert "Accounting date: 2026-10-0" in questions[0]
        assert (
            "asset value change $4.00" in questions[0]
            if row_index == 0
            else "reviewed income change -$10.00" in questions[0]
        )
        assert dialog.model.rows[row_index].entry_key is None
        assert "withdraw" in dialog.history_details.text()
        assert not dialog.action_button.isEnabled()
        dialog.purpose.setCurrentIndex(dialog.purpose.findData("expense" if row_index == 0 else "income"))
        dialog.category.setCurrentIndex(dialog.category.findData("expense:food" if row_index == 0 else "income:pay"))
        dialog.reason.setText("Freshly reviewed after withdrawal")
        dialog.action_button.click()
        assert dialog.model.rows[row_index].entry_key not in {None, old_key}
        with V2ProfileStore.open(profile, read_only=True) as store:
            expected = -400 if row_index == 0 else 1000
            assert store._active_consumed()[evidence.payload.rows[row_index].row_id] == expected
    finally:
        dialog.close()
        app.processEvents()


def test_card_withdrawal_uses_recorded_corrected_date_and_category_then_reposts_explicit_date(
    tmp_path, app, monkeypatch
):
    from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "card.db"
    evidence, old_key = _card(profile)
    questions = []

    def confirm(_parent, _title, message):
        questions.append(message)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = V2CardPurchaseReview(_workspace(profile), evidence.source_sha256)
    try:
        dialog.table.selectRow(0)
        dialog.accounting_date.setText("2026-04-30")
        dialog.category.setCurrentIndex(dialog.category.findData("expense:food"))
        dialog.reason.setText("Withdraw active corrected expense")
        assert dialog.withdraw_button.isEnabled()
        dialog.withdraw_button.click()
        assert "Accounting date: 2026-04-01" in questions[0]
        assert "2026-04-30" not in questions[0]
        assert "Travel: reviewed expense change -$10.00" in questions[0]
        assert "amount owed change -$10.00" in questions[0]
        assert dialog.model.rows[0].entry_key is None
        assert not dialog.action_button.isEnabled()
        dialog.purpose.setCurrentIndex(dialog.purpose.findData("expense"))
        dialog.category.setCurrentIndex(dialog.category.findData("expense:food"))
        dialog.accounting_date.setText("2026-04-02")
        dialog.reason.setText("Fresh explicit date review")
        dialog.action_button.click()
        assert dialog.model.rows[0].entry_key not in {None, old_key}
        assert dialog.model.rows[0].effective_date == "2026-04-02"
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("kind", ["cash", "card"])
def test_cancel_withdrawal_and_failed_snapshot_preserve_books_and_clear_actions(tmp_path, app, monkeypatch, kind):
    from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "cancel.db"
    evidence, _key = _cash(profile, corrected=True) if kind == "cash" else _card(profile)
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    dialog = (
        V2CashActivityReview(profile, evidence.source_sha256)
        if kind == "cash"
        else V2CardPurchaseReview(_workspace(profile), evidence.source_sha256)
    )
    try:
        dialog.table.selectRow(0)
        dialog.reason.setText("Considered withdrawal")
        dialog.withdraw_button.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before

        def unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError("Synthetic snapshot read failure")

        monkeypatch.setattr(V2ProfileStore, "source_interpretation_snapshot", unavailable)
        dialog.refresh()
        assert dialog.model.rowCount() == 0 and dialog.basis is None
        assert not dialog.withdraw_button.isEnabled() and not dialog.action_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("action", ["post", "correct", "withdraw"])
def test_stale_cash_context_cannot_post_correct_or_withdraw(tmp_path, app, monkeypatch, action):
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "stale.db"
    evidence, _key = _cash(profile, posted=action != "post")
    warnings = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    dialog = V2CashActivityReview(profile, evidence.source_sha256)
    try:
        dialog.table.selectRow(0)
        dialog.purpose.setCurrentIndex(dialog.purpose.findData("expense"))
        dialog.category.setCurrentIndex(dialog.category.findData("expense:travel"))
        dialog.reason.setText("From loaded review frame")
        old_basis = dialog.basis
        with V2ProfileStore.open(profile) as store:
            if action == "post":
                store.add_financial_account(FinancialAccount("other", "Other checking", "asset", "synthetic"))
                store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "other")
            else:
                store.rename_category_account("expense:travel", "Concurrent renamed category")
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        (dialog.withdraw_button if action == "withdraw" else dialog.action_button).click()
        assert len(warnings) == 1
        assert "changed_since_selection" in warnings[0]
        assert dialog.basis != old_basis
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        if action == "post":
            assert dialog.model.rows[0].financial_account == "Other checking"
    finally:
        dialog.close()
        app.processEvents()


def test_single_row_review_never_withdraws_a_transfer_leg(tmp_path, app):
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview

    profile = tmp_path / "transfer.db"
    outgoing, incoming = transfer_profile(profile, bank_date="01/03/2026")
    with V2ProfileStore.open(profile) as store:
        store.post_reviewed_transfer(outgoing, incoming, preferences=V2Preferences(), reason="Confirmed whole event")
        source_id = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (outgoing,)
        ).fetchone()[0]
    dialog = V2CashActivityReview(profile, source_id)
    try:
        dialog.table.selectRow(0)
        dialog.reason.setText("Cannot cancel one transfer leg")
        assert dialog.model.rows[0].entry_key is None
        assert not dialog.withdraw_button.isEnabled()
        assert not dialog.action_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("accept", [False, True])
def test_posted_repeat_repair_retains_one_corrected_interpretation_and_reopen_never_reposts(
    tmp_path, app, monkeypatch, accept
):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "repair.db"
    sources = _double_posted(profile)
    retained_id, redundant_id = (source.payload.rows[0].row_id for source in sources)
    questions = []

    def answer(_parent, _title, message):
        questions.append(message)
        return QMessageBox.Yes if accept else QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", answer)
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = V2SourceOverlapReview(profile)
    try:
        dialog.table.selectRow(0)
        pair = dialog._current()
        choice = "retain_left" if pair.left.row_id == retained_id else "retain_right"
        dialog.decision.setCurrentIndex(dialog.decision.findData(choice))
        dialog.reason.setText("Compared both originals; one coffee movement")
        assert not dialog.save_button.isEnabled()
        assert dialog.repair_button.isEnabled()
        dialog.repair_button.click()
        assert "Travel: reviewed expense change -$4.00" in questions[0]
        assert "commit together" in questions[0]
        if not accept:
            assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
            return
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store._active_consumed() == {retained_id: -400}
            assert redundant_id not in store._active_consumed()
            journal_count = store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0]
        assert dialog._current().retained_row_id == retained_id
        assert not dialog.repair_button.isEnabled()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        for decision in ("distinct", "pending"):
            dialog.decision.setCurrentIndex(dialog.decision.findData(decision))
            dialog.reason.setText("Explicit subsequent evidence review")
            assert dialog.save_button.isEnabled()
            dialog.save_button.click()
            with V2ProfileStore.open(profile, read_only=True) as store:
                assert store._active_consumed() == {retained_id: -400}
                assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0] == journal_count
    finally:
        dialog.close()
        app.processEvents()


def test_posted_repeat_repair_stale_preview_refuses_without_book_changes(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "stale-repair.db"
    _double_posted(profile)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = V2SourceOverlapReview(profile)
    try:
        dialog.table.selectRow(0)
        dialog.decision.setCurrentIndex(dialog.decision.findData("retain_left"))
        dialog.reason.setText("Loaded repeat preview")
        assert dialog.repair_button.isEnabled()
        with V2ProfileStore.open(profile) as store:
            store.rename_category_account("expense:travel", "Changed after preview")
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        dialog.repair_button.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        assert "not repaired" in dialog.status.text()
        assert not dialog.repair_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def test_card_preference_change_during_confirmation_reloads_without_posting(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "preference-race.db"
    evidence = _chase_profile(profile)
    with V2ProfileStore.open(profile) as store:
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
    workspace = _workspace(profile)
    warnings = []

    def concurrent_preference_change(*_args):
        workspace.set_allow_assumed_posting_dates(True)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", concurrent_preference_change)
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = V2CardPurchaseReview(workspace, evidence.source_sha256)
    try:
        dialog.table.selectRow(0)
        dialog.purpose.setCurrentIndex(dialog.purpose.findData("expense"))
        dialog.category.setCurrentIndex(dialog.category.findData("expense:food"))
        dialog.accounting_date.setText("2026-03-17")
        dialog.reason.setText("Review from initial date preference")
        assert dialog.action_button.isEnabled()
        dialog.action_button.click()
        assert len(warnings) == 1 and "preferences changed" in warnings[0]
        assert dialog.assumed_dates.isChecked()
        assert dialog.model.rows[0].entry_key is None
        assert dialog.review_preferences == workspace.preferences()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("intermediate", ["pending", "distinct"])
def test_validated_repair_can_reconfirm_repeat_after_later_evidence_review_without_reposting(
    tmp_path, app, monkeypatch, intermediate
):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "reconfirm.db"
    sources = _double_posted(profile)
    retained_id, redundant_id = (source.payload.rows[0].row_id for source in sources)
    with V2ProfileStore.open(profile) as store:
        pair = store.source_overlap_inventory().candidates[0]
        store.repair_posted_repeat(
            retained_id, redundant_id, expected_basis_sha256=pair.basis_sha256, reason="Confirmed duplicate movement"
        )
        pair = store.source_overlap_inventory().candidates[0]
        store.record_source_overlap_review(
            pair.left.row_id,
            pair.right.row_id,
            decision=intermediate,
            expected_basis_sha256=pair.basis_sha256,
            reason="Subsequent evidence review",
        )
        journal_count = store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0]
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = V2SourceOverlapReview(profile)
    try:
        dialog.table.selectRow(0)
        pair = dialog._current()
        supporting = pair.right if pair.left.row_id == retained_id else pair.left
        assert supporting.has_journal_history and supporting.active_allocated_minor == 0
        assert supporting.repeat_support_history_validated
        choice = "retain_left" if pair.left.row_id == retained_id else "retain_right"
        dialog.decision.setCurrentIndex(dialog.decision.findData(choice))
        dialog.reason.setText("Reconfirmed same movement from validated repair history")
        assert dialog.save_button.isEnabled()
        assert not dialog.repair_button.isEnabled()
        dialog.save_button.click()
        assert dialog._current().state == "repeat"
        assert dialog._current().retained_row_id == retained_id
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store._active_consumed() == {retained_id: -400}
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0] == journal_count
    finally:
        dialog.close()
        app.processEvents()


def test_unproven_inactive_journal_history_cannot_be_excluded_by_ordinary_repeat_review(tmp_path, app):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview

    profile = tmp_path / "unproven-history.db"
    sources = _double_posted(profile)
    retained_id, redundant_id = (source.payload.rows[0].row_id for source in sources)
    with V2ProfileStore.open(profile) as store:
        snapshot = store.source_interpretation_snapshot(sources[1].source_sha256, kind="cash")
        row = next(row for row in snapshot.rows if row.row_id == redundant_id)
        store.withdraw_reviewed_interpretation(
            row.entry_key,
            expected_basis_sha256=snapshot.basis_sha256,
            reason="Ordinary withdrawal supplies no repeat-repair proof",
        )
    dialog = V2SourceOverlapReview(profile)
    try:
        dialog.table.selectRow(0)
        pair = dialog._current()
        supporting = pair.right if pair.left.row_id == retained_id else pair.left
        assert supporting.has_journal_history and supporting.active_allocated_minor == 0
        assert not supporting.repeat_support_history_validated
        choice = "retain_left" if pair.left.row_id == retained_id else "retain_right"
        dialog.decision.setCurrentIndex(dialog.decision.findData(choice))
        dialog.reason.setText("An unproven history must still be refused")
        assert not dialog.save_button.isEnabled()
        assert not dialog.repair_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("kind", ["cash", "card"])
def test_prior_withdrawal_retry_after_fresh_repost_reports_current_state_truthfully(tmp_path, app, monkeypatch, kind):
    from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "withdraw-retry.db"
    evidence, old_key = _cash(profile, corrected=True) if kind == "cash" else _card(profile)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = (
        V2CashActivityReview(profile, evidence.source_sha256)
        if kind == "cash"
        else V2CardPurchaseReview(_workspace(profile), evidence.source_sha256)
    )
    try:
        dialog.table.selectRow(0)
        reason = "Same selected-entry withdrawal request"
        dialog.reason.setText(reason)
        with V2ProfileStore.open(profile) as store:
            store.withdraw_reviewed_interpretation(old_key, expected_basis_sha256=dialog.basis, reason=reason)
            if kind == "cash":
                fresh_key = store.post_reviewed_cash_category(
                    evidence.payload.rows[0].row_id, "expense:food", reason="Fresh confirmed posting"
                )
            else:
                fresh_key = store.post_reviewed_card_purchase(
                    evidence.payload.accounts[0].rows[0].row_id,
                    "expense:travel",
                    reason="Fresh confirmed posting",
                    preferences=V2Preferences(),
                    accounting_date=date(2026, 4, 2),
                )
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        dialog.withdraw_button.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        assert dialog.model.rows[0].entry_key == fresh_key
        assert "recorded" in dialog.status.text()
        assert "remains pending" not in dialog.status.text()
        assert "current posting state" in dialog.status.text()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert len(store._active_consumed()) == 1
    finally:
        dialog.close()
        app.processEvents()


def test_prior_repair_retry_after_retained_withdrawal_does_not_claim_one_active_interpretation(
    tmp_path, app, monkeypatch
):
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "repair-retry.db"
    sources = _double_posted(profile)
    retained_id, redundant_id = (source.payload.rows[0].row_id for source in sources)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = V2SourceOverlapReview(profile)
    try:
        dialog.table.selectRow(0)
        pair = dialog._current()
        choice = "retain_left" if pair.left.row_id == retained_id else "retain_right"
        dialog.decision.setCurrentIndex(dialog.decision.findData(choice))
        reason = "Same selected-pair repair request"
        dialog.reason.setText(reason)
        assert dialog.repair_button.isEnabled()
        with V2ProfileStore.open(profile) as store:
            store.repair_posted_repeat(
                retained_id, redundant_id, expected_basis_sha256=pair.basis_sha256, reason=reason
            )
            snapshot = store.source_interpretation_snapshot(sources[0].source_sha256, kind="cash")
            entry_key = next(row.entry_key for row in snapshot.rows if row.row_id == retained_id)
            store.withdraw_reviewed_interpretation(
                entry_key, expected_basis_sha256=snapshot.basis_sha256, reason="Retained interpretation withdrawn later"
            )
            assert store._active_consumed() == {}
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        dialog.repair_button.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        assert "repair is recorded" in dialog.status.text()
        assert "One interpretation remains active" not in dialog.status.text()
        assert dialog._current().left.active_allocated_minor == dialog._current().right.active_allocated_minor == 0
        assert not dialog.repair_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()

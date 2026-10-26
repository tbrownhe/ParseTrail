"""Full settlement authoring and whole-event correction use disposable profiles."""

from __future__ import annotations

import hashlib
from datetime import date

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_settlements import profile
from .test_v2_transfers import BANK_DEFINITION


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    def unexpected(_parent, title, message):
        pytest.fail(f"{title}: {message}")

    monkeypatch.setattr(QMessageBox, "warning", unexpected)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    return QApplication.instance() or QApplication([])


def _workspace(path):
    return V2Workspace.open(
        path, path.parent / "catalog", trusted_keys={}, preferences_path=path.parent / "preferences.json"
    )


def _dialog(path, event_id=None):
    from parsetrail.gui.v2_settlement_review import V2SettlementReview

    return V2SettlementReview(_workspace(path), event_id=event_id)


def _check(dialog, incoming, *, checked=True):
    from PySide6.QtCore import Qt

    for index in range(dialog.receipts.rowCount()):
        item = dialog.receipts.item(index, 0)
        if item.data(Qt.UserRole) == incoming:
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            return
    pytest.fail("Receipt must be reachable by its exact source row identity")


def _select(dialog, outgoing, incoming):
    dialog.outgoing.setCurrentIndex(dialog.outgoing.findData(outgoing))
    for row_id in incoming:
        _check(dialog, row_id)


def _fee(dialog, row_id, amount):
    dialog.fee_leg.setCurrentIndex(dialog.fee_leg.findData(row_id))
    dialog.fee_amount.setText(amount)
    dialog.fee_category.setCurrentIndex(dialog.fee_category.findData("expense:fees"))
    dialog.fee_reference.setText("Reviewed source leg / fee detail")
    dialog.fee_reason.setText("Explicit source-backed fee, not inferred from mismatch")
    assert dialog.add_fee.isEnabled()
    dialog.add_fee.click()


def test_empty_profile_keeps_all_source_and_fee_actions_disabled_without_writes(tmp_path, app):
    path = tmp_path / "empty.db"
    with V2ProfileStore.create(path):
        pass
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    dialog = _dialog(path)
    try:
        dialog.show()
        app.processEvents()
        assert dialog.receipts.rowCount() == 0 and dialog.fee_table.rowCount() == 0
        assert dialog.outgoing.currentData() is None and dialog.preview is None
        assert not dialog.confirm.isEnabled() and not dialog.withdraw.isEnabled()
        assert not dialog.add_fee.isEnabled() and not dialog.remove_fee.isEnabled()
        assert not dialog.open_outgoing.isEnabled() and not dialog.open_receipt.isEnabled()
        assert dialog.profile_path.isReadOnly()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_preference_change_during_confirmation_resets_draft_without_posting(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "preference-race.db"
    _evidence, outgoing, incoming = profile(path)
    dialog = _dialog(path)
    try:
        _select(dialog, outgoing, incoming)
        dialog.reason.setText("Review from the loaded preference context")
        before = hashlib.sha256(path.read_bytes()).hexdigest()

        def concurrent_preference_change(*_args):
            dialog.workspace.set_allow_assumed_posting_dates(True)
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", concurrent_preference_change)
        dialog.confirm.click()
        assert "preferences changed" in dialog.status.text()
        assert dialog.assumed_dates.isChecked()
        assert dialog.preview is None and dialog.outgoing.currentData() is None
        assert not dialog.confirm.isEnabled()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize(
    "receipt,out_fee,in_fee,residual",
    [
        (6000, 0, 0, 4000),
        (6000, 1000, 0, 3000),
        (9000, 0, 1000, 0),
        (6000, 500, 500, 3000),
    ],
)
def test_no_inferred_fee_exact_preview_cancel_post_and_reopen(
    tmp_path, app, monkeypatch, receipt, out_fee, in_fee, residual
):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "settlement.db"
    evidence, outgoing, incoming = profile(path, receipts=(("10/03/2026", str(receipt)),))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    dialog = _dialog(path)
    try:
        assert dialog.outgoing.currentData() is None and dialog.fees == ()
        assert dialog.fee_leg.currentData() is None and dialog.fee_category.currentData() is None
        assert not dialog.confirm.isEnabled() and not dialog.add_fee.isEnabled()
        _select(dialog, outgoing, incoming)
        assert dialog.preview is not None
        assert dialog.preview.settlement.residual_minor == 10000 - receipt
        assert dialog.fees == () and dialog.fee_table.rowCount() == 0
        assert "No fee is inferred" in dialog.status.text()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        if out_fee:
            _fee(dialog, outgoing, f"{out_fee // 100}.{out_fee % 100:02}")
        if in_fee:
            _fee(dialog, incoming[0], f"{in_fee // 100}.{in_fee % 100:02}")
        assert dialog.preview is not None and dialog.preview.settlement.residual_minor == residual
        assert dialog.entry_table.rowCount() == 4 + bool(out_fee) + bool(in_fee)
        assert "gross settlement received" in dialog.summary.text()
        assert "unresolved / in transit" in dialog.summary.text()
        assert dialog.fee_category.findData("income:pay") == -1
        dialog.reason.setText("Reviewed every source leg and explicit fee")
        assert dialog.confirm.isEnabled()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        dialog.confirm.click()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        questions = []

        def accept(_parent, _title, message):
            questions.append(message)
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", accept)
        dialog.confirm.click()
        event = dialog.selected_event
        assert event is not None and event.pair is None and event.status == "active"
        assert event.settlement.residual_minor == residual
        assert "New entry effects" in questions[0] and "Unknown counterpart history stays unknown" in questions[0]
        assert "2026-10-01" in questions[0] and "2026-10-03" in questions[0]
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store._active_consumed() == {outgoing: -10000, incoming[0]: receipt}
            assert store.account_positions(as_of=date(2026, 10, 3)).transfer_clearing_debit_minor == residual
            assert (
                store.reviewed_category_summary(
                    kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)
                ).total_minor
                == out_fee + in_fee
            )
            assert store.load_import(evidence.source_sha256).evidence == evidence
    finally:
        dialog.close()
        app.processEvents()
    reopened = _dialog(path, event.event_id)
    try:
        assert reopened.selected_event.event_id == event.event_id
        assert len(reopened.fees) == bool(out_fee) + bool(in_fee)
        assert "unresolved / in transit" in reopened.history_details.toPlainText()
        assert "Reviewed source leg / fee detail" in reopened.history_details.toPlainText() or not reopened.fees
    finally:
        reopened.close()
        app.processEvents()


def test_fee_requires_each_explicit_field_and_overallocation_can_be_removed(tmp_path, app):
    path = tmp_path / "fee-fields.db"
    _evidence, outgoing, incoming = profile(path, receipts=(("10/03/2026", "9000"),))
    dialog = _dialog(path)
    try:
        _select(dialog, outgoing, incoming)
        dialog.fee_leg.setCurrentIndex(dialog.fee_leg.findData(outgoing))
        dialog.fee_category.setCurrentIndex(dialog.fee_category.findData("expense:fees"))
        dialog.fee_reference.setText("Source fee detail")
        dialog.fee_reason.setText("Explicit fee support")
        for bad in ("", "0", "-1", "1.001"):
            dialog.fee_amount.setText(bad)
            assert not dialog.add_fee.isEnabled()
        dialog.fee_amount.setText("20.00")
        dialog.fee_reference.clear()
        assert not dialog.add_fee.isEnabled()
        dialog.fee_reference.setText("Source fee detail")
        dialog.add_fee.click()
        assert dialog.preview is None and "exceed" in dialog.summary.text()
        dialog.reason.setText("Invalid over-allocation cannot post")
        assert not dialog.confirm.isEnabled()
        dialog.fee_table.selectRow(0)
        dialog.remove_fee.click()
        assert dialog.preview is not None and dialog.preview.settlement.residual_minor == 1000
        assert dialog.fees == ()
    finally:
        dialog.close()
        app.processEvents()


def test_multiple_noncontemporaneous_receipts_full_history_and_whole_fee_withdrawal(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_settlement_review import V2SettlementReview
    from parsetrail.gui.v2_transfer_review import V2TransferReview
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "many.db"
    _evidence, outgoing, incoming = profile(path, receipts=(("09/01/2026", "4000"), ("12/15/2026", "5000")))
    with V2ProfileStore.open(path) as store:
        for account_id in ("checking", "savings"):
            store.update_financial_account(
                FinancialAccount(account_id, "Shared name", "asset", "synthetic", "12345678")
            )
    dialog = _dialog(path)
    try:
        _select(dialog, outgoing, incoming)
        _fee(dialog, outgoing, "10.00")
        assert dialog.preview is not None and dialog.preview.settlement.residual_minor == 0
        assert {entry.posting_date for entry in dialog.preview.entries} == {
            date(2026, 9, 1),
            date(2026, 10, 1),
            date(2026, 12, 15),
        }
        dialog.reason.setText("Receipts have independent dates, including before the outflow")
        dialog.confirm.click()
        event = dialog.selected_event
        assert len(event.settlement.incoming) == 2 and len(event.entry_keys) == 3
    finally:
        dialog.close()
    transfer = V2TransferReview(_workspace(path))
    try:
        transfer.tabs.setCurrentIndex(1)
        transfer.event_table.selectRow(0)
        assert transfer.selected_event.pair is None
        assert "Full" in transfer.event_table.item(0, 1).text()
        assert "ID checking" in transfer.event_table.item(0, 3).text()
        assert "ID savings" in transfer.event_table.item(0, 5).text()
        text = transfer.event_details.toPlainText()
        assert "Shared name" in text and "ID checking" in text and "ID savings" in text
        assert "2026-09-01" in text and "2026-12-15" in text and "explicit fee" in text
        transfer.correction_reason.setText("Withdraw complete event, including fee and every receipt")
        assert transfer.withdraw.isEnabled() and not transfer.replace.isEnabled()
        assert transfer.review_settlement.isEnabled()
        opened = []
        monkeypatch.setattr(V2SettlementReview, "exec", lambda widget: opened.append(widget.selected_event.event_id))
        transfer.review_settlement.click()
        assert opened == [event.event_id]
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        transfer.withdraw.click()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        questions = []

        def accept(_parent, _title, message):
            questions.append(message)
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", accept)
        transfer.withdraw.click()
        assert "inverse fee expense: -$10.00" in questions[0]
        assert "All 3 journal leg(s)" in questions[0]
        assert "ID checking" in questions[0] and "ID savings" in questions[0]
        assert "No income or expense is created" not in questions[0]
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store._active_consumed() == {}
            assert store.transfer_history()[0].status == "cancelled"
            assert (
                store.reviewed_category_summary(
                    kind="expense", start=date(2026, 1, 1), end=date(2027, 1, 1)
                ).total_minor
                == 0
            )
    finally:
        transfer.close()
        app.processEvents()


def test_later_receipt_replaces_every_old_leg_and_preserves_original_fee_history(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "replacement.db"
    _evidence, outgoing, incoming = profile(path, receipts=(("10/03/2026", "6000"), ("10/06/2026", "3000")))
    dialog = _dialog(path)
    try:
        _select(dialog, outgoing, incoming[:1])
        _fee(dialog, outgoing, "10.00")
        dialog.reason.setText("Review initial partial receipt")
        dialog.confirm.click()
        original = dialog.selected_event
        assert original.settlement.residual_minor == 3000
        _check(dialog, incoming[1])
        assert dialog.preview is not None and dialog.preview.settlement.residual_minor == 0
        dialog.reason.setText("Add later source receipt through whole-event replacement")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        dialog.confirm.click()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        questions = []

        def accept(_parent, _title, message):
            questions.append(message)
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", accept)
        dialog.confirm.click()
        assert "Inverse original source and fee effects" in questions[0]
        assert "Replacement entry effects only" in questions[0]
        assert dialog.selected_event.event_id != original.event_id
        with V2ProfileStore.open(path, read_only=True) as store:
            events = store.transfer_history()
            assert len(events) == 2 and events[0].status == "active" and events[1].status == "replaced"
            assert events[1].replacement_event_id == events[0].event_id
            assert store._active_consumed() == {outgoing: -10000, incoming[0]: 6000, incoming[1]: 3000}
            assert store.account_positions(as_of=date(2026, 10, 7)).transfer_clearing_debit_minor == 0
            assert (
                store.reviewed_category_summary(
                    kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)
                ).total_minor
                == 1000
            )
    finally:
        dialog.close()
        app.processEvents()


def test_stale_confirmation_and_failed_refresh_clear_source_versions_and_actions(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "stale.db"
    _evidence, outgoing, incoming = profile(path)
    dialog = _dialog(path)
    try:
        _select(dialog, outgoing, incoming)
        dialog.reason.setText("Review from original source snapshot")

        def concurrent_change(*_args):
            with V2ProfileStore.open(path) as store:
                store.rename_category_account("expense:fees", "Concurrent fee category name")
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", concurrent_change)
        dialog.confirm.click()
        assert "not recorded" in dialog.status.text()
        assert dialog.preview is None and dialog.outgoing.currentData() is None
        assert not dialog.confirm.isEnabled()
        with V2ProfileStore.open(path, read_only=True) as store:
            assert not store._active_consumed() and store.transfer_history() == ()

        def failed(*_args, **_kwargs):
            raise ProfileFormatError("synthetic_snapshot_refusal")

        monkeypatch.setattr(V2ProfileStore, "settlement_review_snapshot", failed)
        dialog.refresh()
        assert dialog.snapshot is None and dialog.receipts.rowCount() == 0
        assert not dialog.confirm.isEnabled() and not dialog.withdraw.isEnabled()
        assert not dialog.add_fee.isEnabled() and not dialog.remove_fee.isEnabled()
        assert not dialog.open_outgoing.isEnabled() and not dialog.open_receipt.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def test_assumed_date_opt_in_remains_explicit_but_opt_out_allows_whole_withdrawal(tmp_path, app, monkeypatch):
    from types import SimpleNamespace

    import parsetrail.gui.v2_settlement_review as review_module
    from PySide6.QtCore import Qt

    path = tmp_path / "assumed.db"
    card = _chase_profile(path)
    content = (
        b"Date,Account,Description,Amount,ReportedBalance\n04/01/2026,Checking A,Owned card payment,-$5.00,$995.00\n"
    )
    bank = build_source_evidence(content, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.import_source(content, BANK_DEFINITION, bank, suffix=".csv")
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        store.bind_source_account(bank.source_sha256, "Checking A", "opaque", "checking")
        account = card.payload.accounts[0]
        store.bind_source_account(card.source_sha256, account.source_identity, account.source_identity_form, "card")
    outgoing, incoming = bank.payload.rows[0].row_id, card.payload.accounts[0].rows[1].row_id
    dialog = _dialog(path)
    try:
        assert not dialog.assumed_dates.isChecked()
        _select(dialog, outgoing, (incoming,))
        assert dialog.preview is None and "assumed" in dialog.summary.text().lower()
        opened = []

        def preview_source(profile_path, source_sha256, *, parent):
            opened.append((profile_path, source_sha256, parent))
            return SimpleNamespace(exec=lambda: None)

        monkeypatch.setattr(review_module, "preview_saved_source", preview_source)
        dialog.open_outgoing.click()
        index = next(
            index
            for index in range(dialog.receipts.rowCount())
            if dialog.receipts.item(index, 0).data(Qt.UserRole) == incoming
        )
        dialog.receipts.selectRow(index)
        dialog.open_receipt.click()
        assert [source for _profile_path, source, _parent in opened] == [bank.source_sha256, card.source_sha256]
        assert all(profile_path == path and parent is dialog for profile_path, _source, parent in opened)
        dialog.assumed_dates.click()
        _select(dialog, outgoing, (incoming,))
        dialog.reason.setText("Confirm reviewed source dates with explicit preference")
        assert dialog.confirm.isEnabled()
        dialog.confirm.click()
        assert dialog.selected_event.status == "active"
        dialog.assumed_dates.click()
        assert not dialog.assumed_dates.isChecked()
        dialog.reason.setText("Withdraw saved event after disabling new best guess dates")
        assert dialog.withdraw.isEnabled() and not dialog.confirm.isEnabled()
        dialog.withdraw.click()
        assert dialog.selected_event.status == "cancelled"
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store._active_consumed() == {}
        from parsetrail.gui.v2_transfer_review import V2TransferReview

        parent = V2TransferReview(dialog.workspace)
        try:

            def nested_preference_change(child):
                child.assumed_dates.click()
                child.close()

            monkeypatch.setattr(review_module.V2SettlementReview, "exec", nested_preference_change)
            for enabled in (True, False):
                parent.full_settlement.click()
                assert parent.assumed_dates.isChecked() == enabled
                assert parent.workspace.preferences().allow_assumed_posting_dates == enabled
                assert parent.candidates and all(pair.posting_allowed == enabled for pair in parent.candidates)
                parent.table.selectRow(0)
                assert parent.confirm.isEnabled() == enabled
        finally:
            parent.close()
    finally:
        dialog.close()
        app.processEvents()

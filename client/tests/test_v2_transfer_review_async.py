"""Transfer controller responsiveness and explicit batch confirmation regressions."""

from __future__ import annotations

import hashlib
import threading
import time

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_transfer_review import V2TransferReview
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QTableWidget

from .test_v2_transfers import _profile


def wait_for_transfers(dialog, timeout=10):
    end = time.monotonic() + timeout
    app = QApplication.instance()
    while dialog.pending or dialog._worker is not None or dialog._timer.isActive():
        app.processEvents()
        time.sleep(0.003)
        assert time.monotonic() < end, "Transfer controller did not settle"
    app.processEvents()


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: None)
    return QApplication.instance() or QApplication([])


def _workspace(tmp_path):
    path = tmp_path / "transfers.db"
    outgoing, incoming = _profile(path, bank_date="01/03/2026")
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    return workspace, outgoing, incoming


def test_shell_is_immediate_and_gap_changes_coalesce_latest_wins(tmp_path, app, monkeypatch):
    workspace, _, _ = _workspace(tmp_path)
    original = V2ProfileStore.transfer_review_snapshot
    started, release = threading.Event(), threading.Event()
    gaps = []

    def delayed(store, **kwargs):
        gaps.append(kwargs["max_day_gap"])
        if len(gaps) == 1:
            started.set()
            assert release.wait(5)
        return original(store, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "transfer_review_snapshot", delayed)
    t = time.monotonic()
    dialog = V2TransferReview(workspace)
    assert time.monotonic() - t < 0.5
    try:
        assert dialog.pending and not dialog.confirm.isEnabled()
        end = time.monotonic() + 5
        while not started.is_set():
            app.processEvents()
            time.sleep(0.003)
            assert time.monotonic() < end
        for gap in (1, 3, 8, 2):
            dialog.gap.setValue(gap)
        assert not dialog.confirm.isEnabled() and dialog.table.rowCount() == 0
        release.set()
        wait_for_transfers(dialog)
        assert gaps == [7, 2]
        assert dialog.table.rowCount() == 1
        assert dialog._snapshot.max_day_gap == 2
    finally:
        release.set()
        dialog.close()
        app.processEvents()


def test_selection_notes_history_and_combo_do_not_read_store(tmp_path, app, monkeypatch):
    workspace, outgoing, incoming = _workspace(tmp_path)
    dialog = V2TransferReview(workspace)
    try:
        wait_for_transfers(dialog)

        def forbidden(*_args, **_kwargs):
            raise AssertionError("Selection must not open the profile")

        monkeypatch.setattr(V2ProfileStore, "open", forbidden)
        for i in range(100):
            dialog.table.selectRow(0)
            dialog.note.setText(str(i))
            dialog.correction_reason.setText(str(i))
            dialog.reopen_reason.setText(str(i))
            dialog.replacement.setCurrentIndex(-1)
            dialog._event_selected()
            dialog._review_selected()
        assert dialog.confirm.isEnabled() and dialog.dismiss.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def test_batch_cancel_does_not_write_and_explicit_manifest_accept_posts(tmp_path, app, monkeypatch):
    workspace, _, _ = _workspace(tmp_path)
    dialog = V2TransferReview(workspace)
    try:
        wait_for_transfers(dialog)
        assert len(dialog.batch_plan.pairs) == 1
        dialog.note.setText("n" * 450)
        before = hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest()
        monkeypatch.setattr(QDialog, "exec", lambda _self: QDialog.Rejected)
        dialog.batch.click()
        assert hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest() == before
        seen = []

        def accept(manifest):
            seen.append(manifest.windowTitle())
            assert "no other matches" in manifest.windowTitle()
            table = manifest.findChild(QTableWidget)
            assert "(derived)" in table.item(0, 3).text()
            return QDialog.Accepted

        monkeypatch.setattr(QDialog, "exec", accept)
        dialog.batch.click()
        wait_for_transfers(dialog)
        assert seen and len(dialog.events) == 1
        assert dialog.events[0].reason.endswith("n" * 450)
        assert not dialog.candidates and "1 transfer pairs posted" in dialog.status.text()
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert len(store._active_consumed()) == 2
    finally:
        dialog.close()
        app.processEvents()


def test_close_during_confirmed_write_waits_and_reports_commit(tmp_path, app, monkeypatch):
    workspace, _, _ = _workspace(tmp_path)
    original = V2ProfileStore.post_reviewed_transfer
    started, release = threading.Event(), threading.Event()

    def delayed(store, *args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(store, *args, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "post_reviewed_transfer", delayed)
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.Yes)
    dialog = V2TransferReview(workspace)
    try:
        wait_for_transfers(dialog)
        dialog.table.selectRow(0)
        dialog.confirm.click()
        end = time.monotonic() + 5
        while not started.is_set():
            app.processEvents()
            time.sleep(0.003)
            assert time.monotonic() < end
        assert dialog.close() is False
        assert "outcome" in dialog.status.text()
        release.set()
        wait_for_transfers(dialog)
        assert len(dialog.events) == 1 and "posted" in dialog.status.text()
        assert not dialog._closed
    finally:
        release.set()
        dialog.close()
        app.processEvents()


def test_focus_hint_selects_pair_without_narrowing_global_scope(tmp_path, app):
    workspace, outgoing, _ = _workspace(tmp_path)
    dialog = V2TransferReview(workspace, focus_row_id=outgoing)
    try:
        wait_for_transfers(dialog)
        assert dialog._current().outgoing.row_id == outgoing
        assert len(dialog.batch_plan.pairs) == 1
    finally:
        dialog.close()
        app.processEvents()


def test_hidden_close_before_events_never_starts_read(tmp_path, app, monkeypatch):
    workspace, _, _ = _workspace(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Closed dialog must not start a read")

    monkeypatch.setattr(V2ProfileStore, "transfer_review_snapshot", forbidden)
    dialog = V2TransferReview(workspace)
    dialog.close()
    app.processEvents()
    assert dialog._worker is None and not dialog._timer.isActive()


def test_confirmed_history_selection_uses_cached_guards(tmp_path, app, monkeypatch):
    workspace, outgoing, incoming = _workspace(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.post_reviewed_transfer(outgoing, incoming, preferences=workspace.preferences(), reason="Reviewed pair")
    dialog = V2TransferReview(workspace)
    try:
        wait_for_transfers(dialog)

        def forbidden(*_args, **_kwargs):
            raise AssertionError("History selection must not open the profile")

        monkeypatch.setattr(V2ProfileStore, "open", forbidden)
        for index in range(100):
            dialog.event_table.selectRow(0)
            dialog.correction_reason.setText(f"Reviewed correction {index}")
            dialog._event_selected()
            dialog.replacement.setCurrentIndex(0)
        assert dialog.withdraw.isEnabled()
        assert dialog.load_replacements.isEnabled()
        assert not dialog.replace.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def test_read_failure_clears_actions_and_retry_recovers(tmp_path, app, monkeypatch):
    workspace, _, _ = _workspace(tmp_path)
    dialog = V2TransferReview(workspace)
    try:
        wait_for_transfers(dialog)
        dialog.table.selectRow(0)
        original = V2ProfileStore.transfer_review_snapshot

        def unavailable(*_args, **_kwargs):
            raise OSError("Synthetic saved state unavailable")

        monkeypatch.setattr(V2ProfileStore, "transfer_review_snapshot", unavailable)
        dialog.refresh()
        wait_for_transfers(dialog)
        dialog.note.setText("An old selection cannot be posted")
        assert "unavailable" in dialog.status.text()
        assert not dialog.candidates and dialog.basis is None
        assert not any(
            button.isEnabled()
            for button in (dialog.confirm, dialog.batch, dialog.dismiss, dialog.withdraw, dialog.replace, dialog.reopen)
        )
        monkeypatch.setattr(V2ProfileStore, "transfer_review_snapshot", original)
        dialog.reload_button.click()
        wait_for_transfers(dialog)
        assert len(dialog.candidates) == 1
    finally:
        dialog.close()
        app.processEvents()


def test_batch_stale_manifest_reloads_without_posting_any_pair(tmp_path, app, monkeypatch):
    workspace, _, _ = _workspace(tmp_path)
    dialog = V2TransferReview(workspace)
    try:
        wait_for_transfers(dialog)
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))

        def changed_manifest(_manifest):
            with V2ProfileStore.open(workspace.profile_path) as store:
                store.add_category_account("expense:concurrent", "Concurrent category", "expense")
            return QDialog.Accepted

        monkeypatch.setattr(QDialog, "exec", changed_manifest)
        dialog.batch.click()
        wait_for_transfers(dialog)
        assert warnings and "changed" in warnings[0]
        assert not dialog.events and len(dialog.candidates) == 1
        assert "changed" in dialog.status.text()
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone()[0] == 0
    finally:
        dialog.close()
        app.processEvents()


def test_confirmed_batch_close_cancels_before_commit_and_reports_none(tmp_path, app, monkeypatch):
    from parsetrail.core import v2_transfer_batch

    workspace, _, _ = _workspace(tmp_path)
    original = v2_transfer_batch.post_reviewed_transfer_batch
    started, release = threading.Event(), threading.Event()

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(v2_transfer_batch, "post_reviewed_transfer_batch", delayed)
    monkeypatch.setattr(QDialog, "exec", lambda _manifest: QDialog.Accepted)
    dialog = V2TransferReview(workspace)
    try:
        wait_for_transfers(dialog)
        dialog.batch.click()
        end = time.monotonic() + 5
        while not started.is_set():
            app.processEvents()
            time.sleep(0.003)
            assert time.monotonic() < end
        assert not dialog.close()
        assert "Cancellation requested" in dialog.status.text()
        release.set()
        wait_for_transfers(dialog)
        assert "no pairs were posted" in dialog.status.text()
        assert len(dialog.candidates) == 1 and not dialog.events
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone()[0] == 0
    finally:
        release.set()
        dialog.close()
        app.processEvents()


def test_assumed_dates_are_qualified_in_candidates_and_final_manifest(tmp_path, app, monkeypatch):
    from parsetrail.core.v2_card_lines import parse_card_lines
    from parsetrail.core.v2_card_source_output import from_card
    from parsetrail.core.v2_pdf_lines import page_lines
    from parsetrail.core.v2_profile_store import FinancialAccount
    from parsetrail.core.v2_source_pipeline import build_source_evidence

    from devtools.parser_engine_pilot.test_card_lines import pages
    from devtools.parser_engine_pilot.test_card_source_output import DEFINITION

    from .test_v2_transfers import BANK_DEFINITION

    path = tmp_path / "assumed.db"
    source = b"Date,Account,Description,Amount,ReportedBalance\n04/01/2026,Checking A,Card payment,-$5.00,$995.00\n"
    cash = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    card_source = b"%PDF-synthetic-assumed-view"
    lines = page_lines(card_source, pages(), extraction_library="synthetic-pdf-1")
    card = from_card(parse_card_lines(DEFINITION, lines), lines)
    with V2ProfileStore.create(path) as store:
        store.import_source(source, BANK_DEFINITION, cash, suffix=".csv")
        store.import_source(card_source, DEFINITION, card, suffix=".pdf")
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "chase"))
        store.bind_source_account(cash.source_sha256, "Checking A", "opaque", "checking")
        account = card.payload.accounts[0]
        store.bind_source_account(card.source_sha256, account.source_identity, account.source_identity_form, "card")
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    workspace.set_allow_assumed_posting_dates(True)
    dialog = V2TransferReview(workspace)
    try:
        wait_for_transfers(dialog)
        index = next(i for i, pair in enumerate(dialog.candidates) if pair.incoming.date_provenance == "assumed")
        assert "(assumed)" in dialog.table.item(index, 3).text()
        seen = []

        def inspect_and_cancel(manifest):
            table = manifest.findChild(QTableWidget)
            seen.extend(table.item(row, 3).text() for row in range(table.rowCount()))
            return QDialog.Rejected

        monkeypatch.setattr(QDialog, "exec", inspect_and_cancel)
        dialog.batch.click()
        assert any("(assumed)" in text for text in seen)
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone()[0] == 0
    finally:
        dialog.close()
        app.processEvents()


def test_nested_confirmation_refresh_keeps_original_review_basis(tmp_path, app, monkeypatch):
    from parsetrail.core.v2_profile_store import BindingCorrectionTarget, FinancialAccount

    workspace, _, _ = _workspace(tmp_path)
    dialog = V2TransferReview(workspace)
    try:
        wait_for_transfers(dialog)
        dialog.table.selectRow(0)
        pair, original_basis = dialog._current(), dialog.basis
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))

        def nested_refresh(_parent, _title, _message):
            with V2ProfileStore.open(workspace.profile_path) as store:
                store.add_financial_account(FinancialAccount("checking-b", "Checking B", "asset", "synthetic"))
                target = BindingCorrectionTarget(pair.outgoing.source_sha256, "source", "Checking A", "opaque")
                frame = store.binding_correction_snapshot(target, destination_account_id="checking-b")
                store.correct_reviewed_binding(
                    frame.target,
                    destination_account_id="checking-b",
                    expected_basis_sha256=frame.basis_sha256,
                    reason="Reviewed new source account context",
                )
            dialog.refresh()
            wait_for_transfers(dialog)
            assert dialog.basis != original_basis
            assert dialog.candidates[0].outgoing.account_id == "checking-b"
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", nested_refresh)
        dialog.confirm.click()
        wait_for_transfers(dialog)
        assert warnings and "context changed" in warnings[0]
        assert not dialog.events
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone()[0] == 0
    finally:
        dialog.close()
        app.processEvents()

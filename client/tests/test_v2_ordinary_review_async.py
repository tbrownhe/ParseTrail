"""Ordinary review stays responsive, explicit and bound to its captured profile."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
from parsetrail.gui.v2_profile_jobs import _JOBS, ProfileJobs
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

DEFINITION = (Path(__file__).parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json").read_bytes()


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.002)
    assert predicate(), "Queued review operation did not finish"


def wait_for_review(view):
    wait_until(lambda: not view.review_pending)
    return view


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: QMessageBox.Ok)
    app = QApplication.instance() or QApplication([])
    yield app
    wait_until(lambda: not _JOBS)


@pytest.fixture
def cash(tmp_path):
    raw = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"10/01/2026,Checking A,Small purchase,-$4.00,$996.00\n"
        b"10/02/2026,Checking A,Large purchase,-$20.00,$976.00\n"
        b"10/03/2026,Checking A,Deposit,$10.00,$986.00\n"
    )
    evidence = build_source_evidence(raw, DEFINITION, suffix=".csv")
    path = tmp_path / "ordinary.db"
    with V2ProfileStore.create(path) as store:
        store.import_source(raw, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Synthetic checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
    return path, evidence


def cleanup(view):
    view.reason.clear()
    view.batch.clear()
    view.request_cancel()
    view.close()


def test_cash_shell_and_search_remain_responsive_during_worker_read(cash, monkeypatch):
    path, evidence = cash
    original = V2ProfileStore.source_interpretation_snapshot
    started, release = threading.Event(), threading.Event()
    threads = []

    def delayed(store, *args, **kwargs):
        threads.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        return original(store, *args, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "source_interpretation_snapshot", delayed)
    view = V2CashActivityReview(path, evidence.source_sha256)
    try:
        assert view.basis is None and not view.action_button.isEnabled()
        assert "Loading" in view.operation_status.text()
        view.show()
        wait_until(started.is_set)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        wait_until(lambda: bool(heartbeat))
        view.navigation.search.setText("Large")
        assert threads[0] != threading.get_ident()
        release.set()
        wait_for_review(view)
        assert view.navigation.proxy.rowCount() == 1
        assert view._current().description == "Large purchase"
    finally:
        release.set()
        cleanup(view)


def test_exact_sort_filter_and_next_pending_preserve_row_identity(cash):
    path, evidence = cash
    view = wait_for_review(V2CashActivityReview(path, evidence.source_sha256))
    try:
        view.table.sortByColumn(2, Qt.AscendingOrder)
        view.table.selectRow(0)
        assert view._current().amount_minor == -2000
        row_id = view._current().row_id
        view.refresh()
        wait_for_review(view)
        assert view._current().row_id == row_id
        view.navigation.next_pending()
        assert view._current().row_id != row_id
        view.navigation.search.setText("Deposit")
        assert view._current().amount_minor == 1000
        view.navigation.status_filter.setCurrentIndex(view.navigation.status_filter.findData("reviewed"))
        assert view.navigation.proxy.rowCount() == 0
        assert view._current() is None
    finally:
        cleanup(view)


def test_async_write_advances_pending_and_retains_correction_history(cash, monkeypatch):
    path, evidence = cash
    writes = []
    original = V2ProfileStore.post_reviewed_cash_category

    def record(store, *args, **kwargs):
        writes.append(threading.get_ident())
        return original(store, *args, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "post_reviewed_cash_category", record)
    view = wait_for_review(V2CashActivityReview(path, evidence.source_sha256))
    try:
        row_id = view._current().row_id
        view.purpose.setCurrentIndex(view.purpose.findData("expense"))
        view.category.setCurrentIndex(view.category.findData("expense:food"))
        view.reason.setText("Inspected purchase")
        assert view.action_button.isEnabled()
        view.action_button.click()
        wait_for_review(view)
        assert writes and writes[0] != threading.get_ident()
        assert view.navigation.proxy.rowCount() == 2
        assert view._current().row_id != row_id
        view.navigation.status_filter.setCurrentIndex(view.navigation.status_filter.findData("reviewed"))
        assert view.navigation.select_id(row_id)
        view.category.setCurrentIndex(view.category.findData("expense:travel"))
        view.reason.setText("Corrected category")
        view.action_button.click()
        wait_for_review(view)
        assert view._current().category_id == "expense:travel"
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (3,)
    finally:
        cleanup(view)


def test_confirmation_cannot_write_to_switched_workspace(cash, tmp_path, monkeypatch):
    path, evidence = cash
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    other = tmp_path / "other.db"
    V2ProfileStore.snapshot_to(path, other)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warnings.append(text))
    view = wait_for_review(V2CashActivityReview(path, evidence.source_sha256, workspace=workspace))
    try:
        view.purpose.setCurrentIndex(view.purpose.findData("expense"))
        view.category.setCurrentIndex(view.category.findData("expense:food"))
        view.reason.setText("Reviewed")

        def switch(*_args):
            workspace.profile_path = other
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", switch)
        view.action_button.click()
        assert warnings
        for profile in (path, other):
            with V2ProfileStore.open(profile, read_only=True) as store:
                assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        cleanup(view)


def test_staged_filter_keeps_hidden_rows_and_atomic_batch(cash, monkeypatch):
    path, evidence = cash
    view = wait_for_review(V2CashActivityReview(path, evidence.source_sha256))
    try:
        view.table.selectRow(0)
        view.purpose.setCurrentIndex(view.purpose.findData("expense"))
        view.category.setCurrentIndex(view.category.findData("expense:food"))
        view.batch.reason.setText("Reviewed selected purchases against source")
        view.batch.stage_selected()
        view.table.selectRow(1)
        view.purpose.setCurrentIndex(view.purpose.findData("expense"))
        view.category.setCurrentIndex(view.category.findData("expense:food"))
        view.batch.stage_selected()
        assert len(view.batch.staged) == 2
        view.navigation.search.setText("Deposit")
        assert "2 hidden" in view.batch.summary.text()
        view.navigation.search.setText("no matches")
        assert view.navigation.proxy.rowCount() == 0 and "2 hidden" in view.batch.summary.text()
        previews = []
        monkeypatch.setattr(view.batch, "show_preview", previews.append)
        view.batch.preview()
        wait_for_review(view)
        assert len(previews) == 1 and len(previews[0].entries) == 2
        preview = previews[0]
        view._submit_review_write(
            lambda store, cancelled: store.post_reviewed_ordinary_batch(preview, cancelled=cancelled),
            message="Batch saved",
            batch=True,
        )
        wait_for_review(view)
        assert not view.batch.staged
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (2,)
            assert store._active_consumed() == {row.row_id: row.amount.minor for row in evidence.payload.rows[:2]}
    finally:
        cleanup(view)


def test_unstaged_choices_survive_filtering_without_read_or_post(cash):
    path, evidence = cash
    view = wait_for_review(V2CashActivityReview(path, evidence.source_sha256))
    try:
        view.table.selectRow(0)
        view.purpose.setCurrentIndex(view.purpose.findData("expense"))
        view.category.setCurrentIndex(view.category.findData("expense:food"))
        view.reason.setText("Keep this explicit review draft")
        basis = view.basis
        view.navigation.search.setText("no matching source row")
        assert view.navigation.proxy.rowCount() == 0 and view.has_unsaved_draft
        view.navigation.search.clear()
        assert view.purpose.currentData() == "expense"
        assert view.category.currentData() == "expense:food"
        assert view.reason.text() == "Keep this explicit review draft"
        assert view.basis == basis and not view.review_pending
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        cleanup(view)


def test_jobs_coalesce_reads_and_writes_remain_owned_until_completion(cash):
    path, _ = cash
    started, release = threading.Event(), threading.Event()
    jobs = ProfileJobs(None, path)
    results = []
    jobs.completed.connect(lambda key, result: results.append((key, result)))

    def delayed(_store, _cancelled):
        started.set()
        assert release.wait(5)
        return "old"

    jobs.submit("old", delayed)
    wait_until(started.is_set)
    jobs.submit("latest", lambda _store, _cancelled: "new")
    release.set()
    wait_until(lambda: not jobs.pending)
    assert results == [("latest", "new")]
    started.clear()
    release.clear()
    jobs.submit("confirmed-write", delayed, write=True)
    wait_until(started.is_set)
    assert not jobs.close()
    assert not jobs.submit("wrong", lambda *_args: None)
    release.set()
    wait_until(lambda: not jobs.pending)
    assert jobs.close()


def test_cancelled_read_and_failure_never_reenable_posting(cash, monkeypatch):
    path, evidence = cash
    original = V2ProfileStore.source_interpretation_snapshot
    started, release = threading.Event(), threading.Event()

    def delayed(store, *args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(store, *args, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "source_interpretation_snapshot", delayed)
    view = V2CashActivityReview(path, evidence.source_sha256)
    try:
        wait_until(started.is_set)
        view._cancel_loading()
        release.set()
        wait_for_review(view)
        assert view.basis is None and not view.action_button.isEnabled()
        assert "cancelled" in view.operation_status.text()

        def failure(*_args, **_kwargs):
            raise OSError("Synthetic read unavailable")

        monkeypatch.setattr(V2ProfileStore, "source_interpretation_snapshot", failure)
        view.refresh()
        wait_for_review(view)
        assert view.basis is None and not view.model.rows
        assert "unavailable" in view.operation_status.text()
        monkeypatch.setattr(V2ProfileStore, "source_interpretation_snapshot", original)
        view.refresh()
        wait_for_review(view)
        assert view.basis is not None and len(view.model.rows) == 3
    finally:
        release.set()
        cleanup(view)


def test_card_explicit_date_batch_and_embedded_escape(tmp_path):
    from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview

    from .test_v2_card_purchase_review import _chase_profile

    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    section = evidence.payload.accounts[0]
    with V2ProfileStore.open(path) as store:
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    view = wait_for_review(V2CardPurchaseReview(workspace, evidence.source_sha256, embedded=True))
    try:
        assert view._current().status == "Enable assumed dates or enter a corrected date"
        view.purpose.setCurrentIndex(view.purpose.findData("expense"))
        view.category.setCurrentIndex(view.category.findData("expense:food"))
        view.accounting_date.setText("2026-03-17")
        view.batch.reason.setText("Explicit reviewed accounting date")
        view.batch.stage_selected()
        selection = next(iter(view.batch.staged.values()))
        assert selection.accounting_date.isoformat() == "2026-03-17"
        assert view.has_unsaved_draft
        view.reject()  # Escape cannot silently dismiss an embedded workspace editor.
        assert not view.jobs._closed
        previews = []
        view.batch.show_preview = previews.append
        view.batch.preview()
        wait_for_review(view)
        assert previews[0].entries[0].posting_date.isoformat() == "2026-03-17"
    finally:
        cleanup(view)


def test_reviewed_elsewhere_uses_owning_event_and_hides_ordinary_form(tmp_path, monkeypatch):
    from parsetrail.core.v2_preferences import V2Preferences
    from parsetrail.gui.v2_transfer_review import V2TransferReview

    from .test_v2_transfers import _profile

    path = tmp_path / "owned-payment.db"
    outgoing, incoming = _profile(path, bank_date="01/05/2026")
    with V2ProfileStore.open(path) as store:
        store.post_reviewed_transfer(outgoing, incoming, preferences=V2Preferences(), reason="Reviewed payment")
        source = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (outgoing,)
        ).fetchone()[0]
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    view = wait_for_review(V2CashActivityReview(path, source, workspace=workspace))
    opened = []
    monkeypatch.setattr(V2TransferReview, "exec", lambda dialog: opened.append(dialog._focus_row_id))
    try:
        assert view.navigation.proxy.rowCount() == 0
        view.navigation.status_filter.setCurrentIndex(view.navigation.status_filter.findData("reviewed"))
        assert view._current().row_id == outgoing
        assert view.purpose.isHidden() and view.category.isHidden() and view.reason.isHidden()
        assert "View reviewed" in view.action_button.text()
        assert "Pending" not in view.model.data(view.model.index(0, 5))
        view.action_button.click()
        wait_for_review(view)
        assert opened == [outgoing]
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store._active_consumed() == {outgoing: -2000, incoming: 2000}
    finally:
        cleanup(view)


def test_exact_batch_dialog_cancel_then_confirm_preserves_staged_choices(cash, monkeypatch):
    from PySide6.QtWidgets import QDialog, QPlainTextEdit

    path, evidence = cash
    view = wait_for_review(V2CashActivityReview(path, evidence.source_sha256))
    previews = []
    accepted = False

    def inspect(dialog):
        assert dialog.windowTitle() == "Confirm staged ordinary review"
        previews.append(dialog.findChild(QPlainTextEdit).toPlainText())
        return QDialog.Accepted if accepted else QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", inspect)
    try:
        view.purpose.setCurrentIndex(view.purpose.findData("expense"))
        view.category.setCurrentIndex(view.category.findData("expense:food"))
        view.batch.reason.setText("Explicitly reviewed purchase")
        view.batch.stage_selected()
        view.batch.preview()
        wait_for_review(view)
        assert len(view.batch.staged) == 1
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert "2026-10-01" in previews[0] and "-$4.00" in previews[0]
        assert "Explicitly reviewed purchase" in previews[0]
        assert "Asset value change: -$4.00" in previews[0] and "reviewed expense change: $4.00" in previews[0]
        accepted = True
        view.batch.preview()
        wait_for_review(view)
        assert not view.batch.staged
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)
    finally:
        cleanup(view)


def test_stale_batch_refusal_keeps_choices_without_partial_posting(cash, monkeypatch):
    from PySide6.QtWidgets import QDialog

    path, evidence = cash
    view = wait_for_review(V2CashActivityReview(path, evidence.source_sha256))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warnings.append(text))
    try:
        view.purpose.setCurrentIndex(view.purpose.findData("expense"))
        view.category.setCurrentIndex(view.category.findData("expense:food"))
        view.batch.reason.setText("Inspected source")
        view.batch.stage_selected()
        captured = []
        show = view.batch.show_preview
        monkeypatch.setattr(view.batch, "show_preview", captured.append)
        view.batch.preview()
        wait_for_review(view)
        with V2ProfileStore.open(path) as store:
            store.update_financial_account(FinancialAccount("cash", "Changed synthetic account", "asset", "synthetic"))
        monkeypatch.setattr(QDialog, "exec", lambda _dialog: QDialog.Accepted)
        show(captured[0])
        wait_for_review(view)
        assert warnings and view.batch.staged and view.batch.reason.text() == "Inspected source"
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        cleanup(view)


def test_profile_job_writes_serialize_across_views(cash):
    path, _ = cash
    first, second = ProfileJobs(None, path), ProfileJobs(None, path)
    started, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def hold(_store, _cancelled):
        started.set()
        assert release.wait(5)
        return "first"

    def following(_store, _cancelled):
        second_started.set()
        return "second"

    first.submit("first", hold, write=True)
    wait_until(started.is_set)
    second.submit("second", following, write=True)
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    wait_until(lambda: bool(heartbeat))
    assert not second_started.is_set()
    release.set()
    wait_until(lambda: not first.pending and not second.pending)
    assert second_started.is_set()
    assert first.close() and second.close()


def test_destroyed_host_cancels_python_read_and_discards_late_result(cash):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QWidget

    path, _ = cash
    host = QWidget()
    jobs = ProfileJobs(host, path)
    started, cancelled = threading.Event(), threading.Event()
    results = []
    jobs.completed.connect(lambda *_args: results.append(True))

    def cooperative(_store, cancellation_requested):
        started.set()
        deadline = time.monotonic() + 5
        while not cancellation_requested() and time.monotonic() < deadline:
            time.sleep(0.002)
        if cancellation_requested():
            cancelled.set()
        return "late"

    jobs.submit("read", cooperative)
    wait_until(started.is_set)
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    wait_until(cancelled.is_set)
    wait_until(lambda: not _JOBS)
    assert not results

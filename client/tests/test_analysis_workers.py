import hashlib
import sys
import threading
import time
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from parsetrail.core import cluster
from parsetrail.core.analysis import AnalysisCancelled
from parsetrail.core.migrate import upgrade_db
from parsetrail.core.orm import Accounts, AccountTypes, Transactions, create_database
from parsetrail.core.transactions import TransactionService
from parsetrail.gui.analysis_worker import LocalAnalysisJob
from parsetrail.gui.main_window import ParseTrail
from parsetrail.gui.transactions import RecurringTransactionsDialog
from parsetrail.gui.verification import TransactionReviewWindow
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def sessions(tmp_path):
    path = tmp_path / "worker.db"
    upgrade_db(path)
    Session = create_database(path)
    with Session.begin() as session:
        session.add(AccountTypes(AccountTypeID=1, AccountType="Checking", AssetType="Asset"))
        session.add(Accounts(AccountID=1, AccountName="Synthetic", AccountTypeID=1, CurrencyCode="USD"))
        for month in range(1, 4):
            session.add(
                Transactions(
                    AccountID=1,
                    PostingDate=date(2026, month, 1),
                    Amount=Decimal("-19.99"),
                    Balance=Decimal("5000"),
                    Description="Streaming subscription",
                    Fingerprint=hashlib.sha256(str(month).encode()).hexdigest(),
                    FingerprintVersion=1,
                    Verified=False,
                )
            )
    yield Session
    Session.kw["bind"].dispose()


def _wait(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(2)
    assert predicate(), "timed out waiting for analysis lifecycle"


def _dialog(Session, parent=None):
    dialog = RecurringTransactionsDialog(Session, parent=parent)
    dialog.start_date.setDate(QDate(2026, 1, 1))
    dialog.end_date.setDate(QDate(2026, 3, 31))
    return dialog


def _block_clustering(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = cluster.DBSCAN.fit_predict

    def blocked(self, *args, **kwargs):
        entered.set()
        assert release.wait(5), "test failed to release analysis"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(cluster.DBSCAN, "fit_predict", blocked)
    return entered, release


def _dispose(window, release=None):
    if release is not None:
        release.set()
    window.analysis_job.cancel()
    _wait(lambda: not window.analysis_job.busy)
    window.close()
    window.deleteLater()
    QApplication.processEvents()


@pytest.mark.usefixtures("app")
def test_database_sessions_and_calculation_run_off_gui_thread(sessions):
    main_thread = threading.get_ident()
    session_events = []

    @contextmanager
    def tracked_sessions():
        session_events.append(("open", threading.get_ident()))
        with sessions() as session:
            yield session
        session_events.append(("close", threading.get_ident()))

    dialog = _dialog(sessions)
    dialog.transaction_service = TransactionService(tracked_sessions)
    delivery_threads = []
    dialog.analysis_job.completed.connect(lambda _value: delivery_threads.append(threading.get_ident()))
    try:
        dialog.analyze_transactions()
        _wait(lambda: not dialog.analysis_job.busy)
        assert dialog.model.rowCount() == 3
        assert [kind for kind, _thread in session_events] == ["open", "close"]
        assert session_events[0][1] == session_events[1][1] != main_thread
        assert delivery_threads == [main_thread]
    finally:
        _dispose(dialog)


@pytest.mark.usefixtures("app")
def test_cancel_keeps_heartbeat_and_discards_result_then_allows_retry(sessions, monkeypatch):
    entered, release = _block_clustering(monkeypatch)
    dialog = _dialog(sessions)
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(threading.get_ident()))
    try:
        dialog.show()
        dialog.analyze_transactions()
        _wait(entered.is_set)
        assert not dialog.analysis_controls.isEnabled()
        timer.start()
        _wait(lambda: len(ticks) >= 3)
        assert set(ticks) == {threading.get_ident()}
        dialog.cancel_analysis_button.click()
        assert dialog.analysis_job.busy
        assert "Canceling" in dialog.status_label.text()
        release.set()
        _wait(lambda: not dialog.analysis_job.busy)
        assert dialog.clustered is None
        assert dialog.model.rowCount() == 0
        assert not dialog.save_button.isEnabled()
        assert dialog.analysis_controls.isEnabled()
        assert "canceled" in dialog.status_label.text()
        dialog.analyze_transactions()
        _wait(lambda: not dialog.analysis_job.busy)
        assert dialog.model.rowCount() == 3
    finally:
        timer.stop()
        _dispose(dialog, release)


@pytest.mark.parametrize("close_method", ["close", "escape", "button"])
@pytest.mark.usefixtures("app")
def test_dialog_close_waits_asynchronously_for_worker(sessions, monkeypatch, close_method):
    entered, release = _block_clustering(monkeypatch)
    dialog = _dialog(sessions)
    finished = []
    dialog.finished.connect(finished.append)
    try:
        dialog.show()
        dialog.analyze_transactions()
        _wait(entered.is_set)
        if close_method == "escape":
            QTest.keyClick(dialog, Qt.Key_Escape)
        elif close_method == "button":
            dialog.close_button.click()
        else:
            dialog.close()
        assert dialog.isVisible()
        assert dialog.analysis_job.busy
        assert not finished
        release.set()
        _wait(lambda: bool(finished))
        assert not dialog.analysis_job.busy
        assert not dialog.isVisible()
        assert dialog.clustered is None
    finally:
        _dispose(dialog, release)


def test_cancellation_after_worker_exit_suppresses_queued_result(app):
    owner = QWidget()
    job = LocalAnalysisJob(owner)
    results, cancellations = [], []
    job.completed.connect(results.append)
    job.cancelled.connect(lambda: cancellations.append(True))
    try:
        job.start(lambda _cancelled: "must not be displayed")
        assert job._thread.wait(2000)
        # No events processed yet: cancellation wins over queued completion.
        assert job.busy
        job.cancel()
        _wait(lambda: not job.busy)
        assert not results
        assert cancellations == [True]
    finally:
        job._shutdown()
        owner.deleteLater()
        app.processEvents()


def test_duplicate_start_is_rejected_and_errors_arrive_on_gui_thread(app):
    owner = QWidget()
    job = LocalAnalysisJob(owner)
    entered, release = threading.Event(), threading.Event()
    failures = []
    job.failed.connect(lambda: failures.append(threading.get_ident()))

    def work(_cancelled):
        entered.set()
        assert release.wait(5)
        raise ValueError("synthetic failure")

    try:
        job.start(work)
        _wait(entered.is_set)
        with pytest.raises(RuntimeError, match="already running"):
            job.start(work)
        release.set()
        _wait(lambda: not job.busy)
        assert failures == [threading.get_ident()]
    finally:
        release.set()
        job._shutdown()
        owner.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("action", ["cancel", "refresh", "close"])
@pytest.mark.usefixtures("app")
def test_review_snapshot_cancel_refresh_and_close_never_apply_old_clusters(sessions, monkeypatch, action):
    entered, release = _block_clustering(monkeypatch)
    window = TransactionReviewWindow(sessions)
    window.btn_auto_categorize.setEnabled(False)  # Preserve an initially disabled control.
    original = [(rec.transaction_id, rec.description, rec.amount, rec.verified) for rec in window.model._records]
    try:
        window.show()
        window.cluster_recurring_transactions()
        _wait(entered.is_set)
        assert not window.table_view.isEnabled()
        if action == "refresh":
            window.load_transactions()
        elif action == "close":
            window.close()
            assert window.isVisible()
        else:
            window.btn_cancel_analysis.click()
        release.set()
        _wait(lambda: not window.analysis_job.busy)
        assert all(rec.cluster is None for rec in window.model._records)
        assert [
            (rec.transaction_id, rec.description, rec.amount, rec.verified) for rec in window.model._records
        ] == original
        assert not window.btn_auto_categorize.isEnabled()
        if action == "close":
            assert not window.isVisible()
        else:
            assert window.table_view.isEnabled()
            window.cluster_recurring_transactions()
            _wait(lambda: not window.analysis_job.busy)
            assert all(rec.cluster == 0 for rec in window.model._records)
    finally:
        _dispose(window, release)


def test_main_window_close_waits_for_child_analysis(app, sessions, monkeypatch):
    entered, release = _block_clustering(monkeypatch)
    monkeypatch.setattr(ParseTrail, "initialize_all_elements", lambda self: None)
    monkeypatch.setattr(ParseTrail, "showMaximized", lambda self: None)
    original_hook = sys.excepthook
    parent = ParseTrail()
    window = TransactionReviewWindow(sessions, parent=parent)
    try:
        parent.show()
        window.cluster_recurring_transactions()
        _wait(entered.is_set)
        parent.close()
        assert parent.isVisible()
        assert window.analysis_job.busy
        assert not parent.isEnabled()
        release.set()
        _wait(lambda: not parent.isVisible())
        assert not window.analysis_job.busy
        assert all(rec.cluster is None for rec in window.model._records)
    finally:
        sys.excepthook = original_hook
        _dispose(window, release)
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_headless_analysis_honors_cancel_during_preprocessing():
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= 5

    frame = pd.DataFrame(
        {"Date": [date(2026, 1, 1)] * 100, "Amount": [Decimal("-10")] * 100, "Description": ["bill"] * 100}
    )
    with pytest.raises(AnalysisCancelled):
        cluster.recurring_transactions(frame, cancelled=cancelled)
    assert checks == 5


@pytest.mark.usefixtures("app")
def test_review_delete_on_close_waits_until_worker_has_exited(sessions, monkeypatch):
    entered, release = _block_clustering(monkeypatch)
    window = TransactionReviewWindow(sessions)
    window.setAttribute(Qt.WA_DeleteOnClose)  # Matches the real main-window adapter.
    destroyed, delivered = [], []
    window.destroyed.connect(lambda: destroyed.append(True))
    window.analysis_job.completed.connect(delivered.append)
    try:
        window.show()
        window.cluster_recurring_transactions()
        _wait(entered.is_set)
        window.close()
        assert not destroyed
        release.set()
        _wait(lambda: bool(destroyed))
        assert not delivered
    finally:
        release.set()
        if not destroyed:
            _dispose(window)


def test_programmatic_shutdown_cancels_and_joins_worker(app):
    owner = QWidget()
    job = LocalAnalysisJob(owner)
    entered, exited = threading.Event(), threading.Event()

    def work(cancelled):
        entered.set()
        deadline = time.monotonic() + 5
        while not cancelled() and time.monotonic() < deadline:
            exited.wait(0.005)
        exited.set()
        return "discard on shutdown"

    try:
        job.start(work)
        _wait(entered.is_set)
        job._shutdown()
        assert exited.is_set()
        assert not job._thread.isRunning()
        _wait(lambda: not job.busy)
    finally:
        job._shutdown()
        owner.deleteLater()
        app.processEvents()

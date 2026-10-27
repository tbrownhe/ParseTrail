"""Report reads stay lazy, scoped and independent of the GUI thread."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.gui.v2_reviewed_reports import _REPORT_READERS, V2ReviewedReportsDialog
from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import QApplication


def wait_for_reports(dialog, timeout=5000):
    """Drive normal queued Qt delivery; never disable production asynchronous reads."""
    deadline = time.monotonic() + timeout / 1000
    while dialog.reports_pending and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert not dialog.reports_pending, "Report read did not finish within the test deadline"
    return dialog


def _wait_until(predicate, timeout=5000):
    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert predicate()


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def profile(tmp_path):
    path = tmp_path / "reports.db"
    with V2ProfileStore.create(path) as store:
        store.add_financial_account(FinancialAccount("cash", "Synthetic checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
    return path


def test_shell_opens_and_remains_interactive_while_only_selected_view_reads(profile, monkeypatch):
    original = V2ProfileStore.reviewed_category_summary
    started, release = threading.Event(), threading.Event()
    reads = []
    main_thread = threading.get_ident()

    def delayed(store, **kwargs):
        reads.append((threading.get_ident(), kwargs["kind"], store.connection.in_transaction))
        started.set()
        assert release.wait(5)
        return original(store, **kwargs)

    def unexpected(*_args, **_kwargs):
        pytest.fail("Opening Spending must not calculate a hidden report")

    monkeypatch.setattr(V2ProfileStore, "reviewed_category_summary", delayed)
    monkeypatch.setattr(V2ProfileStore, "monthly_budget_summary", unexpected)
    monkeypatch.setattr(V2ProfileStore, "account_positions", unexpected)
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = V2ReviewedReportsDialog(profile)
    try:
        assert dialog.spending_report is None
        assert "Loading" in dialog.total.text()
        dialog.show()
        _wait_until(started.is_set)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        _wait_until(lambda: bool(heartbeat))
        assert dialog.isVisible()
        assert reads == [(reads[0][0], "expense", True)]
        assert reads[0][0] != main_thread
        release.set()
        wait_for_reports(dialog)
        assert dialog.spending_report.total_minor == 0
        assert dialog.budget_report is None
        assert dialog.positions_report is None
    finally:
        release.set()
        dialog.close()
        _wait_until(lambda: not _REPORT_READERS)
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_filter_edits_coalesce_and_superseded_read_cannot_publish(profile, monkeypatch):
    original = V2ProfileStore.reviewed_category_summary
    started, release = threading.Event(), threading.Event()
    reads = []

    def delayed(store, **kwargs):
        reads.append((kwargs["start"], kwargs["end"]))
        if len(reads) == 1:
            started.set()
            assert release.wait(5)
        return original(store, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "reviewed_category_summary", delayed)
    dialog = V2ReviewedReportsDialog(profile)
    try:
        _wait_until(started.is_set)
        dialog.start.setDate(QDate(2026, 3, 1))
        dialog.end.setDate(QDate(2026, 4, 1))
        dialog.start.setDate(QDate(2026, 4, 1))
        dialog.end.setDate(QDate(2026, 5, 1))
        assert dialog.spending_report is None
        assert not dialog.export_button.isEnabled()
        release.set()
        wait_for_reports(dialog)
        assert len(reads) == 2
        assert reads[-1] == (date(2026, 4, 1), date(2026, 5, 1))
        assert dialog.spending_report.start == date(2026, 4, 1)
        assert dialog.spending_report.end == date(2026, 5, 1)
    finally:
        release.set()
        dialog.close()
        _wait_until(lambda: not _REPORT_READERS)


def test_tab_dates_compact_positions_details_and_history(profile):
    with V2ProfileStore.open(profile) as store:
        store.add_financial_account(FinancialAccount("card", "Synthetic checking", "liability", "synthetic"))
    dialog = V2ReviewedReportsDialog(profile)
    try:
        wait_for_reports(dialog)
        assert not dialog.period_controls.isHidden()
        dialog.tabs.setCurrentIndex(2)
        assert dialog.period_controls.isHidden()
        assert dialog.export_button.isHidden()
        wait_for_reports(dialog)
        assert dialog.budget_report is not None
        assert dialog.positions_report is None
        dialog.tabs.setCurrentIndex(4)
        wait_for_reports(dialog)
        assert dialog.positions_report is not None
        assert dialog.positions_model.rowCount() == 2
        assert dialog.positions_table.isColumnHidden(2)
        assert not dialog.positions_table.isColumnHidden(1)
        assert {dialog.positions_model.data(dialog.positions_model.index(i, 1)) for i in range(2)} == {
            "Asset",
            "Liability",
        }
        assert not dialog.positions_table.isColumnHidden(3)
        assert dialog.position_details.isHidden()
        assert dialog.history_panel.isHidden()
        selected = dialog.positions_table.currentIndex().row()
        dialog.show_details.setChecked(True)
        dialog.show_history.setChecked(True)
        assert not dialog.position_details.isHidden()
        assert not dialog.positions_table.isColumnHidden(2)
        assert not dialog.history_panel.isHidden()
        assert dialog.positions_table.currentIndex().row() == selected
        assert "Unknown" == dialog.positions_model.data(dialog.positions_model.index(0, 3))
        assert "pending" in dialog.qualification.text()
        assert "across the whole profile and all dates" in dialog.qualification.text()
    finally:
        dialog.close()
        _wait_until(lambda: not _REPORT_READERS)


def test_result_from_previous_profile_is_discarded(profile, tmp_path, monkeypatch):
    other = tmp_path / "other.db"
    with V2ProfileStore.create(other) as store:
        store.add_category_account("expense:other", "Other profile category", "expense")
    original = V2ProfileStore.reviewed_category_summary
    started, release = threading.Event(), threading.Event()
    first = True

    def delayed(store, **kwargs):
        nonlocal first
        if first:
            first = False
            started.set()
            assert release.wait(5)
        return original(store, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "reviewed_category_summary", delayed)
    dialog = V2ReviewedReportsDialog(profile)
    try:
        _wait_until(started.is_set)
        dialog.profile = other
        release.set()
        wait_for_reports(dialog)
        assert [row.name for row in dialog.model.rows] == ["Other profile category"]
        assert dialog._loaded[0][0] == str(other)
    finally:
        release.set()
        dialog.close()
        _wait_until(lambda: not _REPORT_READERS)


def test_failed_read_clears_shared_success_and_can_retry(profile, monkeypatch):
    dialog = V2ReviewedReportsDialog(profile)
    try:
        wait_for_reports(dialog)
        assert dialog.spending_report is not None
        original = V2ProfileStore.account_positions

        def unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError("synthetic read failure")

        monkeypatch.setattr(V2ProfileStore, "account_positions", unavailable)
        dialog.tabs.setCurrentIndex(4)
        wait_for_reports(dialog)
        assert dialog.spending_report is None
        assert dialog.positions_report is None
        assert dialog.model.rowCount() == 0
        assert "unavailable" in dialog.total.text()
        assert not dialog.export_button.isEnabled()
        monkeypatch.setattr(V2ProfileStore, "account_positions", original)
        dialog._refresh_all_reports()
        wait_for_reports(dialog)
        assert dialog.positions_report is not None
    finally:
        dialog.close()
        _wait_until(lambda: not _REPORT_READERS)


def test_closing_during_read_is_nonblocking_and_worker_finishes_safely(profile, monkeypatch):
    original = V2ProfileStore.reviewed_category_summary
    started, release = threading.Event(), threading.Event()

    def delayed(store, **kwargs):
        started.set()
        assert release.wait(5)
        return original(store, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "reviewed_category_summary", delayed)
    dialog = V2ReviewedReportsDialog(profile)
    dialog.show()
    try:
        _wait_until(started.is_set)
        dialog.reject()
        assert not dialog.isVisible()
        assert _REPORT_READERS
        assert dialog.spending_report is None
    finally:
        release.set()
        _wait_until(lambda: not _REPORT_READERS)
        assert dialog.spending_report is None


def test_application_exit_drains_python_read_before_interpreter_teardown(profile):
    """A real child exit must not destroy a running native QThread."""
    script = textwrap.dedent(
        """
        import json
        import sys
        import threading
        import time
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from parsetrail.core.v2_profile_store import V2ProfileStore
        from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog, _REPORT_READERS

        app = QApplication([])
        started, closed = threading.Event(), threading.Event()
        original_read = V2ProfileStore.reviewed_category_summary
        original_exit = V2ProfileStore.__exit__

        def delayed(store, **kwargs):
            started.set()
            # Model Python validation, which SQLite cancellation cannot interrupt.
            time.sleep(0.4)
            return original_read(store, **kwargs)

        def connection_exit(store, *args):
            original_exit(store, *args)
            closed.set()

        V2ProfileStore.reviewed_category_summary = delayed
        V2ProfileStore.__exit__ = connection_exit
        dialog = V2ReviewedReportsDialog(Path(sys.argv[1]))
        dialog.show()
        result = {}

        def exit_when_started():
            if not started.is_set():
                QTimer.singleShot(5, exit_when_started)
                return
            dialog.reject()
            result['dialog_close_returned_before_connection_closed'] = not closed.is_set()
            app.quit()

        QTimer.singleShot(0, exit_when_started)
        app.exec()
        result['connection_closed_before_app_returned'] = closed.is_set()
        result['retained_readers'] = len(_REPORT_READERS)
        print(json.dumps(result), flush=True)
        """
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "client/src"), str(root / "client")))
    environment["QT_QPA_PLATFORM"] = "offscreen"
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    result = subprocess.run(
        [sys.executable, "-c", script, str(profile)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome == {
        "dialog_close_returned_before_connection_closed": True,
        "connection_closed_before_app_returned": True,
        "retained_readers": 0,
    }
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("start_read", [False, True])
def test_hidden_dialog_close_and_exit_without_app_exec(profile, tmp_path, start_read):
    script = textwrap.dedent(
        """
        import json
        import sys
        import threading
        import time
        from pathlib import Path
        from PySide6.QtWidgets import QApplication
        from parsetrail.core.v2_profile_store import V2ProfileStore
        from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog, _REPORT_READERS

        app = QApplication([])
        profile, marker = map(Path, sys.argv[1:3])
        start_read = sys.argv[3] == 'True'
        started = threading.Event()
        original_read = V2ProfileStore.reviewed_category_summary
        original_exit = V2ProfileStore.__exit__

        def delayed(store, **kwargs):
            started.set()
            time.sleep(0.4)
            return original_read(store, **kwargs)

        def connection_exit(store, *args):
            original_exit(store, *args)
            marker.write_text('closed')

        V2ProfileStore.reviewed_category_summary = delayed
        V2ProfileStore.__exit__ = connection_exit
        dialog = V2ReviewedReportsDialog(profile)
        assert not dialog.isVisible()
        if start_read:
            deadline = time.monotonic() + 5
            while not started.is_set() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            assert started.is_set()
        dialog.close()
        app.processEvents()
        print(json.dumps({
            'started': started.is_set(),
            'closed_before_connection_close': not marker.exists(),
            'queued_read': dialog._read_timer.isActive(),
            'retained_readers': len(_REPORT_READERS),
        }), flush=True)
        # No app.exec()/quit(): actual interpreter teardown must safely drain.
        """
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "client/src"), str(root / "client")))
    environment["QT_QPA_PLATFORM"] = "offscreen"
    marker = tmp_path / "connection-closed.txt"
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    result = subprocess.run(
        [sys.executable, "-c", script, str(profile), str(marker), str(start_read)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "started": start_read,
        "closed_before_connection_close": True,
        "queued_read": False,
        "retained_readers": int(start_read),
    }
    assert marker.exists() == start_read
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before

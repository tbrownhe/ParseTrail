"""Integrated context, draft and confirmed-operation ownership in the workspace."""

from threading import Event

from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from .test_v2_document_browser import _populated_workspace, wait_for_inventory
from .test_v2_reports_responsiveness import wait_for_reports
from .test_v2_workspace_window import DEFINITION, SOURCE
from .v2_job_wait import wait_for_jobs


def test_navigation_embeds_working_views_and_keeps_report_period(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = V2WorkspaceWindow(_populated_workspace(tmp_path))
    try:
        wait_for_inventory(window)
        window.navigation.setCurrentRow(1)
        review = window._review_widget
        wait_for_jobs(review)
        assert review.embedded and review.model.rowCount() == 1
        assert "Change" in window.source_review_button.text()
        window.navigation.setCurrentRow(3)
        reports = window._reports_view
        reports.start.setDate(QDate(2026, 10, 1))
        reports.end.setDate(QDate(2026, 11, 1))
        wait_for_reports(reports)
        window.navigation.setCurrentRow(2)
        wait_for_reports(window._positions_view)
        assert window._positions_view.positions_model.rowCount() == 1
        window.navigation.setCurrentRow(3)
        assert window._reports_view is reports
        assert reports.start.date() == QDate(2026, 10, 1)
        window.navigation.setCurrentRow(1)
        assert window._review_widget is review
    finally:
        window.close()
        app.processEvents()


def test_changing_document_preserves_draft_until_explicit_discard(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    workspace = _populated_workspace(tmp_path)
    other = SOURCE.replace(b"Coffee", b"Tea")
    evidence = build_source_evidence(other, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(other, DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
    window = V2WorkspaceWindow(workspace)
    try:
        wait_for_inventory(window)
        window.navigation.setCurrentRow(1)
        wait_for_jobs(window._review_widget)
        source = window._selected_source()
        view = window._review_widget
        view.reason.setText("Unapplied explicit review note")
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        window.sources.setCurrentRow(1)
        assert window._selected_source() == source
        assert window._review_widget is view and view.has_unsaved_draft
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        window.sources.setCurrentRow(1)
        wait_for_jobs(window._review_widget)
        assert window._selected_source() != source
        assert window._review_widget is not view
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        window.close()
        app.processEvents()


def test_confirmed_backup_does_not_block_events_or_lose_close_outcome(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = V2WorkspaceWindow(_populated_workspace(tmp_path))
    destination = tmp_path / "verified.dbb"
    started, release = Event(), Event()
    original = V2ProfileStore.snapshot_to
    notices = []

    def delayed(source, target):
        started.set()
        assert release.wait(10)
        return original(source, target)

    monkeypatch.setattr(V2ProfileStore, "snapshot_to", delayed)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(destination), ""))
    monkeypatch.setattr("parsetrail.gui.v2_workspace_window.show_path_notice", lambda *args: notices.append(args))
    try:
        wait_for_inventory(window)
        window.show()
        window._backup_profile()
        pulses = []
        QTimer.singleShot(0, lambda: pulses.append(True))
        from time import monotonic, sleep

        deadline = monotonic() + 5
        while not started.is_set() and monotonic() < deadline:
            app.processEvents()
            sleep(0.005)
        app.processEvents()
        assert started.is_set() and pulses
        assert not window.close()
        assert window.isVisible()
        release.set()
        wait_for_inventory(window)
        app.processEvents()
        assert destination.is_file() and len(notices) == 1
        assert not window.isVisible()
    finally:
        release.set()
        wait_for_inventory(window)
        window.close()
        app.processEvents()


def test_healthy_backup_restore_is_independent_of_damaged_current_profile(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    workspace = _populated_workspace(tmp_path)
    backup, restored = tmp_path / "healthy.dbb", tmp_path / "restored.db"
    V2ProfileStore.snapshot_to(workspace.profile_path, backup)
    window = V2WorkspaceWindow(workspace)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(backup), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(restored), ""))
    try:
        wait_for_inventory(window)
        workspace.profile_path.write_bytes(b"Synthetic damaged current profile")
        window._restore_profile()
        wait_for_inventory(window)
        assert not warnings
        assert window.workspace.profile_path == restored.resolve()
        with V2ProfileStore.open(restored, read_only=True) as store:
            assert len(store.source_ids()) == 1
    finally:
        window.close()
        app.processEvents()

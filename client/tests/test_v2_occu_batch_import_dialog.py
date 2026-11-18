"""The reusable OCCU batch dialog keeps per-file and per-account draft boundaries."""

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_batch_import import V2BatchImportWorker
from parsetrail.gui.v2_import_account_review import V2ImportAccountReview
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .qt_journey_helpers import JourneyArtifacts, choose_combo, enter_text
from .test_v2_import_account_review import group
from .test_v2_occu_batch_import import occu_workspace


def create(qtbot, view, name, product):
    choose_combo(qtbot, view.account_choice, "__create_new_account__")
    enter_text(qtbot, view.name, name)
    assert view.institution.currentData() == "occu" and not view.institution.isEnabled()
    profile = next(
        view.product.itemData(index)
        for index in range(1, view.product.count())
        if view.product.itemData(index).product_type == product
    )
    choose_combo(qtbot, view.product, profile)


@pytest.mark.parametrize("automatic", [False, True])
def test_fresh_two_account_batch_reuses_dialog_and_commits_each_file(qtbot, tmp_path, automatic):
    workspace, paths = occu_workspace(tmp_path)
    view = V2ImportAccountReview(workspace.institutions())
    qtbot.addWidget(view)
    view.abbreviated_matching_changed.connect(workspace.set_allow_abbreviated_account_matching)
    view.import_preview_mode_changed.connect(workspace.set_import_preview_mode)
    worker = V2BatchImportWorker(workspace, paths)
    requests = []

    def present(request):
        requests.append(request)
        view.present(request)

    worker.import_review_requested.connect(present)
    worker.start()
    try:
        qtbot.waitUntil(lambda: len(requests) == 1, timeout=15000)
        assert view.groups.rowCount() == 2
        create(qtbot, view, "Primary savings", "savings")
        group(qtbot, view, 1)
        create(qtbot, view, "Remarkable checking", "checking")
        assert view.next_button.isEnabled()
        if automatic:
            workspace.set_allow_abbreviated_account_matching(True)
            workspace.set_import_preview_mode("when_needed")
        qtbot.mouseClick(view.next_button, Qt.LeftButton)
        assert view.import_button.isEnabled()
        qtbot.mouseClick(view.import_button, Qt.LeftButton)
        if not automatic:
            qtbot.waitUntil(lambda: len(requests) == 2, timeout=15000)
            assert view.groups.rowCount() == 2 and not view._drafts
            account_ids = {account.product_type: account.id for account in requests[1].review.accounts}
            choose_combo(qtbot, view.account_choice, account_ids["savings"])
            group(qtbot, view, 1)
            choose_combo(qtbot, view.account_choice, account_ids["checking"])
            qtbot.mouseClick(view.next_button, Qt.LeftButton)
            qtbot.mouseClick(view.import_button, Qt.LeftButton)
        qtbot.waitUntil(lambda: not worker.isRunning(), timeout=20000)
        worker.wait()
        assert worker.error is None
        assert [(item.status, item.error_code) for item in worker.result.files] == [
            ("imported", None),
            ("imported", None),
        ]
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert len(store.source_ids()) == 2 and len(store.financial_accounts()) == 2
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        worker.cancel()
        if view.request is not None and not view.request.decided.is_set():
            view.request.finish(None)
        worker.wait(10000)
        view.close()
        worker.deleteLater()


@pytest.mark.parametrize("automatic", [False, True])
def test_fresh_occu_batch_through_workspace_window(qtbot, tmp_path, monkeypatch, journey_artifacts, automatic):
    from parsetrail.gui.v2_batch_import import V2BatchImportReport
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    workspace, paths = occu_workspace(tmp_path, inactive_savings=True)
    reports = []
    monkeypatch.setattr(V2BatchImportReport, "exec", lambda dialog: reports.append(dialog))
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.show()
    artifacts = JourneyArtifacts(journey_artifacts, QApplication.instance(), (1050, 700))
    worker = None
    try:
        qtbot.waitUntil(lambda: not window.inventory_pending and not window.profile_jobs.pending, timeout=15000)
        window.start_batch_import(paths)
        worker = window.import_worker
        qtbot.waitUntil(lambda: window.import_preview is not None, timeout=15000)
        view = window.import_preview
        assert [group.row_count for group in view.review.groups] == [0, 1]
        create(qtbot, view, "Primary savings", "savings")
        group(qtbot, view, 1)
        create(qtbot, view, "Remarkable checking", "checking")
        if automatic:
            qtbot.mouseClick(view.abbreviated_matching, Qt.LeftButton)
            choose_combo(qtbot, view.preview_mode, "when_needed")
        artifacts.capture("two-accounts-ready", view)
        qtbot.mouseClick(view.next_button, Qt.LeftButton)
        artifacts.capture("two-accounts-confirmation", view)
        qtbot.mouseClick(view.import_button, Qt.LeftButton)
        if not automatic:
            qtbot.waitUntil(lambda: view.request.path == paths[1] and view.accounts_page.isEnabled(), timeout=15000)
            account_ids = {account.product_type: account.id for account in view.review.accounts}
            choose_combo(qtbot, view.account_choice, account_ids["savings"])
            group(qtbot, view, 1)
            choose_combo(qtbot, view.account_choice, account_ids["checking"])
            qtbot.mouseClick(view.next_button, Qt.LeftButton)
            qtbot.mouseClick(view.import_button, Qt.LeftButton)
        qtbot.waitUntil(lambda: window.import_worker is None and bool(reports), timeout=20000)
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert len(store.source_ids()) == 2 and len(store.financial_accounts()) == 2
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert "2 imported, 0 failed" in window.status.text()
        qtbot.waitUntil(lambda: not window.inventory_pending and not window.profile_jobs.pending, timeout=15000)
        artifacts.capture("batch-completed", window)
    finally:
        if window.import_worker is not None:
            worker.cancel()
            if window.import_preview is not None and window.import_preview.request is not None:
                window.import_preview.request.finish(None)
            worker.wait(10000)
            qtbot.waitUntil(lambda: window.import_worker is None, timeout=15000)
        window.close()

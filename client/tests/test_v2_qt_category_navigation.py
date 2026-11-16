"""Category setup is reachable in review and refreshes retained review drafts."""

from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
from parsetrail.gui.v2_categories import V2CategoryDialog
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from .ordinary_staging_helpers import review_reason
from .qt_journey_helpers import JourneyArtifacts, ModalSteps, choose_combo, click_list_row, close_dialog, enter_text
from .test_v2_document_browser import _populated_workspace


def test_accounts_category_setup_refreshes_review_without_reload_and_cancel_keeps_draft(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts
):
    workspace = _populated_workspace(tmp_path)
    window = V2WorkspaceWindow(workspace)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    qtbot.addWidget(window)
    window.show()
    modals = ModalSteps(qtbot)
    try:
        qtbot.waitUntil(lambda: not window.inventory_pending, timeout=15000)
        click_list_row(qtbot, window.navigation, window.REVIEW)
        review = window.findChild(V2CashActivityReview)
        assert review is not None
        qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
        choose_combo(qtbot, review.purpose, "expense")
        enter_text(qtbot, review_reason(review), "Keep my review reason while setting up categories")
        assert review.category.count() == 1
        assert review.manage_categories_button.isEnabled()
        row_id = review.navigation.current().row_id
        click_list_row(qtbot, window.navigation, window.ACCOUNTS)

        def add_category(dialog):
            choose_combo(qtbot, dialog.add_kind, "expense")
            enter_text(qtbot, dialog.add_name, "Meals")
            qtbot.mouseClick(dialog.add_button, Qt.LeftButton)
            close_dialog(qtbot, dialog)

        modals.arm((V2CategoryDialog, add_category))
        qtbot.mouseClick(window.categories_button, Qt.LeftButton)
        modals.finish()
        click_list_row(qtbot, window.navigation, window.REVIEW)
        qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
        assert review.category.findText("Meals") >= 0
        assert review_reason(review).text() == "Keep my review reason while setting up categories"
        artifacts.capture("accounts-category-refreshed-draft", window)
        assert review.navigation.current().row_id == row_id
        assert review.purpose.currentData() == "expense"
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            category_id = store.category_accounts()[0].id
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
        choose_combo(qtbot, review.category, category_id)
        qtbot.mouseClick(review.batch.stage_button, Qt.LeftButton)
        staged = dict(review.batch.staged)
        assert staged
        before = workspace.profile_path.read_bytes()

        modals.arm((V2CategoryDialog, lambda dialog: close_dialog(qtbot, dialog)))
        qtbot.mouseClick(review.manage_categories_button, Qt.LeftButton)
        modals.finish()
        qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
        assert workspace.profile_path.read_bytes() == before
        assert review.batch.staged == staged
        assert review.navigation.current().row_id == row_id
        assert review.category.currentData() == category_id
        assert review.purpose.currentData() == "expense"
        assert review_reason(review).text() == "Keep my review reason while setting up categories"
        artifacts.capture("category-cancel-preserved-draft", window)
    finally:
        # Teardown alone approves draft discard; journey interactions above use
        # the real category dialogs and preserve their authored decisions.
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        window.close()

from datetime import date
import pytest
from devtools.qt_heap_crash.journey_snapshot import (
    empty_workspace, qt_file_dialogs, JourneyArtifacts, ModalSteps, prepare_close,
    ready, review_ready, assert_books, confirm_new_import, click_table_text,
    choose_combo, enter_text, close_dialog, select_file, Qt, QFileDialog,
    V2WorkspaceWindow, V2ImportAccountReview, V2ProfileStore, V2CategoryDialog,
    V2EvidencePreview, V2ReviewedEntryDrilldown, QDialog, QDialogButtonBox,
    QPlainTextEdit, QMessageBox, QDateTimeEdit,
)
@pytest.mark.parametrize('size', [(1050, 700)] * 4, ids=[str(i) for i in range(4)])
def test_expense_review_correction(qtbot, qapp, empty_workspace, tmp_path, journey_artifacts, size):
    workspace, source = empty_workspace
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    modals = ModalSteps(qtbot)
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window, before_close_func=lambda widget: prepare_close(qtbot, widget))
    window.resize(*size)
    window.show()
    assert window.inventory_pending and 'Loading' in window.inventory_status.text()
    artifacts.capture('00-loading-document-inventory', window, settle=False)
    ready(qtbot, window)
    assert window.sources.count() == 0
    assert 'Import' in window.inventory_status.text()
    assert not window.review_document_button.isEnabled()
    artifacts.capture('01-empty-profile', window)
    modals.arm((QFileDialog, lambda dialog: qtbot.keyClick(dialog, Qt.Key_Escape)))
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    modals.finish()
    assert window.sources.count() == 0
    modals.arm((QFileDialog, lambda dialog: select_file(qtbot, dialog, source)), (V2ImportAccountReview, lambda dialog: confirm_new_import(qtbot, dialog)))
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: window.import_worker is None, timeout=20000)
    ready(qtbot, window)
    assert window.sources.count() == 1
    assert '2026-10-01' in window.sources.item(0).text()
    assert '2026-10-03' in window.sources.item(0).text()
    assert 'review' in window.review_document_button.text().lower()
    assert_books(workspace.profile_path, entries=0)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        source_id = store.source_ids()[0]
        original_evidence = store.load_import(source_id).evidence
        assert len(store.financial_accounts()) == 1
        assert store.financial_accounts()[0].product_type == 'checking'
        assert store.source_account_bindings(source_id)[0].ledger_account_id is not None
    artifacts.capture('02-imported-and-assigned-pending-review', window)
    qtbot.mouseClick(window.review_document_button, Qt.LeftButton)
    ready(qtbot, window)
    review = review_ready(qtbot, window)
    assert 'Everyday checking' in window.review_document_selector.currentText()
    assert '2026-10-01' in window.review_document_selector.currentText()
    assert not review.action_button.isEnabled()
    artifacts.capture('05-assigned-blocked-no-purpose-category', window)
    click_table_text(qtbot, review.table, 'Coffee')
    choose_combo(qtbot, review.purpose, 'expense')
    enter_text(qtbot, review.reason, 'Draft retained while managing categories')
    assert review.manage_categories_button.isEnabled()

    def author_categories(dialog):
        for name, kind in (('Food', 'expense'), ('Travel', 'expense')):
            enter_text(qtbot, dialog.add_name, name)
            choose_combo(qtbot, dialog.add_kind, kind)
            qtbot.mouseClick(dialog.add_button, Qt.LeftButton)
        assert dialog.categories.count() == 2
        close_dialog(qtbot, dialog)
    modals.arm((V2CategoryDialog, author_categories))
    qtbot.mouseClick(review.manage_categories_button, Qt.LeftButton)
    modals.finish()
    ready(qtbot, window)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        category_ids = {category.name: category.id for category in store.category_accounts()}
    review = review_ready(qtbot, window)
    assert review.reason.text() == 'Draft retained while managing categories'
    assert review.purpose.currentData() == 'expense'
    artifacts.capture('06-ready-for-review', window)
    choose_combo(qtbot, review.category, category_ids['Food'])
    qtbot.mouseClick(review.batch.stage_button, Qt.LeftButton)
    staged = dict(review.batch.staged)
    assert len(staged) == 1
    modals.arm((V2CategoryDialog, lambda dialog: close_dialog(qtbot, dialog)))
    qtbot.mouseClick(review.manage_categories_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
    assert review.batch.staged == staged
    assert review.reason.text() == 'Draft retained while managing categories'
    assert review.category.currentData() == category_ids['Food']
    assert_books(workspace.profile_path, entries=0)
    artifacts.capture('06-category-manager-cancel-keeps-staged-choices', window)
    qtbot.mouseClick(review.batch.clear_button, Qt.LeftButton)

    def confirm(expected, *, accept=True, screenshot=None):

        def interact(dialog):
            assert all((text in dialog.text() for text in expected)), dialog.text()
            if screenshot:
                artifacts.capture(screenshot, dialog)
            qtbot.mouseClick(dialog.button(QMessageBox.Yes if accept else QMessageBox.No), Qt.LeftButton)
        return interact

    def confirm_staged(expected, *, screenshot=None):

        def interact(dialog):
            text = dialog.findChild(QPlainTextEdit).toPlainText()
            assert all((value in text for value in expected)), text
            if screenshot:
                artifacts.capture(screenshot, dialog)
            buttons = dialog.findChild(QDialogButtonBox)
            button = next((button for button in buttons.buttons() if button.text().startswith('Confirm and post')))
            qtbot.mouseClick(button, Qt.LeftButton)
        return interact
    for description, purpose, category, expected_amount in (('Coffee', 'expense', 'Food', '$4.00'),):
        click_table_text(qtbot, review.table, description)
        choose_combo(qtbot, review.purpose, purpose)
        choose_combo(qtbot, review.category, category_ids[category])
        enter_text(qtbot, review.reason, f'Reviewed {description} from original statement')
        assert review.batch.stage_button.isEnabled()
        assert not review.action_button.isVisible()
        if purpose == 'expense':
            qtbot.keyClick(review.batch.stage_button, Qt.Key_Space)
        else:
            qtbot.mouseClick(review.batch.stage_button, Qt.LeftButton)
        assert len(review.batch.staged) == 1
        assert_books(workspace.profile_path, entries=0 if purpose == 'expense' else 1, pending=3 if purpose == 'expense' else 2)
        modals.arm((QDialog, confirm_staged([description, expected_amount, 'Everyday checking', '2026-10-0'], screenshot=f'07-confirm-{purpose}')))
        qtbot.mouseClick(review.batch.preview_button, Qt.LeftButton)
        modals.finish()
        qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
        ready(qtbot, window)
        assert 'Saved 1 reviewed entries together' in review.operation_status.text()
    assert_books(workspace.profile_path, entries=1, pending=2)
    artifacts.capture('08-two-reviewed-one-pending', window)

    def inspect_evidence(dialog):
        assert dialog.rows_model.rowCount() == 3
        assert dialog.rows_model.data(dialog.rows_model.index(0, 4)) == 'Coffee'
        assert 'row' in str(dialog.rows_model.data(dialog.rows_model.index(0, 7))).lower()
        artifacts.capture('09-source-evidence', dialog)
        close_dialog(qtbot, dialog)
    modals.arm((V2EvidencePreview, inspect_evidence))
    qtbot.mouseClick(review.preview_source_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
    assert_books(workspace.profile_path, entries=1, pending=2)
    qtbot.mouseClick(window.document_spending_button, Qt.LeftButton)
    reports = window._reports_view
    qtbot.waitUntil(lambda: not reports.reports_pending, timeout=15000)
    assert reports.start.date().toPython() == date(2026, 10, 1)
    assert reports.end.date().toPython() == date(2026, 10, 4)
    assert '$4.00' in reports.total.text()
    assert 'All profile accounts' in window.report_context.text()
    assert '2' in reports.qualification.text() and 'pending' in reports.qualification.text()
    artifacts.capture('10-reviewed-spending-with-pending-limit', window)
    click_table_text(qtbot, reports.table, 'Food')

    def open_correction(dialog):
        assert dialog.model.rowCount() == 1
        assert 'Coffee' in dialog.model.data(dialog.model.index(0, 1))
        assert 'Everyday checking' in dialog.source.currentText()
        artifacts.capture('11-inspect-exact-reviewed-entry', dialog)
        qtbot.mouseClick(dialog.review_source_button, Qt.LeftButton)
    modals.arm((V2ReviewedEntryDrilldown, open_correction))
    qtbot.mouseClick(reports.inspect_button, Qt.LeftButton)
    modals.finish()
    review = review_ready(qtbot, window)
    assert review.navigation.status_filter.currentData() == 'all'
    assert review.navigation.current().description == 'Coffee'
    assert not (review.operation_status.isVisible() and 'Income posted' in review.operation_status.text())
    choose_combo(qtbot, review.category, category_ids['Travel'])
    enter_text(qtbot, review.reason, 'Correct Food to Travel while retaining purpose')
    modals.arm((QMessageBox, confirm(['Food', 'Travel', '$0.00', 'reversed'], screenshot='12-confirm-category-correction')))
    qtbot.mouseClick(review.action_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
    ready(qtbot, window)
    assert_books(workspace.profile_path, entries=3, corrections=1, pending=2)

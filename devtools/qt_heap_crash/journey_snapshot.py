"""A complete disposable desktop journey driven through Qt mouse/keyboard events.

Fixtures create only an empty profile and an ephemeral fixture-signed catalog.
All imports, accounts, assignments, categories and journal decisions use the UI.
This is a scripted software test, not evidence of unfamiliar-person usability.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from threading import Event

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_categories import V2CategoryDialog
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
from parsetrail.gui.v2_import_account_review import V2ImportAccountReview
from parsetrail.gui.v2_report_drilldown import V2ReviewedEntryDrilldown
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
)
from scripts.v2_catalog_release import signed_catalog_bytes

from .qt_account_import_helpers import confirm_new_import
from .qt_journey_helpers import (
    JourneyArtifacts,
    ModalSteps,
    choose_combo,
    click_menu,
    click_table_text,
    close_dialog,
    enter_text,
    select_file,
)

SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
    b"10/02/2026,Checking A,Salary,$10.00,$1006.00\n"
    b"10/03/2026,Checking A,Tea pending,-$3.00,$1003.00\n"
)


@pytest.fixture(autouse=True)
def qt_file_dialogs(qapp):
    previous = qapp.testAttribute(Qt.AA_DontUseNativeDialogs)
    qapp.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    yield
    qapp.setAttribute(Qt.AA_DontUseNativeDialogs, previous)


@pytest.fixture
def empty_workspace(tmp_path):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    definition = Path(__file__).with_name("synthetic-posted-cash-definition.json")
    (definitions / "cash-definition.json").write_bytes(definition.read_bytes())
    catalog, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    workspace = V2Workspace.create(
        tmp_path / "fresh.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    workspace.catalog_cache.activate(catalog, signature)
    source = tmp_path / "Checking-October.csv"
    source.write_bytes(SOURCE)
    return workspace, source


def ready(qtbot, window):
    qtbot.waitUntil(lambda: not window.inventory_pending and not window.profile_jobs.pending, timeout=15000)


def review_ready(qtbot, window):
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview

    qtbot.waitUntil(lambda: window.findChild(V2CashActivityReview) is not None, timeout=10000)
    review = window.findChild(V2CashActivityReview)
    qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
    return review


def assert_books(profile, *, entries, corrections=0, pending=3):
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (entries,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalCorrections").fetchone() == (corrections,)
        summaries = store.document_summaries()
        assert summaries[0].pending_activity_rows == pending


def prepare_close(qtbot, _window):
    """A failed assertion may leave a draft; discard only during test teardown."""

    def discard():
        modal = QApplication.activeModalWidget()
        if (
            isinstance(modal, QMessageBox)
            and modal.parentWidget() is _window
            and modal.windowTitle() == "Leave this review?"
            and modal.button(QMessageBox.Yes) is not None
        ):
            qtbot.mouseClick(modal.button(QMessageBox.Yes), Qt.LeftButton)

    QTimer.singleShot(0, discard)


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050x700", "1280x800"])
def test_empty_profile_to_reviewed_spending_correction_and_recovery(
    qtbot, qapp, empty_workspace, tmp_path, journey_artifacts, size
):
    workspace, source = empty_workspace
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    modals = ModalSteps(qtbot)
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window, before_close_func=lambda widget: prepare_close(qtbot, widget))
    window.resize(*size)
    window.show()
    assert window.inventory_pending and "Loading" in window.inventory_status.text()
    artifacts.capture("00-loading-document-inventory", window, settle=False)
    ready(qtbot, window)
    assert window.sources.count() == 0
    assert "Import" in window.inventory_status.text()
    assert not window.review_document_button.isEnabled()
    artifacts.capture("01-empty-profile", window)

    modals.arm((QFileDialog, lambda dialog: qtbot.keyClick(dialog, Qt.Key_Escape)))
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    modals.finish()
    assert window.sources.count() == 0
    modals.arm(
        (QFileDialog, lambda dialog: select_file(qtbot, dialog, source)),
        (V2ImportAccountReview, lambda dialog: confirm_new_import(qtbot, dialog)),
    )
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: window.import_worker is None, timeout=20000)
    ready(qtbot, window)
    assert window.sources.count() == 1
    assert "2026-10-01" in window.sources.item(0).text()
    assert "2026-10-03" in window.sources.item(0).text()
    assert "review" in window.review_document_button.text().lower()
    assert_books(workspace.profile_path, entries=0)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        source_id = store.source_ids()[0]
        original_evidence = store.load_import(source_id).evidence
        assert len(store.financial_accounts()) == 1
        assert store.financial_accounts()[0].product_type == "checking"
        assert store.source_account_bindings(source_id)[0].ledger_account_id is not None
    artifacts.capture("02-imported-and-assigned-pending-review", window)
    qtbot.mouseClick(window.review_document_button, Qt.LeftButton)
    ready(qtbot, window)
    review = review_ready(qtbot, window)
    assert "Everyday checking" in window.review_document_selector.currentText()
    assert "2026-10-01" in window.review_document_selector.currentText()
    assert not review.action_button.isEnabled()
    artifacts.capture("05-assigned-blocked-no-purpose-category", window)

    click_table_text(qtbot, review.table, "Coffee")
    choose_combo(qtbot, review.purpose, "expense")
    enter_text(qtbot, review.reason, "Draft retained while managing categories")
    assert review.manage_categories_button.isEnabled()

    def author_categories(dialog):
        for name, kind in (("Food", "expense"), ("Travel", "expense"), ("Salary", "income")):
            enter_text(qtbot, dialog.add_name, name)
            choose_combo(qtbot, dialog.add_kind, kind)
            qtbot.mouseClick(dialog.add_button, Qt.LeftButton)
        assert dialog.categories.count() == 3
        close_dialog(qtbot, dialog)

    modals.arm((V2CategoryDialog, author_categories))
    qtbot.mouseClick(review.manage_categories_button, Qt.LeftButton)
    modals.finish()
    ready(qtbot, window)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        category_ids = {category.name: category.id for category in store.category_accounts()}
    review = review_ready(qtbot, window)
    assert review.reason.text() == "Draft retained while managing categories"
    assert review.purpose.currentData() == "expense"
    artifacts.capture("06-ready-for-review", window)
    choose_combo(qtbot, review.category, category_ids["Food"])
    qtbot.mouseClick(review.batch.stage_button, Qt.LeftButton)
    staged = dict(review.batch.staged)
    assert len(staged) == 1
    modals.arm((V2CategoryDialog, lambda dialog: close_dialog(qtbot, dialog)))
    qtbot.mouseClick(review.manage_categories_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
    assert review.batch.staged == staged
    assert review.reason.text() == "Draft retained while managing categories"
    assert review.category.currentData() == category_ids["Food"]
    assert_books(workspace.profile_path, entries=0)
    artifacts.capture("06-category-manager-cancel-keeps-staged-choices", window)
    qtbot.mouseClick(review.batch.clear_button, Qt.LeftButton)

    def confirm(expected, *, accept=True, screenshot=None):
        def interact(dialog):
            assert all(text in dialog.text() for text in expected), dialog.text()
            if screenshot:
                artifacts.capture(screenshot, dialog)
            qtbot.mouseClick(dialog.button(QMessageBox.Yes if accept else QMessageBox.No), Qt.LeftButton)

        return interact

    def confirm_staged(expected, *, screenshot=None):
        def interact(dialog):
            text = dialog.findChild(QPlainTextEdit).toPlainText()
            assert all(value in text for value in expected), text
            if screenshot:
                artifacts.capture(screenshot, dialog)
            buttons = dialog.findChild(QDialogButtonBox)
            button = next(button for button in buttons.buttons() if button.text().startswith("Confirm and post"))
            qtbot.mouseClick(button, Qt.LeftButton)

        return interact

    for description, purpose, category, expected_amount in (
        ("Coffee", "expense", "Food", "$4.00"),
        ("Salary", "income", "Salary", "$10.00"),
    ):
        click_table_text(qtbot, review.table, description)
        choose_combo(qtbot, review.purpose, purpose)
        choose_combo(qtbot, review.category, category_ids[category])
        enter_text(qtbot, review.reason, f"Reviewed {description} from original statement")
        assert review.batch.stage_button.isEnabled()
        assert not review.action_button.isVisible()
        if purpose == "expense":
            click_table_text(qtbot, review.table, description)
            qtbot.keyClick(review.table, Qt.Key_Tab)
            assert qapp.focusWidget() is review.purpose
            qtbot.keyClick(review.purpose, Qt.Key_Tab)
            assert qapp.focusWidget() is review.category
            qtbot.keyClick(review.category, Qt.Key_Tab)
            assert qapp.focusWidget() is review.manage_categories_button
            qtbot.keyClick(review.manage_categories_button, Qt.Key_Tab)
            assert qapp.focusWidget() is review.reason
            qtbot.keyClick(review.reason, Qt.Key_Tab)
            assert qapp.focusWidget() is review.batch.stage_button
        if purpose == "expense":
            qtbot.keyClick(review.batch.stage_button, Qt.Key_Space)
        else:
            qtbot.mouseClick(review.batch.stage_button, Qt.LeftButton)
        assert len(review.batch.staged) == 1
        assert_books(
            workspace.profile_path, entries=0 if purpose == "expense" else 1, pending=3 if purpose == "expense" else 2
        )
        modals.arm(
            (
                QDialog,
                confirm_staged(
                    [description, expected_amount, "Everyday checking", "2026-10-0"], screenshot=f"07-confirm-{purpose}"
                ),
            )
        )
        qtbot.mouseClick(review.batch.preview_button, Qt.LeftButton)
        modals.finish()
        qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
        ready(qtbot, window)
        assert "Saved 1 reviewed entries together" in review.operation_status.text()
    assert_books(workspace.profile_path, entries=2, pending=1)
    artifacts.capture("08-two-reviewed-one-pending", window)

    # Evidence opens from the actual review button and remains source-only.
    def inspect_evidence(dialog):
        assert dialog.rows_model.rowCount() == 3
        assert dialog.rows_model.data(dialog.rows_model.index(0, 4)) == "Coffee"
        assert "row" in str(dialog.rows_model.data(dialog.rows_model.index(0, 7))).lower()
        artifacts.capture("09-source-evidence", dialog)
        close_dialog(qtbot, dialog)

    modals.arm((V2EvidencePreview, inspect_evidence))
    qtbot.mouseClick(review.preview_source_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
    assert_books(workspace.profile_path, entries=2, pending=1)

    qtbot.mouseClick(window.document_spending_button, Qt.LeftButton)
    reports = window._reports_view
    qtbot.waitUntil(lambda: not reports.reports_pending, timeout=15000)
    assert reports.start.date().toPython() == date(2026, 10, 1)
    assert reports.end.date().toPython() == date(2026, 10, 4)
    assert "$4.00" in reports.total.text()
    assert "All profile accounts" in window.report_context.text()
    assert "1" in reports.qualification.text() and "pending" in reports.qualification.text()
    artifacts.capture("10-reviewed-spending-with-pending-limit", window)
    qtbot.mouseClick(reports.end.lineEdit(), Qt.LeftButton)
    for _ in range(20):
        if reports.end.currentSection() == QDateTimeEdit.DaySection:
            break
        qtbot.keyClick(reports.end, Qt.Key_Right)
    assert reports.end.currentSection() == QDateTimeEdit.DaySection
    for _ in range(11):
        qtbot.keyClick(reports.end, Qt.Key_Up)
    qtbot.waitUntil(lambda: not reports.reports_pending, timeout=15000)
    assert reports.end.date().toPython() == date(2026, 10, 15)
    artifacts.capture("10-edited-report-dates-retained-for-correction", window)
    click_table_text(qtbot, reports.table, "Food")

    def open_correction(dialog):
        assert dialog.model.rowCount() == 1
        assert "Coffee" in dialog.model.data(dialog.model.index(0, 1))
        assert "Everyday checking" in dialog.source.currentText()
        artifacts.capture("11-inspect-exact-reviewed-entry", dialog)
        qtbot.mouseClick(dialog.review_source_button, Qt.LeftButton)

    modals.arm((V2ReviewedEntryDrilldown, open_correction))
    qtbot.mouseClick(reports.inspect_button, Qt.LeftButton)
    modals.finish()
    review = review_ready(qtbot, window)
    assert review.navigation.status_filter.currentData() == "all"
    assert review.navigation.current().description == "Coffee"
    assert not (review.operation_status.isVisible() and "Income posted" in review.operation_status.text())
    choose_combo(qtbot, review.category, category_ids["Travel"])
    enter_text(qtbot, review.reason, "Correct Food to Travel while retaining purpose")
    modals.arm((QMessageBox, confirm(["Food", "Travel", "$0.00", "reversed"], accept=False)))
    qtbot.mouseClick(review.action_button, Qt.LeftButton)
    modals.finish()
    assert review.reason.text() == "Correct Food to Travel while retaining purpose"
    assert review.category.currentData() == category_ids["Travel"]
    assert_books(workspace.profile_path, entries=2, pending=1)
    artifacts.capture("12-cancelled-correction-retains-draft", window)
    modals.arm(
        (QMessageBox, confirm(["Food", "Travel", "$0.00", "reversed"], screenshot="12-confirm-category-correction"))
    )
    qtbot.mouseClick(review.action_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not review.review_pending, timeout=15000)
    ready(qtbot, window)
    assert_books(workspace.profile_path, entries=4, corrections=1, pending=1)
    qtbot.mouseClick(window.back_to_report_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: not reports.reports_pending, timeout=15000)
    assert reports.tabs.currentIndex() == 0
    assert reports.start.date().toPython() == date(2026, 10, 1)
    assert reports.end.date().toPython() == date(2026, 10, 15)
    assert "$4.00" in reports.total.text()
    totals = {row.category_id: row.amount_minor for row in reports.model.rows}
    assert totals[category_ids["Food"]] == 0 and totals[category_ids["Travel"]] == 400
    artifacts.capture("12-corrected-spending-retains-report-dates", window)
    qtbot.mouseClick(reports.tabs.tabBar(), Qt.LeftButton, pos=reports.tabs.tabBar().tabRect(3).center())
    qtbot.waitUntil(lambda: not reports.reports_pending, timeout=15000)
    assert "$10.00" in reports.total.text()
    artifacts.capture("13-income-retained-after-expense-correction", window)

    recovered = tmp_path / "Recovered-original.csv"
    modals.arm(
        (QFileDialog, lambda dialog: select_file(qtbot, dialog, recovered)),
        (QDialog, lambda dialog: close_dialog(qtbot, dialog)),
    )
    click_menu(qtbot, window, "Profile", "Save selected source original")
    modals.finish()
    ready(qtbot, window)
    assert recovered.read_bytes() == SOURCE
    backup = tmp_path / "reviewed-backup.dbb"
    modals.arm(
        (QFileDialog, lambda dialog: select_file(qtbot, dialog, backup)),
        (QDialog, lambda dialog: close_dialog(qtbot, dialog)),
    )
    click_menu(qtbot, window, "Profile", "Back up current profile")
    modals.finish()
    ready(qtbot, window)
    assert backup.is_file()
    restored = tmp_path / "Restored-review.db"
    modals.arm(
        (QFileDialog, lambda dialog: select_file(qtbot, dialog, backup)),
        (QFileDialog, lambda dialog: select_file(qtbot, dialog, restored)),
    )
    click_menu(qtbot, window, "Profile", "Restore backup as new profile")
    modals.finish()
    ready(qtbot, window)
    assert window.workspace.profile_path == restored
    assert_books(restored, entries=4, corrections=1, pending=1)
    with V2ProfileStore.open(restored, read_only=True) as store:
        assert store.load_import(source_id).evidence == original_evidence
        assert store.load_import(source_id).source == SOURCE
    artifacts.capture("14-restored-profile-keeps-source-and-review", window)
    window.close()
    reopened = V2WorkspaceWindow(
        V2Workspace.open(
            restored,
            workspace.catalog_cache.root,
            trusted_keys=workspace.catalog_cache.trusted_keys,
            preferences_path=workspace.preferences_path,
        )
    )
    qtbot.addWidget(reopened, before_close_func=lambda widget: prepare_close(qtbot, widget))
    reopened.resize(*size)
    reopened.show()
    ready(qtbot, reopened)
    assert reopened.sources.count() == 1 and "1 unallocated" in reopened.sources.item(0).text()
    assert_books(restored, entries=4, corrections=1, pending=1)
    artifacts.capture("15-reopened-restored-profile", reopened)


def test_refused_import_can_retry_without_losing_source_or_creating_entries(
    qtbot, qapp, empty_workspace, tmp_path, journey_artifacts
):
    workspace, valid_source = empty_workspace
    unsupported = tmp_path / "Unsupported-layout.csv"
    unsupported.write_bytes(b"Unsupported,Columns\nsynthetic,example\n")
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    modals = ModalSteps(qtbot)
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window, before_close_func=lambda widget: prepare_close(qtbot, widget))
    window.resize(1050, 700)
    window.show()
    ready(qtbot, window)

    def acknowledge_refusal(dialog):
        assert dialog.windowTitle() == "Import failed"
        assert "does not match an installed statement format" in dialog.text()
        assert "try again" in dialog.text()
        assert "Details: catalog_no_match" in dialog.text()
        artifacts.capture("01-refused-import-explains-recovery", dialog)
        qtbot.mouseClick(dialog.button(QMessageBox.Ok), Qt.LeftButton)

    modals.arm(
        (QFileDialog, lambda dialog: select_file(qtbot, dialog, unsupported)),
        (QMessageBox, acknowledge_refusal),
    )
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    modals.finish()
    ready(qtbot, window)
    assert window.sources.count() == 0 and window.import_button.isEnabled()
    assert window.install_catalog_button.isEnabled()
    assert window.account_button.isEnabled()
    assert "no new source saved" in window.status.text()
    assert unsupported.read_bytes() == b"Unsupported,Columns\nsynthetic,example\n"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.source_ids() == ()
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    artifacts.capture("02-refused-import-ready-to-retry", window)

    for attempt in range(2):
        steps = [(QFileDialog, lambda dialog: select_file(qtbot, dialog, valid_source))]
        if attempt == 0:
            steps.append((V2ImportAccountReview, lambda dialog: confirm_new_import(qtbot, dialog)))
        modals.arm(*steps)
        qtbot.mouseClick(window.import_button, Qt.LeftButton)
        modals.finish()
        if attempt == 0:
            assert window.import_worker is not None and window.import_preview.isVisible()
            artifacts.capture("03-importing-source-with-cancel-action", window.import_preview, settle=False)
        qtbot.waitUntil(lambda: window.import_worker is None, timeout=20000)
        ready(qtbot, window)
        assert window.sources.count() == 1
        assert_books(workspace.profile_path, entries=0)
    assert "already imported" in window.status.text()
    assert valid_source.read_bytes() == SOURCE
    artifacts.capture("04-exact-retry-keeps-one-source-pending", window)


def test_cancel_in_flight_import_restores_recovery_actions(
    qtbot, qapp, empty_workspace, journey_artifacts, monkeypatch
):
    from PySide6.QtWidgets import QPushButton

    workspace, source = empty_workspace
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    original_import = workspace.import_file
    started, release = Event(), Event()

    def pause_before_decoding(path, *, cancelled, review_import=None):
        # Hold only the pre-decoder test boundary; the real importer receives
        # the actual worker cancellation flag and performs its normal refusal.
        started.set()
        while not cancelled() and not release.wait(0.01):
            pass
        return original_import(path, cancelled=cancelled, review_import=review_import)

    monkeypatch.setattr(workspace, "import_file", pause_before_decoding)
    modals = ModalSteps(qtbot)
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window, before_close_func=lambda widget: prepare_close(qtbot, widget))
    window.resize(1050, 700)
    window.show()
    ready(qtbot, window)
    try:
        modals.arm((QFileDialog, lambda dialog: select_file(qtbot, dialog, source)))
        qtbot.mouseClick(window.import_button, Qt.LeftButton)
        modals.finish()
        qtbot.waitUntil(started.is_set, timeout=15000)
        assert not window.install_catalog_button.isEnabled()
        artifacts.capture("01-in-flight-import-with-cancel", window.progress)
        cancel = next(button for button in window.progress.findChildren(QPushButton) if "Cancel" in button.text())
        qtbot.mouseClick(cancel, Qt.LeftButton)
        qtbot.waitUntil(lambda: window.import_worker is None, timeout=15000)
        ready(qtbot, window)
        assert "cancelled" in window.status.text()
        assert window.install_catalog_button.isEnabled()
        assert window.account_button.isEnabled()
        assert window.import_button.isEnabled()
        assert source.read_bytes() == SOURCE
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.source_ids() == ()
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
        artifacts.capture("02-cancelled-import-recovery-actions-restored", window)
    finally:
        release.set()

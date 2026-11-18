"""Native-capable regressions for repeated queue decisions and neutral handoff."""

import gc
from dataclasses import replace

import pytest
from parsetrail.core.v2_format_recognition import recognize_catalog_source
from parsetrail.core.v2_import_accounts import build_import_account_review
from parsetrail.core.v2_import_warnings import ImportWarning
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_batch_import import ImportAccountReviewRequest, V2BatchImportWorker
from parsetrail.gui.v2_import_account_review import V2ImportAccountReview
from PySide6.QtCore import QEvent, QPoint, Qt, QThread
from PySide6.QtWidgets import QAbstractItemView, QApplication
from shiboken6 import isValid

from .qt_journey_helpers import JourneyArtifacts, activate, choose_combo, enter_text
from .test_v2_catalog_import import SOURCE, _verified_catalog
from .test_v2_import_account_review import group
from .test_v2_import_accounts import account
from .test_v2_occu_batch_import import occu_workspace
from .test_v2_occu_batch_import_dialog import create


def requests(tmp_path):
    catalog = _verified_catalog()
    with V2ProfileStore.create(tmp_path / "queue.db") as store:
        store.add_financial_account(account())
        review = build_import_account_review(
            store, recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv"), catalog
        )
    first = tmp_path / "A-public-synthetic.csv"
    first.write_bytes(SOURCE)
    second = tmp_path / "B-public-synthetic.csv"
    second.write_bytes(SOURCE.replace(b"Checking A", b"Checking B"))
    with V2ProfileStore.open(tmp_path / "queue.db") as store:
        next_review = build_import_account_review(
            store, recognize_catalog_source(second.read_bytes(), catalog=catalog, suffix=".csv"), catalog
        )
    return (
        ImportAccountReviewRequest(first, review, 1, 2),
        ImportAccountReviewRequest(second, next_review, 2, 2),
    )


def position(view, button):
    return button.mapTo(view, QPoint(0, 0)), button.size()


def assert_neutral(view):
    assert view.pages.currentWidget() is view.pending_page
    assert view.busy.isVisible() and view.cancel_button.isVisible() and view.cancel_button.isEnabled()
    for widget in (
        view.accounts_page,
        view.preview,
        view.step_label,
        view.scope,
        view.assignment_summary,
        view.preferences,
        view.preference_notice,
        view.recovery_notice,
        view.original_button,
        view.back_button,
        view.next_button,
        view.import_button,
        view.skip_button,
    ):
        assert not widget.isVisible(), widget
    assert view.pending_page.hasFocus()


@pytest.mark.parametrize("size", [(1050, 700), (1100, 650)])
def test_primary_coordinates_never_become_skip_and_next_file_has_no_stale_content(
    qtbot, qapp, tmp_path, journey_artifacts, size
):
    first, second = requests(tmp_path)
    view = V2ImportAccountReview()
    qtbot.addWidget(view)
    view.resize(*size)
    view.present(first)
    activate(qtbot, view)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    choose_combo(qtbot, view.account_choice, account().id)
    qapp.processEvents()
    assert view.primary_actions.width() >= max(
        view.next_button.sizeHint().width(), view.import_button.sizeHint().width()
    )
    next_position = position(view, view.next_button)
    skip_position = position(view, view.skip_button)
    cancel_position = position(view, view.cancel_button)
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    qapp.processEvents()
    assert position(view, view.import_button) == next_position
    assert position(view, view.skip_button) == skip_position
    assert position(view, view.cancel_button) == cancel_position
    import_point = view.import_button.mapTo(view, view.import_button.rect().center())
    assert not view.skip_button.geometry().contains(import_point)
    artifacts.capture("01-A-review-stable-actions", view)
    qtbot.mouseClick(view.import_button, Qt.LeftButton)
    assert first.decision is not None
    assert_neutral(view)
    artifacts.capture("02-A-import-pending-neutral", view)
    view.wait_for_next(2, 2, second.path)
    assert_neutral(view)
    assert "B-public-synthetic" in view.file_context.text()
    assert view.file_context.toolTip() == str(second.path)
    artifacts.capture("03-B-reading-no-A-content", view)
    view.present(second)
    activate(qtbot, view)
    qapp.processEvents()
    assert position(view, view.next_button) == next_position
    assert position(view, view.skip_button) == skip_position
    assert position(view, view.cancel_button) == cancel_position
    assert not view.next_button.isEnabled() and view.account_choice.choice() is None
    assert view.groups.item(0, 0).text() == "Checking B"
    assert view.preferences.isVisible() and view.scope.isVisible()
    assert view.focusWidget() is view.account_choice
    # Resolve the real child at the old Import coordinates, as native repeated
    # pointer clicks would; sending directly to the dialog would miss children.
    target = view.childAt(import_point)
    assert target is view.next_button
    for _ in range(3):
        qtbot.mouseClick(target, Qt.LeftButton, pos=target.mapFrom(view, import_point))
    assert not second.decided.is_set()
    artifacts.capture("04-B-account-required-repeated-import-click-safe", view)
    qtbot.mouseClick(view.skip_button, Qt.LeftButton)
    assert second.decided.is_set() and second.decision is None
    assert_neutral(view)
    view.finish_queue()


def test_alt_mnemonics_work_from_editors_and_bare_letters_and_enter_remain_text(qtbot, tmp_path, monkeypatch):
    first, second = requests(tmp_path)
    view = V2ImportAccountReview()
    qtbot.addWidget(view)
    view.present(first)
    activate(qtbot, view)
    choose_combo(qtbot, view.account_choice, "__create_new_account__")
    enter_text(qtbot, view.name, "nibso NIBSO")
    assert view.name.text() == "nibso NIBSO" and not first.decided.is_set()
    qtbot.keyClick(view.name, Qt.Key_Return)
    assert view.pages.currentIndex() == 0 and not first.decided.is_set()
    choose_combo(qtbot, view.account_choice, account().id)
    opened = []
    monkeypatch.setattr(
        "parsetrail.gui.v2_import_account_review.open_selected_original",
        lambda *args: opened.append(args[:2]),
    )
    qtbot.keyClick(view.account_choice.lineEdit(), Qt.Key_O, Qt.AltModifier)
    qtbot.waitUntil(lambda: len(opened) == 1)
    assert opened[0] == (first.path, first.recognition.source_sha256)
    qtbot.keyClick(view.account_choice.lineEdit(), Qt.Key_N, Qt.AltModifier)
    qtbot.waitUntil(lambda: view.pages.currentIndex() == 1)
    view.preview.details.setFocus()
    qtbot.keyClick(view.preview.details, Qt.Key_B, Qt.AltModifier)
    qtbot.waitUntil(lambda: view.pages.currentIndex() == 0)
    qtbot.keyClick(view.account_choice.lineEdit(), Qt.Key_N, Qt.AltModifier)
    qtbot.waitUntil(lambda: view.pages.currentIndex() == 1)
    view.preview.details.setFocus()
    qtbot.keyClick(view.preview.details, Qt.Key_I, Qt.AltModifier)
    qtbot.waitUntil(first.decided.is_set)
    assert first.decision is not None
    assert_neutral(view)
    view.present(second)
    activate(qtbot, view)
    qtbot.keyClick(view.account_choice.lineEdit(), Qt.Key_S, Qt.AltModifier)
    qtbot.waitUntil(second.decided.is_set)
    assert second.decision is None
    assert_neutral(view)
    for button in (view.next_button, view.import_button, view.back_button, view.skip_button, view.original_button):
        assert not button.isDefault() and not button.autoDefault()
        assert button.shortcut().toString().startswith("Alt+")
    view.finish_queue()


def test_repeated_enter_after_import_never_cancels_without_reaching_cancel(qtbot, tmp_path):
    first, _second = requests(tmp_path)
    view = V2ImportAccountReview()
    qtbot.addWidget(view)
    cancelled = []
    view.cancel_remaining.connect(lambda: cancelled.append(True))
    view.present(first)
    activate(qtbot, view)
    choose_combo(qtbot, view.account_choice, account().id)
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    view.import_button.setFocus()
    qtbot.keyClick(view.import_button, Qt.Key_Return)
    assert first.decided.is_set() and first.decision is not None
    assert_neutral(view)
    for _ in range(3):
        qtbot.keyClick(QApplication.focusWidget(), Qt.Key_Return)
    assert not cancelled and view.pending_page.hasFocus()
    qtbot.keyClick(view.pending_page, Qt.Key_Tab)
    assert view.cancel_button.hasFocus()
    qtbot.keyClick(view.cancel_button, Qt.Key_Return)
    assert cancelled == [True]
    view.finish_queue()


def test_valid_warning_guidance_compares_original_and_preserves_read_only_evidence(
    qtbot, qapp, tmp_path, journey_artifacts
):
    first, _ = requests(tmp_path)
    candidate = first.recognition.candidates[0]
    warning = ImportWarning("synthetic_comparison", "requires_review", "Compare the printed source amount")
    recognition = replace(first.recognition, candidates=(replace(candidate, warnings=(warning,)),))
    first.review = replace(first.review, recognition=recognition)
    view = V2ImportAccountReview()
    qtbot.addWidget(view)
    view.present(first)
    choose_combo(qtbot, view.account_choice, account().id)
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    assert view.import_button.isEnabled()
    assert "View original" in view.status.text()
    assert "retains these warnings" in view.status.text() and "no transactions are posted" in view.status.text()
    assert view.preview.details.isReadOnly()
    assert view.preview.rows.editTriggers() == QAbstractItemView.NoEditTriggers
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("valid-warning-next-actions", view)
    view.finish_queue()


def test_cancel_next_required_file_retains_completed_import_and_gui_thread_disposal(qtbot, qapp, tmp_path):
    workspace, paths = occu_workspace(tmp_path)
    view = V2ImportAccountReview(workspace.institutions())
    qtbot.addWidget(view)
    worker = V2BatchImportWorker(workspace, paths)
    seen = []

    def present(request):
        seen.append(request)
        view.present(request)

    worker.import_review_requested.connect(present)
    view.cancel_remaining.connect(worker.cancel)
    worker.start()
    try:
        qtbot.waitUntil(lambda: len(seen) == 1, timeout=15000)
        create(qtbot, view, "Public primary savings", "savings")
        group(qtbot, view, 1)
        create(qtbot, view, "Public remarkable checking", "checking")
        qtbot.mouseClick(view.next_button, Qt.LeftButton)
        qtbot.mouseClick(view.import_button, Qt.LeftButton)
        assert_neutral(view)
        qtbot.waitUntil(lambda: len(seen) == 2, timeout=15000)
        assert not view.next_button.isEnabled()
        qtbot.mouseClick(view.cancel_button, Qt.LeftButton)
        assert_neutral(view)
        qtbot.waitUntil(lambda: not worker.isRunning(), timeout=15000)
        assert worker.wait(1000) and worker.error is None
        assert worker.result.files[0].status == "imported"
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert len(store.source_ids()) == 1 and len(store.financial_accounts()) == 2
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        worker.cancel()
        if view.request is not None:
            view.request.finish(None)
        assert worker.wait(10000)
        view.finish_queue()
    destroyed = []
    worker.destroyed.connect(lambda: destroyed.append(("worker", QThread.currentThread() is qapp.thread())))
    view.destroyed.connect(lambda: destroyed.append(("view", QThread.currentThread() is qapp.thread())))
    worker.deleteLater()
    view.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(worker) and not isValid(view)
    assert sorted(destroyed) == [("view", True), ("worker", True)]
    assert gc.isenabled()
    gc.collect()

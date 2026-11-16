"""Import conveniences preserve drafts, source identity and explicit decisions."""

from dataclasses import replace
from hashlib import sha256

import pytest
from parsetrail.core import v2_original_document as originals
from parsetrail.core.v2_format_recognition import recognize_catalog_source
from parsetrail.core.v2_import_accounts import build_import_account_review
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_batch_import import ImportAccountReviewRequest
from parsetrail.gui.v2_dropdowns import install_dropdown_opening
from parsetrail.gui.v2_financial_account import InstitutionChoice
from parsetrail.gui.v2_import_account_review import V2ImportAccountReview
from parsetrail.gui.v2_original_document import open_selected_original
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtWidgets import QComboBox, QDialog, QVBoxLayout
from shiboken6 import isValid

from .qt_journey_helpers import JourneyArtifacts, choose_combo, enter_text
from .test_v2_document_viewer import synthetic_pdf
from .test_v2_import_account_review import group, workspace


def request_for(tmp_path):
    model, path = workspace(tmp_path)
    recognition = recognize_catalog_source(path.read_bytes(), catalog=model.catalog_cache.load_current(), suffix=".csv")
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        review = build_import_account_review(
            store, recognition, model.catalog_cache.load_current(), model.preferences()
        )
    review = replace(
        review, groups=(replace(review.groups[0], offer_enable_abbreviated_matching=True), *review.groups[1:])
    )
    return model, ImportAccountReviewRequest(path, review, 1, 1)


def create_account(qtbot, view, name, product="checking"):
    choose_combo(qtbot, view.account_choice, view.account_choice.itemData(1))
    enter_text(qtbot, view.name, name)
    choose_combo(qtbot, view.institution, None)
    selected = next(
        view.product.itemData(index)
        for index in range(1, view.product.count())
        if view.product.itemData(index).product_type == product
    )
    choose_combo(qtbot, view.product, selected)


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050x700", "1280x800"])
def test_preimport_original_and_preferences_keep_current_drafts_and_profile(
    qtbot, qapp, tmp_path, journey_artifacts, size
):
    model, request = request_for(tmp_path)
    request.review = replace(request.review, import_preview_mode="when_needed")
    before = sha256(model.profile_path.read_bytes()).hexdigest()
    dialog = V2ImportAccountReview(request.review.institutions)
    qtbot.addWidget(dialog)
    dialog.present(request)
    dialog.sync_preferences(False, "always")
    dialog.resize(*size)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    matching, previews = [], []
    dialog.abbreviated_matching_changed.connect(matching.append)
    dialog.import_preview_mode_changed.connect(previews.append)
    create_account(qtbot, dialog, "Everyday checking")
    expected = (dialog.name.text(), dialog.product.currentData(), dialog.account_choice.choice())
    qtbot.mouseClick(dialog.abbreviated_matching, Qt.LeftButton)
    dialog.preview_mode.setCurrentIndex(dialog.preview_mode.findData("when_needed"))
    assert matching == [True] and previews == ["when_needed"]
    assert expected == (dialog.name.text(), dialog.product.currentData(), dialog.account_choice.choice())
    dialog.sync_preferences(False, "always", "The preferences file could not be written. Retry.")
    assert not dialog.abbreviated_matching.isChecked() and dialog.preview_mode.currentData() == "always"
    assert matching == [True] and previews == ["when_needed"]
    assert dialog.preference_notice.property("formState") == "blocked"
    assert "not saved" in dialog.preference_notice.text()
    assert expected == (dialog.name.text(), dialog.product.currentData(), dialog.account_choice.choice())
    dialog.sync_preferences(True, "when_needed")
    artifacts.capture("00-import-preferences-current-draft-kept", dialog)
    assert not request.decided.is_set()
    qtbot.mouseClick(dialog.original_button, Qt.LeftButton)
    qtbot.waitUntil(
        lambda: dialog._original_open.viewer is not None and dialog._original_open.viewer.ready, timeout=10000
    )
    viewer = dialog._original_open.viewer
    assert "Not imported yet" in viewer.heading.text()
    assert not hasattr(viewer._saved, "evidence")
    artifacts.capture("01-original-while-naming-account", viewer)
    viewer.close()
    qtbot.waitUntil(lambda: not isValid(viewer))
    assert expected == (dialog.name.text(), dialog.product.currentData(), dialog.account_choice.choice())
    group(qtbot, dialog, 1)
    create_account(qtbot, dialog, "Rainy day savings", "savings")
    qtbot.mouseClick(dialog.next_button, Qt.LeftButton)
    assert dialog.pages.currentIndex() == 1
    assert "Preview required: 2 new accounts need confirmation" in dialog.status.text()
    artifacts.capture("02-preview-preferences-and-original-action", dialog)
    qtbot.mouseClick(dialog.original_button, Qt.LeftButton)
    qtbot.waitUntil(
        lambda: dialog._original_open.viewer is not None and dialog._original_open.viewer.ready, timeout=10000
    )
    dialog._original_open.viewer.close()
    assert dialog.pages.currentIndex() == 1 and not request.decided.is_set()
    assert sha256(model.profile_path.read_bytes()).hexdigest() == before
    assert sha256(request.path.read_bytes()).hexdigest() == request.recognition.source_sha256
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert not store.source_ids() and not store.financial_accounts()
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    dialog.finish_queue()


def test_selected_reader_refuses_changed_oversized_and_cancelled_bytes(tmp_path, monkeypatch):
    path = tmp_path / "selected.csv"
    path.write_bytes(b"A,B\n1,2\n")
    expected = sha256(path.read_bytes()).hexdigest()
    result = originals.read_selected_original(path, expected)
    assert result.source == path.read_bytes() and not hasattr(result, "evidence")
    path.write_bytes(b"A,B\n3,4\n")
    with pytest.raises(originals.OriginalDocumentError, match="selected_original_changed"):
        originals.read_selected_original(path, expected)
    with pytest.raises(originals.OriginalDocumentError, match="original_open_cancelled"):
        originals.read_selected_original(path, expected, cancelled=lambda: True)
    monkeypatch.setattr(originals, "MAX_SOURCE_BYTES", 4)
    with pytest.raises(originals.OriginalDocumentError, match="selected_original_size_invalid"):
        originals.read_selected_original(path, expected)


def test_selected_pdf_uses_memory_viewer_and_dies_with_host(qtbot, tmp_path):
    path = tmp_path / "selected.pdf"
    path.write_bytes(synthetic_pdf())
    host = QDialog()
    qtbot.addWidget(host)
    host.show()
    action = open_selected_original(path, sha256(path.read_bytes()).hexdigest(), host)
    qtbot.waitUntil(lambda: action.viewer is not None and action.viewer.ready, timeout=10000)
    viewer = action.viewer
    assert viewer.pdf_buffer is not None and viewer._saved.source == path.read_bytes()
    host.reject()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qtbot.waitUntil(lambda: not isValid(viewer))
    assert path.exists()


@pytest.mark.parametrize("editable", [False, True], ids=["choice", "searchable"])
def test_entire_combo_opens_without_losing_typing_keyboard_or_owner_lifetime(qtbot, editable):
    host = QDialog()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    install_dropdown_opening(host)
    host.show()
    qtbot.waitUntil(lambda: not host._parsetrail_dropdown_opening._scan_timer.isActive())
    # Added after installation: dynamic controls receive the same local behavior.
    combo = InstitutionChoice(()) if editable else QComboBox()
    if not editable:
        combo.addItems(["Choose", "One", "Two"])
    layout.addWidget(combo)
    qtbot.waitUntil(lambda: getattr(combo, "_parsetrail_dropdown_owner", lambda: None)() is not None)
    target = combo.lineEdit() if editable else combo
    qtbot.mouseClick(target, Qt.LeftButton, pos=target.rect().center())
    qtbot.waitUntil(combo.view().isVisible)
    if editable:
        qtbot.keyClick(combo.lineEdit(), Qt.Key_A, Qt.ControlModifier)
        qtbot.keyClicks(combo.lineEdit(), "Search while open")
        assert combo.currentText() == "Search while open"
    qtbot.keyClick(combo.view(), Qt.Key_Escape)
    qtbot.waitUntil(lambda: not combo.view().isVisible())
    qtbot.mouseClick(combo, Qt.LeftButton, pos=QPoint(combo.width() - 8, combo.height() // 2))
    qtbot.waitUntil(combo.view().isVisible)
    qtbot.keyClick(combo.view(), Qt.Key_Escape)
    if editable:
        combo.lineEdit().setFocus()
        qtbot.keyClick(combo.lineEdit(), Qt.Key_A, Qt.ControlModifier)
        qtbot.keyClicks(combo.lineEdit(), "Example bank")
        assert combo.currentText() == "Example bank"
        assert not combo.valid_selection()
    else:
        combo.setFocus()
        qtbot.keyClick(combo, Qt.Key_Down)
        assert combo.currentText() == "One"
    policy = host._parsetrail_dropdown_opening
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(policy) and not isValid(combo)

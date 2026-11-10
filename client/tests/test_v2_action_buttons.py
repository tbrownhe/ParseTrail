"""Rendered action buttons retain full labels and differ from draft fields."""

import pytest
from parsetrail.core.v2_account_creation import AccountCreationDraft
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
from parsetrail.gui.v2_source_account_review import V2SourceAccountReview
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from .qt_journey_helpers import JourneyArtifacts, activate, choose_combo, enter_text
from .test_v2_document_browser import _populated_workspace


def assert_label_fits(button):
    text = button.text().replace("&", "")
    assert button.width() >= button.fontMetrics().horizontalAdvance(text) + 24, (text, button.size())
    assert button.height() >= button.fontMetrics().height() + 6, (text, button.size())


@pytest.fixture
def requested_font(qapp, request):
    previous = qapp.font()
    qapp.setFont(QFont("Segoe UI", request.param))
    yield request.param
    qapp.setFont(previous)


@pytest.mark.parametrize("requested_font", [9, 12], indirect=True, ids=["9pt", "12pt"])
def test_create_account_button_keeps_padding_across_ready_focus_and_disabled(
    qtbot,
    qapp,
    requested_font,
    journey_artifacts,
):
    form = V2FinancialAccountDialog(draft=AccountCreationDraft())
    qtbot.addWidget(form)
    form.resize(620, 700)
    form.show()
    qtbot.waitUntil(form.isVisible)
    assert form.save_button.font().pointSizeF() == requested_font
    assert form.name.font().pointSizeF() == requested_font
    assert form.height() <= 800
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (620, 700))
    assert not form.save_button.isEnabled()
    assert_label_fits(form.save_button)
    enter_text(qtbot, form.name, "Everyday checking")
    choose_combo(qtbot, form.product, "checking")
    assert form.kind.currentData() == "asset" and form.scope.currentData() == "account_total"
    choose_combo(qtbot, form.institution, None)
    qtbot.waitUntil(form.save_button.isEnabled)
    qtbot.wait(20)
    assert_label_fits(form.save_button)
    color = form.save_button.grab().toImage().pixelColor(8, 8)
    assert color.blue() > color.green() > color.red(), color.name()
    field_color = form.name.grab().toImage().pixelColor(8, 4)
    assert field_color.green() > field_color.blue(), field_color.name()
    artifacts.capture("01-blue-create-account-green-draft", form)
    activate(qtbot, form)
    form.save_button.setFocus()
    qtbot.waitUntil(form.save_button.hasFocus)
    assert_label_fits(form.save_button)
    artifacts.capture("02-focused-label-retains-inset", form)
    enter_text(qtbot, form.name, "")
    qtbot.keyClick(form.name, Qt.Key_Backspace)
    assert not form.save_button.isEnabled()
    assert_label_fits(form.save_button)
    artifacts.capture("03-disabled-action-keeps-full-label", form)


def test_use_account_button_is_blue_with_full_text_and_does_not_assign_on_selection(
    qtbot,
    qapp,
    tmp_path,
    journey_artifacts,
):
    workspace = _populated_workspace(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(FinancialAccount("second", "Second checking", "asset", "chase"))
        source = store.source_ids()[0]
    dialog = V2SourceAccountReview(workspace, source)
    qtbot.addWidget(dialog)
    dialog.show()
    choose_combo(qtbot, dialog.account_combo, "second")
    qtbot.wait(20)
    assert dialog.assign_button.isEnabled()
    assert_label_fits(dialog.assign_button)
    color = dialog.assign_button.grab().toImage().pixelColor(8, 8)
    assert color.blue() > color.green() > color.red(), color.name()
    assert "Not saved" in dialog.choice_status.text()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (780, 520))
    artifacts.capture("01-blue-use-account-requires-explicit-save", dialog)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.source_account_bindings(source)[0].ledger_account_id == "cash"
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    qtbot.mouseClick(dialog.assign_button, Qt.LeftButton)
    assert "Saved" in dialog.choice_status.text()
    assert_label_fits(dialog.assign_button)
    artifacts.capture("02-saved-assignment-button-neutral", dialog)

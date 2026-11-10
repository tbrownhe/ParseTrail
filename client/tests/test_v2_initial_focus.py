"""Opening task windows are ready for typing without stealing later focus."""

import pytest
import shiboken6
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_categories import V2CategoryDialog
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
from parsetrail.gui.v2_form_state import install_initial_focus
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QMainWindow, QVBoxLayout


class _TaskDialog(QDialog):
    pass


class _TaskWindow(QMainWindow):
    pass


_TaskDialog.__module__ = _TaskWindow.__module__ = "parsetrail.gui.v2_test_surface"


def _two_field_dialog(qtbot, *, registered=True):
    dialog = _TaskDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    first, later = QLineEdit(), QLineEdit()
    layout.addWidget(first)
    layout.addWidget(later)
    if registered:
        install_initial_focus(dialog)
    return dialog, first, later


def test_financial_account_opens_ready_for_nickname_and_reopens(qtbot, qapp):
    dialog = V2FinancialAccountDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.activateWindow()
    qtbot.waitUntil(lambda: qapp.focusWidget() is dialog.name)
    qtbot.keyClicks(qapp.focusWidget(), "Travel")
    assert dialog.name.text() == "Travel"
    dialog.product.setFocus()
    dialog._update_form_cues()
    assert qapp.focusWidget() is dialog.product
    dialog.hide()
    dialog.show()
    dialog.activateWindow()
    qtbot.waitUntil(lambda: dialog.focusWidget() is dialog.name)
    # Offscreen does not reactivate a hidden/reopened window. Native execution
    # additionally verifies application focus; both verify the logical input.
    if qapp.platformName() != "offscreen":
        qtbot.waitUntil(lambda: qapp.focusWidget() is dialog.name)


def test_categories_open_at_first_choice_and_budget_is_discoverable(qtbot, qapp, tmp_path, journey_artifacts):
    from PySide6.QtWidgets import QGroupBox

    from .qt_journey_helpers import JourneyArtifacts

    profile = tmp_path / "synthetic.db"
    with V2ProfileStore.create(profile):
        pass
    dialog = V2CategoryDialog(profile)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.activateWindow()
    qtbot.waitUntil(lambda: qapp.focusWidget() is dialog.add_name)
    assert any(group.title() == "Monthly budget for selected category" for group in dialog.findChildren(QGroupBox))
    assert dialog.budget_save.text() == "Save budget from month"
    assert dialog.budget_clear.text() == "Remove budget from month"
    assert "monthly budget" in dialog.budget_current.text()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (700, 800))
    artifacts.capture("01-categories-budget-empty-first-choice", dialog)
    qtbot.keyClicks(qapp.focusWidget(), "Food")
    assert dialog.add_name.text() == "Food"
    qtbot.mouseClick(dialog.add_button, Qt.LeftButton)
    dialog.budget_amount.setFocus()
    qtbot.keyClicks(qapp.focusWidget(), "250.00")
    qtbot.mouseClick(dialog.budget_save, Qt.LeftButton)
    assert "Monthly budget saved" in dialog.status.text()
    artifacts.capture("02-budget-saved", dialog)
    qtbot.mouseClick(dialog.budget_clear, Qt.LeftButton)
    assert "Monthly budget removed" in dialog.status.text()
    assert "No budget" in dialog.budget_current.text()


def test_focus_uses_tab_order_skips_ineligible_inputs_and_does_not_repeat_on_refresh(qtbot, qapp):
    dialog = _TaskDialog()
    install_initial_focus(dialog)
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    readonly, hidden, disabled, later = (QLineEdit() for _ in range(4))
    first = QComboBox()
    first.setEditable(True)
    first.addItem("Choose")
    for widget in (readonly, hidden, disabled, later, first):
        layout.addWidget(widget)
    readonly.setReadOnly(True)
    hidden.hide()
    disabled.setEnabled(False)
    QDialog.setTabOrder(disabled, first)
    QDialog.setTabOrder(first, later)
    dialog.show()
    dialog.activateWindow()
    qtbot.waitUntil(lambda: qapp.focusWidget() in (first, first.lineEdit()))
    qtbot.keyClick(first, Qt.Key_Tab)
    assert qapp.focusWidget() is later
    later.setText("retained")
    qapp.processEvents()
    assert qapp.focusWidget() is later


@pytest.mark.parametrize("window_type", (_TaskDialog, _TaskWindow))
def test_registration_is_idempotent_and_window_owns_policy(qtbot, window_type):
    window = window_type()
    qtbot.addWidget(window)
    install_initial_focus(window)
    policy = window._parsetrail_initial_focus
    install_initial_focus(window)
    assert window._parsetrail_initial_focus is policy
    assert policy.parent() is window
    assert sum(child is policy for child in window.children()) == 1


def test_registered_window_does_not_change_an_unregistered_task_window(qtbot, qapp):
    registered, first, _later = _two_field_dialog(qtbot)
    registered.show()
    registered.activateWindow()
    qtbot.waitUntil(lambda: registered.focusWidget() is first)

    unrelated, _unrelated_first, later = _two_field_dialog(qtbot, registered=False)
    later.setFocus()
    unrelated.show()
    unrelated.activateWindow()
    qtbot.waitUntil(lambda: unrelated.focusWidget() is later)
    qapp.processEvents()
    assert unrelated.focusWidget() is later
    qtbot.keyClicks(later, "Keep this choice")
    assert later.text() == "Keep this choice"


def test_registered_non_v2_dialog_retains_its_own_opening_focus(qtbot, qapp):
    dialog = QDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    first, later = QLineEdit(), QLineEdit()
    layout.addWidget(first)
    layout.addWidget(later)
    install_initial_focus(dialog)
    later.setFocus()
    dialog.show()
    dialog.activateWindow()
    qapp.processEvents()
    assert dialog.focusWidget() is later


def test_registered_task_embedded_before_show_does_not_take_opening_focus(qtbot, qapp):
    host = QDialog()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    embedded, _first, later = _two_field_dialog(qtbot)
    embedded.setParent(host)
    embedded.setWindowFlags(Qt.Widget)
    layout.addWidget(embedded)
    later.setFocus()
    host.show()
    host.activateWindow()
    qapp.processEvents()
    assert not embedded.isWindow()
    assert host.focusWidget() is later
    assert embedded.property("parsetrailOpeningFocus") is None


def test_deleting_window_cancels_queued_opening_focus(qapp, monkeypatch):
    dialog = _TaskDialog()
    install_initial_focus(dialog)
    called = []
    monkeypatch.setattr(dialog._parsetrail_initial_focus, "_focus", lambda root: called.append(root))
    dialog.show()
    # Delete before the event loop can deliver the context-bound zero timer.
    shiboken6.delete(dialog)
    qapp.processEvents()
    assert not shiboken6.isValid(dialog)
    assert called == []


def test_hiding_window_discards_queued_opening_focus(qtbot, qapp, monkeypatch):
    dialog, _first, _later = _two_field_dialog(qtbot)
    called = []
    monkeypatch.setattr(dialog._parsetrail_initial_focus, "_focus", lambda root: called.append(root))
    dialog.show()
    dialog.hide()
    qapp.processEvents()
    assert called == []
    assert dialog.property("parsetrailOpeningFocus") is False


def test_deactivation_discards_queued_focus_before_later_activation(qtbot, qapp):
    dialog, _first, later = _two_field_dialog(qtbot)
    dialog.show()
    qapp.sendEvent(dialog, QEvent(QEvent.WindowDeactivate))
    later.setFocus()
    qapp.processEvents()
    qapp.sendEvent(dialog, QEvent(QEvent.WindowActivate))
    qapp.processEvents()
    assert dialog.focusWidget() is later


def test_later_activation_does_not_steal_focus_or_typed_input(qtbot, qapp):
    dialog, first, later = _two_field_dialog(qtbot)
    dialog.show()
    dialog.activateWindow()
    qtbot.waitUntil(lambda: dialog.focusWidget() is first)
    later.setFocus()
    qtbot.keyClicks(later, "Retain my edit")
    qapp.sendEvent(dialog, QEvent(QEvent.WindowDeactivate))
    qapp.sendEvent(dialog, QEvent(QEvent.WindowActivate))
    qapp.processEvents()
    assert dialog.focusWidget() is later
    assert later.text() == "Retain my edit"

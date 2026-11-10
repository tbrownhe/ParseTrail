"""Opening task windows are ready for typing without stealing later focus."""

from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_categories import V2CategoryDialog
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
from parsetrail.gui.v2_form_state import install_initial_focus
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QVBoxLayout


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
    class TaskDialog(QDialog):
        pass

    TaskDialog.__module__ = "parsetrail.gui.v2_test_surface"
    install_initial_focus()
    dialog = TaskDialog()
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

"""Shared software-input setup for the account-first import screen."""

from PySide6.QtCore import Qt

from .qt_journey_helpers import choose_combo, enter_text


def new_import_account(qtbot, dialog, *, name="Everyday checking", product="checking", institution=None):
    choose_combo(qtbot, dialog.account_choice, "__create_new_account__")
    enter_text(qtbot, dialog.name, name)
    if dialog.institution.isEnabled():
        choose_combo(qtbot, dialog.institution, institution)
    profile = next(
        dialog.product.itemData(i)
        for i in range(dialog.product.count())
        if getattr(dialog.product.itemData(i), "product_type", None) == product
    )
    if dialog.product.isEnabled():
        choose_combo(qtbot, dialog.product, profile)
    qtbot.waitUntil(dialog.next_button.isEnabled)
    qtbot.mouseClick(dialog.next_button, Qt.LeftButton)


def confirm_new_import(qtbot, dialog):
    new_import_account(qtbot, dialog)
    assert dialog.import_button.isEnabled(), "This helper requires a unique interpretation"
    qtbot.mouseClick(dialog.import_button, Qt.LeftButton)

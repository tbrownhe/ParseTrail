"""Fresh-profile category authoring stays separate from journal posting."""

from __future__ import annotations

import os
from pathlib import Path

from parsetrail.core.v2_profile_store import V2ProfileStore


def test_category_dialog_adds_and_renames_without_posting(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_categories import V2CategoryDialog
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile):
        pass
    dialog = V2CategoryDialog(profile)
    try:
        assert dialog.categories.count() == 0
        assert not dialog.rename_button.isEnabled()
        dialog.add_name.setText("Groceries")
        dialog.add_button.click()
        assert dialog.categories.count() == 1
        assert dialog.rename_button.isEnabled()
        dialog.rename_name.setText("Food")
        dialog.rename_button.click()
        assert dialog.categories.currentItem().text() == "Food (Expense)"
        dialog.add_name.setText("Wages")
        dialog.add_kind.setCurrentIndex(1)
        dialog.add_button.click()
        assert dialog.categories.count() == 2
    finally:
        dialog.close()
        app.processEvents()
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert [(category.name, category.kind) for category in store.category_accounts()] == [
            ("Food", "expense"),
            ("Wages", "income"),
        ]
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)

"""First-use task boundaries preserve exact saved values and discoverable detail."""

from datetime import date
from hashlib import sha256

from parsetrail.core.v2_profile_store import SavedImport, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_categories import V2CategoryDialog
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
from PySide6.QtCore import QDate, Qt

from .qt_journey_helpers import JourneyArtifacts, enter_text
from .qt_journey_scenarios import SOURCE
from .test_v2_cash_activity_review import DEFINITION


def test_saved_category_budget_is_edit_task_not_missing_new_category(qtbot, qapp, tmp_path, journey_artifacts):
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile) as store:
        store.add_category_account("food", "Groceries", "expense")
        store.add_category_account("travel", "Travel", "expense")
        store.set_category_budget_rate("food", date(2026, 10, 1), 10000)
    dialog = V2CategoryDialog(profile, initial_month=date(2026, 10, 22), selected_category_id="food")
    qtbot.addWidget(dialog)
    dialog.show()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (600, 570))
    assert dialog.budget_month.date() == QDate(2026, 10, 1)
    assert dialog.categories.currentItem().data(Qt.UserRole) == "food"
    assert not dialog.add_panel.isVisible()
    assert dialog.add_name.property("formState") == "neutral"
    assert "food" not in dialog.category_identity.text()
    assert "Groceries" in dialog.category_identity.text()
    assert not dialog.identity_details.isVisible()
    assert "$100.00" in dialog.budget_current.text()
    enter_text(qtbot, dialog.budget_amount, "120.00")
    qtbot.mouseClick(dialog.budget_save, Qt.LeftButton)
    assert dialog.budget_amount.property("formState") == "saved"
    assert dialog.add_name.property("formState") == "neutral"
    assert not dialog.add_choice_status.isVisible()
    artifacts.capture("01-saved-budget-no-unrelated-required-task", dialog)
    qtbot.mouseClick(dialog.new_category_button, Qt.LeftButton)
    qtbot.waitUntil(dialog.add_name.hasFocus)
    assert dialog.add_panel.isVisible() and not dialog.budget_box.isVisible()
    enter_text(qtbot, dialog.add_name, "Unsaved books")
    artifacts.capture("01a-explicit-add-task-valid-not-saved", dialog)
    qtbot.mouseClick(dialog.cancel_add_button, Qt.LeftButton)
    assert not dialog.add_panel.isVisible() and dialog.budget_box.isVisible()
    assert dialog.budget_amount.text() == "120.00"
    qtbot.mouseClick(dialog.new_category_button, Qt.LeftButton)
    enter_text(qtbot, dialog.add_name, "Books")
    qtbot.mouseClick(dialog.add_button, Qt.LeftButton)
    assert "Books" in dialog.category_identity.text()
    assert not dialog.add_panel.isVisible()
    assert dialog.add_name.property("formState") == "neutral"
    assert dialog.budget_amount.text() == ""  # Groceries' draft must not leak to Books.
    artifacts.capture("02-category-added-now-edit-budget", dialog)
    qtbot.mouseClick(dialog.options_button, Qt.LeftButton)
    assert dialog.identity_details.isVisible() and "Category ID:" in dialog.identity_details.text()
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.category_budget_history("food")[-1].amount_minor == 12000
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_category_creation_is_first_task_only_for_empty_profile(qtbot, qapp, tmp_path, journey_artifacts):
    profile = tmp_path / "empty.db"
    with V2ProfileStore.create(profile):
        pass
    dialog = V2CategoryDialog(profile)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.add_panel.isVisible()
    assert dialog.add_name.property("formState") == "required"
    assert not dialog.budget_box.isVisible()
    assert not dialog.options_button.isVisible()
    JourneyArtifacts(journey_artifacts, qapp, (600, 570)).capture("02a-empty-profile-add-category", dialog)


def test_source_context_and_material_limits_precede_hidden_diagnostics(qtbot, qapp, journey_artifacts):
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    saved = SavedImport(SOURCE, DEFINITION, evidence, ".csv")
    before = sha256(saved.source).hexdigest()
    dialog = V2EvidencePreview(saved)
    qtbot.addWidget(dialog)
    dialog.show()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    assert not dialog.details.isVisible()
    assert dialog.original_button.isVisible()
    assert dialog.rows_model.rowCount() == 3
    assert dialog.rows_model.data(dialog.rows_model.index(0, 5)) == "-$4.00"
    artifacts.capture("03-evidence-source-context-and-limits", dialog)
    qtbot.mouseClick(dialog.details_button, Qt.LeftButton)
    assert dialog.details.isVisible() and evidence.source_sha256 in dialog.details.toPlainText()
    assert sha256(saved.source).hexdigest() == before


def test_account_product_precedes_unestablished_derived_fields(qtbot, qapp, journey_artifacts):
    dialog = V2FinancialAccountDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (600, 570))
    assert not dialog.kind.isVisible() and not dialog.scope.isVisible()
    assert "Choose a product" in dialog.product_summary.text()
    assert not dialog.number.isVisible()
    artifacts.capture("04a-account-before-product-collapsed", dialog)
    dialog.product.setCurrentIndex(dialog.product.findData("checking"))
    assert "whole account" in dialog.product_summary.text()
    assert dialog.kind.currentData() == "asset" and dialog.scope.currentData() == "account_total"
    qtbot.mouseClick(dialog.account_details_button, Qt.LeftButton)
    assert dialog.kind.isVisible() and dialog.number.isVisible()
    artifacts.capture("04-product-derived-details-disclosed", dialog)


def test_income_category_has_no_expense_budget_task(qtbot, tmp_path):
    profile = tmp_path / "income.db"
    with V2ProfileStore.create(profile) as store:
        store.add_category_account("wages", "Wages", "income")
    dialog = V2CategoryDialog(profile, selected_category_id="wages")
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.category_note.isVisible()
    assert not dialog.budget_box.isVisible() and not dialog.add_panel.isVisible()
    assert dialog.add_name.property("formState") == "neutral"

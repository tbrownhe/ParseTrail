"""Account/category choices retain an honest distinction between drafts and saves."""

from parsetrail.core.v2_account_creation import AccountCreationDraft
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview
from parsetrail.gui.v2_categories import V2CategoryDialog
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
from PySide6.QtCore import Qt

from .qt_journey_helpers import JourneyArtifacts, choose_combo, enter_text
from .test_v2_account_binding_review import DEFINITION, SOURCE
from .v2_institution_helpers import add_test_financial_account


def test_account_draft_invalid_choice_and_saved_edit(qtbot, qapp, journey_artifacts):
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (600, 700))
    form = V2FinancialAccountDialog(draft=AccountCreationDraft())
    qtbot.addWidget(form)
    form.show()
    assert all(field.property("formState") == "required" for field in (form.name, form.product, form.institution))
    assert form.kind.property("formState") == form.scope.property("formState") == "readonly"
    assert form.number.property("formState") == "optional"
    assert not form.save_button.isEnabled()
    artifacts.capture("01-required-account-details", form)
    enter_text(qtbot, form.name, "Synthetic checking")
    choose_combo(qtbot, form.product, "checking")
    assert form.kind.currentData() == "asset" and form.scope.currentData() == "account_total"
    enter_text(qtbot, form.institution.lineEdit(), "Invalid Bank")
    assert form.institution.property("formState") == "invalid"
    assert form.name.property("formState") == "ready"
    artifacts.capture("02-invalid-institution-retains-valid-choices", form)
    choose_combo(qtbot, form.institution, None)
    assert form.save_button.isEnabled() and "Not saved" in form.save_error.text()
    artifacts.capture("03-valid-account-not-saved", form)
    account = form.account()
    form.reject()
    edit = V2FinancialAccountDialog(existing=account)
    qtbot.addWidget(edit)
    edit.show()
    assert edit.name.property("formState") == "saved" and not edit.save_button.isEnabled()
    enter_text(qtbot, edit.name, "Renamed checking")
    assert edit.name.property("formState") == "ready" and edit.save_button.isEnabled()
    assert edit.institution.property("formState") == "saved"
    enter_text(qtbot, edit.name, account.name)
    assert edit.name.property("formState") == "saved" and not edit.save_button.isEnabled()
    artifacts.capture("04-unchanged-saved-account-neutral", edit)


def test_accountless_choice_requires_confirmation_and_preserves_source(qtbot, qapp, tmp_path, journey_artifacts):
    profile = tmp_path / "synthetic.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        add_test_financial_account(store, FinancialAccount("loan", "Synthetic loan", "liability", "mohela"))
    dialog = V2AccountBindingReview(profile, evidence.source_sha256)
    qtbot.addWidget(dialog)
    dialog.show()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1080, 620))
    assert dialog.account_combo.currentData() is None and not dialog.file_button.isEnabled()
    artifacts.capture("01-account-choice-required", dialog)
    choose_combo(qtbot, dialog.account_combo, "loan")
    assert dialog.account_combo.property("formState") == "ready"
    assert "Not saved" in dialog.choice_status.text()
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert all(binding.ledger_account_id is None for binding in store.account_bindings(evidence.source_sha256))
    artifacts.capture("02-chosen-account-not-saved", dialog)
    qtbot.mouseClick(dialog.file_button, Qt.LeftButton)
    assert dialog.account_combo.property("formState") == "saved"
    artifacts.capture("03-account-assignment-saved", dialog)
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert all(binding.ledger_account_id == "loan" for binding in store.account_bindings(evidence.source_sha256))
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_category_and_optional_budget_drafts_become_saved(qtbot, qapp, tmp_path, journey_artifacts):
    profile = tmp_path / "synthetic.db"
    with V2ProfileStore.create(profile):
        pass
    dialog = V2CategoryDialog(profile)
    qtbot.addWidget(dialog)
    dialog.show()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (600, 650))
    assert dialog.add_name.property("formState") == "required"
    enter_text(qtbot, dialog.add_name, "Food")
    assert dialog.add_name.property("formState") == "ready"
    qtbot.mouseClick(dialog.add_button, Qt.LeftButton)
    assert dialog.rename_name.property("formState") == "saved"
    assert not dialog.rename_button.isEnabled()
    assert dialog.budget_amount.property("formState") == "optional"
    assert not dialog.add_panel.isVisible()
    assert dialog.add_name.property("formState") == "neutral"
    qtbot.mouseClick(dialog.options_button, Qt.LeftButton)
    enter_text(qtbot, dialog.rename_name, "Groceries")
    assert dialog.rename_name.property("formState") == "ready"
    qtbot.mouseClick(dialog.rename_button, Qt.LeftButton)
    assert dialog.rename_name.property("formState") == "saved"
    enter_text(qtbot, dialog.budget_amount, "12.345")
    assert dialog.budget_amount.property("formState") == "invalid" and not dialog.budget_save.isEnabled()
    enter_text(qtbot, dialog.budget_amount, "12.34")
    assert dialog.budget_amount.property("formState") == "ready"
    artifacts.capture("01-category-saved-budget-not-saved", dialog)
    qtbot.mouseClick(dialog.budget_save, Qt.LeftButton)
    assert dialog.budget_amount.property("formState") == "saved" and not dialog.budget_save.isEnabled()
    artifacts.capture("02-budget-saved-neutral", dialog)
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert [category.name for category in store.category_accounts()] == ["Groceries"]
        assert store.category_budget_history(dialog.categories.currentItem().data(Qt.UserRole))[0].amount_minor == 1234
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    # A second view may update this same synthetic profile. A successful fresh
    # read must retire the former saved claim while retaining this view's draft.
    category_id = dialog.categories.currentItem().data(Qt.UserRole)
    with V2ProfileStore.open(profile) as store:
        store.set_category_budget_rate(category_id, dialog._month(), 2000)
    dialog.refresh(selected_id=category_id)
    assert "$20.00" in dialog.budget_current.text()
    assert dialog.budget_amount.text() == "12.34"
    assert dialog.budget_amount.property("formState") == "ready" and dialog.budget_save.isEnabled()
    artifacts.capture("03-fresh-stored-target-differs-draft-retained", dialog)
    enter_text(qtbot, dialog.budget_amount, "20.00")
    assert dialog.budget_amount.property("formState") == "saved" and not dialog.budget_save.isEnabled()
    enter_text(qtbot, dialog.budget_amount, "90000000000000")
    assert dialog.budget_amount.property("formState") == "invalid" and not dialog.budget_save.isEnabled()
    dialog._readable = False
    dialog.builtin.setCurrentIndex(1)
    assert dialog.builtin.property("formState") == "blocked"

"""Purpose review and explicit built-in authoring use disposable actual profiles."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date

import pytest
from parsetrail.core.v2_card_lines import parse_card_lines
from parsetrail.core.v2_card_source_output import from_card
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace

from devtools.parser_engine_pilot.test_card_lines import pages
from devtools.parser_engine_pilot.test_card_source_output import DEFINITION as CARD_DEFINITION

from .test_v2_cash_activity_review import DEFINITION, SOURCE


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    def unexpected(_parent, title, message):
        pytest.fail(f"{title}: {message}")

    monkeypatch.setattr(QMessageBox, "warning", unexpected)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    return QApplication.instance() or QApplication([])


def _profile(profile, kind="cash", *, categories=True):
    if kind == "cash":
        source, definition = SOURCE, DEFINITION
        evidence = build_source_evidence(source, definition, suffix=".csv")
    else:
        source, definition = b"%PDF-synthetic-purpose-review", CARD_DEFINITION
        text = [page.replace("PAYMENT", "MERCHANT CREDIT") for page in pages()]
        lines = page_lines(source, text, extraction_library="synthetic-pdf-1")
        evidence = from_card(parse_card_lines(definition, lines), lines)
    with V2ProfileStore.create(profile) as store:
        store.import_source(source, definition, evidence, suffix=".csv" if kind == "cash" else ".pdf")
        store.add_financial_account(
            FinancialAccount("financial", "Reviewed account", "asset" if kind == "cash" else "liability", "synthetic")
        )
        if categories:
            for category_kind in ("expense", "income"):
                for variant in ("a", "b"):
                    store.add_category_account(
                        f"{category_kind}:{variant}", f"{category_kind.title()} {variant}", category_kind
                    )
        if kind == "cash":
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "financial")
        else:
            account = evidence.payload.accounts[0]
            store.bind_source_account(
                evidence.source_sha256, account.source_identity, account.source_identity_form, "financial"
            )
    return evidence


def _dialog(profile, evidence, kind):
    if kind == "cash":
        from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview

        return V2CashActivityReview(profile, evidence.source_sha256)
    from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview

    workspace = V2Workspace.open(
        profile, profile.parent / "catalog", trusted_keys={}, preferences_path=profile.parent / "preferences.json"
    )
    workspace.set_allow_assumed_posting_dates(True)
    return V2CardPurchaseReview(workspace, evidence.source_sha256)


def _choose(dialog, purpose, category):
    dialog.purpose.setCurrentIndex(dialog.purpose.findData(purpose))
    dialog.category.setCurrentIndex(dialog.category.findData(category))
    dialog.reason.setText("Inspected immutable source and explicitly reviewed this purpose")


@pytest.mark.parametrize("kind", ["cash", "card"])
@pytest.mark.parametrize("purpose", ["expense", "expense_refund", "income", "income_adjustment"])
def test_explicit_purpose_and_category_cancel_post_correct_class_and_exact_effects(
    tmp_path, app, monkeypatch, kind, purpose
):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "purposes.db"
    evidence = _profile(profile, kind)
    dialog = _dialog(profile, evidence, kind)
    row_index = 0 if purpose in {"expense", "income_adjustment"} else 1
    category_kind = "expense" if purpose in {"expense", "expense_refund"} else "income"
    try:
        dialog.table.selectRow(row_index)
        row = dialog.model.rows[row_index]
        assert row.purpose is None and purpose in row.allowed_purposes
        assert dialog.purpose.currentData() is None and dialog.category.currentData() is None
        assert not dialog.action_button.isEnabled()
        _choose(dialog, purpose, f"{category_kind}:a")
        assert dialog.action_button.isEnabled()
        assert dialog.category.findData(f"{'income' if category_kind == 'expense' else 'expense'}:a") == -1
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        dialog.action_button.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        questions = []

        def accept(_parent, _title, message):
            questions.append(message)
            return QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", accept)
        dialog.action_button.click()
        posted = dialog.model.rows[row_index]
        assert posted.purpose == purpose and posted.entry_key is not None
        assert "Purpose:" in questions[0] and f"reviewed {category_kind} change:" in questions[0]
        assert "New entry effects:" in questions[0] and "Replacement entry effects" not in questions[0]
        assert "separate review" in questions[0] or "owned card payment" in questions[0]
        assert not dialog.purpose.isEnabled() and dialog.purpose.currentData() == purpose
        if kind == "card":
            dialog.workspace.set_allow_assumed_posting_dates(False)
            dialog.refresh(selected_row_id=posted.row_id)
            assert not dialog.assumed_dates.isChecked()
        dialog.category.setCurrentIndex(dialog.category.findData(f"{category_kind}:b"))
        dialog.reason.setText("Correct category while retaining purpose and class")
        dialog.action_button.click()
        assert "Replacement entry effects only:" in questions[1]
        assert "previous entry is reversed at its original accounting date" in questions[1]
        assert "category-only correction adds $0.00 net account movement" in questions[1]
        assert f"total reviewed {category_kind} unchanged" in questions[1]
        assert "no second money movement" in questions[1]
        assert dialog.model.rows[row_index].purpose == purpose
        assert dialog.model.rows[row_index].category_id == f"{category_kind}:b"
        with V2ProfileStore.open(profile, read_only=True) as store:
            summary = store.reviewed_category_summary(
                kind=category_kind, start=date(2026, 1, 1), end=date(2026, 12, 31)
            )
            assert summary.total_minor == row.amount_minor * (-1 if category_kind == "expense" else 1)
            assert store._active_consumed() == {posted.row_id: row.amount_minor}
            assert store.load_import(evidence.source_sha256).evidence == evidence
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("kind", ["cash", "card"])
def test_purpose_change_requires_withdrawal_then_fresh_explicit_review(tmp_path, app, kind):
    profile = tmp_path / "change-purpose.db"
    evidence = _profile(profile, kind)
    dialog = _dialog(profile, evidence, kind)
    try:
        dialog.table.selectRow(1)
        _choose(dialog, "expense_refund", "expense:a")
        dialog.action_button.click()
        original = dialog.model.rows[1].entry_key
        assert not dialog.purpose.isEnabled() and dialog.purpose.findData("income") == -1
        assert dialog.category.findData("income:a") == -1
        dialog.reason.setText("Withdraw incorrect refund interpretation before reviewing income")
        dialog.withdraw_button.click()
        assert dialog.model.rows[1].entry_key is None
        assert dialog.purpose.currentData() is None and dialog.category.currentData() is None
        assert not dialog.action_button.isEnabled()
        _choose(dialog, "income", "income:a")
        dialog.action_button.click()
        assert dialog.model.rows[1].purpose == "income"
        assert dialog.model.rows[1].entry_key not in {None, original}
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert (
                store.reviewed_category_summary(
                    kind="expense", start=date(2026, 1, 1), end=date(2026, 12, 31)
                ).total_minor
                == 0
            )
            assert (
                store.reviewed_category_summary(
                    kind="income", start=date(2026, 1, 1), end=date(2026, 12, 31)
                ).total_minor
                == dialog.model.rows[1].amount_minor
            )
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("kind", ["cash", "card"])
def test_stale_purpose_form_refreshes_without_posting_or_retaining_default_choices(tmp_path, app, monkeypatch, kind):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "stale-purpose.db"
    evidence = _profile(profile, kind)
    dialog = _dialog(profile, evidence, kind)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    try:
        dialog.table.selectRow(1)
        _choose(dialog, "expense_refund", "expense:a")
        with V2ProfileStore.open(profile) as store:
            store.rename_category_account("expense:a", "Concurrent category rename")
        dialog.action_button.click()
        assert warnings and dialog.model.rows[1].entry_key is None
        assert dialog.purpose.currentData() is None and dialog.category.currentData() is None
        assert not dialog.action_button.isEnabled()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert not store._active_consumed()
    finally:
        dialog.close()
        app.processEvents()


def test_builtin_is_explicit_fixed_and_custom_same_name_remains_distinct(tmp_path, app):
    from parsetrail.gui.v2_categories import V2CategoryDialog
    from PySide6.QtCore import Qt

    profile = tmp_path / "builtins.db"
    with V2ProfileStore.create(profile) as store:
        store.add_category_account("expense:custom-interest", "Loan interest", "expense")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = V2CategoryDialog(profile)
    try:
        assert dialog.categories.count() == 1 and dialog.builtin.currentData() is None
        assert not dialog.add_builtin_button.isEnabled()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        assert "Custom:" in dialog.categories.item(0).text()
        dialog.builtin.setCurrentIndex(dialog.builtin.findData("builtin:loan-interest"))
        assert dialog.add_builtin_button.isEnabled()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        dialog.add_builtin_button.click()
        assert dialog.categories.count() == 2
        assert dialog.categories.currentItem().data(Qt.UserRole) == "builtin:loan-interest"
        assert "Built-in" in dialog.categories.currentItem().text()
        assert not dialog.rename_button.isEnabled() and dialog.rename_name.isReadOnly()
        assert "fixed" in dialog.category_identity.text()
        assert not dialog.add_builtin_button.isEnabled()
        custom = next(
            dialog.categories.item(index)
            for index in range(dialog.categories.count())
            if dialog.categories.item(index).data(Qt.UserRole) == "expense:custom-interest"
        )
        dialog.categories.setCurrentItem(custom)
        assert dialog.rename_button.isEnabled() and not dialog.rename_name.isReadOnly()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert [(item.id, item.name, item.kind) for item in store.category_accounts()] == [
                ("builtin:loan-interest", "Loan interest", "expense"),
                ("expense:custom-interest", "Loan interest", "expense"),
            ]
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        dialog.close()
        app.processEvents()


def test_only_builtin_category_is_never_selected_by_default_for_ordinary_spending(tmp_path, app):
    profile = tmp_path / "no-default.db"
    evidence = _profile(profile, categories=False)
    with V2ProfileStore.open(profile) as store:
        store.ensure_builtin_category("builtin:loan-interest")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile, evidence, "cash")
    try:
        dialog.table.selectRow(0)
        assert dialog.purpose.currentData() is None and dialog.category.currentData() is None
        dialog.purpose.setCurrentIndex(dialog.purpose.findData("expense"))
        assert dialog.category.count() == 2 and dialog.category.currentData() is None
        assert "Built-in" in dialog.category.itemText(dialog.category.findData("builtin:loan-interest"))
        dialog.reason.setText("No category has been explicitly selected")
        assert not dialog.action_button.isEnabled()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("trigger", ["month", "save"])
def test_builtin_corruption_after_show_clears_budget_target_and_controls(tmp_path, app, monkeypatch, trigger):
    from parsetrail.gui.v2_categories import V2CategoryDialog
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "corrupt-builtin.db"
    with V2ProfileStore.create(profile) as store:
        store.ensure_builtin_category("builtin:loan-interest")
        store.set_category_budget_rate("builtin:loan-interest", date(2026, 1, 1), 2500)
    dialog = V2CategoryDialog(profile)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    try:
        dialog.show()
        app.processEvents()
        item = next(
            dialog.categories.item(index)
            for index in range(dialog.categories.count())
            if dialog.categories.item(index).data(Qt.UserRole) == "builtin:loan-interest"
        )
        dialog.categories.setCurrentItem(item)
        assert dialog.budget_history.count() == 1 and "$25.00" in dialog.budget_current.text()
        dialog.budget_amount.setText("99.00")
        with sqlite3.connect(profile) as connection:
            connection.execute("UPDATE Accounts SET name='Corrupted builtin name' WHERE id='builtin:loan-interest'")
        if trigger == "month":
            dialog.budget_month.setDate(dialog.budget_month.date().addMonths(1))
        else:
            dialog.budget_save.click()
            assert warnings
        assert dialog.budget_history.count() == 0
        assert "unavailable" in dialog.budget_current.text()
        assert dialog.budget_amount.text() == ""
        assert not dialog.budget_save.isEnabled() and not dialog.budget_clear.isEnabled()
        assert dialog.categories.count() == 0
        assert not dialog.rename_button.isEnabled() and not dialog.add_button.isEnabled()
        assert not dialog.add_builtin_button.isEnabled() and not dialog._readable
        assert "could not be read" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()

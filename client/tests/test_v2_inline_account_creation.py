"""Inline creation suggests source facts and saves only an authored account."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_account_creation import suggest_account_creation
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_hsa_cash_lines import parse_cash_section
from parsetrail.core.v2_hsa_cash_source_output import from_hsa_cash
from parsetrail.core.v2_loan_history_lines import parse_loan_history
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_two_date_card_lines import parse_two_date_card
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog, create_financial_account
from parsetrail.gui.v2_source_account_review import V2SourceAccountReview
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot import test_hsa_cash_lines as hsa
from devtools.parser_engine_pilot import test_loan_history_lines as capital
from devtools.parser_engine_pilot import test_two_date_card_lines as yamaha

from .test_v2_account_binding_review import DEFINITION as ACCOUNTLESS_DEFINITION
from .test_v2_account_binding_review import SOURCE as ACCOUNTLESS_SOURCE
from .test_v2_source_account_bindings import CASH_DEFINITION, CASH_SOURCE

PDF_SOURCE = b"%PDF-synthetic"


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _workspace(tmp_path, definition, evidence, *, institution="yamaha", kind="liability", source=PDF_SOURCE):
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / "source-definition.json").write_bytes(definition)
    (definitions / "account-contexts.json").write_text(
        json.dumps({evidence.parser_id: {"institution_key": institution, "kind": kind}})
    )
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    workspace = V2Workspace.create(
        tmp_path / "profile.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    workspace.catalog_cache.activate(snapshot, signature)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(source, definition, evidence, suffix=".csv" if source != PDF_SOURCE else ".pdf")
    return workspace


def _suggest(workspace, evidence, section=0):
    account = evidence.payload.accounts[section]
    return suggest_account_creation(
        evidence,
        catalog=workspace.catalog_cache.load_current(),
        source_identity=account.source_identity,
        source_form=account.source_identity_form,
    )


@pytest.mark.parametrize("family", ["yamaha", "capital", "hsa"])
def test_statement_draft_uses_exact_section_scope_and_truthful_number(tmp_path, family):
    if family == "yamaha":
        definition = yamaha.DEFINITION
        evidence = parse_two_date_card(definition, yamaha.lines())
        expected = ("liability", "account_total", None)
    elif family == "capital":
        definition = capital.DEFINITION
        evidence = parse_loan_history(definition, capital.lines())
        expected = ("liability", "principal_component", "1234567890123")
    else:
        definition = hsa.DEFINITION.read_bytes()
        lines = page_lines(PDF_SOURCE, hsa.pages(), extraction_library="synthetic-pdf-1")
        evidence = from_hsa_cash(parse_cash_section(definition, lines), lines)
        expected = ("asset", "cash_component", None)
    workspace = _workspace(tmp_path, definition, evidence, institution=family, kind=expected[0])
    draft = _suggest(workspace, evidence)
    assert (draft.kind, draft.tracking_scope, draft.full_account_number) == expected
    assert draft.verified_context
    assert draft.name.endswith(re.findall(r"[0-9]+", evidence.payload.accounts[0].source_identity)[-1][-4:])
    form = V2FinancialAccountDialog(draft=draft)
    try:
        assert form.source_identity.text() == evidence.payload.accounts[0].source_identity
        assert form.number.text() == (expected[2] or "")
        assert form.kind.currentData() == expected[0]
        assert form.scope.currentData() == expected[1]
        assert form.name.isEnabled() and form.institution.isEnabled()
        assert form.institution.isReadOnly() and not form.institution.hasFrame()
        assert form.source_identity.isReadOnly() and not form.source_identity.hasFrame()
    finally:
        form.close()


@pytest.mark.parametrize("mismatch", ["missing", "parser", "revision", "digest"])
def test_unavailable_exact_context_requires_explicit_kind_and_institution(tmp_path, mismatch):
    evidence = parse_two_date_card(yamaha.DEFINITION, yamaha.lines())
    workspace = _workspace(tmp_path, yamaha.DEFINITION, evidence)
    catalog = workspace.catalog_cache.load_current()
    if mismatch == "missing":
        catalog = None
    else:
        entry = catalog.definitions[0]
        if mismatch == "digest":
            entry = replace(entry, sha256="0" * 64)
        else:
            entry = replace(
                entry,
                identity=replace(entry.identity, **{"parser_id" if mismatch == "parser" else "revision": "other"}),
            )
        catalog = replace(catalog, definitions=(entry,))
    section = evidence.payload.accounts[0]
    draft = suggest_account_creation(
        evidence, catalog=catalog, source_identity=section.source_identity, source_form=section.source_identity_form
    )
    assert draft.institution_key == "" and draft.kind is None and not draft.verified_context
    assert draft.full_account_number is None
    form = V2FinancialAccountDialog(draft=draft)
    try:
        assert form.kind.currentData() is None
        form.accept()
        assert form.result() == QDialog.Rejected
        assert "Choose" in form.save_error.text()
        form.kind.setCurrentIndex(form.kind.findData("liability"))
        assert form.scope.currentData() == "account_total"
        assert form.institution.text() == ""
        assert not form.institution.isReadOnly()
    finally:
        form.close()


def test_selected_section_not_first_section_controls_scope_and_number(tmp_path):
    evidence = parse_loan_history(capital.DEFINITION, capital.lines())
    first = evidence.payload.accounts[0]
    second = first.model_copy(
        update={
            "source_identity": "xxxx7654",
            "source_identity_form": "opaque",
            "balance_scope": "account_total",
            "rows": (),
        }
    )
    evidence = evidence.model_copy(
        update={"payload": evidence.payload.model_copy(update={"accounts": (first, second)})}
    )
    workspace = _workspace(tmp_path, capital.DEFINITION, evidence, institution="capital_one")
    assert _suggest(workspace, evidence, 0).tracking_scope == "principal_component"
    second_draft = _suggest(workspace, evidence, 1)
    assert second_draft.tracking_scope == "account_total"
    assert second_draft.full_account_number is None and second_draft.name == "Capital One 7654"
    with pytest.raises(ValueError, match="selected_source_account_missing"):
        suggest_account_creation(evidence, catalog=None, source_identity="missing", source_form="opaque")


@pytest.mark.parametrize(
    ("identity", "form"),
    [("1234", "last_four"), ("123456XXXXXX7890", "opaque"), ("123456XXXXXX7890", "full"), ("1234567890", "opaque")],
)
def test_abbreviated_or_masked_identity_never_becomes_full_number(identity, form):
    evidence = parse_loan_history(capital.DEFINITION, capital.lines())
    section = evidence.payload.accounts[0].model_copy(
        update={"source_identity": identity, "source_identity_form": form, "rows": ()}
    )
    evidence = evidence.model_copy(update={"payload": evidence.payload.model_copy(update={"accounts": (section,)})})
    draft = suggest_account_creation(evidence, catalog=None, source_identity=identity, source_form=form)
    assert draft.source_identity == identity and draft.name.endswith(identity[-4:])
    assert draft.full_account_number is None


def test_source_creation_selects_new_account_without_assignment_until_confirmed(tmp_path, monkeypatch):
    evidence = parse_two_date_card(yamaha.DEFINITION, yamaha.lines())
    workspace = _workspace(tmp_path, yamaha.DEFINITION, evidence)
    captured = []

    def accept(form):
        captured.append((form.source_identity.text(), form.number.text(), form.scope.currentData()))
        form.name.setText("Owner's Yamaha account")
        form.accept()
        return form.result()

    monkeypatch.setattr(V2FinancialAccountDialog, "exec", accept)
    dialog = V2SourceAccountReview(workspace, evidence.source_sha256)
    try:
        assert dialog.account_combo.currentData() is None and dialog.new_account_button.isEnabled()
        selected = dialog._selected_key()
        dialog.new_account_button.click()
        account_id = dialog.account_combo.currentData()
        assert account_id is not None and dialog._selected_key() == selected
        assert captured == [(selected[0], "", "account_total")]
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert len(store.financial_accounts()) == 1
            assert store.financial_accounts()[0].name == "Owner's Yamaha account"
            assert store.source_account_bindings(evidence.source_sha256)[0].ledger_account_id is None
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
            assert store.load_import(evidence.source_sha256).evidence == evidence
        dialog.assign_button.click()
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.source_account_bindings(evidence.source_sha256)[0].ledger_account_id == account_id
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        dialog.close()


def test_cancel_and_failed_save_retain_values_without_partial_creation(tmp_path, monkeypatch):
    evidence = parse_two_date_card(yamaha.DEFINITION, yamaha.lines())
    workspace = _workspace(tmp_path, yamaha.DEFINITION, evidence)
    draft = _suggest(workspace, evidence)
    before = hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest()
    monkeypatch.setattr(V2FinancialAccountDialog, "exec", lambda _self: QDialog.Rejected)
    assert create_financial_account(workspace.profile_path, draft=draft) is None
    assert hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest() == before
    original = V2ProfileStore.add_financial_account
    attempts, forms, warnings = [], [], []

    def save(store, account):
        attempts.append(account)
        if len(attempts) == 1:
            raise sqlite3.OperationalError("synthetic save refusal")
        original(store, account)

    def accept(form):
        forms.append(form)
        if len(forms) == 1:
            form.name.setText("Edited name retained")
        else:
            assert form is forms[0]
            assert form.name.text() == "Edited name retained"
            assert "synthetic save refusal" in form.save_error.text()
            with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
                assert not store.financial_accounts()
        form.accept()
        return form.result()

    monkeypatch.setattr(V2ProfileStore, "add_financial_account", save)
    monkeypatch.setattr(V2FinancialAccountDialog, "exec", accept)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(True))
    account = create_financial_account(workspace.profile_path, draft=draft)
    assert account.name == "Edited name retained" and len(attempts) == 2 and warnings == [True]
    assert attempts[0].id == attempts[1].id
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.financial_accounts()) == 1
        assert store.source_account_bindings(evidence.source_sha256)[0].ledger_account_id is None
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize("verified", [False, True])
def test_accountless_creation_preserves_rows_and_requires_separate_assignment(tmp_path, monkeypatch, verified):
    evidence = build_source_evidence(ACCOUNTLESS_SOURCE, ACCOUNTLESS_DEFINITION, suffix=".csv")
    workspace = _workspace(tmp_path, ACCOUNTLESS_DEFINITION, evidence, institution="mohela", source=ACCOUNTLESS_SOURCE)
    captured = []

    def accept(form):
        captured.append(form.draft)
        assert form.number.text() == "" and form.draft.source_identity is None
        if not verified:
            assert form.kind.currentData() is None and form.institution.text() == ""
            form.kind.setCurrentIndex(form.kind.findData("liability"))
            assert form.scope.currentData() is None
            form.scope.setCurrentIndex(form.scope.findData("principal_component"))
            form.institution.setText("mohela")
        form.name.setText("Owner's education loan")
        form.accept()
        return form.result()

    monkeypatch.setattr(V2FinancialAccountDialog, "exec", accept)
    dialog = V2AccountBindingReview(
        workspace.profile_path, evidence.source_sha256, workspace=workspace if verified else None
    )
    try:
        selected_row = dialog.model.rows[1].row_id
        dialog.table.selectionModel().select(
            dialog.model.index(1, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows
        )
        dialog.new_account_button.click()
        assert dialog._selected_row_ids() == (selected_row,)
        account_id = dialog.account_combo.currentData()
        assert account_id is not None
        assert captured[0].tracking_scope == ("principal_component" if verified else None)
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert all(binding.ledger_account_id is None for binding in store.account_bindings(evidence.source_sha256))
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        dialog.assign_rows_button.click()
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert [binding.ledger_account_id for binding in store.account_bindings(evidence.source_sha256)] == [
                None,
                account_id,
            ]
            assert store.load_import(evidence.source_sha256).evidence == evidence
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        dialog.close()


def test_other_accountless_family_needs_scope_even_with_signed_liability_context(tmp_path):
    data = json.loads(ACCOUNTLESS_DEFINITION)
    data["parser_id"] = "synthetic_unknown_loan_export"
    definition = json.dumps(data).encode()
    evidence = build_source_evidence(ACCOUNTLESS_SOURCE, definition, suffix=".csv")
    workspace = _workspace(tmp_path, definition, evidence, institution="mohela", source=ACCOUNTLESS_SOURCE)
    draft = suggest_account_creation(evidence, catalog=workspace.catalog_cache.load_current())
    assert draft.kind == "liability" and draft.tracking_scope is None
    form = V2FinancialAccountDialog(draft=draft)
    try:
        assert form.scope.currentData() is None
    finally:
        form.close()


@pytest.mark.parametrize("accountless", [False, True])
def test_locked_assignment_cannot_use_creation_to_bypass_correction(tmp_path, monkeypatch, accountless):
    definition, source = CASH_DEFINITION, CASH_SOURCE
    if accountless:
        data = json.loads(definition)
        data["header"].remove("Account")
        del data["columns"]["account"]
        data["account_key"] = "unknown"
        definition = json.dumps(data).encode()
        source = b"Date,Description,Amount,ReportedBalance\n10/01/2026,Coffee,-$4.00,$996.00\n"
    evidence = build_source_evidence(source, definition, suffix=".csv")
    workspace = _workspace(tmp_path, definition, evidence, institution="synthetic", kind="asset", source=source)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        if accountless:
            store.assert_file_account(evidence.source_sha256, "cash")
        else:
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        store.post_reviewed_cash_category(evidence.payload.rows[0].row_id, "expense:food", reason="Reviewed coffee")
    dialog = (
        V2AccountBindingReview(workspace.profile_path, evidence.source_sha256, workspace=workspace)
        if accountless
        else V2SourceAccountReview(workspace, evidence.source_sha256)
    )

    def accept(form):
        form.name.setText("New choice awaiting correction")
        form.scope.setCurrentIndex(form.scope.findData("account_total"))
        form.accept()
        return form.result()

    monkeypatch.setattr(V2FinancialAccountDialog, "exec", accept)
    try:
        assert dialog.new_account_button.isEnabled()
        dialog._new_account()
        assert dialog.account_combo.currentData() != "cash"
        assert not (dialog.file_button if accountless else dialog.assign_button).isEnabled()
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert len(store.financial_accounts()) == 2
            assert store.account_bindings(evidence.source_sha256)[0].ledger_account_id == "cash"
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)
            assert store.load_import(evidence.source_sha256).evidence == evidence
    finally:
        dialog.close()


def test_standalone_form_import_defaults_and_edit_scope_lock_remain_compatible():
    from parsetrail.gui.v2_workspace_window import V2FinancialAccountDialog as ImportedDialog

    assert ImportedDialog is V2FinancialAccountDialog
    form = ImportedDialog()
    existing = FinancialAccount("loan", "Loan", "liability", "mohela", tracking_scope="principal_component")
    edit = ImportedDialog(existing=existing, scope_locked=True)
    try:
        assert form.kind.currentData() == "asset" and form.scope.currentData() == "account_total"
        assert edit.account() == existing
        assert not edit.kind.isEnabled() and not edit.scope.isEnabled()
    finally:
        form.close()
        edit.close()

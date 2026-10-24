"""Printed source identities need explicit, reversible ledger assignments."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_synchrony_source_output import from_synchrony_table
from parsetrail.core.v2_workspace import V2Workspace

from devtools.parser_engine_pilot.test_synchrony_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_synchrony_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_synchrony_source_output import channels as card_channels

CASH_DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()
CASH_SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
    b"10/02/2026,Checking B,Tea,-$3.00,$997.00\n"
)


def test_identified_export_binds_only_selected_identity_and_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    evidence = build_source_evidence(CASH_SOURCE, CASH_DEFINITION, suffix=".csv")
    source_id = evidence.source_sha256
    with V2ProfileStore.create(path) as store:
        store.import_source(CASH_SOURCE, CASH_DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("checking-a", "Checking A", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("checking-b", "Checking B", "asset", "synthetic"))
        bindings = store.source_account_bindings(source_id)
        assert [(binding.source_identity, binding.ledger_account_id) for binding in bindings] == [
            ("Checking A", None),
            ("Checking B", None),
        ]
        form = bindings[0].source_identity_form
        with pytest.raises(ProfileFormatError, match="source_account_missing"):
            store.bind_source_account(source_id, "Checking C", form, "checking-a")
        with pytest.raises(ProfileFormatError, match="financial_account_missing"):
            store.bind_source_account(source_id, "Checking A", form, "missing")
        store.bind_source_account(source_id, "Checking A", form, "checking-a")
        assert [(binding.ledger_account_id, binding.basis) for binding in store.account_bindings(source_id)] == [
            ("checking-a", "source"),
            (None, None),
        ]
        assert not store.import_source(CASH_SOURCE, CASH_DEFINITION, evidence, suffix=".csv")
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.source_account_bindings(source_id)[0].ledger_account_id == "checking-a"
        assert store.load_import(source_id).evidence == evidence
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            store.clear_source_account_binding(source_id, "Checking A", form)
    with V2ProfileStore.open(path) as store:
        store.clear_source_account_binding(source_id, "Checking A", form)
        assert all(binding.ledger_account_id is None for binding in store.account_bindings(source_id))
        assert store.connection.execute("SELECT count(*) FROM sqlite_master WHERE name='LedgerEntries'").fetchone() == (
            0,
        )


def test_statement_identity_can_be_bound_without_changing_evidence(tmp_path: Path) -> None:
    path = tmp_path / "statement.db"
    evidence = from_synchrony_table(CARD_DEFINITION, *card_channels())
    source_id = evidence.source_sha256
    with V2ProfileStore.create(path) as store:
        store.import_source(CARD_SOURCE, CARD_DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "synchrony"))
        source_account = store.source_account_bindings(source_id)[0]
        assert source_account.ledger_account_id is None
        store.bind_source_account(
            source_id, source_account.source_identity, source_account.source_identity_form, "card"
        )
        assert [(binding.ledger_account_id, binding.basis) for binding in store.account_bindings(source_id)] == [
            ("card", "source")
        ]
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.load_import(source_id).evidence == evidence
        assert store.source_account_bindings(source_id)[0].ledger_account_id == "card"


def test_source_account_review_assigns_and_clears_without_posting(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_source_account_review import V2SourceAccountReview
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "review.db"
    evidence = build_source_evidence(CASH_SOURCE, CASH_DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(CASH_SOURCE, CASH_DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("checking-a", "Checking A", "asset", "synthetic"))
    workspace = V2Workspace.open(path, tmp_path / "catalog", preferences_path=tmp_path / "preferences.json")
    dialog = V2SourceAccountReview(workspace, evidence.source_sha256)
    try:
        assert dialog.identities.count() == 2
        assert "2 of 2" in dialog.status.text()
        assert not dialog.assign_button.isEnabled()
        dialog.account_combo.setCurrentIndex(1)
        assert dialog.assign_button.isEnabled()
        dialog.assign_button.click()
        assert "1 of 2" in dialog.status.text()
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.account_bindings(evidence.source_sha256)[0].basis == "source"
        dialog.clear_button.click()
        assert "2 of 2" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert all(binding.ledger_account_id is None for binding in store.account_bindings(evidence.source_sha256))

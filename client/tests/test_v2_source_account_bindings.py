"""Printed source identities need explicit, reversible ledger assignments."""

from __future__ import annotations

import os
from hashlib import sha256
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
        assert store.connection.execute("SELECT role,currency FROM Accounts WHERE id='checking-a'").fetchone() == (
            "financial",
            "USD",
        )
        assert store.connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='LedgerAccounts'"
        ).fetchone() == (0,)
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


def test_statement_overlap_uses_explicit_account_and_printed_period(tmp_path: Path) -> None:
    path = tmp_path / "overlap.db"
    original = from_synchrony_table(CARD_DEFINITION, *card_channels())
    account = original.payload.accounts[0]
    payload = original.payload.model_copy(
        update={"accounts": (account.model_copy(update={"rows": ()}),), "independent_balance_verified": False}
    )

    def source_variant(label: bytes, *, starts: str = "2026-01-01", ends: str = "2026-01-31"):
        source = CARD_SOURCE + label
        period = payload.model_copy(
            update={
                "start": payload.start.model_copy(update={"iso": starts, "raw": starts}),
                "end": payload.end.model_copy(update={"iso": ends, "raw": ends}),
            }
        )
        evidence = original.model_copy(update={"source_sha256": sha256(source).hexdigest(), "payload": period})
        return source, evidence

    first, first_evidence = source_variant(b" first")
    overlapping, overlapping_evidence = source_variant(b" overlapping", starts="2026-01-15", ends="2026-02-15")
    adjacent, adjacent_evidence = source_variant(b" adjacent", starts="2026-02-16", ends="2026-02-28")
    disjoint, disjoint_evidence = source_variant(b" disjoint", starts="2026-03-01", ends="2026-03-31")
    gapped, gapped_evidence = source_variant(b" gapped", starts="2026-04-02", ends="2026-04-30")
    with V2ProfileStore.create(path) as store:
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "synchrony"))
        store.add_financial_account(FinancialAccount("other", "Other card", "liability", "synchrony"))
        for source, evidence in (
            (first, first_evidence),
            (overlapping, overlapping_evidence),
            (adjacent, adjacent_evidence),
            (disjoint, disjoint_evidence),
            (gapped, gapped_evidence),
        ):
            store.import_source(source, CARD_DEFINITION, evidence, suffix=".pdf")
        identity = account.source_identity
        form = account.source_identity_form
        store.bind_source_account(first_evidence.source_sha256, identity, form, "card")
        assert store.overlapping_statement_sources(first_evidence.source_sha256) == ()
        store.bind_source_account(overlapping_evidence.source_sha256, identity, form, "other")
        assert store.overlapping_statement_sources(first_evidence.source_sha256) == ()
        store.bind_source_account(overlapping_evidence.source_sha256, identity, form, "card")
        store.bind_source_account(adjacent_evidence.source_sha256, identity, form, "card")
        store.bind_source_account(disjoint_evidence.source_sha256, identity, form, "card")
        store.bind_source_account(gapped_evidence.source_sha256, identity, form, "card")
    with V2ProfileStore.open(path, read_only=True) as store:
        coverage = store.statement_coverage()
        assert [row.relation_to_known_periods for row in coverage] == [
            "first_known",
            "overlap",
            "adjacent",
            "adjacent",
            "gap",
        ]
        assert [row.source_sha256 for row in coverage] == [
            first_evidence.source_sha256,
            overlapping_evidence.source_sha256,
            adjacent_evidence.source_sha256,
            disjoint_evidence.source_sha256,
            gapped_evidence.source_sha256,
        ]
        assert coverage[0].period_start.isoformat() == "2026-01-01"
        assert coverage[0].opening == account.opening
        assert all(not row.independent_balance_verified for row in coverage)
        assert store.overlapping_statement_sources(first_evidence.source_sha256) == (
            overlapping_evidence.source_sha256,
        )
        assert store.overlapping_statement_sources(overlapping_evidence.source_sha256) == (
            first_evidence.source_sha256,
        )
        assert store.overlapping_statement_sources(disjoint_evidence.source_sha256) == ()
        assert store.connection.execute("SELECT count(*) FROM sqlite_master WHERE name='LedgerEntries'").fetchone() == (
            0,
        )
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])
    workspace = V2Workspace.open(path, tmp_path / "catalog", preferences_path=tmp_path / "preferences.json")
    window = V2WorkspaceWindow(workspace)
    try:
        dialog = V2StatementCoverageDialog(path, window)
        assert dialog.model.rowCount() == 5
        assert dialog.model.data(dialog.model.index(2, 2)) == "Adjacent dates"
        assert dialog.model.data(dialog.model.index(4, 2)) == "Calendar gap"
        assert "do not establish" in dialog.findChildren(QLabel)[1].text()
        dialog.close()
        for index in range(window.sources.count()):
            if window.sources.item(index).data(Qt.UserRole) == first_evidence.source_sha256:
                window.sources.setCurrentRow(index)
                break
        assert "Possible period overlap" in window.selected_details.text()
        assert overlapping_evidence.source_sha256[:16] in window.selected_details.text()
        assert disjoint_evidence.source_sha256[:16] not in window.selected_details.text()
        with V2ProfileStore.open(path) as store:
            store.clear_source_account_binding(overlapping_evidence.source_sha256, identity, form)
        window.refresh(select_source=first_evidence.source_sha256)
        assert "Possible period overlap" not in window.selected_details.text()
    finally:
        window.close()
        app.processEvents()


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


def test_source_account_review_explains_posted_assignment_lock(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_source_account_review import V2SourceAccountReview
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "review.db"
    evidence = build_source_evidence(CASH_SOURCE, CASH_DEFINITION, suffix=".csv")
    row = evidence.payload.rows[0]
    with V2ProfileStore.create(path) as store:
        store.import_source(CASH_SOURCE, CASH_DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("checking-a", "Checking A", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.bind_source_account(evidence.source_sha256, row.source_account, row.source_account_form, "checking-a")
    workspace = V2Workspace.open(path, tmp_path / "catalog", preferences_path=tmp_path / "preferences.json")
    stale_dialog = V2SourceAccountReview(workspace, evidence.source_sha256)
    assert stale_dialog.clear_button.isEnabled()
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: messages.append(message))
    with V2ProfileStore.open(path) as store:
        store.post_reviewed_cash_category(row.row_id, "expense:food", reason="Reviewed coffee")
        assert row.row_id in store.journal_history_row_ids(evidence.source_sha256)
    stale_dialog.clear_button.click()
    assert messages and "posted journal history" in messages[0]
    assert "account_binding_has_journal_history" not in messages[0]
    assert not stale_dialog.clear_button.isEnabled()
    stale_dialog.close()
    dialog = V2SourceAccountReview(workspace, evidence.source_sha256)
    try:
        selected = next(
            index for index, binding in enumerate(dialog.bindings) if binding.source_identity == row.source_account
        )
        dialog.identities.setCurrentRow(selected)
        dialog.account_combo.setCurrentIndex(1)
        assert "Locked by posted entries" in dialog.identities.currentItem().text()
        assert "posted journal history" in dialog.lock_notice.text()
        assert not dialog.assign_button.isEnabled()
        assert not dialog.clear_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()

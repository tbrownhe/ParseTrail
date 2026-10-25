"""Positions show exact reviewed books and opening/evidence limits without writes."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_table_card_source_output import from_anchored_card

from devtools.parser_engine_pilot.test_table_card_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_table_card_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_table_card_source_output import evidence as card_channels

from .test_v2_reviewed_openings import _profile as opening_profile
from .test_v2_statement_journal_comparison import _profile as statement_profile
from .test_v2_statement_reconciliation import _review_and_post
from .test_v2_transfers import _profile as transfer_profile

CASH_DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _dialog(profile: Path):
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog

    dialog = V2ReviewedReportsDialog(profile)
    dialog.tabs.setCurrentIndex(4)
    return dialog


def _cell(model, row: int, column: int):
    return model.data(model.index(row, column))


def test_positions_empty_and_failed_refresh_clear_data_without_writes(tmp_path: Path, app, monkeypatch):
    profile = tmp_path / "empty.db"
    with V2ProfileStore.create(profile):
        pass
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile)
    try:
        dialog.show()
        app.processEvents()
        assert dialog.positions_model.rowCount() == 0
        assert dialog.history_model.rowCount() == 0
        assert "No financial accounts" in dialog.position_details.text()
        assert "USD" in dialog.total.text()
        assert "0 activity row(s) have no account binding" in dialog.scope.text()
        assert dialog.positions_table.viewport().width() > 800

        def unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError("synthetic read failure")

        monkeypatch.setattr(V2ProfileStore, "account_positions", unavailable)
        dialog._refresh_positions()
        assert dialog.positions_report is None
        assert dialog.positions_model.rowCount() == 0
        assert "unavailable" in dialog.total.text()
        assert "synthetic read failure" in dialog.scope.text()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_positions_pending_and_unbound_scope_is_independent_of_period_range(tmp_path: Path, app, monkeypatch):
    from PySide6.QtCore import QDate

    source = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
        b"10/02/2026,Checking A,Deposit,$10.00,$1006.00\n"
        b"10/03/2026,Unbound B,Unreviewed,-$2.00,$998.00\n"
    )
    evidence = build_source_evidence(source, CASH_DEFINITION, suffix=".csv")
    profile = tmp_path / "pending.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(source, CASH_DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        store.post_reviewed_cash_category(evidence.payload.rows[0].row_id, "expense:food", reason="Coffee")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile)
    try:
        dialog.as_of.setDate(QDate(2026, 10, 1))
        assert _cell(dialog.positions_model, 0, 2) == "-$4.00"
        assert _cell(dialog.positions_model, 0, 3) == "Unknown"
        assert _cell(dialog.positions_model, 0, 4) == "Not established"
        assert _cell(dialog.positions_model, 0, 5) == "1"
        assert "1 activity row(s) have no account binding" in dialog.scope.text()
        assert "across all dates" in dialog.position_details.text()
        assert "not a saved reconciliation cutoff" in dialog.position_details.text()
        assert dialog.history_model.rowCount() == 1
        assert _cell(dialog.history_model, 0, 2) == "-$4.00"
        assert _cell(dialog.history_model, 0, 4) == "Unknown"
        dialog.start.setDate(QDate(2026, 11, 1))
        dialog.end.setDate(QDate(2026, 11, 1))
        assert dialog.model.rowCount() == 0
        assert dialog.positions_model.rowCount() == 1
        assert "As of 2026-10-01" in dialog.total.text()
        assert not dialog.export_button.isEnabled()
        dialog.as_of.setDate(QDate(2026, 9, 30))
        assert _cell(dialog.positions_model, 0, 2) == "$0.00"
        assert _cell(dialog.positions_model, 0, 3) == "Unknown"
        assert dialog.history_model.rowCount() == 0
        assert _cell(dialog.positions_model, 0, 5) == "1"

        def unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError("synthetic read failure")

        monkeypatch.setattr(V2ProfileStore, "account_positions", unavailable)
        dialog._refresh_positions()
        assert dialog.positions_report is None
        assert dialog.positions_model.rowCount() == 0
        assert dialog.history_model.rowCount() == 0
        assert "unavailable" in dialog.total.text()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_positions_opening_cutoff_live_check_corrections_and_stale_state(tmp_path: Path, app):
    from PySide6.QtCore import QDate, Qt

    profile = tmp_path / "reviewed.db"
    evidence = statement_profile(profile)
    with V2ProfileStore.open(profile) as store:
        _review_and_post(store, evidence)
        original = f"review:cash:expense:{evidence.payload.accounts[0].rows[1].row_id}"
        store.correct_reviewed_cash_category(original, "expense:travel", reason="Reviewed category correction")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile)
    try:
        dialog.as_of.setDate(QDate(2026, 1, 31))
        assert _cell(dialog.positions_model, 0, 2) == "$90.00"
        assert _cell(dialog.positions_model, 0, 3) == "$90.00"
        assert _cell(dialog.positions_model, 0, 4) == "Valid at as-of date"
        assert _cell(dialog.positions_model, 0, 6) == "2026-01-31"
        assert dialog.history_model.rowCount() == 5
        assert {row.correction_role for row in dialog.history_model.rows} >= {"original", "reversal", "replacement"}
        assert "as they stand now" in dialog.history_model.data(dialog.history_model.index(0, 1), Qt.ToolTipRole)
        assert "not a saved reconciliation cutoff" in dialog.position_details.text()
        assert "Source page capture unverified" in dialog.position_details.text()
        assert dialog.history_table.columnWidth(1) > 100
        dialog.as_of.setDate(QDate(2025, 12, 30))
        assert _cell(dialog.positions_model, 0, 3) == "Unknown"
        assert _cell(dialog.positions_model, 0, 4) == "After as-of date"
        assert dialog.history_model.rowCount() == 0
        dialog.as_of.setDate(QDate(2025, 12, 31))
        assert _cell(dialog.positions_model, 0, 3) == "$100.00"
        assert _cell(dialog.positions_model, 0, 6) == "None passing"
        assert dialog.history_model.rowCount() == 1
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
    with V2ProfileStore.open(profile) as store:
        latest = store.statement_source_reviews("cash")[0]
        store.record_statement_source_review(
            "cash",
            evidence.source_sha256,
            expected_revision_id=latest.revision_id,
            opening_origin="reported",
            closing_origin="reported",
            timing_confirmed=True,
            posting_dates="reported",
            source_reference="Updated source inspection",
        )
    dialog = _dialog(profile)
    try:
        dialog.as_of.setDate(QDate(2026, 1, 31))
        assert _cell(dialog.positions_model, 0, 2) == "$90.00"
        assert _cell(dialog.positions_model, 0, 3) == "Unknown"
        assert "Stale" in _cell(dialog.positions_model, 0, 4)
        assert _cell(dialog.positions_model, 0, 6) == "None passing"
    finally:
        dialog.close()
        app.processEvents()


def test_liability_opening_is_displayed_as_amount_owed(tmp_path: Path, app):
    from PySide6.QtCore import QDate

    profile = tmp_path / "card.db"
    evidence = from_anchored_card(CARD_DEFINITION, *card_channels())
    with V2ProfileStore.create(profile) as store:
        store.import_source(CARD_SOURCE, CARD_DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "citi"))
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        store.record_opening_source_review(
            "card",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Synthetic printed card opening",
        )
        store.post_reviewed_opening("card")
    dialog = _dialog(profile)
    try:
        dialog.as_of.setDate(QDate(2025, 12, 31))
        assert _cell(dialog.positions_model, 0, 1) == "Liability"
        assert _cell(dialog.positions_model, 0, 2) == "$100.00"
        assert _cell(dialog.positions_model, 0, 3) == "$100.00"
        assert _cell(dialog.history_model, 0, 2) == "$100.00"
        assert "Opening: $100.00" in dialog.position_details.text()
    finally:
        dialog.close()
        app.processEvents()


def test_zero_opening_is_known_without_a_history_posting(tmp_path: Path, app):
    from PySide6.QtCore import QDate

    profile = tmp_path / "zero.db"
    evidence = opening_profile(profile, amount_minor=0)
    with V2ProfileStore.open(profile) as store:
        store.record_opening_source_review(
            "cash",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Synthetic printed zero opening",
        )
        store.post_reviewed_opening("cash")
    dialog = _dialog(profile)
    try:
        dialog.as_of.setDate(QDate(2025, 12, 31))
        assert _cell(dialog.positions_model, 0, 2) == "$0.00"
        assert _cell(dialog.positions_model, 0, 3) == "$0.00"
        assert _cell(dialog.positions_model, 0, 4) == "Valid at as-of date"
        assert dialog.history_model.rowCount() == 0
        assert "Opening: $0.00" in dialog.position_details.text()
    finally:
        dialog.close()
        app.processEvents()


def test_different_date_payment_displays_clearing_and_preserves_selected_account(tmp_path: Path, app):
    from PySide6.QtCore import QDate

    profile = tmp_path / "payment.db"
    cash_row, card_row = transfer_profile(profile, bank_date="01/03/2026")
    with V2ProfileStore.open(profile) as store:
        store.post_reviewed_transfer(cash_row, card_row, preferences=V2Preferences(), reason="Reviewed payment")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile)
    try:
        dialog.as_of.setDate(QDate(2026, 1, 3))
        assert "Transfer clearing recorded total: $20.00" in dialog.total.text()
        card_index = next(index for index, row in enumerate(dialog.positions_model.rows) if row.account_id == "card")
        dialog.positions_table.selectRow(card_index)
        assert _cell(dialog.positions_model, card_index, 2) == "$0.00"
        assert dialog.history_model.rowCount() == 0
        dialog.as_of.setDate(QDate(2026, 1, 5))
        assert "Transfer clearing recorded total: $0.00" in dialog.total.text()
        assert dialog.positions_model.rows[dialog.positions_table.currentIndex().row()].account_id == "card"
        assert _cell(dialog.positions_model, card_index, 2) == "-$20.00"
        assert _cell(dialog.positions_model, card_index, 3) == "Unknown"
        assert dialog.history_model.rowCount() == 1
        assert _cell(dialog.history_model, 0, 2) == "-$20.00"
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before

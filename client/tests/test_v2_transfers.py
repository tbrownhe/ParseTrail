"""Reviewed transfers consume two owned movements without creating spending."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_card_lines import parse_card_lines
from parsetrail.core.v2_card_source_output import from_card
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_table_card_source_output import from_anchored_card

from devtools.parser_engine_pilot.test_card_lines import pages
from devtools.parser_engine_pilot.test_card_source_output import DEFINITION as CHASE_DEFINITION
from devtools.parser_engine_pilot.test_table_card_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_table_card_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_table_card_source_output import evidence as card_channels

BANK_DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()


def _profile(path: Path, *, bank_date: str):
    source = (
        f"Date,Account,Description,Amount,ReportedBalance\n{bank_date},Checking A,Card payment,-$20.00,$980.00\n"
    ).encode()
    bank = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    card = from_anchored_card(CARD_DEFINITION, *card_channels())
    with V2ProfileStore.create(path) as store:
        store.import_source(source, BANK_DEFINITION, bank, suffix=".csv")
        store.import_source(CARD_SOURCE, CARD_DEFINITION, card, suffix=".pdf")
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "citi"))
        store.add_category_account("expense:food", "Food", "expense")
        store.bind_source_account(bank.source_sha256, "Checking A", "opaque", "checking")
        account = card.payload.accounts[0]
        store.bind_source_account(card.source_sha256, account.source_identity, account.source_identity_form, "card")
    return bank.payload.rows[0].row_id, card.payload.accounts[0].rows[0].row_id


@pytest.mark.parametrize("bank_date,entry_count", [("01/05/2026", 1), ("01/03/2026", 2)])
def test_card_payment_pair_preserves_dates_and_has_no_expense(tmp_path: Path, bank_date: str, entry_count: int):
    path = tmp_path / "transfer.db"
    cash_id, card_id = _profile(path, bank_date=bank_date)
    with V2ProfileStore.open(path) as store:
        candidates = store.transfer_candidates(preferences=V2Preferences())
        assert len(candidates) == 1
        pair = candidates[0]
        assert (pair.outgoing.row_id, pair.incoming.row_id, pair.kind) == (cash_id, card_id, "card payment")
        assert pair.posting_allowed
        event = store.post_reviewed_transfer(
            cash_id, card_id, preferences=V2Preferences(), reason="Confirmed repayment"
        )
        assert event.startswith("review:transfer:")
        assert store._active_consumed() == {cash_id: -2000, card_id: 2000}
        assert (
            store.post_reviewed_transfer(cash_id, card_id, preferences=V2Preferences(), reason="Confirmed repayment")
            == event
        )
        assert not store.transfer_candidates(preferences=V2Preferences())
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
        entries = [json.loads(payload) for (payload,) in store.connection.execute("SELECT payload FROM JournalEntries")]
        assert len(entries) == entry_count
        assert {entry["posting_date"] for entry in entries} == (
            {"2026-01-05"} if entry_count == 1 else {"2026-01-03", "2026-01-05"}
        )
        assert all(entry["event_id"] == event and entry["reviewed"] for entry in entries)
        if entry_count == 2:
            assert store.connection.execute(
                "SELECT kind,purpose FROM Accounts WHERE id='internal:transfer-clearing:USD'"
            ).fetchone() == ("asset", "clearing")
            assert (
                sum(
                    posting["amount_minor"]
                    for entry in entries
                    for posting in entry["postings"]
                    if posting["account_id"] == "internal:transfer-clearing:USD"
                )
                == 0
            )
        with pytest.raises(ProfileFormatError, match="transfer_conflicts_with_prior_decision"):
            store.post_reviewed_transfer(cash_id, card_id, preferences=V2Preferences(), reason="Again")


def test_transfer_refuses_consumed_cash(tmp_path: Path):
    path = tmp_path / "transfer.db"
    cash_id, card_id = _profile(path, bank_date="01/05/2026")
    with V2ProfileStore.open(path) as store:
        store.post_reviewed_cash_category(cash_id, "expense:food", reason="Initial classification")
        assert not store.transfer_candidates(preferences=V2Preferences())
        with pytest.raises(ProfileFormatError, match="transfer_pair_unavailable_or_already_posted"):
            store.post_reviewed_transfer(cash_id, card_id, preferences=V2Preferences(), reason="Conflicting payment")
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (1,)


def test_assumed_card_payment_date_needs_global_choice(tmp_path: Path):
    path = tmp_path / "assumed.db"
    cash_source = (
        b"Date,Account,Description,Amount,ReportedBalance\n04/01/2026,Checking A,Card payment,-$5.00,$995.00\n"
    )
    cash = build_source_evidence(cash_source, BANK_DEFINITION, suffix=".csv")
    card_source = b"%PDF-assumed-transfer-test"
    lines = page_lines(card_source, pages(), extraction_library="synthetic-pdf-1")
    card = from_card(parse_card_lines(CHASE_DEFINITION, lines), lines)
    with V2ProfileStore.create(path) as store:
        store.import_source(cash_source, BANK_DEFINITION, cash, suffix=".csv")
        store.import_source(card_source, CHASE_DEFINITION, card, suffix=".pdf")
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "chase"))
        store.bind_source_account(cash.source_sha256, "Checking A", "opaque", "checking")
        account = card.payload.accounts[0]
        store.bind_source_account(card.source_sha256, account.source_identity, account.source_identity_form, "card")
        pair = store.transfer_candidates(preferences=V2Preferences())[0]
        assert pair.incoming.date_provenance == "assumed" and not pair.posting_allowed
        with pytest.raises(ProfileFormatError, match="transfer_assumed_date_disabled"):
            store.post_reviewed_transfer(
                pair.outgoing.row_id,
                pair.incoming.row_id,
                preferences=V2Preferences(),
                reason="Confirmed repayment",
            )
        store.post_reviewed_transfer(
            pair.outgoing.row_id,
            pair.incoming.row_id,
            preferences=V2Preferences(False, True),
            reason="Confirmed repayment",
        )


def test_asset_transfer_candidates_keep_multiple_matches_explicit(tmp_path: Path):
    path = tmp_path / "assets.db"
    outgoing_source = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"01/05/2026,Checking A,Transfer A,-$20.00,$980.00\n"
        b"01/05/2026,Checking A,Transfer B,-$20.00,$960.00\n"
    )
    incoming_source = b"Date,Account,Description,Amount,ReportedBalance\n01/06/2026,Savings B,Deposit,$20.00,$1020.00\n"
    outgoing = build_source_evidence(outgoing_source, BANK_DEFINITION, suffix=".csv")
    incoming = build_source_evidence(incoming_source, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        for source, evidence in ((outgoing_source, outgoing), (incoming_source, incoming)):
            store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("savings", "Savings", "asset", "synthetic"))
        store.bind_source_account(outgoing.source_sha256, "Checking A", "opaque", "checking")
        store.bind_source_account(incoming.source_sha256, "Savings B", "opaque", "savings")
        pairs = store.transfer_candidates(preferences=V2Preferences())
        assert len(pairs) == 2
        assert {pair.kind for pair in pairs} == {"asset transfer"}
        selected = pairs[1]
        store.post_reviewed_transfer(
            selected.outgoing.row_id,
            selected.incoming.row_id,
            preferences=V2Preferences(),
            reason="Chose this pair from two possibilities",
        )
        assert store._active_consumed() == {
            selected.outgoing.row_id: -2000,
            selected.incoming.row_id: 2000,
        }
        assert (
            outgoing.payload.rows[0].row_id not in store._active_consumed()
            or outgoing.payload.rows[1].row_id not in store._active_consumed()
        )
        assert not store.transfer_candidates(preferences=V2Preferences())


def test_transfer_dialog_requires_selection_and_confirmation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_transfer_review import V2TransferReview
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "transfer.db"
    cash_id, card_id = _profile(path, bank_date="01/03/2026")
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    questions = []

    def answer(_parent, _title, message):
        questions.append(message)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer)
    dialog = V2TransferReview(workspace)
    try:
        dialog.show()
        app.processEvents()
        assert dialog.table.rowCount() == 1
        assert not dialog.confirm.isEnabled()
        dialog.table.selectRow(0)
        assert dialog.confirm.isEnabled()
        dialog.confirm.click()
        assert len(questions) == 1
        assert "No income or expense is created" in questions[0]
        assert dialog.table.rowCount() == 0
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store._active_consumed() == {cash_id: -2000, card_id: 2000}
    finally:
        dialog.close()
        app.processEvents()

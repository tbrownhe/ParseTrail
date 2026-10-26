"""Reviewed card purchases use source rows once and correct dates append-only."""

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
from parsetrail.core.v2_table_card_source_output import from_anchored_card
from parsetrail.core.v2_workspace import V2Workspace

from devtools.parser_engine_pilot.test_card_lines import pages
from devtools.parser_engine_pilot.test_card_source_output import DEFINITION as CHASE_DEFINITION
from devtools.parser_engine_pilot.test_table_card_source_output import DEFINITION as CITI_DEFINITION
from devtools.parser_engine_pilot.test_table_card_source_output import SOURCE as CITI_SOURCE
from devtools.parser_engine_pilot.test_table_card_source_output import evidence as citi_channels


def _chase_profile(path: Path):
    source = b"%PDF-card-purchase-test"
    lines = page_lines(source, pages(), extraction_library="synthetic-pdf-1")
    evidence = from_card(parse_card_lines(CHASE_DEFINITION, lines), lines)
    with V2ProfileStore.create(path) as store:
        store.import_source(source, CHASE_DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "chase"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
        store.add_category_account("income:other", "Other income", "income")
    return evidence


def test_assumed_card_date_requires_global_choice_or_explicit_different_date(tmp_path: Path) -> None:
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    purchase, payment = evidence.payload.accounts[0].rows
    with V2ProfileStore.open(path) as store:
        assert store.card_purchase_review_rows(evidence.source_sha256, preferences=V2Preferences())[0].status == (
            "Assign a financial account first"
        )
        source_account = evidence.payload.accounts[0]
        store.bind_source_account(
            evidence.source_sha256, source_account.source_identity, source_account.source_identity_form, "card"
        )
        rows = store.card_purchase_review_rows(evidence.source_sha256, preferences=V2Preferences())
        assert rows[0].source_date == "2026-03-15"
        assert rows[0].posting_candidate == "2026-03-16"
        assert rows[0].date_provenance == "assumed"
        assert rows[0].status == "Enable assumed dates or enter a corrected date"
        assert rows[1].status == "Enable assumed dates or enter a corrected date"
        assert rows[1].purpose is None and rows[1].allowed_purposes == ("expense_refund", "income")
        with pytest.raises(ProfileFormatError, match="card_purchase_assumed_date_disabled"):
            store.post_reviewed_card_purchase(
                purchase.row_id, "expense:food", reason="Reviewed charge", preferences=V2Preferences()
            )
        with pytest.raises(ProfileFormatError, match="card_purchase_assumed_date_disabled"):
            store.post_reviewed_card_purchase(
                purchase.row_id,
                "expense:food",
                reason="Reviewed charge",
                preferences=V2Preferences(),
                accounting_date=date(2026, 3, 16),
            )
        with pytest.raises(ProfileFormatError, match="card_category_purpose_invalid"):
            store.post_reviewed_card_purchase(
                payment.row_id, "expense:food", reason="Wrong sign", preferences=V2Preferences(True, True)
            )
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
        key = store.post_reviewed_card_purchase(
            purchase.row_id,
            "expense:food",
            reason="Reviewed date from statement",
            preferences=V2Preferences(),
            accounting_date=date(2026, 3, 17),
        )
        assert key == f"review:card:expense:{purchase.row_id}"
        assert store.card_purchase_review_rows(evidence.source_sha256, preferences=V2Preferences())[
            0
        ].effective_date == ("2026-03-17")
    with V2ProfileStore.open(path, read_only=True) as store:
        entry = json.loads(
            store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[0]
        )
        assert entry["posting_date"] == "2026-03-17"
        assert [(item["account_id"], item["amount_minor"]) for item in entry["postings"]] == [
            ("card", -1000),
            ("expense:food", 1000),
        ]
        assert store._active_consumed() == {purchase.row_id: -1000}
        assert store.load_import(evidence.source_sha256).evidence == evidence


def test_card_date_and_category_correction_preserves_source_and_allocation(tmp_path: Path) -> None:
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    purchase = evidence.payload.accounts[0].rows[0]
    with V2ProfileStore.open(path) as store:
        source_account = evidence.payload.accounts[0]
        store.bind_source_account(
            evidence.source_sha256, source_account.source_identity, source_account.source_identity_form, "card"
        )
        original = store.post_reviewed_card_purchase(
            purchase.row_id, "expense:food", reason="Reviewed guess", preferences=V2Preferences(False, True)
        )
        assert (
            store.post_reviewed_card_purchase(
                purchase.row_id, "expense:food", reason="Reviewed guess", preferences=V2Preferences(False, True)
            )
            == original
        )
        with pytest.raises(ProfileFormatError, match="card_correction_requires_changed_category_or_date"):
            store.correct_reviewed_card_purchase(original, "expense:food", reason="No change")
        corrected = store.correct_reviewed_card_purchase(
            original, "expense:food", reason="Corrected posting date", accounting_date=date(2026, 4, 1)
        )
        assert (
            store.correct_reviewed_card_purchase(
                original, "expense:food", reason="Corrected posting date", accounting_date=date(2026, 4, 1)
            )
            == corrected
        )
        with pytest.raises(ProfileFormatError, match="card_correction_conflicts_with_prior_decision"):
            store.correct_reviewed_card_purchase(
                original, "expense:food", reason="Different", accounting_date=date(2026, 3, 18)
            )
        with pytest.raises(ProfileFormatError, match="card_purchase_already_corrected"):
            store.post_reviewed_card_purchase(
                purchase.row_id, "expense:food", reason="Reviewed guess", preferences=V2Preferences(False, True)
            )
        recategorized = store.correct_reviewed_card_purchase(corrected, "expense:travel", reason="Corrected category")
        assert recategorized != corrected
        assert store._active_consumed() == {purchase.row_id: -1000}
        rows = store.card_purchase_review_rows(evidence.source_sha256, preferences=V2Preferences())
        assert rows[0].status == "Posted: Travel" and rows[0].effective_date == "2026-04-01"
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 3, 1), end=date(2026, 4, 1)).total_minor
            == 0
        )
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 4, 1), end=date(2026, 5, 1)).total_minor
            == 1000
        )
        assert store.connection.execute("SELECT COUNT(*) FROM JournalCorrections").fetchone() == (2,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalAllocations").fetchone() == (3,)
    with V2ProfileStore.open(path, read_only=True) as store:
        entries = {
            key: json.loads(payload)
            for key, payload in store.connection.execute("SELECT key,payload FROM JournalEntries")
        }
        assert entries[original]["posting_date"] == "2026-03-16"
        assert entries[corrected]["posting_date"] == "2026-04-01"
        assert entries[recategorized]["posting_date"] == "2026-04-01"
        assert store.load_import(evidence.source_sha256).evidence == evidence


def test_printed_post_date_card_purchase_needs_no_assumption_toggle(tmp_path: Path) -> None:
    evidence = from_anchored_card(CITI_DEFINITION, *citi_channels())
    path = tmp_path / "printed.db"
    with V2ProfileStore.create(path) as store:
        store.import_source(CITI_SOURCE, CITI_DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "citi"))
        store.add_category_account("expense:travel", "Travel", "expense")
        source_account = evidence.payload.accounts[0]
        store.bind_source_account(
            evidence.source_sha256, source_account.source_identity, source_account.source_identity_form, "card"
        )
        rows = store.card_purchase_review_rows(evidence.source_sha256, preferences=V2Preferences())
        assert rows[0].status == "Ready for purpose review" and rows[0].purpose is None
        assert rows[1].date_provenance == "derived" and rows[1].status == "Ready for purpose review"
        key = store.post_reviewed_card_purchase(
            rows[1].row_id, "expense:travel", reason="Reviewed purchase", preferences=V2Preferences()
        )
        assert key.startswith("review:card:expense:")
        assert store._active_consumed() == {rows[1].row_id: -1000}


def test_card_review_dialog_toggles_assumed_date_and_corrects_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        source_account = evidence.payload.accounts[0]
        store.bind_source_account(
            evidence.source_sha256, source_account.source_identity, source_account.source_identity_form, "card"
        )
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    confirmations = []

    def confirm(_parent, _title, message):
        confirmations.append(message)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    window = V2WorkspaceWindow(workspace)
    dialog = V2CardPurchaseReview(workspace, evidence.source_sha256, window)
    try:
        assert window.card_review_button.isEnabled()
        dialog.show()
        dialog.table.selectRow(0)
        app.processEvents()
        assert not dialog.action_button.isEnabled()
        assert dialog.assumed_dates.isVisible()
        assert dialog.model.data(dialog.model.index(0, 1)) == "2026-03-16 (assumed)"
        dialog.assumed_dates.click()
        assert workspace.preferences().allow_assumed_posting_dates
        assert dialog.purpose.currentData() is None and dialog.category.currentData() is None
        dialog.purpose.setCurrentIndex(dialog.purpose.findData("expense"))
        dialog.category.setCurrentIndex(dialog.category.findData("expense:food"))
        dialog.reason.setText("Reviewed card charge")
        assert dialog.action_button.isEnabled()
        dialog.action_button.click()
        assert dialog.model.rows[0].status == "Posted: Food"
        assert dialog.model.rows[1].status == "Ready for purpose review" and dialog.model.rows[1].purpose is None
        dialog.accounting_date.setText("2026-03-17")
        dialog.reason.setText("Corrected date")
        assert dialog.action_button.isEnabled()
        dialog.action_button.click()
        assert dialog.model.rows[0].effective_date == "2026-03-17"
        assert "Replacement entry effects only:" in confirmations[1]
        assert "original accounting date (2026-03-16)" in confirmations[1]
        assert "replacement is dated 2026-03-17" in confirmations[1]
        assert "Individual dates and periods are restated" in confirmations[1]
        assert "$0.00 net account movement" in confirmations[1]
        assert "category-only correction" not in confirmations[1]
        dialog.table.selectRow(1)
        assert not dialog.action_button.isEnabled()
    finally:
        dialog.close()
        window.close()
        app.processEvents()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM JournalCorrections").fetchone() == (1,)
        assert store.load_import(evidence.source_sha256).evidence == evidence

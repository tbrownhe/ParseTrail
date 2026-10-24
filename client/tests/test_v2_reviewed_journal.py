"""A reviewed cash expense uses source evidence and one fresh 2.0 database."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()
SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
    b"10/02/2026,Checking A,Deposit,$10.00,$1006.00\n"
)


def test_reviewed_cash_expense_reopens_once_and_other_row_stays_pending(tmp_path: Path) -> None:
    profile = tmp_path / "fresh.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    outflow, inflow = evidence.payload.rows
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        key = store.post_reviewed_cash_expense(outflow.row_id, "expense:food", reason="Reviewed coffee purchase")
        assert key == f"review:expense:{outflow.row_id}"
        assert (
            store.post_reviewed_cash_expense(outflow.row_id, "expense:food", reason="Reviewed coffee purchase") == key
        )
        with pytest.raises(ProfileFormatError, match="expense_review_conflicts_with_prior_entry"):
            store.post_reviewed_cash_expense(outflow.row_id, "expense:food", reason="Different review")
        with pytest.raises(ProfileFormatError, match="cash_expense_requires_bound_posted_outflow"):
            store.post_reviewed_cash_expense(inflow.row_id, "expense:food", reason="Not an expense")
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.load_import(evidence.source_sha256).evidence == evidence
        rows = store.connection.execute("SELECT key,payload FROM JournalEntries").fetchall()
        assert len(rows) == 1 and rows[0][0] == key
        posted = json.loads(rows[0][1])
        assert [(item["account_id"], item["amount_minor"]) for item in posted["postings"]] == [
            ("cash", -400),
            ("expense:food", 400),
        ]
        assert store.connection.execute("SELECT row_id,amount_minor FROM JournalAllocations").fetchall() == [
            (outflow.row_id, -400)
        ]
        assert store.connection.execute(
            "SELECT count(*) FROM JournalAllocations WHERE row_id=?", (inflow.row_id,)
        ).fetchone() == (0,)
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            store.post_reviewed_cash_expense(outflow.row_id, "expense:food", reason="Reviewed coffee purchase")


def test_cash_expense_requires_explicit_mapping_and_expense_category(tmp_path: Path) -> None:
    profile = tmp_path / "fresh.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    row_id = evidence.payload.rows[0].row_id
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "synthetic"))
        store.add_category_account("income:other", "Other income", "income")
        with pytest.raises(ProfileFormatError, match="cash_expense_requires_bound_posted_outflow"):
            store.post_reviewed_cash_expense(row_id, "income:other", reason="Missing account decision")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        with pytest.raises(ProfileFormatError, match="cash_expense_account_or_category"):
            store.post_reviewed_cash_expense(row_id, "income:other", reason="Wrong category")
        store.add_category_account("expense:food", "Food", "expense")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "card")
        with pytest.raises(ProfileFormatError, match="cash_expense_account_or_category"):
            store.post_reviewed_cash_expense(row_id, "expense:food", reason="Liability sign is different")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)

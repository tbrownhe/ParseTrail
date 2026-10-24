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
        original_payload = store.connection.execute(
            "SELECT payload FROM JournalEntries WHERE key=?", (key,)
        ).fetchone()[0]
        store.rename_category_account("expense:food", "Dining")
        assert (
            store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[0]
            == original_payload
        )
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert [(category.name, category.kind) for category in store.category_accounts()] == [("Dining", "expense")]
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


def test_cash_expense_correction_reverses_and_replaces_without_reusing_evidence(tmp_path: Path) -> None:
    profile = tmp_path / "fresh.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    row_id = evidence.payload.rows[0].row_id
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("other-cash", "Other checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
        store.add_category_account("income:other", "Other income", "income")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        original = store.post_reviewed_cash_expense(row_id, "expense:food", reason="Reviewed coffee purchase")
        old_payload = store.connection.execute(
            "SELECT payload FROM JournalEntries WHERE key=?", (original,)
        ).fetchone()[0]
        store.update_financial_account(FinancialAccount("cash", "Main checking", "asset", "new-bank", "12345678"))
        assert store.financial_accounts()[0].name == "Main checking"
        assert (
            store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (original,)).fetchone()[0]
            == old_payload
        )
        with pytest.raises(ProfileFormatError, match="financial_account_kind_immutable"):
            store.update_financial_account(FinancialAccount("cash", "Main checking", "liability", "new-bank"))
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        with pytest.raises(ProfileFormatError, match="account_binding_has_journal_history"):
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "other-cash")
        with pytest.raises(ProfileFormatError, match="account_binding_has_journal_history"):
            store.clear_source_account_binding(evidence.source_sha256, "Checking A", "opaque")
        with pytest.raises(ProfileFormatError, match="expense_correction_requires_new_expense_category"):
            store.correct_reviewed_cash_expense(original, "expense:food", reason="No category change")
        with pytest.raises(ProfileFormatError, match="expense_correction_requires_new_expense_category"):
            store.correct_reviewed_cash_expense(original, "income:other", reason="Income is wrong")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)
        replacement = store.correct_reviewed_cash_expense(original, "expense:travel", reason="Correct category")
        assert store.correct_reviewed_cash_expense(original, "expense:travel", reason="Correct category") == replacement
        with pytest.raises(ProfileFormatError, match="expense_correction_conflicts_with_prior_decision"):
            store.correct_reviewed_cash_expense(original, "expense:food", reason="Different correction")
        with pytest.raises(ProfileFormatError, match="expense_review_already_corrected"):
            store.post_reviewed_cash_expense(row_id, "expense:food", reason="Reviewed coffee purchase")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (3,)
        assert store.connection.execute("SELECT count(*) FROM JournalCorrections").fetchone() == (1,)
        assert store.connection.execute("SELECT count(*) FROM JournalAllocations").fetchone() == (2,)
        assert store._active_consumed() == {row_id: -400}
        second = store.correct_reviewed_cash_expense(replacement, "expense:food", reason="Reconsidered category")
        assert second != replacement
        assert store._active_consumed() == {row_id: -400}
    with V2ProfileStore.open(profile, read_only=True) as store:
        totals: dict[str, int] = {}
        for (payload,) in store.connection.execute("SELECT payload FROM JournalEntries"):
            for posting in json.loads(payload)["postings"]:
                account_id = posting["account_id"]
                totals[account_id] = totals.get(account_id, 0) + posting["amount_minor"]
        assert totals == {"cash": -400, "expense:food": 400, "expense:travel": 0}
        assert store.connection.execute("SELECT count(*) FROM JournalCorrections").fetchone() == (2,)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (5,)
        assert store.load_import(evidence.source_sha256).evidence == evidence


@pytest.mark.parametrize("assignment", ["file", "row"])
def test_accountless_assignment_stays_fixed_after_cash_expense_post(tmp_path: Path, assignment: str) -> None:
    definition = json.loads(DEFINITION)
    definition["parser_id"] = "synthetic_accountless_cash_csv"
    definition["header"].remove("Account")
    del definition["columns"]["account"]
    definition["account_key"] = "unknown"
    definition_bytes = json.dumps(definition).encode()
    source = SOURCE.replace(b"Account,", b"").replace(b"Checking A,", b"")
    evidence = build_source_evidence(source, definition_bytes, suffix=".csv")
    row_id = evidence.payload.rows[0].row_id
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        store.import_source(source, definition_bytes, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("other-cash", "Other checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        if assignment == "file":
            store.assert_file_account(evidence.source_sha256, "cash")
        else:
            store.assign_row_account(row_id, "cash")
        store.post_reviewed_cash_expense(row_id, "expense:food", reason="Reviewed coffee purchase")
        if assignment == "file":
            store.assert_file_account(evidence.source_sha256, "cash")
            with pytest.raises(ProfileFormatError, match="account_binding_has_journal_history"):
                store.assert_file_account(evidence.source_sha256, "other-cash")
            with pytest.raises(ProfileFormatError, match="account_binding_has_journal_history"):
                store.clear_file_account_assertion(evidence.source_sha256)
        else:
            store.assign_row_account(row_id, "cash")
            with pytest.raises(ProfileFormatError, match="account_binding_has_journal_history"):
                store.assign_row_account(row_id, "other-cash")
            with pytest.raises(ProfileFormatError, match="account_binding_has_journal_history"):
                store.clear_row_account_assignments(evidence.source_sha256, (row_id,))

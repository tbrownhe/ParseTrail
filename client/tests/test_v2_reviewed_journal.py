"""A reviewed cash expense uses source evidence and one fresh 2.0 database."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_table_bank_source_output import from_anchored_bank

from devtools.parser_engine_pilot.test_table_bank_source_output import DEFINITION as BANK_DEFINITION
from devtools.parser_engine_pilot.test_table_bank_source_output import SOURCE as BANK_SOURCE
from devtools.parser_engine_pilot.test_table_bank_source_output import evidence as bank_channels

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
        key = store.post_reviewed_cash_category(outflow.row_id, "expense:food", reason="Reviewed coffee purchase")
        assert key == f"review:cash:expense:{outflow.row_id}"
        assert (
            store.post_reviewed_cash_category(outflow.row_id, "expense:food", reason="Reviewed coffee purchase") == key
        )
        with pytest.raises(ProfileFormatError, match="cash_review_conflicts_with_prior_entry"):
            store.post_reviewed_cash_category(outflow.row_id, "expense:food", reason="Different review")
        with pytest.raises(ProfileFormatError, match="cash_category_purpose_invalid"):
            store.post_reviewed_cash_category(inflow.row_id, "expense:food", reason="Not an expense")
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
            store.post_reviewed_cash_category(outflow.row_id, "expense:food", reason="Reviewed coffee purchase")


def test_cash_expense_requires_explicit_mapping_and_expense_category(tmp_path: Path) -> None:
    profile = tmp_path / "fresh.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    row_id = evidence.payload.rows[0].row_id
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "synthetic"))
        store.add_category_account("income:other", "Other income", "income")
        with pytest.raises(ProfileFormatError, match="cash_category_requires_bound_posted_movement"):
            store.post_reviewed_cash_category(row_id, "income:other", reason="Missing account decision")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        with pytest.raises(ProfileFormatError, match="cash_category_purpose_invalid"):
            store.post_reviewed_cash_category(row_id, "income:other", reason="Wrong category")
        store.add_category_account("expense:food", "Food", "expense")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "card")
        with pytest.raises(ProfileFormatError, match="cash_category_requires_asset_account"):
            store.post_reviewed_cash_category(row_id, "expense:food", reason="Liability sign is different")
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
        original = store.post_reviewed_cash_category(row_id, "expense:food", reason="Reviewed coffee purchase")
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
        with pytest.raises(ProfileFormatError, match="cash_correction_requires_new_same_kind_category"):
            store.correct_reviewed_cash_category(original, "expense:food", reason="No category change")
        with pytest.raises(ProfileFormatError, match="cash_correction_requires_new_same_kind_category"):
            store.correct_reviewed_cash_category(original, "income:other", reason="Income is wrong")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)
        replacement = store.correct_reviewed_cash_category(original, "expense:travel", reason="Correct category")
        assert (
            store.correct_reviewed_cash_category(original, "expense:travel", reason="Correct category") == replacement
        )
        with pytest.raises(ProfileFormatError, match="cash_correction_conflicts_with_prior_decision"):
            store.correct_reviewed_cash_category(original, "expense:food", reason="Different correction")
        with pytest.raises(ProfileFormatError, match="cash_review_already_corrected"):
            store.post_reviewed_cash_category(row_id, "expense:food", reason="Reviewed coffee purchase")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (3,)
        assert store.connection.execute("SELECT count(*) FROM JournalCorrections").fetchone() == (1,)
        assert store.connection.execute("SELECT count(*) FROM JournalAllocations").fetchone() == (2,)
        assert store._active_consumed() == {row_id: -400}
        second = store.correct_reviewed_cash_category(replacement, "expense:food", reason="Reconsidered category")
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


def test_positive_cash_requires_explicit_income_category_and_corrects_with_history(tmp_path: Path) -> None:
    profile = tmp_path / "fresh.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    expense_row, deposit = evidence.payload.rows
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("income:pay", "Pay", "income")
        store.add_category_account("income:gift", "Gift", "income")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        with pytest.raises(ProfileFormatError, match="cash_category_purpose_invalid"):
            store.post_reviewed_cash_category(deposit.row_id, "expense:food", reason="Wrong sign")
        with pytest.raises(ProfileFormatError, match="cash_category_purpose_invalid"):
            store.post_reviewed_cash_category(expense_row.row_id, "income:pay", reason="Wrong sign")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        original = store.post_reviewed_cash_category(deposit.row_id, "income:pay", reason="Confirmed cash income")
        assert (
            store.post_reviewed_cash_category(deposit.row_id, "income:pay", reason="Confirmed cash income") == original
        )
        with pytest.raises(ProfileFormatError, match="cash_correction_requires_new_same_kind_category"):
            store.correct_reviewed_cash_category(original, "expense:food", reason="Wrong kind")
        replacement = store.correct_reviewed_cash_category(original, "income:gift", reason="Correct income category")
        assert replacement != original
        assert store._active_consumed() == {deposit.row_id: 1_000}
        assert store.connection.execute("SELECT count(*) FROM JournalCorrections").fetchone() == (1,)
    with V2ProfileStore.open(profile, read_only=True) as store:
        entries = [json.loads(payload) for (payload,) in store.connection.execute("SELECT payload FROM JournalEntries")]
        totals: dict[str, int] = {}
        for entry in entries:
            for posting in entry["postings"]:
                totals[posting["account_id"]] = totals.get(posting["account_id"], 0) + posting["amount_minor"]
        assert totals == {"cash": 1_000, "income:pay": 0, "income:gift": -1_000}
        assert store.cash_activity_review_rows(evidence.source_sha256)[1].status == "Posted: Gift"
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
        store.post_reviewed_cash_category(row_id, "expense:food", reason="Reviewed coffee purchase")
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


def test_bound_bank_statement_cash_rows_post_but_component_scope_stays_pending(tmp_path: Path) -> None:
    evidence = from_anchored_bank(BANK_DEFINITION, *bank_channels())
    interest, withdrawal = evidence.payload.accounts[0].rows
    profile = tmp_path / "bank.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(BANK_SOURCE, BANK_DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("cash", "Savings", "asset", "lendingclub"))
        store.add_category_account("expense:other", "Other", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
        store.add_category_account("income:interest", "Interest", "income")
        source_account = evidence.payload.accounts[0]
        assert [row.status for row in store.cash_activity_review_rows(evidence.source_sha256)] == [
            "Assign a financial account first",
            "Assign a financial account first",
        ]
        store.bind_source_account(
            evidence.source_sha256, source_account.source_identity, source_account.source_identity_form, "cash"
        )
        assert [row.status for row in store.cash_activity_review_rows(evidence.source_sha256)] == [
            "Ready for purpose review",
            "Ready for purpose review",
        ]
        expense_key = store.post_reviewed_cash_category(
            withdrawal.row_id, "expense:other", reason="Reviewed withdrawal"
        )
        store.post_reviewed_cash_category(interest.row_id, "income:interest", reason="Confirmed interest")
        store.correct_reviewed_cash_category(expense_key, "expense:travel", reason="Corrected category")
        assert [row.status for row in store.cash_activity_review_rows(evidence.source_sha256)] == [
            "Posted: Interest",
            "Posted: Travel",
        ]
        assert store._active_consumed() == {interest.row_id: 1000, withdrawal.row_id: -2000}
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.load_import(evidence.source_sha256).evidence == evidence

    component = evidence.payload.accounts[0].model_copy(update={"balance_scope": "cash_component"})
    component_payload = evidence.payload.model_copy(update={"accounts": (component,)})
    component_evidence = evidence.model_copy(update={"payload": component_payload})
    with V2ProfileStore.create(tmp_path / "component.db") as store:
        store.import_source(BANK_SOURCE, BANK_DEFINITION, component_evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("cash", "Savings", "asset", "lendingclub"))
        store.add_category_account("expense:other", "Other", "expense")
        store.bind_source_account(
            evidence.source_sha256, component.source_identity, component.source_identity_form, "cash"
        )
        assert all(
            row.status == "Outside supported asset cash statement scope"
            for row in store.cash_activity_review_rows(evidence.source_sha256)
        )
        with pytest.raises(ProfileFormatError, match="cash_category_unsupported_source_scope"):
            store.post_reviewed_cash_category(withdrawal.row_id, "expense:other", reason="Unsupported component")
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)

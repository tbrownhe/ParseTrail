"""A 2.0 spending read uses journal postings and exposes incomplete source scope."""

from __future__ import annotations

from datetime import date
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
    b"10/02/2026,Checking A,Tea,-$3.00,$993.00\n"
    b"10/03/2026,Checking A,Deposit,$10.00,$1003.00\n"
)


def test_spending_summary_nets_corrections_and_keeps_unallocated_activity_visible(tmp_path: Path) -> None:
    profile = tmp_path / "fresh.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    coffee, tea, deposit = evidence.payload.rows
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
        store.set_category_budget_rate("expense:food", date(2026, 10, 1), 1_000)
        store.set_category_budget_rate("expense:food", date(2026, 11, 1), 2_000)
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        original = store.post_reviewed_cash_category(coffee.row_id, "expense:food", reason="Reviewed coffee")
        store.post_reviewed_cash_category(tea.row_id, "expense:food", reason="Reviewed tea")
        store.correct_reviewed_cash_category(original, "expense:travel", reason="Correct category")
        store.rename_category_account("expense:travel", "Trips")
        store.update_financial_account(FinancialAccount("cash", "Updated checking", "asset", "synthetic"))
    with V2ProfileStore.open(profile, read_only=True) as store:
        report = store.spending_summary(start=date(2026, 10, 1), end=date(2026, 10, 4))
        assert [(row.category_id, row.name, row.amount_minor) for row in report.categories] == [
            ("expense:food", "Food", 300),
            ("expense:travel", "Trips", 400),
        ]
        assert report.total_minor == 700
        assert report.activity_rows_without_full_allocation == 1
        assert report.sources_with_incomplete_activity == 1
        assert report.excluded_unreviewed_expense_entries == 0
        assert deposit.row_id not in store._active_consumed()
        movement = store.financial_journal_summary(start=date(2026, 10, 1), end=date(2026, 10, 4))
        assert [
            (row.account_id, row.name, row.kind, row.nonopening_change_minor, row.opening_minor)
            for row in movement.accounts
        ] == [
            ("card", "Card", "liability", 0, None),
            ("cash", "Updated checking", "asset", -700, None),
        ]
        assert movement.activity_rows_without_full_allocation == 1
        assert movement.sources_with_incomplete_activity == 1
        october_budget = store.monthly_budget_summary(date(2026, 10, 1))
        assert [
            (row.name, row.target_minor, row.reviewed_spending_minor, row.remaining_minor)
            for row in october_budget.categories
        ] == [("Food", 1_000, 300, 700), ("Trips", None, 400, None)]
        assert october_budget.total_target_minor is None
        assert october_budget.total_reviewed_spending_minor == report.total_minor
        assert october_budget.activity_rows_without_full_allocation == 1
        november_budget = store.monthly_budget_summary(date(2026, 11, 1))
        assert november_budget.categories[0].target_minor == 2_000
        assert november_budget.categories[0].reviewed_spending_minor == 0
        assert november_budget.categories[0].remaining_minor == 2_000
        narrow = store.spending_summary(start=date(2026, 10, 3), end=date(2026, 10, 4))
        assert narrow.total_minor == 0
        assert narrow.activity_rows_without_full_allocation == 1
        narrow_movement = store.financial_journal_summary(start=date(2026, 10, 3), end=date(2026, 10, 4))
        assert all(row.nonopening_change_minor == 0 for row in narrow_movement.accounts)
        with pytest.raises(ProfileFormatError, match="report_period_invalid"):
            store.spending_summary(start=date(2026, 10, 1), end=date(2026, 10, 1))
        with pytest.raises(ProfileFormatError, match="report_period_invalid"):
            store.financial_journal_summary(start=date(2026, 10, 2), end=date(2026, 10, 1))
        with pytest.raises(ProfileFormatError, match="budget_effective_month_invalid"):
            store.monthly_budget_summary(date(2026, 10, 2))
        assert store.load_import(evidence.source_sha256).evidence == evidence

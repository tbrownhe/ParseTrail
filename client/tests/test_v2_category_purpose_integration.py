"""Explicit purposes keep negative net reports and exact source effects coherent."""

from datetime import date

from openpyxl import load_workbook
from parsetrail.core.v2_builtin_categories import BUILTIN_CATEGORIES, builtin_category
from parsetrail.core.v2_cash_movement import read_cash_movement
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_report_drilldown import read_reviewed_entry_drilldown
from parsetrail.core.v2_report_export import write_reviewed_journal_workbook
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_cash_activity_review import DEFINITION

START, END = date(2026, 10, 1), date(2026, 11, 1)
SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Purchase,-$4.00,$996.00\n"
    b"10/02/2026,Checking A,Receipt,$10.00,$1006.00\n"
    b"10/03/2026,Checking A,Receipt,$5.00,$1011.00\n"
    b"10/04/2026,Checking A,Debit,-$7.00,$1004.00\n"
    b"10/05/2026,Checking A,Unreviewed receipt,$2.00,$1006.00\n"
)


def _profile(path):
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        for account_id, name, kind in (
            ("expense:food", "Food", "expense"),
            ("expense:travel", "Travel", "expense"),
            ("income:pay", "Pay", "income"),
        ):
            store.add_category_account(account_id, name, kind)
        store.set_category_budget_rate("expense:food", START, 1000)
        store.set_category_budget_rate("expense:travel", START, 0)
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        purposes = ("expense", "expense_refund", "income", "income_adjustment")
        categories = ("expense:food", "expense:food", "income:pay", "income:pay")
        originals = [
            store.post_reviewed_cash_category(
                row.row_id, category, purpose=purpose, reason=f"Explicit reviewed {purpose}"
            )
            for row, category, purpose in zip(evidence.payload.rows[:4], categories, purposes, strict=True)
        ]
        refund = store.correct_reviewed_cash_category(
            originals[1], "expense:travel", reason="Refund relates to earlier travel"
        )
    return evidence, originals, refund


def test_refunds_and_income_adjustments_agree_across_cash_budget_history_export_and_backup(tmp_path):
    profile = tmp_path / "purposes.db"
    evidence, originals, refund = _profile(profile)
    before = profile.read_bytes()
    with V2ProfileStore.open(profile, read_only=True) as store:
        expense = store.reviewed_category_summary(kind="expense", start=START, end=END)
        income = store.reviewed_category_summary(kind="income", start=START, end=END)
        budget = store.monthly_budget_summary(START)
        movement = store.financial_journal_summary(start=START, end=END)
        position = store.account_positions(as_of=date(2026, 10, 31)).accounts[0]
        journal = store.reviewed_journal_export(start=START, end=END)
        assert expense.total_minor == -600 and income.total_minor == -200
        assert [(row.category_id, row.amount_minor) for row in expense.categories] == [
            ("expense:food", 400),
            ("expense:travel", -1000),
        ]
        assert budget.total_reviewed_spending_minor == -600
        assert sum(row.remaining_minor for row in budget.categories) == 1600
        assert movement.accounts[0].nonopening_change_minor == position.recorded_debit_minor == 400
        assert position.position_debit_minor is None and position.opening_status == "missing"
        assert journal.activity_rows_without_full_allocation == position.pending_activity_rows == 1
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert store._active_consumed() == {row.row_id: row.amount.minor for row in evidence.payload.rows[:4]}
    cash = read_cash_movement(profile, ("cash",), start=START, end=END)
    assert cash.total_minor == 400
    assert {row.classification: row.amount_minor for row in cash.rows} == {
        "expense": -400,
        "expense_refund": 1000,
        "income": 500,
        "income_adjustment": -700,
    }
    drilldown = read_reviewed_entry_drilldown(profile, "expense:travel", start=START, end=END)
    assert drilldown.total_minor == -1000 and [entry.key for entry in drilldown.entries] == [refund]
    assert originals[1] in {entry.key for entry in drilldown.related_entries(drilldown.entries[0])}
    workbook_path = write_reviewed_journal_workbook(journal, tmp_path / "purposes.xlsx")
    workbook = load_workbook(workbook_path, read_only=True, data_only=False)
    try:
        rows = list(workbook["Reviewed Entries"].values)[1:]
        assert len(rows) == 4
        assert sum(int(row[7]) for row in rows) == -600
        assert sum(int(row[9]) for row in rows) == -200
        assert sum(int(row[5]) for row in list(workbook["Source Allocations"].values)[1:]) == 400
    finally:
        workbook.close()
    assert profile.read_bytes() == before
    backup = V2ProfileStore.snapshot_to(profile, tmp_path / "backup.db")
    assert read_cash_movement(backup, ("cash",), start=START, end=END) == cash


def test_builtin_discovery_and_reports_preserve_empty_profile_until_explicit_addition(tmp_path):
    profile = tmp_path / "builtin.db"
    with V2ProfileStore.create(profile):
        pass
    before = profile.read_bytes()
    loan_interest = builtin_category("builtin:loan-interest")
    assert loan_interest in BUILTIN_CATEGORIES and builtin_category("builtin:future") is None
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.category_accounts() == ()
        assert store.reviewed_category_summary(kind="expense", start=START, end=END).categories == ()
    assert profile.read_bytes() == before
    with V2ProfileStore.open(profile) as store:
        store.ensure_builtin_category(loan_interest.account_id)
        store.add_category_account("expense:custom-interest", loan_interest.name, "expense")
        accounts = store.category_accounts()
        assert {account.id for account in accounts} == {"builtin:loan-interest", "expense:custom-interest"}
        assert len(accounts) == 2 and {account.name for account in accounts} == {"Loan interest"}
    backup = V2ProfileStore.snapshot_to(profile, tmp_path / "builtin-backup.db")
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.category_accounts() == accounts


def test_first_builtin_post_uses_the_selected_source_basis_before_atomic_materialization(tmp_path):
    profile = tmp_path / "first-builtin-post.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        selected = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        assert store.category_accounts() == ()
        key = store.post_reviewed_cash_category(
            evidence.payload.rows[0].row_id,
            "builtin:loan-interest",
            purpose="expense",
            reason="Explicitly reviewed ordinary interest expense",
            expected_basis_sha256=selected.basis_sha256,
        )
        assert [category.id for category in store.category_accounts()] == ["builtin:loan-interest"]
        assert [entry.key for entry in store.reviewed_journal_export(start=START, end=END).entries] == [key]


def test_report_dialogs_keep_negative_net_spending_and_income_visible(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_cash_movement import V2CashMovementDialog
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate, Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "display.db"
    _profile(profile)
    before = profile.read_bytes()
    reports = V2ReviewedReportsDialog(profile)
    cash = V2CashMovementDialog(profile)
    try:
        reports.start.setDate(QDate(2026, 10, 1))
        reports.end.setDate(QDate(2026, 11, 1))
        reports.budget_month.setDate(QDate(2026, 10, 1))
        assert reports.spending_report.total_minor == -600
        assert reports.income_report.total_minor == -200
        assert reports.model.data(reports.model.index(1, 1)) == "-$10.00"
        assert reports.income_model.data(reports.income_model.index(0, 1)) == "-$2.00"
        assert sum(row.remaining_minor for row in reports.budget_model.rows) == 1600
        cash.start.setDate(QDate(2026, 10, 1))
        cash.end.setDate(QDate(2026, 11, 1))
        assert cash.report is None
        cash.accounts.item(0).setCheckState(Qt.Checked)
        assert cash.report.total_minor == 400
        assert cash.summary.rowCount() == 4
        purposes = {cash.summary.item(index, 0).text() for index in range(4)}
        assert "Reviewed cash expense refund" in purposes
        assert "Reviewed cash income adjustment" in purposes
        assert "1 activity row(s)" in cash.scope.text()
    finally:
        reports.close()
        cash.close()
        app.processEvents()
    assert profile.read_bytes() == before


def test_card_correction_can_atomically_select_unmaterialized_builtin(tmp_path):
    from parsetrail.core.v2_preferences import V2Preferences

    profile = tmp_path / "card-builtin-correction.db"
    evidence = _chase_profile(profile)
    account = evidence.payload.accounts[0]
    with V2ProfileStore.open(profile) as store:
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        original = store.post_reviewed_card_purchase(
            account.rows[0].row_id,
            "expense:food",
            reason="Reviewed ordinary charge",
            preferences=V2Preferences(False, True),
        )
        selected = store.source_interpretation_snapshot(
            evidence.source_sha256, kind="card", preferences=V2Preferences()
        )
        corrected = store.correct_reviewed_card_purchase(
            original,
            "builtin:loan-interest",
            reason="Reviewed statement charge relates to interest",
            expected_basis_sha256=selected.basis_sha256,
        )
        journal = store.reviewed_journal_export(start=date(2026, 3, 1), end=date(2026, 4, 1))
        assert [entry.key for entry in journal.entries] == [corrected]
        assert journal.entries[0].postings[1].account_id == "builtin:loan-interest"


def test_builtin_and_custom_same_name_remain_distinct_in_reports_and_selected_drilldown(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui import v2_reviewed_reports
    from parsetrail.gui.v2_report_drilldown import V2ReviewedEntryDrilldown
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "same-name-reports.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:custom-interest", "Loan interest", "expense")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        for row, category_id, purpose in zip(
            evidence.payload.rows[:2],
            ("builtin:loan-interest", "expense:custom-interest"),
            ("expense", "expense_refund"),
            strict=True,
        ):
            store.post_reviewed_cash_category(row.row_id, category_id, purpose=purpose, reason="Explicit category")
            store.set_category_budget_rate(category_id, START, 1000)
    reports = v2_reviewed_reports.V2ReviewedReportsDialog(profile)
    inspected = []

    class CaptureDrilldown:
        def __init__(self, _profile, account_id, **kwargs):
            inspected.append((account_id, kwargs["expected_total_minor"]))

        def exec(self):
            pass

    monkeypatch.setattr(v2_reviewed_reports, "V2ReviewedEntryDrilldown", CaptureDrilldown)
    try:
        reports.start.setDate(QDate(2026, 10, 1))
        reports.end.setDate(QDate(2026, 11, 1))
        reports.budget_month.setDate(QDate(2026, 10, 1))
        expected = {
            "builtin:loan-interest": ("Loan interest [Built-in]", 400),
            "expense:custom-interest": ("Loan interest [Custom: expense:custom-interest]", -1000),
        }
        for model, tab in ((reports.model, 0), (reports.budget_model, 2)):
            labels = set()
            for index, row in enumerate(model.rows):
                label, amount = expected[row.category_id]
                assert model.data(model.index(index, 0)) == label
                labels.add(label)
                reports._inspect_report_row(tab, model.index(index, 0))
                assert inspected[-1] == (row.category_id, amount)
            assert len(labels) == 2
        for account_id, (label, amount) in expected.items():
            detail = V2ReviewedEntryDrilldown(profile, account_id, start=START, end=END)
            try:
                assert detail.scope.text().startswith(label + ":")
                assert account_id in detail.scope.toolTip()
                assert f"ID {account_id}" in detail.details.toPlainText()
                assert detail.drilldown.total_minor == amount
            finally:
                detail.close()
        cash = read_cash_movement(profile, ("cash",), start=START, end=END)
        assert {row.event_note for row in cash.rows} == {
            f"Reviewed category: {label}." for label, _amount in expected.values()
        }
    finally:
        reports.close()
        app.processEvents()

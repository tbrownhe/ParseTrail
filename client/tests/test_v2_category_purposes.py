"""Explicit source purposes retain exact effects and protected category identity."""

from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_source_overlap import review, setup, source

START, END = date(2026, 10, 1), date(2026, 11, 1)


def categories(store):
    setup(store)
    store.add_category_account("income:pay", "Pay", "income")
    store.add_category_account("income:other", "Other income", "income")


@pytest.mark.parametrize(
    ("amount", "purpose", "category", "expected"),
    [
        ("-$4.00", "expense", "expense:food", 400),
        ("$4.00", "expense_refund", "expense:food", -400),
        ("$4.00", "income", "income:pay", 400),
        ("-$4.00", "income_adjustment", "income:pay", -400),
    ],
)
def test_cash_explicit_purpose_retains_source_and_exact_effect(tmp_path, amount, purpose, category, expected):
    path = tmp_path / "cash.db"
    with V2ProfileStore.create(path) as store:
        categories(store)
        evidence = source(store, "Reviewed source purpose", amount=amount)
        row = evidence.payload.rows[0]
        before = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        assert before.rows[0].purpose is None
        assert purpose in before.rows[0].allowed_purposes
        key = store.post_reviewed_cash_category(
            row.row_id, category, purpose=purpose, reason="Explicit review", expected_basis_sha256=before.basis_sha256
        )
        assert f":{purpose}:" in key
        assert (
            store.post_reviewed_cash_category(
                row.row_id,
                category,
                purpose=purpose,
                reason="Explicit review",
                expected_basis_sha256=before.basis_sha256,
            )
            == key
        )
        current = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        assert current.rows[0].purpose == purpose and current.rows[0].allowed_purposes == (purpose,)
        assert [(p.account_id, p.amount_minor) for p in current.entries[0].postings] == [
            ("cash", row.amount.minor),
            (category, -row.amount.minor),
        ]
        assert (
            store.reviewed_category_summary(kind=category.split(":")[0], start=START, end=END).total_minor == expected
        )
        assert store._active_consumed() == {row.row_id: row.amount.minor}
        assert store.load_import(evidence.source_sha256).evidence == evidence
    backup = tmp_path / "backup.db"
    V2ProfileStore.snapshot_to(path, backup)
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.source_interpretation_snapshot(evidence.source_sha256, kind="cash").rows[0].purpose == purpose


@pytest.mark.parametrize(
    ("amount", "purpose", "category"),
    [
        ("$4.00", "expense", "expense:food"),
        ("-$4.00", "income", "income:pay"),
        ("$4.00", "income", "expense:food"),
        ("-$4.00", "income_adjustment", "expense:food"),
        ("$4.00", "transfer", "income:pay"),
    ],
)
def test_cash_refuses_incompatible_or_unknown_purpose_atomically(tmp_path, amount, purpose, category):
    with V2ProfileStore.create(tmp_path / "cash.db") as store:
        categories(store)
        evidence = source(store, "Unsupported purpose", amount=amount)
        with pytest.raises(ProfileFormatError, match="cash_category_purpose_invalid"):
            store.post_reviewed_cash_category(
                evidence.payload.rows[0].row_id, category, purpose=purpose, reason="Review"
            )
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize(
    ("index", "purpose", "category"),
    [
        (0, "expense", "expense:food"),
        (0, "income_adjustment", "income:other"),
        (1, "expense_refund", "expense:food"),
        (1, "income", "income:other"),
    ],
)
def test_card_purpose_keeps_assumed_date_gate_and_corrected_history(tmp_path, index, purpose, category):
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        row = account.rows[index]
        with pytest.raises(ProfileFormatError, match="card_purchase_assumed_date_disabled"):
            store.post_reviewed_card_purchase(
                row.row_id, category, purpose=purpose, reason="Review", preferences=V2Preferences()
            )
        original = store.post_reviewed_card_purchase(
            row.row_id,
            category,
            purpose=purpose,
            reason="Reviewed date",
            preferences=V2Preferences(),
            accounting_date=date(2026, 3, 18),
        )
        corrected = store.correct_reviewed_card_purchase(
            original, category, accounting_date=date(2026, 4, 2), reason="Corrected date"
        )
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="card", preferences=V2Preferences())
        assert frame.rows[index].purpose == purpose and frame.rows[index].effective_date == "2026-04-02"
        assert frame.rows[index].entry_key == corrected
        wrong_class = "income:other" if category.startswith("expense:") else "expense:food"
        with pytest.raises(ProfileFormatError, match="card_correction_requires_changed_category_or_date"):
            store.correct_reviewed_card_purchase(corrected, wrong_class, reason="Purpose changes require withdrawal")
        assert store._active_consumed() == {row.row_id: row.amount.minor}
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


def test_refund_category_correction_withdrawal_and_fresh_income_preserves_every_identity(tmp_path):
    with V2ProfileStore.create(tmp_path / "cash.db") as store:
        categories(store)
        evidence = source(store, "Credit without inferred purpose", amount="$4.00")
        row = evidence.payload.rows[0]
        original = store.post_reviewed_cash_category(
            row.row_id, "expense:food", purpose="expense_refund", reason="Reviewed refund"
        )
        corrected = store.correct_reviewed_cash_category(original, "expense:other", reason="Correct expense category")
        with pytest.raises(ProfileFormatError, match="cash_correction_requires_new_same_kind_category"):
            store.correct_reviewed_cash_category(corrected, "income:pay", reason="Cannot change purpose as correction")
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        action = store.withdraw_reviewed_interpretation(
            corrected, expected_basis_sha256=frame.basis_sha256, reason="Actual income"
        )
        fresh = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        income = store.post_reviewed_cash_category(
            row.row_id,
            "income:pay",
            purpose="income",
            reason="Fresh income review",
            expected_basis_sha256=fresh.basis_sha256,
        )
        assert income not in {original, corrected, action.reversal_key}
        assert store.reviewed_category_summary(kind="expense", start=START, end=END).total_minor == 0
        assert store.reviewed_category_summary(kind="income", start=START, end=END).total_minor == 400
        assert store._active_consumed() == {row.row_id: 400}
        with pytest.raises(ProfileFormatError, match="cash_review_already_corrected"):
            store.post_reviewed_cash_category(
                row.row_id, "expense:food", purpose="expense_refund", reason="Reviewed refund"
            )


def test_refund_posted_repeat_repair_retires_one_credit_without_double_count(tmp_path):
    with V2ProfileStore.create(tmp_path / "cash.db") as store:
        categories(store)
        first = source(store, "Credit original", amount="$4.00")
        second = source(store, "Credit supporting export", amount="$4.00")
        left, right = first.payload.rows[0].row_id, second.payload.rows[0].row_id
        review(store, left, right, decision="distinct")
        store.post_reviewed_cash_category(left, "expense:food", purpose="expense_refund", reason="First credit")
        store.post_reviewed_cash_category(right, "expense:other", purpose="expense_refund", reason="Second credit")
        pair = store.source_overlap_pair(left, right)
        repair = store.repair_posted_repeat(
            left, right, expected_basis_sha256=pair.basis_sha256, reason="Same refund in two sources"
        )
        assert repair.retained_row_id == left
        assert store._active_consumed() == {left: 400}
        assert store.reviewed_category_summary(kind="expense", start=START, end=END).total_minor == -400
        assert (
            store.source_interpretation_snapshot(first.source_sha256, kind="cash").rows[0].purpose == "expense_refund"
        )


def test_builtin_post_materialization_checks_original_basis_and_rolls_back_on_any_failure(tmp_path):
    with V2ProfileStore.create(tmp_path / "cash.db") as store:
        categories(store)
        evidence = source(store, "Explicit category review")
        row = evidence.payload.rows[0]
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        assert all(c.id != "builtin:loan-interest" for c in store.category_accounts())
        with pytest.raises(ProfileFormatError, match="source_interpretation_changed_since_selection"):
            store.post_reviewed_cash_category(
                row.row_id, "builtin:loan-interest", reason="Review", purpose="expense", expected_basis_sha256="0" * 64
            )
        store.connection.execute(
            "CREATE TEMP TRIGGER fail_entry BEFORE INSERT ON JournalEntries BEGIN SELECT RAISE(ABORT,'test failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="test failure"):
            store.post_reviewed_cash_category(
                row.row_id,
                "builtin:loan-interest",
                reason="Review",
                purpose="expense",
                expected_basis_sha256=frame.basis_sha256,
            )
        assert all(c.id != "builtin:loan-interest" for c in store.category_accounts())
        assert store._active_consumed() == {}
        store.connection.execute("DROP TRIGGER fail_entry")
        key = store.post_reviewed_cash_category(
            row.row_id,
            "builtin:loan-interest",
            reason="Review",
            purpose="expense",
            expected_basis_sha256=frame.basis_sha256,
        )
        assert key and store.ensure_builtin_category("builtin:loan-interest").name == "Loan interest"
        assert len([c for c in store.category_accounts() if c.id == "builtin:loan-interest"]) == 1


def test_builtin_namespace_is_code_owned_and_custom_same_name_remains_distinct(tmp_path):
    path = tmp_path / "categories.db"
    with V2ProfileStore.create(path) as store:
        assert store.category_accounts() == ()
        with pytest.raises(ProfileFormatError, match="invalid_category_account"):
            store.add_category_account("builtin:loan-interest", "Loan interest", "expense")
        with pytest.raises(ProfileFormatError, match="invalid_category_account"):
            store.add_category_account("builtin:future", "Future", "expense")
        with pytest.raises(ProfileFormatError, match="invalid_financial_account"):
            store.add_financial_account(FinancialAccount("builtin:bank", "Bank", "asset", "synthetic"))
        with pytest.raises(ProfileFormatError, match="builtin_category_unknown"):
            store.ensure_builtin_category("builtin:future")
        fixed = store.ensure_builtin_category("builtin:loan-interest")
        with pytest.raises(ProfileFormatError, match="builtin_category_immutable"):
            store.rename_category_account(fixed.id, "New title")
        store.add_category_account("custom:interest", fixed.name, fixed.kind)
        assert len(store.category_accounts()) == 2
    original = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert len(store.category_accounts()) == 2
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            store.ensure_builtin_category("builtin:loan-interest")
    assert path.read_bytes() == original


def test_card_correction_can_atomically_materialize_explicit_builtin_category(tmp_path):
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        original = store.post_reviewed_card_purchase(
            account.rows[0].row_id, "expense:food", reason="Reviewed purchase", preferences=V2Preferences(False, True)
        )
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="card", preferences=V2Preferences())
        replacement = store.correct_reviewed_card_purchase(
            original,
            "builtin:loan-interest",
            reason="Explicit ordinary classification",
            expected_basis_sha256=frame.basis_sha256,
        )
        assert store._ordinary_category_entry(replacement)[0].postings[1].account_id == "builtin:loan-interest"
        assert store.ensure_builtin_category("builtin:loan-interest").kind == "expense"


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "Renamed"),
        ("kind", "income"),
        ("id", "builtin:unknown"),
        ("id", b"builtin:loan-interest"),
        ("id", None),
    ],
)
def test_malformed_builtin_account_refuses_common_reads_and_backup(tmp_path, field, value):
    path = tmp_path / "categories.db"
    with V2ProfileStore.create(path) as store:
        store.ensure_builtin_category("builtin:loan-interest")
    with sqlite3.connect(path) as connection:
        connection.execute(f"UPDATE Accounts SET {field}=? WHERE id='builtin:loan-interest'", (value,))
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        for read in (
            store.category_accounts,
            lambda: store.account_positions(as_of=START),
            lambda: store.reviewed_category_summary(kind="expense", start=START, end=END),
        ):
            with pytest.raises(ProfileFormatError, match="(builtin_category_integrity|account_identity_integrity)"):
                read()
    destination = tmp_path / "refused.db"
    with pytest.raises(ProfileFormatError, match="(builtin_category_integrity|account_identity_integrity)"):
        V2ProfileStore.snapshot_to(path, destination)
    assert not destination.exists() and path.read_bytes() == before


def test_historical_correction_cannot_change_category_class_even_with_balanced_payload(tmp_path):
    path = tmp_path / "cash.db"
    with V2ProfileStore.create(path) as store:
        categories(store)
        evidence = source(store, "Reviewed refund", amount="$4.00")
        row = evidence.payload.rows[0]
        original = store.post_reviewed_cash_category(
            row.row_id, "expense:food", purpose="expense_refund", reason="Refund"
        )
        corrected = store.correct_reviewed_cash_category(original, "expense:other", reason="Expense classification")
    with sqlite3.connect(path) as connection:
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_JournalEntries_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_JournalEntries_update")
        payload = json.loads(
            connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (corrected,)).fetchone()[0]
        )
        payload["postings"][1]["account_id"] = "income:pay"
        connection.execute("UPDATE JournalEntries SET payload=? WHERE key=?", (json.dumps(payload), corrected))
        connection.execute(trigger_sql)
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="ordinary_journal_integrity"):
            store.reviewed_category_summary(kind="income", start=START, end=END)
    with pytest.raises(ProfileFormatError, match="ordinary_journal_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")

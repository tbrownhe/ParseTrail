import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.ledger import (
    AccountKind,
    Allocation,
    JournalEntry,
    LedgerAccount,
    LedgerError,
    Observation,
    Posting,
)
from parsetrail.core.ledger_reconciliation import StatementEvidence
from parsetrail.core.ledger_store import LedgerStore

DAY = date(2026, 8, 31)
NEXT = date(2026, 9, 2)


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.db", create=True) as ledger:
        for account in (
            LedgerAccount("bank", "Checking", AccountKind.ASSET, source_account_id="legacy-bank"),
            LedgerAccount("card", "Card", AccountKind.LIABILITY, source_account_id="legacy-card"),
            LedgerAccount("loan", "Loan", AccountKind.LIABILITY, source_account_id="legacy-loan"),
            LedgerAccount("expense", "Groceries", AccountKind.EXPENSE),
            LedgerAccount("interest", "Interest", AccountKind.EXPENSE),
            LedgerAccount("income", "Salary", AccountKind.INCOME),
            LedgerAccount("clearing", "In transit", AccountKind.ASSET, purpose="clearing"),
            LedgerAccount("opening", "Opening equity", AccountKind.EQUITY, purpose="opening_equity"),
            LedgerAccount("suspense", "Unresolved", AccountKind.ASSET, purpose="suspense"),
        ):
            ledger.add_account(account)
        yield ledger


def observe(store, key, account, amount, day=DAY):
    store.add_observation(Observation(key, account, amount, day))
    return Posting(account, amount, (Allocation(key, amount),))


def purchase(store, key="purchase", amount=10000):
    return JournalEntry(
        key,
        "purchase-event",
        DAY,
        "Synthetic groceries",
        (observe(store, "swipe", "card", -amount), Posting("expense", amount)),
    )


def test_card_purchase_and_repayment_count_expense_once(store):
    store.post(purchase(store))
    payment = JournalEntry(
        "repayment",
        "payment-event",
        DAY,
        "Card payment",
        (observe(store, "debit", "bank", -10000), observe(store, "credit", "card", 10000)),
    )
    store.post(payment)
    balances = store.balances(DAY)
    assert (balances["expense"], balances["card"], balances["bank"]) == (10000, 0, -10000)
    assert set(store.evidence_remaining().values()) == {0}
    assert store.entry_status("repayment") == {
        "posted": True,
        "reviewed": False,
        "superseded": False,
        "statement_reconciled": None,
    }


def test_different_posting_dates_use_two_entries_and_preserve_in_transit_balance(store):
    first = JournalEntry(
        "sent", "transfer", DAY, "Transfer sent", (observe(store, "debit", "bank", -10000), Posting("clearing", 10000))
    )
    second = JournalEntry(
        "received",
        "transfer",
        NEXT,
        "Transfer received",
        (Posting("clearing", -10000), observe(store, "credit", "card", 10000, NEXT)),
    )
    store.post(first)
    store.post(second)
    assert store.balances(DAY)["clearing"] == 10000
    assert store.balances(DAY)["card"] == 0
    assert store.balances(NEXT)["clearing"] == 0
    assert store.balances(NEXT)["expense"] == 0


def test_loan_payment_split_preserves_principal_and_interest(store):
    entry = JournalEntry(
        "payment",
        "loan-event",
        DAY,
        "Loan payment",
        (
            observe(store, "bank-payment", "bank", -50000),
            observe(store, "loan-principal", "loan", 40000),
            Posting("interest", 10000),
        ),
    )
    store.post(entry)
    assert store.balances(DAY)["loan"] == 40000
    assert store.balances(DAY)["interest"] == 10000


def test_partial_evidence_is_explicit_and_cannot_be_reused(store):
    store.add_observation(Observation("debit", "bank", -10000, DAY))

    def part(key, amount):
        return JournalEntry(
            key,
            "split",
            DAY,
            "Split purchase",
            (Posting("bank", -amount, (Allocation("debit", -amount),)), Posting("expense", amount)),
        )

    store.post(part("part1", 6000))
    assert store.evidence_remaining()["debit"] == -4000
    with pytest.raises(LedgerError, match="more than once"):
        store.post(part("too-much", 4001))
    store.post(part("part2", 4000))
    assert store.evidence_remaining()["debit"] == 0


@pytest.mark.parametrize("amount", [0, True, 1.0, 2**63])
def test_invalid_money_never_posts(store, amount):
    entry = JournalEntry(
        "bad",
        "bad",
        DAY,
        "Invalid money",
        (Posting("expense", amount), Posting("income", -amount)),
        origin="manual",
        reviewed=True,
        reason="Synthetic",
    )
    with pytest.raises(LedgerError, match="minor units"):
        store.post(entry)
    assert store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0] == 0


def test_imbalance_rejects_without_consuming_evidence(store):
    entry = purchase(store)
    bad = replace(entry, postings=(entry.postings[0], Posting("expense", 9999)))
    with pytest.raises(LedgerError, match="balance exactly"):
        store.post(bad)
    assert store.evidence_remaining()["swipe"] == -10000
    assert store.balances(DAY)["card"] == 0


@pytest.mark.parametrize("change", ["account", "date", "sign", "allocation", "missing"])
def test_evidence_ownership_date_sign_and_allocation_are_enforced(store, change):
    entry = purchase(store)
    p = entry.postings[0]
    if change == "account":
        p = replace(p, account_id="bank")
    elif change == "date":
        entry = replace(entry, posting_date=NEXT)
    elif change == "sign":
        p = replace(p, allocations=(Allocation("swipe", 10000),))
    elif change == "allocation":
        p = replace(p, allocations=(Allocation("swipe", -9999),))
    else:
        p = replace(p, allocations=())
    with pytest.raises(LedgerError):
        store.post(replace(entry, postings=(p, entry.postings[1])))


def test_duplicate_processing_is_idempotent_but_changed_key_contents_fail(store):
    entry = purchase(store)
    assert store.post(entry) == store.post(entry)
    assert store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0] == 1
    with pytest.raises(LedgerError, match="Idempotency"):
        store.post(replace(entry, description="Different claim"))
    with pytest.raises(LedgerError, match="more than once"):
        store.post(replace(entry, key="different-key"))


def test_opening_debt_is_equity_not_spending_and_requires_review(store):
    entry = JournalEntry(
        "opening",
        "opening-event",
        DAY,
        "Opening card position",
        (Posting("card", -10000), Posting("opening", 10000)),
        origin="opening",
        reason="Synthetic statement anchor",
    )
    with pytest.raises(LedgerError, match="require review"):
        store.post(entry)
    store.post(replace(entry, reviewed=True))
    assert store.balances(DAY)["expense"] == 0
    assert store.balances(DAY)["card"] == -10000
    with pytest.raises(LedgerError, match="cannot create income or expenses"):
        store.post(
            replace(
                entry,
                key="bad-opening",
                reviewed=True,
                postings=(Posting("expense", -10000), Posting("opening", 10000)),
            )
        )


def test_suspense_is_balanced_but_not_reviewed_or_reconciled(store):
    entry = JournalEntry(
        "unknown",
        "unknown",
        DAY,
        "Unknown counterparty",
        (observe(store, "debit", "bank", -10000), Posting("suspense", 10000)),
    )
    store.post(entry)
    with pytest.raises(LedgerError, match="Suspense"):
        store.review(entry.key, reviewed=True, reason="Cannot guess the counterparty")
    assert not store.entry_status(entry.key)["reviewed"]


def test_correction_reverses_old_entry_and_reallocates_without_rewriting_history(store):
    original = purchase(store)
    store.post(original)
    replacement = replace(
        original, key="corrected", postings=(original.postings[0], Posting("interest", 10000)), reviewed=True
    )
    store.correct(original.key, replacement, reason="Correct interpretation")
    assert store.correct(original.key, replacement, reason="Correct interpretation") == replacement.key
    assert store.balances(DAY)["expense"] == 0
    assert store.balances(DAY)["interest"] == 10000
    assert store.balances(DAY)["card"] == -10000
    assert store.evidence_remaining()["swipe"] == 0
    assert store.entry_status(original.key)["superseded"]
    assert store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0] == 3
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.connection.execute("DELETE FROM LedgerEntries WHERE key=?", (original.key,))


def test_failed_correction_rolls_back_reversal_replacement_and_evidence_release(store, monkeypatch):
    original = purchase(store)
    store.post(original)
    insert = store._insert

    def fail_after_reversal(entry, usage):
        insert(entry, usage)
        if entry.origin == "reversal":
            raise RuntimeError("Synthetic storage failure")

    monkeypatch.setattr(store, "_insert", fail_after_reversal)
    with pytest.raises(RuntimeError, match="storage failure"):
        store.correct(original.key, replace(original, key="replacement"), reason="Synthetic correction")
    assert store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0] == 1
    assert store.evidence_remaining()["swipe"] == 0
    assert not store.entry_status(original.key)["superseded"]


def test_review_is_separate_append_only_history(store):
    entry = purchase(store)
    store.post(entry)
    store.review(entry.key, reviewed=True, reason="Confirmed expense")
    assert store.entry_status(entry.key)["reviewed"]
    assert not store.entry_status(entry.key)["statement_reconciled"]
    store.review(entry.key, reviewed=False, reason="Needs another look")
    assert not store.entry_status(entry.key)["reviewed"]
    assert store.connection.execute("SELECT count(*) FROM LedgerReviews").fetchone()[0] == 2


def test_currency_and_account_remapping_are_rejected(store):
    with pytest.raises(LedgerError, match="USD"):
        store.add_account(LedgerAccount("foreign", "Foreign", AccountKind.ASSET, currency="EUR"))
    with pytest.raises(LedgerError, match="different mapping"):
        store.add_account(LedgerAccount("bank", "Different account", AccountKind.LIABILITY))
    with pytest.raises(sqlite3.IntegrityError):
        store.add_account(
            LedgerAccount("duplicate-bank", "Duplicate", AccountKind.ASSET, source_account_id="legacy-bank")
        )


def test_existing_application_database_is_not_initialized_as_ledger(tmp_path):
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE Accounts(id INTEGER)")
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        LedgerStore(path, create=True)
    with pytest.raises(sqlite3.OperationalError):
        LedgerStore(path)
    assert path.read_bytes() == before


def test_reopened_store_rejects_second_consumption(store, tmp_path):
    entry = purchase(store)
    store.post(entry)
    with LedgerStore(tmp_path / "ledger.db") as second:
        assert second.post(entry) == entry.key
        with pytest.raises(LedgerError, match="more than once"):
            second.post(replace(entry, key="again"))


def card_statement(**changes):
    statement = StatementEvidence("statement", "card", date(2026, 8, 1), DAY, 0, -10000, ("swipe",))
    return replace(statement, **changes)


def test_overlapping_statement_memberships_reconcile_without_duplicate_postings(store):
    store.post(purchase(store))
    first = card_statement()
    second = replace(first, id="overlapping-export")
    store.add_statement(first)
    store.add_statement(second)
    assert store.reconcile(first.id)["reconciled"]
    assert store.reconcile(second.id)["reconciled"]
    assert not store.entry_status("purchase")["reviewed"]
    assert store.balances(DAY)["card"] == -10000


def test_reconciliation_reopens_after_correction_even_when_balances_match(store):
    entry = purchase(store)
    store.post(entry)
    store.add_statement(card_statement())
    assert store.reconcile("statement")["reconciled"]
    store.correct(entry.key, replace(entry, key="corrected", reviewed=True), reason="Confirm revised interpretation")
    result = store.reconciliation_status("statement")
    assert result["status"] == "stale"
    assert result["reconciled"] is False
    assert store.reconcile("statement")["reconciled"]
    assert store.reconciliation_status("statement")["status"] == "current"


@pytest.mark.parametrize("provenance", ["derived", "assumed"])
def test_derived_or_assumed_balances_are_not_independent_reconciliation(store, provenance):
    store.post(purchase(store))
    store.add_statement(card_statement(opening_provenance=provenance))
    result = store.reconcile("statement")
    assert result["exceptions"] == ["balance_evidence_not_independent"]
    assert not result["reconciled"]


def test_missing_opening_position_is_an_exception_not_an_automatic_adjustment(store):
    store.post(purchase(store))
    store.add_statement(card_statement(opening_minor=-5000, closing_minor=-15000))
    result = store.reconcile("statement")
    assert result["exceptions"] == ["opening_balance", "closing_balance"]
    assert store.balances(DAY)["card"] == -10000


def test_explicit_opening_equity_anchor_reconciles_without_current_period_expense(store):
    store.post(
        JournalEntry(
            "opening",
            "opening",
            date(2026, 7, 31),
            "Evidenced opening debt",
            (Posting("card", -5000), Posting("opening", 5000)),
            origin="opening",
            reviewed=True,
            reason="Synthetic prior closing observation",
        )
    )
    store.post(purchase(store))
    store.add_statement(card_statement(opening_minor=-5000, closing_minor=-15000))
    assert store.reconcile("statement")["reconciled"]
    assert store.balances(DAY)["expense"] == 10000


def test_unallocated_and_uncovered_activity_cannot_be_reconciled_by_netting_to_zero(store):
    purchase(store)  # Register observed purchase without posting it.
    store.add_statement(card_statement())
    assert "unallocated_evidence" in store.reconcile("statement")["exceptions"]
    store.post(purchase(store))
    for key, amount in (("manual1", 100), ("manual2", -100)):
        store.post(
            JournalEntry(
                key,
                key,
                DAY,
                "Synthetic manual activity",
                (Posting("card", amount), Posting("expense", -amount)),
                origin="manual",
                reviewed=True,
                reason="Explicit synthetic manual entry",
            )
        )
    result = store.reconcile("statement")
    assert result["exceptions"] == ["postings_outside_statement_evidence"]
    assert result["uncovered_entry_keys"] == ["manual1", "manual2"]


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "bank"},
        {"start_date": NEXT},
        {"observation_ids": ("missing",)},
        {"observation_ids": ("swipe", "swipe")},
    ],
)
def test_statement_membership_ownership_and_dates_are_enforced(store, changes):
    purchase(store)
    with pytest.raises(LedgerError):
        store.add_statement(card_statement(**changes))


def test_refund_reverses_expense_and_transfer_fee_is_explicit(store):
    store.post(purchase(store))
    store.post(
        JournalEntry(
            "refund",
            "refund",
            DAY,
            "Grocery refund",
            (observe(store, "refund", "card", 2000), Posting("expense", -2000)),
        )
    )
    store.post(
        JournalEntry(
            "fee-transfer",
            "fee-transfer",
            DAY,
            "Payment with fee",
            (
                observe(store, "bank-payment", "bank", -10500),
                observe(store, "card-payment", "card", 10000),
                Posting("interest", 500),
            ),
        )
    )
    assert store.balances(DAY)["expense"] == 8000
    assert store.balances(DAY)["interest"] == 500

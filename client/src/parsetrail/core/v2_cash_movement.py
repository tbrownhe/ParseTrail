"""Read-only movement classification over explicitly selected asset accounts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from parsetrail.core.ledger import JournalEntry
from parsetrail.core.v2_profile_store import (
    FinancialAccount,
    JournalExportAccount,
    ProfileFormatError,
    ReviewedJournalExport,
    V2ProfileStore,
)

MOVEMENT_LABELS = {
    "income": "Reviewed cash income",
    "income_adjustment": "Reviewed cash income adjustment",
    "expense": "Reviewed cash expense",
    "expense_refund": "Reviewed cash expense refund",
    "within_scope_transfer": "Owned transfer within selected scope",
    "owned_transfer": "Owned transfer across scope boundary",
    "card_payment": "Reviewed card payment",
    "unclassified": "Unclassified reviewed movement",
}


def cash_account_labels(accounts: tuple[FinancialAccount, ...]) -> dict[str, str]:
    """Distinguish permitted duplicate names without showing full account numbers."""
    scopes = {
        "account_total": "whole account",
        "principal_component": "loan principal",
        "cash_component": "cash component",
    }
    if any(type(account.tracking_scope) is not str or account.tracking_scope not in scopes for account in accounts):
        raise ProfileFormatError("financial_account_scope_invalid")
    bases = {
        account.id: (
            f"{account.name} ({account.institution_key}, {account.kind}"
            + (f", {scopes[account.tracking_scope]}" if account.tracking_scope != "account_total" else "")
            + (f", ending {account.full_account_number[-4:]}" if account.full_account_number else "")
            + ")"
        )
        for account in accounts
    }
    counts = Counter(bases.values())
    return {
        account_id: label if counts[label] == 1 else f"ID {account_id} · {label}" for account_id, label in bases.items()
    }


@dataclass(frozen=True)
class CashMovementRow:
    entry: JournalEntry
    classification: str
    amount_minor: int
    account_effects: tuple[tuple[str, int], ...]
    event_note: str


@dataclass(frozen=True)
class CashMovementBucket:
    classification: str
    amount_minor: int
    entry_count: int


@dataclass(frozen=True)
class CashMovementReport:
    journal: ReviewedJournalExport
    selected_accounts: tuple[JournalExportAccount, ...]
    rows: tuple[CashMovementRow, ...]
    buckets: tuple[CashMovementBucket, ...]
    total_minor: int
    outside_scope_entries: int
    account_labels: tuple[tuple[str, str], ...]


def read_cash_movement(
    profile: Path, selected_account_ids: tuple[str, ...], *, start: date, end: date
) -> CashMovementReport:
    """No default cash scope, inferred purpose, or source-to-money reconstruction."""
    if (
        type(selected_account_ids) is not tuple
        or not selected_account_ids
        or any(type(account) is not str or not account for account in selected_account_ids)
        or len(set(selected_account_ids)) != len(selected_account_ids)
    ):
        raise ProfileFormatError("cash_movement_scope_required")
    selected = frozenset(selected_account_ids)
    with V2ProfileStore.open(profile, read_only=True) as store:
        store.connection.execute("BEGIN")
        try:
            financial = store.financial_accounts()
            labels = cash_account_labels(financial)
            allowed = {account.id for account in financial if account.kind == "asset"}
            if not selected <= allowed:
                raise ProfileFormatError("cash_movement_scope_invalid")
            journal = store.reviewed_journal_export(start=start, end=end)
            # Full validated event context can place the counterpart leg outside
            # this period. Its money is still excluded from this period's rows.
            events = {event.event_id: event for event in store._read_transfer_history()[0] if event.status == "active"}
            accounts = {account.id: account for account in journal.accounts}
            rows = []
            for entry in journal.entries:
                effects = tuple((p.account_id, p.amount_minor) for p in entry.postings if p.account_id in selected)
                if not effects:
                    continue
                amount = sum(value for _account, value in effects)
                classification, note = "unclassified", "No admitted movement classification for this reviewed entry."
                if entry.key.startswith("review:cash:") and len(entry.postings) == 2:
                    categories = [p for p in entry.postings if accounts[p.account_id].kind in {"expense", "income"}]
                    if len(categories) == 1 and amount == -categories[0].amount_minor:
                        kind = accounts[categories[0].account_id].kind
                        classification = (
                            ("expense" if amount < 0 else "expense_refund")
                            if kind == "expense"
                            else ("income" if amount > 0 else "income_adjustment")
                        )
                        note = f"Reviewed category: {accounts[categories[0].account_id].name}."
                elif entry.event_id in events:
                    pair = events[entry.event_id].pair
                    if pair.kind == "card payment":
                        classification = "card_payment"
                    else:
                        classification = (
                            "within_scope_transfer"
                            if {pair.outgoing.account_id, pair.incoming.account_id} <= selected
                            else "owned_transfer"
                        )
                    note = (
                        f"{labels[pair.outgoing.account_id]} ({pair.outgoing.posting_date}) to "
                        f"{labels[pair.incoming.account_id]} ({pair.incoming.posting_date}). "
                        + (
                            "Different posting dates retain transfer clearing; this is no second expense."
                            if pair.outgoing.posting_date != pair.incoming.posting_date
                            else "One reviewed event; this is no second expense."
                        )
                    )
                rows.append(CashMovementRow(entry, classification, amount, effects, note))
            buckets = tuple(
                CashMovementBucket(
                    classification,
                    sum(row.amount_minor for row in rows if row.classification == classification),
                    sum(row.classification == classification for row in rows),
                )
                for classification in MOVEMENT_LABELS
                if any(row.classification == classification for row in rows)
            )
            return CashMovementReport(
                journal,
                tuple(account for account in journal.accounts if account.id in selected),
                tuple(rows),
                buckets,
                sum(row.amount_minor for row in rows),
                len(journal.entries) - len(rows),
                tuple(sorted(labels.items())),
            )
        finally:
            store.connection.execute("ROLLBACK")

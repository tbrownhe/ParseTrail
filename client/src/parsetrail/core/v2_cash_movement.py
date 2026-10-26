"""Read-only movement classification over explicitly selected asset accounts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from parsetrail.core.ledger import JournalEntry
from parsetrail.core.v2_builtin_categories import category_labels
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
    "loan_payment": "Reviewed loan payment",
    "loan_principal": "Reviewed loan principal payment",
    "unsettled_transfer": "Owned transfer with unresolved clearing",
    "mixed_settlement": "Owned settlement with reviewed fee",
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
class CashMovementComponent:
    classification: str
    amount_minor: int


@dataclass(frozen=True)
class CashMovementRow:
    entry: JournalEntry
    classification: str
    amount_minor: int
    account_effects: tuple[tuple[str, int], ...]
    event_note: str
    components: tuple[CashMovementComponent, ...] = ()


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
    expected_receipts_without_source: int = 0


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
            loans = {event.event_id: event for event in store.loan_history() if event.status == "active"}
            accounts = {account.id: account for account in journal.accounts}
            category_names = category_labels((account.id, account.name, account.kind) for account in journal.accounts)
            rows = []
            for entry in journal.entries:
                effects = tuple((p.account_id, p.amount_minor) for p in entry.postings if p.account_id in selected)
                if not effects:
                    continue
                amount = sum(value for _account, value in effects)
                classification, note = "unclassified", "No admitted movement classification for this reviewed entry."
                components = ()
                if entry.key.startswith("review:cash:") and len(entry.postings) == 2:
                    categories = [p for p in entry.postings if accounts[p.account_id].kind in {"expense", "income"}]
                    if len(categories) == 1 and amount == -categories[0].amount_minor:
                        kind = accounts[categories[0].account_id].kind
                        classification = (
                            ("expense" if amount < 0 else "expense_refund")
                            if kind == "expense"
                            else ("income" if amount > 0 else "income_adjustment")
                        )
                        note = f"Reviewed category: {category_names[categories[0].account_id]}."
                elif entry.event_id in loans:
                    event = loans[entry.event_id]
                    payment = event.manifest
                    if entry.key != event.entry_keys[0] or amount != payment.bank.amount_minor:
                        raise ProfileFormatError("cash_loan_payment_integrity")
                    classification = "loan_payment"
                    components = tuple(
                        CashMovementComponent(purpose, -value)
                        for purpose, value in (
                            ("loan_principal", payment.principal_minor),
                            ("expense", payment.interest_minor),
                        )
                        if value
                    )
                    lender = payment.components[0]
                    note = (
                        f"Reviewed loan payment from {labels[payment.bank.account_id]} on {payment.bank.posting_date} "
                        f"to {lender.account_name} (ID {lender.account_id}, principal component). "
                        f"Principal {payment.principal_minor} and interest {payment.interest_minor} USD minor units. "
                        "This is a cash-purpose split of the actual bank outflow; it adds no expense posting. "
                        "Interest expense is recorded at the lender's separately reviewed assumed accounting date(s): "
                        + ", ".join(sorted({part.effective_date for part in payment.components}))
                        + ". Original lender activity dates and printed components remain source evidence. "
                        "Dates outside this period add context only; different dates retain transfer clearing."
                    )
                elif entry.event_id in events:
                    event = events[entry.event_id]
                    pair = event.pair
                    if pair is None:
                        settlement = event.settlement
                        if settlement.residual_minor:
                            purpose = "unsettled_transfer"
                        elif all(movement.account_kind == "liability" for movement in settlement.incoming):
                            purpose = "card_payment"
                        elif {movement.account_id for movement in settlement.movements} <= selected:
                            purpose = "within_scope_transfer"
                        else:
                            purpose = "owned_transfer"
                        selected_rows = {
                            allocation.observation_id
                            for posting in entry.postings
                            if posting.account_id in selected
                            for allocation in posting.allocations
                        }
                        fee_effect = -sum(
                            fee.amount_minor for fee in settlement.fees if fee.source_row_id in selected_rows
                        )
                        # A net receipt can represent gross transfer less an
                        # explicitly reviewed fee. Its two components still sum
                        # to the exact selected financial posting. A fee on a
                        # non-selected/card leg creates no synthetic cash row.
                        components = (CashMovementComponent(purpose, amount - fee_effect),) + (
                            (CashMovementComponent("expense", fee_effect),) if fee_effect else ()
                        )
                        classification = "mixed_settlement" if fee_effect else purpose
                        note = (
                            f"Reviewed settlement sent from {labels[settlement.outgoing.account_id]} "
                            f"on {settlement.outgoing.posting_date}; "
                            + (
                                "receipts: "
                                + "; ".join(
                                    f"{labels[movement.account_id]} on {movement.posting_date}"
                                    for movement in settlement.incoming
                                )
                                if settlement.incoming
                                else "no receipt evidence is recorded"
                            )
                            + f". Remaining clearing after all reviewed receipts (any date): {settlement.residual_minor} USD minor units. "
                            "Event context can lie outside this period and adds no money here."
                        )
                        if settlement.fees:
                            note += " Reviewed fee allocations: " + "; ".join(
                                f"{fee.amount_minor} USD minor units to {category_names[fee.category_id]} "
                                f"on source row {fee.source_row_id}; {fee.reference}; {fee.reason}"
                                for fee in settlement.fees
                            )
                        if settlement.expected_destination is not None:
                            expected = settlement.expected_destination
                            note += (
                                f" Expected owned destination: {labels[expected.account_id]} (ID {expected.account_id}). "
                                f"Ownership review reference: {expected.reference}. This is an authored expectation; "
                                "no destination receipt or positive financial posting has been created."
                            )
                    elif pair.kind == "card payment":
                        classification = "card_payment"
                    else:
                        classification = (
                            "within_scope_transfer"
                            if {pair.outgoing.account_id, pair.incoming.account_id} <= selected
                            else "owned_transfer"
                        )
                    if pair is not None:
                        note = (
                            f"{labels[pair.outgoing.account_id]} ({pair.outgoing.posting_date}) to "
                            f"{labels[pair.incoming.account_id]} ({pair.incoming.posting_date}). "
                            + (
                                "Different posting dates retain transfer clearing; this is no second expense."
                                if pair.outgoing.posting_date != pair.incoming.posting_date
                                else "One reviewed event; this is no second expense."
                            )
                        )
                components = components or (CashMovementComponent(classification, amount),)
                if sum(component.amount_minor for component in components) != amount:
                    raise ProfileFormatError("cash_movement_component_integrity")
                rows.append(CashMovementRow(entry, classification, amount, effects, note, components))
            buckets = tuple(
                CashMovementBucket(
                    classification,
                    sum(
                        component.amount_minor
                        for row in rows
                        for component in row.components
                        if component.classification == classification
                    ),
                    sum(
                        any(component.classification == classification for component in row.components) for row in rows
                    ),
                )
                for classification in MOVEMENT_LABELS
                if any(component.classification == classification for row in rows for component in row.components)
            )
            return CashMovementReport(
                journal,
                tuple(account for account in journal.accounts if account.id in selected),
                tuple(rows),
                buckets,
                sum(row.amount_minor for row in rows),
                len(journal.entries) - len(rows),
                tuple(sorted(labels.items())),
                sum(
                    event.settlement.expected_destination is not None
                    and (
                        event.settlement.outgoing.account_id in selected
                        or event.settlement.expected_destination.account_id in selected
                    )
                    for event in events.values()
                ),
            )
        finally:
            store.connection.execute("ROLLBACK")

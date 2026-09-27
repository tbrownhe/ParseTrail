"""Exact double-entry rules, independent of legacy categories and the GUI.

Positive postings are debits, negative postings credits. This module does not
infer account ownership, transfer matches, opening anchors, or source corrections.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum


class LedgerError(ValueError):
    """A proposed entry cannot be posted without breaking the accounting contract."""


class AccountKind(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"


def identifier(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LedgerError("An explicit nonempty identity/reason is required.")


def minor_units(value: int) -> None:
    if type(value) is not int or not -(2**63) < value < 2**63 or value == 0:
        raise LedgerError("Postings and allocations require nonzero signed integer minor units.")


def currency(value: str) -> None:
    if value != "USD":
        raise LedgerError("The initial ledger supports exact USD entries only.")


@dataclass(frozen=True)
class LedgerAccount:
    id: str
    name: str
    kind: AccountKind
    currency: str = "USD"
    source_account_id: str | None = None
    purpose: str = "normal"

    def validate(self) -> None:
        identifier(self.id)
        identifier(self.name)
        currency(self.currency)
        if not isinstance(self.kind, AccountKind):
            raise LedgerError("An explicit ledger account class is required.")
        if self.source_account_id is not None:
            identifier(self.source_account_id)
            if self.kind not in {AccountKind.ASSET, AccountKind.LIABILITY}:
                raise LedgerError("A financial source account must map to an asset or liability.")
        if self.purpose not in {"normal", "clearing", "opening_equity", "suspense"}:
            raise LedgerError("Unknown account purpose.")
        if self.purpose == "opening_equity" and self.kind != AccountKind.EQUITY:
            raise LedgerError("Opening equity must use an equity account.")


@dataclass(frozen=True)
class Observation:
    """One canonical financial-account movement, not one statement membership."""

    id: str
    account_id: str
    amount_minor: int
    posting_date: date
    currency: str = "USD"

    def validate(self, accounts: dict[str, LedgerAccount]) -> None:
        identifier(self.id)
        minor_units(self.amount_minor)
        currency(self.currency)
        if type(self.posting_date) is not date:
            raise LedgerError("Evidence requires a calendar posting date.")
        account = accounts.get(self.account_id)
        if account is None or account.source_account_id is None or account.currency != self.currency:
            raise LedgerError("Evidence must belong to a mapped financial account in the same currency.")


@dataclass(frozen=True)
class Allocation:
    observation_id: str
    amount_minor: int


@dataclass(frozen=True)
class Posting:
    account_id: str
    amount_minor: int
    allocations: tuple[Allocation, ...] = ()


@dataclass(frozen=True)
class JournalEntry:
    key: str
    event_id: str
    posting_date: date
    description: str
    postings: tuple[Posting, ...]
    origin: str = "imported"
    reviewed: bool = False
    reason: str = ""

    def payload(self) -> dict:
        result = asdict(self)
        result["posting_date"] = self.posting_date.isoformat()
        return result


def validate_entry(
    entry: JournalEntry,
    accounts: dict[str, LedgerAccount],
    observations: dict[str, Observation],
    consumed: dict[str, int],
) -> dict[str, int]:
    """Return evidence usage only after all posting/ownership/allocation checks pass.

    Partial allocation across entries is permitted and remains explicitly
    incomplete. A posted financial movement itself must be fully supported.
    """
    identifier(entry.key)
    identifier(entry.event_id)
    identifier(entry.description)
    if type(entry.posting_date) is not date or type(entry.reviewed) is not bool:
        raise LedgerError("Entry date and review assertion must be explicit.")
    if entry.origin not in {"imported", "manual", "opening"}:
        raise LedgerError("Unsupported entry origin; reversals use the correction operation.")
    if entry.origin in {"manual", "opening"}:
        identifier(entry.reason)
        if not entry.reviewed:
            raise LedgerError("Source-independent manual/opening entries require review.")
    if len(entry.postings) < 2:
        raise LedgerError("Posted entries need at least two nonzero postings.")
    usage: dict[str, int] = {}
    kinds = set()
    purposes = set()
    for posting in entry.postings:
        minor_units(posting.amount_minor)
        account = accounts.get(posting.account_id)
        if account is None:
            raise LedgerError("Posting account does not exist.")
        account.validate()
        kinds.add(account.kind)
        purposes.add(account.purpose)
        if account.purpose == "suspense" and entry.reviewed:
            raise LedgerError("A suspense entry must retain unresolved interpretation review.")
        allocated = 0
        for allocation in posting.allocations:
            minor_units(allocation.amount_minor)
            observation = observations.get(allocation.observation_id)
            if observation is None:
                raise LedgerError("Evidence observation does not exist.")
            observation.validate(accounts)
            if observation.account_id != posting.account_id or observation.posting_date != entry.posting_date:
                raise LedgerError("Evidence account and observed posting date must match its posting.")
            if (allocation.amount_minor > 0) != (posting.amount_minor > 0) or (allocation.amount_minor > 0) != (
                observation.amount_minor > 0
            ):
                raise LedgerError("Allocation must preserve the evidence and posting signs.")
            allocated += allocation.amount_minor
            usage[observation.id] = usage.get(observation.id, 0) + allocation.amount_minor
        if posting.allocations and allocated != posting.amount_minor:
            raise LedgerError("Allocations must exactly support the posting amount.")
        if entry.origin == "imported" and account.source_account_id is not None and allocated != posting.amount_minor:
            raise LedgerError("An imported financial posting requires complete evidence allocation.")
    if sum(posting.amount_minor for posting in entry.postings) != 0:
        raise LedgerError("Debits and credits must balance exactly.")
    if entry.origin == "imported" and not usage:
        raise LedgerError("An imported entry needs source evidence.")
    if entry.origin == "opening":
        if "opening_equity" not in purposes or not kinds.issubset(
            {AccountKind.ASSET, AccountKind.LIABILITY, AccountKind.EQUITY}
        ):
            raise LedgerError("Opening positions require opening equity and cannot create income or expenses.")
    elif "opening_equity" in purposes:
        raise LedgerError("Opening equity is reserved for explicit opening positions.")
    for observation_id, amount in usage.items():
        prior = consumed.get(observation_id, 0)
        observed = observations[observation_id].amount_minor
        if prior and (prior > 0) != (observed > 0):
            raise LedgerError("Existing evidence usage has an inconsistent sign.")
        if abs(prior + amount) > abs(observed):
            raise LedgerError("Evidence cannot be consumed more than once.")
    return usage

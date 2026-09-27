"""Explicit statement evidence and versioned reconciliation, without coverage inference."""

from dataclasses import asdict, dataclass
from datetime import date, timedelta

from parsetrail.core.ledger import JournalEntry, LedgerAccount, LedgerError, Observation, identifier


@dataclass(frozen=True)
class StatementEvidence:
    """Opening is before the inclusive start date; closing is at inclusive end.

    Callers must establish this timing and the legacy-to-ledger signs before
    registering a source. Synthetic/estimated observations stay explicitly tagged.
    """

    id: str
    account_id: str
    start_date: date
    end_date: date
    opening_minor: int
    closing_minor: int
    observation_ids: tuple[str, ...]
    opening_provenance: str = "reported"
    closing_provenance: str = "reported"

    def payload(self) -> dict:
        result = asdict(self)
        result["start_date"] = self.start_date.isoformat()
        result["end_date"] = self.end_date.isoformat()
        return result

    def validate(self, accounts: dict[str, LedgerAccount], observations: dict[str, Observation]) -> None:
        identifier(self.id)
        account = accounts.get(self.account_id)
        if account is None or account.source_account_id is None:
            raise LedgerError("Statement must belong to a mapped financial account.")
        if type(self.start_date) is not date or type(self.end_date) is not date:
            raise LedgerError("Statement boundaries must be calendar dates.")
        if not date.min < self.start_date <= self.end_date:
            raise LedgerError("Invalid statement date boundaries.")
        for amount in (self.opening_minor, self.closing_minor):
            if type(amount) is not int or not -(2**63) < amount < 2**63:
                raise LedgerError("Statement balances require exact integer minor units.")
        if any(p not in {"reported", "derived", "assumed"} for p in (self.opening_provenance, self.closing_provenance)):
            raise LedgerError("Unknown balance provenance.")
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise LedgerError("A statement cannot list the same canonical observation twice.")
        for key in self.observation_ids:
            observation = observations.get(key)
            if observation is None or observation.account_id != self.account_id:
                raise LedgerError("Statement observation has the wrong account or does not exist.")
            if not self.start_date <= observation.posting_date <= self.end_date:
                raise LedgerError("Statement observation falls outside its declared period.")


def evaluate_statement(
    statement: StatementEvidence,
    accounts: dict[str, LedgerAccount],
    observations: dict[str, Observation],
    entries: list[JournalEntry],
    superseded: set[str],
    remaining: dict[str, int],
) -> dict:
    statement.validate(accounts, observations)
    opening_cutoff = statement.start_date - timedelta(days=1)
    opening, closing = 0, 0
    uncovered = set()
    membership = set(statement.observation_ids)
    for entry in entries:
        for posting in entry.postings:
            if posting.account_id != statement.account_id:
                continue
            if entry.posting_date <= opening_cutoff:
                opening += posting.amount_minor
            if entry.posting_date <= statement.end_date:
                closing += posting.amount_minor
            if (
                statement.start_date <= entry.posting_date <= statement.end_date
                and entry.key not in superseded
                and entry.origin != "reversal"
            ):
                if not posting.allocations or any(a.observation_id not in membership for a in posting.allocations):
                    uncovered.add(entry.key)
    observation_total = sum(observations[key].amount_minor for key in membership)
    exceptions = []
    if statement.opening_provenance != "reported" or statement.closing_provenance != "reported":
        exceptions.append("balance_evidence_not_independent")
    if statement.closing_minor - statement.opening_minor != observation_total:
        exceptions.append("source_balance_equation")
    if opening != statement.opening_minor:
        exceptions.append("opening_balance")
    if closing != statement.closing_minor:
        exceptions.append("closing_balance")
    if any(remaining[key] for key in membership):
        exceptions.append("unallocated_evidence")
    if uncovered:
        exceptions.append("postings_outside_statement_evidence")
    return {
        "reconciled": not exceptions,
        "exceptions": exceptions,
        "opening_difference_minor": opening - statement.opening_minor,
        "closing_difference_minor": closing - statement.closing_minor,
        "source_difference_minor": statement.closing_minor - statement.opening_minor - observation_total,
        "uncovered_entry_keys": sorted(uncovered),
    }

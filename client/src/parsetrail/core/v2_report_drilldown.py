"""Account-scoped inspection of the common active reviewed journal query."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from parsetrail.core.ledger import JournalEntry
from parsetrail.core.v2_profile_store import (
    JournalExportAccount,
    JournalExportCorrection,
    JournalExportRetirement,
    ProfileFormatError,
    ReviewedJournalExport,
    V2ProfileStore,
    _decode_journal,
)


@dataclass(frozen=True)
class ReviewedEntryDrilldown:
    report: ReviewedJournalExport
    account: JournalExportAccount
    entries: tuple[JournalEntry, ...]
    total_minor: int
    corrections: tuple[JournalExportCorrection, ...]
    retirements: tuple[JournalExportRetirement, ...]
    related_keys: tuple[tuple[str, frozenset[str]], ...]
    audit_entries: tuple[JournalEntry, ...]

    def effect_minor(self, entry: JournalEntry) -> int:
        natural = -1 if self.account.kind in {"income", "liability"} else 1
        return natural * sum(p.amount_minor for p in entry.postings if p.account_id == self.account.id)

    def entry_history(self, entry: JournalEntry):
        related = dict(self.related_keys).get(entry.key, frozenset())
        return (
            tuple(row for row in self.corrections if row.original_key in related),
            tuple(row for row in self.retirements if row.original_key in related),
        )

    def related_entries(self, entry: JournalEntry) -> tuple[JournalEntry, ...]:
        related = dict(self.related_keys).get(entry.key, frozenset())
        return tuple(item for item in self.audit_entries if item.key != entry.key and item.key in related)


def read_reviewed_entry_drilldown(profile: Path, account_id: str, *, start: date, end: date) -> ReviewedEntryDrilldown:
    """Keep totals, posting/source references and out-of-period audit links coherent."""
    with V2ProfileStore.open(profile, read_only=True) as store:
        store.connection.execute("BEGIN")
        try:
            allowed = {account.id for account in store.financial_accounts()} | {
                account.id for account in store.category_accounts()
            }
            if account_id not in allowed:
                raise ProfileFormatError("drilldown_account_missing")
            report = store.reviewed_journal_export(start=start, end=end)
            account = next(item for item in report.accounts if item.id == account_id)
            entries = tuple(
                entry for entry in report.entries if any(p.account_id == account_id for p in entry.postings)
            )
            # Related history can predate the selected report range. It provides
            # provenance only; the money above still comes from the common query.
            by_source_row: dict[str, set[str]] = {}
            for key, row_id in store.connection.execute("SELECT entry_key,row_id FROM JournalAllocations"):
                by_source_row.setdefault(row_id, set()).add(key)
            for link in report.loan_source_links:
                by_source_row.setdefault(link.row_id, set()).add(link.entry_key)
                if link.derived_observation_id is not None:
                    by_source_row.setdefault(link.derived_observation_id, set()).add(link.entry_key)
            all_corrections = tuple(
                JournalExportCorrection(*row)
                for row in store.connection.execute(
                    "SELECT original_key,reversal_key,replacement_key,reason,created_at "
                    "FROM JournalCorrections ORDER BY created_at,original_key"
                )
            )
            all_retirements = tuple(
                JournalExportRetirement(*row)
                for row in store.connection.execute(
                    "SELECT original_key,reversal_key,reason,created_at FROM JournalRetirements "
                    "ORDER BY created_at,original_key"
                )
            )
            adjacency: dict[str, set[str]] = {}
            loan_events = {event.event_id: event for event in report.loan_events}
            for event in loan_events.values():
                keys = set(event.entry_keys)
                for row_id in event.manifest.row_ids:
                    keys.update(by_source_row.get(row_id, ()))
                for key in keys:
                    adjacency.setdefault(key, set()).update(keys)
            for action in report.loan_actions:
                if action.replacement_event_id is not None:
                    keys = set(loan_events[action.event_id].entry_keys) | set(
                        loan_events[action.replacement_event_id].entry_keys
                    )
                    for key in keys:
                        adjacency.setdefault(key, set()).update(keys)
            for row in all_corrections:
                keys = {row.original_key, row.reversal_key, row.replacement_key}
                for key in keys:
                    adjacency.setdefault(key, set()).update(keys)
            for row in all_retirements:
                adjacency.setdefault(row.original_key, set()).add(row.reversal_key)
                adjacency.setdefault(row.reversal_key, set()).add(row.original_key)
            # A posted-repeat repair can connect different source rows. Its
            # historical linkage does not turn a supporting source into money.
            for retained, redundant, reversal in store.connection.execute(
                "SELECT p.retained_entry_key,p.redundant_entry_key,r.reversal_key FROM PostedRepeatRepairs p "
                "JOIN JournalRetirements r ON r.original_key=p.redundant_entry_key"
            ):
                keys = {retained, redundant, reversal}
                for key in keys:
                    adjacency.setdefault(key, set()).update(keys)
            related_keys = []
            for entry in entries:
                keys = {entry.key}
                for posting in entry.postings:
                    for allocation in posting.allocations:
                        keys.update(by_source_row.get(allocation.observation_id, ()))
                pending = list(keys)
                while pending:
                    for neighbor in adjacency.get(pending.pop(), ()):
                        if neighbor not in keys:
                            keys.add(neighbor)
                            pending.append(neighbor)
                related_keys.append((entry.key, frozenset(keys)))
            related = set().union(*(keys for _entry_key, keys in related_keys)) if related_keys else set()
            corrections = tuple(row for row in all_corrections if row.original_key in related)
            retirements = tuple(row for row in all_retirements if row.original_key in related)
            audit_entries = tuple(
                sorted(
                    (
                        _decode_journal(payload)
                        for key, payload in store.connection.execute("SELECT key,payload FROM JournalEntries")
                        if key in related
                    ),
                    key=lambda entry: (entry.posting_date, entry.key),
                )
            )
            natural = -1 if account.kind in {"income", "liability"} else 1
            total = natural * sum(
                p.amount_minor for entry in entries for p in entry.postings if p.account_id == account_id
            )
            return ReviewedEntryDrilldown(
                report, account, entries, total, corrections, retirements, tuple(related_keys), audit_entries
            )
        finally:
            store.connection.execute("ROLLBACK")

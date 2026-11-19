"""Explicit continuing-account identity, without rewriting financial evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone

TABLE = "AccountConsolidations"
COLUMNS = (
    ("consolidation_id", "INTEGER", 0, 1),
    ("kept_account_id", "TEXT", 1, 0),
    ("absorbed_account_id", "TEXT", 1, 0),
    ("members_payload", "TEXT", 1, 0),
    ("request_basis", "TEXT", 1, 0),
    ("profile_sha256", "TEXT", 1, 0),
    ("reason", "TEXT", 1, 0),
    ("reference", "TEXT", 1, 0),
    ("record_sha256", "TEXT", 1, 0),
    ("created_at", "TEXT", 1, 0),
)
FOREIGN_KEYS = (("absorbed_account_id", "Accounts", "id"), ("kept_account_id", "Accounts", "id"))
SQL = """
CREATE TABLE AccountConsolidations (
    consolidation_id INTEGER PRIMARY KEY,
    kept_account_id TEXT NOT NULL REFERENCES Accounts(id),
    absorbed_account_id TEXT NOT NULL UNIQUE REFERENCES Accounts(id),
    members_payload TEXT NOT NULL, request_basis TEXT NOT NULL,
    profile_sha256 TEXT NOT NULL, reason TEXT NOT NULL, reference TEXT NOT NULL,
    record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
    CHECK(kept_account_id != absorbed_account_id)
);
"""


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class AccountConsolidation:
    consolidation_id: int
    kept_account_id: str
    absorbed_account_id: str
    member_account_ids: tuple[str, ...]
    basis_sha256: str
    profile_sha256: str
    reason: str
    reference: str
    record_sha256: str
    created_at: str


@dataclass(frozen=True)
class AccountConsolidationSnapshot:
    kept_account: object
    absorbed_account: object
    member_account_ids: tuple[str, ...]
    basis_sha256: str
    profile_sha256: str
    source_count: int
    source_binding_count: int
    activity_row_count: int
    journal_entry_count: int
    retained_numbers: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    retained_source_identities: tuple[tuple[str, str], ...] = ()


def history(store):
    from parsetrail.core.v2_profile_store import ProfileFormatError

    accounts = {
        row[0]: row[1:]
        for row in store.connection.execute(
            "SELECT id,kind,currency,institution_key,tracking_scope,product_type FROM Accounts WHERE role='financial'"
        )
    }
    parents, result = {}, []
    for row in store.connection.execute("SELECT * FROM AccountConsolidations ORDER BY consolidation_id"):
        identity, kept, absorbed, raw_members, basis, profile, reason, reference, checksum, created = row
        try:
            members = tuple(json.loads(raw_members))
            expected_members = tuple(
                sorted(account for account in accounts if _canonical(account, parents) in {kept, absorbed})
            )
            if (
                kept not in accounts
                or absorbed not in accounts
                or kept == absorbed
                or kept in parents
                or absorbed in parents
                or accounts[kept] != accounts[absorbed]
                or members != expected_members
                or not isinstance(reason, str)
                or not 0 < len(reason.strip()) <= 500
                or not isinstance(reference, str)
                or not 0 < len(reference.strip()) <= 500
                or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in (basis, profile))
                or checksum != _digest(row[:8] + (created,))
                or datetime.fromisoformat(created).tzinfo is None
            ):
                raise ValueError
        except (TypeError, ValueError):
            raise ProfileFormatError("account_consolidation_history_integrity") from None
        parents[absorbed] = kept
        result.append(
            AccountConsolidation(
                identity, kept, absorbed, members, basis, profile, reason, reference, checksum, created
            )
        )
    return tuple(result)


def _canonical(account_id, parents):
    while account_id in parents:
        account_id = parents[account_id]
    return account_id


def identity_map(store):
    # total_changes does not decrease on rollback. Include the actual identity
    # records so a rolled-back consolidation cannot leave a cached alias alive.
    epoch = (
        store.connection.total_changes,
        store.connection.execute("PRAGMA data_version").fetchone()[0],
        tuple(
            store.connection.execute(
                "SELECT kept_account_id,absorbed_account_id FROM AccountConsolidations ORDER BY consolidation_id"
            )
        ),
        store.connection.execute("SELECT count(*),max(rowid) FROM Accounts").fetchone(),
    )
    cached = getattr(store, "_consolidation_identity_cache", None)
    if cached is not None and cached[0] == epoch:
        return cached[1]
    parents = {item.absorbed_account_id: item.kept_account_id for item in history(store)}
    mapping = {account.id: _canonical(account.id, parents) for account in store.financial_accounts()}
    store._consolidation_identity_cache = epoch, mapping
    return mapping


def numbers(store, account_id):
    members = set(store.account_members(account_id))
    values = {account.full_account_number for account in store.financial_accounts() if account.id in members}
    values.update(
        identity
        for identity, form, bound in store.connection.execute(
            "SELECT source_identity,source_identity_form,ledger_account_id FROM SourceAccountBindings"
        )
        if bound in members and form == "full"
    )
    return tuple(sorted(value for value in values if value))


def _cancel(cancelled):
    if cancelled is not None and cancelled():
        from parsetrail.core.v2_source_import import ImportCancelled

        raise ImportCancelled()


def _basis(store):
    from parsetrail.core.v2_import_accounts import _profile_identity
    from parsetrail.core.v2_profile_store import TABLE_COLUMNS

    rows = []
    for table in sorted(TABLE_COLUMNS):
        # Source bytes are already verified by load_import, and must not be logged.
        columns = (
            "sha256,size"
            if table in {"Sources", "Definitions"}
            else ("source_sha256,definition_sha256,sha256,size" if table == "EvidenceSnapshots" else "*")
        )
        rows.append((table, sorted(store.connection.execute(f"SELECT {columns} FROM {table}").fetchall(), key=repr)))
    profile = _profile_identity(store)
    return _digest(("continuing-account-1", profile, rows)), profile


def snapshot(store, kept_account_id, absorbed_account_id, *, cancelled=None):
    from parsetrail.core.v2_profile_store import ProfileFormatError, _decode_journal
    from parsetrail.core.v2_source_overlap import NearbySourceIndex

    _cancel(cancelled)
    accounts = {account.id: account for account in store.financial_accounts()}
    if kept_account_id not in accounts or absorbed_account_id not in accounts:
        raise ProfileFormatError("financial_account_missing")
    mapping = identity_map(store)
    kept, absorbed = accounts[kept_account_id], accounts[absorbed_account_id]
    blockers, warnings = [], []
    if kept.id == absorbed.id:
        blockers.append("Choose two different bookkeeping accounts")
    if mapping[kept.id] != kept.id or mapping[absorbed.id] != absorbed.id:
        blockers.append("An account has already been absorbed; choose its continuing account")
    members = tuple(
        sorted(account_id for account_id, canonical in mapping.items() if canonical in {kept.id, absorbed.id})
    )
    member_set = set(members)
    metadata = list(
        store.connection.execute(
            "SELECT id,kind,currency,institution_key,tracking_scope,product_type FROM Accounts WHERE role='financial'"
        )
    )
    signatures = {row[1:] for row in metadata if row[0] in member_set}
    if (
        len(signatures) != 1
        or kept.institution_key is None
        or any(row[2] != "USD" for row in metadata if row[0] in member_set)
    ):
        blockers.append("Accounts must have the same known institution, currency, kind, product and tracking scope")
    if kept.tracking_scope != "account_total" or kept.product_type in {
        "tangible_asset",
        "loan",
        "mortgage",
        "vehicle_loan",
    }:
        blockers.append("Only ordinary account-total cash and card accounts are supported")
    store._validate_common_journal_read()
    store._validate_transfer_history()
    store._validate_source_interpretation_history()
    store._validate_journal_retirements()
    entries = tuple(
        _decode_journal(payload) for (payload,) in store.connection.execute("SELECT payload FROM JournalEntries")
    )
    related_entries = tuple(entry for entry in entries if any(p.account_id in member_set for p in entry.postings))
    event_accounts = {}
    inactive = store._inactive_journal_keys()
    for entry in entries:
        if entry.key in inactive:
            continue
        event_accounts.setdefault(entry.event_id, set()).update(
            p.account_id for p in entry.postings if p.account_id in member_set
        )
    if any(len(identities) > 1 for identities in event_accounts.values()):
        blockers.append("A journal moves money between these accounts; resolve that interpretation first")
    for event in store._read_transfer_history()[0]:
        if event.status == "active" and event.settlement is not None:
            settlement = event.settlement
            if settlement.expected_destination is not None and (
                settlement.outgoing.account_id in member_set
                and settlement.expected_destination.account_id in member_set
            ):
                blockers.append(
                    "A transfer expects one of these accounts as the other's destination; resolve that expectation first"
                )
    openings = tuple(store.opening_decision(account_id) for account_id in members)
    openings = tuple(item for item in openings if item is not None and item.state == "active")
    if len(openings) > 1:
        blockers.append("Both accounts have opening decisions; resolve the continuing account opening first")
    elif openings:
        opening = openings[0]
        if opening.state != "active" or opening.stale:
            blockers.append("The existing opening is withdrawn or stale; resolve it first")
        if any(
            entry.key != opening.entry_key and entry.key not in inactive and entry.posting_date <= opening.cutoff_date
            for entry in related_entries
        ):
            blockers.append("Posted activity precedes the existing opening; review the opening first")
        if any(
            store._manual_opening_history_conflict(member, opening.cutoff_date)
            for member in members
            if member != opening.account_id
        ):
            blockers.append(
                "Earlier source evidence precedes the existing opening; correct or withdraw the opening first"
            )
    else:
        warnings.append("No reviewed opening: combined journal movement will remain an unknown position")
    values = tuple(
        item for item in store._read_dated_values() if item.account_id in member_set and item.state == "active"
    )
    amounts = {}
    for item in values:
        amounts.setdefault(item.value_date, set()).add(item.amount_minor)
    if any(len(amount) > 1 for amount in amounts.values()):
        blockers.append("Reviewed dated values disagree on the same date; resolve them first")
    if any(item.account_id in member_set for item in store._read_account_lifecycle()):
        blockers.append("Accounts with lifecycle history are not yet supported for consolidation")
    for table, column, message in (
        (
            "ReconciliationDecisions",
            "account_id",
            "Accounts with saved reconciliations are not yet supported for consolidation",
        ),
        ("DerivedFinancialObservations", "account_id", "Loan component histories are not supported for consolidation"),
        ("LoanOriginationEvents", "account_id", "Loan origination histories are not supported for consolidation"),
    ):
        if any(row[0] in member_set for row in store.connection.execute(f"SELECT {column} FROM {table}")):
            blockers.append(message)
    bindings, sources, activity = 0, set(), set()
    sources.update(
        source
        for source, account in store.connection.execute(
            "SELECT source_sha256,ledger_account_id FROM SourceAccountBindings UNION SELECT source_sha256,ledger_account_id FROM FileAccountAssertions"
        )
        if account in member_set
    )
    for source_id, _saved, bound in store._iter_verified_bound_imports():
        _cancel(cancelled)
        selected = {item.row_id for item in bound if item.ledger_account_id in member_set}
        if selected:
            sources.add(source_id)
            activity.update(
                row[0]
                for row in store.connection.execute(
                    "SELECT row_id FROM SourceObservations WHERE source_sha256=? AND row_role='activity'", (source_id,)
                )
                if row[0] in selected
            )
    bindings = sum(
        row[0] in member_set for row in store.connection.execute("SELECT ledger_account_id FROM SourceAccountBindings")
    )
    rows, _index, _reviews, _aliases = store._source_overlap_index()
    proposed = [replace(row, account_id=kept.id) for row in rows.values() if row.account_id in member_set]
    index = NearbySourceIndex(proposed)
    for left, right in index.pairs():
        if mapping[rows[left].account_id] != mapping[rows[right].account_id]:
            if rows[left].active_allocated_minor and rows[right].active_allocated_minor:
                blockers.append(
                    "Possible repeated source occurrences are posted on both accounts; withdraw the redundant interpretation first"
                )
            else:
                warnings.append("Possible repeated source occurrences will require review before further posting")
            if blockers:
                break
    # Separate dated unresolved legs can otherwise become an ambiguous self-transfer.
    from parsetrail.core.v2_resolution import validate_history

    items, links = validate_history(store)
    items_by_id = {item.id: item for item in items}
    if any(
        link.status == "active"
        and items_by_id[link.outgoing_id].account_id in member_set
        and items_by_id[link.incoming_id].account_id in member_set
        for link in links
    ):
        blockers.append("A transfer resolution links these accounts; resolve that relationship first")
    basis, profile = _basis(store)
    return AccountConsolidationSnapshot(
        kept,
        absorbed,
        members,
        basis,
        profile,
        len(sources),
        bindings,
        len(activity),
        len(related_entries),
        tuple(sorted(set(numbers(store, kept.id)) | set(numbers(store, absorbed.id)))),
        tuple(dict.fromkeys(blockers)),
        tuple(warnings),
        tuple(
            sorted(
                {
                    (identity, form)
                    for identity, form, bound in store.connection.execute(
                        "SELECT source_identity,source_identity_form,ledger_account_id FROM SourceAccountBindings"
                    )
                    if bound in member_set
                }
            )
        ),
    )


def consolidate(
    store,
    kept_account_id,
    absorbed_account_id,
    *,
    expected_basis_sha256,
    expected_profile_sha256,
    reason,
    reference,
    cancelled=None,
    before_write=None,
    before_commit=None,
):
    from parsetrail.core.v2_profile_store import ProfileFormatError

    store._require_writable()
    if store.connection.in_transaction:
        raise ProfileFormatError("account_consolidation_requires_committed_snapshot")
    if any(type(value) is not str or not 0 < len(value.strip()) <= 500 for value in (reason, reference)):
        raise ProfileFormatError("account_consolidation_reason_and_reference_required")
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        _cancel(cancelled)
        from parsetrail.core.v2_import_accounts import _profile_identity

        if _profile_identity(store) != expected_profile_sha256:
            raise ProfileFormatError("account_consolidation_profile_changed")
        existing = next((item for item in history(store) if item.absorbed_account_id == absorbed_account_id), None)
        if existing is not None:
            if (existing.kept_account_id, existing.basis_sha256, existing.reason, existing.reference) != (
                kept_account_id,
                expected_basis_sha256,
                reason.strip(),
                reference.strip(),
            ):
                raise ProfileFormatError("account_consolidation_conflicts_with_prior_decision")
            store.connection.execute("COMMIT")
            return existing
        preview = snapshot(store, kept_account_id, absorbed_account_id, cancelled=cancelled)
        if preview.profile_sha256 != expected_profile_sha256:
            raise ProfileFormatError("account_consolidation_profile_changed")
        if preview.basis_sha256 != expected_basis_sha256:
            raise ProfileFormatError("account_consolidation_changed_since_selection")
        if preview.blockers:
            raise ProfileFormatError("account_consolidation_blocked: " + "; ".join(preview.blockers))
        if before_write is not None:
            before_write()
        _cancel(cancelled)
        identity = store.connection.execute(
            "SELECT coalesce(max(consolidation_id),0)+1 FROM AccountConsolidations"
        ).fetchone()[0]
        created = datetime.now(timezone.utc).isoformat()
        fields = (
            identity,
            kept_account_id,
            absorbed_account_id,
            json.dumps(preview.member_account_ids, separators=(",", ":")),
            expected_basis_sha256,
            preview.profile_sha256,
            reason.strip(),
            reference.strip(),
        )
        store.connection.execute(
            "INSERT INTO AccountConsolidations VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*fields, _digest(fields + (created,)), created),
        )
        _cancel(cancelled)
        result = history(store)[-1]
        store._validate_common_journal_read()
        store._source_overlap_index()
        if before_commit is not None:
            before_commit()
        _cancel(cancelled)
        store.connection.execute("COMMIT")
        return result
    except BaseException:
        store.connection.execute("ROLLBACK")
        store._consolidation_identity_cache = None
        raise

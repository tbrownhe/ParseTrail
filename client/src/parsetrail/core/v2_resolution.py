"""Posted source legs remain individually unresolved until an explicit link is saved."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date

from parsetrail.core.ledger import Allocation, JournalEntry, Observation, Posting, validate_entry
from parsetrail.core.v2_loan_payments import CLEARING, digest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_settlements import TransferMovement, validate_movement


@dataclass(frozen=True)
class ResolutionItem:
    id: str
    kind: str
    row_ids: tuple[str, ...]
    source_sha256: str
    account_id: str
    account_name: str
    posting_date: str
    gross_minor: int
    direction: str
    status: str
    reason: str
    version: str
    description: str = ""
    entry_keys: tuple[str, ...] = ()
    posting_allowed: bool = True
    date_provenance: str = "unknown"
    # Effective accounting dates for all evidenced legs, not rewritten raw
    # activity dates. A loan proof keeps its observed activity date separately.
    source_dates: tuple[tuple[str, str], ...] = ()
    expected_destination_account_id: str | None = None


@dataclass(frozen=True)
class ResolutionCandidate:
    outgoing_id: str
    incoming_id: str
    day_gap: int
    posting_allowed: bool
    automatic: bool = True


@dataclass(frozen=True)
class ResolutionLink:
    link_id: str
    outgoing_id: str
    incoming_id: str
    reason: str
    version: str
    status: str
    created_at: str


@dataclass(frozen=True)
class ResolutionSnapshot:
    items: tuple[ResolutionItem, ...]
    candidates: tuple[ResolutionCandidate, ...]
    links: tuple[ResolutionLink, ...]
    basis_sha256: str
    max_day_gap: int = 7


def error(code):
    from parsetrail.core.v2_profile_store import ProfileFormatError

    return ProfileFormatError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def reason_text(reason):
    if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
        raise error("resolution_reason_required")
    return reason.strip()


def now(store):
    return store.connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]


def leg_entry(movement, event_id, reason):
    validate_movement(movement)
    if not movement.date_allowed:
        raise error("resolution_date_permission_required")
    return JournalEntry(
        event_id + ":leg",
        event_id,
        date.fromisoformat(movement.posting_date),
        "Reviewed transfer — counterpart unresolved",
        (
            Posting(movement.account_id, movement.amount_minor, (Allocation(movement.row_id, movement.amount_minor),)),
            Posting(CLEARING, -movement.amount_minor),
        ),
        reviewed=True,
        reason=reason,
    )


def _inactive(store):
    from parsetrail.core.v2_profile_store import _INACTIVE_JOURNAL_SQL

    return {row[0] for row in store.connection.execute(_INACTIVE_JOURNAL_SQL)}


def transfer_legs(store):
    """Validate immutable records, journals, source reconstruction and withdrawal inverses."""
    from parsetrail.core.v2_profile_store import _decode_journal, _journal_payload

    records, actions = [], {}
    inactive = _inactive(store)
    for saved in store.connection.execute("SELECT * FROM UnresolvedTransferActions ORDER BY action_id"):
        number, event, version, reason, basis, checksum, created = saved
        if (
            type(number) is not int
            or number <= 0
            or reason != reason_text(reason)
            or checksum != digest(list(saved[:-2]) + [created])
            or event in actions
        ):
            raise error("resolution_history_integrity")
        actions[event] = saved
    seen, expected_keys = set(), set()
    context = None
    for saved in store.connection.execute("SELECT * FROM UnresolvedTransferLegs ORDER BY created_at,event_id"):
        event, row_id, source, account, payload, key, reason, basis, version, created = saved
        try:
            movement = TransferMovement(**json.loads(payload))
            validate_movement(movement)
            if context is None:
                context = store._transfer_source_validation_context()
            store._validate_transfer_movements_source((movement,), _context=context, _resolution=True)
            entry = leg_entry(movement, event, reason)
            active = event not in actions
            if (
                canonical(asdict(movement)) != payload
                or reason != reason_text(reason)
                or re.fullmatch(r"[0-9a-f]{64}", basis) is None
                or version != digest(list(saved[:-2]) + [created])
                or event != "review:unresolved:" + digest([payload, basis, reason])
                or (row_id, source, account, key)
                != (movement.row_id, movement.source_sha256, movement.account_id, entry.key)
                or store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()
                != (_journal_payload(entry),)
                or store.connection.execute(
                    "SELECT row_id,amount_minor FROM JournalAllocations WHERE entry_key=?", (key,)
                ).fetchall()
                != [(row_id, movement.amount_minor)]
                or (key in inactive) == active
            ):
                raise ValueError
            accounts = store._ledger_accounts()
            validate_entry(
                entry, accounts, {row_id: Observation(row_id, account, movement.amount_minor, entry.posting_date)}, {}
            )
            if active:
                bindings = {b.row_id: b.ledger_account_id for b in store.account_bindings(source)}
                if bindings.get(row_id) != account or row_id in seen:
                    raise ValueError
                seen.add(row_id)
            elif actions[event][2] != version or store.connection.execute(
                "SELECT reason FROM JournalRetirements WHERE original_key=?", (key,)
            ).fetchone() != (actions[event][3],):
                raise ValueError
            expected_keys.add(key)
            records.append(
                ResolutionItem(
                    event,
                    "transfer",
                    (row_id,),
                    source,
                    account,
                    movement.account_name,
                    movement.posting_date,
                    abs(movement.amount_minor),
                    "outgoing" if movement.amount_minor < 0 else "incoming",
                    "unmatched" if active else "withdrawn",
                    reason,
                    version,
                    movement.description,
                    (key,),
                    movement.date_allowed,
                    movement.date_provenance,
                    ((movement.posting_date, movement.date_provenance),),
                )
            )
        except (ValueError, TypeError, KeyError):
            raise error("resolution_history_integrity") from None
    if set(actions) - {r.id for r in records}:
        raise error("resolution_history_integrity")
    if {
        r[0]
        for r in store.connection.execute(
            "SELECT key FROM JournalEntries WHERE key LIKE 'review:unresolved:%' AND key NOT LIKE '%:retired:%'"
        )
    } - expected_keys:
        # Reversal keys are checked by the common retirement validator.
        for key, payload in store.connection.execute(
            "SELECT key,payload FROM JournalEntries WHERE key LIKE 'review:unresolved:%'"
        ):
            if key not in expected_keys and _decode_journal(payload).origin != "reversal":
                raise error("resolution_history_integrity")
    return tuple(records)


def loan_items(store):
    result = []
    for event in store._read_loan_history()[0]:
        if event.manifest.bank is not None:
            continue
        proofs = event.manifest.components
        first = proofs[0]
        dated_legs = tuple(sorted({(proof.effective_date, proof.date_provenance) for proof in proofs}))
        provenance = {qualification for _day, qualification in dated_legs}
        result.append(
            ResolutionItem(
                event.event_id,
                "loan",
                tuple(p.row_id for p in proofs),
                first.source_sha256,
                first.account_id,
                first.account_name,
                min(day for day, _qualification in dated_legs),
                sum(p.gross_minor for p in proofs),
                "incoming",
                "unmatched" if event.status == "active" else "withdrawn",
                event.reason,
                event.version,
                "Loan payment: principal and printed interest",
                event.entry_keys,
                True,
                next(iter(provenance)) if len(provenance) == 1 else "mixed",
                dated_legs,
            )
        )
    return tuple(result)


def links(store, items):
    by_id, result, used, actions = {item.id: item for item in items}, [], set(), {}
    for saved in store.connection.execute("SELECT * FROM TransferResolutionActions ORDER BY action_id"):
        number, link_id, version, reason, checksum, created = saved
        if (
            number <= 0
            or reason != reason_text(reason)
            or checksum != digest(list(saved[:-2]) + [created])
            or link_id in actions
        ):
            raise error("resolution_link_integrity")
        actions[link_id] = saved
    for saved in store.connection.execute("SELECT * FROM TransferResolutionLinks ORDER BY created_at,link_id"):
        link_id, out_id, in_id, out_version, in_version, reason, basis, version, created = saved
        outgoing, incoming = by_id.get(out_id), by_id.get(in_id)
        active = link_id not in actions
        if (
            outgoing is None
            or incoming is None
            or reason != reason_text(reason)
            or version != digest(list(saved[:-2]) + [created])
            or link_id != "resolution:" + digest([out_id, in_id, out_version, in_version, basis, reason])
            or (outgoing.version, incoming.version) != (out_version, in_version)
            or outgoing.direction != "outgoing"
            or incoming.direction != "incoming"
            or outgoing.account_id == incoming.account_id
            or outgoing.gross_minor != incoming.gross_minor
            or (
                outgoing.expected_destination_account_id is not None
                and store.canonical_account_id(outgoing.expected_destination_account_id)
                != store.canonical_account_id(incoming.account_id)
            )
            or (
                active
                and (
                    outgoing.status == "withdrawn" or incoming.status == "withdrawn" or out_id in used or in_id in used
                )
            )
            or (not active and actions[link_id][2] != version)
        ):
            raise error("resolution_link_integrity")
        if active:
            used.update((out_id, in_id))
        result.append(
            ResolutionLink(link_id, out_id, in_id, reason, version, "active" if active else "withdrawn", created)
        )
    if set(actions) - {link.link_id for link in result}:
        raise error("resolution_link_integrity")
    return tuple(result)


def origination_items(store):
    from parsetrail.core.v2_origination import history

    result = []
    for event in history(store):
        if event.mode != "funding" or event.tangible_allocation_date is not None:
            continue
        name = store.connection.execute("SELECT name FROM Accounts WHERE id=?", (event.account_id,)).fetchone()[0]
        result.append(
            ResolutionItem(
                event.event_id,
                "origination",
                (event.row_id,),
                event.source_sha256,
                event.account_id,
                name,
                event.effective_date.isoformat(),
                event.principal_minor,
                "outgoing",
                "unmatched" if event.status == "active" else "withdrawn",
                event.reason,
                event.version,
                "Loan proceeds: receipt not yet matched",
                event.entry_keys,
                True,
                event.date_provenance,
                ((event.effective_date.isoformat(), event.date_provenance),),
                event.destination_account_id,
            )
        )
    return tuple(result)


def validate_history(store):
    items = transfer_legs(store) + loan_items(store) + origination_items(store)
    return items, links(store, items)


def unmatched_items(store, *, start=None, end=None, as_of=None):
    """Current matching state beside financial postings at their accounting dates."""
    items, history = validate_history(store)
    matched = {
        identity for link in history if link.status == "active" for identity in (link.outgoing_id, link.incoming_id)
    }

    def in_period(item):
        dates = item.source_dates or ((item.posting_date, item.date_provenance),)
        return any(
            (start is None or date.fromisoformat(day) >= start)
            and (end is None or date.fromisoformat(day) < end)
            and (as_of is None or date.fromisoformat(day) <= as_of)
            for day, _provenance in dates
        )

    return tuple(item for item in items if item.status != "withdrawn" and item.id not in matched and in_period(item))


def require_unmatched(store, event_id):
    items, history = validate_history(store)
    if any(link.status == "active" and event_id in (link.outgoing_id, link.incoming_id) for link in history):
        raise error("resolution_unlink_before_correction")
    return next((item for item in items if item.id == event_id), None)


def snapshot(store, *, preferences, max_day_gap=7):
    if type(preferences) is not V2Preferences or type(max_day_gap) is not int or not 0 <= max_day_gap <= 31:
        raise error("resolution_preferences_invalid")
    items, history = validate_history(store)
    matched = {i for link in history if link.status == "active" for i in (link.outgoing_id, link.incoming_id)}
    items = tuple(replace(item, status="matched") if item.id in matched else item for item in items)
    # Raw rows are deliberate manual alternatives. They are never automatic
    # proposals unless the user has explicitly saved a transfer designation.
    from parsetrail.core.v2_pending_transfers import read_history

    pending = {r.row_id for r in read_history(store) if r.action == "pending"}
    movements = store._transfer_movements(preferences, _resolution=True)
    raw = tuple(
        ResolutionItem(
            "row:" + m.row_id,
            "source",
            (m.row_id,),
            m.source_sha256,
            m.account_id,
            m.account_name,
            m.posting_date,
            abs(m.amount_minor),
            "outgoing" if m.amount_minor < 0 else "incoming",
            "unposted",
            "",
            "",
            m.description,
            (),
            m.date_allowed,
            m.date_provenance,
            ((m.posting_date, m.date_provenance),),
        )
        for m in movements
    )
    all_items = items + raw
    candidates = []
    for outgoing in all_items:
        if outgoing.direction != "outgoing" or outgoing.status not in {"unmatched", "unposted"}:
            continue
        for incoming in all_items:
            if incoming.direction != "incoming" or incoming.status not in {"unmatched", "unposted"}:
                continue
            # A component bundle can contain several independently dated legs.
            # Every retained date must fit the selected window; row/hash order
            # cannot choose one convenient date and hide an outlying component.
            outgoing_dates = outgoing.source_dates or ((outgoing.posting_date, outgoing.date_provenance),)
            incoming_dates = incoming.source_dates or ((incoming.posting_date, incoming.date_provenance),)
            gap = max(
                abs((date.fromisoformat(left) - date.fromisoformat(right)).days)
                for left, _left_provenance in outgoing_dates
                for right, _right_provenance in incoming_dates
            )
            if (
                outgoing.kind == incoming.kind == "source"
                or store.canonical_account_id(outgoing.account_id) == store.canonical_account_id(incoming.account_id)
                or outgoing.gross_minor != incoming.gross_minor
                or (
                    outgoing.expected_destination_account_id is not None
                    and store.canonical_account_id(outgoing.expected_destination_account_id)
                    != store.canonical_account_id(incoming.account_id)
                )
                or gap > max_day_gap
            ):
                continue
            automatic = all(item.kind != "source" or item.row_ids[0] in pending for item in (outgoing, incoming))
            candidates.append(
                ResolutionCandidate(
                    outgoing.id, incoming.id, gap, outgoing.posting_allowed and incoming.posting_allowed, automatic
                )
            )
    return ResolutionSnapshot(all_items, tuple(candidates), history, store._source_overlap_basis(), max_day_gap)


def insert_leg(store, movement, *, reason, basis):
    from parsetrail.core.v2_profile_store import _journal_payload

    reason = reason_text(reason)
    payload = canonical(asdict(movement))
    event_id = "review:unresolved:" + digest([payload, basis, reason])
    store._ensure_transfer_clearing()
    entry = leg_entry(movement, event_id, reason)
    validate_entry(
        entry,
        store._ledger_accounts(),
        {movement.row_id: Observation(movement.row_id, movement.account_id, movement.amount_minor, entry.posting_date)},
        store._active_consumed(),
    )
    store.connection.execute(
        "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (entry.key, _journal_payload(entry))
    )
    store.connection.execute(
        "INSERT INTO JournalAllocations VALUES (?,?,?)", (entry.key, movement.row_id, movement.amount_minor)
    )
    created = now(store)
    values = (event_id, movement.row_id, movement.source_sha256, movement.account_id, payload, entry.key, reason, basis)
    store.connection.execute(
        "INSERT INTO UnresolvedTransferLegs VALUES (?,?,?,?,?,?,?,?,?,?)",
        (*values, digest([*values, created]), created),
    )
    return event_id


def post_leg(store, row_id, *, preferences, expected_basis_sha256, reason):
    reason = reason_text(reason)
    store._require_writable()
    if store.connection.in_transaction:
        raise error("resolution_requires_committed_snapshot")
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        for item in transfer_legs(store):
            prior = store.connection.execute(
                "SELECT request_basis FROM UnresolvedTransferLegs WHERE event_id=?", (item.id,)
            ).fetchone()[0]
            if item.row_ids == (row_id,) and prior == expected_basis_sha256 and item.reason == reason:
                if item.status == "withdrawn":
                    raise error("resolution_leg_retired")
                store.connection.execute("COMMIT")
                return item
        store._require_source_interpretation_basis(expected_basis_sha256, required=True)
        movement = next(
            (m for m in store._transfer_movements(preferences, _resolution=True) if m.row_id == row_id), None
        )
        if movement is None:
            raise error("resolution_source_unavailable")
        event_id = insert_leg(store, movement, reason=reason, basis=expected_basis_sha256)
        result = next(item for item in transfer_legs(store) if item.id == event_id)
        store.connection.execute("COMMIT")
        return result
    except BaseException:
        store.connection.execute("ROLLBACK")
        raise


def resolve(store, outgoing_id, incoming_id, *, preferences, expected_basis_sha256, reason, max_day_gap=7):
    reason = reason_text(reason)
    store._require_writable()
    if store.connection.in_transaction:
        raise error("resolution_requires_committed_snapshot")
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        current = snapshot(store, preferences=preferences, max_day_gap=max_day_gap)
        retry_ids = [outgoing_id, incoming_id]
        for index, identity in enumerate(retry_ids):
            if identity.startswith("row:"):
                saved = store.connection.execute(
                    "SELECT event_id FROM UnresolvedTransferLegs WHERE row_id=? AND request_basis=? AND reason=?",
                    (identity[4:], expected_basis_sha256, reason),
                ).fetchall()
                if len(saved) == 1:
                    retry_ids[index] = saved[0][0]
        for link in current.links:
            if (link.outgoing_id, link.incoming_id, link.reason) == (*retry_ids, reason):
                prior = store.connection.execute(
                    "SELECT request_basis FROM TransferResolutionLinks WHERE link_id=?", (link.link_id,)
                ).fetchone()[0]
                if prior == expected_basis_sha256:
                    if link.status != "active":
                        raise error("resolution_link_retired")
                    store.connection.execute("COMMIT")
                    return link
        store._require_source_interpretation_basis(expected_basis_sha256, required=True)
        candidate = next(
            (c for c in current.candidates if (c.outgoing_id, c.incoming_id) == (outgoing_id, incoming_id)), None
        )
        if candidate is None or not candidate.posting_allowed:
            raise error("resolution_candidate_unavailable")
        ids = [outgoing_id, incoming_id]
        for index, identity in enumerate(ids):
            if identity.startswith("row:"):
                row_id = identity[4:]
                movement = next(
                    (m for m in store._transfer_movements(preferences, _resolution=True) if m.row_id == row_id), None
                )
                if movement is None:
                    raise error("resolution_source_unavailable")
                ids[index] = insert_leg(store, movement, reason=reason, basis=expected_basis_sha256)
        by_id = {item.id: item for item in transfer_legs(store) + loan_items(store) + origination_items(store)}
        outgoing, incoming = (by_id[identity] for identity in ids)
        created = now(store)
        link_id = "resolution:" + digest([*ids, outgoing.version, incoming.version, expected_basis_sha256, reason])
        values = (link_id, *ids, outgoing.version, incoming.version, reason, expected_basis_sha256)
        store.connection.execute(
            "INSERT INTO TransferResolutionLinks VALUES (?,?,?,?,?,?,?,?,?)",
            (*values, digest([*values, created]), created),
        )
        result = next(link for link in links(store, tuple(by_id.values())) if link.link_id == link_id)
        store.connection.execute("COMMIT")
        return result
    except BaseException:
        store.connection.execute("ROLLBACK")
        raise


def withdraw_link(store, link_id, *, expected_version, reason):
    reason = reason_text(reason)
    store._require_writable()
    if store.connection.in_transaction:
        raise error("resolution_requires_committed_snapshot")
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        _, history = validate_history(store)
        link = next((item for item in history if item.link_id == link_id), None)
        if link is None or link.version != expected_version:
            raise error("resolution_link_changed")
        prior = store.connection.execute(
            "SELECT reason FROM TransferResolutionActions WHERE link_id=?", (link_id,)
        ).fetchone()
        if prior:
            if prior != (reason,):
                raise error("resolution_link_changed")
        else:
            number = store.connection.execute(
                "SELECT COALESCE(MAX(action_id),0)+1 FROM TransferResolutionActions"
            ).fetchone()[0]
            created = now(store)
            values = (number, link_id, expected_version, reason)
            store.connection.execute(
                "INSERT INTO TransferResolutionActions VALUES (?,?,?,?,?,?)",
                (*values, digest([*values, created]), created),
            )
        store.connection.execute("COMMIT")
    except BaseException:
        store.connection.execute("ROLLBACK")
        raise


def withdraw_leg(store, event_id, *, expected_version, reason):
    from parsetrail.core.v2_profile_store import _decode_journal

    reason = reason_text(reason)
    store._require_writable()
    if store.connection.in_transaction:
        raise error("resolution_requires_committed_snapshot")
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        item = require_unmatched(store, event_id)
        if item is None or item.kind != "transfer" or item.version != expected_version:
            raise error("resolution_leg_changed")
        prior = store.connection.execute(
            "SELECT reason FROM UnresolvedTransferActions WHERE event_id=?", (event_id,)
        ).fetchone()
        if prior:
            if prior != (reason,):
                raise error("resolution_leg_changed")
        else:
            basis = store._source_overlap_basis()
            entry = _decode_journal(
                store.connection.execute(
                    "SELECT payload FROM JournalEntries WHERE key=?", (item.entry_keys[0],)
                ).fetchone()[0]
            )
            store._retire_journal_entry(entry, reason=reason)
            number = store.connection.execute(
                "SELECT COALESCE(MAX(action_id),0)+1 FROM UnresolvedTransferActions"
            ).fetchone()[0]
            created = now(store)
            values = (number, event_id, expected_version, reason, basis)
            store.connection.execute(
                "INSERT INTO UnresolvedTransferActions VALUES (?,?,?,?,?,?,?)",
                (*values, digest([*values, created]), created),
            )
        validate_history(store)
        store.connection.execute("COMMIT")
    except BaseException:
        store.connection.execute("ROLLBACK")
        raise

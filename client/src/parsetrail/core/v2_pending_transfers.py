"""Reviewed transfer intent is an account decision, never a money posting.

An intent may wait indefinitely. Only an explicit, independently confirmed match
consumes evidence and creates journal entries through the existing transfer API.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from parsetrail.core.v2_settlements import TransferMovement, validate_movement


@dataclass(frozen=True)
class PendingTransferReview:
    revision_id: int
    row_id: str
    source_sha256: str
    account_id: str
    movement: TransferMovement
    context_sha256: str
    prior_revision_id: int | None
    action: Literal["pending", "withdrawn"]
    request_basis: str
    reason: str
    version: str
    created_at: str


@dataclass(frozen=True)
class PendingTransferState:
    review: PendingTransferReview
    status: Literal["waiting", "match_available", "stale", "blocked", "consumed", "withdrawn"]
    blockers: tuple[str, ...] = ()
    counterpart_row_ids: tuple[str, ...] = ()

    @property
    def row_id(self):
        return self.review.row_id

    @property
    def revision_id(self):
        return self.review.revision_id

    @property
    def reason(self):
        return self.review.reason

    @property
    def active(self):
        return self.status in {"waiting", "match_available"}


@dataclass(frozen=True)
class PendingTransferSnapshot:
    rows: tuple[PendingTransferState, ...]
    history: tuple[PendingTransferReview, ...]
    basis_sha256: str


@dataclass(frozen=True)
class PendingTransferDraft:
    row_id: str
    movement: TransferMovement
    context_sha256: str
    prior_revision_id: int | None
    action: Literal["pending", "withdrawn"] = "pending"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _error(code):
    from parsetrail.core.v2_profile_store import ProfileFormatError

    return ProfileFormatError(code)


def read_history(store):
    """Validate the immutable revision chain without requiring historic bindings."""
    from parsetrail.core.v2_profile_store import ProfileFormatError

    history, latest = [], {}
    source_context = None
    try:
        for saved in store.connection.execute("SELECT * FROM PendingTransferReviews ORDER BY revision_id"):
            number, row_id, source, account, payload, context, prior, action, basis, reason, version, created = saved
            movement = TransferMovement(**json.loads(payload))
            validate_movement(movement)
            if (
                type(number) is not int
                or number <= 0
                or (row_id, source, account) != (movement.row_id, movement.source_sha256, movement.account_id)
                or action not in {"pending", "withdrawn"}
                or movement.tracking_scope != "account_total"
                or not movement.date_allowed
                or type(reason) is not str
                or not 0 < len(reason.strip()) <= 500
                or reason != reason.strip()
                or any(
                    type(v) is not str or re.fullmatch(r"[0-9a-f]{64}", v) is None for v in (context, basis, version)
                )
                or prior != (latest[row_id].revision_id if row_id in latest else None)
                or (action == "withdrawn" and (row_id not in latest or latest[row_id].action != "pending"))
                or (
                    action == "withdrawn"
                    and (movement != latest[row_id].movement or context != latest[row_id].context_sha256)
                )
                or version != _digest(["pending-transfer-1", *saved[:10], created])
            ):
                raise ValueError
            date.fromisoformat(movement.posting_date)
            source_row = store.connection.execute(
                "SELECT source_sha256,amount_minor FROM SourceObservations WHERE row_id=?", (row_id,)
            ).fetchone()
            if source_row != (source, movement.amount_minor):
                raise ValueError
            if source_context is None:
                source_context = store._transfer_source_validation_context()
            # Reuse the transfer validator's immutable evidence reconstruction:
            # exact row amount, source description, date/provenance and admitted
            # account scope. Historical account labels need not equal today's
            # label, and historic assignment decisions are not rewritten.
            store._validate_transfer_movements_source((movement,), _context=source_context, _resolution=True)
            review = PendingTransferReview(
                number, row_id, source, account, movement, context, prior, action, basis, reason, version, created
            )
            latest[row_id] = review
            history.append(review)
    except (ValueError, TypeError, KeyError):
        raise _error("pending_transfer_history_integrity") from None
    except ProfileFormatError as exc:
        if str(exc) == "transfer_history_integrity":
            raise _error("pending_transfer_history_integrity") from None
        raise
    return tuple(history)


def _context(store, movement, releasing_entry_keys=()):
    """Row-local review facts survive unrelated imports, but never a rebound/repair."""
    row_id = movement.row_id
    return _digest(
        [
            asdict(movement),
            store.connection.execute(
                "SELECT kind,currency,tracking_scope FROM Accounts WHERE id=?", (movement.account_id,)
            ).fetchone(),
            [
                r
                for r in store.connection.execute(
                    "SELECT entry_key,amount_minor FROM JournalAllocations WHERE row_id=? ORDER BY entry_key", (row_id,)
                )
                if r[0] not in releasing_entry_keys
            ],
            store.connection.execute(
                "SELECT revision_id,decision,retained_row_id FROM SourceOverlapReviews "
                "WHERE left_row_id=? OR right_row_id=? ORDER BY revision_id",
                (row_id, row_id),
            ).fetchall(),
            # Corrections are source-scoped: even a later restoration of the original
            # assignment cannot silently revive a prior authored intent.
            store.connection.execute(
                "SELECT correction_id FROM BindingCorrections WHERE source_sha256=? ORDER BY correction_id",
                (movement.source_sha256,),
            ).fetchall(),
        ]
    )


def _latest(store):
    return {r.row_id: r for r in read_history(store)}


def _all_movements(store, releasing_entry_keys=()):
    from parsetrail.core.v2_preferences import V2Preferences

    # Date permission governs posting; a no-money designation itself needs none.
    return {
        m.row_id: m
        for m in store._transfer_movements(
            V2Preferences(allow_assumed_posting_dates=True), releasing_entry_keys, _resolution=True
        )
        if m.tracking_scope == "account_total"
    }


def states(store, *, source_sha256=None, include_matches=True, releasing_entry_keys=()):
    latest = _latest(store)
    if not latest:
        return ()
    movements = _all_movements(store, releasing_entry_keys)
    consumed = store._active_consumed()
    for key in releasing_entry_keys:
        for row_id, amount in store.connection.execute(
            "SELECT row_id,amount_minor FROM JournalAllocations WHERE entry_key=?", (key,)
        ):
            consumed[row_id] = consumed.get(row_id, 0) - amount
    result = []
    for review in latest.values():
        if source_sha256 is not None and review.source_sha256 != source_sha256:
            continue
        movement = movements.get(review.row_id)
        if review.action == "withdrawn":
            status, blockers = "withdrawn", ()
        elif consumed.get(review.row_id, 0):
            status, blockers = "consumed", ("pending_transfer_source_consumed",)
        elif movement is None:
            status, blockers = "blocked", ("pending_transfer_source_unavailable_or_overlap",)
        elif _context(store, movement, releasing_entry_keys) != review.context_sha256:
            status, blockers = "stale", ("pending_transfer_context_changed",)
        else:
            status, blockers = "waiting", ()
        result.append(PendingTransferState(review, status, blockers))
    if include_matches:
        from dataclasses import replace

        from parsetrail.core.v2_preferences import V2Preferences

        active_ids = {s.row_id for s in states(store, include_matches=False) if s.active}
        counterparts = {}
        for pair in store._transfer_candidates(
            preferences=V2Preferences(allow_assumed_posting_dates=True), max_day_gap=31
        ):
            a, b = pair.outgoing.row_id, pair.incoming.row_id
            if a in active_ids and b in active_ids:
                counterparts.setdefault(a, []).append(b)
                counterparts.setdefault(b, []).append(a)
        result = [
            replace(s, status="match_available", counterpart_row_ids=tuple(counterparts[s.row_id]))
            if s.active and s.row_id in counterparts
            else s
            for s in result
        ]
    return tuple(result)


def draft(store, row_id, *, expected_revision_id, reason, action="pending"):
    if type(reason) is not str or not 0 < len(reason.strip()) <= 500:
        raise _error("pending_transfer_reason_required")
    prior = _latest(store).get(row_id)
    if expected_revision_id != (prior.revision_id if prior else None):
        raise _error("pending_transfer_changed_since_selection")
    if action == "withdrawn":
        if prior is None or prior.action != "pending":
            raise _error("pending_transfer_not_pending")
        return PendingTransferDraft(row_id, prior.movement, prior.context_sha256, prior.revision_id, action)
    movement = _all_movements(store).get(row_id)
    if movement is None:
        raise _error("pending_transfer_source_unavailable_or_overlap")
    return PendingTransferDraft(row_id, movement, _context(store, movement), prior.revision_id if prior else None)


def insert_draft(store, item, *, basis, reason):
    number = store.connection.execute("SELECT coalesce(max(revision_id),0)+1 FROM PendingTransferReviews").fetchone()[0]
    created = store.connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
    values = (
        number,
        item.row_id,
        item.movement.source_sha256,
        item.movement.account_id,
        json.dumps(asdict(item.movement), sort_keys=True, separators=(",", ":")),
        item.context_sha256,
        item.prior_revision_id,
        item.action,
        basis,
        reason.strip(),
    )
    version = _digest(["pending-transfer-1", *values, created])
    store.connection.execute(
        "INSERT INTO PendingTransferReviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (*values, version, created)
    )
    return number

"""Explicit atomic confirmation of current transfer pairs with no competing matches."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import ProfileFormatError, TransferCandidate, TransferReviewSnapshot

RULE = "unique-transfer-batch-1"


class TransferBatchCancelled(ProfileFormatError):
    """No batch postings were committed before cancellation."""


@dataclass(frozen=True)
class TransferBatchPlan:
    basis_sha256: str
    profile_sha256: str
    preferences: V2Preferences
    max_day_gap: int
    pairs: tuple[TransferCandidate, ...]
    candidate_count: int
    ambiguous_pair_count: int
    date_blocked_pair_count: int
    confirmation_sha256: str

    @property
    def excluded_pair_count(self):
        return self.candidate_count - len(self.pairs)

    @property
    def total_minor(self):
        return sum(-pair.outgoing.amount_minor for pair in self.pairs)


@dataclass(frozen=True)
class TransferBatchResult:
    event_ids: tuple[str, ...]
    posted_pairs: int
    already_posted_pairs: int = 0


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def profile_identity(store):
    filename = next(
        (filename for _, name, filename in store.connection.execute("PRAGMA database_list") if name == "main"), ""
    )
    if not filename:
        raise ProfileFormatError("transfer_batch_profile_identity_unavailable")
    path = Path(filename).resolve(strict=True)
    stat = path.stat()
    return _digest([os.path.normcase(str(path)), stat.st_dev, stat.st_ino])


def _confirmation(basis, profile, preferences, gap, pairs, candidates, ambiguous, disabled):
    return _digest(
        [
            RULE,
            basis,
            profile,
            asdict(preferences),
            gap,
            [asdict(pair) for pair in pairs],
            candidates,
            ambiguous,
            disabled,
        ]
    )


def plan_unique_transfers(snapshot: TransferReviewSnapshot) -> TransferBatchPlan:
    """Count all current competing edges before filtering posting eligibility.

    A date-disabled competitor still makes a pair ambiguous. Dismissed matches
    remain governed by the current reviewed candidate graph and scope.
    """
    if not isinstance(snapshot, TransferReviewSnapshot) or snapshot.replacing_event_id is not None:
        raise ProfileFormatError("transfer_batch_requires_current_snapshot")
    degrees = Counter(row_id for pair in snapshot.candidates for row_id in (pair.outgoing.row_id, pair.incoming.row_id))
    pairs = tuple(
        pair
        for pair in snapshot.candidates
        if pair.posting_allowed and degrees[pair.outgoing.row_id] == degrees[pair.incoming.row_id] == 1
    )
    ambiguous = sum(
        degrees[pair.outgoing.row_id] > 1 or degrees[pair.incoming.row_id] > 1 for pair in snapshot.candidates
    )
    disabled = sum(
        not pair.posting_allowed and degrees[pair.outgoing.row_id] == degrees[pair.incoming.row_id] == 1
        for pair in snapshot.candidates
    )
    token = _confirmation(
        snapshot.basis_sha256,
        snapshot.profile_sha256,
        snapshot.preferences,
        snapshot.max_day_gap,
        pairs,
        len(snapshot.candidates),
        ambiguous,
        disabled,
    )
    return TransferBatchPlan(
        snapshot.basis_sha256,
        snapshot.profile_sha256,
        snapshot.preferences,
        snapshot.max_day_gap,
        pairs,
        len(snapshot.candidates),
        ambiguous,
        disabled,
        token,
    )


def validate_plan(plan):
    if (
        not isinstance(plan, TransferBatchPlan)
        or type(plan.pairs) is not tuple
        or not plan.pairs
        or any(type(pair) is not TransferCandidate for pair in plan.pairs)
        or type(plan.preferences) is not V2Preferences
        or type(plan.preferences.allow_assumed_posting_dates) is not bool
        or type(plan.preferences.allow_abbreviated_account_matching) is not bool
        or type(plan.max_day_gap) is not int
        or not 0 <= plan.max_day_gap <= 31
        or any(
            type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (plan.basis_sha256, plan.profile_sha256, plan.confirmation_sha256)
        )
        or any(
            type(value) is not int or value < 0
            for value in (plan.candidate_count, plan.ambiguous_pair_count, plan.date_blocked_pair_count)
        )
        or plan.candidate_count != len(plan.pairs) + plan.ambiguous_pair_count + plan.date_blocked_pair_count
        or plan.confirmation_sha256
        != _confirmation(
            plan.basis_sha256,
            plan.profile_sha256,
            plan.preferences,
            plan.max_day_gap,
            plan.pairs,
            plan.candidate_count,
            plan.ambiguous_pair_count,
            plan.date_blocked_pair_count,
        )
    ):
        raise ProfileFormatError("transfer_batch_plan_invalid")


def post_reviewed_transfer_batch(store, plan, *, preferences, reason, cancelled=None) -> TransferBatchResult:
    return store.post_reviewed_transfer_batch(plan, preferences=preferences, reason=reason, cancelled=cancelled)

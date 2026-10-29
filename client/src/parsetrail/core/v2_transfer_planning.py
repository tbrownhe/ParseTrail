"""Full-horizon, tentative transfer proposals for explicit one-time review.

Dates rank alternatives; they do not establish a financial relationship. The
movement model has no structured counterparty/reference field. Descriptions are
therefore displayed as source text and never parsed into matching evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date

from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import ProfileFormatError, TransferCandidate, TransferReviewSnapshot
from parsetrail.core.v2_settlements import validate_movement

RULE = "full-window-date-proposals-1"
MAX_COMPONENT_LEGS = 64
MAX_COMPONENT_EDGES = 512
DATE_EXPLANATION = (
    "Tentative date-only proposal: maximize total (horizon + 1 - day gap); "
    "unmatched scores zero. No structured reference evidence is available."
)


def pair_key(pair: TransferCandidate) -> tuple[str, str]:
    return pair.outgoing.row_id, pair.incoming.row_id


@dataclass(frozen=True)
class TransferProposal:
    pair: TransferCandidate
    component_id: str
    score: int
    explanation: str = DATE_EXPLANATION


@dataclass(frozen=True)
class TransferPlanningComponent:
    component_id: str
    pairs: tuple[TransferCandidate, ...]
    status: str
    optimum_score: int | None = None
    unmatched_row_ids: tuple[str, ...] = ()
    explanation: str = ""


@dataclass(frozen=True)
class TransferWindowPlan:
    basis_sha256: str
    profile_sha256: str
    preferences: V2Preferences
    max_day_gap: int
    candidates: tuple[TransferCandidate, ...]
    ready_pairs: tuple[TransferCandidate, ...]
    proposals: tuple[TransferProposal, ...]
    estimated_date_pairs: tuple[TransferCandidate, ...]
    components: tuple[TransferPlanningComponent, ...]
    confirmation_sha256: str

    @property
    def candidate_count(self):
        return len(self.candidates)

    @property
    def selectable_pairs(self):
        return tuple(
            sorted(self.ready_pairs + tuple(p.pair for p in self.proposals) + self.estimated_date_pairs, key=pair_key)
        )


@dataclass(frozen=True)
class TransferPostingSelection:
    plan: TransferWindowPlan
    pairs: tuple[TransferCandidate, ...]
    confirmation_sha256: str

    @property
    def total_minor(self):
        return sum(-pair.outgoing.amount_minor for pair in self.pairs)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        from parsetrail.core.v2_transfer_batch import TransferBatchCancelled

        raise TransferBatchCancelled("transfer_batch_cancelled")


def _maximum_matching(pairs, horizon, *, excluded=None, cancelled=None):
    """Exact rectangular Hungarian assignment, including an unmatched column per outflow."""
    outgoing = tuple(sorted({p.outgoing.row_id for p in pairs}))
    incoming = tuple(sorted({p.incoming.row_id for p in pairs}))
    weights = {pair_key(p): horizon + 1 - p.day_gap for p in pairs if pair_key(p) != excluded}
    forbidden = (horizon + 1) * (len(outgoing) + 1) + 1
    costs = [
        [-weights.get((out_id, in_id), -forbidden) for in_id in incoming] + [0] * len(outgoing) for out_id in outgoing
    ]
    n, m = len(outgoing), len(incoming) + len(outgoing)
    u, v, assignment, previous = [0] * (n + 1), [0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for row in range(1, n + 1):
        _check_cancelled(cancelled)
        assignment[0] = row
        minimum, used = [None] * (m + 1), [False] * (m + 1)
        column = 0
        while True:
            used[column] = True
            current = assignment[column]
            delta, next_column = None, 0
            for candidate in range(1, m + 1):
                if not used[candidate]:
                    reduced = costs[current - 1][candidate - 1] - u[current] - v[candidate]
                    if minimum[candidate] is None or reduced < minimum[candidate]:
                        minimum[candidate], previous[candidate] = reduced, column
                    if delta is None or minimum[candidate] < delta:
                        delta, next_column = minimum[candidate], candidate
            for candidate in range(m + 1):
                if used[candidate]:
                    u[assignment[candidate]] += delta
                    v[candidate] -= delta
                elif minimum[candidate] is not None:
                    minimum[candidate] -= delta
            column = next_column
            if assignment[column] == 0:
                break
        while column:
            prior = previous[column]
            assignment[column] = assignment[prior]
            column = prior
    chosen = tuple(
        sorted(
            (outgoing[assignment[column] - 1], incoming[column - 1])
            for column in range(1, len(incoming) + 1)
            if assignment[column] and (outgoing[assignment[column] - 1], incoming[column - 1]) in weights
        )
    )
    return sum(weights[key] for key in chosen), chosen


def _validated_candidates(snapshot):
    if (
        type(snapshot) is not TransferReviewSnapshot
        or snapshot.replacing_event_id is not None
        or type(snapshot.candidates) is not tuple
        or type(snapshot.preferences) is not V2Preferences
        or type(snapshot.preferences.allow_assumed_posting_dates) is not bool
        or type(snapshot.preferences.allow_abbreviated_account_matching) is not bool
        or type(snapshot.max_day_gap) is not int
        or not 0 <= snapshot.max_day_gap <= 31
        or any(
            type(v) is not str or re.fullmatch(r"[0-9a-f]{64}", v) is None
            for v in (snapshot.basis_sha256, snapshot.profile_sha256)
        )
    ):
        raise ProfileFormatError("transfer_planning_snapshot_invalid")
    movements, keys = {}, set()
    for pair in snapshot.candidates:
        try:
            if type(pair) is not TransferCandidate:
                raise ValueError
            for movement in (pair.outgoing, pair.incoming):
                validate_movement(movement)
                if movement.row_id in movements and movements[movement.row_id] != movement:
                    raise ValueError
                movements[movement.row_id] = movement
            if (
                pair_key(pair) in keys
                or pair.outgoing.account_kind != "asset"
                or pair.outgoing.amount_minor >= 0
                or pair.outgoing.amount_minor != -pair.incoming.amount_minor
                or pair.incoming.amount_minor <= 0
                or pair.outgoing.account_id == pair.incoming.account_id
                or pair.kind != ("liability payment" if pair.incoming.account_kind == "liability" else "asset transfer")
                or type(pair.day_gap) is not int
                or pair.day_gap
                != abs(
                    (
                        date.fromisoformat(pair.outgoing.posting_date) - date.fromisoformat(pair.incoming.posting_date)
                    ).days
                )
                or not 0 <= pair.day_gap <= snapshot.max_day_gap
                or type(pair.posting_allowed) is not bool
                or pair.posting_allowed != (pair.outgoing.date_allowed and pair.incoming.date_allowed)
            ):
                raise ValueError
            keys.add(pair_key(pair))
        except (ValueError, TypeError, AttributeError):
            raise ProfileFormatError("transfer_planning_graph_invalid") from None
    return tuple(sorted(snapshot.candidates, key=pair_key))


def plan_transfers(snapshot: TransferReviewSnapshot, *, cancelled=None) -> TransferWindowPlan:
    """Prepare the entire supplied horizon, with no import-order or local-gap choices."""
    candidates = _validated_candidates(snapshot)
    degrees = Counter(row for pair in candidates for row in pair_key(pair))
    by_row = {}
    for index, pair in enumerate(candidates):
        for row in pair_key(pair):
            by_row.setdefault(row, []).append(index)
    components, ready, estimated, proposals, visited = [], [], [], [], set()
    for first in sorted(by_row):
        if first in visited:
            continue
        _check_cancelled(cancelled)
        pending, rows, edges = [first], set(), set()
        while pending:
            row = pending.pop()
            if row in rows:
                continue
            rows.add(row)
            for index in by_row[row]:
                edges.add(index)
                pending.extend(other for other in pair_key(candidates[index]) if other not in rows)
        visited.update(rows)
        pairs = tuple(candidates[index] for index in sorted(edges))
        component_id = _digest([RULE, [pair_key(pair) for pair in pairs]])
        assumed = any(m.date_provenance == "assumed" for p in pairs for m in (p.outgoing, p.incoming))
        if len(pairs) == 1 and all(degrees[row] == 1 for row in pair_key(pairs[0])):
            pair = pairs[0]
            if not pair.posting_allowed:
                status, explanation = "date_blocked", "Posting date requires the existing explicit preference."
            elif assumed:
                estimated.append(pair)
                status, explanation = (
                    "estimated_dates",
                    "Unique pair with an estimated posting date; explicit selection required.",
                )
            else:
                ready.append(pair)
                status, explanation = "ready", "Neither leg has another candidate in the complete chosen horizon."
            components.append(TransferPlanningComponent(component_id, pairs, status, explanation=explanation))
            continue
        if assumed:
            components.append(
                TransferPlanningComponent(
                    component_id,
                    pairs,
                    "estimated_dates",
                    explanation="Estimated-date competitors remain in the graph; this component is not date-ranked.",
                )
            )
            continue
        if len(rows) > MAX_COMPONENT_LEGS or len(pairs) > MAX_COMPONENT_EDGES:
            components.append(
                TransferPlanningComponent(
                    component_id,
                    pairs,
                    "oversized",
                    explanation="Component exceeds the exact solver bound; all candidates remain available for individual review.",
                )
            )
            continue
        score, chosen = _maximum_matching(pairs, snapshot.max_day_gap, cancelled=cancelled)
        forced = tuple(
            key
            for key in chosen
            if _maximum_matching(pairs, snapshot.max_day_gap, excluded=key, cancelled=cancelled)[0] < score
        )
        lookup = {pair_key(pair): pair for pair in pairs}
        proposals.extend(
            TransferProposal(lookup[key], component_id, snapshot.max_day_gap + 1 - lookup[key].day_gap)
            for key in forced
            if lookup[key].posting_allowed
        )
        tied = len(forced) != len(chosen)
        unmatched = tuple(sorted(rows - {row for key in chosen for row in key})) if not tied else ()
        components.append(
            TransferPlanningComponent(
                component_id,
                pairs,
                "ties" if tied else "tentative",
                score,
                unmatched,
                DATE_EXPLANATION + (" Equal best alternatives remain unresolved." if tied else ""),
            )
        )
    values = (
        snapshot.basis_sha256,
        snapshot.profile_sha256,
        snapshot.preferences,
        snapshot.max_day_gap,
        candidates,
        tuple(sorted(ready, key=pair_key)),
        tuple(sorted(proposals, key=lambda p: pair_key(p.pair))),
        tuple(sorted(estimated, key=pair_key)),
        tuple(sorted(components, key=lambda c: c.component_id)),
    )
    unsigned = TransferWindowPlan(*values, "")
    return TransferWindowPlan(*values, _digest([RULE, asdict(unsigned)]))


def validate_window_plan(plan, *, cancelled=None):
    if type(plan) is not TransferWindowPlan:
        raise ProfileFormatError("transfer_planning_plan_invalid")
    rebuilt = plan_transfers(
        TransferReviewSnapshot(
            plan.candidates, (), (), plan.basis_sha256, plan.preferences, plan.max_day_gap, plan.profile_sha256
        ),
        cancelled=cancelled,
    )
    if rebuilt != plan:
        raise ProfileFormatError("transfer_planning_plan_invalid")


def select_transfer_plan(plan: TransferWindowPlan, pair_keys) -> TransferPostingSelection:
    """Select only explicitly chosen compatible ready or tentative pairs."""
    # A consistency token avoids rerunning the solver while users tick boxes.
    # It is not authority: the store rebuilds the full plan under its write lock.
    try:
        if type(plan) is not TransferWindowPlan or plan.confirmation_sha256 != _digest(
            [RULE, asdict(replace(plan, confirmation_sha256=""))]
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ProfileFormatError("transfer_planning_plan_invalid") from None
    try:
        keys = tuple(sorted(tuple(key) for key in pair_keys))
        available = {pair_key(pair): pair for pair in plan.selectable_pairs}
        if not keys or len(set(keys)) != len(keys) or any(key not in available for key in keys):
            raise ValueError
        pairs = tuple(available[key] for key in keys)
        rows = [row for pair in pairs for row in pair_key(pair)]
        if len(set(rows)) != len(rows):
            raise ValueError
    except (ValueError, TypeError):
        raise ProfileFormatError("transfer_planning_selection_invalid") from None
    return TransferPostingSelection(
        plan, pairs, _digest([RULE, plan.confirmation_sha256, [asdict(pair) for pair in pairs]])
    )


def validate_selection(selection):
    if type(selection) is not TransferPostingSelection or type(selection.pairs) is not tuple:
        raise ProfileFormatError("transfer_planning_selection_invalid")
    try:
        rebuilt = select_transfer_plan(selection.plan, tuple(pair_key(pair) for pair in selection.pairs))
    except (AttributeError, TypeError):
        raise ProfileFormatError("transfer_planning_selection_invalid") from None
    if rebuilt != selection:
        raise ProfileFormatError("transfer_planning_selection_invalid")


def _reason_suffix(selection):
    return (
        "\n[" + RULE + f"; horizon={selection.plan.max_day_gap}; "
        "tentative conflict score=H+1-gap; ready/estimated unranked; unmatched=0; no cardinality tiebreak; "
        f"selection={selection.confirmation_sha256}]"
    )


def max_user_reason_length(selection):
    return 500 - len(_reason_suffix(selection))


def selection_reason(selection, reason):
    """Keep the reviewed rule and exact selection token in immutable event history."""
    if type(reason) is not str or not reason.strip():
        raise ProfileFormatError("transfer_reason_required")
    recorded = reason.strip() + _reason_suffix(selection)
    if len(recorded) > 500:
        raise ProfileFormatError("transfer_planning_reason_too_long")
    return recorded


def post_reviewed_transfer_selection(store, selection, *, preferences, reason, cancelled=None):
    return store.post_reviewed_transfer_selection(
        selection, preferences=preferences, reason=reason, cancelled=cancelled
    )

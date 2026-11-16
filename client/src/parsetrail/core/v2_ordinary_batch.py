"""Immutable exact previews for explicitly selected ordinary source movements."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from parsetrail.core.ledger import JournalEntry
from parsetrail.core.v2_pending_transfers import PendingTransferDraft
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import CategoryPurpose, ProfileFormatError
from parsetrail.core.v2_review_decisions import ZeroReviewDraft
from parsetrail.core.v2_settlements import TransferMovement


class OrdinaryBatchCancelled(ProfileFormatError):
    """Cancellation leaves no batch journal or allocation committed."""


@dataclass(frozen=True)
class OrdinaryCategorySelection:
    row_id: str
    category_id: str
    purpose: CategoryPurpose
    accounting_date: date | None = None
    pending_transfer_revision_id: int | None = None


@dataclass(frozen=True)
class OrdinaryTransferSelection:
    row_id: str
    expected_revision_id: int | None = None


@dataclass(frozen=True)
class OrdinaryBatchPreview:
    source_sha256: str
    kind: Literal["cash", "card", "register"]
    selections: tuple[OrdinaryCategorySelection | OrdinaryTransferSelection, ...]
    entries: tuple[JournalEntry, ...]
    basis_sha256: str
    profile_sha256: str
    preferences: V2Preferences | None
    reason: str
    preview_sha256: str
    pending_transfers: tuple[PendingTransferDraft, ...] = ()
    pending_transfer_withdrawals: tuple[PendingTransferDraft, ...] = ()
    transfer_entries: tuple[JournalEntry, ...] = ()
    zero_reviews: tuple[ZeroReviewDraft, ...] = ()


@dataclass(frozen=True)
class OrdinaryBatchResult:
    entry_keys: tuple[str, ...]
    already_posted: bool = False
    pending_transfer_revision_ids: tuple[int, ...] = ()
    resolution_event_ids: tuple[str, ...] = ()
    zero_review_revision_ids: tuple[int, ...] = ()


def preview_digest(preview: OrdinaryBatchPreview) -> str:
    """Bind the confirmation to every exact effect and explicit review choice."""
    fields = asdict(preview)
    fields.pop("preview_sha256")
    return hashlib.sha256(
        json.dumps(["ordinary-category-batch-1", fields], sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def validate_effect_correspondence(preview: OrdinaryBatchPreview) -> None:
    """Bind every selected action to exactly one effect, including saved retries.

    Recomputed preview hashes are consistency checks, not authority. In
    particular, an existing category entry must never make an unrepresented
    transfer selection appear to have been successfully saved.
    """
    categories = tuple(i for i in preview.selections if type(i) is OrdinaryCategorySelection)
    transfers = tuple(i for i in preview.selections if type(i) is OrdinaryTransferSelection)
    withdrawals = tuple(i for i in categories if i.pending_transfer_revision_id is not None)
    valid = (
        len(preview.entries) + len(preview.zero_reviews) == len(categories)
        and len(preview.pending_transfers) == len(transfers)
        and len(preview.transfer_entries) == len(transfers)
        and len(preview.pending_transfer_withdrawals) == len(withdrawals)
    )
    if valid:
        for drafts, selections, action, revision_field in (
            (preview.pending_transfers, transfers, "pending", "expected_revision_id"),
            (preview.pending_transfer_withdrawals, withdrawals, "withdrawn", "pending_transfer_revision_id"),
        ):
            for item, selected in zip(drafts, selections, strict=True):
                valid = valid and (
                    type(item) is PendingTransferDraft
                    and type(item.movement) is TransferMovement
                    and item.row_id == selected.row_id == item.movement.row_id
                    and item.movement.source_sha256 == preview.source_sha256
                    and item.action == action
                    and item.prior_revision_id == getattr(selected, revision_field)
                )
    if not valid:
        raise ProfileFormatError("ordinary_batch_effect_selection_mismatch")
    zero_ids = {item.row_id for item in preview.zero_reviews}
    if (
        len(zero_ids) != len(preview.zero_reviews)
        or not zero_ids <= {item.row_id for item in categories}
        or any(type(item) is not ZeroReviewDraft for item in preview.zero_reviews)
        or any(
            (item.category_id, item.purpose)
            != next((s.category_id, s.purpose) for s in categories if s.row_id == item.row_id)
            for item in preview.zero_reviews
        )
    ):
        raise ProfileFormatError("ordinary_batch_effect_selection_mismatch")


def check_cancelled(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise OrdinaryBatchCancelled("ordinary_batch_cancelled")

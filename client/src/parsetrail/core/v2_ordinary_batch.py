"""Immutable exact previews for explicitly selected ordinary source movements."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from parsetrail.core.ledger import JournalEntry
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import CategoryPurpose, ProfileFormatError


class OrdinaryBatchCancelled(ProfileFormatError):
    """Cancellation leaves no batch journal or allocation committed."""


@dataclass(frozen=True)
class OrdinaryCategorySelection:
    row_id: str
    category_id: str
    purpose: CategoryPurpose
    accounting_date: date | None = None


@dataclass(frozen=True)
class OrdinaryBatchPreview:
    source_sha256: str
    kind: Literal["cash", "card", "register"]
    selections: tuple[OrdinaryCategorySelection, ...]
    entries: tuple[JournalEntry, ...]
    basis_sha256: str
    profile_sha256: str
    preferences: V2Preferences | None
    reason: str
    preview_sha256: str


@dataclass(frozen=True)
class OrdinaryBatchResult:
    entry_keys: tuple[str, ...]
    already_posted: bool = False


def preview_digest(preview: OrdinaryBatchPreview) -> str:
    """Bind the confirmation to every exact effect and explicit review choice."""
    fields = asdict(preview)
    fields.pop("preview_sha256")
    return hashlib.sha256(
        json.dumps(["ordinary-category-batch-1", fields], sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def check_cancelled(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise OrdinaryBatchCancelled("ordinary_batch_cancelled")

"""Single-source 2.0 ingestion before account mapping or ledger review."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_profile_store import V2ProfileStore


class ImportCancelled(ValueError):
    """Cancellation left the new source and observations unrecorded."""


@dataclass(frozen=True, slots=True)
class SourceImportResult:
    status: Literal["imported", "already_imported"]
    source_sha256: str
    evidence: SourceEvidence


@dataclass(frozen=True, slots=True)
class ReparseComparison:
    source_sha256: str
    saved: SourceEvidence
    candidate: SourceEvidence
    identical_output: bool


Parser = Callable[[bytes, bytes], SourceEvidence]


def import_source(
    store: V2ProfileStore,
    source: bytes,
    definition: bytes,
    *,
    suffix: Literal[".csv", ".pdf"],
    parse: Parser,
    cancelled: Callable[[], bool] | None = None,
) -> SourceImportResult:
    """Parse only new bytes, then atomically retain their unposted evidence."""
    if cancelled is not None and cancelled():
        raise ImportCancelled("cancelled")
    source_hash = hashlib.sha256(source).hexdigest()
    if store.source_imported(source):
        saved = store.load_import(source_hash)
        return SourceImportResult("already_imported", source_hash, saved.evidence)
    evidence = parse(source, definition)
    if cancelled is not None and cancelled():
        raise ImportCancelled("cancelled")
    inserted = store.import_source(source, definition, evidence, suffix=suffix)
    saved = store.load_import(source_hash)
    return SourceImportResult("imported" if inserted else "already_imported", source_hash, saved.evidence)


def compare_reparse(
    store: V2ProfileStore,
    source_sha256: str,
    candidate_definition: bytes,
    *,
    parse: Parser,
) -> ReparseComparison:
    """Reparse saved bytes for review without replacing their original snapshot."""
    saved = store.load_import(source_sha256)
    candidate = parse(saved.source, candidate_definition)
    try:
        candidate = SourceEvidence.model_validate_json(candidate.model_dump_json())
    except (AttributeError, ValueError):
        raise ValueError("invalid_reparse_evidence") from None
    if (
        candidate.source_sha256 != source_sha256
        or candidate.definition_sha256 != hashlib.sha256(candidate_definition).hexdigest()
    ):
        raise ValueError("reparse_source_or_definition_mismatch")
    return ReparseComparison(source_sha256, saved.evidence, candidate, saved.evidence == candidate)

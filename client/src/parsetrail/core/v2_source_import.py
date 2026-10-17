"""Single-source 2.0 ingestion before account mapping or ledger review."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_data_catalog import VerifiedCatalog
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_pipeline import SourcePipelineError, build_source_evidence


class ImportCancelled(ValueError):
    """Cancellation left the new source and observations unrecorded."""


class CatalogImportError(ValueError):
    """No unique verified definition admits the source evidence."""


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


class CatalogParser(Protocol):
    def __call__(
        self,
        source: bytes,
        definition: bytes,
        *,
        suffix: Literal[".csv", ".pdf"],
        cancelled: Callable[[], bool] | None = None,
    ) -> SourceEvidence: ...


def _saved_retry(store: V2ProfileStore, source: bytes) -> SourceImportResult | None:
    if store.source_imported(source):
        source_hash = hashlib.sha256(source).hexdigest()
        saved = store.load_import(source_hash)
        return SourceImportResult("already_imported", source_hash, saved.evidence)
    return None


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
    existing = _saved_retry(store, source)
    if existing is not None:
        return existing
    source_hash = hashlib.sha256(source).hexdigest()
    evidence = parse(source, definition)
    if cancelled is not None and cancelled():
        raise ImportCancelled("cancelled")
    inserted = store.import_source(source, definition, evidence, suffix=suffix)
    saved = store.load_import(source_hash)
    return SourceImportResult("imported" if inserted else "already_imported", source_hash, saved.evidence)


def import_catalog_source(
    store: V2ProfileStore,
    source: bytes,
    *,
    catalog: VerifiedCatalog,
    parser_id: str | None = None,
    suffix: Literal[".csv", ".pdf"],
    parse: CatalogParser = build_source_evidence,
    cancelled: Callable[[], bool] | None = None,
) -> SourceImportResult:
    """Import a verified entry, with unique bounded CSV selection when omitted."""
    if cancelled is not None and cancelled():
        raise ImportCancelled("cancelled")
    existing = _saved_retry(store, source)
    if existing is not None:
        return existing
    preparsed = None
    if parser_id is None:
        if suffix != ".csv":
            raise CatalogImportError("automatic_pdf_routing_unavailable")
        matches = []
        for item in catalog.definitions:
            if item.identity.suffix != ".csv":
                continue
            if cancelled is not None and cancelled():
                raise ImportCancelled("cancelled")
            try:
                candidate = parse(source, item.content, suffix=suffix, cancelled=cancelled)
            except SourcePipelineError:
                if cancelled is not None and cancelled():
                    raise ImportCancelled("cancelled") from None
                continue
            if (
                not isinstance(candidate, SourceEvidence)
                or candidate.parser_id != item.identity.parser_id
                or candidate.definition_revision != item.identity.revision
                or candidate.definition_sha256 != item.sha256
            ):
                raise CatalogImportError("catalog_evidence_mismatch")
            matches.append((item, candidate))
        if len(matches) != 1:
            raise CatalogImportError("catalog_ambiguous_match" if matches else "catalog_no_match")
        selected, preparsed = matches[0]
    else:
        choices = tuple(item for item in catalog.definitions if item.identity.parser_id == parser_id)
        if len(choices) != 1 or choices[0].identity.suffix != suffix:
            raise CatalogImportError("catalog_definition_unavailable")
        selected = choices[0]

    def admitted_parse(source_bytes: bytes, definition_bytes: bytes) -> SourceEvidence:
        try:
            evidence = (
                preparsed
                if preparsed is not None
                else parse(source_bytes, definition_bytes, suffix=suffix, cancelled=cancelled)
            )
        except Exception:
            if cancelled is not None and cancelled():
                raise ImportCancelled("cancelled") from None
            raise
        if (
            not isinstance(evidence, SourceEvidence)
            or evidence.parser_id != selected.identity.parser_id
            or evidence.definition_revision != selected.identity.revision
            or evidence.definition_sha256 != selected.sha256
        ):
            raise CatalogImportError("catalog_evidence_mismatch")
        return evidence

    return import_source(
        store,
        source,
        selected.content,
        suffix=suffix,
        parse=admitted_parse,
        cancelled=cancelled,
    )


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

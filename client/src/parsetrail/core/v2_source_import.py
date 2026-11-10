"""Single-source 2.0 ingestion before account mapping or ledger review."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_data_catalog import VerifiedCatalog
from parsetrail.core.v2_format_recognition import (
    CatalogImportError,
    CatalogParser,
    FormatCandidate,
    FormatSelection,
    ImportCancelled,
    candidate_from_evidence,
    selected_definition,
    validate_catalog_evidence,
)
from parsetrail.core.v2_pdf_routing import PDFRoutingError, select_pdf_definition
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_pipeline import SourcePipelineError, build_source_evidence
from parsetrail.core.v2_worker_limits import WorkerError


@dataclass(frozen=True, slots=True)
class SourceImportResult:
    status: Literal["imported", "already_imported"]
    source_sha256: str
    evidence: SourceEvidence


@dataclass(frozen=True, slots=True)
class PreparedSourceImport:
    """Revalidated source/evidence for an atomic account-and-import commit."""

    source: bytes
    definition: bytes
    evidence: SourceEvidence
    suffix: Literal[".csv", ".pdf"]
    candidate: FormatCandidate


def prepare_catalog_source(
    source: bytes,
    *,
    catalog: VerifiedCatalog,
    suffix: Literal[".csv", ".pdf"],
    selection: FormatSelection,
    cancelled: Callable[[], bool] | None = None,
    parse: CatalogParser = build_source_evidence,
) -> PreparedSourceImport:
    """Reparse exact selected bytes without opening or writing a profile."""
    if cancelled is not None and cancelled():
        raise ImportCancelled("cancelled")
    definition = selected_definition(source, catalog=catalog, suffix=suffix, selection=selection)
    if suffix == ".pdf":
        try:
            routed_id = select_pdf_definition(source, catalog, cancelled=cancelled)
        except (PDFRoutingError, WorkerError) as error:
            if cancelled is not None and cancelled():
                raise ImportCancelled("cancelled") from None
            raise CatalogImportError(
                str(error) if isinstance(error, PDFRoutingError) else "pdf_routing_failed"
            ) from None
        if routed_id != definition.identity.parser_id:
            raise CatalogImportError("catalog_selected_route_mismatch")
    try:
        evidence = parse(source, definition.content, suffix=suffix, cancelled=cancelled)
    except Exception:
        if cancelled is not None and cancelled():
            raise ImportCancelled("cancelled") from None
        raise
    if cancelled is not None and cancelled():
        raise ImportCancelled("cancelled")
    validate_catalog_evidence(evidence, hashlib.sha256(source).hexdigest(), definition)
    candidate = candidate_from_evidence(definition, evidence, catalog)
    if cancelled is not None and cancelled():
        raise ImportCancelled("cancelled")
    return PreparedSourceImport(source, definition.content, evidence, suffix, candidate)


@dataclass(frozen=True, slots=True)
class ReparseComparison:
    source_sha256: str
    saved: SourceEvidence
    candidate: SourceEvidence
    identical_output: bool


Parser = Callable[[bytes, bytes], SourceEvidence]


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
    selection: FormatSelection | None = None,
    suffix: Literal[".csv", ".pdf"],
    parse: CatalogParser = build_source_evidence,
    cancelled: Callable[[], bool] | None = None,
) -> SourceImportResult:
    """Import a verified entry; PDFs must have one matching signed route."""
    if cancelled is not None and cancelled():
        raise ImportCancelled("cancelled")
    selected = None
    if selection is not None:
        selected = selected_definition(source, catalog=catalog, suffix=suffix, selection=selection)
        if parser_id is not None and parser_id != selected.identity.parser_id:
            raise CatalogImportError("catalog_selection_mismatch")
        parser_id = selected.identity.parser_id
    existing = _saved_retry(store, source)
    if existing is not None:
        return existing
    if parser_id is not None:
        choices = tuple(item for item in catalog.definitions if item.identity.parser_id == parser_id)
        if len(choices) != 1 or choices[0].identity.suffix != suffix:
            raise CatalogImportError("catalog_definition_unavailable")
        selected = choices[0]
    if suffix == ".pdf":
        try:
            routed_id = select_pdf_definition(source, catalog, cancelled=cancelled)
        except (PDFRoutingError, WorkerError) as error:
            if cancelled is not None and cancelled():
                raise ImportCancelled("cancelled") from None
            code = str(error) if isinstance(error, PDFRoutingError) else "pdf_routing_failed"
            raise CatalogImportError(code) from None
        if parser_id is not None and parser_id != routed_id:
            raise CatalogImportError("catalog_selected_route_mismatch")
        parser_id = routed_id
    preparsed = None
    if parser_id is None:
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
            validate_catalog_evidence(candidate, hashlib.sha256(source).hexdigest(), item)
            matches.append((item, candidate))
        if len(matches) != 1:
            raise CatalogImportError("catalog_ambiguous_match" if matches else "catalog_no_match")
        selected, preparsed = matches[0]
    elif selected is None:
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
        validate_catalog_evidence(evidence, hashlib.sha256(source_bytes).hexdigest(), selected)
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

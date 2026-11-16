"""Read-only recognition of complete files against installed signed definitions.

Candidates are bounded previews, never cached evidence or permission to post.
Selection binds the exact source, catalog snapshot and declaration; import parses
the selected declaration again before retaining authoritative evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from parsetrail.core.source_evidence import (
    ActivityExportPayload,
    ComponentEvidence,
    DateValue,
    MoneyValue,
    SourceEvidence,
    SourceLocation,
    StatementPayload,
)
from parsetrail.core.v2_account_products import AccountProductProfile
from parsetrail.core.v2_data_catalog import VerifiedCatalog, VerifiedDefinition
from parsetrail.core.v2_parser_engine import load_definition
from parsetrail.core.v2_pdf_routing import PDFRoutingError, select_pdf_definition
from parsetrail.core.v2_source_account_context import source_account_profiles, verified_source_account_context
from parsetrail.core.v2_source_pipeline import MAX_SOURCE_BYTES, SourcePipelineError, build_source_evidence
from parsetrail.core.v2_worker_limits import WorkerError

PREVIEW_ROWS = 5
PREVIEW_DESCRIPTION_CHARS = 240
PREVIEW_ACCOUNT_CHARS = 160
MAX_SOURCE_ACCOUNTS = 100


class ImportCancelled(ValueError):
    """Cancellation left the new source and observations unrecorded."""


class CatalogImportError(ValueError):
    """No verified definition or current explicit selection admits the source."""


class CatalogParser(Protocol):
    def __call__(
        self,
        source: bytes,
        definition: bytes,
        *,
        suffix: Literal[".csv", ".pdf"],
        cancelled: Callable[[], bool] | None = None,
    ) -> SourceEvidence: ...


@dataclass(frozen=True, slots=True)
class FormatPreviewRow:
    row_id: str
    date: DateValue
    date_role: str
    description: str
    amount: MoneyValue
    running_balance: MoneyValue | None
    components: tuple[ComponentEvidence, ...]
    source_account: str | None
    locations: tuple[SourceLocation, ...]


@dataclass(frozen=True, slots=True)
class FormatSourceAccount:
    source_identity: str | None
    source_form: str | None
    row_count: int
    locations: tuple[SourceLocation, ...]
    source_label: str | None = None
    source_scope: str | None = None


@dataclass(frozen=True, slots=True)
class FormatCandidate:
    parser_id: str
    revision: str
    definition_sha256: str
    institution_key: str | None
    account_kind: str | None
    row_count: int
    start: DateValue
    end: DateValue
    preview_rows: tuple[FormatPreviewRow, ...]
    header: tuple[str, ...]
    column_mapping: tuple[tuple[str, str], ...]
    date_format: str | None
    date_role: str | None
    money_format: str | None
    engine_version: str
    extractor_version: str
    source_accounts: tuple[FormatSourceAccount, ...] = ()
    account_profiles: tuple[AccountProductProfile, ...] = ()
    identifying_product_type: str | None = None
    attention_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FormatSelection:
    source_sha256: str
    suffix: Literal[".csv", ".pdf"]
    catalog_sha256: str
    parser_id: str
    revision: str
    definition_sha256: str


@dataclass(frozen=True, slots=True)
class FormatRecognition:
    source_sha256: str
    suffix: Literal[".csv", ".pdf"]
    catalog_sha256: str
    candidates: tuple[FormatCandidate, ...]

    def selection(self, parser_id: str) -> FormatSelection:
        candidates = tuple(candidate for candidate in self.candidates if candidate.parser_id == parser_id)
        if len(candidates) != 1:
            raise CatalogImportError("catalog_definition_unavailable")
        candidate = candidates[0]
        return FormatSelection(
            self.source_sha256,
            self.suffix,
            self.catalog_sha256,
            candidate.parser_id,
            candidate.revision,
            candidate.definition_sha256,
        )


def catalog_digest(catalog: VerifiedCatalog) -> str:
    return hashlib.sha256(catalog.snapshot).hexdigest()


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ImportCancelled("cancelled")


def validate_catalog_evidence(evidence: SourceEvidence, source_hash: str, definition: VerifiedDefinition) -> None:
    """Retain the same declaration identity as the installed signed definition."""
    if (
        not isinstance(evidence, SourceEvidence)
        or evidence.source_sha256 != source_hash
        or evidence.parser_id != definition.identity.parser_id
        or evidence.definition_revision != definition.identity.revision
        or evidence.definition_sha256 != definition.sha256
    ):
        raise CatalogImportError("catalog_evidence_mismatch")


def selected_definition(
    source: bytes,
    *,
    catalog: VerifiedCatalog,
    suffix: Literal[".csv", ".pdf"],
    selection: FormatSelection,
) -> VerifiedDefinition:
    """Reject changed source/catalog/definition rather than reusing an old preview."""
    if not isinstance(selection, FormatSelection) or selection.suffix != suffix:
        raise CatalogImportError("catalog_selection_mismatch")
    if hashlib.sha256(source).hexdigest() != selection.source_sha256:
        raise CatalogImportError("catalog_selection_source_changed")
    if catalog_digest(catalog) != selection.catalog_sha256:
        raise CatalogImportError("catalog_selection_catalog_changed")
    candidates = tuple(
        item
        for item in catalog.definitions
        if item.identity.parser_id == selection.parser_id
        and item.identity.revision == selection.revision
        and item.identity.suffix == suffix
        and item.sha256 == selection.definition_sha256
    )
    if len(candidates) != 1:
        raise CatalogImportError("catalog_selection_definition_changed")
    return candidates[0]


def _excerpt(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _source_accounts(evidence: SourceEvidence, profiles) -> tuple[FormatSourceAccount, ...]:
    payload = evidence.payload
    if isinstance(payload, StatementPayload):
        return tuple(
            FormatSourceAccount(
                section.source_identity,
                section.source_identity_form,
                len(section.rows),
                section.identity_locations,
                source_scope=section.balance_scope,
            )
            for section in payload.accounts
        )
    counts, locations = {}, {}
    for row in payload.rows:
        key = (row.source_account, row.source_account_form)
        if key not in counts:
            if len(counts) == MAX_SOURCE_ACCOUNTS:
                raise SourcePipelineError("source_account_group_limit")
            counts[key] = 0
            locations[key] = tuple(fragment.location for fragment in row.fragments)[:16]
        counts[key] += 1
    # An empty export still has one unidentified account-selection question.
    if not counts:
        counts[None, None], locations[None, None] = 0, ()
    scopes = {profile.tracking_scope for profile in profiles}
    scope = next(iter(scopes)) if len(scopes) == 1 else None
    return tuple(
        FormatSourceAccount(identity, form, count, locations[identity, form], source_scope=scope)
        for (identity, form), count in counts.items()
    )


def candidate_from_evidence(
    item: VerifiedDefinition, evidence: SourceEvidence, catalog: VerifiedCatalog
) -> FormatCandidate:
    if item not in catalog.definitions or hashlib.sha256(item.content).hexdigest() != item.sha256:
        raise CatalogImportError("catalog_definition_unavailable")
    validate_catalog_evidence(evidence, evidence.source_sha256, item)
    payload = evidence.payload
    if isinstance(payload, StatementPayload):
        row_count = sum(len(account.rows) for account in payload.accounts)
        rows = tuple(row for account in payload.accounts for row in account.rows)
        start, end = payload.start, payload.end
    else:
        row_count = len(payload.rows)
        rows = payload.rows
        start, end = payload.activity_start, payload.activity_end
    preview = []
    for row in rows:
        if len(preview) == PREVIEW_ROWS:
            break
        preview.append(
            FormatPreviewRow(
                row.row_id,
                row.date,
                row.date_role,
                _excerpt(row.description.text or row.description.raw or "", PREVIEW_DESCRIPTION_CHARS),
                row.amount,
                row.running_balance,
                row.components,
                _excerpt(row.source_account, PREVIEW_ACCOUNT_CHARS) if row.source_account else None,
                tuple(fragment.location for fragment in row.fragments),
            )
        )
    header, mapping, date_format, date_role, money_format = (), (), None, None, None
    if item.identity.suffix == ".csv" and isinstance(payload, ActivityExportPayload):
        declaration, _digest = load_definition(item.content)
        header = declaration.header
        mapping = tuple(
            (role, column) for role, column in declaration.columns.model_dump().items() if column is not None
        )
        date_format, date_role, money_format = declaration.date_format, declaration.date_role, declaration.money_format
    context = verified_source_account_context(evidence, catalog)
    profiles = source_account_profiles(evidence, catalog)
    attention = []
    if not row_count:
        attention.append("no_activity_captured")
    if start.iso is None or end.iso is None:
        attention.append("source_period_unknown")
    if start.provenance == "assumed" or end.provenance == "assumed":
        attention.append("source_period_assumed")
    if any(row.date.provenance == "assumed" for row in rows):
        attention.append("source_activity_date_assumed")
    attention.extend(
        item.code
        for item in payload.dispositions
        if any(token in item.code for token in ("unclassified", "unsupported", "unresolved", "mismatch"))
    )
    return FormatCandidate(
        item.identity.parser_id,
        item.identity.revision,
        item.sha256,
        context.institution_key if context is not None else None,
        context.kind if context is not None else None,
        row_count,
        start,
        end,
        tuple(preview),
        header,
        mapping,
        date_format,
        date_role,
        money_format,
        evidence.engine_version,
        evidence.extractor_version,
        _source_accounts(evidence, profiles),
        profiles,
        context.product_type if context is not None else None,
        tuple(dict.fromkeys(attention)),
    )


def recognize_catalog_source(
    source: bytes,
    *,
    catalog: VerifiedCatalog,
    suffix: Literal[".csv", ".pdf"],
    parse: CatalogParser = build_source_evidence,
    cancelled: Callable[[], bool] | None = None,
) -> FormatRecognition:
    """Fully validate candidates without opening a profile or retaining full outputs.

    CSV candidates must match the exact ordered declared header (including
    only its explicitly declared wrappers) and pass every row rule. Account
    metadata may narrow overlapping declarations; users do not map columns.
    A PDF has only its one unique signed route; selection cannot override it.
    """
    _check_cancelled(cancelled)
    if type(source) is not bytes or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise SourcePipelineError("source_size")
    if suffix not in {".csv", ".pdf"}:
        raise SourcePipelineError("unsupported_source_kind")
    source_hash = hashlib.sha256(source).hexdigest()
    definitions = tuple(item for item in catalog.definitions if item.identity.suffix == suffix)
    if suffix == ".pdf":
        try:
            routed_id = select_pdf_definition(source, catalog, cancelled=cancelled)
        except (PDFRoutingError, WorkerError) as exc:
            _check_cancelled(cancelled)
            raise CatalogImportError(str(exc) if isinstance(exc, PDFRoutingError) else "pdf_routing_failed") from None
        definitions = tuple(item for item in definitions if item.identity.parser_id == routed_id)
    candidates = []
    for item in definitions:
        _check_cancelled(cancelled)
        try:
            evidence = parse(source, item.content, suffix=suffix, cancelled=cancelled)
        except SourcePipelineError:
            _check_cancelled(cancelled)
            if suffix == ".pdf":
                raise
            continue
        _check_cancelled(cancelled)
        validate_catalog_evidence(evidence, source_hash, item)
        candidates.append(candidate_from_evidence(item, evidence, catalog))
        # The next candidate must not keep this candidate's complete evidence.
        del evidence
    _check_cancelled(cancelled)
    return FormatRecognition(source_hash, suffix, catalog_digest(catalog), tuple(candidates))

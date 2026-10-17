"""Wells table-region pilot with PDF word and table work confined to a worker."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from pydantic import TypeAdapter, ValidationError

from parsetrail.core.v2_pdf_lines import MAX_PDF_BYTES
from parsetrail.core.v2_wells_table import (
    MAX_DEFINITION_BYTES,
    MAX_TABLE_ROWS,
    WellsTableEvidence,
    load_definition,
)
from parsetrail.core.v2_worker_limits import MAX_OUTPUT_BYTES, WorkerError, WorkerLimits, run_worker

_EVIDENCE_ADAPTER = TypeAdapter(WellsTableEvidence)


def extract_bounded_wells(
    definition: bytes,
    source: bytes,
    *,
    limits: WorkerLimits = WorkerLimits(),
    cancelled: Callable[[], bool] | None = None,
) -> WellsTableEvidence:
    """Extract capped raw cells and regions; no financial rows are admitted."""
    if not isinstance(definition, bytes) or not 0 < len(definition) <= MAX_DEFINITION_BYTES:
        raise WorkerError("definition_size")
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_PDF_BYTES:
        raise WorkerError("source_size")
    declaration, definition_hash = load_definition(definition)
    payload = len(definition).to_bytes(4, "big") + definition + source
    output = run_worker(
        "pdf_wells_table",
        payload,
        output_limit=MAX_OUTPUT_BYTES,
        limits=limits,
        cancelled=cancelled,
    )
    try:
        evidence = _EVIDENCE_ADAPTER.validate_json(output, strict=True)
    except ValidationError:
        raise WorkerError("invalid_output") from None
    if (
        evidence.output_schema_version != 1
        or evidence.source_sha256 != hashlib.sha256(source).hexdigest()
        or evidence.definition_sha256 != definition_hash
        or evidence.parser_id != declaration.parser_id
        or evidence.definition_revision != declaration.revision
        or evidence.coverage_verified is not False
        or evidence.account_balance_reconciled is not False
        or len(evidence.rows) > MAX_TABLE_ROWS
        or any(row.page < 1 or row.page > len(evidence.pages) for row in evidence.rows)
    ):
        raise WorkerError("invalid_output")
    return evidence

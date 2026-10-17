"""Parent-side validation for bounded declared PDF table extraction."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable

from pydantic import TypeAdapter, ValidationError

from devtools.parser_engine_pilot.anchored_table import (
    ENGINE_VERSION,
    MAX_CELL_CHARS,
    MAX_CHARS_PER_PAGE,
    MAX_DEFINITION_BYTES,
    MAX_TABLE_ROWS,
    AnchoredTableEvidence,
    load_definition,
)
from devtools.parser_engine_pilot.pdf_lines import MAX_PDF_BYTES
from devtools.parser_engine_pilot.worker_limits import MAX_OUTPUT_BYTES, WorkerError, WorkerLimits, run_worker

_ADAPTER = TypeAdapter(AnchoredTableEvidence)


def extract_bounded_anchored_table(
    definition: bytes,
    source: bytes,
    *,
    limits: WorkerLimits = WorkerLimits(),
    cancelled: Callable[[], bool] | None = None,
) -> AnchoredTableEvidence:
    """Decode only checked declaration geometry and capped table cells."""
    if type(definition) is not bytes or not 0 < len(definition) <= MAX_DEFINITION_BYTES:
        raise WorkerError("definition_size")
    if type(source) is not bytes or not 0 < len(source) <= MAX_PDF_BYTES:
        raise WorkerError("source_size")
    parsed, definition_hash = load_definition(definition)
    payload = len(definition).to_bytes(4, "big") + definition + source
    output = run_worker(
        "devtools.parser_engine_pilot.anchored_table_worker",
        payload,
        output_limit=MAX_OUTPUT_BYTES,
        limits=limits,
        cancelled=cancelled,
    )
    try:
        evidence = _ADAPTER.validate_json(output, strict=True)
    except ValidationError:
        raise WorkerError("invalid_output") from None
    if (
        evidence.output_schema_version != 1
        or evidence.source_sha256 != hashlib.sha256(source).hexdigest()
        or evidence.definition_sha256 != definition_hash
        or evidence.engine_version != ENGINE_VERSION
        or not evidence.extraction_library.startswith("pdfplumber-")
        or not 0 < len(evidence.first_page_chars) <= MAX_CHARS_PER_PAGE
        or not evidence.pages
        or not any(page.status == "table" for page in evidence.pages)
        or len(evidence.rows) > MAX_TABLE_ROWS
        or any(page.page != index for index, page in enumerate(evidence.pages, 1))
        or any(
            row.page < 1
            or row.page > len(evidence.pages)
            or row.ordinal < 1
            or len(row.raw_cells) != len(parsed.boundaries) - 1
            or any(len(cell) > MAX_CELL_CHARS for cell in row.raw_cells)
            or not all(math.isfinite(value) for value in row.region)
            for row in evidence.rows
        )
    ):
        raise WorkerError("invalid_output")
    return evidence

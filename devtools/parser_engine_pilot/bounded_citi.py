"""Recent Citi table evidence behind the shared OS-limited worker boundary."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable

from parsetrail.core.v2_citi_table import (
    ENGINE_VERSION,
    MAX_CELL_CHARS,
    MAX_CHARS_PER_PAGE,
    MAX_TABLE_ROWS,
    CitiTableEvidence,
)
from parsetrail.core.v2_pdf_lines import MAX_PDF_BYTES
from parsetrail.core.v2_worker_limits import MAX_OUTPUT_BYTES, WorkerError, WorkerLimits, run_worker
from pydantic import TypeAdapter, ValidationError

_EVIDENCE_ADAPTER = TypeAdapter(CitiTableEvidence)


def extract_bounded_citi(
    source: bytes,
    *,
    limits: WorkerLimits = WorkerLimits(),
    cancelled: Callable[[], bool] | None = None,
) -> CitiTableEvidence:
    """Extract capped source cells and regions; never post financial rows."""
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_PDF_BYTES:
        raise WorkerError("source_size")
    output = run_worker(
        "pdf_citi_table",
        source,
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
        or evidence.engine_version != ENGINE_VERSION
        or evidence.coverage_verified is not False
        or evidence.account_balance_reconciled is not False
        or not evidence.first_page_chars
        or len(evidence.first_page_chars) > MAX_CHARS_PER_PAGE
        or not evidence.pages
        or len(evidence.rows) > MAX_TABLE_ROWS
        or any(page.page != index for index, page in enumerate(evidence.pages, 1))
        or any(
            row.page < 1
            or row.page > len(evidence.pages)
            or row.table_row < 1
            or len(row.raw_cells) != 4
            or any(len(cell) > MAX_CELL_CHARS for cell in row.raw_cells)
            or (row.channel == "table" and row.region is None)
            or (row.channel == "interest_text" and row.source_line is None)
            or (row.region is not None and not all(math.isfinite(value) for value in row.region))
            for row in evidence.rows
        )
    ):
        raise WorkerError("invalid_output")
    return evidence

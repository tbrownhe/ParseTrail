"""Read-only XLSX evidence decoding through the shared limited worker."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from parsetrail.core.v2_worker_limits import MAX_OUTPUT_BYTES, WorkerError, WorkerLimits, run_worker
from pydantic import TypeAdapter, ValidationError

from devtools.parser_engine_pilot.engine import MAX_DEFINITION_BYTES, MAX_SOURCE_BYTES, Evidence

_EVIDENCE_ADAPTER = TypeAdapter(Evidence)
DEFAULT_XLSX_LIMITS = WorkerLimits(memory_bytes=1024 * 1024 * 1024)


def parse_bounded_xlsx(
    definition: bytes,
    source: bytes,
    *,
    sheet: str,
    limits: WorkerLimits = DEFAULT_XLSX_LIMITS,
    cancelled: Callable[[], bool] | None = None,
) -> Evidence:
    """Return checked evidence without loading workbook XML in this process."""
    if not isinstance(definition, bytes) or not 0 < len(definition) <= MAX_DEFINITION_BYTES:
        raise WorkerError("definition_size")
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise WorkerError("source_size")
    if not isinstance(sheet, str) or not sheet or len(sheet) > 31:
        raise WorkerError("sheet_name")
    sheet_bytes = sheet.encode("utf-8")
    if len(sheet_bytes) > 124:
        raise WorkerError("sheet_name")
    payload = (
        len(definition).to_bytes(4, "big") + len(sheet_bytes).to_bytes(2, "big") + definition + sheet_bytes + source
    )
    output = run_worker(
        "devtools.parser_engine_pilot.xlsx_worker",
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
        or evidence.definition_sha256 != hashlib.sha256(definition).hexdigest()
        or evidence.kind != "activity_export"
        or any(row.total.location.sheet != sheet for row in evidence.rows)
    ):
        raise WorkerError("invalid_output")
    return evidence

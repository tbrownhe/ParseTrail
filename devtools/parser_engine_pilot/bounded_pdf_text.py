"""Read-only PDF text decoding through the shared resource-limited worker."""

from __future__ import annotations

import json

from devtools.parser_engine_pilot.pdf_text_worker import (
    MAX_LINES_PER_PAGE,
    MAX_OUTPUT_BYTES,
    MAX_PAGE_TEXT_BYTES,
    MAX_PAGES,
    MAX_SOURCE_BYTES,
    MAX_TEXT_BYTES,
    MAX_TOTAL_LINES,
)
from devtools.parser_engine_pilot.worker_limits import WorkerError, WorkerLimits, run_worker


def decode_text(source: bytes, limits: WorkerLimits = WorkerLimits()) -> tuple[str, ...]:
    """Return capped simple page text; never open the PDF in this process."""
    if not isinstance(source, bytes) or not source or len(source) > MAX_SOURCE_BYTES:
        raise WorkerError("source_size")
    output = run_worker(
        "devtools.parser_engine_pilot.pdf_text_worker", source, output_limit=MAX_OUTPUT_BYTES, limits=limits
    )
    try:
        decoded = json.loads(output)
    except (ValueError, UnicodeDecodeError):
        raise WorkerError("invalid_output") from None
    if not isinstance(decoded, dict) or set(decoded) != {"pages"} or not isinstance(decoded["pages"], list):
        raise WorkerError("invalid_output")
    pages = decoded["pages"]
    if not 1 <= len(pages) <= MAX_PAGES or any(not isinstance(page, str) for page in pages):
        raise WorkerError("invalid_output")
    sizes = [len(page.encode("utf-8")) for page in pages]
    line_counts = [len(page.splitlines()) for page in pages]
    if (
        any(size > MAX_PAGE_TEXT_BYTES for size in sizes)
        or sum(sizes) > MAX_TEXT_BYTES
        or any(count > MAX_LINES_PER_PAGE for count in line_counts)
        or sum(line_counts) > MAX_TOTAL_LINES
    ):
        raise WorkerError("invalid_output")
    return tuple(pages)

"""Read-only PDF text decoding through the shared resource-limited worker."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from parsetrail.core.v2_pdf_text_worker import (
    MAX_LINES_PER_PAGE,
    MAX_METADATA_KEY_CHARS,
    MAX_METADATA_KEYS,
    MAX_METADATA_VALUE_CHARS,
    MAX_OUTPUT_BYTES,
    MAX_PAGE_TEXT_BYTES,
    MAX_PAGES,
    MAX_SOURCE_BYTES,
    MAX_TEXT_BYTES,
    MAX_TOTAL_LINES,
)
from parsetrail.core.v2_worker_limits import WorkerError, WorkerLimits, WorkerModule, run_worker


@dataclass(frozen=True, slots=True)
class DecodedPDFText:
    pages: tuple[str, ...]
    metadata: tuple[tuple[str, str], ...]


_operation_decodes: ContextVar[dict | None] = ContextVar("pdf_operation_decodes", default=None)


@contextmanager
def pdf_decode_operation():
    """Reuse immutable bounded results only within one synchronous operation.

    Each operation has its own context, including nested operations. Exact
    source bytes, worker mode and resource limits identify a result. Clearing
    on exit releases source/text references even if a context is retained.
    """
    decodes = {}
    token = _operation_decodes.set(decodes)
    try:
        yield
    finally:
        decodes.clear()
        _operation_decodes.reset(token)


def _decode_pdf(
    source: bytes,
    module: WorkerModule,
    limits: WorkerLimits,
    cancelled: Callable[[], bool] | None,
) -> DecodedPDFText:
    if not isinstance(source, bytes) or not source or len(source) > MAX_SOURCE_BYTES:
        raise WorkerError("source_size")
    if cancelled is not None and cancelled():
        raise WorkerError("cancelled")
    decodes = _operation_decodes.get()
    key = (source, module, limits)
    if decodes is not None and key in decodes:
        result = decodes[key]
        if cancelled is not None and cancelled():
            raise WorkerError("cancelled")
        return result
    output = run_worker(module, source, output_limit=MAX_OUTPUT_BYTES, limits=limits, cancelled=cancelled)
    try:
        decoded = json.loads(output)
    except (ValueError, UnicodeDecodeError):
        raise WorkerError("invalid_output") from None
    if (
        not isinstance(decoded, dict)
        or set(decoded) != {"pages", "metadata"}
        or not isinstance(decoded["pages"], list)
        or not isinstance(decoded["metadata"], dict)
    ):
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
    metadata = decoded["metadata"]
    if len(metadata) > MAX_METADATA_KEYS or any(
        not isinstance(key, str)
        or not key
        or len(key) > MAX_METADATA_KEY_CHARS
        or not isinstance(value, str)
        or len(value) > MAX_METADATA_VALUE_CHARS
        for key, value in metadata.items()
    ):
        raise WorkerError("invalid_output")
    result = DecodedPDFText(tuple(pages), tuple(sorted(metadata.items())))
    if cancelled is not None and cancelled():
        raise WorkerError("cancelled")
    if decodes is not None:
        decodes[key] = result
    return result


def decode_pdf(
    source: bytes, limits: WorkerLimits = WorkerLimits(), *, cancelled: Callable[[], bool] | None = None
) -> DecodedPDFText:
    """Return capped simple pages and metadata without opening a PDF here."""
    return _decode_pdf(source, "pdf_text_simple", limits, cancelled)


def decode_pdf_layout(
    source: bytes, limits: WorkerLimits = WorkerLimits(), *, cancelled: Callable[[], bool] | None = None
) -> DecodedPDFText:
    """Return capped fixed-tolerance layout pages through the same OS boundary."""
    return _decode_pdf(source, "pdf_text_fixed", limits, cancelled)


def decode_pdf_default_layout(
    source: bytes, limits: WorkerLimits = WorkerLimits(), *, cancelled: Callable[[], bool] | None = None
) -> DecodedPDFText:
    """Return capped default-layout pages through the same OS boundary."""
    return _decode_pdf(source, "pdf_text_default", limits, cancelled)

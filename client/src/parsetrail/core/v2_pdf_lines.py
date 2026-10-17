"""Bounded page/line provenance pilot for already extracted PDF text."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass

MAX_PDF_BYTES = 16 * 1024 * 1024
MAX_PAGES = 100
MAX_LINES = 100_000
MAX_TEXT_CHARS = 2_000_000
MAX_LINE_CHARS = 4096
ADAPTER_VERSION = "pdf-lines-pilot-1"


class PDFLineError(ValueError):
    """Redacted extraction failure with an optional page and line."""

    def __init__(self, code: str, page: int | None = None, line: int | None = None):
        self.code = code
        self.page = page
        self.line = line
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PageLine:
    line_id: str
    page: int
    line: int
    raw: str
    normalized: str


@dataclass(frozen=True, slots=True)
class PDFLineEvidence:
    source_sha256: str
    adapter_version: str
    extraction_library: str
    page_count: int
    lines: tuple[PageLine, ...]


def page_lines(
    source_bytes: bytes,
    extracted_pages: Iterable[str],
    *,
    extraction_library: str,
    cancelled: Callable[[], bool] | None = None,
) -> PDFLineEvidence:
    """Retain page/line locations after a trusted PDF decoder has produced text."""
    if not source_bytes or len(source_bytes) > MAX_PDF_BYTES:
        raise PDFLineError("source_size")
    if not extraction_library or len(extraction_library) > 80:
        raise PDFLineError("extraction_library")
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    result = []
    total_chars = 0
    page_count = 0
    for page_number, page_text in enumerate(extracted_pages, 1):
        if cancelled is not None and cancelled():
            raise PDFLineError("cancelled", page_number)
        if page_number > MAX_PAGES:
            raise PDFLineError("page_limit", page_number)
        if not isinstance(page_text, str):
            raise PDFLineError("page_text_type", page_number)
        total_chars += len(page_text)
        if total_chars > MAX_TEXT_CHARS:
            raise PDFLineError("text_limit", page_number)
        page_count = page_number
        for line_number, raw in enumerate(page_text.splitlines(), 1):
            if cancelled is not None and cancelled():
                raise PDFLineError("cancelled", page_number, line_number)
            if len(result) >= MAX_LINES or len(raw) > MAX_LINE_CHARS:
                raise PDFLineError("line_limit", page_number, line_number)
            line_id = hashlib.sha256(
                f"{source_hash}:{ADAPTER_VERSION}:{extraction_library}:{page_number}:{line_number}".encode()
            ).hexdigest()
            result.append(PageLine(line_id, page_number, line_number, raw, " ".join(raw.split())))
    if page_count == 0:
        raise PDFLineError("no_pages")
    return PDFLineEvidence(source_hash, ADAPTER_VERSION, extraction_library, page_count, tuple(result))

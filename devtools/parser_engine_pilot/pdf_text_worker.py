"""Private subprocess entry point for bounded, read-only PDF text extraction."""

from __future__ import annotations

import json
import sys
from io import BytesIO

from devtools.parser_engine_pilot.worker_limits import enforce_child_memory_limit

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_PAGES = 100
MAX_PAGE_TEXT_BYTES = 512 * 1024
MAX_TEXT_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_LINES_PER_PAGE = 10_000
MAX_TOTAL_LINES = 50_000


def extract(source: bytes) -> tuple[str, ...]:
    import pdfplumber

    if not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError("source_size")
    pages = []
    total = 0
    total_lines = 0
    with pdfplumber.open(BytesIO(source)) as pdf:
        if not 1 <= len(pdf.pages) <= MAX_PAGES:
            raise ValueError("page_limit")
        for page in pdf.pages:
            value = page.extract_text_simple() or ""
            size = len(value.encode("utf-8"))
            total += size
            lines = len(value.splitlines())
            total_lines += lines
            if (
                size > MAX_PAGE_TEXT_BYTES
                or total > MAX_TEXT_BYTES
                or lines > MAX_LINES_PER_PAGE
                or total_lines > MAX_TOTAL_LINES
            ):
                raise ValueError("text_limit")
            pages.append(value)
    return tuple(pages)


def main() -> int:
    try:
        enforce_child_memory_limit(sys.argv[1])
        source = sys.stdin.buffer.read(MAX_SOURCE_BYTES + 1)
        pages = extract(source)
        payload = json.dumps({"pages": pages}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_OUTPUT_BYTES:
            raise ValueError("output_limit")
    except Exception:
        # Errors and tracebacks can contain document text; the parent gets only a code.
        return 1
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

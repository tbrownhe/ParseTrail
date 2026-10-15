"""Private subprocess entry point for bounded, read-only PDF text extraction."""

from __future__ import annotations

import json
import sys
from io import BytesIO
from typing import Literal

from devtools.parser_engine_pilot.worker_limits import enforce_child_memory_limit

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_PAGES = 100
MAX_PAGE_TEXT_BYTES = 512 * 1024
MAX_TEXT_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_LINES_PER_PAGE = 10_000
MAX_TOTAL_LINES = 50_000
MAX_METADATA_KEYS = 32
MAX_METADATA_KEY_CHARS = 128
MAX_METADATA_VALUE_CHARS = 1024


def extract(
    source: bytes, *, layout: Literal["simple", "fixed", "default"] = "simple"
) -> tuple[tuple[str, ...], dict[str, str]]:
    import pdfplumber

    if not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError("source_size")
    pages = []
    total = 0
    total_lines = 0
    with pdfplumber.open(BytesIO(source)) as pdf:
        if not 1 <= len(pdf.pages) <= MAX_PAGES:
            raise ValueError("page_limit")
        raw_metadata = pdf.metadata or {}
        if len(raw_metadata) > MAX_METADATA_KEYS:
            raise ValueError("metadata_limit")
        metadata = {str(key): str(value) for key, value in raw_metadata.items() if value is not None}
        if any(
            not key or len(key) > MAX_METADATA_KEY_CHARS or len(value) > MAX_METADATA_VALUE_CHARS
            for key, value in metadata.items()
        ):
            raise ValueError("metadata_limit")
        for page in pdf.pages:
            if layout == "fixed":
                value = page.extract_text(layout=True, x_tolerance=0.5, y_tolerance=0.5) or ""
            elif layout == "default":
                value = page.extract_text(layout=True) or ""
            else:
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
    return tuple(pages), metadata


def main(*, layout: Literal["simple", "fixed", "default"] = "simple") -> int:
    try:
        enforce_child_memory_limit(sys.argv[1])
        source = sys.stdin.buffer.read(MAX_SOURCE_BYTES + 1)
        pages, metadata = extract(source, layout=layout)
        payload = json.dumps({"pages": pages, "metadata": metadata}, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(payload) > MAX_OUTPUT_BYTES:
            raise ValueError("output_limit")
    except Exception:
        # Errors and tracebacks can contain document text; the parent gets only a code.
        return 1
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

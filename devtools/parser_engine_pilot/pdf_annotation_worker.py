"""Bounded first-page PDF date annotation decoder for OCCU bank statements."""

from __future__ import annotations

import json
import re
import sys
from io import BytesIO

from parsetrail.core.v2_worker_limits import enforce_child_memory_limit

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_ANNOTATIONS = 1000
MAX_OUTPUT_BYTES = 4096
DATE = re.compile(rb"\d{2}/\d{2}/\d{2}\Z")


def extract(source: bytes) -> tuple[dict[str, str | int], ...]:
    import pdfplumber

    if not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError("source_size")
    with pdfplumber.open(BytesIO(source)) as pdf:
        if not 1 <= len(pdf.pages) <= 100:
            raise ValueError("page_limit")
        annotations = pdf.pages[0].annots or []
        if len(annotations) > MAX_ANNOTATIONS:
            raise ValueError("annotation_limit")
        dates = []
        for ordinal, annotation in enumerate(annotations, 1):
            title = annotation.get("title")
            if not isinstance(title, str):
                continue
            field = next((field for field in ("FROM_DATE", "TO_DATE") if title.startswith(field)), None)
            if field is None:
                continue
            raw = annotation.get("data", {}).get("V")
            if not isinstance(raw, bytes) or DATE.fullmatch(raw) is None or len(title) > 128:
                raise ValueError("invalid_date_annotation")
            dates.append({"field": field, "title": title, "raw": raw.decode("ascii"), "ordinal": ordinal})
        return tuple(dates)


def main() -> int:
    try:
        enforce_child_memory_limit(sys.argv[1])
        source = sys.stdin.buffer.read(MAX_SOURCE_BYTES + 1)
        output = json.dumps({"dates": extract(source)}, separators=(",", ":")).encode("utf-8")
        if len(output) > MAX_OUTPUT_BYTES:
            raise ValueError("output_limit")
    except Exception:
        return 1
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

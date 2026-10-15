"""Private bounded worker for declared PDF header-anchor table geometry."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from io import BytesIO

from devtools.parser_engine_pilot.worker_limits import MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, enforce_child_memory_limit


def main() -> int:
    try:
        enforce_child_memory_limit(sys.argv[1])
        payload = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(payload) < 5 or len(payload) > MAX_INPUT_BYTES:
            return 1
        size = int.from_bytes(payload[:4], "big")
        if not 0 < size <= 64 * 1024 or size + 4 >= len(payload):
            return 1
        definition, source = payload[4 : 4 + size], payload[4 + size :]
        import pdfplumber

        from devtools.parser_engine_pilot.anchored_table import extract_anchored_table

        with pdfplumber.open(BytesIO(source)) as pdf:
            evidence = extract_anchored_table(
                definition, source, pdf.pages, extraction_library=f"pdfplumber-{pdfplumber.__version__}-anchored-table"
            )
        output = json.dumps(asdict(evidence), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(output) > MAX_OUTPUT_BYTES:
            return 1
    except Exception:
        return 1
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Private subprocess entry point for recent Citi word/table extraction."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from io import BytesIO

from devtools.parser_engine_pilot.worker_limits import (
    MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES,
    enforce_child_memory_limit,
)


def main() -> int:
    try:
        enforce_child_memory_limit(sys.argv[1])
        source = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if not source or len(source) > MAX_INPUT_BYTES:
            return 1
        import pdfplumber

        from devtools.parser_engine_pilot.citi_table import extract_citi_table

        with pdfplumber.open(BytesIO(source)) as pdf:
            evidence = extract_citi_table(
                source,
                pdf.pages,
                extraction_library=f"pdfplumber-{pdfplumber.__version__}-words-table",
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

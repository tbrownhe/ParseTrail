"""Private subprocess entry point for bounded Wells table-region extraction."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from io import BytesIO

from parsetrail.core.v2_worker_limits import (
    MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES,
    enforce_child_memory_limit,
)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 1:
            raise ValueError("worker_arguments")
        enforce_child_memory_limit(args[0])
        data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(data) < 5 or len(data) > MAX_INPUT_BYTES:
            return 1
        definition_size = int.from_bytes(data[:4], "big")
        if not 0 < definition_size <= 64 * 1024 or 4 + definition_size >= len(data):
            return 1
        definition = data[4 : 4 + definition_size]
        source = data[4 + definition_size :]
        import pdfplumber

        from parsetrail.core.v2_wells_table import extract_table_rows

        with pdfplumber.open(BytesIO(source)) as pdf:
            evidence = extract_table_rows(
                definition,
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

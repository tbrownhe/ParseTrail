"""Private resource-limited subprocess entry point for XLSX evidence decoding."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

from devtools.parser_engine_pilot.worker_limits import (
    MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES,
    enforce_child_memory_limit,
)


def main() -> int:
    try:
        enforce_child_memory_limit(sys.argv[1])
        data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(data) < 6 or len(data) > MAX_INPUT_BYTES:
            return 1
        definition_size = int.from_bytes(data[:4], "big")
        sheet_size = int.from_bytes(data[4:6], "big")
        if not 0 < definition_size <= 64 * 1024 or not 0 < sheet_size <= 124:
            return 1
        boundary = 6 + definition_size + sheet_size
        if boundary >= len(data):
            return 1
        definition = data[6 : 6 + definition_size]
        sheet = data[6 + definition_size : boundary].decode("utf-8")
        source = data[boundary:]
        from devtools.parser_engine_pilot.xlsx_adapter import parse_xlsx

        evidence = parse_xlsx(definition, source, sheet=sheet)
        output = json.dumps(asdict(evidence), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(output) > MAX_OUTPUT_BYTES:
            return 1
    except Exception:
        return 1
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

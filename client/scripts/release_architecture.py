"""Inspect frozen executable architecture without executing it or importing packages."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

TARGETS = ("windows-x86_64", "macos-x86_64")


def verify_binary(path: Path, target: str) -> dict[str, str]:
    """Require a PE32+ AMD64 executable or a thin Intel 64-bit Mach-O executable."""
    if target not in TARGETS:
        raise ValueError("Unsupported executable target")
    with path.open("rb") as stream:
        header = stream.read(64)
        if target == "windows-x86_64":
            if len(header) != 64 or header[:2] != b"MZ":
                raise ValueError("Expected a Windows PE executable")
            offset = struct.unpack_from("<I", header, 60)[0]
            if offset < 64 or offset > path.stat().st_size - 26:
                raise ValueError("Invalid Windows PE header offset")
            stream.seek(offset)
            pe = stream.read(26)
            if pe[:4] != b"PE\0\0" or struct.unpack_from("<H", pe, 4)[0] != 0x8664:
                raise ValueError("Frozen Windows executable must target AMD64 (x86_64)")
            optional_size, flags, magic = struct.unpack_from("<HHH", pe, 20)
            if optional_size < 112 or magic != 0x20B or not flags & 0x0002 or flags & 0x2000:
                raise ValueError("Expected a PE32+ executable, not a DLL or 32-bit image")
            if offset + 24 + optional_size > path.stat().st_size:
                raise ValueError("Truncated Windows optional header")
            binary_format = "PE32+"
        else:
            byte_order = {b"\xcf\xfa\xed\xfe": "<", b"\xfe\xed\xfa\xcf": ">"}.get(header[:4])
            if byte_order is None or len(header) < 32:
                raise ValueError("Expected a thin 64-bit Mach-O executable; universal/ARM releases are deferred")
            cpu_type, _subtype, file_type, commands, command_bytes = struct.unpack_from(byte_order + "IIIII", header, 4)
            if cpu_type != 0x01000007 or file_type != 2:
                raise ValueError("Frozen Mac executable must be an Intel x86_64 executable")
            if not commands or command_bytes < commands * 8 or 32 + command_bytes > path.stat().st_size:
                raise ValueError("Truncated or invalid Mach-O load-command region")
            binary_format = "Mach-O 64-bit"
    return {"target_platform": target, "architecture": "x86_64", "format": binary_format}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=TARGETS, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify_binary(args.binary, args.platform), sort_keys=True))
        return 0
    except (OSError, ValueError, struct.error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

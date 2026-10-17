"""Exercise bounded parser worker pipes in the built windowed executable."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from parsetrail.core.runtime_smoke import _sample_pdf


def check_frozen_workers(binary: Path) -> None:
    for mode, expected in (
        ("simple", {"pages": ["ParseTrail smoke"], "metadata": {}}),
        ("annotation-period", {"dates": []}),
    ):
        process = subprocess.run(
            [str(binary), "--v2-parser-worker", mode, str(512 * 1024 * 1024)],
            input=_sample_pdf(),
            capture_output=True,
            timeout=30,
            check=False,
        )
        if process.returncode != 0 or process.stderr or json.loads(process.stdout) != expected:
            raise RuntimeError(f"Frozen {mode} worker smoke failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    check_frozen_workers(args.binary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

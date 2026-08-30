"""Select a devtool environment file before settings-dependent imports."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path


def preselect_environment_file(argv: Sequence[str]) -> Path | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-file", type=Path)
    arguments, _remainder = parser.parse_known_args(argv)
    if arguments.env_file is None:
        return None
    selected = arguments.env_file.expanduser().resolve()
    if not selected.is_file():
        raise FileNotFoundError(f"Configured environment file does not exist: {selected}")
    os.environ["PARSETRAIL_ENV_FILE"] = str(selected)
    return selected

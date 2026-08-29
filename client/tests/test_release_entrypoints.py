"""Regression tests for the package-aware release command entry points."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    (
        "scripts.client_release",
        "scripts.immutable_publish",
        "scripts.plugin_release",
        "scripts.release",
        "scripts.release_inventory",
        "scripts.release_source",
    ),
)
def test_release_module_entrypoint_imports(module: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr

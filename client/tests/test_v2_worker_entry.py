"""Installed-entry shape for the first packaged 2.0 decoder worker."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from parsetrail.core.runtime_smoke import _sample_pdf
from parsetrail.core.v2_worker_limits import WorkerError, _worker_launch


def test_pdf_text_worker_entry_runs_without_gui_bootstrap() -> None:
    process = subprocess.run(
        [sys.executable, "-m", "parsetrail.main", "--v2-parser-worker", "simple", str(512 * 1024 * 1024)],
        input=_sample_pdf(),
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert process.returncode == 0
    assert json.loads(process.stdout)["pages"] == ["ParseTrail smoke"]
    assert process.stderr == b""


def test_pdf_annotation_worker_entry_runs_without_gui_bootstrap() -> None:
    process = subprocess.run(
        [sys.executable, "-m", "parsetrail.main", "--v2-parser-worker", "annotation-period", str(512 * 1024 * 1024)],
        input=_sample_pdf(),
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert process.returncode == 0
    assert json.loads(process.stdout) == {"dates": []}
    assert process.stderr == b""


def test_frozen_launch_uses_app_entry_and_refuses_pilot_only_workers() -> None:
    source_command, source_cwd = _worker_launch("pdf_text_fixed", 512 * 1024 * 1024, frozen=False, executable="python")
    frozen_command, frozen_cwd = _worker_launch("pdf_text_fixed", 512 * 1024 * 1024, frozen=True, executable="app.exe")
    assert source_command == ["python", "-m", "parsetrail.core.v2_pdf_text_worker", "fixed", "536870912"]
    assert frozen_command == ["app.exe", "--v2-parser-worker", "fixed", "536870912"]
    assert source_cwd is None and frozen_cwd is None
    annotation_command, annotation_cwd = _worker_launch(
        "pdf_annotation_period", 512 * 1024 * 1024, frozen=True, executable="app.exe"
    )
    assert annotation_command == ["app.exe", "--v2-parser-worker", "annotation-period", "536870912"]
    assert annotation_cwd is None
    with pytest.raises(WorkerError, match="unsupported_worker"):
        _worker_launch("devtools.parser_engine_pilot.citi_worker", 512 * 1024 * 1024, frozen=True, executable="app.exe")

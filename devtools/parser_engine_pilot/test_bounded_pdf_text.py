"""Exercise the subprocess boundary with synthetic bytes and native limits."""

from __future__ import annotations

import subprocess
import sys

import pytest
from parsetrail.core.runtime_smoke import _sample_pdf

from devtools.parser_engine_pilot.bounded_pdf_text import (
    DecodeLimits,
    DecoderError,
    _WindowsJob,
    decode_text,
)


def test_decodes_synthetic_pdf_in_bounded_worker() -> None:
    assert decode_text(_sample_pdf()) == ("ParseTrail smoke",)


def test_refuses_oversized_or_invalid_pdf_without_source_in_error() -> None:
    with pytest.raises(DecoderError, match="source_size"):
        decode_text(b"")
    with pytest.raises(DecoderError, match="worker_failed") as error:
        decode_text(b"private statement text")
    assert "private" not in str(error.value)


def test_deadline_terminates_worker() -> None:
    with pytest.raises(DecoderError, match="timeout"):
        decode_text(_sample_pdf(), DecodeLimits(wall_seconds=0.01))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object check")
def test_windows_job_enforces_committed_memory_limit() -> None:
    job = _WindowsJob(128 * 1024 * 1024)
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdin.buffer.read(1); value = bytearray(192 * 1024 * 1024); print('allocated')",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        job.attach(process.pid)
        output, _ = process.communicate(input=b"x", timeout=10)
        assert process.returncode != 0
        assert b"allocated" not in output
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        job.close()

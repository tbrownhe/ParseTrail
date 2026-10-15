"""Exercise the subprocess boundary with synthetic bytes and native limits."""

from __future__ import annotations

import subprocess
import sys

import pytest
from parsetrail.core.runtime_smoke import _sample_pdf

from devtools.parser_engine_pilot.bounded_pdf_text import decode_pdf, decode_pdf_layout
from devtools.parser_engine_pilot.worker_limits import WorkerError, WorkerLimits, _WindowsJob


def test_decodes_synthetic_pdf_in_bounded_worker() -> None:
    assert decode_pdf(_sample_pdf()).pages == ("ParseTrail smoke",)
    assert any("ParseTrail smoke" in page for page in decode_pdf_layout(_sample_pdf()).pages)


def test_retains_pdf_author_for_bounded_layout_routing() -> None:
    stream = b"BT /F1 12 Tf 20 40 Td (ParseTrail smoke) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Author (Citi Test) >>",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    decoded = decode_pdf(bytes(document))
    assert decoded.pages == ("ParseTrail smoke",)
    assert ("Author", "Citi Test") in decoded.metadata


def test_refuses_oversized_or_invalid_pdf_without_source_in_error() -> None:
    with pytest.raises(WorkerError, match="source_size"):
        decode_pdf(b"")
    with pytest.raises(WorkerError, match="worker_failed") as error:
        decode_pdf(b"private statement text")
    assert "private" not in str(error.value)
    with pytest.raises(WorkerError, match="worker_failed") as layout_error:
        decode_pdf_layout(b"private statement text")
    assert "private" not in str(layout_error.value)


def test_deadline_terminates_worker() -> None:
    with pytest.raises(WorkerError, match="timeout"):
        decode_pdf(_sample_pdf(), WorkerLimits(wall_seconds=0.01))


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

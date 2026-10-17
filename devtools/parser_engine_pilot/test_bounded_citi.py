"""Recent Citi raw table cells through the OS-limited worker."""

from __future__ import annotations

from dataclasses import asdict
from io import BytesIO

import pdfplumber
import pytest
from parsetrail.core.v2_worker_limits import WorkerError

from devtools.parser_engine_pilot.bounded_citi import extract_bounded_citi
from devtools.parser_engine_pilot.citi_table import extract_citi_table


def sample_table_pdf() -> bytes:
    words = [
        (20, 370, "Sale"),
        (80, 370, "Post"),
        (140, 370, "Description"),
        (320, 370, "Amount"),
        (20, 320, "01/02"),
        (80, 320, "01/03"),
        (140, 320, "SAMPLE"),
        (320, 320, "$10.00"),
    ]
    commands = [f"BT /F1 10 Tf {x} {y} Td ({value}) Tj ET" for x, y, value in words]
    commands.extend(f"15 {y} m 370 {y} l S" for y in (340, 300))
    stream = "\n".join(commands).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 400] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
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
    document.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(document)


def test_worker_matches_in_process_cells_and_regions() -> None:
    source = sample_table_pdf()
    bounded = extract_bounded_citi(source)
    with pdfplumber.open(BytesIO(source)) as pdf:
        direct = extract_citi_table(
            source, pdf.pages, extraction_library=f"pdfplumber-{pdfplumber.__version__}-words-table"
        )
    assert asdict(bounded) == asdict(direct)
    assert len(bounded.rows) == 1
    assert bounded.rows[0].raw_cells == ("01/02", "01/03", "SAMPLE", "$10.00")
    assert bounded.rows[0].region is not None
    assert bounded.coverage_verified is False


def test_worker_refuses_invalid_source_without_echoing_it() -> None:
    with pytest.raises(WorkerError, match="source_size"):
        extract_bounded_citi(b"")
    with pytest.raises(WorkerError, match="worker_failed") as error:
        extract_bounded_citi(b"private statement text")
    assert "private" not in str(error.value)

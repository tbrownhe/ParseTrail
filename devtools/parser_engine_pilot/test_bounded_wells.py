"""Synthetic PDF word/table extraction through the OS-limited worker."""

from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
from pathlib import Path

import pdfplumber
import pytest

from devtools.parser_engine_pilot.bounded_wells import extract_bounded_wells
from devtools.parser_engine_pilot.wells_table import extract_table_rows
from devtools.parser_engine_pilot.worker_limits import WorkerError

DEFINITION = Path(__file__).with_name("wells-table-pilot-definition.json")


def sample_table_pdf() -> bytes:
    words = [
        (20, 380, "Date"),
        (70, 380, "Description"),
        (170, 380, "Credits"),
        (230, 380, "Debits"),
        (290, 380, "balance"),
        (20, 350, "1/1"),
        (70, 350, "Printed"),
        (170, 350, "$1.00"),
        (290, 350, "$101.00"),
    ]
    stream = "\n".join(f"BT /F1 12 Tf {x} {y} Td ({value}) Tj ET" for x, y, value in words).encode()
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


def test_worker_matches_in_process_word_and_table_evidence() -> None:
    source = sample_table_pdf()
    definition = DEFINITION.read_bytes()
    bounded = extract_bounded_wells(definition, source)
    with pdfplumber.open(BytesIO(source)) as pdf:
        direct = extract_table_rows(
            definition, source, pdf.pages, extraction_library=f"pdfplumber-{pdfplumber.__version__}-words-table"
        )
    assert asdict(bounded) == asdict(direct)
    assert bounded.rows[0].disposition == "dated_candidate"
    assert bounded.coverage_verified is False


def test_worker_refuses_invalid_source_without_echoing_it() -> None:
    with pytest.raises(WorkerError, match="source_size"):
        extract_bounded_wells(DEFINITION.read_bytes(), b"")
    with pytest.raises(WorkerError, match="worker_failed") as error:
        extract_bounded_wells(DEFINITION.read_bytes(), b"private statement text")
    assert "private" not in str(error.value)

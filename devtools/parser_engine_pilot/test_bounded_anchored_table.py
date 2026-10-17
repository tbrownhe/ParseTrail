"""Declared table geometry agrees inside and outside the bounded worker."""

from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
from pathlib import Path

import pdfplumber
import pytest
from parsetrail.core.v2_anchored_table import (
    AnchoredTableError,
    _selected_header,
    extract_anchored_table,
    load_definition,
)
from parsetrail.core.v2_worker_limits import WorkerError

from devtools.parser_engine_pilot.bounded_anchored_table import extract_bounded_anchored_table

DEFINITION = Path(__file__).with_name("middle-citi-table-pilot-definition.json").read_bytes()
WELLS_DEFINITION = Path(__file__).with_name("wells-personal-table-pilot-definition.json").read_bytes()


def sample_table_pdf() -> bytes:
    words = [
        (20, 380, "Trans."),
        (80, 380, "Post"),
        (140, 380, "Description"),
        (300, 380, "Amount"),
        (20, 350, "01/05"),
        (80, 350, "01/05"),
        (140, 350, "Payment"),
        (300, 350, "-$20.00"),
        (20, 330, "01/10"),
        (80, 330, "01/09"),
        (140, 330, "Purchase"),
        (300, 330, "$10.00"),
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


def test_bounded_declared_geometry_matches_in_process() -> None:
    source = sample_table_pdf()
    bounded = extract_bounded_anchored_table(DEFINITION, source)
    with pdfplumber.open(BytesIO(source)) as pdf:
        direct = extract_anchored_table(
            DEFINITION,
            source,
            pdf.pages,
            extraction_library=f"pdfplumber-{pdfplumber.__version__}-anchored-table",
        )
    assert asdict(bounded) == asdict(direct)
    assert bounded.pages[0].status == "table"
    assert any(row.raw_cells[2] == "Payment" for row in bounded.rows)
    assert bounded.coverage_verified is False


def test_invalid_source_refuses_without_echoing_content() -> None:
    with pytest.raises(WorkerError, match="source_size"):
        extract_bounded_anchored_table(DEFINITION, b"")
    with pytest.raises(WorkerError, match="worker_failed") as error:
        extract_bounded_anchored_table(DEFINITION, b"private statement")
    assert "private" not in str(error.value)


def test_header_line_ignores_repeated_balance_words_but_refuses_two_complete_headers() -> None:
    definition, _ = load_definition(WELLS_DEFINITION)

    class Page:
        def __init__(self, duplicate_header: bool):
            self.duplicate_header = duplicate_header

        def extract_words(self):
            result = []
            for y in (100.0, 300.0) if self.duplicate_header else (100.0,):
                result.extend(
                    {"text": label, "x0": float(index * 30), "x1": float(index * 30 + 20), "top": y - 10, "bottom": y}
                    for index, label in enumerate(definition.headers)
                )
            result.append({"text": "balance", "x0": 20.0, "x1": 40.0, "top": 490.0, "bottom": 500.0})
            return result

    assert _selected_header(Page(False), definition) is not None
    with pytest.raises(AnchoredTableError, match="ambiguous_header_line"):
        _selected_header(Page(True), definition)

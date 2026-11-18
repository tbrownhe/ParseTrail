"""Synthetic PDF word/table extraction through the OS-limited worker."""

from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
from pathlib import Path

import pdfplumber
import pytest
from parsetrail.core.v2_bounded_wells import extract_bounded_wells
from parsetrail.core.v2_wells_table import extract_table_rows
from parsetrail.core.v2_worker_limits import WorkerError

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


def test_actual_bounded_footer_preserves_unknowns_product_and_cancelled_input():
    from parsetrail.core.v2_source_pipeline import SourcePipelineError, build_source_evidence

    from devtools.parser_engine_pilot.synthetic_family_sources import pdf_document, table_page, text_page

    source = pdf_document(
        (
            text_page(
                "Initiate Business Checking SM",
                "Wells Fargo",
                "October 31, 2026 Page 1 of 1",
                "Statement period activity summary Account number: 1234567890",
                "Beginning balance on 10/1 $100.00",
                "Ending balance on 10/31 $101.00",
                *("Printed service information" for _ in range(10)),
            ),
            table_page(
                ("Date", "Description", "Credits", "Debits", "balance"),
                (("10/1", "Printed", "$1.00", "", "$101.00"),),
                (20, 100, 400, 600, 800),
            )
            + (
                (20, 640, "Ending balance on 10/31"),
                (800, 640, "$101.00"),
                (20, 620, "Totals"),
                (400, 620, "$1.00"),
                (600, 620, "$0.00"),
                (100, 600, "Unknown adjustment $7.00"),
            ),
        )
    )
    output = build_source_evidence(source, DEFINITION.read_bytes(), suffix=".pdf")
    assert len(output.payload.accounts[0].rows) == 1
    assert len([d for d in output.payload.dispositions if d.code == "wells_statement_summary"]) == 2
    assert len([d for d in output.payload.dispositions if d.code == "wells_account_product"]) == 1
    unknown = [d for d in output.payload.dispositions if d.code == "unresolved_after_stop"]
    assert len(unknown) == 1 and "$7.00" in "".join(unknown[0].raw_values)
    assert not output.payload.capture_verified
    with pytest.raises(SourcePipelineError, match="cancelled"):
        build_source_evidence(source, DEFINITION.read_bytes(), suffix=".pdf", cancelled=lambda: True)
    with pytest.raises(SourcePipelineError):
        build_source_evidence(source[:90], DEFINITION.read_bytes(), suffix=".pdf")

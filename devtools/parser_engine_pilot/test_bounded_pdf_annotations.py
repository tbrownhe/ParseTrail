"""The OCCU period fallback keeps exact first-page annotation locations."""

from __future__ import annotations

import pytest
from parsetrail.core.source_evidence import PdfAnnotation

from devtools.parser_engine_pilot.bounded_pdf_annotations import decode_pdf_period_annotations
from devtools.parser_engine_pilot.worker_limits import WorkerError, WorkerLimits


def sample_pdf(values: tuple[tuple[str, str], ...]) -> bytes:
    annotations = []
    for field, value in values:
        annotations.append(
            f"<< /Type /Annot /Subtype /Widget /Rect [10 10 60 20] /T ({field}) /V ({value}) >>".encode()
        )
    contents = 4 + len(annotations)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Annots ["
            + b" ".join(f"{i} 0 R".encode() for i in range(4, contents))
            + f"] /Contents {contents} 0 R >>".encode()
        ),
        *annotations,
        b"<< /Length 0 >>\nstream\n\nendstream",
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


def test_bounded_annotation_dates_and_locations() -> None:
    source = sample_pdf((("FROM_DATE", "01/01/26"), ("TO_DATE", "01/31/26")))
    fields = decode_pdf_period_annotations(source)
    assert [(item.field, item.raw, item.ordinal) for item in fields] == [
        ("FROM_DATE", "01/01/26", 1),
        ("TO_DATE", "01/31/26", 2),
    ]
    assert PdfAnnotation(kind="pdf_annotation", page=1, ordinal=fields[0].ordinal)


def test_missing_duplicate_or_invalid_annotations_refuse() -> None:
    with pytest.raises(WorkerError, match="incomplete_date_annotations"):
        decode_pdf_period_annotations(sample_pdf((("FROM_DATE", "01/01/26"),)))
    with pytest.raises(WorkerError, match="incomplete_date_annotations"):
        decode_pdf_period_annotations(
            sample_pdf((("FROM_DATE", "01/01/26"), ("FROM_DATE_COPY", "01/02/26"), ("TO_DATE", "01/31/26")))
        )
    with pytest.raises(WorkerError, match="worker_failed"):
        decode_pdf_period_annotations(sample_pdf((("FROM_DATE", "private"), ("TO_DATE", "01/31/26"))))


def test_annotation_worker_deadline() -> None:
    with pytest.raises(WorkerError, match="timeout"):
        decode_pdf_period_annotations(
            sample_pdf((("FROM_DATE", "01/01/26"), ("TO_DATE", "01/31/26"))),
            WorkerLimits(wall_seconds=0.01),
        )

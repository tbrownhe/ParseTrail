"""Strict parent-side validation for the isolated PDF annotation decoder."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from devtools.parser_engine_pilot.pdf_annotation_worker import MAX_OUTPUT_BYTES, MAX_SOURCE_BYTES
from devtools.parser_engine_pilot.worker_limits import WorkerError, WorkerLimits, run_worker

DATE = re.compile(r"\d{2}/\d{2}/\d{2}\Z")


@dataclass(frozen=True, slots=True)
class PDFPeriodAnnotation:
    field: str
    title: str
    raw: str
    ordinal: int


def decode_pdf_period_annotations(
    source: bytes, limits: WorkerLimits = WorkerLimits()
) -> tuple[PDFPeriodAnnotation, PDFPeriodAnnotation]:
    """Return two first-page date fields, or refuse incomplete annotation evidence."""
    if type(source) is not bytes or not source or len(source) > MAX_SOURCE_BYTES:
        raise WorkerError("source_size")
    output = run_worker(
        "devtools.parser_engine_pilot.pdf_annotation_worker",
        source,
        output_limit=MAX_OUTPUT_BYTES,
        limits=limits,
    )
    try:
        decoded = json.loads(output)
    except (ValueError, UnicodeDecodeError):
        raise WorkerError("invalid_output") from None
    if not isinstance(decoded, dict) or set(decoded) != {"dates"} or not isinstance(decoded["dates"], list):
        raise WorkerError("invalid_output")
    dates = decoded["dates"]
    if len(dates) != 2:
        raise WorkerError("incomplete_date_annotations")
    result = []
    for item in dates:
        if (
            not isinstance(item, dict)
            or set(item) != {"field", "title", "raw", "ordinal"}
            or not isinstance(item["field"], str)
            or item["field"] not in {"FROM_DATE", "TO_DATE"}
            or not isinstance(item["title"], str)
            or len(item["title"]) > 128
            or not item["title"].startswith(item["field"])
            or not isinstance(item["raw"], str)
            or DATE.fullmatch(item["raw"]) is None
            or type(item["ordinal"]) is not int
            or not 1 <= item["ordinal"] <= 1000
        ):
            raise WorkerError("invalid_output")
        result.append(PDFPeriodAnnotation(**item))
    if {item.field for item in result} != {"FROM_DATE", "TO_DATE"} or result[0].ordinal == result[1].ordinal:
        raise WorkerError("invalid_output")
    return tuple(sorted(result, key=lambda item: item.field))

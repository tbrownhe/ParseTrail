"""Retain extracted PDF text lines not already located by parser evidence."""

from __future__ import annotations

from collections.abc import Iterable

from parsetrail.core.source_evidence import PdfLine, SourceDisposition, SourceLocation


class PDFLineInventoryError(ValueError):
    """A parser location cannot be reconciled with its extracted text pages."""


def unlocated_text_lines(
    pages: tuple[str, ...], locations: Iterable[SourceLocation], *, code: str
) -> tuple[SourceDisposition, ...]:
    """Return exact nonblank text lines lacking any PDF line location."""
    lines = tuple(tuple(page.splitlines()) for page in pages)
    located: set[tuple[int, int]] = set()
    for location in locations:
        if not isinstance(location, PdfLine):
            continue
        last = location.end_line or location.line
        if location.page > len(lines) or last > len(lines[location.page - 1]):
            raise PDFLineInventoryError("pdf_line_location_out_of_range")
        located.update((location.page, number) for number in range(location.line, last + 1))
    return tuple(
        SourceDisposition(
            code=code,
            location=PdfLine(kind="pdf_line", page=page, line=number),
            raw_values=(raw,),
        )
        for page, page_lines in enumerate(lines, 1)
        for number, raw in enumerate(page_lines, 1)
        if raw.strip() and (page, number) not in located
    )

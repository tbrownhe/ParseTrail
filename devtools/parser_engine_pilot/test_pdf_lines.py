"""Synthetic PDF line-location and resource-bound cases."""

from __future__ import annotations

import hashlib

import pytest
from parsetrail.core import v2_pdf_lines as pdf_lines
from parsetrail.core.v2_pdf_lines import PDFLineError, page_lines


def test_page_locations_keep_raw_text_and_replay_provenance() -> None:
    source = b"%PDF-synthetic"
    pages = [
        "BeginningBalance $10.00\n01/01/2026 Cash 1.00 11.00",
        "\n01/02/2026 Cash -1.00 10.00\nEndingBalance $10.00",
    ]
    evidence = page_lines(source, pages, extraction_library="synthetic-decoder-1")
    assert evidence.source_sha256 == hashlib.sha256(source).hexdigest()
    assert evidence.page_count == 2
    assert [(line.page, line.line) for line in evidence.lines] == [(1, 1), (1, 2), (2, 1), (2, 2), (2, 3)]
    assert evidence.lines[2].raw == "" and evidence.lines[2].normalized == ""
    assert evidence.lines[3].raw == "01/02/2026 Cash -1.00 10.00"
    assert len({line.line_id for line in evidence.lines}) == len(evidence.lines)
    revised = page_lines(source, pages, extraction_library="synthetic-decoder-2")
    assert revised.lines[0].line_id != evidence.lines[0].line_id


def test_cancellation_and_unbounded_text_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = 0

    def cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(PDFLineError) as exc:
        page_lines(b"%PDF", ["first\nsecond", "third"], extraction_library="synthetic", cancelled=cancel)
    assert (exc.value.code, exc.value.page, exc.value.line) == ("cancelled", 1, 2)
    monkeypatch.setattr(pdf_lines, "MAX_TEXT_CHARS", 6)
    with pytest.raises(PDFLineError, match="text_limit"):
        page_lines(b"%PDF", ["1234567"], extraction_library="synthetic")
    monkeypatch.setattr(pdf_lines, "MAX_TEXT_CHARS", 2_000_000)
    monkeypatch.setattr(pdf_lines, "MAX_PAGES", 1)
    with pytest.raises(PDFLineError, match="page_limit"):
        page_lines(b"%PDF", ["one", "two"], extraction_library="synthetic")
    with pytest.raises(PDFLineError, match="no_pages"):
        page_lines(b"%PDF", [], extraction_library="synthetic")

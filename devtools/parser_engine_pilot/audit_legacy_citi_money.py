"""Read-only aggregate audit of older Citi monetary-line provenance."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pdfplumber
from parsetrail.core.source_evidence import PdfLine
from parsetrail.core.v2_bounded_pdf_text import decode_pdf_default_layout
from parsetrail.core.v2_legacy_citi_lines import MONEY_TOKEN, parse_legacy_citi
from parsetrail.core.v2_pdf_lines import page_lines

DEFINITION = Path(__file__).with_name("legacy-citi-pilot-definition.json")


def _older_citi(path: Path) -> bool:
    with pdfplumber.open(path) as pdf:
        metadata = pdf.metadata or {}
        producer = str(metadata.get("Producer", "")).lower()
        first = (pdf.pages[0].extract_text() or "").lower()
    return "crawfordtech" not in producer and "www.citicards.com" in first


def _locations(location: PdfLine) -> set[tuple[int, int]]:
    return {(location.page, number) for number in range(location.line, (location.end_line or location.line) + 1)}


def audit(archive: Path) -> dict[str, object]:
    if not archive.is_dir():
        raise ValueError("archive_unavailable")
    definition = DEFINITION.read_bytes()
    totals: Counter[str] = Counter()
    disposition_codes: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    for path in sorted(archive.rglob("*.pdf")):
        try:
            if path.is_symlink() or not _older_citi(path):
                continue
            totals["selected_sources"] += 1
            before = path.stat()
            source = path.read_bytes()
            pages = decode_pdf_default_layout(source).pages
            lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-layout-default-v1")
            evidence = parse_legacy_citi(definition, lines)
            after = path.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise ValueError("source_changed")
            account = evidence.payload.accounts[0]
            totals["parsed_sources"] += 1
            totals["activity_rows"] += len(account.rows)
            totals["unclassified_monetary_lines"] += sum(
                item.code == "unclassified_monetary_line" for item in evidence.payload.dispositions
            )
            disposition_codes.update(item.code for item in evidence.payload.dispositions)
            covered = set()
            for location in (
                account.opening.locations
                + account.closing.locations
                + tuple(fragment.location for row in account.rows for fragment in row.fragments)
                + tuple(item.location for item in evidence.payload.dispositions)
            ):
                covered.update(_locations(location))
            for line in lines.lines:
                if MONEY_TOKEN.search(line.raw):
                    totals["money_lines"] += 1
                    totals["uncovered_money_lines"] += (line.page, line.line) not in covered
        except Exception as exc:
            failure_reasons[type(exc).__name__] += 1
    if not totals["selected_sources"]:
        failure_reasons["no_matching_sources"] += 1
    return {
        "counts": dict(sorted(totals.items())),
        "disposition_codes": dict(sorted(disposition_codes.items())),
        "failure_reasons": dict(sorted(failure_reasons.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    args = parser.parse_args(argv)
    report = audit(args.archive)
    print(json.dumps(report, sort_keys=True))
    return 1 if report["failure_reasons"] or report["counts"].get("uncovered_money_lines", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only recent-Citi simple-text line-location audit.

This measures whether extracted text lines have a line location in retained
evidence. It does not establish complete PDF-page capture or accounting review.
Only aggregate counts and redacted failure reasons are printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from parsetrail.core.source_evidence import PdfLine, SourceEvidence, StatementPayload
from parsetrail.core.v2_citi_evidence import CitiEvidence, read_recent_citi
from parsetrail.core.v2_citi_layout import AMOUNT, DATE_PREFIX
from parsetrail.core.v2_citi_source_output import from_citi
from parsetrail.core.v2_source_pipeline import MAX_SOURCE_BYTES

DEFINITION = Path(__file__).with_name("recent-citi-pilot-definition.json").read_bytes()


def _line_locations(output: SourceEvidence):
    payload = output.payload
    if not isinstance(payload, StatementPayload) or output.parser_id != "pdf_citicc_202511":
        raise ValueError("unexpected_source_evidence")
    for value in (payload.start, payload.end):
        yield from value.locations
    for account in payload.accounts:
        yield from account.identity_locations
        for value in (account.opening, account.closing):
            if value is not None:
                yield from value.locations
        for row in account.rows:
            for fragment in row.fragments:
                yield fragment.location
            for value in (row.date, row.transaction_date, row.description, row.amount, row.running_balance):
                if value is not None:
                    yield from value.locations
            for component in row.components:
                yield from component.amount.locations
    for disposition in payload.dispositions:
        yield disposition.location


def line_location_counts(source: CitiEvidence, output: SourceEvidence) -> dict[str, int]:
    """Count unlocated nonblank text lines without returning their contents."""
    lines = tuple(tuple(page.splitlines()) for page in source.simple_text_pages)
    located: set[tuple[int, int]] = set()
    for location in _line_locations(output):
        if not isinstance(location, PdfLine):
            continue
        if location.page > len(lines) or (location.end_line or location.line) > len(lines[location.page - 1]):
            raise ValueError("evidence_line_out_of_range")
        located.update((location.page, line) for line in range(location.line, (location.end_line or location.line) + 1))
    counts: Counter[str] = Counter()
    counts["pages"] = len(lines)
    counts["all_text_lines"] = sum(map(len, lines))
    for page, page_lines in enumerate(lines, 1):
        for number, raw in enumerate(page_lines, 1):
            if not raw.strip():
                continue
            counts["nonblank_text_lines"] += 1
            if (page, number) in located:
                counts["line_located"] += 1
                continue
            counts["without_line_location"] += 1
            money = AMOUNT.search(raw) is not None
            dated = DATE_PREFIX.match(raw) is not None
            counts["without_line_location_money"] += money
            counts["without_line_location_dated_start"] += dated
            counts["without_line_location_other"] += not money and not dated
    return dict(sorted(counts.items()))


def audit(sources: tuple[Path, ...]) -> dict[str, object]:
    if not sources:
        raise ValueError("no_sources")
    totals: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    for path in sources:
        try:
            if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".pdf":
                raise ValueError("source_unavailable")
            before = path.stat()
            if not 0 < before.st_size <= MAX_SOURCE_BYTES:
                raise ValueError("source_size")
            source = path.read_bytes()
            if len(source) != before.st_size:
                raise ValueError("source_changed")
            parsed = read_recent_citi(source, DEFINITION)
            output = from_citi(parsed, DEFINITION)
            if output.source_sha256 != hashlib.sha256(source).hexdigest():
                raise ValueError("source_hash_mismatch")
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("source_changed")
            if hashlib.sha256(path.read_bytes()).hexdigest() != output.source_sha256:
                raise ValueError("source_changed")
            totals.update(line_location_counts(parsed, output))
            totals["parsed_sources"] += 1
            totals["activity_rows"] += sum(len(account.rows) for account in output.payload.accounts)
            totals["unclassified_page_text_lines"] += sum(
                item.code == "unclassified_page_text" for item in output.payload.dispositions
            )
        except Exception as exc:
            reason = (
                str(exc)
                if type(exc) is ValueError
                and str(exc)
                in {
                    "source_unavailable",
                    "source_size",
                    "source_changed",
                    "source_hash_mismatch",
                    "evidence_line_out_of_range",
                    "unexpected_source_evidence",
                }
                else type(exc).__name__
            )
            failures[reason] += 1
    return {
        "counts": dict(sorted(totals.items())),
        "failure_count": sum(failures.values()),
        "failure_reasons": dict(sorted(failures.items())),
        "selected_sources": len(sources),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True, help="Recent Citi PDF; read-only")
    args = parser.parse_args(argv)
    report = audit(tuple(args.source))
    print(json.dumps(report, sort_keys=True))
    counts = report["counts"]
    return (
        1
        if report["failure_count"]
        or counts.get("without_line_location_money", 0)
        or counts.get("without_line_location_dated_start", 0)
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())

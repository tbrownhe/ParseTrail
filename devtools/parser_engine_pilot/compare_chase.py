"""Read-only Chase card-line pilot comparison with the accepted PDF parser."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pdfplumber
from loguru import logger
from parsetrail.core.money import to_minor_units
from parsetrail.core.utils import PDFReader
from parsetrail.core.v2_card_lines import DATED_PREFIX, parse_card_lines
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.plugins.pdf_chasecc_202602 import Parser

DEFINITION = Path(__file__).with_name("chase-card-pilot-definition.json")


def compare(source: bytes, definition: bytes) -> dict[str, bool]:
    logger.remove()
    with PDFReader(source, "in-memory.pdf") as reader:
        accepted = Parser().parse(reader)
        lines = page_lines(
            source, reader.pages_simple, extraction_library=f"pdfplumber-{pdfplumber.__version__}-simple"
        )
        pilot = parse_card_lines(definition, lines)
    account = accepted.accounts[0]
    expected_rows = [
        (str(row.transaction_date)[:10], str(row.posting_date)[:10], to_minor_units(row.amount), row.desc)
        for row in account.transactions
    ]
    observed_rows = [
        (
            row.transaction_date.normalized,
            row.posting_date.normalized,
            row.amount.normalized,
            row.description.normalized,
        )
        for row in pilot.rows
    ]
    dated_lines = sum(DATED_PREFIX.match(line.raw) is not None for line in lines.lines)
    return {
        "source_hash_equal": pilot.source_sha256 == hashlib.sha256(source).hexdigest(),
        "account_equal": pilot.account_identity.normalized == account.account_num,
        "period_equal": (pilot.period_start.normalized, pilot.period_end.normalized)
        == (str(accepted.start_date)[:10], str(accepted.end_date)[:10]),
        "printed_balances_equal": (pilot.opening_minor.normalized, pilot.closing_minor.normalized)
        == (to_minor_units(account.start_balance), to_minor_units(account.end_balance)),
        "rows_equal": observed_rows == expected_rows,
        "dated_lines_dispositioned": dated_lines == len(pilot.rows) + len(pilot.auxiliary_lines),
        "uncertainty_retained": pilot.coverage_verified is False and pilot.balance_reconciled is False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="A Chase card PDF; read-only")
    args = parser.parse_args()
    source = args.source.read_bytes()
    before = hashlib.sha256(source).hexdigest()
    try:
        result = compare(source, DEFINITION.read_bytes())
    except Exception as exc:
        print(json.dumps({"comparison_error_type": type(exc).__name__}))
        return 1
    result["file_unchanged"] = before == hashlib.sha256(args.source.read_bytes()).hexdigest()
    print(json.dumps(result, sort_keys=True))
    return 0 if all(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

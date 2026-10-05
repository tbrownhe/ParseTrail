"""Read-only Wells Fargo business table-region comparison with the accepted reader."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pdfplumber
from loguru import logger
from parsetrail.core.utils import PDFReader
from parsetrail.plugins.pdf_wfbankbus_202110 import Parser

from devtools.parser_engine_pilot.wells_table import extract_table_rows

DEFINITION = Path(__file__).with_name("wells-table-pilot-definition.json")


def compare(source: bytes, definition: bytes) -> dict[str, bool]:
    logger.remove()
    with PDFReader(source, "in-memory.pdf") as reader:
        accepted_parser = Parser()
        accepted = accepted_parser.parse(reader)
        expected = [tuple(cell or "" for cell in row) for row in accepted_parser.get_transaction_array()]
        pilot = extract_table_rows(
            definition, source, reader.PDF.pages, extraction_library=f"pdfplumber-{pdfplumber.__version__}-words-table"
        )
    retained = [
        row.raw_cells for row in pilot.rows if row.disposition in {"dated_candidate", "description_continuation"}
    ]
    dated = sum(row.disposition == "dated_candidate" for row in pilot.rows)
    return {
        "source_hash_equal": pilot.source_sha256 == hashlib.sha256(source).hexdigest(),
        "retained_cells_equal": retained == expected,
        "dated_candidate_count_equal": dated == sum(len(account.transactions) for account in accepted.accounts),
        "row_regions_present": all(
            row.region[0] < row.region[2] and row.region[1] < row.region[3] for row in pilot.rows
        ),
        "uncertainty_retained": pilot.coverage_verified is False and pilot.account_balance_reconciled is False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="A Wells Fargo business PDF; read-only")
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

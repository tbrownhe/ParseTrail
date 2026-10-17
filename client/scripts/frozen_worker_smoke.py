"""Exercise bounded parser worker pipes in the built windowed executable."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
from pathlib import Path

import openpyxl
from parsetrail.core.runtime_smoke import _sample_pdf


def _sample_xlsx_payload() -> bytes:
    header = ("Date", "Account", "Description", "Total", "Balance")
    definition = json.dumps(
        {
            "schema_version": 1,
            "parser_id": "synthetic_xlsx_table",
            "revision": "1",
            "suffix": ".xlsx",
            "kind": "activity_export",
            "capabilities": ["table_rows_v1"],
            "header": header,
            "columns": {
                "account": "Account",
                "date": "Date",
                "description": "Description",
                "total": "Total",
                "balance": "Balance",
            },
            "date_format": "MM/DD/YYYY",
            "money_format": "usd_symbol_2dp",
            "unknown_balance_literals": ["Unavailable"],
        }
    ).encode()
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Activity"
    sheet.append(header)
    sheet.append(("10/01/2026", "Account A", "Payment", "-$1.00", "Unavailable"))
    output = io.BytesIO()
    book.save(output)
    book.close()
    sheet_name = b"Activity"
    return (
        len(definition).to_bytes(4, "big")
        + len(sheet_name).to_bytes(2, "big")
        + definition
        + sheet_name
        + output.getvalue()
    )


def check_frozen_workers(binary: Path) -> None:
    for mode, source in (
        ("simple", _sample_pdf()),
        ("annotation-period", _sample_pdf()),
        ("xlsx-evidence", _sample_xlsx_payload()),
    ):
        process = subprocess.run(
            [str(binary), "--v2-parser-worker", mode, str(512 * 1024 * 1024)],
            input=source,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if process.returncode != 0 or process.stderr:
            raise RuntimeError(f"Frozen {mode} worker smoke failed")
        decoded = json.loads(process.stdout)
        if mode == "simple" and decoded != {"pages": ["ParseTrail smoke"], "metadata": {}}:
            raise RuntimeError("Frozen simple worker output mismatch")
        if mode == "annotation-period" and decoded != {"dates": []}:
            raise RuntimeError("Frozen annotation worker output mismatch")
        if mode == "xlsx-evidence" and (decoded.get("kind") != "activity_export" or len(decoded.get("rows", [])) != 1):
            raise RuntimeError("Frozen XLSX worker output mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    check_frozen_workers(args.binary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

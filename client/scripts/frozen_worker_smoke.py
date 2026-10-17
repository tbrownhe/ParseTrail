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


def _sample_table_pdf(words: tuple[tuple[int, int, str], ...]) -> bytes:
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


def _sample_table_payload(definition_name: str, words: tuple[tuple[int, int, str], ...]) -> bytes:
    definition = (
        Path(__file__).resolve().parents[2] / "devtools" / "parser_engine_pilot" / definition_name
    ).read_bytes()
    return len(definition).to_bytes(4, "big") + definition + _sample_table_pdf(words)


def check_frozen_workers(binary: Path) -> None:
    for mode, source in (
        ("simple", _sample_pdf()),
        ("annotation-period", _sample_pdf()),
        ("xlsx-evidence", _sample_xlsx_payload()),
        (
            "anchored-table",
            _sample_table_payload(
                "middle-citi-table-pilot-definition.json",
                (
                    (20, 380, "Trans."),
                    (80, 380, "Post"),
                    (140, 380, "Description"),
                    (300, 380, "Amount"),
                    (20, 350, "01/05"),
                    (80, 350, "01/05"),
                    (140, 350, "Payment"),
                    (300, 350, "-$20.00"),
                    (20, 330, "01/10"),
                    (80, 330, "01/09"),
                    (140, 330, "Purchase"),
                    (300, 330, "$10.00"),
                ),
            ),
        ),
        (
            "wells-table",
            _sample_table_payload(
                "wells-table-pilot-definition.json",
                (
                    (20, 380, "Date"),
                    (70, 380, "Description"),
                    (170, 380, "Credits"),
                    (230, 380, "Debits"),
                    (290, 380, "balance"),
                    (20, 350, "1/1"),
                    (70, 350, "Printed"),
                    (170, 350, "$1.00"),
                    (290, 350, "$101.00"),
                ),
            ),
        ),
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
        if mode == "anchored-table" and len(decoded.get("rows", [])) != 3:
            raise RuntimeError("Frozen anchored table worker output mismatch")
        if mode == "wells-table" and len(decoded.get("rows", [])) != 1:
            raise RuntimeError("Frozen Wells table worker output mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    check_frozen_workers(args.binary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

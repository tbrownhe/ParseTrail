"""Read-only review of fresh archive evidence and retained category assertions."""

import json
from pathlib import Path

from parsetrail.core.recovery_bundle import digest
from parsetrail.gui.ledger_preview import money


def load_rebuild_preview(folder: Path) -> dict:
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    for filename, expected in (
        ("plan.json", report["plan_sha256"]),
        ("fresh.db", report["database_sha256"]),
        ("legacy.db", report["source_sha256"]),
    ):
        if digest(folder / filename) != expected:
            raise ValueError("Rebuild artifact changed after verification.")
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    accounts = {a["AccountID"]: a["AccountName"] for a in plan["legacy_metadata"]["Accounts"]}
    categories = {c["CategoryID"]: c["Name"] for c in plan["legacy_metadata"]["Categories"]}
    evidence = plan["evidence"]
    restored, pending, totals, sources = [], [], [], []
    for decision in plan["annotations"]["decisions"]:
        old = decision["legacy"]
        record = {
            "cells": [
                accounts[decision["account_id"]],
                old["PostingDate"],
                old["Description"],
                money(decision["amount_minor"]),
                categories[decision["category_id"]],
                decision["status"],
            ],
            "details": "Category verification is separate from ledger review and statement reconciliation.\n"
            + json.dumps(
                {
                    "decision": decision,
                    "fresh_candidates": [evidence["transactions"][tid] for tid in decision["candidates"]],
                    "source_files": [evidence["files"][s]["filename"] for s in decision["sources"]],
                },
                indent=2,
            ),
        }
        (restored if decision["status"] == "restored" else pending).append(record)
    for row in plan["annotations"]["totals"]:
        totals.append(
            {
                "cells": [
                    accounts[row["account_id"]],
                    categories[row["category_id"]],
                    str(row["original_count"]),
                    str(row["restored_count"]),
                    str(row["pending_count"]),
                    money(row["original_minor"]),
                    money(row["restored_minor"]),
                    money(row["pending_minor"]),
                ],
                "details": "Signed account movement amounts, including refunds. Original = restored + pending.\n"
                + json.dumps(row, indent=2),
            }
        )
    for record in plan["evidence"]["files"].values():
        sources.append(
            {
                "cells": [
                    record["filename"],
                    record["status"],
                    record.get("plugin", "") or "",
                    record.get("code", ""),
                    ", ".join(record.get("diagnostics", [])),
                ],
                "details": json.dumps(record, indent=2),
            }
        )
    untouched = [
        {"cells": [path], "details": "Retained archive file outside the successful-source replay scope."}
        for path in plan["evidence"]["unreferenced_archive_files"]
    ]
    headers = ["Account", "Date", "Description", "Amount", "Category", "Review status"]
    return {
        "window_title": "ParseTrail — Fresh rebuild review (read only)",
        "title": "Fresh archive rebuild — category preservation review",
        "summary": f"{len(restored):,} verified expense categories restored · {len(pending):,} pending, with old decisions retained\n"
        f"{report['transactions']:,} fresh evidence transactions · {report['statements']:,} account statements\n"
        "No journal entries posted. This database is not ready for report cutover. The active profile is unchanged.",
        "tabs": [
            (
                "Category totals",
                [
                    "Account",
                    "Category",
                    "Original count",
                    "Restored count",
                    "Pending count",
                    "Original amount",
                    "Restored amount",
                    "Pending amount",
                ],
                totals,
            ),
            ("Pending categories", headers, pending),
            ("Restored categories", headers, restored),
            ("Source replay", ["File", "Status", "Parser", "Error", "Diagnostics"], sources),
            ("Other archive files", ["Retained file"], untouched),
        ],
    }

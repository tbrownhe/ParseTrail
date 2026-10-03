"""Read-only loan evidence, provenance and interpretation-readiness tables."""

import json

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_loan_readiness import RULE
from parsetrail.core.recovery_bundle import digest
from parsetrail.gui.ledger_preview import money


def load_loan_preview(folder):
    manifest = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    path = folder / "readiness.json"
    if manifest.get("rule") != RULE or digest(path) != manifest["readiness_sha256"]:
        raise LedgerError("Loan readiness report is unsupported or changed.")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report["rule"] != RULE or report["rebuild_hash"] != manifest["rebuild_hash"]:
        raise LedgerError("Loan readiness report belongs to different evidence.")
    return loan_preview(report)


def loan_preview(report):
    def amount(row, field):
        return money(row[field]) if row["currency"] == "USD" else f"{row['currency']}: {row[field]} minor units"

    def detail(row):
        return json.dumps(row, indent=2, ensure_ascii=False)

    accounts = [
        {
            "cells": [
                r["account_name"],
                str(r["statement_count"]),
                str(r["movement_count"]),
                ", ".join(r["plugins"]),
                ", ".join(r["blockers"]).replace("_", " "),
            ],
            "details": f"{r['account_name']} · {r['currency']}\n"
            f"{r['statement_count']} source periods; {r['movement_count']} distinct movements.\n"
            "No loan journals have been proposed. These accounts remain outside the posting workflow.\n\n"
            "Needs review:\n"
            + "\n".join("• " + b.replace("_", " ") for b in r["blockers"])
            + "\n\nRetained report details:\n"
            + detail(r),
        }
        for r in report["accounts"]
    ]
    statements = [
        {
            "cells": [
                r["account_name"],
                r["start"],
                r["end"],
                amount(r, "opening_minor"),
                amount(r, "closing_minor"),
                amount(r, "difference_minor"),
                r["balance_basis"],
            ],
            "details": "Equation: closing − opening − parsed movements. Agreement is not independent reconciliation.\n\n"
            + f"{r['account_name']} · {r['start']} through {r['end']}\n"
            + f"Balance evidence: {r['balance_basis']}\nPeriod evidence: {r['period_basis']}\n"
            + f"Movement representation: {r['movement_basis']}\n"
            + f"Source: {r['filename']}\nParser: {r['plugin']}\n\nRetained report details:\n"
            + detail(r),
        }
        for r in report["statements"]
    ]
    movements = [
        {
            "cells": [
                r["account_name"],
                r["posting_date"],
                r["description"],
                amount(r, "amount_minor"),
                r["hint"].replace("_", " "),
                r["date_provenance"].replace("_", " "),
            ],
            "details": "This is an interpretation hint, not a posted or reviewed classification.\n"
            "Interest components must not be expensed again when matching the payment.\n\n"
            + f"{r['account_name']} · {r['posting_date']} · {amount(r, 'amount_minor')}\n{r['description']}\n"
            + f"Review hint: {r['hint'].replace('_', ' ')}\nDate basis: {r['date_provenance'].replace('_', ' ')}\n"
            + "\nRetained report details:\n"
            + detail(r),
        }
        for r in report["movements"]
    ]
    return {
        "window_title": "ParseTrail — Loan readiness review (read only)",
        "title": "Loan evidence readiness — no postings or source changes",
        "summary": f"{report['account_count']} loan accounts · {report['statement_count']} source periods · {report['movement_count']} distinct movements.\n"
        "Balance equations, parser assumptions and interpretation hints remain unverified. "
        "Synthetic origination is not an observed cash receipt. Loans remain outside the posting adapter.",
        "tabs": [
            ("Loan accounts", ["Account", "Source periods", "Movements", "Parsers", "Posting blockers"], accounts),
            (
                "Source balances",
                ["Account", "Start", "End", "Opening", "Closing", "Equation difference", "Balance evidence"],
                statements,
            ),
            (
                "Loan movements",
                ["Account", "Date", "Description", "Movement", "Interpretation hint", "Date provenance"],
                movements,
            ),
        ],
    }

"""Read-only acceptance of a one-time MOHELA evidence replacement."""

import json
from contextlib import closing

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_mohela_replacement import replacement_report
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.recovery_bundle import digest, read_only
from parsetrail.gui.ledger_preview import money


def preview_data(folder):
    saved = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    if digest(folder / "plan.json") != saved["plan_sha256"] or digest(folder / "fresh.db") != saved["database_sha256"]:
        raise LedgerError("Replacement workspace changed since verification.")
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    with closing(read_only(folder / "fresh.db")) as c:
        if c.execute("SELECT plan_hash FROM RebuildMeta").fetchall() != [(key(plan),)]:
            raise LedgerError("Replacement database belongs to another plan.")
    report = replacement_report(plan)
    export = plan["activity_exports"][plan["mohela_replacement"]["new_source"]]
    categories = {c["CategoryID"]: c["Name"] for c in plan["legacy_metadata"]["Categories"]}
    accounts = {a["AccountID"]: a["AccountName"] for a in plan["legacy_metadata"]["Accounts"]}
    loans, annotations, payments, activity = [], [], [], []
    for loan in report["loans"]:
        loans.append(
            {
                "cells": [
                    loan["loan_id"],
                    loan["loan_name"],
                    str(loan["row_count"]),
                    loan["balance_date"] or "Unknown",
                    money(loan["reported_principal_minor"])
                    if loan["reported_principal_minor"] is not None
                    else "Unknown",
                    money(loan["net_listed_principal_minor"]),
                    money(loan["unexplained_minor"]) if loan["unexplained_minor"] is not None else "Unknown",
                    "Conflicting balance observations" if loan["balance_conflict"] else "Unreconciled",
                ],
                "details": "Reported principal is an observation attached to an export row date, not an independently verified statement endpoint.\n"
                "Net listed principal is the sum of supplied changes through that date, not a balance reconstructed from an assumed opening.\n"
                "The difference may reflect omitted activity or an unknown starting position. No balancing entry is created.\n"
                "Unavailable means unknown, including for a loan reported paid off elsewhere. Coverage remains unverified.\n"
                + json.dumps(loan, indent=2),
            }
        )
    for binding in plan["export_category_bindings"]:
        old = binding["legacy"]
        annotations.append(
            {
                "cells": [
                    old["PostingDate"],
                    old["Description"],
                    money(old["AmountMinor"]),
                    categories[binding["category_id"]],
                    str(len(binding["allocations"])),
                    "Verified annotation retained",
                ],
                "details": "The original verified category is retained on this exact component group. It does not approve spending, interest, a disbursement or a bank match.\n"
                "Do not count the old aggregate and its new component rows as separate activity.\n"
                + json.dumps(binding, indent=2),
            }
        )
    for payment in report["bank_counterparts"]:
        candidates = payment["bank_candidates"]
        payments.append(
            {
                "cells": [
                    payment["date"],
                    money(payment["outflow_minor"]),
                    str(len(candidates)),
                    " / ".join(sorted({accounts[r["AccountID"]] for r in candidates})),
                    "Not confirmed",
                ],
                "details": "Exact opposite checking/savings amounts within seven days are candidates only. A payment date can contain more than one bank withdrawal.\n"
                "Missing candidates can reflect stale bank imports; no bank movement or saved decision is changed.\n"
                + json.dumps(payment, indent=2),
            }
        )
    for row in export["rows"]:
        activity.append(
            {
                "cells": [
                    row["loan_id"],
                    row["date"],
                    row["description"],
                    money(row["principal_minor"]),
                    money(row["interest_minor"]),
                    money(row["fees_minor"]),
                    money(row["total_minor"]),
                    money(row["reported_principal_minor"])
                    if row["reported_principal_minor"] is not None
                    else "Unknown",
                ],
                "details": "Original export signs and component values; zero rows remain evidence. No ledger entry is posted.\n"
                + json.dumps(row, indent=2),
            }
        )
    return {
        "window_title": "ParseTrail — MOHELA replacement review (read only)",
        "title": "MOHELA evidence replacement — disposable rebuild",
        "summary": f"{report['old_movements_replaced']} old derived movements replaced by {report['new_source_rows']} detailed source rows. "
        f"{report['verified_categories_retained']} verified category annotations retained. Bank evidence is unchanged.\n"
        "Reported balances and listed activity stay separate. Loan history is incomplete; nothing is posted and the live database is unchanged.",
        "tabs": [
            (
                "Loan balances",
                [
                    "Loan",
                    "Name",
                    "Rows",
                    "Balance row date",
                    "Reported principal",
                    "Net listed principal",
                    "Unexplained difference",
                    "Review status",
                ],
                loans,
            ),
            (
                "Retained categories",
                ["Date", "Original description", "Original amount", "Category", "Components", "Review status"],
                annotations,
            ),
            ("Bank match candidates", ["Date", "Payment", "Candidates", "Bank accounts", "Review status"], payments),
            (
                "Export activity",
                ["Loan", "Date", "Description", "Principal", "Interest", "Fees", "Total", "Reported principal"],
                activity,
            ),
        ],
    }

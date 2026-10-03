"""Read-only loan evidence inventory; never admit observations or propose journals."""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_rebuild import key

RULE = "loan-readiness-1"
CONTRACTS = {
    "pdf_capitaloneauto_202402": {
        "balance_basis": "Principal balance; opening derived from closing and principal activity",
        "period_basis": "Printed transaction-history range; boundary timing unreviewed",
        "movement_basis": "Payment total and separate interest component; do not expense interest twice",
        "limitations": ["derived_opening_balance", "source_date_and_balance_review_required"],
    },
    "pdf_wfloanper_202306": {
        "balance_basis": "Printed principal balances, except synthetic origination resets opening to zero",
        "period_basis": "Assumed 31-day lookback from statement date; coverage is not established",
        "movement_basis": "Payment combines same-date principal and interest; separate interest row offsets it",
        "limitations": [
            "assumed_statement_period",
            "synthetic_origination_review_required",
            "source_date_and_balance_review_required",
        ],
    },
    "pdf_yamahafin_202306": {
        "balance_basis": "Printed previous/new loan-register balances; principal-only meaning not established",
        "period_basis": "Closing date and billing-cycle length; boundary timing unreviewed",
        "movement_basis": "Register purchases, payments and charges require separate interpretations",
        "limitations": [
            "balance_composition_review_required",
            "transaction_date_extraction_requires_review",
            "source_date_and_balance_review_required",
        ],
    },
    "csv_mohela_202411": {
        "balance_basis": "Opening assumed zero; closing and running balances reconstructed from exported rows",
        "period_basis": "First/last activity dates; not independent statement coverage",
        "movement_basis": "Total and interest columns melted into rows; disbursement/capitalization need review",
        "limitations": [
            "derived_balances",
            "activity_range_not_coverage",
            "capitalized_interest_review_required",
            "source_date_and_balance_review_required",
        ],
    },
}


def movement_hint(row, plugins):
    """Search hints only, not classifications or permission to post."""
    desc, amount = row["Description"].strip().upper(), row["AmountMinor"]
    if "pdf_wfloanper_202306" in plugins and desc == "LOAN ORIGINATION":
        return "synthetic_estimated_origination"
    if plugins - CONTRACTS.keys():
        return "unknown_parser_review"
    if "CAPITALIZED" in desc or "CAPITALIZATION" in desc:
        return "capitalized_interest_review"
    if "DISBURSEMENT" in desc or desc == "AMOUNT FINANCED":
        return "financing_counterpart_review"
    if "INTEREST" in desc:
        return "interest_component_review"
    if "PURCHASE" in desc:
        return "purchase_or_asset_funding_review"
    if "PAYMENT" in desc and amount > 0:
        return "payment_counterpart_review"
    if amount == 0:
        return "zero_amount_evidence"
    return "other_loan_movement_review"


def build_loan_readiness(rebuild):
    evidence, metadata = rebuild["evidence"], rebuild["legacy_metadata"]
    types = {a["AccountTypeID"]: a for a in metadata["AccountTypes"]}
    accounts = {a["AccountID"]: a for a in metadata["Accounts"] if types[a["AccountTypeID"]]["AccountType"] == "Loan"}
    for row in evidence["transactions"].values():
        if row["AccountID"] in accounts and (
            type(row["AmountMinor"]) is not int or not -(2**63) < row["AmountMinor"] < 2**63
        ):
            raise LedgerError("Loan evidence requires exact integer minor units.")
    links, sources = defaultdict(list), defaultdict(set)
    for link in evidence["memberships"]:
        statement = evidence["statements"][link["statement_id"]]
        row = evidence["transactions"][link["transaction_id"]]
        if statement["account_id"] != row["AccountID"] or statement["source"] != link["source"]:
            raise LedgerError("Loan audit source membership has inconsistent ownership.")
        links[statement["id"]].append(row["id"])
        sources[row["id"]].add(statement["id"])
    statements, movements, account_rows = [], [], []
    for sid, s in sorted(evidence["statements"].items()):
        if s["account_id"] not in accounts:
            continue
        if date.fromisoformat(s["start"]) > date.fromisoformat(s["end"]):
            raise LedgerError("Loan statement period is reversed.")
        if any(type(s[k]) is not int or not -(2**63) < s[k] < 2**63 for k in ("opening_minor", "closing_minor")):
            raise LedgerError("Loan balances require exact integer minor units.")
        ids = links[sid]
        if len(ids) != len(set(ids)):
            raise LedgerError("Loan statement repeats canonical evidence.")
        source = evidence["files"][s["source"]]
        plugin = source.get("plugin", "unknown")
        contract = CONTRACTS.get(
            plugin,
            {
                "balance_basis": "Unknown parser contract",
                "period_basis": "Unknown parser contract",
                "movement_basis": "No admitted sign or component contract",
                "limitations": ["unknown_parser_contract"],
            },
        )
        total = sum(evidence["transactions"][tid]["AmountMinor"] for tid in ids)
        contract = deepcopy(contract)
        difference = s["closing_minor"] - s["opening_minor"] - total
        outside = sorted(
            tid for tid in ids if not s["start"] <= evidence["transactions"][tid]["PostingDate"] <= s["end"]
        )
        blockers = set(contract["limitations"]) | {
            "loan_posting_adapter_not_implemented",
            "opening_and_counterpart_review_required",
        }
        if source["status"] != "parsed" or s["status"] != "parsed":
            blockers.add("source_replay_not_accepted")
        if difference:
            blockers.add("source_balance_difference")
        if outside:
            blockers.add("movement_outside_source_period")
        synthetic = sorted(
            tid
            for tid in ids
            if movement_hint(evidence["transactions"][tid], {plugin}) == "synthetic_estimated_origination"
        )
        statements.append(
            {
                "statement_id": sid,
                "account_id": s["account_id"],
                "account_name": accounts[s["account_id"]]["AccountName"],
                "currency": accounts[s["account_id"]]["CurrencyCode"],
                "source_id": s["source"],
                "filename": source.get("filename", "Unknown source filename"),
                "plugin": plugin,
                "parser_manifest": rebuild.get("parser_manifest", {}).get(plugin),
                "start": s["start"],
                "end": s["end"],
                "opening_minor": s["opening_minor"],
                "closing_minor": s["closing_minor"],
                "movement_total_minor": total,
                "difference_minor": difference,
                "equation_agrees": difference == 0,
                "transaction_ids": sorted(ids),
                "outside_period_ids": outside,
                "synthetic_origination_ids": synthetic,
                "source_balance_provenance": s["balance_provenance"],
                **contract,
                "blockers": sorted(blockers),
                "independently_reconciled": False,
                "ready_for_posting": False,
            }
        )
    for tid, row in sorted(evidence["transactions"].items()):
        aid = row["AccountID"]
        if aid not in accounts:
            continue
        memberships = sorted(sources[tid])
        plugins = {
            evidence["files"][evidence["statements"][sid]["source"]].get("plugin", "unknown") for sid in memberships
        }
        hint = movement_hint(row, plugins) if memberships else "missing_source_membership"
        movements.append(
            {
                "transaction_id": tid,
                "account_id": aid,
                "account_name": accounts[aid]["AccountName"],
                "posting_date": row["PostingDate"],
                "transaction_date": row.get("TransactionDate"),
                "amount_minor": row["AmountMinor"],
                "currency": row["CurrencyCode"],
                "description": row["Description"],
                "statement_ids": memberships,
                "plugins": sorted(plugins),
                "hint": hint,
                "interpretation_reviewed": False,
                "posted": False,
                "date_provenance": "synthetic_estimated"
                if hint == "synthetic_estimated_origination"
                else "unreviewed_parser_output",
            }
        )
    for aid, account in sorted(accounts.items()):
        rows = [s for s in statements if s["account_id"] == aid]
        txs = [m for m in movements if m["account_id"] == aid]
        blockers = {b for s in rows for b in s["blockers"]}
        if not rows:
            blockers.add("no_source_statement")
        if types[account["AccountTypeID"]]["AssetType"] != "Debt":
            blockers.add("account_class_conflict")
        if account["CurrencyCode"] != "USD" or any(t["currency"] != account["CurrencyCode"] for t in txs):
            blockers.add("currency_contract_pending")
        if any(not t["statement_ids"] for t in txs):
            blockers.add("missing_source_membership")
        account_rows.append(
            {
                "account_id": aid,
                "account_name": account["AccountName"],
                "currency": account["CurrencyCode"],
                "statement_count": len(rows),
                "movement_count": len(txs),
                "movement_total_minor": sum(t["amount_minor"] for t in txs),
                "plugins": sorted({s["plugin"] for s in rows}),
                "hints": dict(sorted(Counter(t["hint"] for t in txs).items())),
                "blockers": sorted(blockers),
                "ready_for_posting": False,
            }
        )
    statements.sort(key=lambda row: (row["account_name"], row["start"], row["end"], row["statement_id"]))
    movements.sort(key=lambda row: (row["account_name"], row["posting_date"], row["transaction_id"]))
    account_rows.sort(key=lambda row: (row["account_name"], row["account_id"]))
    return {
        "rule": RULE,
        "rebuild_hash": key(rebuild),
        "accounts": account_rows,
        "statements": statements,
        "movements": movements,
        "account_count": len(account_rows),
        "statement_count": len(statements),
        "movement_count": len(movements),
        "hint_summary": dict(sorted(Counter(m["hint"] for m in movements).items())),
        "journal_entries_posted": 0,
        "ready_for_cutover": False,
    }

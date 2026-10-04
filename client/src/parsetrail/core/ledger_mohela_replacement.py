"""One-time MOHELA evidence replacement in a new, unposted rebuild only."""

import copy
import json
import shutil
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_migration import read_legacy
from parsetrail.core.ledger_rebuild import key, signature, write_rebuild
from parsetrail.core.ledger_store import encoded
from parsetrail.core.mohela_export import loan_summary, read_export
from parsetrail.core.recovery_bundle import digest, read_only

RULE = "mohela-evidence-replacement-1"


def build_replacement(original, export, legacy):
    if original.get("activity_exports") or original.get("superseded_source_evidence"):
        raise LedgerError("This workflow replaces only the original aggregate MOHELA import once.")
    plan = copy.deepcopy(original)
    e = plan["evidence"]
    sources = {fid for fid, f in e["files"].items() if f.get("plugin") == "csv_mohela_202411"}
    if len(sources) != 1:
        raise LedgerError("Choose a rebuild with exactly one aggregate MOHELA source; multiple sources need review.")
    source = next(iter(sources))
    statements = {sid: s for sid, s in e["statements"].items() if s["source"] == source}
    accounts = {s["account_id"] for s in statements.values()}
    if len(accounts) != 1 or not statements or e["files"][source]["status"] != "parsed":
        raise LedgerError("MOHELA source ownership/status requires review.")
    account = next(iter(accounts))
    ids = {m["transaction_id"] for m in e["memberships"] if m["source"] == source}
    if any(m["transaction_id"] in ids and m["source"] != source for m in e["memberships"]):
        raise LedgerError("Shared source movements cannot be replaced without reviewing every membership.")
    oldrows = {tid: e["transactions"][tid] for tid in ids}
    if any(r["AccountID"] != account or r["CurrencyCode"] != "USD" for r in oldrows.values()):
        raise LedgerError("MOHELA source account/currency is inconsistent.")
    grouped = defaultdict(list)
    for r in export["rows"]:
        grouped[r["date"], r["description"]].append(r)
    matches, used = {}, set()
    for tid, old in sorted(oldrows.items()):
        desc = old["Description"]
        if desc not in {"PAYMENT", "INTEREST", "DISBURSEMENT", "CAPITALIZED INTEREST"}:
            raise LedgerError("An old MOHELA movement has an unsupported interpretation; review required.")
        role, factor, kind = ("interest_minor", 1, "PAYMENT") if desc == "INTEREST" else ("total_minor", -1, desc)
        group = (old["PostingDate"], kind, role)
        if group in used:
            raise LedgerError("Repeated aggregate movements require individual matching review.")
        used.add(group)
        candidates = grouped[old["PostingDate"], kind]
        if not candidates or sum(factor * r[role] for r in candidates) != old["AmountMinor"]:
            raise LedgerError("New MOHELA components do not exactly preserve an old movement; review required.")
        matches[tid] = {
            "component": role,
            "factor": factor,
            "allocations": [{"row_id": r["id"], "amount_minor": factor * r[role]} for r in candidates],
        }
    # Use original statement membership, never merely a similar manual transaction.
    old_statement_ids = set(e["files"][source]["statement_ids"])
    linked = {m["TransactionID"] for m in legacy["StatementTransactions"] if m["StatementID"] in old_statement_ids}
    bindings = []
    for old in legacy["Transactions"]:
        if old["TransactionID"] not in linked or not old["Verified"] or old["CategoryID"] is None:
            continue
        candidates = [tid for tid, r in oldrows.items() if signature(old) == signature(r)]
        if len(candidates) != 1:
            raise LedgerError("A verified category has an ambiguous old source mapping; review required.")
        tid = candidates[0]
        bindings.append(
            {
                "legacy_id": old["TransactionID"],
                "category_id": old["CategoryID"],
                "export_id": export["source_sha256"],
                "source_transaction_id": tid,
                "category_verified": True,
                "accounting_approved": False,
                "legacy": copy.deepcopy(old),
                **matches[tid],
            }
        )
    if len({b["source_transaction_id"] for b in bindings}) != len(bindings):
        raise LedgerError("Several verified categories target one old movement; review required.")
    archive = {
        "file": copy.deepcopy(e["files"][source]),
        "statements": statements,
        "transactions": oldrows,
        "memberships": [m for m in e["memberships"] if m["source"] == source],
        "category_decisions": [
            copy.deepcopy(d) for d in plan["annotations"]["decisions"] if d.get("transaction_id") in ids
        ],
    }
    binding_ids = {b["legacy_id"] for b in bindings}
    for decision in plan["annotations"]["decisions"]:
        if decision.get("transaction_id") not in ids:
            continue
        if decision["status"] != "restored" or decision["legacy_id"] not in binding_ids:
            raise LedgerError("An existing category decision cannot be retained automatically.")
        decision.update(
            status="retained_export_annotation",
            transaction_id=None,
            candidates=[],
            match_method="exact_aggregate_components",
        )
        total = next(
            t
            for t in plan["annotations"]["totals"]
            if (t["account_id"], t["category_id"], t["currency"])
            == (decision["account_id"], decision["category_id"], decision["currency"])
        )
        for suffix, amount in (("count", 1), ("minor", decision["amount_minor"])):
            total[f"restored_{suffix}"] -= amount
            total[f"retained_{suffix}"] = total.get(f"retained_{suffix}", 0) + amount
    plan["annotations"]["counts"] = dict(Counter(d["status"] for d in plan["annotations"]["decisions"]))
    for sid in statements:
        del e["statements"][sid]
    for tid in ids:
        del e["transactions"][tid]
    e["memberships"] = [m for m in e["memberships"] if m["source"] != source]
    e["files"][source].update(status="superseded_by_detailed_export", replacement=export["source_sha256"])
    e["files"][export["source_sha256"]] = {
        "filename": export.get("filename", "Detailed MOHELA export.csv"),
        "sha256": export["source_sha256"],
        "status": "activity_export_review_only",
        "reader": export["rule"],
    }
    plan["activity_exports"] = {export["source_sha256"]: copy.deepcopy(export)}
    plan["export_category_bindings"] = bindings
    plan["superseded_source_evidence"] = {source: archive}
    plan["mohela_replacement"] = {
        "rule": RULE,
        "original_plan_hash": key(original),
        "account_id": account,
        "old_source": source,
        "new_source": export["source_sha256"],
        "movement_matches": matches,
        "financial_approval": False,
    }
    return plan


def replacement_report(plan):
    replacement = plan["mohela_replacement"]
    export = plan["activity_exports"][replacement["new_source"]]
    roles = {t["AccountTypeID"]: t["AccountType"] for t in plan["legacy_metadata"]["AccountTypes"]}
    cash = {
        a["AccountID"]
        for a in plan["legacy_metadata"]["Accounts"]
        if roles[a["AccountTypeID"]] in {"Checking", "Savings"}
    }
    payments = defaultdict(list)
    for row in export["rows"]:
        if row["description"] == "PAYMENT":
            payments[row["date"]].append(row)
    counterparts = []
    for when, rows in sorted(payments.items()):
        amount = sum(r["total_minor"] for r in rows)
        if amount >= 0:
            continue
        candidates = [
            r
            for r in plan["evidence"]["transactions"].values()
            if r["AccountID"] in cash
            and r["CurrencyCode"] == "USD"
            and r["AmountMinor"] == amount
            and abs((date.fromisoformat(r["PostingDate"]) - date.fromisoformat(when)).days) <= 7
        ]
        counterparts.append(
            {
                "date": when,
                "outflow_minor": -amount,
                "row_ids": [r["id"] for r in rows],
                "bank_candidates": candidates,
                "confirmed": False,
            }
        )
    return {
        "loans": loan_summary(export),
        "bank_counterparts": counterparts,
        "old_movements_replaced": len(replacement["movement_matches"]),
        "new_source_rows": len(export["rows"]),
        "verified_categories_retained": len(plan["export_category_bindings"]),
        "posted_entries": 0,
        "ready_for_cutover": False,
    }


def create_replacement(accepted: Path, csv_path: Path, output: Path, *, old_export: Path | None = None):
    """Verify inputs and write a new isolated rebuild; never edit a source database."""
    report = json.loads((accepted / "report.json").read_text(encoding="utf-8"))
    checks = {
        accepted / "plan.json": report["plan_sha256"],
        accepted / "fresh.db": report["database_sha256"],
        accepted / "legacy.db": report["source_sha256"],
    }
    if any(digest(p) != h for p, h in checks.items()) or any(
        Path(str(p) + suffix).exists() for p in checks if p.suffix == ".db" for suffix in ("-wal", "-shm", "-journal")
    ):
        raise LedgerError("Use unchanged, inactive accepted rebuild inputs.")
    original = json.loads((accepted / "plan.json").read_text(encoding="utf-8"))
    with closing(read_only(accepted / "fresh.db")) as c:
        if (
            c.execute("SELECT plan_hash FROM RebuildMeta").fetchall() != [(key(original),)]
            or c.execute("SELECT COUNT(*) FROM LedgerEntries").fetchone()[0]
        ):
            raise LedgerError("Replacement requires the original unposted rebuild, not saved workflow decisions.")
    data = csv_path.read_bytes()
    export = read_export(data)
    export.update(filename=csv_path.name, captured_at=datetime.now(timezone.utc).isoformat())
    plan = build_replacement(original, export, read_legacy(accepted / "legacy.db"))
    if old_export is not None and digest(old_export) != plan["mohela_replacement"]["old_source"]:
        raise LedgerError("Original MOHELA archive bytes do not match retained evidence.")
    result = replacement_report(plan)
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "original"
    archive.mkdir()
    for p in checks:
        shutil.copyfile(p, archive / p.name)
    if old_export is not None:
        shutil.copyfile(old_export, archive / "old-export.csv")
        if digest(archive / "old-export.csv") != plan["mohela_replacement"]["old_source"]:
            raise LedgerError("Original MOHELA archive changed while copying.")
    shutil.copyfile(accepted / "legacy.db", output / "legacy.db")
    (output / "new-export.csv").write_bytes(data)
    write_rebuild(output / "fresh.db", plan)
    (output / "plan.json").write_text(encoded(plan), encoding="utf-8")
    result.update(
        plan_sha256=digest(output / "plan.json"),
        database_sha256=digest(output / "fresh.db"),
        source_sha256=report["source_sha256"],
        original_inputs_unchanged=True,
    )
    if (
        any(digest(p) != h or digest(archive / p.name) != h for p, h in checks.items())
        or digest(csv_path) != export["source_sha256"]
    ):
        raise LedgerError("Input changed during replacement; do not use the output.")
    (output / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result

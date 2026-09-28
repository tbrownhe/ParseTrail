"""Deterministic, conservative shadow conversion; never repair the source database."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from parsetrail.core.ledger import AccountKind, Allocation, JournalEntry, LedgerAccount, Observation, Posting
from parsetrail.core.ledger_reconciliation import StatementEvidence, evaluate_statement
from parsetrail.core.ledger_store import LedgerStore, encoded
from parsetrail.core.money import to_minor_units
from parsetrail.core.recovery_bundle import digest, inspect_database, read_only, safe_member
from parsetrail.core.utils import PDFReader
from parsetrail.plugins.pdf_hehsa_201810 import Parser as HSAParser

RULE_VERSION = "shadow-1"
CLOSURE = "Manual Entry: Account Closed Manually"


def signature(row: dict) -> tuple:
    return (row["PostingDate"], row["AmountMinor"], row["BalanceMinor"], row["Description"])


def read_legacy(source: Path) -> dict:
    with closing(read_only(source)) as connection:
        connection.row_factory = sqlite3.Row
        return {
            table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
            for table in (
                "Accounts",
                "AccountTypes",
                "AccountNumbers",
                "Categories",
                "Transactions",
                "Statements",
                "StatementTransactions",
                "Plugins",
            )
        }


def corrected_hsa(legacy: dict, archive: Path) -> list[dict]:
    """Reparse hash-verified sources and require every legacy row to survive."""
    plugins = {row["PluginID"]: row["PluginName"] for row in legacy["Plugins"]}
    transactions = {row["TransactionID"]: row for row in legacy["Transactions"]}
    memberships = defaultdict(list)
    for link in sorted(legacy["StatementTransactions"], key=lambda r: (r["StatementID"], r["StatementRow"])):
        memberships[link["StatementID"]].append(transactions[link["TransactionID"]])
    corrections = []
    for statement in sorted(legacy["Statements"], key=lambda r: r["StatementID"]):
        if plugins[statement["PluginID"]] not in {"pdf_hehsa", "pdf_hehsa_201810"}:
            continue
        filename = safe_member(statement["Filename"])
        if "/" in filename:
            raise ValueError("Expected a canonical archive filename.")
        path = archive / "SUCCESS" / filename
        if digest(path, statement["ContentHashAlgorithm"]) != statement["ContentHash"]:
            raise ValueError("HSA archive hash differs from the snapshot reference.")
        with PDFReader(path) as reader:
            parsed = HSAParser().parse(reader)
        if len(parsed.accounts) != 1 or (parsed.start_date.isoformat(), parsed.end_date.isoformat()) != (
            statement["StartDate"],
            statement["EndDate"],
        ):
            raise ValueError("HSA source identity/period requires review.")
        account = parsed.accounts[0]
        numbers = {
            row["AccountNumber"] for row in legacy["AccountNumbers"] if row["AccountID"] == statement["AccountID"]
        }
        if account.account_num not in numbers:
            raise ValueError("HSA source account number does not match the recorded account.")
        rows = [
            {
                "PostingDate": t.posting_date.isoformat(),
                "AmountMinor": to_minor_units(t.amount),
                "BalanceMinor": to_minor_units(t.balance),
                "Description": t.desc,
            }
            for t in account.transactions
        ]
        previous = Counter(signature(row) for row in memberships[statement["StatementID"]])
        current = Counter(signature(row) for row in rows)
        if previous - current or to_minor_units(account.start_balance) != statement["StartBalanceMinor"]:
            raise ValueError("HSA reparse would change/remove existing evidence; stop for review.")
        corrections.append(
            {
                "statement_id": statement["StatementID"],
                "source_hash": statement["ContentHash"],
                "parser": HSAParser.PLUGIN_NAME,
                "version": HSAParser.VERSION,
                "opening_minor": to_minor_units(account.start_balance),
                "closing_minor": to_minor_units(account.end_balance),
                "rows": rows,
            }
        )
    return corrections


def build_plan(legacy: dict, *, source_id: str, corrections: list[dict]) -> dict:
    """Build a reviewable plan; matching transfer labels never creates postings."""
    if not source_id.strip():
        raise ValueError("A stable source identity is required across reruns.")
    namespace = hashlib.sha256(source_id.encode()).hexdigest()[:24]
    prefix = f"legacy:{namespace}"

    def account_key(value):
        return f"{prefix}:account:{value}"

    def transaction_key(value):
        return f"{prefix}:transaction:{value}"

    def statement_key(value):
        return f"{prefix}:statement:{value}"

    types = {row["AccountTypeID"]: row for row in legacy["AccountTypes"]}
    categories = {row["CategoryID"]: row for row in legacy["Categories"]}
    accounts_by_id = {row["AccountID"]: row for row in legacy["Accounts"]}
    plugins = {row["PluginID"]: row["PluginName"] for row in legacy["Plugins"]}
    accounts, observations, statements, entries, decisions = [], [], [], [], []
    for row in sorted(legacy["Accounts"], key=lambda r: r["AccountID"]):
        asset_type = types[row["AccountTypeID"]]["AssetType"]
        if asset_type not in {"Asset", "Debt", "TangibleAsset"}:
            raise ValueError("Unknown source account class requires review.")
        accounts.append(
            LedgerAccount(
                account_key(row["AccountID"]),
                row["AccountName"],
                AccountKind.LIABILITY if asset_type == "Debt" else AccountKind.ASSET,
                currency=row["CurrencyCode"],
                source_account_id=account_key(row["AccountID"]),
            )
        )
    for row in sorted(categories.values(), key=lambda r: r["CategoryID"]):
        if row["Type"] in {"Income", "Expense"}:
            accounts.append(
                LedgerAccount(f"{prefix}:category:{row['CategoryID']}", row["Name"], AccountKind(row["Type"].lower()))
            )
    by_key = {transaction_key(row["TransactionID"]): dict(row) for row in legacy["Transactions"]}
    membership = defaultdict(list)
    for link in sorted(legacy["StatementTransactions"], key=lambda r: (r["StatementID"], r["StatementRow"])):
        membership[link["StatementID"]].append(transaction_key(link["TransactionID"]))
    corrected = {row["statement_id"]: row for row in corrections}
    if len(corrected) != len(corrections):
        raise ValueError("Duplicate source correction.")
    statements_by_id = {s["StatementID"]: s for s in legacy["Statements"]}
    added = []
    for sid, correction in sorted(corrected.items()):
        source = statements_by_id[sid]
        if correction["source_hash"] != source["ContentHash"] or plugins[source["PluginID"]] not in {
            "pdf_hehsa",
            "pdf_hehsa_201810",
        }:
            raise ValueError("Correction does not belong to the approved HSA source.")
        available = defaultdict(list)
        for key in membership[sid]:
            available[signature(by_key[key])].append(key)
        result = []
        for index, row in enumerate(correction["rows"]):
            matches = available[signature(row)]
            if matches:
                key = matches.pop(0)
            else:
                # Do not silently merge an added row with another statement's
                # observation: overlapping correction evidence needs review.
                if any(
                    r["AccountID"] == source["AccountID"] and signature(r) == signature(row) for r in by_key.values()
                ):
                    raise ValueError("Added correction row overlaps existing evidence; review canonical identity.")
                token = hashlib.sha256(encoded([source["ContentHash"], index, row]).encode()).hexdigest()
                key = f"{prefix}:source-row:{token}"
                by_key[key] = {
                    **row,
                    "TransactionID": None,
                    "AccountID": source["AccountID"],
                    "CurrencyCode": source["CurrencyCode"],
                    "TransactionDate": row["PostingDate"],
                    "CategoryID": None,
                    "Verified": False,
                }
                added.append(
                    {
                        "observation_id": key,
                        "statement_id": sid,
                        "parser": correction["parser"],
                        "version": correction["version"],
                    }
                )
            result.append(key)
        if any(available.values()) or correction["opening_minor"] != source["StartBalanceMinor"]:
            raise ValueError("Correction must preserve existing rows and opening balance.")
        if correction["closing_minor"] - correction["opening_minor"] != sum(
            row["AmountMinor"] for row in correction["rows"]
        ):
            raise ValueError("Corrected source equation does not balance.")
        membership[sid] = result
    linked = {key for keys in membership.values() for key in keys}
    observable = set()
    for key, row in sorted(by_key.items()):
        account_type = types[accounts_by_id[row["AccountID"]]["AccountTypeID"]]["AccountType"]
        category = categories.get(row["CategoryID"])
        reason = None
        if row["Description"] == CLOSURE:
            reason = "manual_closure_control_evidence"
        elif row["AmountMinor"] == 0:
            reason = "zero_amount_evidence"
        elif account_type == "TangibleAsset":
            reason = "tangible_asset_valuation_review"
        elif row["Description"] == "LOAN ORIGINATION":
            reason = "synthetic_loan_opening_review"
        if reason is None:
            observations.append(
                Observation(
                    key,
                    account_key(row["AccountID"]),
                    row["AmountMinor"],
                    date.fromisoformat(row["PostingDate"]),
                    row["CurrencyCode"],
                )
            )
            observable.add(key)
            if key not in linked:
                reason = "manual_entry_review"
            elif account_type == "401k" or (
                account_type == "HSA" and not any(key in membership[sid] for sid in corrected)
            ):
                reason = "investment_scope_review"
            elif category is None:
                reason = "uncategorized_evidence"
            elif category["Type"] == "Transfer":
                reason = "unconfirmed_transfer"
            elif category["Type"] not in {"Income", "Expense"}:
                reason = "category_type_review"
            else:
                entries.append(
                    JournalEntry(
                        f"{key}:category-v1",
                        key,
                        date.fromisoformat(row["PostingDate"]),
                        row["Description"],
                        (
                            Posting(
                                account_key(row["AccountID"]),
                                row["AmountMinor"],
                                (Allocation(key, row["AmountMinor"]),),
                            ),
                            Posting(f"{prefix}:category:{category['CategoryID']}", -row["AmountMinor"]),
                        ),
                        reason="Provisional legacy category interpretation; not newly reviewed.",
                    )
                )
                reason = "posted_legacy_category_unreviewed"
        decisions.append(
            {
                "observation_id": key,
                "legacy_transaction_id": row["TransactionID"],
                "account_id": row["AccountID"],
                "reason": reason,
                "legacy_category_id": row["CategoryID"],
                "legacy_verified": bool(row["Verified"]),
            }
        )
    boundaries = defaultdict(list)
    statement_notes = []
    for source in sorted(legacy["Statements"], key=lambda r: r["StatementID"]):
        sid = source["StatementID"]
        correction = corrected.get(sid)
        opening = correction["opening_minor"] if correction else source["StartBalanceMinor"]
        closing = correction["closing_minor"] if correction else source["EndBalanceMinor"]
        provenance = "reported" if correction else "assumed"
        # Historical database endpoints remain unverified until independently
        # re-established. The first shadow run must not certify old parser output.
        ids = tuple(key for key in membership[sid] if key in observable)
        outside = [key for key in ids if not source["StartDate"] <= by_key[key]["PostingDate"] <= source["EndDate"]]
        statement_notes.append(
            {
                "statement_id": sid,
                "legacy_plugin": plugins[source["PluginID"]],
                "balance_provenance": "source_reparsed" if correction else "legacy_unverified",
                "excluded_observations": [key for key in membership[sid] if key not in observable],
                "out_of_period_observations": outside,
            }
        )
        if not outside:
            statements.append(
                StatementEvidence(
                    statement_key(sid),
                    account_key(source["AccountID"]),
                    date.fromisoformat(source["StartDate"]),
                    date.fromisoformat(source["EndDate"]),
                    opening,
                    closing,
                    ids,
                    opening_provenance=provenance,
                    closing_provenance=provenance,
                )
            )
        boundaries[source["AccountID"]].append(
            (source["StartDate"], source["EndDate"], sid, opening, closing, provenance)
        )
    gaps, openings = [], []
    for aid, periods in sorted(boundaries.items()):
        periods.sort()
        first = periods[0]
        openings.append(
            {
                "account_id": aid,
                "statement_id": first[2],
                "date": str(date.fromisoformat(first[0]) - timedelta(days=1)),
                "amount_minor": first[3],
                "provenance": first[5],
                "status": "unposted_anchor_proposal",
            }
        )
        for earlier, later in zip(periods, periods[1:], strict=False):
            if (
                date.fromisoformat(earlier[1]) + timedelta(days=1) == date.fromisoformat(later[0])
                and earlier[4] != later[3]
            ):
                gaps.append(
                    {
                        "account_id": aid,
                        "statement_ids": [earlier[2], later[2]],
                        "difference_minor": later[3] - earlier[4],
                        "both_reported": earlier[5] == later[5] == "reported",
                    }
                )
    by_amount = defaultdict(list)
    for observation in observations:
        by_amount[(observation.currency, observation.amount_minor)].append(observation)
    candidates = []
    for decision in decisions:
        if decision["reason"] != "unconfirmed_transfer":
            continue
        key = decision["observation_id"]
        row = by_key[key]
        matches = [
            other.id
            for other in by_amount[(row["CurrencyCode"], -row["AmountMinor"])]
            if other.account_id != account_key(row["AccountID"])
            and abs((other.posting_date - date.fromisoformat(row["PostingDate"])).days) <= 7
        ]
        candidates.append({"observation_id": key, "candidate_ids": sorted(matches), "confirmed": False})
    plan = {
        "rule_version": RULE_VERSION,
        "source_namespace": namespace,
        "accounts": [asdict(a) for a in accounts],
        "observations": [{**asdict(o), "posting_date": o.posting_date.isoformat()} for o in observations],
        "statements": [s.payload() for s in statements],
        "entries": [e.payload() for e in entries],
        "decisions": decisions,
        "added_source_rows": added,
        "statement_notes": statement_notes,
        "continuity_exceptions": gaps,
        "opening_proposals": openings,
        "transfer_candidates": candidates,
        "summary": dict(Counter(d["reason"] for d in decisions)),
    }
    plan["plan_sha256"] = hashlib.sha256(encoded(plan).encode()).hexdigest()
    return plan


def apply_plan(plan: dict, store: LedgerStore) -> None:
    from parsetrail.core.ledger_store import decode_entry

    if (
        plan["rule_version"] != RULE_VERSION
        or plan["plan_sha256"]
        != hashlib.sha256(encoded({k: v for k, v in plan.items() if k != "plan_sha256"}).encode()).hexdigest()
    ):
        raise ValueError("Migration plan version/checksum mismatch.")
    accounts = [LedgerAccount(**{**r, "kind": AccountKind(r["kind"])}) for r in plan["accounts"]]
    observations = [
        Observation(**{**r, "posting_date": date.fromisoformat(r["posting_date"])}) for r in plan["observations"]
    ]
    statements = [
        StatementEvidence(
            **{
                **r,
                "start_date": date.fromisoformat(r["start_date"]),
                "end_date": date.fromisoformat(r["end_date"]),
                "observation_ids": tuple(r["observation_ids"]),
            }
        )
        for r in plan["statements"]
    ]
    entries = [decode_entry(encoded(r)) for r in plan["entries"]]
    store.load_batch(accounts, observations, statements, entries)


def reconcile_plan(plan: dict, store: LedgerStore) -> dict:
    """Read all context once; compare every statement without quadratic SQL reads."""
    from parsetrail.core.ledger_store import decode_entry

    accounts, observations, remaining = store.accounts(), store.observations(), store.evidence_remaining()
    entries = [
        decode_entry(row[0]) for row in store.connection.execute("SELECT payload FROM LedgerEntries ORDER BY key")
    ]
    superseded = {row[0] for row in store.connection.execute("SELECT original_key FROM LedgerCorrections")}
    results = {}
    for row in plan["statements"]:
        statement = StatementEvidence(
            **{
                **row,
                "start_date": date.fromisoformat(row["start_date"]),
                "end_date": date.fromisoformat(row["end_date"]),
                "observation_ids": tuple(row["observation_ids"]),
            }
        )
        results[statement.id] = evaluate_statement(statement, accounts, observations, entries, superseded, remaining)
    return {
        "plan_sha256": plan["plan_sha256"],
        "statement_results": results,
        "unallocated_observation_count": sum(amount != 0 for amount in remaining.values()),
        "reconciled_statement_count": sum(r["reconciled"] for r in results.values()),
    }


def verify_approved_preview(legacy: dict, corrections: list[dict], plan: dict, preview: dict) -> None:
    """Bind the private migration to the exact additive correction already reviewed."""
    expected = {r["statement_id"]: r for r in preview["statements"]}
    if set(expected) != {r["statement_id"] for r in corrections}:
        raise ValueError("Approved correction statement set changed.")
    rows = {r["TransactionID"]: r for r in legacy["Transactions"]}
    membership = defaultdict(list)
    for link in legacy["StatementTransactions"]:
        membership[link["StatementID"]].append(rows[link["TransactionID"]])
    for correction in corrections:
        approved = expected[correction["statement_id"]]
        added = Counter(signature(r) for r in correction["rows"]) - Counter(
            signature(r) for r in membership[correction["statement_id"]]
        )
        if (
            added != Counter(tuple(r) for r in approved["added"])
            or correction["opening_minor"] != approved["opening_minor"]
            or correction["closing_minor"] != approved["closing_minor"]
            or correction["version"] != preview["parser_version"]
        ):
            raise ValueError("Reparsed corrections differ from the approved preview.")
    gaps = sorted(
        [*r["statement_ids"], r["difference_minor"]] for r in plan["continuity_exceptions"] if r["both_reported"]
    )
    if gaps != sorted(preview["remaining_continuity_exceptions"]):
        raise ValueError("Printed continuity exceptions differ from the approved preview.")


def create_shadow(source: Path, archive: Path, output: Path, *, source_id: str, approved_preview: Path) -> dict:
    """Only use a verified disposable snapshot; retain it byte-for-byte beside the ledger."""
    source = source.resolve(strict=True)
    archive = archive.resolve(strict=True)
    output = output.resolve()
    if output.is_relative_to(archive) or source.is_relative_to(output):
        raise ValueError("Shadow output must be outside the input trees.")
    output.mkdir(parents=True, exist_ok=False)
    before = digest(source)
    # Refuse active WAL databases: the caller must supply a verified L2 restore.
    if Path(str(source) + "-wal").exists():
        raise ValueError("Use an inactive verified restore, not an active WAL database.")
    inspect_database(source)
    preserved = output / "legacy.db"
    shutil.copyfile(source, preserved)
    if digest(preserved) != before:
        raise ValueError("Input snapshot changed during copying.")
    legacy = read_legacy(preserved)
    corrections = corrected_hsa(legacy, archive)
    plan = build_plan(legacy, source_id=source_id, corrections=corrections)
    preview = json.loads(approved_preview.read_text(encoding="utf-8"))
    verify_approved_preview(legacy, corrections, plan, preview)
    # Preserve all original IDs, annotations, memberships and schema in legacy.db;
    # the sidecar plan contains only interpretations and additive source evidence.
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    (output / "source-corrections.json").write_text(json.dumps(corrections, indent=2) + "\n", encoding="utf-8")
    with LedgerStore(output / "ledger.db", create=True) as ledger:
        apply_plan(plan, ledger)
        count_before = ledger.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0]
        apply_plan(plan, ledger)
        if ledger.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0] != count_before:
            raise ValueError("Plan replay duplicated entries.")
        report = reconcile_plan(plan, ledger)
    if digest(source) != before or digest(preserved) != before:
        raise ValueError("Source snapshot changed during migration.")
    report.update(
        {
            "source_sha256": before,
            "approved_preview_sha256": digest(approved_preview),
            "ledger_sha256": digest(output / "ledger.db"),
            "corrections_sha256": digest(output / "source-corrections.json"),
            "rule_version": RULE_VERSION,
            "summary": plan["summary"],
            "added_source_row_count": len(plan["added_source_rows"]),
            "entry_count": count_before,
            "replay_unchanged": True,
            "source_unchanged": True,
        }
    )
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report

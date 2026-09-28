"""Adapt fresh cash/card evidence into the kernel and unposted journal proposals."""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date
from pathlib import Path

from parsetrail.core.ledger import (
    AccountKind,
    Allocation,
    JournalEntry,
    LedgerAccount,
    LedgerError,
    Observation,
    Posting,
    validate_entry,
)
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reconciliation import StatementEvidence
from parsetrail.core.ledger_store import LedgerStore, decode_entry, encoded
from parsetrail.core.recovery_bundle import digest

RULE = "cash-card-proposals-1"
KINDS = {"Checking": AccountKind.ASSET, "Savings": AccountKind.ASSET, "Credit Card": AccountKind.LIABILITY}
# These parsers normalize deposits as positive and card charges/debt as negative.
# Unknown formats remain outside this adapter until their sign contract is checked.
PARSER_ROLES = {
    **{
        name: {"Checking", "Savings"}
        for name in (
            "pdf_occubank_201409",
            "pdf_wfbankper_202105",
            "pdf_wfbankbus_202110",
        )
    },
    **{
        name: {"Savings"}
        for name in (
            "pdf_lendingclublus_202506",
            "pdf_lendingclubsavings_202601",
            "pdf_happenbank_202606",
        )
    },
    **{
        name: {"Credit Card"}
        for name in (
            "pdf_citicc_201505",
            "pdf_citicc_202506",
            "pdf_citicc_202511",
            "pdf_chasecc_202602",
            "pdf_occucc_201904",
            "pdf_usbankreicc_201405",
        )
    },
}


def build_candidates(rebuild: dict) -> dict:
    """Pure deterministic plan. No source mutation, posting, or review promotion."""
    evidence, metadata = rebuild["evidence"], rebuild["legacy_metadata"]
    types = {t["AccountTypeID"]: t for t in metadata["AccountTypes"]}
    source_accounts = {a["AccountID"]: a for a in metadata["Accounts"]}
    categories = {c["CategoryID"]: c for c in metadata["Categories"]}
    accounts, roles = {}, {}
    for aid, row in sorted(source_accounts.items()):
        kind = types[row["AccountTypeID"]]
        role = kind["AccountType"]
        if role not in KINDS:
            continue
        expected = "Debt" if role == "Credit Card" else "Asset"
        if kind["AssetType"] != expected:
            raise LedgerError("Source account role and asset/liability mapping disagree.")
        account = LedgerAccount(f"account:{aid}", row["AccountName"], KINDS[role], row["CurrencyCode"], str(aid))
        account.validate()
        accounts[account.id], roles[aid] = account, role
    memberships, sources_by_transaction = defaultdict(list), defaultdict(set)
    for link in evidence["memberships"]:
        statement = evidence["statements"][link["statement_id"]]
        row = evidence["transactions"][link["transaction_id"]]
        if statement["account_id"] != row["AccountID"] or statement["source"] != link["source"]:
            raise LedgerError("Source membership has inconsistent ownership.")
        memberships[statement["id"]].append(row["id"])
        sources_by_transaction[row["id"]].add(statement["id"])
    statement_decisions = {}
    for sid, row in sorted(evidence["statements"].items()):
        aid = row["account_id"]
        source = evidence["files"][row["source"]]
        tids = memberships[sid]
        if len(tids) != len(set(tids)):
            raise LedgerError("A statement repeats the same canonical observation.")
        difference = (
            row["closing_minor"] - row["opening_minor"] - sum(evidence["transactions"][t]["AmountMinor"] for t in tids)
        )
        if aid not in roles:
            status = "outside_cash_card_scope"
        elif row["status"] != "parsed" or source["status"] != "parsed":
            status = "source_review_pending"
        elif roles[aid] not in PARSER_ROLES.get(source["plugin"], set()):
            status = "source_sign_contract_pending"
        elif any(not row["start"] <= evidence["transactions"][t]["PostingDate"] <= row["end"] for t in tids):
            status = "source_date_exception"
        elif difference:
            status = "source_balance_difference"
        else:
            status = "eligible_unverified_balances"
        statement_decisions[sid] = {
            "status": status,
            "source_difference_minor": difference,
            "source": row["source"],
            "account_id": aid,
            "source_balance_provenance": row["balance_provenance"],
            "zero_amount_ids": sorted(t for t in tids if evidence["transactions"][t]["AmountMinor"] == 0),
        }
    annotations = {}
    for d in rebuild["annotations"]["decisions"]:
        if d["status"] != "restored":
            continue
        tid = d["transaction_id"]
        row = evidence["transactions"][tid]
        if tid in annotations or (d["account_id"], d["amount_minor"], d["currency"]) != (
            row["AccountID"],
            row["AmountMinor"],
            row["CurrencyCode"],
        ):
            raise LedgerError("Restored category does not uniquely belong to its source transaction.")
        if not d["legacy"]["Verified"] or categories[d["category_id"]]["Type"] != "Expense":
            raise LedgerError("Expense proposal requires preserved category verification.")
        annotations[tid] = d
    observations, entries, decisions = {}, [], []
    proposed_usage = {}
    for tid, row in sorted(evidence["transactions"].items()):
        aid, amount = row["AccountID"], row["AmountMinor"]
        links = sorted(sources_by_transaction[tid])
        if aid not in roles:
            status = "outside_cash_card_scope"
        elif not links:
            status = "missing_statement_membership"
        elif any(statement_decisions[s]["status"] != "eligible_unverified_balances" for s in links):
            status = "source_review_pending"
        elif not amount:
            status = "zero_amount_evidence"
        else:
            observation = Observation(
                f"source:{tid}", f"account:{aid}", amount, date.fromisoformat(row["PostingDate"]), row["CurrencyCode"]
            )
            observation.validate(accounts)
            observations[observation.id] = observation
            status = "needs_interpretation"
            if tid in annotations:
                category = categories[annotations[tid]["category_id"]]
                cid = f"category:{category['CategoryID']}"
                accounts.setdefault(cid, LedgerAccount(cid, category["Name"], AccountKind.EXPENSE, row["CurrencyCode"]))
                entry = JournalEntry(
                    f"proposal:{tid}",
                    f"event:{tid}",
                    observation.posting_date,
                    row["Description"],
                    (
                        Posting(observation.account_id, amount, (Allocation(observation.id, amount),)),
                        Posting(cid, -amount),
                    ),
                    reviewed=False,
                    reason="Preserved category suggests an expense/refund; accounting interpretation requires review.",
                )
                usage = validate_entry(entry, accounts, observations, proposed_usage)
                for oid, used in usage.items():
                    proposed_usage[oid] = proposed_usage.get(oid, 0) + used
                entries.append(entry.payload())
                status = "proposed_refund" if amount > 0 else "proposed_expense"
        decisions.append(
            {
                "transaction_id": tid,
                "account_id": aid,
                "amount_minor": amount,
                "status": status,
                "statement_ids": links,
                "category_id": annotations[tid]["category_id"] if tid in annotations else None,
                "category_verified": tid in annotations,
                "interpretation_reviewed": False,
            }
        )
    statements = []
    for sid, decision in statement_decisions.items():
        if decision["status"] != "eligible_unverified_balances":
            continue
        row = evidence["statements"][sid]
        nonzero = [t for t in memberships[sid] if evidence["transactions"][t]["AmountMinor"] != 0]
        if any(f"source:{t}" not in observations for t in nonzero):
            decision["status"] = "shared_evidence_review_pending"
            continue
        statement = StatementEvidence(
            f"statement:{sid}",
            f"account:{row['account_id']}",
            date.fromisoformat(row["start"]),
            date.fromisoformat(row["end"]),
            row["opening_minor"],
            row["closing_minor"],
            tuple(f"source:{t}" for t in nonzero),
            opening_provenance="assumed",
            closing_provenance="assumed",
        )
        statement.validate(accounts, observations)
        statements.append(statement.payload())
    serialized_observations = [{**asdict(o), "posting_date": o.posting_date.isoformat()} for o in observations.values()]
    return {
        "rule": RULE,
        "rebuild_hash": key(rebuild),
        "accounts": [asdict(a) for a in accounts.values()],
        "observations": serialized_observations,
        "statements": statements,
        "proposals": entries,
        "decisions": decisions,
        "statement_decisions": statement_decisions,
        "summary": dict(sorted(Counter(d["status"] for d in decisions).items())),
        "statement_summary": dict(sorted(Counter(d["status"] for d in statement_decisions.values()).items())),
        "asset_values_retained": len(rebuild.get("asset_valuations", [])),
        "journal_entries_posted": 0,
    }


def apply_candidates(store: LedgerStore, plan: dict) -> None:
    """Install evidence and immutable proposals in a disposable, unposted store.

    Kernel evidence loads atomically; proposal registration is a second transaction.
    No completion report is published until both pass. A retry is idempotent.
    """
    c = store.connection
    if plan["rule"] != RULE:
        raise LedgerError("Unsupported proposal rule.")
    if c.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0]:
        raise LedgerError("This proposal-only adapter requires an unposted ledger.")
    accounts = [LedgerAccount(**{**a, "kind": AccountKind(a["kind"])}) for a in plan["accounts"]]
    observations = [
        Observation(**{**o, "posting_date": date.fromisoformat(o["posting_date"])}) for o in plan["observations"]
    ]
    statements = [
        StatementEvidence(
            **{
                **s,
                "start_date": date.fromisoformat(s["start_date"]),
                "end_date": date.fromisoformat(s["end_date"]),
                "observation_ids": tuple(s["observation_ids"]),
            }
        )
        for s in plan["statements"]
    ]
    proposals = [decode_entry(encoded(p)) for p in plan["proposals"]]
    known_accounts, known_observations, consumed = {a.id: a for a in accounts}, {o.id: o for o in observations}, {}
    proposal_observations = {}
    for entry in proposals:
        if entry.reviewed or entry.origin != "imported":
            raise LedgerError("A generated proposal cannot claim accounting review.")
        usage = validate_entry(entry, known_accounts, known_observations, consumed)
        if (
            entry.key in proposal_observations
            or len(entry.postings) != 2
            or len(usage) != 1
            or len(entry.postings[0].allocations) != 1
            or entry.postings[1].allocations
            or known_accounts[entry.postings[1].account_id].kind != AccountKind.EXPENSE
            or next(iter(usage.values())) != known_observations[next(iter(usage))].amount_minor
        ):
            raise LedgerError("Ordinary proposals require one complete observation and one expense counterpart.")
        proposal_observations[entry.key] = next(iter(usage))
        for oid, amount in usage.items():
            consumed[oid] = consumed.get(oid, 0) + amount
    c.executescript("""
        CREATE TABLE IF NOT EXISTS JournalProposalPlans(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS JournalProposals(id TEXT PRIMARY KEY, observation_id TEXT NOT NULL UNIQUE
            REFERENCES LedgerObservations(id), payload TEXT NOT NULL);
    """)
    for table in ("JournalProposalPlans", "JournalProposals"):
        for action in ("UPDATE", "DELETE"):
            c.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_{action} BEFORE {action} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'Proposal history is immutable'); END"
            )
    store.load_batch(accounts, observations, statements, [])
    with store._transaction():
        for entry in proposals:
            oid = proposal_observations[entry.key]
            expected = (entry.key, oid, encoded(entry.payload()))
            previous = c.execute(
                "SELECT id,observation_id,payload FROM JournalProposals WHERE id=? OR observation_id=?",
                (entry.key, oid),
            ).fetchall()
            if previous:
                if previous != [expected]:
                    raise LedgerError("Existing proposal has different contents; use a reviewed revision.")
            else:
                c.execute("INSERT INTO JournalProposals VALUES(?,?,?)", expected)
        c.execute("INSERT OR IGNORE INTO JournalProposalPlans VALUES(?,?)", (key(plan), encoded(plan)))


def create_candidates(rebuild_folder: Path, output: Path) -> dict:
    """Copy a checksum-verified rebuild; never open the accepted database writable."""
    if any(
        Path(str(rebuild_folder / name) + suffix).exists()
        for name in ("fresh.db", "legacy.db")
        for suffix in ("-wal", "-shm", "-journal")
    ):
        raise LedgerError("Use an inactive accepted rebuild without database sidecars.")
    report = json.loads((rebuild_folder / "report.json").read_text(encoding="utf-8"))
    checksums = {
        "plan.json": report["plan_sha256"],
        "fresh.db": report["database_sha256"],
        "legacy.db": report["source_sha256"],
    }
    for name, expected in checksums.items():
        if digest(rebuild_folder / name) != expected:
            raise LedgerError("Accepted rebuild artifact has changed.")
    rebuild = json.loads((rebuild_folder / "plan.json").read_text(encoding="utf-8"))
    plan = build_candidates(rebuild)
    output.mkdir(parents=True, exist_ok=False)
    path = output / "candidates.db"
    shutil.copyfile(rebuild_folder / "fresh.db", path)
    if digest(path) != checksums["fresh.db"]:
        raise LedgerError("Rebuild database changed while copying.")
    with LedgerStore(path) as store:
        if store.connection.execute("SELECT version,plan_hash FROM RebuildMeta").fetchall() != [(1, key(rebuild))]:
            raise LedgerError("Rebuild database does not belong to this plan.")
        apply_candidates(store, plan)
        before = list(store.connection.iterdump())
        apply_candidates(store, plan)
        if list(store.connection.iterdump()) != before:
            raise LedgerError("Proposal replay changed the database.")
        if (
            store.connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
            or store.connection.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise LedgerError("Proposal database failed integrity checks.")
    (output / "proposals.json").write_text(encoded(plan), encoding="utf-8")
    for name, expected in checksums.items():
        if digest(rebuild_folder / name) != expected:
            raise LedgerError("Accepted source changed during candidate generation.")
    result = {
        "rule": RULE,
        "rebuild_sha256": report["plan_sha256"],
        "proposal_sha256": digest(output / "proposals.json"),
        "database_sha256": digest(path),
        "summary": plan["summary"],
        "statement_summary": plan["statement_summary"],
        "observation_count": len(plan["observations"]),
        "statement_count": len(plan["statements"]),
        "proposal_count": len(plan["proposals"]),
        "journal_entries_posted": 0,
        "source_unchanged": True,
        "replay_unchanged": True,
        "ready_for_cutover": False,
    }
    (output / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result

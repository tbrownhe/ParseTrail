"""Fresh local evidence import and conservative preservation of reviewed categories.

This is an opt-in rebuild format, not a migration of the active ORM database.
No imported evidence or category assertion authorizes a journal posting.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from parsetrail.core.ledger import AccountKind, LedgerAccount
from parsetrail.core.ledger_migration import read_legacy
from parsetrail.core.ledger_store import LedgerStore, encoded
from parsetrail.core.money import to_minor_units
from parsetrail.core.parse import parse_any
from parsetrail.core.parser_routing import ParseError
from parsetrail.core.recovery_bundle import digest, inspect_database, safe_member

RULE_VERSION = "fresh-evidence-1"


def key(value) -> str:
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def signature(row: dict) -> tuple:
    """Exact category identity; running balances may change after parser fixes."""
    return tuple(row[field] for field in ("AccountID", "PostingDate", "AmountMinor", "CurrencyCode", "Description"))


def replay_sources(legacy: dict, archive: Path, registry, progress=None) -> dict:
    """Replay referenced successful sources only; capture every source failure.

    Account-number mappings are retained explicit user mappings, never inferred
    from an institution name, amount, or a partial account-number match.
    """
    numbers = {r["AccountNumber"]: r["AccountID"] for r in legacy["AccountNumbers"]}
    accounts = {r["AccountID"]: r for r in legacy["Accounts"]}
    references = defaultdict(list)
    for row in legacy["Statements"]:
        references[row["Filename"]].append(row)
    files, statements, transactions, links = {}, {}, {}, []
    old_sources = {}
    for index, (filename, refs) in enumerate(sorted(references.items()), 1):
        if progress:
            progress(index - 1, len(references))
        safe = safe_member(filename)
        if "/" in safe:
            raise ValueError("Expected a canonical archive filename.")
        path = archive / "SUCCESS" / safe
        if not path.is_file():
            token = key(["missing", filename])
            files[token] = {
                "filename": filename,
                "status": "missing",
                "statement_ids": [r["StatementID"] for r in refs],
            }
            continue
        data_hash = digest(path)
        for ref in refs:
            if digest(path, ref["ContentHashAlgorithm"]) != ref["ContentHash"]:
                raise ValueError("Archive bytes differ from the retained statement reference.")
            old_sources[str(ref["StatementID"])] = data_hash
        if data_hash in files:
            files[data_hash]["statement_ids"].extend(r["StatementID"] for r in refs)
            continue
        record = {"filename": filename, "sha256": data_hash, "statement_ids": [r["StatementID"] for r in refs]}
        files[data_hash] = record
        try:
            result = parse_any(registry, path)
        except ParseError as exc:
            record.update(
                status="parse_failed",
                code=exc.code,
                plugin=getattr(exc, "plugin_name", None),
                diagnostics=[d.code for d in exc.diagnostics],
            )
            continue
        if digest(path) != data_hash:
            raise ValueError("Source changed during parsing.")
        record.update(
            plugin=result.plugin_name,
            version=registry.metadata[result.plugin_name]["VERSION"],
            diagnostics=[d.code for d in result.diagnostics],
        )
        parsed = result.statement
        mapped = [numbers.get(a.account_num) for a in parsed.accounts]
        record["expected_account_ids"] = sorted({r["AccountID"] for r in refs})
        record["parsed_account_ids"] = mapped
        if (
            None in mapped
            or len(set(mapped)) != len(mapped)
            or any(
                a.currency_code != accounts[aid]["CurrencyCode"] for a, aid in zip(parsed.accounts, mapped, strict=True)
            )
        ):
            record["status"] = "account_mapping_pending"
            continue
        record["status"] = "warnings_pending" if result.diagnostics else "parsed"
        if set(mapped) != set(record["expected_account_ids"]):
            record["status"] = "statement_coverage_pending"
        for account, aid in zip(parsed.accounts, mapped, strict=True):
            sid = key([data_hash, aid, parsed.start_date.isoformat(), parsed.end_date.isoformat()])
            statements[sid] = {
                "id": sid,
                "source": data_hash,
                "account_id": aid,
                "start": parsed.start_date.isoformat(),
                "end": parsed.end_date.isoformat(),
                "opening_minor": to_minor_units(account.start_balance),
                "closing_minor": to_minor_units(account.end_balance),
                "balance_provenance": "parser output; independent endpoint provenance requires review",
                "status": record["status"],
            }
            occurrences = Counter()
            for position, tx in enumerate(account.transactions):
                row = {
                    "AccountID": aid,
                    "TransactionDate": tx.transaction_date.isoformat(),
                    "PostingDate": tx.posting_date.isoformat(),
                    "AmountMinor": to_minor_units(tx.amount),
                    "BalanceMinor": to_minor_units(tx.balance),
                    "CurrencyCode": account.currency_code,
                    "Description": tx.desc,
                }
                # Exact evidence plus occurrence converges overlapping exports.
                # Annotation matching separately refuses indistinguishable rows.
                fingerprint = key(row)
                occurrence = occurrences[fingerprint]
                occurrences[fingerprint] += 1
                tid = key([fingerprint, occurrence])
                transactions.setdefault(tid, {"id": tid, **row})
                links.append({"statement_id": sid, "transaction_id": tid, "source": data_hash, "row": position})
    if progress:
        progress(len(references), len(references))
    referenced = set(references)
    unreferenced = sorted(
        p.relative_to(archive).as_posix()
        for p in archive.rglob("*")
        if p.is_file() and not (p.parent == archive / "SUCCESS" and p.name in referenced)
    )
    return {
        "files": files,
        "statements": statements,
        "transactions": transactions,
        "memberships": links,
        "legacy_sources": old_sources,
        "unreferenced_archive_files": unreferenced,
    }


def match_categories(legacy: dict, evidence: dict) -> dict:
    """Require a unique match in both directions, including unverified old rows."""
    categories = {r["CategoryID"]: r for r in legacy["Categories"]}
    source_linked = {r["TransactionID"] for r in legacy["StatementTransactions"]}
    old_links = defaultdict(set)
    for link in legacy["StatementTransactions"]:
        if source := evidence["legacy_sources"].get(str(link["StatementID"])):
            old_links[link["TransactionID"]].add(source)
    new_links = defaultdict(set)
    for link in evidence["memberships"]:
        new_links[link["transaction_id"]].add(link["source"])
    candidates = defaultdict(list)
    for tid, row in evidence["transactions"].items():
        candidates[signature(row)].append(tid)
    matches, reverse = {}, defaultdict(list)
    for old in legacy["Transactions"]:
        oid = old["TransactionID"]
        matches[oid] = sorted(
            tid
            for tid in candidates[signature(old)]
            if old_links[oid] & new_links[tid]
            and (
                old["TransactionDate"] is None
                or old["TransactionDate"] == evidence["transactions"][tid]["TransactionDate"]
            )
        )
        for tid in matches[oid]:
            reverse[tid].append(oid)
    decisions, totals = [], {}
    for old in sorted(legacy["Transactions"], key=lambda r: r["TransactionID"]):
        category = categories.get(old["CategoryID"])
        if not old["Verified"] or not category or category["Type"] != "Expense":
            continue
        oid = old["TransactionID"]
        choices = matches[oid]
        reason = "restored"
        if not old_links[oid]:
            reason = "no_available_source" if oid in source_linked else "manual_only"
        elif all(
            evidence["files"].get(s, {}).get("status")
            in {"parse_failed", "account_mapping_pending", "statement_coverage_pending"}
            for s in old_links[oid]
        ):
            reason = "source_replay_pending"
        elif not choices:
            reason = "no_exact_match"
        elif len(choices) != 1 or len(reverse[choices[0]]) != 1:
            reason = "ambiguous_match"
        elif any(evidence["files"][s]["status"] != "parsed" for s in old_links[oid] & new_links[choices[0]]):
            reason = "source_review_pending"
        decision = {
            "legacy_id": oid,
            "category_id": old["CategoryID"],
            "account_id": old["AccountID"],
            "amount_minor": old["AmountMinor"],
            "currency": old["CurrencyCode"],
            "status": reason,
            "transaction_id": choices[0] if reason == "restored" else None,
            "candidates": choices,
            "legacy": old,
            "sources": sorted(old_links[oid]),
        }
        decisions.append(decision)
        group = (old["AccountID"], old["CategoryID"], old["CurrencyCode"])
        total = totals.setdefault(
            group,
            {
                "account_id": group[0],
                "category_id": group[1],
                "currency": group[2],
                "original_count": 0,
                "original_minor": 0,
                "restored_count": 0,
                "restored_minor": 0,
                "pending_count": 0,
                "pending_minor": 0,
            },
        )
        bucket = "restored" if reason == "restored" else "pending"
        for prefix in ("original", bucket):
            total[f"{prefix}_count"] += 1
            total[f"{prefix}_minor"] += old["AmountMinor"]
    for total in totals.values():
        for suffix in ("count", "minor"):
            assert total[f"original_{suffix}"] == total[f"restored_{suffix}"] + total[f"pending_{suffix}"]
    return {
        "decisions": decisions,
        "totals": [totals[k] for k in sorted(totals)],
        "counts": dict(sorted(Counter(d["status"] for d in decisions).items())),
    }


def write_rebuild(path: Path, plan: dict) -> None:
    """New database only. Evidence and verified decisions are immutable in v1."""
    legacy, evidence, annotations = plan["legacy_metadata"], plan["evidence"], plan["annotations"]
    types = {r["AccountTypeID"]: r for r in legacy["AccountTypes"]}
    accounts = []
    for row in legacy["Accounts"]:
        kind = types[row["AccountTypeID"]]["AssetType"]
        if kind not in {"Asset", "Debt", "TangibleAsset"}:
            raise ValueError("Unknown account class requires explicit mapping.")
        accounts.append(
            LedgerAccount(
                f"account:{row['AccountID']}",
                row["AccountName"],
                AccountKind.LIABILITY if kind == "Debt" else AccountKind.ASSET,
                currency=row["CurrencyCode"],
                source_account_id=str(row["AccountID"]),
            )
        )
    with LedgerStore(path, create=True) as store:
        store.load_batch(accounts=accounts, observations=[], statements=[], entries=[])
        c = store.connection
        c.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE RebuildMeta(version INTEGER PRIMARY KEY, plan_hash TEXT NOT NULL);
            CREATE TABLE SourceFiles(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE SourceStatements(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES SourceFiles(id), payload TEXT NOT NULL);
            CREATE TABLE SourceTransactions(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE SourceMemberships(statement_id TEXT REFERENCES SourceStatements(id), row_number INTEGER,
                transaction_id TEXT NOT NULL REFERENCES SourceTransactions(id), PRIMARY KEY(statement_id,row_number));
            CREATE TABLE CategoryDefinitions(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE CategoryDecisions(legacy_id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL REFERENCES CategoryDefinitions(id),
                transaction_id TEXT UNIQUE REFERENCES SourceTransactions(id), status TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE CategoryAnnotations(transaction_id TEXT PRIMARY KEY REFERENCES SourceTransactions(id),
                category_id INTEGER NOT NULL REFERENCES CategoryDefinitions(id), verified INTEGER NOT NULL CHECK(verified=1),
                legacy_id INTEGER NOT NULL UNIQUE REFERENCES CategoryDecisions(legacy_id));
            CREATE TABLE RetainedMetadata(name TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)
        try:
            c.execute("INSERT INTO RebuildMeta VALUES(1,?)", (key(plan),))
            c.executemany(
                "INSERT INTO SourceFiles VALUES(?,?)", [(k, encoded(v)) for k, v in sorted(evidence["files"].items())]
            )
            c.executemany(
                "INSERT INTO SourceStatements VALUES(?,?,?)",
                [(k, v["source"], encoded(v)) for k, v in sorted(evidence["statements"].items())],
            )
            c.executemany(
                "INSERT INTO SourceTransactions VALUES(?,?)",
                [(k, encoded(v)) for k, v in sorted(evidence["transactions"].items())],
            )
            c.executemany(
                "INSERT INTO SourceMemberships VALUES(?,?,?)",
                [(r["statement_id"], r["row"], r["transaction_id"]) for r in evidence["memberships"]],
            )
            c.executemany(
                "INSERT INTO CategoryDefinitions VALUES(?,?)",
                [(r["CategoryID"], encoded(r)) for r in legacy["Categories"]],
            )
            c.executemany(
                "INSERT INTO CategoryDecisions VALUES(?,?,?,?,?)",
                [
                    (d["legacy_id"], d["category_id"], d["transaction_id"], d["status"], encoded(d))
                    for d in annotations["decisions"]
                ],
            )
            c.executemany(
                "INSERT INTO CategoryAnnotations VALUES(?,?,1,?)",
                [
                    (d["transaction_id"], d["category_id"], d["legacy_id"])
                    for d in annotations["decisions"]
                    if d["status"] == "restored"
                ],
            )
            c.executemany(
                "INSERT INTO RetainedMetadata VALUES(?,?)", [(k, encoded(v)) for k, v in sorted(legacy.items())]
            )
            for table in (
                "RebuildMeta",
                "SourceFiles",
                "SourceStatements",
                "SourceTransactions",
                "SourceMemberships",
                "CategoryDefinitions",
                "CategoryDecisions",
                "CategoryAnnotations",
                "RetainedMetadata",
            ):
                for action in ("UPDATE", "DELETE"):
                    c.execute(
                        f"CREATE TRIGGER {table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Rebuild evidence is immutable'); END"
                    )
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        if (
            c.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
            or c.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise ValueError("Fresh database integrity check failed.")


def create_rebuild(source: Path, archive: Path, output: Path, registry, progress=None) -> dict:
    """Build from a retained, inactive recovery snapshot, never a live profile."""
    if any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Use an inactive verified recovery snapshot.")
    inspect_database(source)
    before = digest(source)
    output.mkdir(parents=True, exist_ok=False)
    retained = output / "legacy.db"
    shutil.copyfile(source, retained)
    if digest(retained) != before:
        raise ValueError("Snapshot changed during copy.")
    legacy = read_legacy(retained)
    evidence = replay_sources(legacy, archive, registry, progress)
    annotations = match_categories(legacy, evidence)
    plan = {
        "rule": RULE_VERSION,
        "source_sha256": before,
        "parser_manifest": getattr(registry, "manifest", {}),
        "legacy_metadata": {k: v for k, v in legacy.items() if k != "StatementTransactions"},
        "evidence": evidence,
        "annotations": annotations,
    }
    (output / "plan.json").write_text(encoded(plan), encoding="utf-8")
    write_rebuild(output / "fresh.db", plan)
    if digest(source) != before or digest(retained) != before:
        raise ValueError("Source snapshot changed during rebuild.")
    for record in evidence["files"].values():
        if "sha256" in record and digest(archive / "SUCCESS" / record["filename"]) != record["sha256"]:
            raise ValueError("Archive changed during rebuild.")
    report = {
        "rule": RULE_VERSION,
        "plan_sha256": digest(output / "plan.json"),
        "database_sha256": digest(output / "fresh.db"),
        "source_unchanged": True,
        "source_sha256": before,
        "files": dict(Counter(r["status"] for r in evidence["files"].values())),
        "statements": len(evidence["statements"]),
        "transactions": len(evidence["transactions"]),
        "annotations": annotations["counts"],
        "totals": annotations["totals"],
        "unreferenced_archive_files": len(evidence["unreferenced_archive_files"]),
        "journal_entries": 0,
        "ready_for_cutover": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

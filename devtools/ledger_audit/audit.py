"""Create a read-only SQLite snapshot and audit migration evidence; never migrate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.execute("PRAGMA query_only=ON")
    return connection


def audit_connection(connection: sqlite3.Connection, *, window_days: int = 7) -> dict:
    """Only scalar SQL reads; results contain IDs/counts, never descriptions/names.

    Exact amounts in private balance exceptions are for investigation. Transfer
    candidates are heuristics and do not establish ownership or accounting truth.
    """
    if not 0 <= window_days <= 31:
        raise ValueError("Candidate window must be between 0 and 31 days.")
    integrity = connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    accounts = connection.execute(
        "SELECT a.AccountID, a.CurrencyCode, k.AssetType FROM Accounts a "
        "JOIN AccountTypes k ON k.AccountTypeID=a.AccountTypeID ORDER BY a.AccountID"
    ).fetchall()
    transactions = connection.execute(
        "SELECT t.TransactionID,t.AccountID,t.PostingDate,t.AmountMinor,t.BalanceMinor,"
        "t.CurrencyCode,t.CategoryID,t.Verified,c.Type,t.Description FROM Transactions t "
        "LEFT JOIN Categories c ON c.CategoryID=t.CategoryID ORDER BY t.TransactionID"
    ).fetchall()
    statements = connection.execute(
        "SELECT StatementID,AccountID,StartDate,EndDate,StartBalanceMinor,EndBalanceMinor,"
        "CurrencyCode,TransactionCount FROM Statements ORDER BY AccountID,StartDate,EndDate,StatementID"
    ).fetchall()
    links = connection.execute(
        "SELECT StatementID,TransactionID,StatementRow FROM StatementTransactions ORDER BY StatementID,StatementRow"
    ).fetchall()
    transaction_by_id = {row[0]: row for row in transactions}
    statement_by_id = {row[0]: row for row in statements}
    account_currency = {row[0]: row[1] for row in accounts}
    linked_by_statement = defaultdict(list)
    memberships = Counter()
    invalid_links = []
    for statement_id, transaction_id, row_number in links:
        statement, transaction = statement_by_id.get(statement_id), transaction_by_id.get(transaction_id)
        memberships[transaction_id] += 1
        if statement is None or transaction is None:
            invalid_links.append([statement_id, transaction_id, "missing_reference"])
            continue
        linked_by_statement[statement_id].append(transaction)
        if statement[1] != transaction[1] or statement[6] != transaction[5]:
            invalid_links.append([statement_id, transaction_id, "account_or_currency"])
        if row_number < 1:
            invalid_links.append([statement_id, transaction_id, "row_number"])

    balance_exceptions, count_exceptions, out_of_period = [], [], []
    by_account = defaultdict(list)
    for statement in statements:
        statement_id, account_id, start, end, opening, closing_balance, currency, count = statement
        linked = linked_by_statement[statement_id]
        total = sum(row[3] for row in linked)
        difference = closing_balance - opening - total
        if difference:
            balance_exceptions.append({"statement_id": statement_id, "difference_minor": difference})
        if count != len(linked):
            count_exceptions.append({"statement_id": statement_id, "declared": count, "linked": len(linked)})
        outside = [row[0] for row in linked if not start <= row[2] <= end]
        if outside:
            out_of_period.append({"statement_id": statement_id, "transaction_ids": outside})
        by_account[account_id].append(statement)

    coverage, continuity = [], []
    for account_id, _currency, _asset_type in accounts:
        merged = []
        previous = None
        for item in by_account[account_id]:
            start, end = date.fromisoformat(item[2]).toordinal(), date.fromisoformat(item[3]).toordinal()
            if start > end:
                raise ValueError("Invalid statement date order.")
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
            if previous is not None and start == date.fromisoformat(previous[3]).toordinal() + 1:
                difference = item[4] - previous[5]
                if difference:
                    continuity.append({"statement_ids": [previous[0], item[0]], "difference_minor": difference})
            # Only compare unambiguous immediate adjacent ranges, not overlaps.
            previous = item
        coverage.append(
            {
                "account_id": account_id,
                "intervals": [
                    [date.fromordinal(left).isoformat(), date.fromordinal(right).isoformat()] for left, right in merged
                ],
                "internal_gap_count": max(0, len(merged) - 1),
            }
        )

    # Index all possible opposite legs, not just Transfer labels; a counterpart
    # can be mislabeled. Filter account identity and dates without fuzzy money.
    index = defaultdict(list)
    for row in transactions:
        if row[3]:
            index[(row[5], row[3])].append((date.fromisoformat(row[2]).toordinal(), row[0]))
    for values in index.values():
        values.sort()
    candidate_cache = {}

    def candidates(row):
        if row[0] not in candidate_cache:
            values = index.get((row[5], -row[3]), []) if row[3] else []
            day = date.fromisoformat(row[2]).toordinal()
            lower = bisect_left(values, (day - window_days, -1))
            upper = bisect_right(values, (day + window_days, float("inf")))
            candidate_cache[row[0]] = [
                other_id for _, other_id in values[lower:upper] if transaction_by_id[other_id][1] != row[1]
            ]
        return candidate_cache[row[0]]

    transfers = [row for row in transactions if row[8] == "Transfer"]
    candidate_details = []
    for row in transfers:
        matches = candidates(row)
        reciprocal = len(matches) == 1 and candidates(transaction_by_id[matches[0]]) == [row[0]]
        candidate_details.append(
            {
                "transaction_id": row[0],
                "verified": bool(row[7]),
                "candidate_count": len(matches),
                "candidate_ids": matches[:20],
                "candidate_ids_truncated": len(matches) > 20,
                "reciprocal_unique_candidate": reciprocal,
                "opposite_category_type": transaction_by_id[matches[0]][8] if len(matches) == 1 else None,
            }
        )
    by_type = Counter(row[8] or "Uncategorized" for row in transactions)
    unlinked_markers = []
    for row in transactions:
        if memberships[row[0]]:
            continue
        description = row[9].strip().casefold()
        if description.removeprefix("manual entry: ") == "account closed manually":
            marker = "manual_account_closure"
        elif description.startswith("manual entry:"):
            marker = "manual_entry"
        else:
            marker = "unknown_origin"
        unlinked_markers.append({"transaction_id": row[0], "marker": marker})
    metadata = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    summary = {
        "integrity_ok": integrity,
        "foreign_key_violation_count": len(foreign_keys),
        "account_count": len(accounts),
        "statement_count": len(statements),
        "transaction_count": len(transactions),
        "category_type_counts": dict(sorted(by_type.items())),
        "verified_count": sum(bool(row[7]) for row in transactions),
        "verified_without_category_count": sum(bool(row[7]) and row[6] is None for row in transactions),
        "currency_count": len({row[5] for row in transactions}),
        "noninteger_money_count": sum(type(row[3]) is not int or type(row[4]) is not int for row in transactions),
        "account_currency_mismatch_count": sum(account_currency.get(row[1]) != row[5] for row in transactions),
        "unlinked_transaction_count": sum(not memberships[row[0]] for row in transactions),
        "unlinked_origin_markers": dict(sorted(Counter(row["marker"] for row in unlinked_markers).items())),
        "multiply_observed_transaction_count": sum(memberships[row[0]] > 1 for row in transactions),
        "invalid_source_link_count": len(invalid_links),
        "statement_balance_exception_count": len(balance_exceptions),
        "statement_count_exception_count": len(count_exceptions),
        "statement_out_of_period_count": len(out_of_period),
        "adjacent_statement_balance_exception_count": len(continuity),
        "accounts_without_statements": sum(not row["intervals"] for row in coverage),
        "accounts_with_internal_gaps": sum(bool(row["internal_gap_count"]) for row in coverage),
        "transfer_verified_count": sum(bool(row[7]) for row in transfers),
        "transfer_no_candidate_count": sum(row["candidate_count"] == 0 for row in candidate_details),
        "transfer_multiple_candidates_count": sum(row["candidate_count"] > 1 for row in candidate_details),
        "transfer_reciprocal_unique_candidate_count": sum(
            row["reciprocal_unique_candidate"] for row in candidate_details
        ),
    }
    return {
        "format_version": 1,
        "schema_revisions": [row[0] for row in metadata],
        "candidate_window_days": window_days,
        "summary": summary,
        "limitations": [
            "Candidate matches are not confirmed transfers or evidence of ownership.",
            "Statement equations use existing memberships; mismatches require source investigation.",
            "Coverage intervals do not prove classification, reconciliation, or account lifetime.",
            "This does not verify archive files, restore recovery, or historical parser provenance.",
        ],
        "private_findings": {
            "invalid_source_links": invalid_links,
            "statement_balance_exceptions": balance_exceptions,
            "statement_count_exceptions": count_exceptions,
            "statement_out_of_period": out_of_period,
            "adjacent_statement_balance_exceptions": continuity,
            "account_coverage": coverage,
            "transfer_candidates": candidate_details,
            "unlinked_transaction_ids": [row[0] for row in transactions if not memberships[row[0]]],
            "unlinked_origin_markers": unlinked_markers,
        },
    }


def create_audit(source: Path, output: Path, *, window_days: int = 7) -> dict:
    source = source.resolve(strict=True)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "snapshot.db"
    deadline = time.monotonic() + 60

    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise TimeoutError("Snapshot timed out; close the client and retry with a new output directory.")

    before = {
        suffix: file_hash(Path(str(source) + suffix)) for suffix in ("", "-wal") if Path(str(source) + suffix).is_file()
    }
    with closing(read_only(source)) as original, closing(sqlite3.connect(snapshot)) as target:
        original.backup(target, pages=256, progress=progress)
    digest = file_hash(snapshot)
    with closing(read_only(snapshot)) as connection:
        report = audit_connection(connection, window_days=window_days)
    if file_hash(snapshot) != digest:
        raise RuntimeError("Audit unexpectedly changed its snapshot.")
    after = {
        suffix: file_hash(Path(str(source) + suffix)) for suffix in ("", "-wal") if Path(str(source) + suffix).is_file()
    }
    report["snapshot"] = {
        "sha256": digest,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_files_unchanged_during_run": before == after,
        "audit_snapshot_unchanged": True,
    }
    (output / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New private directory; never commit its contents.")
    parser.add_argument("--window-days", type=int, choices=range(32), default=7)
    args = parser.parse_args()
    try:
        report = create_audit(args.source, args.output, window_days=args.window_days)
    except (OSError, sqlite3.Error, ValueError, RuntimeError):
        print("Audit failed. Check the source/schema and use a new private output directory. No migration ran.")
        return 1
    print(json.dumps({"summary": report["summary"], "snapshot": report["snapshot"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only statement-family comparison between current 1.x and V2 parsers.

Stdout contains aggregate counts only. Optional source-level findings use short
source hashes and must be written outside the repository. No profile is opened.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from loguru import logger
from parsetrail.core.money import to_minor_units
from parsetrail.core.parse import ParseInput, parse_any
from parsetrail.core.source_evidence import StatementPayload
from parsetrail.core.v2_pdf_routing import select_pdf_definition
from parsetrail.core.v2_source_pipeline import MAX_SOURCE_BYTES, build_source_evidence

from devtools.parser_engine_pilot.audit_full_archive import DEFAULT_DEFINITIONS, _test_signed_catalog
from devtools.v2_inventory.replay_probe import SourceRegistry

ROOT = Path(__file__).resolve().parents[2]


def _rows(statement) -> Counter[tuple[str, int, str]]:
    return Counter(
        (transaction.posting_date.isoformat(), to_minor_units(transaction.amount), " ".join(transaction.desc.split()))
        for account in statement.accounts
        for transaction in account.transactions
    )


def _evidence_rows(payload: StatementPayload, *, activity_only: bool) -> Counter[tuple[str, int, str]]:
    return Counter(
        (row.date.iso, row.amount.minor, " ".join((row.description.text or "").split()))
        for account in payload.accounts
        for row in account.rows
        if not activity_only or row.row_role == "activity"
    )


def _dated_amounts(rows: Counter[tuple[str, int, str]]) -> Counter[tuple[str, int]]:
    amounts: Counter[tuple[str, int]] = Counter()
    for (date, amount, _description), count in rows.items():
        amounts[(date, amount)] += count
    return amounts


def compare(source: bytes, *, registry, definition: bytes, legacy_parser_id: str) -> tuple[str, ...]:
    """Compare source facts, not ledger interpretation or inferred balances."""
    old_result = parse_any(registry, ParseInput(name="redacted.pdf", suffix=".pdf", data=source))
    if old_result.plugin_name != legacy_parser_id:
        return ("legacy_route_mismatch",)
    old = old_result.statement
    new = build_source_evidence(source, definition, suffix=".pdf")
    payload = new.payload
    if not isinstance(payload, StatementPayload):
        return ("not_statement",)
    reasons = []
    if len(old.accounts) != len(payload.accounts):
        reasons.append("account_count")
    if Counter(account.account_num for account in old.accounts) != Counter(
        account.source_identity for account in payload.accounts
    ):
        reasons.append("account_identity")
    if any(row.row_role != "activity" for account in payload.accounts for row in account.rows):
        reasons.append("non_activity_rows")
    old_rows = _rows(old)
    activity_rows = _evidence_rows(payload, activity_only=True)
    if old_rows != activity_rows:
        all_rows = _evidence_rows(payload, activity_only=False)
        if old_rows == all_rows:
            reasons.append("legacy_rows_now_nonactivity")
        elif _dated_amounts(old_rows) == _dated_amounts(activity_rows):
            reasons.append("descriptions")
        elif _dated_amounts(old_rows) == _dated_amounts(all_rows):
            reasons.append("legacy_amounts_include_nonactivity")
        else:
            reasons.append("dated_amount_rows")
    old_balances = Counter(
        (to_minor_units(account.start_balance), to_minor_units(account.end_balance)) for account in old.accounts
    )
    new_balances = Counter(
        (account.opening.minor, account.closing.minor)
        for account in payload.accounts
        if account.opening is not None and account.closing is not None
    )
    if old_balances != new_balances:
        reasons.append("opening_closing_values")
    if not payload.independent_balance_verified:
        arithmetic_passes = all(
            account.balance_scope == "account_total"
            and account.opening is not None
            and account.closing is not None
            and account.opening.provenance == "observed"
            and account.closing.provenance == "observed"
            and all(row.amount.provenance == "observed" for row in account.rows)
            and account.opening.minor + sum(row.amount.minor for row in account.rows) == account.closing.minor
            for account in payload.accounts
        )
        reasons.append("equation_passes_but_unverified" if arithmetic_passes else "balance_equation_unverified")
    return tuple(reasons)


def audit(
    archives: tuple[Path, ...], candidate_glob: str, *, v2_parser_id: str, legacy_parser_id: str
) -> tuple[dict, list[dict]]:
    logger.remove()
    catalog = _test_signed_catalog(DEFAULT_DEFINITIONS)
    definitions = tuple(item.content for item in catalog.definitions if item.identity.parser_id == v2_parser_id)
    if len(definitions) != 1:
        raise ValueError("v2_definition_unavailable")
    definition = definitions[0]
    registry = SourceRegistry()
    counts: Counter[str] = Counter()
    findings = []
    files = tuple(sorted(path for archive in archives for path in archive.rglob(candidate_glob)))
    for path in files:
        counts["candidate_sources"] += 1
        if path.is_symlink() or not path.is_file():
            raise ValueError("source_unavailable")
        before = path.stat()
        if not 0 < before.st_size <= MAX_SOURCE_BYTES:
            raise ValueError("source_size")
        source = path.read_bytes()
        if len(source) != before.st_size:
            raise ValueError("source_changed")
        route = select_pdf_definition(source, catalog)
        after = path.stat()
        if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
            raise ValueError("source_changed")
        if route != v2_parser_id:
            findings.append({"source": hashlib.sha256(source).hexdigest()[:16], "reasons": ("route_mismatch",)})
            counts["route_mismatch"] += 1
            continue
        counts["selected_sources"] += 1
        try:
            reasons = compare(source, registry=registry, definition=definition, legacy_parser_id=legacy_parser_id)
        except Exception as exc:
            reasons = ("comparison_error_" + type(exc).__name__,)
        after = path.stat()
        if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
            raise ValueError("source_changed")
        if reasons:
            findings.append({"source": hashlib.sha256(source).hexdigest()[:16], "reasons": reasons})
            counts.update(reasons)
        else:
            counts["exact_parity_sources"] += 1
    if not counts["candidate_sources"]:
        raise ValueError("no_candidate_sources")
    return (
        {
            "candidate_sources": counts["candidate_sources"],
            "selected_sources": counts["selected_sources"],
            "exact_parity_sources": counts["exact_parity_sources"],
            "reason_counts": {
                key: value
                for key, value in sorted(counts.items())
                if key not in {"candidate_sources", "selected_sources", "exact_parity_sources"}
            },
        },
        findings,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="append", type=Path, required=True)
    parser.add_argument("--candidate-glob", required=True, help="Archive filename pattern for the bounded family")
    parser.add_argument("--v2-parser-id", required=True)
    parser.add_argument("--legacy-parser-id", required=True)
    parser.add_argument("--private-report", type=Path)
    args = parser.parse_args(argv)
    archives = tuple(path.resolve(strict=True) for path in args.archive)
    if any(not path.is_dir() for path in archives):
        parser.error("every archive must be a directory")
    report = args.private_report.expanduser().resolve() if args.private_report else None
    if report is not None and report.is_relative_to(ROOT):
        parser.error("private report must be outside the repository")
    summary, findings = audit(
        archives, args.candidate_glob, v2_parser_id=args.v2_parser_id, legacy_parser_id=args.legacy_parser_id
    )
    print(json.dumps(summary, sort_keys=True))
    if report is not None:
        with report.open("x", encoding="utf-8") as output:
            json.dump(findings, output, indent=2)
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
